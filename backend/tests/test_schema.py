"""Tests del esquema de salida estandarizado."""

import copy

import pytest
from pydantic import ValidationError

from app.schemas.questionnaire import Cuestionario, TipoItem


def _with_item(example: dict, index: int, **changes) -> dict:
    data = copy.deepcopy(example)
    data["items"][index].update(changes)
    return data


def test_spec_example_is_valid_and_round_trips(spec_example):
    questionnaire = Cuestionario.model_validate(spec_example)

    assert questionnaire.total_items == 3
    assert [item.tipo for item in questionnaire.items] == [
        TipoItem.ESCALA_LIKERT,
        TipoItem.SELECCION_MULTIPLE,
        TipoItem.DESARROLLO,
    ]
    assert questionnaire.model_dump(mode="json") == spec_example


def test_output_keys_follow_the_documented_order(spec_example):
    dumped = Cuestionario.model_validate(spec_example).model_dump(mode="json")
    assert list(dumped) == ["titulo", "idioma", "total_items", "items"]
    assert list(dumped["items"][0]) == ["numero", "enunciado", "tipo", "alternativas", "respuesta_correcta"]
    assert list(dumped["items"][0]["alternativas"][0]) == ["valor", "texto"]


def test_all_item_types_are_supported():
    assert {tipo.value for tipo in TipoItem} == {
        "escala_likert",
        "seleccion_multiple",
        "verdadero_falso",
        "desarrollo",
        "emparejamiento",
    }


def test_total_items_must_match_items_length(spec_example):
    spec_example["total_items"] = 5
    with pytest.raises(ValidationError, match="total_items"):
        Cuestionario.model_validate(spec_example)


def test_requires_at_least_one_item(spec_example):
    spec_example["items"] = []
    spec_example["total_items"] = 0
    with pytest.raises(ValidationError):
        Cuestionario.model_validate(spec_example)


def test_item_numbers_must_be_unique(spec_example):
    spec_example["items"][2]["numero"] = 1
    with pytest.raises(ValidationError, match="únicos"):
        Cuestionario.model_validate(spec_example)


@pytest.mark.parametrize("idioma", ["italiano", "IT", "i", ""])
def test_language_must_be_iso_639_1(spec_example, idioma):
    spec_example["idioma"] = idioma
    with pytest.raises(ValidationError):
        Cuestionario.model_validate(spec_example)


def test_unknown_item_type_is_rejected(spec_example):
    with pytest.raises(ValidationError):
        Cuestionario.model_validate(_with_item(spec_example, 0, tipo="ensayo"))


def test_extra_fields_are_rejected(spec_example):
    with pytest.raises(ValidationError):
        Cuestionario.model_validate(_with_item(spec_example, 0, puntaje=3))


def test_open_question_cannot_have_alternatives(spec_example):
    data = _with_item(spec_example, 2, alternativas=[{"valor": "A", "texto": "x"}, {"valor": "B", "texto": "y"}])
    with pytest.raises(ValidationError, match="desarrollo"):
        Cuestionario.model_validate(data)


def test_multiple_choice_needs_at_least_two_alternatives(spec_example):
    data = _with_item(spec_example, 1, alternativas=[{"valor": "A", "texto": "18"}], respuesta_correcta="A")
    with pytest.raises(ValidationError, match="al menos 2"):
        Cuestionario.model_validate(data)


def test_likert_values_must_be_integers(spec_example):
    data = _with_item(spec_example, 0, alternativas=[{"valor": "A", "texto": "Mai"}, {"valor": "B", "texto": "Sempre"}])
    with pytest.raises(ValidationError, match="enteros"):
        Cuestionario.model_validate(data)


def test_likert_has_no_correct_answer(spec_example):
    with pytest.raises(ValidationError, match="Likert"):
        Cuestionario.model_validate(_with_item(spec_example, 0, respuesta_correcta=2))


def test_correct_answer_must_be_one_of_the_alternatives(spec_example):
    with pytest.raises(ValidationError, match="no coincide"):
        Cuestionario.model_validate(_with_item(spec_example, 1, respuesta_correcta="D"))


def test_duplicate_alternative_values_are_rejected(spec_example):
    alternatives = [{"valor": "A", "texto": "18"}, {"valor": "A", "texto": "24"}]
    with pytest.raises(ValidationError, match="duplicados"):
        Cuestionario.model_validate(_with_item(spec_example, 1, alternativas=alternatives, respuesta_correcta=None))


def test_multiple_choice_accepts_several_correct_answers(spec_example):
    questionnaire = Cuestionario.model_validate(_with_item(spec_example, 1, respuesta_correcta="A,C"))
    assert questionnaire.items[1].respuesta_correcta == "A,C"


def test_true_false_uses_v_and_f_values():
    item = {
        "numero": 1,
        "enunciado": "Il sole sorge a est.",
        "tipo": "verdadero_falso",
        "alternativas": [{"valor": "V", "texto": "Vero"}, {"valor": "F", "texto": "Falso"}],
        "respuesta_correcta": "V",
    }
    valid = {"titulo": "T", "idioma": "it", "total_items": 1, "items": [item]}
    assert Cuestionario.model_validate(valid).items[0].respuesta_correcta == "V"

    invalid = copy.deepcopy(valid)
    invalid["items"][0]["alternativas"] = [{"valor": "A", "texto": "Vero"}, {"valor": "B", "texto": "Falso"}]
    invalid["items"][0]["respuesta_correcta"] = "A"
    with pytest.raises(ValidationError, match="'V' y 'F'"):
        Cuestionario.model_validate(invalid)


def test_matching_item_accepts_shared_alternatives():
    alternatives = [{"valor": "A", "texto": "Montevideo"}, {"valor": "B", "texto": "Lima"}]
    data = {
        "titulo": "Capitales",
        "idioma": "es",
        "total_items": 2,
        "items": [
            {"numero": 1, "enunciado": "Perú", "tipo": "emparejamiento", "alternativas": alternatives,
             "respuesta_correcta": "B"},
            {"numero": 2, "enunciado": "Uruguay", "tipo": "emparejamiento", "alternativas": alternatives,
             "respuesta_correcta": "A"},
        ],
    }  # fmt: skip
    assert Cuestionario.model_validate(data).total_items == 2
