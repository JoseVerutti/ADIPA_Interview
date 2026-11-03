"""Punto de entrada para Vercel: expone la instancia ``app`` de FastAPI.

En local se sigue usando ``uvicorn app.main:app``.
"""

from app.main import app

__all__ = ["app"]
