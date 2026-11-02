"""Genera los documentos de ejemplo de /examples (contenido inventado, sin datos personales).

Uso (desde backend/):  python -m scripts.generate_examples
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from fpdf import FPDF
from openpyxl import Workbook
from openpyxl.styles import Font

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def build_pdf_it(path: Path) -> None:
    lines: list[tuple[str, str]] = [
        ("title", "Questionario di esempio sul benessere"),
        ("text", "Istruzioni: legga attentamente ogni domanda e risponda con sincerità."),
        ("section", "Sezione A - Frequenza"),
        ("text", "Indichi con quale frequenza le capita quanto descritto."),
        ("text", "Scala: 0 = Mai, 1 = A volte, 2 = Spesso, 3 = Sempre"),
        ("text", "1. Mi preoccupo eccessivamente per cose di poca importanza."),
        ("text", "2. Faccio fatica a rilassarmi alla fine della giornata."),
        ("text", "3. Mi sento soddisfatto delle mie relazioni personali."),
        ("section", "Sezione B - Ragionamento (scelta multipla)"),
        ("text", "4. Quale numero completa la serie: 2, 4, 8, 16, ...?"),
        ("text", "A) 18"),
        ("text", "B) 24"),
        ("text", "C) 32"),
        ("text", "5. Quale parola non appartiene al gruppo?"),
        ("text", "A) Mela    B) Pera    C) Carota    D) Banana"),
        ("section", "Sezione C - Vero o falso"),
        ("text", "6. Il sole sorge a est. (V/F)"),
        ("text", "7. Un triangolo ha quattro lati. (V/F)"),
        ("section", "Sezione D - Domande aperte"),
        ("text", "8. Descriva una situazione recente in cui si è sentito sotto pressione."),
        ("text", "9. Quali strategie utilizza per gestire lo stress?"),
        ("section", "Soluzioni: 4-C, 5-C, 6-V, 7-F"),
    ]
    pdf = FPDF(format="A4")
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    for kind, text in lines:
        if kind == "title":
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        elif kind == "section":
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "", 11)
            pdf.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def build_docx_es(path: Path) -> None:
    doc = Document()
    doc.add_heading("Cuestionario de hábitos de estudio (ejemplo)", level=0)
    doc.add_paragraph("Instrucciones: lea cada enunciado y responda según corresponda.")

    doc.add_heading("Sección 1 - Escala de frecuencia", level=2)
    doc.add_paragraph("Indique con qué frecuencia realiza cada conducta.")
    rows = [
        ["N°", "Afirmación", "Nunca", "A veces", "Frecuentemente", "Siempre"],
        ["1", "Planifico mis horas de estudio con anticipación.", "", "", "", ""],
        ["2", "Estudio en un lugar sin distracciones.", "", "", "", ""],
        ["3", "Repaso los contenidos antes de una evaluación.", "", "", "", ""],
    ]
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            table.cell(r, c).text = value

    doc.add_heading("Sección 2 - Selección múltiple", level=2)
    doc.add_paragraph("4. ¿Cuál es la capital de Chile?")
    for option in ["a) Valparaíso", "b) Santiago", "c) Concepción"]:
        doc.add_paragraph(option)
    doc.add_paragraph("Respuesta: b")
    doc.add_paragraph("5. ¿Cuántos minutos tiene una hora?")
    doc.add_paragraph("a) 30")
    highlighted = doc.add_paragraph().add_run("b) 60")  # la alternativa correcta está resaltada
    highlighted.font.highlight_color = WD_COLOR_INDEX.YELLOW
    doc.add_paragraph("c) 100")

    doc.add_heading("Sección 3 - Verdadero o falso", level=2)
    doc.add_paragraph("6. El agua hierve a 100 °C a nivel del mar. (V/F)")
    doc.add_paragraph("7. La Luna es una estrella. (V/F)")

    doc.add_heading("Sección 4 - Emparejamiento", level=2)
    doc.add_paragraph("Relacione cada país con su capital.")
    for premise in ["8. Perú", "9. Argentina", "10. Uruguay"]:
        doc.add_paragraph(premise)
    for option in ["A. Montevideo", "B. Lima", "C. Buenos Aires"]:
        doc.add_paragraph(option)

    doc.add_heading("Sección 5 - Desarrollo", level=2)
    doc.add_paragraph("11. Explique qué técnica de estudio le resulta más efectiva y por qué.")

    doc.add_paragraph("Clave de respuestas: 6-V, 7-F, 8-B, 9-C, 10-A")
    doc.save(str(path))


def build_xlsx_en(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quiz"
    sheet.append(["General Knowledge Quiz (sample)"])
    sheet["A1"].font = Font(bold=True, size=14)
    sheet.append(["Read each question carefully. Correct answers are listed in the last column."])
    sheet.append([])
    sheet.append(["No.", "Question", "Type", "A", "B", "C", "D", "Correct answer"])
    for cell in sheet[4]:
        cell.font = Font(bold=True)
    data = [
        [1, "Which planet is known as the Red Planet?", "Multiple choice", "Venus", "Mars", "Jupiter", "Saturn", "B"],
        [2, "How many continents are there on Earth?", "Multiple choice", 5, 6, 7, 8, "C"],
        [3, "Water freezes at 0 °C at sea level.", "True/False", None, None, None, None, "True"],
        [4, "The Pacific is the smallest ocean on Earth.", "True/False", None, None, None, None, "False"],
        [5, "I enjoy learning new things.", "Likert", "Strongly disagree", "Disagree", "Agree", "Strongly agree", None],
        [6, "Describe a book that changed your perspective.", "Open", None, None, None, None, None],
    ]
    for row in data:
        sheet.append(row)
    sheet.column_dimensions["B"].width = 50
    workbook.save(str(path))


def main() -> None:
    EXAMPLES_DIR.mkdir(exist_ok=True)
    build_pdf_it(EXAMPLES_DIR / "questionario_benessere_it.pdf")
    build_docx_es(EXAMPLES_DIR / "cuestionario_habitos_estudio_es.docx")
    build_xlsx_en(EXAMPLES_DIR / "knowledge_quiz_en.xlsx")
    print(f"Ejemplos generados en {EXAMPLES_DIR}")


if __name__ == "__main__":
    main()
