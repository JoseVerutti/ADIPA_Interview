"""Integración con Jev: cliente HTTP, clasificador, normalizador y pipeline.

Requisito clave: sin API key, o si Jev falla, el sistema funciona igual que sin Jev.
"""

import asyncio
import json

import httpx
import pytest

from app.core.exceptions import ClassifierError
from app.dependencies import build_classifier
from app.schemas.extraction import RawQuestionnaire
from app.schemas.questionnaire import TipoItem
from app.services.classification.base import ItemQuery, ItemReview, NoopClassifier
from app.services.classification.jev_classifier import JevClassifier
from app.services.classification.jev_client import JEV_URL, JevClient
from app.services.normalization_service import QuestionnaireNormalizer
from tests.conftest import FakeClassifier, FakeLLMClient
from tests.factories import SAMPLE_PDF_LINES, pdf_bytes

ENDPOINT = "/api/v1/questionnaires/extract"


def run(coro):
    return asyncio.run(coro)


def jev_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def jev_client(handler, **kwargs) -> JevClient:
    return JevClient("jev-secret", "jev-1.14.0", transport=jev_transport(handler), **kwargs)


def answers_response(answers: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"model": "jev-1.14.0", "answers": answers, "usage": {"input_tokens": 10}})


# ------------------------------------------------------------------ JevClient
def test_client_sends_documented_request_format():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return answers_response({"q": {"type": "noul", "noul": 0.9}})

    answers = run(jev_client(handler).ask("texto", {"q": {"type": "noul", "instructions": "¿?"}}))

    assert answers == {"q": {"type": "noul", "noul": 0.9}}
    request = captured[0]
    assert str(request.url) == JEV_URL
    assert request.headers["authorization"] == "Bearer jev-secret"
    payload = json.loads(request.content)
    assert payload == {
        "model": "jev-1.14.0",
        "state": "texto",
        "questions": {"q": {"type": "noul", "instructions": "¿?"}},
    }


@pytest.mark.parametrize("status", [429, 529, 503])
def test_client_retries_transient_errors(status):
    responses = [httpx.Response(status, headers={"retry-after": "0"}), answers_response({"q": {"noul": 0.5}})]
    answers = run(jev_client(lambda _: responses.pop(0)).ask("t", {"q": {}}))
    assert answers == {"q": {"noul": 0.5}}


def test_client_does_not_retry_auth_errors():
    calls = []

    def handler(_):
        calls.append(1)
        return httpx.Response(401, json={"detail": "invalid key"})

    with pytest.raises(ClassifierError) as error:
        run(jev_client(handler).ask("t", {"q": {}}))
    assert not error.value.retryable
    assert len(calls) == 1


def test_client_batch_isolates_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        state = json.loads(request.content)["state"]
        return httpx.Response(400, json={"detail": "bad"}) if state == "malo" else answers_response({"q": {"ok": 1}})

    results = run(jev_client(handler).ask_many([("bueno", {"q": {}}), ("malo", {"q": {}}), ("bueno", {"q": {}})]))

    assert results[0] == {"q": {"ok": 1}}
    assert isinstance(results[1], ClassifierError)
    assert results[2] == {"q": {"ok": 1}}


# ------------------------------------------------------------------ JevClassifier
def classifier_with(handler, min_confidence: float = 0.6) -> JevClassifier:
    return JevClassifier(jev_client(handler), min_confidence=min_confidence)


def test_gate_returns_probability():
    classifier = classifier_with(lambda _: answers_response({"is_questionnaire": {"type": "noul", "noul": 0.97}}))
    assert run(classifier.questionnaire_probability("1. ¿Pregunta?")) == 0.97


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(401),
        httpx.Response(200, json={"unexpected": True}),
        answers_response({"is_questionnaire": {"type": "noul", "noul": "alto"}}),
    ],
)
def test_gate_fails_open(response):
    classifier = JevClassifier(JevClient("k", "m", max_attempts=1, transport=jev_transport(lambda _: response)))
    assert run(classifier.questionnaire_probability("texto")) is None


def test_gate_only_sends_a_sample_of_long_documents():
    states = []

    def handler(request):
        states.append(json.loads(request.content)["state"])
        return answers_response({"is_questionnaire": {"type": "noul", "noul": 0.9}})

    run(classifier_with(handler).questionnaire_probability("x" * 50_000))
    assert len(states[0]) == 12_000


