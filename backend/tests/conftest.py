import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.dependencies import build_questionnaire_service, get_questionnaire_service
from app.main import create_app


class FakeLLMClient:
    """Cliente LLM falso: devuelve (o lanza) las respuestas configuradas, en orden."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, *responses: str | dict | Exception) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def generate_json(self, system_prompt: str, user_prompt: str) -> str:
        self.prompts.append(user_prompt)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides) -> Settings:
        values = {"llm_provider": "none", "heuristic_fallback": True} | overrides
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def make_client(make_settings) -> Callable[..., TestClient]:
    def _make(llm_client=None, **overrides) -> TestClient:
        settings = make_settings(**overrides)
        app = create_app(settings)
        service = build_questionnaire_service(settings, llm_client)
        app.dependency_overrides[get_questionnaire_service] = lambda: service
        app.dependency_overrides[get_settings] = lambda: settings
        return TestClient(app)

    return _make


@pytest.fixture
def spec_example() -> dict:
    """El ejemplo de salida del enunciado de la prueba."""
    return {
        "titulo": "Questionario di esempio",
        "idioma": "it",
        "total_items": 3,
        "items": [
            {
                "numero": 1,
                "enunciado": "Mi preoccupo eccessivamente per cose di poca importanza.",
                "tipo": "escala_likert",
                "alternativas": [
                    {"valor": 0, "texto": "Mai"},
                    {"valor": 1, "texto": "A volte"},
                    {"valor": 2, "texto": "Spesso"},
                    {"valor": 3, "texto": "Sempre"},
                ],
                "respuesta_correcta": None,
            },
            {
                "numero": 2,
                "enunciado": "Quale numero completa la serie: 2, 4, 8, 16, ...?",
                "tipo": "seleccion_multiple",
                "alternativas": [
                    {"valor": "A", "texto": "18"},
                    {"valor": "B", "texto": "24"},
                    {"valor": "C", "texto": "32"},
                ],
                "respuesta_correcta": "C",
            },
            {
                "numero": 3,
                "enunciado": "Descriva una situazione recente in cui si è sentito sotto pressione.",
                "tipo": "desarrollo",
                "alternativas": [],
                "respuesta_correcta": None,
            },
        ],
    }
