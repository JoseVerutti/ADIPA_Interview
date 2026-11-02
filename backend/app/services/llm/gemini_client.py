"""Cliente de Google Gemini (AI Studio, free tier) vía REST con salida JSON estructurada."""

import httpx

from app.core.exceptions import LLMError
from app.services.llm.base import post_json
from app.services.llm.prompts import GEMINI_RESPONSE_SCHEMA

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiClient:
    provider = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._transport = transport

    async def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_RESPONSE_SCHEMA,
            },
        }
        data = await post_json(
            f"{GEMINI_BASE_URL}/models/{self.model}:generateContent",
            payload=payload,
            # La key va en cabecera (no en la URL) para que no aparezca en logs de acceso.
            headers={"x-goog-api-key": self._api_key},
            timeout=self._timeout,
            provider=self.provider,
            transport=self._transport,
        )

        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "desconocido")
            raise LLMError(f"gemini: respuesta sin candidatos (bloqueo: {reason})")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        if finish_reason == "MAX_TOKENS":
            raise LLMError("gemini: la respuesta se truncó por exceder el máximo de tokens")
        if not text.strip():
            raise LLMError(f"gemini: respuesta vacía (finishReason={finish_reason})", retryable=True)
        return text