def type_answer(choice: str, confidence: float, is_item: float = 0.95) -> dict:
    return {
        "is_item": {"type": "noul", "noul": is_item},
        "tipo": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {}},
    }


SM_OR_LIKERT = (TipoItem.SELECCION_MULTIPLE, TipoItem.ESCALA_LIKERT, TipoItem.EMPAREJAMIENTO)
OPEN_OR_TF = (TipoItem.DESARROLLO, TipoItem.VERDADERO_FALSO)


def test_review_asks_both_questions_in_a_single_request():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return answers_response(type_answer("escala_likert", 0.9))

    query = ItemQuery("Disfruto aprendiendo.", ["1", "2"], SM_OR_LIKERT)
    reviews = run(classifier_with(handler).review_items([query]))

    assert len(requests) == 1
    assert set(requests[0]["questions"]) == {"is_item", "tipo"}
    assert requests[0]["state"] == {"entry": "Disfruto aprendiendo.", "answer_options": ["1", "2"]}
    assert reviews == [ItemReview(is_item_probability=0.95, tipo=TipoItem.ESCALA_LIKERT)]


def test_review_only_asks_is_item_when_structure_decides_the_type():
    questions = []

    def handler(request):
        questions.append(json.loads(request.content)["questions"])
        return answers_response({"is_item": {"type": "noul", "noul": 0.9}})

    query = ItemQuery("La Luna es una estrella.", ["Verdadero", "Falso"], (TipoItem.VERDADERO_FALSO,))
    reviews = run(classifier_with(handler).review_items([query]))

    assert list(questions[0]) == ["is_item"]
    assert reviews == [ItemReview(is_item_probability=0.9, tipo=None)]


def test_review_accepts_confident_types_only():
    replies = {
        "confiado": type_answer("escala_likert", 0.9),
        "dudoso": type_answer("escala_likert", 0.4),
        "fuera_de_candidatos": type_answer("desarrollo", 0.99),
    }

    def handler(request):
        return answers_response(replies[json.loads(request.content)["state"]["entry"]])

    queries = [ItemQuery(name, ["1", "2", "3"], SM_OR_LIKERT) for name in replies]
    reviews = run(classifier_with(handler).review_items(queries))

    assert [review.tipo for review in reviews] == [TipoItem.ESCALA_LIKERT, None, None]


def test_item_without_options_includes_self_report_decoy():
    questions = []

    def handler(request):
        questions.append(json.loads(request.content)["questions"]["tipo"])
        return answers_response(type_answer("self_report", 0.95))

    reviews = run(classifier_with(handler).review_items([ItemQuery("Me siento nervioso.", [], OPEN_OR_TF)]))

    assert list(questions[0]["criteria"]) == ["desarrollo", "verdadero_falso", "self_report"]
    assert reviews[0].tipo is None  # el señuelo no decide: se mantiene el tipo propuesto


def test_review_fails_open_per_item():
    def handler(request):
        if json.loads(request.content)["state"]["entry"] == "falla":
            return httpx.Response(400)
        return answers_response(type_answer("verdadero_falso", 0.8, is_item=0.1))

    queries = [ItemQuery(text, [], OPEN_OR_TF) for text in ("ok", "falla")]
    reviews = run(classifier_with(handler).review_items(queries))

    assert reviews == [ItemReview(is_item_probability=0.1, tipo=TipoItem.VERDADERO_FALSO), ItemReview()]


def test_detect_language():
    reply = {"idioma": {"type": "choice", "choice": "it", "confidence": 0.9}}
    assert run(classifier_with(lambda _: answers_response(reply)).detect_language("testo")) == "it"
    other = {"idioma": {"type": "choice", "choice": "other", "confidence": 0.9}}
    assert run(classifier_with(lambda _: answers_response(other)).detect_language("tekst")) is None


# ------------------------------------------------------------------ configuración
@pytest.mark.parametrize("env_var", ["JEV_API_KEY", "TYPESAFE_API_KEY"])
def test_classifier_is_enabled_by_either_env_var(monkeypatch, make_settings, env_var):
    from app.core.config import Settings

    monkeypatch.setenv(env_var, "una-key")
    assert isinstance(build_classifier(Settings(_env_file=None)), JevClassifier)


def test_without_key_the_classifier_is_a_noop(make_settings):
    assert isinstance(build_classifier(make_settings()), NoopClassifier)


