import json
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.dependencies import build_questionnaire_service, get_questionnaire_service
from app.main import create_app
from app.services.classification.base import ItemReview


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


class FakeClassifier:
    """Clasificador falso con respuestas fijas; registra las llamadas recibidas."""

    name = "fake-jev"

    def __init__(self, *, probability=None, item_types=None, non_items=(), language=None) -> None:
        self.probability = probability
        self.item_types = item_types or {}  # enunciado -> TipoItem
        self.non_items = set(non_items)  # enunciados que "no son ítems"
        self.language = language
        self.calls: list[str] = []
        self.item_queries = []

    async def questionnaire_probability(self, text):
        self.calls.append("gate")
        return self.probability

    async def review_items(self, queries):
        self.calls.append("items")
        self.item_queries.extend(queries)
        return [
            ItemReview(
                is_item_probability=0.05 if query.enunciado in self.non_items else 0.95,
                tipo=self.item_types.get(query.enunciado),
            )
            for query in queries
        ]

    async def detect_language(self, text):
        self.calls.append("language")
        return self.language


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides) -> Settings:
        # Sin keys explícitamente: los tests nunca deben llamar a servicios externos reales.
        values = {"gemini_api_key": None, "heuristic_fallback": True, "jev_api_key": None} | overrides
        return Settings(_env_file=None, **values)

    return _make


@pytest.fixture
def make_client(make_settings) -> Callable[..., TestClient]:
    def _make(llm_client=None, classifier=None, **overrides) -> TestClient:
        settings = make_settings(**overrides)
        app = create_app(settings)
        service = build_questionnaire_service(settings, llm_client, classifier)
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
