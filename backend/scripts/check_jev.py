"""Verifica la integración con Jev contra la API real, usando la key del .env.

Comprueba que la key y el modelo funcionan y mide si los umbrales configurados
(JEV_GATE_THRESHOLD, JEV_MIN_CONFIDENCE) deciden bien en español, italiano e inglés:

1. modelos disponibles para la key,
2. filtro "¿es un cuestionario?" sobre los ejemplos y sobre documentos que no lo son,
3. revisión de ítems: si son ítems reales y de qué tipo,
4. detección de idioma.

Uso (desde backend/):  python -m scripts.check_jev
Sale con código 1 si alguna comprobación falla.
"""

import asyncio
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import ClassifierError
from app.schemas.questionnaire import TipoItem
from app.services.classification.base import ItemQuery
from app.services.classification.jev_classifier import JevClassifier
from app.services.classification.jev_client import JevClient
from app.services.file_validation_service import ALLOWED_EXTENSIONS, FileValidationService
from app.services.text_extraction_service import TextExtractionService

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"

SM, LIKERT, VF, OPEN, EMP = (
    TipoItem.SELECCION_MULTIPLE,
    TipoItem.ESCALA_LIKERT,
    TipoItem.VERDADERO_FALSO,
    TipoItem.DESARROLLO,
    TipoItem.EMPAREJAMIENTO,
)

# Textos inventados que NO son cuestionarios: el filtro debe rechazarlos.
NOT_QUESTIONNAIRES = {
    "informe (es)": "Informe trimestral de ventas. Durante el tercer trimestre las ventas crecieron un 12 % "
    "respecto del periodo anterior, impulsadas por la región norte. Se recomienda ampliar el inventario.",
    "ricetta (it)": "Ricetta della pasta al pomodoro. Far bollire l'acqua, salare e cuocere la pasta per dieci "
    "minuti. Nel frattempo scaldare l'olio con l'aglio e aggiungere i pomodori.",
    "invoice (en)": "Invoice #1042. Bill to: Example Company Ltd. Item: annual software license, quantity 1, "
    "unit price 1,200.00 USD. Payment due within 30 days.",
}

CAPITALS = ["Montevideo", "Lima", "Buenos Aires"]

# (consulta, tipo esperado, ¿es un ítem real?). Los candidatos son los que permite la
# estructura; el primero es el tipo que propondría el extractor (a veces equivocado a propósito).
ITEM_CASES = [
    (ItemQuery("Disfruto aprendiendo cosas nuevas.", ["1", "2", "3", "4", "5"], (SM, LIKERT, EMP)), LIKERT, True),
    (ItemQuery("¿Cuál es la capital de Francia?", ["Madrid", "París", "Roma"], (LIKERT, SM, EMP)), SM, True),
    (
        ItemQuery(
            "Mi sento a mio agio con gli altri.",
            ["Pochissimo", "Così così", "Parecchio", "Del tutto"],
            (SM, LIKERT, EMP),
        ),
        LIKERT,
        True,
    ),
    (ItemQuery("Which gas do plants absorb?", ["Oxygen", "Carbon dioxide", "Nitrogen"], (SM, LIKERT, EMP)), SM, True),
    # Emparejamiento: el contexto de las otras premisas que comparten las opciones es imprescindible.
    (ItemQuery("Perú", CAPITALS, (EMP, SM, LIKERT), ["Argentina", "Uruguay"]), EMP, True),
    (ItemQuery("Argentina", CAPITALS, (SM, LIKERT, EMP), ["Perú", "Uruguay"]), EMP, True),  # propuesto: SM
    (
        ItemQuery("¿Tiene usted mascotas?", ["Sí", "No"], (SM, LIKERT, EMP), ["¿Practica algún deporte?"]),
        SM,
        True,
    ),
    (ItemQuery("El agua hierve a 100 °C a nivel del mar.", [], (OPEN, VF)), VF, True),
    (ItemQuery("Roma è la capitale d'Italia.", [], (OPEN, VF)), VF, True),
    (ItemQuery("Describa su rutina de estudio.", [], (OPEN, VF)), OPEN, True),
    (ItemQuery("Me siento nervioso antes de los exámenes.", [], (OPEN, VF)), OPEN, True),  # autoinforme
    # Entradas que no son ítems: deben descartarse.
    (ItemQuery("Nombre y apellido:", [], (OPEN, VF)), OPEN, False),
    (ItemQuery("Fecha de nacimiento", [], (OPEN, VF)), OPEN, False),
    (ItemQuery("Istruzioni: legga attentamente ogni domanda prima di rispondere.", [], (OPEN, VF)), OPEN, False),
    (ItemQuery("Section B - True or false", [], (OPEN, VF)), OPEN, False),
]

