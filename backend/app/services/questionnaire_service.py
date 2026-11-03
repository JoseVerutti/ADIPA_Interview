"""Orquestador del caso de uso: archivo subido → cuestionario estructurado.

Pipeline: validar archivo → extraer texto → filtro "¿es un cuestionario?" (clasificador)
→ extraer ítems (LLM, con respaldo heurístico) → revisar cada ítem con el clasificador
(¿es un ítem real? ¿de qué tipo?) → idioma → normalizar y validar contra el esquema.

Las decisiones de clasificación las toma el clasificador (Jev). El LLM estructura el
contenido y propone un tipo en la misma llamada, que solo se usa como respaldo cuando
el clasificador no está configurado, falla o no tiene una decisión con confianza.
Sin clasificador configurado el pipeline se comporta exactamente igual que antes.
Nada se persiste: el documento y el resultado viven solo durante la petición.
"""

import logging
import re
import time
from dataclasses import dataclass, field

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import (
    DocumentTooLongError,
    ExtractionError,
    LLMError,
    LLMRateLimitError,
    NoItemsDetectedError,
)
from app.schemas.extraction import RawQuestionnaire
from app.schemas.questionnaire import Cuestionario, TipoItem
from app.services.classification.base import Classifier, NoopClassifier
from app.services.file_validation_service import FileValidationService
from app.services.heuristic_extraction_service import HeuristicExtractionService
from app.services.language_detection_service import UNDETERMINED, LanguageDetectionService
from app.services.llm_extraction_service import LLMExtractionService
from app.services.normalization_service import QuestionnaireNormalizer
from app.services.text_extraction_service import TextExtractionService

logger = logging.getLogger(__name__)

METHOD_LLM = "llm"
METHOD_HEURISTIC = "heuristic"


@dataclass
class ExtractionResult:
    questionnaire: Cuestionario
    method: str
    provider: str | None = None
    fallback_reason: str | None = None
    classifier: str | None = None
    classifier_decisions: int = 0
    type_corrections: int = 0
    items_excluded: int = 0
    timings_ms: dict[str, int] = field(default_factory=dict)


@dataclass
class _ItemsReview:
    type_decisions: dict[int, TipoItem] = field(default_factory=dict)
    excluded: set[int] = field(default_factory=set)
    type_corrections: int = 0


