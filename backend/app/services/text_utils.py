"""Utilidades de texto compartidas por el normalizador y el extractor heurístico."""

import re
import unicodedata

_MARKUP_RE = re.compile(r"\*\*|==")
_WHITESPACE_RE = re.compile(r"\s+")

_LIKERT_HINTS_RE = re.compile(
    r"\b(nunca|casi nunca|siempre|casi siempre|a veces|algunas veces|frecuentemente|a menudo|raramente|"
    r"acuerdo|desacuerdo|nada|poco|bastante|mucho|"
    r"mai|quasi mai|sempre|quasi sempre|a volte|qualche volta|talvolta|spesso|raramente|"
    r"accordo|disaccordo|per niente|abbastanza|molto|moltissimo|"
    r"never|rarely|sometimes|often|usually|always|agree|disagree|neutral|"
    r"not at all|a little|somewhat|moderately|quite a bit|very much|extremely)\b"
)


def clean_text(value: str) -> str:
    """Quita marcas de formato (**, ==) y colapsa espacios."""
    return _WHITESPACE_RE.sub(" ", _MARKUP_RE.sub("", value)).strip()


def fold(value: str) -> str:
    """Minúsculas y sin tildes, para comparaciones tolerantes."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).strip()


def to_int(value: object) -> int | None:
    """Convierte 3, 3.0, "3", "3." o "3)" a entero; cualquier otra cosa → None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    match = re.fullmatch(r"\s*(-?\d+)\s*[.)]?\s*", str(value))
    return int(match.group(1)) if match else None


def number_to_str(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def is_likert_label(value: str) -> bool:
    return bool(_LIKERT_HINTS_RE.search(fold(value)))
