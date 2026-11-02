"""Orquestador del caso de uso: archivo subido → cuestionario estructurado.

Pipeline: validar archivo → extraer texto → extraer ítems (LLM, con respaldo
heurístico) → detectar idioma → normalizar y validar contra el esquema.
Nada se persiste: el documento y el resultado viven solo durante la petición.
"""

import logging
import time
from dataclasses import dataclass, field

from starlette.concurrency import run_in_threadpool

from app.core.exceptions import DocumentTooLongError, ExtractionError, LLMError, LLMRateLimitError
from app.schemas.extraction import RawQuestionnaire
from app.schemas.questionnaire import Cuestionario
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
    timings_ms: dict[str, int] = field(default_factory=dict)


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
    ) -> None:
        self._file_validator = file_validator
        self._text_extractor = text_extractor
        self._language_detector = language_detector
        self._normalizer = normalizer
        self._heuristic_extractor = heuristic_extractor
        self._llm_extractor = llm_extractor
        self._heuristic_fallback = heuristic_fallback
        self._max_text_chars = max_text_chars

    @property
    def llm_provider(self) -> str | None:
        return self._llm_extractor.provider if self._llm_extractor else None

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
        raw, method, fallback_reason = await self._extract_items(text)
        timings["item_extraction"] = _elapsed_ms(step)

        idioma = self._language_detector.detect(text)
        if idioma == UNDETERMINED and raw.idioma and len(raw.idioma.strip()) == 2:
            idioma = raw.idioma.strip().lower()

        questionnaire = self._normalizer.normalize(raw, idioma=idioma, source_name=filename or "")
        timings["total"] = _elapsed_ms(started)
        logger.info(
            "Cuestionario procesado: %d ítems, idioma=%s, método=%s, tiempos=%s",
            questionnaire.total_items,
            idioma,
            method,
            timings,
        )
        return ExtractionResult(
            questionnaire=questionnaire,
            method=method,
            provider=self.llm_provider if method == METHOD_LLM else None,
            fallback_reason=fallback_reason,
            timings_ms=timings,
        )

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
