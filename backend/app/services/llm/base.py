"""Contrato común de los clientes LLM y utilidades compartidas."""

from typing import Protocol

import httpx

from app.core.exceptions import LLMError, LLMRateLimitError


class LLMClient(Protocol):
    provider: str
    model: str

    async def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        """Devuelve el texto (JSON) generado por el modelo o lanza ``LLMError``."""
        ...


async def post_json(
    url: str,
    *,
    payload: dict,
    headers: dict[str, str],
    timeout: float,
    provider: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict:
    """POST con traducción uniforme de errores de red y HTTP a ``LLMError``."""
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as exc:
        raise LLMError(f"{provider}: tiempo de espera agotado", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"{provider}: error de red ({exc.__class__.__name__})", retryable=True) from exc

    if response.status_code == 429:
        raise LLMRateLimitError(f"{provider}: límite de cuota o de tasa alcanzado (HTTP 429)")
    if response.status_code >= 500:
        raise LLMError(f"{provider}: error del proveedor (HTTP {response.status_code})", retryable=True)
    if response.status_code >= 400:
        # El cuerpo de error de los proveedores no incluye la API key; se recorta por prudencia.
        raise LLMError(f"{provider}: petición rechazada (HTTP {response.status_code}): {response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError(f"{provider}: la respuesta HTTP no es JSON") from exc
