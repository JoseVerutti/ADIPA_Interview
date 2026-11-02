"""Normalización de la estructura cruda al esquema estandarizado ``Cuestionario``.

Aplica reglas deterministas para que la salida sea consistente sin importar si
vino del LLM o del extractor heurístico:
- tipos con sinónimos → tipo canónico (o inferido a partir de las alternativas),
- selección múltiple / emparejamiento → valores en letras mayúsculas (A, B, C…),
- verdadero/falso → valores "V" y "F",
- Likert → valores enteros (los del documento, o 0..n-1 si no los hay),
- respuesta correcta → se mapea a un valor existente; si no coincide, se descarta,
- números de ítem únicos y crecientes (si no, se renumera 1..n).
"""

import itertools
import logging
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from app.core.exceptions import NoItemsDetectedError
from app.schemas.extraction import RawItem, RawQuestionnaire
from app.schemas.questionnaire import Cuestionario, Item, TipoItem
from app.services.classification.base import TypeQuery
from app.services.text_utils import clean_text, fold, is_likert_label, number_to_str, to_int

logger = logging.getLogger(__name__)

_LIKERT_LABEL_WITH_VALUE_RE = re.compile(r"^(?P<value>-?\d{1,2})\s*[=:\-–).]\s*(?P<label>\S.*)$")

_TIPO_ALIASES: dict[str, TipoItem] = {}
for _tipo, _aliases in {
    TipoItem.ESCALA_LIKERT: ["escala_likert", "likert", "escala", "scala", "scale", "rating", "rating_scale"],
    TipoItem.SELECCION_MULTIPLE: [
        "seleccion_multiple",
        "opcion_multiple",
        "multiple_choice",
        "multiple",
        "scelta_multipla",
        "single_choice",
        "choice",
        "si_no",
        "yes_no",
    ],
    TipoItem.VERDADERO_FALSO: [
        "verdadero_falso",
        "true_false",
        "vero_falso",
        "v_f",
        "t_f",
        "vf",
        "tf",
        "boolean",
        "booleano",
    ],
    TipoItem.DESARROLLO: [
        "desarrollo",
        "abierta",
        "pregunta_abierta",
        "respuesta_abierta",
        "open",
        "open_ended",
        "open_question",
        "essay",
        "short_answer",
        "texto",
        "text",
        "aperta",
        "risposta_aperta",
    ],
    TipoItem.EMPAREJAMIENTO: [
        "emparejamiento",
        "matching",
        "match",
        "abbinamento",
        "relacion",
        "relacionar",
        "pareo",
    ],
}.items():
    for _alias in _aliases:
        _TIPO_ALIASES[_alias] = _tipo

_TRUE_TOKENS = {
    "v", "verdadero", "verdadera", "vero", "true", "t", "cierto", "verdadeiro", "vrai", "wahr",
    "si", "yes", "y", "correcto", "corretto", "correct",
}  # fmt: skip
_FALSE_TOKENS = {
    "f", "falso", "falsa", "false", "faux", "falsch", "no", "n", "incorrecto", "errato", "incorrect",
}  # fmt: skip

TRUE_FALSE_LABELS: dict[str, tuple[str, str]] = {
    "es": ("Verdadero", "Falso"),
    "it": ("Vero", "Falso"),
    "en": ("True", "False"),
    "pt": ("Verdadeiro", "Falso"),
    "fr": ("Vrai", "Faux"),
    "de": ("Wahr", "Falsch"),
}


