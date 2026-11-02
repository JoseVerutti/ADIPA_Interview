"""Extractor heurístico (basado en reglas), usado como respaldo del LLM.

Se activa cuando no hay API key configurada o el proveedor falla (cuota agotada,
caída, timeout). Reconoce los formatos más habituales:

- ítems numerados ("1.", "1)", "Pregunta 1:", "Q1."),
- alternativas con letra ("A)", "b.", "(c)"), en líneas separadas o en una misma línea,
  o con viñetas/casillas ("•", "☐", "( )"),
- leyendas de escala Likert ("0 = Mai, 1 = A volte…") y encabezados de sección que
  indican el tipo ("Verdadero o falso", "Domande aperte", "Emparejamiento"…),
- respuestas correctas: "Respuesta: C", marcas "*" / "✓" / "(correcta)",
  una única alternativa en negrita o resaltada, y claves al final ("Soluzioni: 1-C, 2-A"),
- tablas (Word) y hojas de cálculo con encabezados (N°, Pregunta, Tipo, A, B, C, Respuesta…).

Es intencionalmente conservador: ante la duda deja la decisión final de tipos y
valores al ``QuestionnaireNormalizer``.
"""

import re
from dataclasses import dataclass, field

from app.schemas.extraction import RawAlternative, RawItem, RawQuestionnaire
from app.schemas.questionnaire import TipoItem
from app.services.text_utils import clean_text, fold, is_likert_label, to_int

