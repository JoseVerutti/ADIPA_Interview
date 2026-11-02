"""Configuración de la aplicación, leída desde variables de entorno (o un archivo .env)."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    app_name: str = "Questionnaire Extractor API"
    environment: str = "development"
    log_level: str = "INFO"

    # Orígenes permitidos para CORS, separados por coma. El regex opcional sirve
    # para aceptar, por ejemplo, las URLs de preview de Vercel.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_origin_regex: str | None = None

    max_file_size_mb: float = Field(default=10, gt=0)
    max_text_chars: int = Field(default=120_000, gt=0)

    llm_provider: Literal["gemini", "groq", "none"] = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_max_attempts: int = Field(default=2, ge=1, le=5)

    # Si el LLM falla (cuota, red, sin API key) se usa el extractor basado en reglas.
    heuristic_fallback: bool = True

    # Jev (TypeSafe AI): clasificador para las decisiones de clasificación. Opcional: sin
    # key, o si Jev falla, el sistema usa sus reglas. Acepta JEV_API_KEY o TYPESAFE_API_KEY.
    jev_api_key: str | None = Field(default=None, validation_alias=AliasChoices("JEV_API_KEY", "TYPESAFE_API_KEY"))
    jev_model: str = "jev-1.14.0"
    jev_timeout_seconds: float = Field(default=10, gt=0)
    jev_max_concurrency: int = Field(default=8, ge=1, le=64)
    # Confianza mínima para aceptar una elección de Jev (si no, deciden las reglas).
    jev_min_confidence: float = Field(default=0.6, ge=0, le=1)
    # Si la probabilidad de que el documento sea un cuestionario es menor, se rechaza sin llamar al LLM.
    jev_gate_threshold: float = Field(default=0.1, ge=0, le=1)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_file_size_bytes(self) -> int:
        return int(self.max_file_size_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
