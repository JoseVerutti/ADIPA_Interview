"""Estructura intermedia y tolerante producida por los extractores (LLM o heurístico).

Acepta datos imperfectos (números como texto, alternativas como strings sueltos,
tipos con sinónimos…). ``QuestionnaireNormalizer`` la convierte después en el
esquema estricto ``Cuestionario``.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RawAlternative(BaseModel):
    model_config = ConfigDict(extra="ignore")

    valor: int | float | str | None = None
    texto: str = ""

    @field_validator("texto", mode="before")
    @classmethod
    def _texto_a_str(cls, value: Any) -> str:
        return "" if value is None else str(value)


class RawItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    numero: int | float | str | None = None
    enunciado: str = ""
    tipo: str | None = None
    alternativas: list[RawAlternative] = Field(default_factory=list)
    respuesta_correcta: bool | int | float | str | None = None

    @field_validator("enunciado", mode="before")
    @classmethod
    def _enunciado_a_str(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("alternativas", mode="before")
    @classmethod
    def _alternativas_flexibles(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [{"texto": entry} if isinstance(entry, str | int | float) else entry for entry in value]
        return value


class RawQuestionnaire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    titulo: str | None = None
    idioma: str | None = None
    items: list[RawItem] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _items_nulos(cls, value: Any) -> Any:
        return [] if value is None else value