# ------------------------------------------------------------------ normalizador
def raw(items: list[dict]) -> RawQuestionnaire:
    return RawQuestionnaire.model_validate({"titulo": "T", "items": items})


def test_every_item_is_queried_with_the_types_its_structure_allows():
    questionnaire = raw([
        {"enunciado": "¿Capital de Chile?", "alternativas": ["Lima", "Santiago"]},             # 0
        {"enunciado": "Me siento", "alternativas": ["Nunca", "A veces", "Siempre"]},          # 1
        {"enunciado": "La Luna es una estrella.", "alternativas": ["Verdadero", "Falso"]},    # 2
        {"enunciado": "El sol es una estrella."},                                             # 3
        {"enunciado": "Perú", "tipo": "emparejamiento", "alternativas": ["Lima", "Quito"]},   # 4
        {"enunciado": "   "},                                                                 # 5: sin enunciado
    ])  # fmt: skip

    queries = QuestionnaireNormalizer().item_queries(questionnaire)

    assert set(queries) == {0, 1, 2, 3, 4}
    # El primer candidato es el tipo propuesto por el extractor o por las reglas.
    assert queries[0].candidates == (TipoItem.SELECCION_MULTIPLE, TipoItem.ESCALA_LIKERT, TipoItem.EMPAREJAMIENTO)
    assert queries[1].candidates == (TipoItem.ESCALA_LIKERT, TipoItem.SELECCION_MULTIPLE, TipoItem.EMPAREJAMIENTO)
    assert queries[2].candidates == (TipoItem.VERDADERO_FALSO,)  # Verdadero/Falso: nada que elegir
    assert queries[3].candidates == (TipoItem.DESARROLLO, TipoItem.VERDADERO_FALSO)
    assert queries[4].candidates[0] is TipoItem.EMPAREJAMIENTO


def test_classifier_decisions_override_the_proposed_type():
    questionnaire = raw([
        {"enunciado": "Disfruto aprendiendo.", "alternativas": ["1", "2", "3", "4", "5"]},
        {"enunciado": "El sol es una estrella."},
    ])  # fmt: skip
    normalizer = QuestionnaireNormalizer()

    by_rules = normalizer.normalize(questionnaire, idioma="es", source_name="x.pdf")
    by_classifier = normalizer.normalize(
        questionnaire,
        idioma="es",
        source_name="x.pdf",
        type_decisions={0: TipoItem.ESCALA_LIKERT, 1: TipoItem.VERDADERO_FALSO},
    )

    assert [item.tipo for item in by_rules.items] == [TipoItem.SELECCION_MULTIPLE, TipoItem.DESARROLLO]
    assert [item.tipo for item in by_classifier.items] == [TipoItem.ESCALA_LIKERT, TipoItem.VERDADERO_FALSO]
    assert [a.valor for a in by_classifier.items[0].alternativas] == [1, 2, 3, 4, 5]
    assert [a.valor for a in by_classifier.items[1].alternativas] == ["V", "F"]


def test_excluded_entries_are_dropped():
    questionnaire = raw([
        {"numero": 1, "enunciado": "Nombre:"},
        {"numero": 2, "enunciado": "Describa su día.", "tipo": "desarrollo"},
    ])  # fmt: skip
    result = QuestionnaireNormalizer().normalize(questionnaire, idioma="es", source_name="x.pdf", excluded={0})

    assert [(item.numero, item.enunciado) for item in result.items] == [(2, "Describa su día.")]


# ------------------------------------------------------------------ pipeline / API
def upload(client, lines=SAMPLE_PDF_LINES):
    return client.post(ENDPOINT, files={"file": ("doc.pdf", pdf_bytes(lines), "application/pdf")})


def llm_output_of(example: dict) -> dict:
    return {key: value for key, value in example.items() if key != "total_items"}


def test_gate_rejects_non_questionnaires_without_calling_the_llm(make_client):
    llm = FakeLLMClient()  # sin respuestas: si se llamara, fallaría
    classifier = FakeClassifier(probability=0.02)

    response = upload(make_client(llm, classifier))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_items_detected"
    assert llm.prompts == []


