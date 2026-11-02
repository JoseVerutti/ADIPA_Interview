"""Excepciones de dominio.

Las subclases de ``AppError`` se traducen a respuestas HTTP con un cuerpo uniforme
(``{"error": {"code": ..., "message": ...}}``). Los mensajes están pensados para
mostrarse directamente al usuario final.
"""


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidFileError(AppError):
    status_code = 400
    code = "invalid_file"


class UnsupportedFileTypeError(AppError):
    status_code = 415
    code = "unsupported_file_type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class EmptyDocumentError(AppError):
    status_code = 422
    code = "empty_document"


class DocumentTooLongError(AppError):
    status_code = 413
    code = "document_too_long"


class NoItemsDetectedError(AppError):
    status_code = 422
    code = "no_items_detected"


class ExtractionError(AppError):
    status_code = 502
    code = "extraction_failed"


class LLMError(Exception):
    """Fallo al invocar al proveedor LLM. Es interno: el servicio decide cómo exponerlo."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMRateLimitError(LLMError):
    """El proveedor rechazó la petición por cuota o límite de tasa (HTTP 429)."""


class LLMOutputError(LLMError):
    """El LLM respondió, pero el contenido no es un JSON utilizable."""


class ClassifierError(Exception):
    """Fallo al invocar al clasificador (Jev). Nunca llega al usuario: se usan las reglas."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