class QuestionnaireNormalizer:
    def type_queries(self, raw: RawQuestionnaire) -> dict[int, TypeQuery]:
        """Ítems (por índice) cuyo tipo las reglas no pueden decidir con seguridad.

        Son los únicos que vale la pena enviar a un clasificador externo; el resto se
        resuelve gratis y de forma determinista.
        """
        queries: dict[int, TypeQuery] = {}
        for index, raw_item in enumerate(raw.items):
            enunciado = _strip_number_prefix(clean_text(raw_item.enunciado), raw_item.numero)
            if not enunciado:
                continue
            alternativas = self._clean_alternatives(raw_item)
            candidates = _ambiguous_type_candidates(raw_item.tipo, alternativas, enunciado)
            if candidates:
                texts = [texto or (valor or "") for valor, texto in alternativas]
                queries[index] = TypeQuery(enunciado=enunciado, alternativas=texts, candidates=candidates)
        return queries

    def normalize(
        self,
        raw: RawQuestionnaire,
        *,
        idioma: str,
        source_name: str,
        type_decisions: Mapping[int, TipoItem] | None = None,
    ) -> Cuestionario:
        """``type_decisions``: tipos decididos por un clasificador externo, por índice de ítem."""
        decisions = type_decisions or {}
        normalized: list[tuple[int | None, dict]] = []
        for index, raw_item in enumerate(raw.items):
            item = self._normalize_item(raw_item, idioma, decisions.get(index))
            if item is not None:
                normalized.append((to_int(raw_item.numero), item))

        if not normalized:
            raise NoItemsDetectedError(
                "No se detectaron ítems de cuestionario en el documento. Verifica que contenga "
                "preguntas o afirmaciones con sus alternativas de respuesta."
            )

        numbers = [number for number, _ in normalized]
        keep_numbers = all(n is not None and n >= 1 for n in numbers) and all(
            a < b for a, b in itertools.pairwise(numbers)
        )
        items = []
        for index, (number, item) in enumerate(normalized, start=1):
            item["numero"] = number if keep_numbers else index
            try:
                items.append(Item(**item))
            except ValidationError as exc:  # salvaguarda: un ítem defectuoso no tumba todo el documento
                logger.warning("Ítem %s descartado por no cumplir el esquema: %s", item["numero"], exc.errors()[:1])

        if not items:
            raise NoItemsDetectedError("No se pudo estructurar ningún ítem válido a partir del documento.")

        return Cuestionario(
            titulo=self._title(raw.titulo, source_name),
            idioma=idioma,
            total_items=len(items),
            items=items,
        )

    # ------------------------------------------------------------------ ítems
    def _normalize_item(self, raw: RawItem, idioma: str, decided_tipo: TipoItem | None = None) -> dict | None:
        enunciado = _strip_number_prefix(clean_text(raw.enunciado), raw.numero)
        if not enunciado:
            logger.info("Ítem descartado por no tener enunciado: %r", raw)
            return None

        alternativas = self._clean_alternatives(raw)
        tipo = decided_tipo or self._resolve_tipo(raw.tipo, alternativas)
        answer = raw.respuesta_correcta

        if tipo is TipoItem.VERDADERO_FALSO:
            final_alts, answer = self._true_false(alternativas, answer, idioma)
        elif tipo is TipoItem.ESCALA_LIKERT:
            final_alts, answer = self._likert(alternativas), None
        elif tipo in (TipoItem.SELECCION_MULTIPLE, TipoItem.EMPAREJAMIENTO):
            final_alts, answer = self._lettered(
                alternativas, answer, allow_multiple=tipo is TipoItem.SELECCION_MULTIPLE
            )
        else:
            # En desarrollo la "respuesta correcta" solo puede ser una respuesta modelo en texto.
            final_alts = []
            model_answer = clean_text(number_to_str(answer)) if isinstance(answer, str | int | float) else ""
            answer = model_answer if isinstance(answer, str) and model_answer else None

        if tipo is not TipoItem.DESARROLLO and len(final_alts) < 2:
            logger.info("Ítem '%s' sin alternativas suficientes: se clasifica como desarrollo.", enunciado[:60])
            tipo, final_alts, answer = TipoItem.DESARROLLO, [], None

        return {
            "enunciado": enunciado,
            "tipo": tipo,
            "alternativas": final_alts,
            "respuesta_correcta": answer,
        }

    @staticmethod
    def _clean_alternatives(raw: RawItem) -> list[tuple[str | None, str]]:
        cleaned = []
        for alt in raw.alternativas:
            valor = None if alt.valor is None else clean_text(number_to_str(alt.valor)) or None
            texto = clean_text(alt.texto)
            if texto or valor is not None:
                cleaned.append((valor, texto))
        return cleaned

    @staticmethod
    def _resolve_tipo(raw_tipo: str | None, alternativas: list[tuple[str | None, str]]) -> TipoItem:
        tipo = _tipo_alias(raw_tipo)

        if _looks_true_false(alternativas) and tipo in (None, TipoItem.SELECCION_MULTIPLE):
            return TipoItem.VERDADERO_FALSO
        if tipo is not None and not (tipo is TipoItem.DESARROLLO and len(alternativas) >= 2):
            return tipo
        # Tipo ausente/desconocido, o "desarrollo" con alternativas: se infiere.
        if len(alternativas) < 2:
            return TipoItem.DESARROLLO
        if _looks_likert(alternativas):
            return TipoItem.ESCALA_LIKERT
        return TipoItem.SELECCION_MULTIPLE

    # ------------------------------------------------------------ por tipo
    @staticmethod
    def _likert(alternativas: list[tuple[str | None, str]]) -> list[dict]:
        entries = []
        for valor, texto in alternativas:
            value = to_int(valor)
            match = _LIKERT_LABEL_WITH_VALUE_RE.match(texto)
            if match and (value is None or value == int(match["value"])):
                value, texto = int(match["value"]), match["label"]
            elif value is None:
                value = to_int(texto)  # escala solo numérica ("1 2 3 4 5"): se conservan sus números
            entries.append((value, texto or (valor or "")))

        values = [value for value, _ in entries]
        if any(value is None for value in values) or len(set(values)) != len(values):
            values = list(range(len(entries)))
        return [{"valor": value, "texto": texto} for value, (_, texto) in zip(values, entries, strict=True)]

    def _lettered(
        self, alternativas: list[tuple[str | None, str]], answer: object, *, allow_multiple: bool
    ) -> tuple[list[dict], str | None]:
        raw_values = [(valor or "").strip().strip("().").upper() for valor, _ in alternativas]
        use_document_letters = all(re.fullmatch(r"[A-Z]", v) for v in raw_values) and len(set(raw_values)) == len(
            raw_values
        )
        result: list[dict] = []
        original_to_letter: dict[str, str] = {}
        for index, ((valor, texto), raw_value) in enumerate(zip(alternativas, raw_values, strict=True)):
            letter = raw_value if use_document_letters else _index_to_letter(index)
            if raw_value:
                original_to_letter.setdefault(raw_value, letter)
            text = _strip_option_label(texto, raw_value) or (valor or "")
            result.append({"valor": letter, "texto": text})
        return result, self._match_answer(answer, result, original_to_letter, allow_multiple=allow_multiple)

    @staticmethod
    def _match_answer(
        answer: object, alternatives: list[dict], original_to_letter: dict[str, str], *, allow_multiple: bool
    ) -> str | None:
        if answer is None or isinstance(answer, bool):
            return None
        text = clean_text(number_to_str(answer))
        if not text:
            return None
        letters = [alt["valor"] for alt in alternatives]
        by_text = {fold(alt["texto"]): alt["valor"] for alt in alternatives}

        def resolve(token: str) -> str | None:
            candidate = token.strip().strip("().*").upper()
            if candidate in letters:
                return candidate
            if candidate in original_to_letter:
                return original_to_letter[candidate]
            if fold(token) in by_text:
                return by_text[fold(token)]
            leading = re.match(r"^\(?([A-Za-z]|\d{1,2})[).:\s-]", token.strip())
            return resolve(leading.group(1)) if leading else None

        whole = resolve(text)
        if whole is not None:
            return whole
        parts = [p for p in re.split(r"\s*[,;/&]\s*|\s+(?:y|e|and|et|und)\s+", text) if p]
        if allow_multiple and len(parts) > 1:
            resolved = [resolve(part) for part in parts]
            if all(resolved):
                return ",".join(dict.fromkeys(r for r in resolved if r))
        logger.info("Respuesta correcta '%s' no coincide con ninguna alternativa: se descarta.", text)
        return None

    @staticmethod
    def _true_false(
        alternativas: list[tuple[str | None, str]], answer: object, idioma: str
    ) -> tuple[list[dict], str | None]:
        default_true, default_false = TRUE_FALSE_LABELS.get(idioma, TRUE_FALSE_LABELS["es"])
        true_label = false_label = None
        original_to_vf: dict[str, str] = {}
        for valor, texto in alternativas:
            truth = _truth(texto) if _truth(texto) is not None else _truth(valor)
            if truth is None:
                continue
            if valor:
                original_to_vf[valor.strip().upper()] = "V" if truth else "F"
            # Una etiqueta de una sola letra ("V") se reemplaza por la palabra completa.
            label = texto if len(texto) > 1 else None
            if truth and true_label is None:
                true_label = label
            elif not truth and false_label is None:
                false_label = label

        alternatives = [
            {"valor": "V", "texto": true_label or default_true},
            {"valor": "F", "texto": false_label or default_false},
        ]

        resolved = None
        if isinstance(answer, bool):
            resolved = "V" if answer else "F"
        elif answer is not None:
            token = clean_text(number_to_str(answer))
            truth = _truth(token)
            if truth is not None:
                resolved = "V" if truth else "F"
            else:
                resolved = original_to_vf.get(token.strip("().").upper())
        return alternatives, resolved

    @staticmethod
    def _title(raw_title: str | None, source_name: str) -> str:
        title = clean_text(raw_title or "")
        if not title:
            stem = Path(source_name).stem if source_name else ""
            title = clean_text(re.sub(r"[_\-]+", " ", stem)).capitalize() or "Cuestionario"
        return title[:200]