LANGUAGE_CASES = {
    "es": "Lea cada pregunta y marque la alternativa correcta.",
    "it": "Legga ogni domanda e segni la risposta corretta.",
    "en": "Read each question and mark the correct answer.",
}


async def main() -> int:
    settings = get_settings()
    if not settings.jev_api_key:
        print("Falta JEV_API_KEY (o TYPESAFE_API_KEY) en backend/.env. Sin ella la app usa solo reglas.")
        return 1

    client = JevClient(settings.jev_api_key, settings.jev_model, timeout=settings.jev_timeout_seconds)
    classifier = JevClassifier(client, min_confidence=settings.jev_min_confidence)
    failures = 0

    print(f"Modelo configurado: {settings.jev_model}")
    print(
        f"Umbrales: filtro < {settings.jev_gate_threshold} rechaza · ítem < {settings.jev_item_threshold} "
        f"se descarta · confianza mínima {settings.jev_min_confidence}"
    )

    print("\n1) Modelos disponibles")
    try:
        models = await client.list_models()
        print(f"   {', '.join(models) or '(lista vacía)'}")
        if models and settings.jev_model not in models:
            # La API solo lista alias (jev-latest, jev-preview); las versiones fijadas como
            # jev-1.14.0 también funcionan. Las llamadas siguientes lo verifican.
            print(f"   i {settings.jev_model} no está listado (solo se listan alias); lo verifican las llamadas")
    except ClassifierError as exc:
        print(f"   ✗ {exc}")
        if "401" in str(exc) or "403" in str(exc):
            print("   La key no es válida: revisa JEV_API_KEY.")
            return 1

    print("\n2) Filtro '¿es un cuestionario?'")
    validator, extractor = FileValidationService(settings.max_file_size_bytes), TextExtractionService()
    gate_cases: list[tuple[str, str, bool]] = []
    for document in sorted(p for p in EXAMPLES_DIR.iterdir() if p.suffix.lower() in ALLOWED_EXTENSIONS):
        content = document.read_bytes()
        gate_cases.append((document.name, extractor.extract(validator.validate(document.name, content), content), True))
    gate_cases += [(name, text, False) for name, text in NOT_QUESTIONNAIRES.items()]
    for name, text, expected in gate_cases:
        probability = await classifier.questionnaire_probability(text)
        if probability is None:
            print(f"   ✗ {name}: sin respuesta de Jev")
            failures += 1
            continue
        passes = probability >= settings.jev_gate_threshold
        ok = passes == expected
        failures += not ok
        verdict = "pasa" if passes else "se rechaza"
        print(f"   {'✓' if ok else '✗'} {name}: p={probability:.3f} → {verdict}")

    print("\n3) Revisión de ítems: ¿es un ítem real? y ¿de qué tipo?")
    reviews = await classifier.review_items([query for query, _, _ in ITEM_CASES])
    for (query, expected_type, expected_item), review in zip(ITEM_CASES, reviews, strict=True):
        probability = review.is_item_probability
        kept = probability is None or probability >= settings.jev_item_threshold
        final = review.tipo or query.candidates[0]
        item_ok = kept == expected_item
        type_ok = final is expected_type or not expected_item  # el tipo de una entrada descartada no importa
        failures += (not item_ok) + (not type_ok)
        p_text = "  —  " if probability is None else f"{probability:.2f}"
        verdict = f"{final.value} ({'Jev' if review.tipo else 'propuesto'})" if kept else "descartada"
        mark = "✓" if item_ok and type_ok else "✗"
        print(f"   {mark} {query.enunciado[:42]:<42} p_ítem={p_text} → {verdict}")

    print("\n4) Idioma")
    for expected, text in LANGUAGE_CASES.items():
        detected = await classifier.detect_language(text)
        ok = detected == expected
        failures += not ok
        print(f"   {'✓' if ok else '✗'} {expected}: Jev → {detected}")

    print(f"\n{'Todo correcto.' if not failures else f'{failures} comprobación(es) fallida(s).'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
