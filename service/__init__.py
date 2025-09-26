"""Service package exposing the FastAPI endpoints."""

from .api import app  # re-export for uvicorn convenience

__all__ = ["app"]
