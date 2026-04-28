"""FastAPI-Einstiegspunkt.

Lifespan startet/stoppt den MQTT-Subscriber (Sprint 5).
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from heizung import __version__
from heizung.api.v1 import router as v1_router
from heizung.config import get_settings
from heizung.services.mqtt_subscriber import start_subscriber, stop_subscriber

settings = get_settings()

# Stdlib-Logging an uvicorn-Stream binden, damit logger.info() aus
# heizung-Modulen sichtbar wird. Uvicorn richtet nur seine eigenen
# Logger ein - unsere Anwendungs-Logger brauchen einen Root-Handler.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if settings.mqtt_enabled:
        start_subscriber()
    try:
        yield
    finally:
        if settings.mqtt_enabled:
            await stop_subscriber()


app = FastAPI(
    title="Heizungssteuerung Hotel Sonnblick",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)
app.include_router(v1_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness-Probe für Monitoring und Reverse-Proxy."""
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
    }
