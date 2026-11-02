"""Decisiones de clasificación con Jev.

Política "fail-open": cualquier error, respuesta inesperada o confianza por debajo
del umbral devuelve ``None`` y el sistema continúa con sus reglas. Jev nunca puede
hacer fallar una petición.

Las instrucciones van en inglés (idioma principal de entrenamiento de Jev) y avisan
que el contenido puede estar en español, italiano o inglés.
"""

import logging

from app.core.exceptions import ClassifierError
from app.schemas.questionnaire import TipoItem
from app.services.classification.base import TypeQuery
from app.services.classification.jev_client import JevClient

logger = logging.getLogger(__name__)

# El filtro inicial solo necesita una muestra del documento (Jev: 32k tokens por pregunta).
GATE_MAX_CHARS = 12_000

_GATE_QUESTION = {
    "type": "noul",
    "instructions": (
        "Does this document contain a questionnaire, test, quiz, exam or survey: items (questions or "
        "statements) that a respondent has to answer? The document may be written in Spanish, Italian "
        "or English."
    ),
    "criteria": {
        "true": "It contains items to answer: multiple-choice, true/false, rating-scale (Likert), "
        "matching or open-ended questions.",
        "false": "It is another kind of document (report, article, letter, invoice, notes...) with "
        "nothing for a respondent to answer.",
    },
}

_TYPE_CRITERIA: dict[TipoItem, str] = {
    TipoItem.ESCALA_LIKERT: "A statement or question rated on an ordered scale of frequency, agreement or "
    "intensity (e.g. never ... always, strongly disagree ... strongly agree). No answer is correct.",
    TipoItem.SELECCION_MULTIPLE: "A question with discrete answer options where the respondent picks the "
    "right one(s), usually exactly one correct option.",
    TipoItem.VERDADERO_FALSO: "A factual claim that the respondent must judge as true or false.",
    TipoItem.DESARROLLO: "An open-ended question or instruction answered in free text (describe, explain, "
    "why, how...).",
    TipoItem.EMPAREJAMIENTO: "An element that must be matched with one option from a shared list.",
}

# Opción "señuelo" para ítems sin alternativas: absorbe las afirmaciones de autoinforme
# ("Me siento nervioso") para que no se confundan con verdadero/falso. Si gana, no se decide.
_SELF_REPORT = "self_report"
_SELF_REPORT_CRITERIA = (
    "A statement about the respondent's own feelings, habits or opinions, meant to be rated rather "
    "than judged true or false."
)

_LANGUAGE_QUESTION = {
    "type": "choice",
    "instructions": "In which language is this document mainly written?",
    "criteria": {
        "es": "Spanish",
        "it": "Italian",
        "en": "English",
        "pt": "Portuguese",
        "fr": "French",
        "de": "German",
        "other": "Any other language",
    },
}


class JevClassifier:
    name = "jev"

    def __init__(self, client: JevClient, *, min_confidence: float = 0.6) -> None:
        self._client = client
        self._min_confidence = min_confidence

    async def questionnaire_probability(self, text: str) -> float | None:
        try:
            answers = await self._client.ask(text[:GATE_MAX_CHARS], {"is_questionnaire": _GATE_QUESTION})
        except ClassifierError as exc:
            logger.warning("Jev no disponible para el filtro inicial; se continúa sin él: %s", exc)
            return None
        value = (answers.get("is_questionnaire") or {}).get("noul")
        if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= value <= 1:
            logger.warning("Jev: respuesta inesperada en el filtro inicial: %r", answers)
            return None
        return float(value)

    async def classify_item_types(self, queries: list[TypeQuery]) -> list[TipoItem | None]:
        if not queries:
            return []
        # Una petición por ítem (recomendación de Jev: el contexto ajeno degrada la precisión),
        # ejecutadas en paralelo sobre una única conexión.
        requests = [(self._item_state(query), {"tipo": self._type_question(query)}) for query in queries]
        results = await self._client.ask_many(requests)

        decisions: list[TipoItem | None] = []
        for query, result in zip(queries, results, strict=True):
            if isinstance(result, ClassifierError):
                logger.warning("Jev no pudo clasificar un ítem; se usan las reglas: %s", result)
                decisions.append(None)
                continue
            decisions.append(self._type_decision(result.get("tipo"), query))
        return decisions

    async def detect_language(self, text: str) -> str | None:
        try:
            answers = await self._client.ask(text[:GATE_MAX_CHARS], {"idioma": _LANGUAGE_QUESTION})
        except ClassifierError as exc:
            logger.warning("Jev no disponible para detectar el idioma: %s", exc)
            return None
        choice = self._confident_choice(answers.get("idioma"))
        return choice if choice in _LANGUAGE_QUESTION["criteria"] and choice != "other" else None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _item_state(query: TypeQuery) -> dict:
        return {"item": query.enunciado, "answer_options": query.alternativas}

    @staticmethod
    def _type_question(query: TypeQuery) -> dict:
        # El orden importa (Jev favorece levemente la primera opción): va primero lo que
        # decidirían las reglas, que es la opción conservadora.
        criteria = {tipo.value: _TYPE_CRITERIA[tipo] for tipo in query.candidates}
        if not query.alternativas and TipoItem.VERDADERO_FALSO in query.candidates:
            criteria[_SELF_REPORT] = _SELF_REPORT_CRITERIA
        return {
            "type": "choice",
            "instructions": (
                "What kind of questionnaire item is this, judging by how the respondent must answer it? "
                "The item may be written in Spanish, Italian or English."
            ),
            "criteria": criteria,
        }

    def _type_decision(self, answer: dict | None, query: TypeQuery) -> TipoItem | None:
        choice = self._confident_choice(answer)
        allowed = {tipo.value: tipo for tipo in query.candidates}
        return allowed.get(choice) if choice else None

    def _confident_choice(self, answer: dict | None) -> str | None:
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            return None
        confidence = answer.get("confidence")
        if not isinstance(confidence, int | float) or confidence < self._min_confidence:
            return None
        choice = answer.get("choice")
        return choice if isinstance(choice, str) else None
