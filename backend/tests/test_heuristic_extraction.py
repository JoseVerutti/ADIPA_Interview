from app.schemas.questionnaire import TipoItem
from app.services.heuristic_extraction_service import HeuristicExtractionService
from app.services.normalization_service import QuestionnaireNormalizer


def extract(text: str, idioma: str = "es"):
    raw = HeuristicExtractionService().extract(text)
    return QuestionnaireNormalizer().normalize(raw, idioma=idioma, source_name="doc.pdf")


def test_spec_example_layout_is_recognized(spec_example):
    text = "\n".join([
        "Questionario di esempio",
        "Scala: 0 = Mai, 1 = A volte, 2 = Spesso, 3 = Sempre",
        "1. Mi preoccupo eccessivamente per cose di poca importanza.",
        "Sezione B - Scelta multipla",
        "2. Quale numero completa la serie: 2, 4, 8, 16, ...?",
        "A) 18",
        "B) 24",
        "C) 32",
        "Sezione C - Domande aperte",
        "3. Descriva una situazione recente in cui si è sentito sotto pressione.",
        "Soluzioni: 2-C",
    ])  # fmt: skip
    result = extract(text, idioma="it")
    assert result.model_dump(mode="json") == spec_example


def test_inline_answer_and_marked_options():
    text = "\n".join([
        "1. ¿Capital de Chile?",
        "a) Valparaíso",
        "b) Santiago",
        "Respuesta: b",
        "2. ¿Cuántos minutos tiene una hora?",
        "a) 30",
        "*b) 60",
        "3. ¿Cuántos días tiene una semana?",
        "a) 5",
        "b) 7 (correcta)",
    ])  # fmt: skip
    result = extract(text)
    assert [item.respuesta_correcta for item in result.items] == ["B", "B", "B"]


def test_inline_options_on_a_single_line():
    result = extract("1. ¿Cuál es una fruta?\nA) Mesa   B) Pera   C) Silla")
    assert [a.texto for a in result.items[0].alternativas] == ["Mesa", "Pera", "Silla"]


def test_true_false_section_and_answer_key():
    text = "\n".join([
        "Sección 1 - Verdadero o falso",
        "1. El sol es una estrella.",
        "2. La Luna es un planeta.",
        "Clave de respuestas: 1-V, 2-F",
    ])  # fmt: skip
    result = extract(text)
    assert all(item.tipo is TipoItem.VERDADERO_FALSO for item in result.items)
    assert [item.respuesta_correcta for item in result.items] == ["V", "F"]


def test_matching_exercise_shares_the_options():
    text = "\n".join([
        "Emparejamiento: relacione cada país con su capital.",
        "1. Perú",
        "2. Uruguay",
        "A. Montevideo",
        "B. Lima",
        "Respuestas: 1-B, 2-A",
    ])  # fmt: skip
    result = extract(text)
    assert [item.tipo for item in result.items] == [TipoItem.EMPAREJAMIENTO] * 2
    assert [a.texto for a in result.items[0].alternativas] == ["Montevideo", "Lima"]
    assert [item.respuesta_correcta for item in result.items] == ["B", "A"]


def test_likert_table_with_scale_in_header():
    text = "\n".join([
        "Hábitos de estudio",
        "N° | Afirmación | Nunca | A veces | Siempre",
        "1 | Planifico mis horas de estudio. | | |",
        "2 | Estudio sin distracciones. | | |",
    ])  # fmt: skip
    result = extract(text)
    assert result.titulo == "Hábitos de estudio"
    assert [item.tipo for item in result.items] == [TipoItem.ESCALA_LIKERT] * 2
    assert [(a.valor, a.texto) for a in result.items[0].alternativas] == [(0, "Nunca"), (1, "A veces"), (2, "Siempre")]


def test_spreadsheet_with_type_options_and_answer_columns():
    text = "\n".join([
        "[Hoja: Quiz]",
        "Quiz",
        "No. | Question | Type | A | B | C | Correct answer",
        "1 | Red planet? | Multiple choice | Venus | Mars | Saturn | B",
        "2 | Water freezes at 0 °C. | True/False | | | | True",
        "3 | Describe your city. | Open | | | |",
    ])  # fmt: skip
    result = extract(text, idioma="en")
    assert [item.tipo for item in result.items] == [
        TipoItem.SELECCION_MULTIPLE,
        TipoItem.VERDADERO_FALSO,
        TipoItem.DESARROLLO,
    ]
    assert [item.respuesta_correcta for item in result.items] == ["B", "V", None]
    assert [a.texto for a in result.items[1].alternativas] == ["True", "False"]


def test_wrapped_statement_lines_are_joined():
    result = extract("1. Me preocupo por cosas\nde poca importancia.\n2. Otra pregunta abierta.")
    assert result.items[0].enunciado == "Me preocupo por cosas de poca importancia."
    assert result.total_items == 2


def test_text_without_items_yields_no_items():
    raw = HeuristicExtractionService().extract("Informe trimestral\nVentas en alza durante el periodo.")
    assert raw.items == []
