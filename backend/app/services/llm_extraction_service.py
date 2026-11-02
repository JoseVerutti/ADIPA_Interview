"""Extracción de ítems con un LLM: prompt, reintentos y autocorrección del JSON."""

import asyncio
import json
import logging
import re

from pydantic import ValidationError

from app.core.exceptions import LLMError, LLMOutputError, LLMRateLimitError
from app.schemas.extraction import RawQuestionnaire
from app.services.llm.base import LLMClient
from app.services.llm.prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMExtractionService:
    def __init__(self, client: LLMClient, max_attempts: int = 2, retry_delay_seconds: float = 1.5) -> None:
        self._client = client
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay_seconds

    @property
    def provider(self) -> str:
        return self._client.provider

    async def extract(self, document_text: str) -> RawQuestionnaire:
        """Devuelve la estructura cruda extraída o lanza ``LLMError`` si no fue posible.

        - JSON inválido: se reintenta indicando al modelo el error (autocorrección).
        - Errores transitorios (red, 5xx): se reintenta con una breve espera.
        - Cuota agotada (429) o petición rechazada: se falla de inmediato.
        """
        base_prompt = build_user_prompt(document_text)
        prompt = base_prompt
        last_error: LLMError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                raw_output = await self._client.generate_json(SYSTEM_PROMPT, prompt)
                questionnaire = parse_llm_output(raw_output)
                logger.info(
                    "LLM %s/%s extrajo %d ítems (intento %d)",
                    self._client.provider,
                    self._client.model,
                    len(questionnaire.items),
                    attempt,
                )
                return questionnaire
            except LLMRateLimitError:
                raise
            except LLMOutputError as exc:
                logger.warning("Salida del LLM inválida (intento %d): %s", attempt, exc)
                last_error = exc
                prompt = base_prompt + build_repair_prompt(str(exc))
            except LLMError as exc:
                if not exc.retryable:
                    raise
                logger.warning("Error transitorio del LLM (intento %d): %s", attempt, exc)
                last_error = exc
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_delay * attempt)

        raise LLMError(f"No se obtuvo una respuesta válida del LLM tras {self._max_attempts} intentos: {last_error}")


def parse_llm_output(raw_output: str) -> RawQuestionnaire:
    text = _CODE_FENCE_RE.sub("", raw_output.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"La respuesta no es JSON válido ({exc.msg}, posición {exc.pos}).") from exc

    if isinstance(data, list):  # algunos modelos devuelven solo la lista de ítems
        data = {"items": data}
    if not isinstance(data, dict):
        raise LLMOutputError("La respuesta debe ser un objeto JSON con la clave 'items'.")
    if "items" not in data:
        raise LLMOutputError("Falta la clave 'items' en el objeto JSON.")
    try:
        return RawQuestionnaire.model_validate(data)
    except ValidationError as exc:
        raise LLMOutputError(f"El JSON no respeta la estructura pedida: {exc.errors()[:3]}") from exc
