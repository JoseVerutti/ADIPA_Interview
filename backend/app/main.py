"""Punto de entrada de la API (``uvicorn app.main:app``)."""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.controllers import health_controller, questionnaire_controller
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, request_id_var

logger = logging.getLogger(__name__)

EXPOSED_HEADERS = [
    "X-Request-ID",
    "X-Processing-Time-Ms",
    "X-Extraction-Method",
    "X-Fallback-Reason",
    "X-Classifier",
]


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Convierte cuestionarios en PDF, Word o Excel a un JSON estandarizado de ítems.",
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        logger.info("Petición rechazada (%s): %s", exc.code, exc.message)
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        missing_file = any(error.get("loc", [None])[-1] == "file" for error in exc.errors())
        message = "Debes adjuntar un archivo en el campo 'file'." if missing_file else "La petición no es válida."
        return error_response(422, "validation_error", message)

    # Se registra ANTES que CORS para que CORS quede por fuera y también decore las respuestas 500.
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Error no controlado en %s %s", request.method, request.url.path)
            response = error_response(500, "internal_error", "Ocurrió un error inesperado al procesar la solicitud.")
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Processing-Time-Ms"] = f"{elapsed_ms:.0f}"
        logger.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code, elapsed_ms)
        request_id_var.reset(token)
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_origin_regex=settings.cors_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=EXPOSED_HEADERS,
    )

    app.include_router(health_controller.router)
    app.include_router(questionnaire_controller.router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"name": settings.app_name, "docs": "/docs", "health": "/api/v1/health"}

    return app


app = create_app()
