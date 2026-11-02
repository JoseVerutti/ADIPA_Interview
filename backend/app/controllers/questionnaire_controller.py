from fastapi import APIRouter, Depends, File, Response, UploadFile

from app.core.config import Settings, get_settings
from app.dependencies import get_questionnaire_service
from app.schemas.errors import ErrorResponse
from app.schemas.questionnaire import Cuestionario
from app.services.questionnaire_service import QuestionnaireService

router = APIRouter(prefix="/api/v1/questionnaires", tags=["questionnaires"])

_ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Archivo inválido, dañado o protegido."},
    413: {"model": ErrorResponse, "description": "Archivo o documento demasiado grande."},
    415: {"model": ErrorResponse, "description": "Formato no soportado (solo PDF, DOCX y XLSX)."},
    422: {"model": ErrorResponse, "description": "Documento sin texto o sin ítems detectables."},
    502: {"model": ErrorResponse, "description": "Falló el proveedor LLM y no hay respaldo."},
}


@router.post(
    "/extract",
    response_model=Cuestionario,
    responses=_ERROR_RESPONSES,
    summary="Extrae los ítems de un cuestionario",
    description=(
        "Recibe un documento PDF, DOCX o XLSX y devuelve sus ítems, tipos, alternativas y "
        "respuestas correctas en el formato JSON estandarizado. La cabecera `X-Extraction-Method` "
        "indica si se usó el LLM (`llm:<proveedor>`) o el extractor heurístico (`heuristic`)."
    ),
)
async def extract_questionnaire(
    response: Response,
    file: UploadFile = File(..., description="Documento PDF, DOCX o XLSX"),
    service: QuestionnaireService = Depends(get_questionnaire_service),
    settings: Settings = Depends(get_settings),
) -> Cuestionario:
    # Se lee como máximo el límite + 1 byte: suficiente para detectar archivos demasiado grandes
    # sin cargar en memoria un archivo arbitrariamente grande.
    content = await file.read(settings.max_file_size_bytes + 1)
    result = await service.process(file.filename, content)

    response.headers["X-Extraction-Method"] = f"llm:{result.provider}" if result.provider else result.method
    if result.fallback_reason:
        response.headers["X-Fallback-Reason"] = result.fallback_reason
    return result.questionnaire
