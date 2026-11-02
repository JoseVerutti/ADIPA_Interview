"""Extracción de texto plano desde PDF, DOCX y XLSX.

El texto conserva pistas de estructura útiles para identificar ítems:
- DOCX: orden real de párrafos y tablas, numeración automática de listas
  (que Word no guarda en el texto), **negrita** y ==resaltado==.
- Tablas (DOCX) y hojas (XLSX): una fila por línea, celdas separadas por " | ".
"""

import io
import logging
import re
from collections import defaultdict
from collections.abc import Iterator

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.hyperlink import Hyperlink
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.exceptions import AppError, EmptyDocumentError, InvalidFileError
from app.services.file_validation_service import FileKind

logger = logging.getLogger(__name__)

CELL_SEPARATOR = " | "


class TextExtractionService:
    def extract(self, kind: FileKind, content: bytes) -> str:
        extractors = {
            FileKind.PDF: self._extract_pdf,
            FileKind.DOCX: self._extract_docx,
            FileKind.XLSX: self._extract_xlsx,
        }
        try:
            raw_text = extractors[kind](content)
        except AppError:
            raise
        except Exception as exc:  # las librerías lanzan excepciones muy variadas ante archivos corruptos
            logger.warning("No se pudo leer el documento %s: %r", kind.value, exc)
            raise InvalidFileError(
                f"No se pudo leer el archivo {kind.value.upper()}. Puede estar dañado o protegido."
            ) from exc

        text = normalize_text(raw_text)
        if not text:
            hint = (
                " Si es un PDF escaneado (imagen), conviértelo antes a PDF con texto (OCR)."
                if kind is FileKind.PDF
                else ""
            )
            raise EmptyDocumentError(f"No se encontró texto en el documento.{hint}")
        return text

    # ---------------------------------------------------------------- PDF
    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(content))
        except PdfReadError as exc:
            raise InvalidFileError("El PDF está dañado o no se puede abrir.") from exc

        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = 0
            if not unlocked:
                raise InvalidFileError("El PDF está protegido con contraseña.")

        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(pages)

    # ---------------------------------------------------------------- DOCX
    def _extract_docx(self, content: bytes) -> str:
        document = Document(io.BytesIO(content))
        numbering = _NumberingResolver(document)
        lines: list[str] = []
        for block in document.iter_inner_content():
            if isinstance(block, Paragraph):
                text = _paragraph_text(block)
                if text.strip():
                    lines.append(numbering.prefix_for(block) + text)
                else:
                    lines.append("")
            elif isinstance(block, Table):
                lines.append("")
                lines.extend(_table_lines(block))
                lines.append("")
        return "\n".join(lines)

    # ---------------------------------------------------------------- XLSX
    @staticmethod
    def _extract_xlsx(content: bytes) -> str:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            sections: list[str] = []
            for sheet in workbook.worksheets:
                rows = [[_cell_to_text(value) for value in row] for row in sheet.iter_rows(values_only=True)]
                lines = _sheet_lines(rows)
                if lines:
                    sections.append(f"[Hoja: {sheet.title}]\n" + "\n".join(lines))
            return "\n\n".join(sections)
        finally:
            workbook.close()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.replace(" ", " ").replace("​", "").replace("\t", " ")
    lines = [re.sub(r"[ ]{2,}", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------- helpers DOCX
def _paragraph_text(paragraph: Paragraph) -> str:
    """Texto del párrafo marcando negrita (**…**) y resaltado (==…==) a nivel de run."""
    segments: list[tuple[str, bool, bool]] = []
    for element in paragraph.iter_inner_content():
        runs = element.runs if isinstance(element, Hyperlink) else [element]
        for run in runs:
            if not run.text:
                continue
            style = (bool(run.bold), run.font.highlight_color is not None)
            if segments and segments[-1][1:] == style:
                segments[-1] = (segments[-1][0] + run.text, *style)
            else:
                segments.append((run.text, *style))

    parts = []
    for text, bold, highlighted in segments:
        core = text.strip()
        if not core or not (bold or highlighted):
            parts.append(text)
            continue
        marker = "==" if highlighted else "**"
        leading = text[: len(text) - len(text.lstrip())]
        trailing = text[len(text.rstrip()) :]
        parts.append(f"{leading}{marker}{core}{marker}{trailing}")
    return "".join(parts)


def _table_lines(table: Table) -> list[str]:
    lines = []
    for row in table.rows:
        cells = []
        previous = None
        for cell in row.cells:
            if previous is not None and cell._tc is previous:  # celdas combinadas se repiten
                continue
            previous = cell._tc
            cell_text = " ".join(_paragraph_text(p).strip() for p in cell.paragraphs if p.text.strip())
            cells.append(cell_text.replace("|", "/"))
        if len(cells) == 1:
            if cells[0].strip():
                lines.append(cells[0])
        elif any(cell.strip() for cell in cells):
            lines.append(CELL_SEPARATOR.join(cells))
    return lines


class _NumberingResolver:
    """Reconstruye el prefijo de las listas numeradas automáticas de Word ("1.", "a)", "•").

    Word guarda el número de cada elemento en ``numbering.xml``, no en el texto,
    por lo que sin esto se perdería la numeración de ítems y alternativas.
    """

    def __init__(self, document: DocxDocument) -> None:
        self._levels: dict[str, dict[int, tuple[str, str, int]]] = {}
        self._counters: dict[str, dict[int, int]] = defaultdict(dict)
        try:
            root = document.part.numbering_part.element
        except (KeyError, NotImplementedError, AttributeError):
            return

        abstract: dict[str, dict[int, tuple[str, str, int]]] = {}
        for abstract_num in root.findall(qn("w:abstractNum")):
            levels = {}
            for lvl in abstract_num.findall(qn("w:lvl")):
                ilvl = int(lvl.get(qn("w:ilvl"), "0"))
                fmt = _child_val(lvl, "w:numFmt") or "decimal"
                pattern = _child_val(lvl, "w:lvlText")
                if pattern is None:
                    pattern = f"%{ilvl + 1}."
                start = int(_child_val(lvl, "w:start") or 1)
                levels[ilvl] = (fmt, pattern, start)
            abstract[abstract_num.get(qn("w:abstractNumId"))] = levels

        for num in root.findall(qn("w:num")):
            levels = dict(abstract.get(_child_val(num, "w:abstractNumId") or "", {}))
            for override in num.findall(qn("w:lvlOverride")):
                ilvl = int(override.get(qn("w:ilvl"), "0"))
                start_override = _child_val(override, "w:startOverride")
                if start_override is not None and ilvl in levels:
                    fmt, pattern, _ = levels[ilvl]
                    levels[ilvl] = (fmt, pattern, int(start_override))
            self._levels[num.get(qn("w:numId"))] = levels

    def prefix_for(self, paragraph: Paragraph) -> str:
        num_id, ilvl = _numbering_props(paragraph)
        if num_id is None or num_id == "0" or num_id not in self._levels:
            return ""
        levels = self._levels[num_id]
        fmt, pattern, start = levels.get(ilvl, ("decimal", f"%{ilvl + 1}.", 1))
        counters = self._counters[num_id]
        counters[ilvl] = counters.get(ilvl, start - 1) + 1
        for deeper in [level for level in counters if level > ilvl]:
            del counters[deeper]

        if fmt == "bullet":
            return "• "
        if fmt == "none" or not pattern:
            return ""

        def render(match: re.Match[str]) -> str:
            level = int(match.group(1)) - 1
            level_fmt, _, level_start = levels.get(level, ("decimal", "", 1))
            return _format_number(counters.get(level, level_start), level_fmt)

        return re.sub(r"%(\d)", render, pattern) + " "


def _numbering_props(paragraph: Paragraph) -> tuple[str | None, int]:
    """numId/ilvl del párrafo; si no tiene, los hereda de su estilo (p. ej. "List Number")."""
    for ppr in _ppr_chain(paragraph):
        if ppr is None or ppr.numPr is None:
            continue
        num_pr = ppr.numPr
        num_id = num_pr.numId.val if num_pr.numId is not None else None
        ilvl = num_pr.ilvl.val if num_pr.ilvl is not None else 0
        if num_id is not None:
            return str(num_id), int(ilvl)
    return None, 0


def _ppr_chain(paragraph: Paragraph) -> Iterator:
    yield paragraph._p.pPr
    style = paragraph.style
    while style is not None:
        yield style.element.pPr
        style = style.base_style


def _child_val(element, tag: str) -> str | None:
    child = element.find(qn(tag))
    return None if child is None else child.get(qn("w:val"))


def _format_number(value: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        letters = ""
        n = value
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            letters = chr(ord("a") + remainder) + letters
        return letters.upper() if fmt == "upperLetter" else letters
    if fmt in ("lowerRoman", "upperRoman"):
        roman = _to_roman(value)
        return roman if fmt == "upperRoman" else roman.lower()
    if fmt == "decimalZero":
        return f"{value:02d}"
    return str(value)


def _to_roman(value: int) -> str:
    numerals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]  # fmt: skip
    result = ""
    for number, numeral in numerals:
        while value >= number:
            result += numeral
            value -= number
    return result


# ---------------------------------------------------------------- helpers XLSX
def _cell_to_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).replace("\n", " ").replace("|", "/").strip()


def _sheet_lines(rows: list[list[str]]) -> list[str]:
    """Convierte las filas de una hoja en líneas.

    Las filas con una sola celda antes de que empiece la tabla (título,
    instrucciones) se emiten como texto simple; el resto como filas " | ".
    """
    used_columns = max((i + 1 for row in rows for i, cell in enumerate(row) if cell), default=0)
    lines: list[str] = []
    table_started = False
    for row in rows:
        cells = row[:used_columns]
        filled = [cell for cell in cells if cell]
        if not filled:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if len(filled) == 1 and not table_started:
            lines.append(filled[0])
            continue
        table_started = True
        lines.append(CELL_SEPARATOR.join(cells))
    return lines