# ------------------------------------------------------------------ helpers


def _tipo_alias(raw_tipo: str | None) -> TipoItem | None:
    key = fold(raw_tipo or "").replace(" ", "_").replace("-", "_").replace("/", "_")
    return _TIPO_ALIASES.get(key)


def _ambiguous_type_candidates(
    raw_tipo: str | None, alternativas: list[tuple[str | None, str]], enunciado: str
) -> tuple[TipoItem, ...] | None:
    """Tipos posibles cuando las reglas no pueden decidir (el primero es el que aplicarían)."""
    tipo = _tipo_alias(raw_tipo)
    if len(alternativas) >= 2:
        if _looks_true_false(alternativas) or _looks_likert(alternativas):
            return None
        if tipo is not None and tipo is not TipoItem.DESARROLLO:
            return None  # tipo explícito y coherente con tener alternativas
        return (TipoItem.SELECCION_MULTIPLE, TipoItem.ESCALA_LIKERT)
    if tipo is not None or enunciado.rstrip().endswith("?"):
        return None  # tipo explícito, o una pregunta sin alternativas (claramente de desarrollo)
    return (TipoItem.DESARROLLO, TipoItem.VERDADERO_FALSO)


def _truth(value: str | None) -> bool | None:
    if not value:
        return None
    token = fold(value).strip(" .()[]*")
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return None


