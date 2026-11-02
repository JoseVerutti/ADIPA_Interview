"""Procesa cada documento de /examples con el mismo servicio que usa la API y guarda el JSON.

Usa la configuración de entorno (.env): con GEMINI_API_KEY/GROQ_API_KEY se extrae con el
LLM; sin API key, con el extractor heurístico.

Uso (desde backend/):  python -m scripts.run_examples [--heuristic]
"""

import asyncio
import json
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.dependencies import build_questionnaire_service
from app.services.file_validation_service import ALLOWED_EXTENSIONS

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


async def main(force_heuristic: bool) -> None:
    settings = get_settings()
    if force_heuristic:
        settings = settings.model_copy(update={"llm_provider": "none"})
    configure_logging(settings.log_level)
    service = build_questionnaire_service(settings)

    documents = sorted(p for p in EXAMPLES_DIR.iterdir() if p.suffix.lower() in ALLOWED_EXTENSIONS)
    for document in documents:
        result = await service.process(document.name, document.read_bytes())
        output = document.with_suffix(".json")
        payload = result.questionnaire.model_dump(mode="json")
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        method = f"llm:{result.provider}" if result.provider else result.method
        print(f"{document.name} -> {output.name}: {result.questionnaire.total_items} ítems ({method})")


if __name__ == "__main__":
    asyncio.run(main(force_heuristic="--heuristic" in sys.argv))
