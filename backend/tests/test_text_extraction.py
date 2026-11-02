import pytest

from app.core.exceptions import EmptyDocumentError, InvalidFileError
from app.services.file_validation_service import FileKind
from app.services.text_extraction_service import TextExtractionService, normalize_text
from tests.factories import blank_pdf_bytes, docx_bytes, pdf_bytes, xlsx_bytes


@pytest.fixture
def extractor() -> TextExtractionService:
    return TextExtractionService()


def test_pdf_text_is_extracted(extractor):
    text = extractor.extract(FileKind.PDF, pdf_bytes(["Questionario", "1. Mi preoccupo spesso."]))
    assert "Questionario" in text
    assert "1. Mi preoccupo spesso." in text


def test_pdf_without_text_reports_empty_document(extractor):
    with pytest.raises(EmptyDocumentError, match="OCR"):
        extractor.extract(FileKind.PDF, blank_pdf_bytes())


def test_corrupted_pdf_is_reported_as_invalid(extractor):
    with pytest.raises(InvalidFileError):
        extractor.extract(FileKind.PDF, b"%PDF-1.7\nbasura sin estructura")


def test_docx_keeps_paragraph_and_table_order(extractor):
    content = docx_bytes(
        ["Título", "1. Primera pregunta"],
        table=[["N°", "Afirmación", "Nunca", "Siempre"], ["2", "Me concentro", "", ""]],
    )
    lines = extractor.extract(FileKind.DOCX, content).splitlines()
    assert lines[0] == "Título"
    assert lines[1] == "1. Primera pregunta"
    assert "N° | Afirmación | Nunca | Siempre" in lines
    assert any(line.startswith("2 | Me concentro") for line in lines)


def test_docx_automatic_numbering_is_rendered(extractor):
    text = extractor.extract(FileKind.DOCX, docx_bytes(numbered=["Primera", "Segunda"]))
    assert "1. Primera" in text
    assert "2. Segunda" in text


def test_docx_highlight_is_marked(extractor):
    text = extractor.extract(FileKind.DOCX, docx_bytes(["a) 30"], highlighted=["b) 60"]))
    assert "==b) 60==" in text


def test_xlsx_rows_become_pipe_separated_lines(extractor):
    rows = [
        ["Quiz de ejemplo"],
        [],
        ["N°", "Pregunta", "A", "B"],
        [1, "¿2+2?", 3, 4.0],
    ]
    lines = extractor.extract(FileKind.XLSX, xlsx_bytes(rows)).splitlines()
    assert lines[0] == "[Hoja: Hoja1]"
    assert lines[1] == "Quiz de ejemplo"
    assert "N° | Pregunta | A | B" in lines
    assert "1 | ¿2+2? | 3 | 4" in lines


def test_empty_xlsx_reports_empty_document(extractor):
    with pytest.raises(EmptyDocumentError):
        extractor.extract(FileKind.XLSX, xlsx_bytes([]))


def test_normalize_text_collapses_whitespace():
    assert normalize_text("  a  b \r\n\r\n\r\n\r\nc\x00 ") == "a b\n\nc"
