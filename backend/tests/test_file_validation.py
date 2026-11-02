import pytest

from app.core.exceptions import FileTooLargeError, InvalidFileError, UnsupportedFileTypeError
from app.services.file_validation_service import FileKind, FileValidationService
from tests.factories import docx_bytes, pdf_bytes, xlsx_bytes

MAX_BYTES = 1024 * 1024


@pytest.fixture
def validator() -> FileValidationService:
    return FileValidationService(MAX_BYTES)


@pytest.mark.parametrize(
    ("filename", "content_factory", "expected"),
    [
        ("cuestionario.pdf", lambda: pdf_bytes(["1. Hola"]), FileKind.PDF),
        ("CUESTIONARIO.PDF", lambda: pdf_bytes(["1. Hola"]), FileKind.PDF),
        ("cuestionario.docx", lambda: docx_bytes(["1. Hola"]), FileKind.DOCX),
        ("cuestionario.xlsx", lambda: xlsx_bytes([["1", "Hola"]]), FileKind.XLSX),
    ],
)
def test_accepts_supported_formats(validator, filename, content_factory, expected):
    assert validator.validate(filename, content_factory()) is expected


@pytest.mark.parametrize("filename", ["notas.txt", "imagen.png", "presentacion.pptx", "sin_extension"])
def test_rejects_unsupported_extensions(validator, filename):
    with pytest.raises(UnsupportedFileTypeError, match="no soportado"):
        validator.validate(filename, b"contenido")


@pytest.mark.parametrize(("filename", "hint"), [("viejo.doc", ".docx"), ("viejo.xls", ".xlsx")])
def test_legacy_office_formats_get_a_helpful_hint(validator, filename, hint):
    with pytest.raises(UnsupportedFileTypeError, match=hint):
        validator.validate(filename, b"\xd0\xcf\x11\xe0")


def test_rejects_missing_filename(validator):
    with pytest.raises(InvalidFileError):
        validator.validate(None, b"%PDF-1.7")


def test_rejects_empty_file(validator):
    with pytest.raises(InvalidFileError, match="vacío"):
        validator.validate("vacio.pdf", b"")


def test_rejects_file_over_size_limit(validator):
    content = b"%PDF-1.7\n" + b"0" * MAX_BYTES
    with pytest.raises(FileTooLargeError, match="1 MB"):
        validator.validate("grande.pdf", content)


def test_rejects_pdf_extension_with_non_pdf_content(validator):
    with pytest.raises(InvalidFileError, match="no es un PDF"):
        validator.validate("falso.pdf", b"esto es texto plano renombrado")


def test_rejects_docx_extension_with_xlsx_content(validator):
    with pytest.raises(InvalidFileError, match="no corresponde"):
        validator.validate("renombrado.docx", xlsx_bytes([["a", "b"]]))


def test_rejects_xlsx_extension_with_docx_content(validator):
    with pytest.raises(InvalidFileError, match="no corresponde"):
        validator.validate("renombrado.xlsx", docx_bytes(["hola"]))


def test_rejects_corrupted_office_file(validator):
    with pytest.raises(InvalidFileError, match="dañado"):
        validator.validate("roto.docx", b"PK\x03\x04" + b"\x00" * 50)


def test_rejects_non_zip_office_file(validator):
    with pytest.raises(InvalidFileError):
        validator.validate("texto.xlsx", b"col1,col2\n1,2")
