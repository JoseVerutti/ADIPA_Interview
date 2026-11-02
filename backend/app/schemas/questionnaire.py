"""Esquema de salida estandarizado (contrato público de la API).

Además de los tipos, el esquema valida la coherencia interna de cada ítem: un
ítem de desarrollo no tiene alternativas, una escala Likert usa valores enteros,
la respuesta correcta debe ser una de las alternativas, etc. Así, cualquier JSON
que salga de la API cumple las reglas, venga del LLM o del extractor heurístico.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TipoItem(StrEnum):
    ESCALA_LIKERT = "escala_likert"
    SELECCION_MULTIPLE = "seleccion_multiple"
    VERDADERO_FALSO = "verdadero_falso"
    DESARROLLO = "desarrollo"
    EMPAREJAMIENTO = "emparejamiento"


TIPOS_CON_ALTERNATIVAS = {
    TipoItem.ESCALA_LIKERT,
    TipoItem.SELECCION_MULTIPLE,
    TipoItem.VERDADERO_FALSO,
    TipoItem.EMPAREJAMIENTO,
}


class Alternativa(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valor: int | str = Field(description="Entero en escalas Likert; letra (A, B, C…) o V/F en el resto.")
    texto: str = Field(min_length=1)


class Item(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: int = Field(ge=1)
    enunciado: str = Field(min_length=1)
    tipo: TipoItem
    alternativas: list[Alternativa] = Field(default_factory=list)
    respuesta_correcta: int | str | None = None

    @model_validator(mode="after")
    def _validar_coherencia(self) -> "Item":
        valores = [alternativa.valor for alternativa in self.alternativas]
        if len({str(valor) for valor in valores}) != len(valores):
            raise ValueError(f"El ítem {self.numero} tiene valores de alternativa duplicados.")

        if self.tipo is TipoItem.DESARROLLO:
            if self.alternativas:
                raise ValueError(f"El ítem {self.numero} es de desarrollo y no debe tener alternativas.")
            return self

        if len(self.alternativas) < 2:
            raise ValueError(f"El ítem {self.numero} ({self.tipo.value}) requiere al menos 2 alternativas.")

        if self.tipo is TipoItem.ESCALA_LIKERT:
            if not all(isinstance(valor, int) for valor in valores):
                raise ValueError(f"El ítem {self.numero} es Likert: los valores deben ser enteros.")
            if self.respuesta_correcta is not None:
                raise ValueError(f"El ítem {self.numero} es Likert: no tiene respuesta correcta.")
            return self

        if not all(isinstance(valor, str) for valor in valores):
            raise ValueError(f"El ítem {self.numero} ({self.tipo.value}): los valores deben ser texto.")

        if self.tipo is TipoItem.VERDADERO_FALSO and sorted(valores) != ["F", "V"]:
            raise ValueError(f"El ítem {self.numero} es verdadero/falso: los valores deben ser 'V' y 'F'.")

        if self.respuesta_correcta is not None:
            # Selección múltiple admite varias respuestas correctas separadas por coma ("A,C").
            respuestas = str(self.respuesta_correcta).split(",")
            if self.tipo is not TipoItem.SELECCION_MULTIPLE and len(respuestas) > 1:
                raise ValueError(f"El ítem {self.numero} admite una sola respuesta correcta.")
            if any(respuesta not in valores for respuesta in respuestas):
                raise ValueError(f"La respuesta correcta del ítem {self.numero} no coincide con ninguna alternativa.")
        return self


class Cuestionario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: str = Field(min_length=1)
    idioma: str = Field(
        pattern=r"^([a-z]{2}|und)$",
        description="Código ISO 639-1 del idioma del documento ('und' si no se pudo determinar).",
    )
    total_items: int = Field(ge=1)
    items: list[Item] = Field(min_length=1)

    @model_validator(mode="after")
    def _validar_totales(self) -> "Cuestionario":
        if self.total_items != len(self.items):
            raise ValueError("total_items no coincide con la cantidad de ítems.")
        numeros = [item.numero for item in self.items]
        if len(set(numeros)) != len(numeros):
            raise ValueError("Los números de ítem deben ser únicos.")
        return self
