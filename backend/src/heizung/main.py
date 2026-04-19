"""FastAPI-Einstiegspunkt.

Minimales App-Grundgerüst für Sprint 1. Router, Middleware und
Lifespan-Events werden in nachfolgenden Sprints ergänzt.
"""

from fastapi import FastAPI

from heizung import __version__
from heizung.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Heizungssteuerung Hotel Sonnblick",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness-Probe für Monitoring und Reverse-Proxy."""
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
    }
