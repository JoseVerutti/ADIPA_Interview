"""Generadores de documentos en memoria para los tests (sin archivos binarios en el repo)."""

import io
from collections.abc import Sequence

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from fpdf import FPDF
from openpyxl import Workbook


def pdf_bytes(lines: Sequence[str]) -> bytes:
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in lines:
        pdf.multi_cell(0, 7, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def blank_pdf_bytes() -> bytes:
    pdf = FPDF()
    pdf.add_page()
    return bytes(pdf.output())


def docx_bytes(
    paragraphs: Sequence[str] = (),
    *,
    table: Sequence[Sequence[str]] | None = None,
    numbered: Sequence[str] = (),
    highlighted: Sequence[str] = (),
) -> bytes:
    """Párrafos simples, luego una tabla, luego una lista numerada automática y párrafos resaltados."""
    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        word_table = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                word_table.cell(r, c).text = value
    for text in numbered:
        document.add_paragraph(text, style="List Number")
    for text in highlighted:
        run = document.add_paragraph().add_run(text)
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def xlsx_bytes(rows: Sequence[Sequence[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Hoja1"
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


SAMPLE_PDF_LINES = [
    "Questionario di esempio",
    "Scala: 0 = Mai, 1 = A volte, 2 = Spesso, 3 = Sempre",
    "1. Mi preoccupo eccessivamente per cose di poca importanza.",
    "Sezione B - Scelta multipla",
    "2. Quale numero completa la serie: 2, 4, 8, 16, ...?",
    "A) 18",
    "B) 24",
    "C) 32",
    "Sezione C - Domande aperte",
    "3. Descriva una situazione recente in cui si è sentito sotto pressione.",
    "Soluzioni: 2-C",
]
