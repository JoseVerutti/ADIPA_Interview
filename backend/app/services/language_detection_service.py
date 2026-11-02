"""Detección determinística del idioma basada en palabras funcionales (stopwords).

Se eligió un detector propio en lugar de una librería probabilística porque:
- es determinístico (mismo documento → mismo resultado, fácil de testear),
- no requiere dependencias ni red,
- para cuestionarios (texto abundante en artículos, preposiciones y conectores)
  es muy preciso en los idiomas requeridos (it, es, en) y en otros cercanos (pt, fr, de).

Cada palabra pesa 1/N, donde N es la cantidad de idiomas que la comparten: así
"de" o "la" (compartidas) aportan poco, y "che", "the" o "los" aportan mucho.
"""

import re
import unicodedata
from collections import Counter

UNDETERMINED = "und"

_STOPWORDS: dict[str, str] = {
    "es": """el la los las de del que y en un una unos unas por con para es son se no su sus al lo como más
        pero ya o este esta estos estas cuando muy sin sobre también me hasta hay donde quien desde todo
        nos durante todos uno les ni otros ese eso ante ellos e esto antes algunos qué yo otro otra él
        tanto esa mucho nada muchos cual poco ella estar algo usted cuál ha he han fue ser era sido
        está están usted ustedes le pregunta preguntas respuesta respuestas verdadero nunca siempre veces
        frecuentemente cuál cuántos indique marque seleccione alternativa correcta""",
    "it": """il lo la i gli le di da in con su per tra fra un uno una che e è non si mi ti ci vi del dello
        della dei degli delle nel nello nella nei negli nelle al allo alla ai agli alle dal dalla dai sul
        sulla sono come più ma anche se perché questo questa questi queste quale quali quando molto
        sempre mai spesso volte domanda domande risposta risposte vero ho ha hai abbiamo essere stato
        stata suo sua suoi loro cosa ogni dell nell all dall sull quanto indichi indica scegli scelga
        corretta corretto affermazione""",
    "en": """the of and to in is you that it he was for on are as with his they at be this have from or
        one had by but not what all were we when your can said there an each which she do how their
        if will up other about out many then them these so some her would make like him into time has
        two more could people my than been who its now did get may question questions answer answers
        true false never always often sometimes usually rarely choose select statement correct""",
    "pt": """o os as da do das dos em um uma que e não com para por mais mas se na no nas nos ao à ou seu
        sua você também já está são muito quando foi pelo pela isso este esta essa ele ela eles
        verdadeiro sempre nunca às vezes pergunta resposta""",
    "fr": """le la les de des du un une et est en que qui dans pour pas sur au aux ce cette il elle ils
        nous vous je ne se plus par avec son sa ses mais ou où été être avoir fait très toujours jamais
        souvent parfois vrai faux question réponse""",
    "de": """der die das und ist ich nicht ein eine zu den von mit sich des auf für im dem auch es an als
        wie bei oder wird nach aus er sie wir ihr sind war nur noch immer nie oft manchmal frage antwort
        wahr falsch""",
}

_WORD_LANGS: dict[str, set[str]] = {}
for _lang, _words in _STOPWORDS.items():
    for _word in _words.split():
        _WORD_LANGS.setdefault(_word, set()).add(_lang)
_WEIGHTS: dict[str, dict[str, float]] = {
    word: {lang: 1 / len(langs) for lang in langs} for word, langs in _WORD_LANGS.items()
}

# Caracteres muy característicos de un idioma concreto.
_CHAR_HINTS: dict[str, str] = {"ñ": "es", "¿": "es", "¡": "es", "ã": "pt", "õ": "pt", "ß": "de"}

_TOKEN_RE = re.compile(r"[a-zàáâãäçèéêëìíîïñòóôõöùúûüß]+")

_MIN_SCORE = 3.0
_MIN_MARGIN = 1.15


class LanguageDetectionService:
    def detect(self, text: str) -> str:
        """Devuelve el código ISO 639-1 del idioma predominante, o ``"und"`` si no hay señal suficiente."""
        lowered = unicodedata.normalize("NFC", text.lower())
        scores: Counter[str] = Counter()
        for token in _TOKEN_RE.findall(lowered):
            for lang, weight in _WEIGHTS.get(token, {}).items():
                scores[lang] += weight
        for char, lang in _CHAR_HINTS.items():
            scores[lang] += 0.5 * lowered.count(char)

        if not scores:
            return UNDETERMINED
        ranking = scores.most_common(2)
        best_lang, best_score = ranking[0]
        second_score = ranking[1][1] if len(ranking) > 1 else 0.0
        if best_score < _MIN_SCORE or best_score < second_score * _MIN_MARGIN:
            return UNDETERMINED
        return best_lang