class QuestionnaireService:
    def __init__(
        self,
        *,
        file_validator: FileValidationService,
        text_extractor: TextExtractionService,
        language_detector: LanguageDetectionService,
        normalizer: QuestionnaireNormalizer,
        heuristic_extractor: HeuristicExtractionService,
        llm_extractor: LLMExtractionService | None,
        heuristic_fallback: bool,
        max_text_chars: int,
        classifier: Classifier | None = None,
        gate_threshold: float = 0.1,
        item_threshold: float = 0.2,
    ) -> None:
        self._file_validator = file_validator
        self._text_extractor = text_extractor
        self._language_detector = language_detector
        self._normalizer = normalizer
        self._heuristic_extractor = heuristic_extractor
        self._llm_extractor = llm_extractor
        self._heuristic_fallback = heuristic_fallback
        self._max_text_chars = max_text_chars
        self._classifier: Classifier = classifier or NoopClassifier()
        self._gate_threshold = gate_threshold
        self._item_threshold = item_threshold

    @property
    def llm_provider(self) -> str | None:
        return self._llm_extractor.provider if self._llm_extractor else None

    @property
    def classifier_name(self) -> str | None:
        return self._classifier.name

    async def process(self, filename: str | None, content: bytes) -> ExtractionResult:
        timings: dict[str, int] = {}
        started = time.perf_counter()

        kind = self._file_validator.validate(filename, content)
        # La extracción de texto es CPU-bound y síncrona: se saca del event loop.
        text = await run_in_threadpool(self._text_extractor.extract, kind, content)
        timings["text_extraction"] = _elapsed_ms(started)
        logger.info("Texto extraído de %s (%s): %d caracteres", filename, kind.value, len(text))

        if len(text) > self._max_text_chars:
            raise DocumentTooLongError(
                f"El documento es demasiado extenso ({len(text):,} caracteres; máximo "
                f"{self._max_text_chars:,}). Divídelo en partes más pequeñas."
            )

        step = time.perf_counter()
        await self._check_is_questionnaire(text)
        timings["gate"] = _elapsed_ms(step)

        step = time.perf_counter()
        raw, method, fallback_reason = await self._extract_items(text)
        timings["item_extraction"] = _elapsed_ms(step)

        step = time.perf_counter()
        review = await self._review_items(raw)
        idioma = await self._detect_language(text, raw)
        timings["classification"] = _elapsed_ms(step)

        questionnaire = self._normalizer.normalize(
            raw,
            idioma=idioma,
            source_name=filename or "",
            type_decisions=review.type_decisions,
            excluded=review.excluded,
        )
        timings["total"] = _elapsed_ms(started)
        logger.info(
            "Cuestionario procesado: %d ítems, idioma=%s, método=%s, clasificador=%s "
            "(%d tipos decididos, %d corregidos, %d entradas descartadas), tiempos=%s",
            questionnaire.total_items,
            idioma,
            method,
            self._classifier.name or "reglas",
            len(review.type_decisions),
            review.type_corrections,
            len(review.excluded),
            timings,
        )
        return ExtractionResult(
            questionnaire=questionnaire,
            method=method,
            provider=self.llm_provider if method == METHOD_LLM else None,
            fallback_reason=fallback_reason,
            classifier=self._classifier.name,
            classifier_decisions=len(review.type_decisions),
            type_corrections=review.type_corrections,
            items_excluded=len(review.excluded),
            timings_ms=timings,
        )

    async def _check_is_questionnaire(self, text: str) -> None:
        """Filtro previo: evita gastar una llamada al LLM en documentos que no son cuestionarios."""
        probability = await self._classifier.questionnaire_probability(text)
        if probability is None:
            return
        logger.info("Clasificador: probabilidad de que sea un cuestionario = %.3f", probability)
        if probability < self._gate_threshold:
            raise NoItemsDetectedError(
                "El documento no parece contener un cuestionario: no se encontraron preguntas ni "
                "afirmaciones para responder."
            )

    async def _review_items(self, raw: RawQuestionnaire) -> _ItemsReview:
        """El clasificador revisa cada ítem: decide su tipo y si es realmente un ítem.

        Un tipo solo se aplica si el clasificador lo decidió con confianza; si no, queda el
        que propone el extractor. Una entrada se descarta si su probabilidad de ser un ítem
        es menor que ``item_threshold``, salvo que eso dejara el cuestionario vacío.
        """
        result = _ItemsReview()
        queries = self._normalizer.item_queries(raw)
        if not queries:
            return result
        reviews = await self._classifier.review_items(list(queries.values()))

        for (index, query), review in zip(queries.items(), reviews, strict=True):
            if review.is_item_probability is not None and review.is_item_probability < self._item_threshold:
                result.excluded.add(index)
            if review.tipo is not None:
                result.type_decisions[index] = review.tipo
                if review.tipo is not query.candidates[0]:
                    result.type_corrections += 1
                    logger.info(
                        "Clasificador: tipo de '%s' corregido de %s a %s",
                        query.enunciado[:60],
                        query.candidates[0].value,
                        review.tipo.value,
                    )

        if result.excluded and len(result.excluded) == len(queries):
            logger.warning("El clasificador descartaría todas las entradas; se conservan (fail-open).")
            result.excluded.clear()
        return result

    async def _detect_language(self, text: str, raw: RawQuestionnaire) -> str:
        """Detector determinístico → idioma propuesto por el LLM (sin costo extra) → clasificador → 'und'."""
        idioma = self._language_detector.detect(text)
        if idioma != UNDETERMINED:
            return idioma
        if raw.idioma and re.fullmatch(r"[a-zA-Z]{2}", raw.idioma.strip()):
            return raw.idioma.strip().lower()
        return await self._classifier.detect_language(text) or UNDETERMINED

    async def _extract_items(self, text: str) -> tuple[RawQuestionnaire, str, str | None]:
        if self._llm_extractor is not None:
            try:
                return await self._llm_extractor.extract(text), METHOD_LLM, None
            except LLMError as exc:
                if not self._heuristic_fallback:
                    logger.error("Falló la extracción con LLM y el respaldo está deshabilitado: %s", exc)
                    raise ExtractionError(
                        "El servicio de inteligencia artificial no está disponible en este momento. "
                        "Inténtalo de nuevo en unos minutos."
                    ) from exc
                logger.warning("Falló la extracción con LLM; se usa el extractor heurístico: %s", exc)
                reason = "llm_rate_limited" if isinstance(exc, LLMRateLimitError) else "llm_error"
        else:
            if not self._heuristic_fallback:
                raise ExtractionError("No hay un proveedor LLM configurado en el servidor.")
            reason = "llm_not_configured"

        raw = await run_in_threadpool(self._heuristic_extractor.extract, text)
        return raw, METHOD_HEURISTIC, reason


def _elapsed_ms(since: float) -> int:
    return round((time.perf_counter() - since) * 1000)
