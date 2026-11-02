from fastapi import APIRouter, Depends

from app import __version__
from app.dependencies import get_questionnaire_service
from app.services.questionnaire_service import QuestionnaireService

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", summary="Estado del servicio")
async def health(service: QuestionnaireService = Depends(get_questionnaire_service)) -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "llm_provider": service.llm_provider,
        "classifier": service.classifier_name,
    }
