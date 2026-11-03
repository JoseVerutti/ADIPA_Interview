"""Contrato de los clasificadores: decisiones de clasificación separadas de la extracción generativa.

Toda decisión del tipo "¿es X o Y?" pasa por un ``Classifier``. Hay dos implementaciones:
- ``JevClassifier``: usa Jev (TypeSafe AI), un modelo no generativo especializado en
  clasificar, con probabilidades calibradas y un costo muy inferior al de un LLM.
- ``NoopClassifier``: no decide nada (devuelve ``None``) y el sistema usa sus reglas
  y el tipo propuesto por el extractor. Es el comportamiento cuando no hay API key, y
  la red de seguridad cuando Jev falla.

Los métodos devuelven ``None`` cuando no hay una decisión confiable: quien llama
siempre tiene una alternativa determinista.
"""

from dataclasses import dataclass, field
from typing import Protocol

from app.schemas.questionnaire import TipoItem


@dataclass(frozen=True)
class ItemQuery:
    """Un ítem extraído que el clasificador debe revisar."""

    enunciado: str
    alternativas: list[str] = field(default_factory=list)
    # Tipos que la estructura del ítem permite; el primero es el que propone el extractor
    # (LLM o reglas). Con un solo candidato el tipo ya está decidido y no se consulta.
    candidates: tuple[TipoItem, ...] = ()
    # Otros ítems con exactamente las mismas alternativas. Sin este contexto, una premisa de
    # emparejamiento ("Perú" + capitales) es indistinguible de una selección múltiple.
    siblings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ItemReview:
    """Resultado de revisar un ítem. ``None`` en un campo = sin decisión confiable."""

    # Probabilidad de que la entrada sea un ítem real (y no una instrucción, un título
    # o un campo de datos personales).
    is_item_probability: float | None = None
    tipo: TipoItem | None = None


class Classifier(Protocol):
    name: str | None

    async def questionnaire_probability(self, text: str) -> float | None:
        """Probabilidad (0-1) de que el documento contenga un cuestionario."""
        ...

    async def review_items(self, queries: list[ItemQuery]) -> list[ItemReview]:
        """Una revisión por consulta, en el mismo orden."""
        ...

    async def detect_language(self, text: str) -> str | None:
        """Código ISO 639-1 del idioma, o ``None``."""
        ...


class NoopClassifier:
    """Clasificador nulo: el sistema funciona solo con reglas y con lo que propone el extractor."""

    name = None

    async def questionnaire_probability(self, text: str) -> float | None:
        return None

    async def review_items(self, queries: list[ItemQuery]) -> list[ItemReview]:
        return [ItemReview() for _ in queries]

    async def detect_language(self, text: str) -> str | None:
        return None