def test_classifier_reviews_every_item_extracted_by_the_llm(make_client, spec_example):
    classifier = FakeClassifier(probability=0.95)

    response = upload(make_client(FakeLLMClient(llm_output_of(spec_example)), classifier))

    assert response.status_code == 200
    assert response.json() == spec_example
    assert response.headers["X-Classifier"] == "fake-jev"
    assert classifier.calls == ["gate", "items"]
    statements = [item["enunciado"] for item in spec_example["items"]]
    assert [query.enunciado for query in classifier.item_queries] == statements


def test_classifier_type_wins_over_the_llm_type(make_client, spec_example):
    statement = spec_example["items"][0]["enunciado"]  # Likert según el LLM
    classifier = FakeClassifier(probability=0.95, item_types={statement: TipoItem.SELECCION_MULTIPLE})

    response = upload(make_client(FakeLLMClient(llm_output_of(spec_example)), classifier))

    first = response.json()["items"][0]
    assert first["tipo"] == "seleccion_multiple"
    assert [a["valor"] for a in first["alternativas"]] == ["A", "B", "C", "D"]


def test_classifier_drops_entries_that_are_not_items(make_client):
    lines = ["Evaluación", "1. Nombre del estudiante", "2. ¿Por qué estudias?", "3. ¿Qué te motiva?"]
    classifier = FakeClassifier(probability=0.9, non_items={"Nombre del estudiante"})

    response = upload(make_client(classifier=classifier), lines)

    assert response.status_code == 200
    assert [item["enunciado"] for item in response.json()["items"]] == ["¿Por qué estudias?", "¿Qué te motiva?"]


def test_exclusions_never_empty_the_questionnaire(make_client):
    lines = ["Ficha", "1. Nombre del estudiante", "2. Curso"]
    classifier = FakeClassifier(probability=0.9, non_items={"Nombre del estudiante", "Curso"})

    response = upload(make_client(classifier=classifier), lines)

    assert response.status_code == 200  # fail-open: el clasificador nunca deja el resultado vacío
    assert response.json()["total_items"] == 2


def test_classifier_resolves_heuristic_items(make_client):
    lines = ["Repaso", "1. El sol es una estrella.", "2. ¿Por qué estudias?"]
    classifier = FakeClassifier(probability=0.9, item_types={"El sol es una estrella.": TipoItem.VERDADERO_FALSO})

    response = upload(make_client(classifier=classifier), lines)

    assert response.status_code == 200
    assert [item["tipo"] for item in response.json()["items"]] == ["verdadero_falso", "desarrollo"]


def test_classifier_without_answers_keeps_rule_based_behaviour(make_client, spec_example):
    classifier = FakeClassifier()
    classifier.review_items = NoopClassifier().review_items  # sin decisiones de ningún tipo

    response = upload(make_client(classifier=classifier))

    assert response.status_code == 200
    assert response.json() == spec_example


def test_without_jev_key_the_header_reports_rules(make_client):
    response = upload(make_client())
    assert response.status_code == 200
    assert response.headers["X-Classifier"] == "rules"


def test_client_lists_models():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer jev-secret"
        # Formato real de la API (verificado): solo alias, con la clave "name".
        return httpx.Response(200, json={"models": [{"name": "jev-latest"}, {"name": "jev-preview"}]})

    assert run(jev_client(handler).list_models()) == ["jev-latest", "jev-preview"]


def test_items_sharing_options_are_sent_as_context():
    capitals = ["Montevideo", "Lima", "Quito"]
    questionnaire = raw([
        {"enunciado": "Perú", "alternativas": capitals},
        {"enunciado": "Uruguay", "alternativas": capitals},
        {"enunciado": "Ecuador", "alternativas": capitals},
        {"enunciado": "¿2+2?", "alternativas": ["3", "4"]},
    ])  # fmt: skip

    queries = QuestionnaireNormalizer().item_queries(questionnaire)

    assert queries[0].siblings == ["Uruguay", "Ecuador"]
    assert queries[3].siblings == []


def test_siblings_are_included_in_the_jev_state():
    states = []

    def handler(request):
        states.append(json.loads(request.content)["state"])
        return answers_response(type_answer("emparejamiento", 0.8))

    query = ItemQuery("Perú", ["Montevideo", "Lima"], SM_OR_LIKERT, ["Uruguay", "Ecuador"])
    reviews = run(classifier_with(handler).review_items([query]))

    assert states[0]["other_entries_sharing_these_options"] == ["Uruguay", "Ecuador"]
    assert reviews[0].tipo is TipoItem.EMPAREJAMIENTO