ITEM_RE = re.compile(
    r"^(?:(?:pregunta|preg\.|question|domanda|quesito|[íi]tem|reactivo|q)\s*)?"
    r"(?P<num>\d{1,3})\s*[.)\-–:]\s*(?P<text>\S.*)$",
    re.IGNORECASE,
)
OPTION_RE = re.compile(r"^[(\[]?(?P<label>[A-Ha-h])\s*[).\]:\-–]\s*(?P<text>\S.*)$")
INLINE_OPTION_RE = re.compile(r"(?:^|\s)[(\[]?([A-Ha-h])[).\]]\s+")
BULLET_RE = re.compile(r"^(?:[•▪◦○●□☐■❑–\-]|\[\s?\]|\(\s?\))\s*(?P<text>\S.*)$")
CORRECT_SUFFIX_RE = re.compile(r"\s*(?:\(\s*(?:correct[ao]?|corrett[ao]|right|x)\s*\)|[✓✔✅]|\*+)\s*$", re.IGNORECASE)
ANSWER_LINE_RE = re.compile(
    r"^(?:respuesta(?:\s+correcta)?|soluci[oó]n|risposta(?:\s+corretta)?|soluzione|"
    r"(?:correct\s+)?answer|clave)\s*[:=]\s*(?P<ans>\S.*)$",
    re.IGNORECASE,
)
ANSWER_KEY_HEADER_RE = re.compile(
    r"^(?:clave\s+de\s+respuestas|hoja\s+de\s+respuestas|respuestas(?:\s+correctas)?|soluciones|"
    r"soluzioni|risposte(?:\s+corrette)?|chiave\s+di\s+correzione|griglia\s+di\s+correzione|"
    r"answer\s+key|answers|solutions|correct\s+answers)\s*:?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
KEY_PAIR_RE = re.compile(r"(\d{1,3})\s*[.)\-–:=→]\s*([A-Za-zÀ-ÿ]+)")
SECTION_RE = re.compile(
    r"^(?:secci[oó]n|sezione|section|parte|part|bloque|blocco|ejercicio|esercizio|exercise|"
    r"instrucciones|istruzioni|instructions|indicaciones|consegna)\b",
    re.IGNORECASE,
)
SHEET_RE = re.compile(r"^\[Hoja: .*\]$")
LEGEND_PAIR_RE = re.compile(r"(?<!\w)(-?\d{1,2})\s*=\s*([^=,;|]+?)\s*(?=[,;|]|\s+-?\d{1,2}\s*=|$)")
LABEL_SCALE_SPLIT_RE = re.compile(r"\s+[–\-/]\s+|\s*[,;/|]\s*")
TRUE_FALSE_MARK_RE = re.compile(
    r"\s*[(\[]\s*(?:v\s*/\s*f|t\s*/\s*f|vero\s*/\s*falso|verdadero\s*/\s*falso|true\s*/\s*false)\s*[)\]]\s*$"
    r"|\s+(?:v\s*/\s*f|t\s*/\s*f)\s*$",
    re.IGNORECASE,
)
_MODE_PATTERNS: list[tuple[TipoItem, re.Pattern[str]]] = [
    (
        TipoItem.VERDADERO_FALSO,
        re.compile(
            r"verdader[oa]s?\s*(?:o|/)\s*fals[oa]s?|ver[oea]\s*(?:o|/)\s*fals[oea]|true\s*(?:or|/)\s*false|\bv\s*/\s*f\b"
        ),
    ),
    (TipoItem.EMPAREJAMIENTO, re.compile(r"empareja|relacion[ae]|une cada|abbina|collega|\bmatch")),
    (
        TipoItem.SELECCION_MULTIPLE,
        re.compile(r"seleccion multiple|opcion multiple|scelta multipla|multiple[- ]choice"),
    ),
    (
        TipoItem.DESARROLLO,
        re.compile(
            r"desarrollo|respuesta abierta|preguntas? abiertas?|domande aperte|risposta aperta|"
            r"open[- ]ended|open questions?|essay|short answer"
        ),
    ),
    (
        TipoItem.ESCALA_LIKERT,
        re.compile(r"likert|escala|scala|\bscale|frecuencia|frequenza|frequency|de acuerdo|d'accordo|\bagree"),
    ),
]

# Encabezados de tablas / hojas de cálculo.
_NUMBER_HEADERS = {"n", "no", "nº", "n°", "#", "num", "numero", "number", "nro", "id"}
_STATEMENT_HEADER_RE = re.compile(
    r"pregunta|enunciado|item|domanda|question|statement|affermazione|afirmacion|reactivo|testo|texto|frase"
)
_TYPE_HEADER_RE = re.compile(r"(?:tipo|type|tipologia)(?:\s+(?:de\s+)?(?:pregunta|item|domanda|question))?")
_OPTION_HEADER_RE = re.compile(r"(?:opci[oó]n|opzione|option|alternativa|alt\.?)?\s*\(?([A-Ha-h])\)?", re.IGNORECASE)
_ANSWER_HEADER_RE = re.compile(r"respuesta|correct|corrett|risposta|answer|solucion|soluzione|clave|key")
_LIKERT_HEADER_RE = re.compile(
    r"^(?:(?P<v1>-?\d{1,2})\s*[=:\-–.)]\s*(?P<l1>.+)|(?P<l2>.+?)\s*\((?P<v2>-?\d{1,2})\)|(?P<v3>-?\d{1,2})|(?P<l3>.+))$"
)


@dataclass
class _Option:
    label: str | None
    text: str
    correct: bool = False
    emphasized: bool = False


@dataclass
class _Draft:
    numero: int | None
    enunciado: str
    mode: TipoItem | None = None
    tipo: str | None = None
    options: list[_Option] = field(default_factory=list)
    scale: list[tuple[int | None, str]] | None = None
    answer: str | None = None
    true_false_mark: bool = False


@dataclass
class _Columns:
    statement: int
    number: int | None = None
    type: int | None = None
    answer: int | None = None
    options: dict[int, str] = field(default_factory=dict)
    likert: list[tuple[int, int | None, str]] = field(default_factory=list)


class HeuristicExtractionService:
    def extract(self, text: str) -> RawQuestionnaire:
        parser = _Parser()
        for line in text.splitlines():
            parser.feed(line)
        return parser.finish()


class _Parser:
    def __init__(self) -> None:
        self.title: str | None = None
        self.items: list[_Draft] = []
        self.current: _Draft | None = None
        self.mode: TipoItem | None = None
        self.scale: list[tuple[int | None, str]] | None = None
        self.answer_key: dict[int, str] = {}
        self.in_answer_key = False
        self.after_blank = False
        self.table_rows: list[list[str]] = []
        self.section_items: list[_Draft] = []
        self.shared_options: list[_Option] = []

    # ------------------------------------------------------------ entrada
    def feed(self, raw_line: str) -> None:
        line = raw_line.strip()
        if "|" in line and not self.in_answer_key:
            self.table_rows.append([cell.strip() for cell in line.split("|")])
            return
        self._flush_table()
        if not line:
            self.after_blank = True
            return
        self._handle_line(line)
        self.after_blank = False

    def finish(self) -> RawQuestionnaire:
        self._flush_table()
        self._close_item()
        self._finish_section()
        return RawQuestionnaire(titulo=self.title, items=[self._to_raw(draft) for draft in self.items])

    # ------------------------------------------------------------ líneas
    def _handle_line(self, line: str) -> None:
        plain = clean_text(line)
        if self.in_answer_key:
            self._add_key_pairs(plain)
            return
        if SHEET_RE.match(plain):
            self._start_section(None)
            return

        key = ANSWER_KEY_HEADER_RE.match(plain)
        if key and (not key["rest"] or KEY_PAIR_RE.search(key["rest"])):
            self._start_section(None)
            self.in_answer_key = True
            self._add_key_pairs(key["rest"])
            return

        if self._try_scale_legend(plain):
            return

        answer = ANSWER_LINE_RE.match(plain)
        if answer:
            if self.current is not None:
                self.current.answer = answer["ans"]
            return

        emphasized = bool(re.fullmatch(r"(\*\*|==)(?:(?!\1).)+\1", line))
        marked = plain[:1] in ("*", "✓", "✔") and len(plain) > 1
        body = plain[1:].strip() if marked else plain
        accepts_options = self.current is not None or self.mode is TipoItem.EMPAREJAMIENTO

        inline = _split_inline_options(body)
        if inline and accepts_options:
            for label, text in inline:
                text, is_correct = _strip_correct_marker(text)
                self._add_option(_Option(label, text, is_correct))
            return

        option = OPTION_RE.match(body)
        if option and accepts_options:
            text, is_correct = _strip_correct_marker(option["text"])
            self._add_option(_Option(option["label"].upper(), text, marked or is_correct, emphasized))
            return

        item = ITEM_RE.match(plain)
        if item:
            self._start_item(int(item["num"]), item["text"])
            return

        bullet = BULLET_RE.match(body)
        if bullet and accepts_options:
            text, is_correct = _strip_correct_marker(bullet["text"])
            self._add_option(_Option(None, text, marked or is_correct, emphasized))
            return

        mode = _detect_mode(plain) if len(plain) <= 160 else None
        if self.title is None and not self.items and self.current is None and not SECTION_RE.match(plain):
            self.title = plain[:200]
            if mode is not None:  # p. ej. "Escala de ansiedad" sugiere el tipo de todo el documento
                self.mode = mode
            return

        is_header = SECTION_RE.match(plain) or (
            mode is not None and (self.current is None or self.after_blank or plain.endswith(":"))
        )
        if is_header:
            self._start_section(mode)
            return

        if self.current is not None and not self.after_blank and self._is_continuation(plain):
            if self.current.options:
                self.current.options[-1].text += " " + plain
            else:
                self.current.enunciado += " " + plain
            return

    def _try_scale_legend(self, plain: str) -> bool:
        """Leyenda de escala: "0 = Mai, 1 = A volte…" o "Nunca – A veces – Siempre"."""
        pairs = LEGEND_PAIR_RE.findall(plain)
        if len(pairs) >= 2 and not ITEM_RE.match(plain):
            self._start_section(TipoItem.ESCALA_LIKERT)
            self.scale = [(int(value), label.strip(" .")) for value, label in pairs]
            return True
        if self.mode is TipoItem.ESCALA_LIKERT and self.current is None:
            parts = [part.strip(" .") for part in LABEL_SCALE_SPLIT_RE.split(plain) if part.strip(" .")]
            if len(parts) >= 3 and sum(is_likert_label(part) for part in parts) / len(parts) >= 0.75:
                self.scale = [(None, part) for part in parts]
                return True
        return False

    def _is_continuation(self, plain: str) -> bool:
        if plain[:1].islower():
            return True
        if self.current is None or self.current.options:
            return False
        return not self.current.enunciado.rstrip().endswith((".", "?", "!", ":", "…"))

    def _add_key_pairs(self, text: str) -> None:
        for number, answer in KEY_PAIR_RE.findall(text):
            self.answer_key.setdefault(int(number), answer)

    # ------------------------------------------------------------ estado
    def _start_item(self, number: int, text: str) -> None:
        self._close_item()
        text, true_false_mark = _strip_true_false_mark(text)
        self.current = _Draft(
            numero=number,
            enunciado=text,
            mode=self.mode,
            scale=self.scale,
            true_false_mark=true_false_mark,
        )

    def _add_option(self, option: _Option) -> None:
        if self.mode is TipoItem.EMPAREJAMIENTO:
            self.shared_options.append(option)
        elif self.current is not None:
            self.current.options.append(option)

    def _close_item(self) -> None:
        if self.current is not None:
            self.items.append(self.current)
            self.section_items.append(self.current)
            self.current = None

    def _start_section(self, mode: TipoItem | None) -> None:
        self._close_item()
        if self.section_items:
            self._finish_section()
            self.scale = None
            self.mode = None
        if mode is not None:
            self.mode = mode

    def _finish_section(self) -> None:
        if self.mode is TipoItem.EMPAREJAMIENTO and self.shared_options:
            for draft in self.section_items:
                if not draft.options:
                    draft.options = list(self.shared_options)
                    draft.tipo = TipoItem.EMPAREJAMIENTO.value
        self.section_items = []
        self.shared_options = []

    # ------------------------------------------------------------ tablas
    def _flush_table(self) -> None:
        rows, self.table_rows = self.table_rows, []
        if not rows:
            return
        columns = _detect_columns(rows[0])
        if columns is None:
            # Sin encabezado reconocible: cada celda se procesa como una línea de texto.
            for row in rows:
                for cell in row:
                    if cell:
                        self._handle_line(cell)
            return

        self._close_item()
        for row in rows[1:]:
            draft = self._row_to_draft(row, columns)
            if draft is not None:
                self.items.append(draft)
                self.section_items.append(draft)

    def _row_to_draft(self, row: list[str], columns: _Columns) -> _Draft | None:
        def cell(index: int | None) -> str:
            return clean_text(row[index]) if index is not None and index < len(row) else ""

        statement = cell(columns.statement)
        if not statement:
            return None
        number = to_int(cell(columns.number))
        numbered = ITEM_RE.match(statement)
        if numbered:
            number = number if number is not None else int(numbered["num"])
            statement = numbered["text"]
        statement, true_false_mark = _strip_true_false_mark(statement)

        draft = _Draft(numero=number, enunciado=statement, mode=self.mode, true_false_mark=true_false_mark)
        draft.tipo = cell(columns.type) or None
        for index, letter in columns.options.items():
            text, is_correct = _strip_correct_marker(cell(index))
            if text:
                draft.options.append(_Option(letter, text, is_correct))
        if not draft.options and columns.likert:
            draft.scale = [(value, label) for _, value, label in columns.likert]
            draft.tipo = draft.tipo or TipoItem.ESCALA_LIKERT.value
        draft.answer = cell(columns.answer) or None
        return draft

    # ------------------------------------------------------------ salida
    def _to_raw(self, draft: _Draft) -> RawItem:
        options = draft.options
        answer = draft.answer
        if answer is None:
            marked = [option for option in options if option.correct]
            emphasized = [option for option in options if option.emphasized]
            if marked:
                answer = ",".join(option.label or option.text for option in marked)
            elif len(emphasized) == 1 and len(options) >= 2:
                answer = emphasized[0].label or emphasized[0].text
        if answer is None and draft.numero is not None:
            answer = self.answer_key.get(draft.numero)

        tipo = draft.tipo
        alternatives = [RawAlternative(valor=option.label, texto=option.text) for option in options]
        if tipo is None:
            if options:
                if draft.mode in (TipoItem.EMPAREJAMIENTO, TipoItem.ESCALA_LIKERT, TipoItem.VERDADERO_FALSO):
                    tipo = draft.mode.value
            elif draft.true_false_mark or draft.mode is TipoItem.VERDADERO_FALSO:
                tipo = TipoItem.VERDADERO_FALSO.value
            elif draft.scale and draft.mode in (TipoItem.ESCALA_LIKERT, None):
                tipo = TipoItem.ESCALA_LIKERT.value
            else:
                tipo = TipoItem.DESARROLLO.value
        if not options and draft.scale and tipo == TipoItem.ESCALA_LIKERT.value:
            alternatives = [
                RawAlternative(valor=None if value is None else str(value), texto=label) for value, label in draft.scale
            ]

        return RawItem(
            numero=draft.numero,
            enunciado=draft.enunciado,
            tipo=tipo,
            alternativas=alternatives,
            respuesta_correcta=answer,
        )


# ---------------------------------------------------------------- helpers
def _detect_mode(text: str) -> TipoItem | None:
    folded = fold(text)
    for mode, pattern in _MODE_PATTERNS:
        if pattern.search(folded):
            return mode
    return None


def _split_inline_options(text: str) -> list[tuple[str, str]] | None:
    """ "A) 18   B) 24   C) 32" → [("A", "18"), ("B", "24"), ("C", "32")]."""
    matches = list(INLINE_OPTION_RE.finditer(text))
    if len(matches) < 2 or matches[0].start() != 0:
        return None
    labels = [match.group(1).upper() for match in matches]
    if labels != [chr(ord(labels[0]) + offset) for offset in range(len(labels))]:
        return None
    options = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        option_text = text[match.end() : end].strip()
        if not option_text:
            return None
        options.append((labels[index], option_text))
    return options


def _strip_correct_marker(text: str) -> tuple[str, bool]:
    stripped = CORRECT_SUFFIX_RE.sub("", text)
    return stripped.strip(), stripped != text


def _strip_true_false_mark(text: str) -> tuple[str, bool]:
    stripped = TRUE_FALSE_MARK_RE.sub("", text)
    return stripped.strip(), stripped != text


def _detect_columns(header: list[str]) -> _Columns | None:
    cells = [clean_text(cell) for cell in header]
    if not any(cells) or any(ITEM_RE.match(cell) for cell in cells):
        return None

    number = statement = type_ = answer = None
    options: dict[int, str] = {}
    others: list[int] = []
    for index, cell in enumerate(cells):
        folded = fold(cell).strip(" .:")
        if not folded:
            continue
        option = _OPTION_HEADER_RE.fullmatch(cell)
        if number is None and folded in _NUMBER_HEADERS:
            number = index
        elif type_ is None and _TYPE_HEADER_RE.fullmatch(folded):
            type_ = index
        elif option:
            options[index] = option.group(1).upper()
        elif answer is None and _ANSWER_HEADER_RE.search(folded):
            answer = index
        elif statement is None and _STATEMENT_HEADER_RE.search(folded):
            statement = index
        else:
            others.append(index)
    if statement is None:
        return None

    columns = _Columns(statement=statement, number=number, type=type_, answer=answer, options=options)
    if not options:
        for index in (i for i in others if i > statement):
            match = _LIKERT_HEADER_RE.match(cells[index])
            if match is None:
                continue
            value = match["v1"] or match["v2"] or match["v3"]
            label = match["l1"] or match["l2"] or match["v3"] or match["l3"]
            if match["l3"] and not (is_likert_label(label) or len(label) <= 25):
                continue
            columns.likert.append((index, int(value) if value is not None else None, label.strip()))
    return columns
