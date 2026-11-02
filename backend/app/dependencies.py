"""Construcción de servicios (composition root) para la inyección de dependencias de FastAPI."""

import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.services.classification.base import Classifier, NoopClassifier
from app.services.classification.jev_classifier import JevClassifier
from app.services.classification.jev_client import JevClient
from app.services.file_validation_service import FileValidationService
from app.services.heuristic_extraction_service import HeuristicExtractionService
from app.services.language_detection_service import LanguageDetectionService
from app.services.llm.base import LLMClient
from app.services.llm.gemini_client import GeminiClient
from app.services.llm.groq_client import GroqClient
from app.services.llm_extraction_service import LLMExtractionService
from app.services.normalization_service import QuestionnaireNormalizer
from app.services.questionnaire_service import QuestionnaireService
from app.services.text_extraction_service import TextExtractionService

logger = logging.getLogger(__name__)


def build_llm_client(settings: Settings) -> LLMClient | None:
    if settings.llm_provider == "gemini" and settings.gemini_api_key:
        return GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
    if settings.llm_provider == "groq" and settings.groq_api_key:
        return GroqClient(settings.groq_api_key, settings.groq_model, settings.llm_timeout_seconds)
    if settings.llm_provider != "none":
        logger.warning(
            "LLM_PROVIDER=%s pero falta su API key: se usará solo el extractor heurístico.",
            settings.llm_provider,
        )
    return None


def build_classifier(settings: Settings) -> Classifier:
    if not settings.jev_api_key:
        logger.info("Sin JEV_API_KEY: las decisiones de clasificación se toman solo con reglas.")
        return NoopClassifier()
    client = JevClient(
        settings.jev_api_key,
        settings.jev_model,
        timeout=settings.jev_timeout_seconds,
        max_concurrency=settings.jev_max_concurrency,
    )
    return JevClassifier(client, min_confidence=settings.jev_min_confidence)


def build_questionnaire_service(
    settings: Settings,
    llm_client: LLMClient | None = None,
    classifier: Classifier | None = None,
) -> QuestionnaireService:
    client = llm_client if llm_client is not None else build_llm_client(settings)
    return QuestionnaireService(
        classifier=classifier if classifier is not None else build_classifier(settings),
        gate_threshold=settings.jev_gate_threshold,
        file_validator=FileValidationService(settings.max_file_size_bytes),
        text_extractor=TextExtractionService(),
        language_detector=LanguageDetectionService(),
        normalizer=QuestionnaireNormalizer(),
        heuristic_extractor=HeuristicExtractionService(),
        llm_extractor=LLMExtractionService(client, settings.llm_max_attempts) if client else None,
        heuristic_fallback=settings.heuristic_fallback,
        max_text_chars=settings.max_text_chars,
    )


@lru_cache
def get_questionnaire_service() -> QuestionnaireService:
    return build_questionnaire_service(get_settings())
