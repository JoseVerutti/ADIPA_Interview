import pytest

from app.core.exceptions import NoItemsDetectedError
from app.schemas.extraction import RawQuestionnaire
from app.schemas.questionnaire import TipoItem
from app.services.normalization_service import QuestionnaireNormalizer


def normalize(items: list[dict], idioma: str = "es", titulo: str | None = "Test"):
    raw = RawQuestionnaire.model_validate({"titulo": titulo, "items": items})
    return QuestionnaireNormalizer().normalize(raw, idioma=idioma, source_name="mi_cuestionario.pdf")


def test_multiple_choice_letters_are_uppercased_and_answer_mapped():
    result = normalize([{
        "numero": 1, "enunciado": "¿2+2?", "tipo": "seleccion_multiple",
        "alternativas": [{"valor": "a", "texto": "a) 3"}, {"valor": "b", "texto": "4"}],
        "respuesta_correcta": "b",
    }])  # fmt: skip
    item = result.items[0]
    assert [(a.valor, a.texto) for a in item.alternativas] == [("A", "3"), ("B", "4")]
    assert item.respuesta_correcta == "B"


def test_numbered_options_are_relabelled_with_letters_and_answer_follows():
    result = normalize([{
        "enunciado": "¿Capital de Italia?", "tipo": "multiple_choice",
        "alternativas": [{"valor": 1, "texto": "Milán"}, {"valor": 2, "texto": "Roma"}],
        "respuesta_correcta": 2,
    }])  # fmt: skip
    item = result.items[0]
    assert [a.valor for a in item.alternativas] == ["A", "B"]
    assert item.respuesta_correcta == "B"


def test_answer_can_be_given_as_option_text():
    result = normalize([{
        "enunciado": "¿Capital de Italia?",
        "alternativas": [{"valor": "A", "texto": "Milán"}, {"valor": "B", "texto": "Roma"}],
        "respuesta_correcta": "roma",
    }])  # fmt: skip
    assert result.items[0].tipo is TipoItem.SELECCION_MULTIPLE
    assert result.items[0].respuesta_correcta == "B"


def test_answer_that_matches_no_alternative_is_discarded():
    result = normalize([{
        "enunciado": "¿2+2?", "tipo": "seleccion_multiple",
        "alternativas": [{"valor": "A", "texto": "3"}, {"valor": "B", "texto": "4"}],
        "respuesta_correcta": "Z",
    }])  # fmt: skip
    assert result.items[0].respuesta_correcta is None


@pytest.mark.parametrize(("idioma", "labels"), [("it", ["Vero", "Falso"]), ("en", ["True", "False"])])
def test_true_false_without_options_gets_localized_labels(idioma, labels):
    result = normalize([{"enunciado": "Statement", "tipo": "true_false", "respuesta_correcta": "False"}], idioma=idioma)
    item = result.items[0]
    assert item.tipo is TipoItem.VERDADERO_FALSO
    assert [(a.valor, a.texto) for a in item.alternativas] == [("V", labels[0]), ("F", labels[1])]
    assert item.respuesta_correcta == "F"


def test_true_false_is_inferred_from_options():
    result = normalize([{
        "enunciado": "La Luna es una estrella.",
        "alternativas": [{"valor": "A", "texto": "Verdadero"}, {"valor": "B", "texto": "Falso"}],
        "respuesta_correcta": "B",
    }])  # fmt: skip
    item = result.items[0]
    assert item.tipo is TipoItem.VERDADERO_FALSO
    assert item.respuesta_correcta == "F"


def test_likert_keeps_document_values():
    result = normalize([{
        "enunciado": "Me siento tranquilo.", "tipo": "likert",
        "alternativas": [{"valor": "1", "texto": "Nunca"}, {"valor": "2", "texto": "A veces"},
                         {"valor": "3", "texto": "Siempre"}],
        "respuesta_correcta": "2",
    }])  # fmt: skip
    item = result.items[0]
    assert [a.valor for a in item.alternativas] == [1, 2, 3]
    assert item.respuesta_correcta is None


def test_likert_without_numbers_is_numbered_from_zero_and_inferred():
    result = normalize([{
        "enunciado": "Mi preoccupo.",
        "alternativas": ["Mai", "A volte", "Spesso", "Sempre"],
    }], idioma="it")  # fmt: skip
    item = result.items[0]
    assert item.tipo is TipoItem.ESCALA_LIKERT
    assert [(a.valor, a.texto) for a in item.alternativas] == [(0, "Mai"), (1, "A volte"), (2, "Spesso"), (3, "Sempre")]


def test_likert_value_embedded_in_label_is_extracted():
    result = normalize([{
        "enunciado": "Me siento tranquilo.", "tipo": "escala_likert",
        "alternativas": [{"texto": "1 = Nunca"}, {"texto": "2 = A veces"}, {"texto": "3 = Siempre"}],
    }])  # fmt: skip
    assert [(a.valor, a.texto) for a in result.items[0].alternativas] == [(1, "Nunca"), (2, "A veces"), (3, "Siempre")]


def test_closed_item_without_alternatives_becomes_open_question():
    result = normalize([{"enunciado": "Describa su día.", "tipo": "seleccion_multiple", "alternativas": []}])
    assert result.items[0].tipo is TipoItem.DESARROLLO


def test_open_question_drops_alternatives_and_keeps_model_answer():
    result = normalize([{"enunciado": "Defina ansiedad.", "tipo": "open", "respuesta_correcta": "Un estado..."}])
    item = result.items[0]
    assert item.tipo is TipoItem.DESARROLLO
    assert item.alternativas == []
    assert item.respuesta_correcta == "Un estado..."


def test_duplicate_or_missing_numbers_are_renumbered():
    result = normalize([
        {"numero": 1, "enunciado": "Uno", "tipo": "desarrollo"},
        {"numero": 1, "enunciado": "Dos", "tipo": "desarrollo"},
        {"enunciado": "Tres", "tipo": "desarrollo"},
    ])  # fmt: skip
    assert [item.numero for item in result.items] == [1, 2, 3]


def test_increasing_document_numbers_are_preserved():
    result = normalize([
        {"numero": 5, "enunciado": "Cinco", "tipo": "desarrollo"},
        {"numero": 6, "enunciado": "Seis", "tipo": "desarrollo"},
    ])  # fmt: skip
    assert [item.numero for item in result.items] == [5, 6]


def test_formatting_markers_and_number_prefix_are_removed():
    result = normalize([{"numero": 3, "enunciado": "3. **Texto   en negrita**", "tipo": "desarrollo"}])
    assert result.items[0].enunciado == "Texto en negrita"


def test_items_without_statement_are_dropped():
    result = normalize([{"enunciado": "  "}, {"enunciado": "Válido", "tipo": "desarrollo"}])
    assert result.total_items == 1
    assert result.items[0].enunciado == "Válido"


def test_raises_when_there_are_no_items():
    with pytest.raises(NoItemsDetectedError):
        normalize([])


def test_title_falls_back_to_file_name():
    result = normalize([{"enunciado": "Uno", "tipo": "desarrollo"}], titulo=None)
    assert result.titulo == "Mi cuestionario"


def test_true_false_mark_is_removed_from_the_statement():
    result = normalize([{"enunciado": "Il sole sorge a est. (V/F)", "tipo": "verdadero_falso"}], idioma="it")
    assert result.items[0].enunciado == "Il sole sorge a est."
