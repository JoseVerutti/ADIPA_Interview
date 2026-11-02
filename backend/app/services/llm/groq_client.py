"""Cliente de Groq (free tier) usando su API compatible con OpenAI, en modo JSON."""

import httpx

from app.core.exceptions import LLMError
from app.services.llm.base import post_json

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClient:
    provider = "groq"

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
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = await post_json(
            GROQ_CHAT_URL,
            payload=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
            provider=self.provider,
            transport=self._transport,
        )

        choices = data.get("choices") or []
        if not choices:
            raise LLMError("groq: respuesta sin contenido")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("groq: la respuesta se truncó por exceder el máximo de tokens")
        text = (choice.get("message") or {}).get("content") or ""
        if not text.strip():
            raise LLMError("groq: respuesta vacía", retryable=True)
        return text