def _looks_true_false(alternativas: list[tuple[str | None, str]]) -> bool:
    if len(alternativas) != 2:
        return False
    truths = [_truth(texto) if _truth(texto) is not None else _truth(valor) for valor, texto in alternativas]
    # "Sí/No" se considera selección múltiple: solo palabras inequívocas de verdadero/falso.
    unambiguous = {"verdadero", "falso", "vero", "true", "false", "verdadeiro", "vrai", "faux", "wahr", "falsch"}
    words = {fold(texto).strip(" .") for _, texto in alternativas}
    return sorted(truths, key=str) == [False, True] and words <= unambiguous | {"v", "f"}


def _looks_likert(alternativas: list[tuple[str | None, str]]) -> bool:
    if len(alternativas) < 3:
        return False
    hits = sum(1 for _, texto in alternativas if is_likert_label(texto))
    return hits / len(alternativas) >= 0.75


def _index_to_letter(index: int) -> str:
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _strip_option_label(texto: str, label: str) -> str:
    if not label:
        return texto
    pattern = rf"^\(?{re.escape(label)}\s*[).:\-–]\s+"
    return re.sub(pattern, "", texto, flags=re.IGNORECASE).strip()


def _strip_number_prefix(enunciado: str, numero: object) -> str:
    number = to_int(numero)
    if number is None:
        return enunciado
    return re.sub(rf"^{number}\s*[.):\-–]\s+", "", enunciado).strip()
