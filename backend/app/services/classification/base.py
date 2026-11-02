"""Contrato de los clasificadores: decisiones de clasificación separadas de la extracción generativa.

Toda decisión del tipo "¿es X o Y?" pasa por un ``Classifier``. Hay dos implementaciones:
- ``JevClassifier``: usa Jev (TypeSafe AI), un modelo no generativo especializado en
  clasificar, con probabilidades calibradas y un costo muy inferior al de un LLM.
- ``NoopClassifier``: no decide nada (devuelve ``None``) y el sistema usa sus reglas.
  Es el comportamiento cuando no hay API key, y la red de seguridad cuando Jev falla.

Los métodos devuelven ``None`` cuando no hay una decisión confiable: quien llama
siempre tiene una alternativa determinista.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.questionnaire import TipoItem


@dataclass(frozen=True)
class TypeQuery:
    """Un ítem cuyo tipo no se pudo decidir con reglas."""

    enunciado: str
    alternativas: list[str] = field(default_factory=list)
    # Tipos posibles para este ítem; el primero es el que aplicarían las reglas.
    candidates: tuple[TipoItem, ...] = ()


class Classifier(Protocol):
    name: str | None

    async def questionnaire_probability(self, text: str) -> float | None:
        """Probabilidad (0-1) de que el documento contenga un cuestionario."""
        ...

    async def classify_item_types(self, queries: list[TypeQuery]) -> list[TipoItem | None]:
        """Un tipo por consulta (en el mismo orden), o ``None`` si no hay decisión confiable."""
        ...

    async def detect_language(self, text: str) -> str | None:
        """Código ISO 639-1 del idioma, o ``None``."""
        ...


class NoopClassifier:
    """Clasificador nulo: el sistema funciona solo con reglas."""

    name = None

    async def questionnaire_probability(self, text: str) -> float | None:
        return None

    async def classify_item_types(self, queries: list[TypeQuery]) -> list[TipoItem | None]:
        return [None] * len(queries)

    async def detect_language(self, text: str) -> str | None:
        return None
