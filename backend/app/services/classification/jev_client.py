"""Cliente HTTP de Jev (TypeSafe AI "System One"): POST /v1/systemone.

Formato (docs.typesafe.ai/api/system-one):
    request : {"model": ..., "state": <texto|objeto|lista>, "questions": {nombre: pregunta}}
    response: {"model": ..., "answers": {nombre: respuesta}, "usage": {...}}
Tipos de pregunta usados: "noul" (sí/no → probabilidad) y "choice" (una etiqueta + confianza).
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.exceptions import ClassifierError

logger = logging.getLogger(__name__)

JEV_URL = "https://api.typesafe.ai/v1/systemone"
_RETRYABLE_STATUS = {429, 529}
_MAX_RETRY_DELAY_SECONDS = 2.0

JevRequest = tuple[Any, dict[str, dict]]


class JevClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 10,
        max_attempts: int = 2,
        max_concurrency: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._max_concurrency = max_concurrency
        self._transport = transport

    async def ask(self, state: Any, questions: dict[str, dict]) -> dict[str, dict]:
        """Una petición; lanza ``ClassifierError`` si falla."""
        result = (await self.ask_many([(state, questions)]))[0]
        if isinstance(result, ClassifierError):
            raise result
        return result

    async def ask_many(self, requests: Sequence[JevRequest]) -> list[dict[str, dict] | ClassifierError]:
        """Varias peticiones en paralelo (con concurrencia acotada) sobre una sola conexión.

        Devuelve, en el mismo orden, las respuestas o el error de cada una: un fallo
        aislado no invalida las demás.
        """
        semaphore = asyncio.Semaphore(self._max_concurrency)
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as http:

            async def run(state: Any, questions: dict[str, dict]) -> dict[str, dict] | ClassifierError:
                async with semaphore:
                    try:
                        return await self._post(http, state, questions)
                    except ClassifierError as exc:
                        return exc

            return list(await asyncio.gather(*(run(state, questions) for state, questions in requests)))

    async def _post(self, http: httpx.AsyncClient, state: Any, questions: dict[str, dict]) -> dict[str, dict]:
        payload = {"model": self.model, "state": state, "questions": questions}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(1, self._max_attempts + 1):
            delay = 0.5 * attempt
            try:
                response = await http.post(JEV_URL, json=payload, headers=headers)
            except httpx.TimeoutException:
                error = ClassifierError("jev: tiempo de espera agotado", retryable=True)
            except httpx.HTTPError as exc:
                error = ClassifierError(f"jev: error de red ({exc.__class__.__name__})", retryable=True)
            else:
                if response.status_code == 200:
                    return _answers(response)
                retryable = response.status_code in _RETRYABLE_STATUS or response.status_code >= 500
                error = ClassifierError(f"jev: HTTP {response.status_code}: {response.text[:200]}", retryable=retryable)
                delay = _retry_after(response) or delay

            if not error.retryable or attempt == self._max_attempts:
                raise error
            logger.info("Jev: reintento %d tras error transitorio: %s", attempt, error)
            await asyncio.sleep(min(delay, _MAX_RETRY_DELAY_SECONDS))
        raise AssertionError("unreachable")  # pragma: no cover


def _answers(response: httpx.Response) -> dict[str, dict]:
    try:
        data = response.json()
    except ValueError as exc:
        raise ClassifierError("jev: la respuesta no es JSON") from exc
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise ClassifierError("jev: la respuesta no contiene 'answers'")
    usage = data.get("usage") or {}
    logger.debug("Jev %s: %s tokens de entrada", data.get("model"), usage.get("input_tokens"))
    return answers


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
