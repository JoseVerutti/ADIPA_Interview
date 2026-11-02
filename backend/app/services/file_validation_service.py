"""Validación del archivo subido: extensión, tamaño y contenido real (firma binaria).

No se confía en el ``Content-Type`` que envía el cliente: se verifica que los bytes
correspondan al formato declarado por la extensión.
"""

import io
import zipfile
from enum import StrEnum
from pathlib import Path

from app.core.exceptions import FileTooLargeError, InvalidFileError, UnsupportedFileTypeError


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"


ALLOWED_EXTENSIONS: dict[str, FileKind] = {
    ".pdf": FileKind.PDF,
    ".docx": FileKind.DOCX,
    ".xlsx": FileKind.XLSX,
}

_LEGACY_HINTS = {
    ".doc": "Los archivos .doc (Word 97-2003) no están soportados: guárdalo como .docx.",
    ".xls": "Los archivos .xls (Excel 97-2003) no están soportados: guárdalo como .xlsx.",
}

# Parte obligatoria dentro del paquete ZIP (Office Open XML) de cada formato.
_OOXML_MAIN_PART = {
    FileKind.DOCX: "word/document.xml",
    FileKind.XLSX: "xl/workbook.xml",
}


class FileValidationService:
    def __init__(self, max_size_bytes: int) -> None:
        self._max_size_bytes = max_size_bytes

    def validate(self, filename: str | None, content: bytes) -> FileKind:
        if not filename:
            raise InvalidFileError("El archivo no tiene nombre.")

        extension = Path(filename).suffix.lower()
        kind = ALLOWED_EXTENSIONS.get(extension)
        if kind is None:
            hint = _LEGACY_HINTS.get(extension, "Formatos permitidos: PDF, DOCX y XLSX.")
            shown = extension or "sin extensión"
            raise UnsupportedFileTypeError(f"Formato de archivo no soportado ({shown}). {hint}")

        if not content:
            raise InvalidFileError("El archivo está vacío.")

        if len(content) > self._max_size_bytes:
            max_mb = self._max_size_bytes / (1024 * 1024)
            raise FileTooLargeError(f"El archivo supera el tamaño máximo permitido ({max_mb:g} MB).")

        self._check_signature(kind, content)
        return kind

    @staticmethod
    def _check_signature(kind: FileKind, content: bytes) -> None:
        if kind is FileKind.PDF:
            # La especificación permite bytes basura antes de la cabecera, dentro del primer KB.
            if b"%PDF-" not in content[:1024]:
                raise InvalidFileError("El archivo tiene extensión .pdf pero su contenido no es un PDF válido.")
            return

        label = kind.value.upper()
        if not content.startswith(b"PK"):
            raise InvalidFileError(f"El archivo tiene extensión .{kind.value} pero no es un documento {label} válido.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                names = set(package.namelist())
        except zipfile.BadZipFile as exc:
            raise InvalidFileError(f"El archivo {label} está dañado o no se puede abrir.") from exc

        if _OOXML_MAIN_PART[kind] not in names:
            raise InvalidFileError(
                f"El archivo tiene extensión .{kind.value} pero su contenido no corresponde a un documento {label}."
            )
