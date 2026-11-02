import pytest

from app.services.language_detection_service import LanguageDetectionService


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Mi preoccupo eccessivamente per cose di poca importanza. Quale numero completa la serie? "
            "Descriva una situazione recente in cui si è sentito sotto pressione.",
            "it",
        ),
        (
            "Me preocupo demasiado por cosas de poca importancia. ¿Qué número completa la serie? "
            "Describa una situación reciente en la que se sintió bajo presión.",
            "es",
        ),
        (
            "I worry too much about things that are not important. Which number completes the series? "
            "Describe a recent situation in which you felt under pressure.",
            "en",
        ),
        (
            "Eu me preocupo muito com coisas sem importância. Qual número completa a série? "
            "Descreva uma situação recente em que você se sentiu sob pressão.",
            "pt",
        ),
    ],
)
def test_detects_language(text, expected):
    assert LanguageDetectionService().detect(text) == expected


@pytest.mark.parametrize("text", ["", "12345 !!!", "Xyzzy plugh"])
def test_returns_und_without_signal(text):
    assert LanguageDetectionService().detect(text) == "und"
