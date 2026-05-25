"""FastAPI-Einstiegspunkt.

Lifespan startet/stoppt den MQTT-Subscriber (Sprint 5).
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import DBAPIError

from heizung import __version__
from heizung.api.v1 import router as v1_router
from heizung.auth.rate_limit import limiter
from heizung.config import get_settings
from heizung.services.exceptions import DeviceNotFound, LifecycleError
from heizung.services.mqtt_subscriber import start_subscriber, stop_subscriber
from heizung.services.override_service import OverrideError

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
# Sprint 9.17 (AE-50 / R3): slowapi-Rate-Limit auf /auth/login.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

app.include_router(v1_router)


@app.exception_handler(DBAPIError)
async def _dbapi_error_handler(_: Request, exc: DBAPIError) -> JSONResponse:
    """Faengt asyncpg/SQLAlchemy-Datenbank-Fehler ab und antwortet sauber.

    Vorher: Path-Param ausserhalb int4-Range -> 500 Internal Server Error
    mit Stacktrace im Log. QA-Audit K-2.
    """
    logging.getLogger(__name__).warning("db error: %s", str(exc).split("\n")[0][:200])
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Ungueltiger Anfrage-Parameter (Datenbank-Validierung)"},
    )


@app.exception_handler(LifecycleError)
async def _lifecycle_error_handler(_request: Request, exc: LifecycleError) -> JSONResponse:
    """B-Sprint13b2-4 (AE-59): App-weiter Handler fuer Lifecycle-Exceptions.

    Rendert ``{"detail": <message>, "error_code": <CODE>}``. ``DeviceNotFound``
    -> 404, alle anderen Subklassen (``DeviceStateError`` /
    ``PoolDeviceUnavailable`` / ``SelfReplacementError``) -> 409.

    Scope: Lifecycle-Pfade (replace, retire). Override-Pfade nutzen den
    parallelen ``OverrideError``-Handler (B-Sprint13b2-7).
    """
    status_code = (
        status.HTTP_404_NOT_FOUND if isinstance(exc, DeviceNotFound) else status.HTTP_409_CONFLICT
    )
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "error_code": exc.error_code},
    )


@app.exception_handler(OverrideError)
async def _override_error_handler(_request: Request, exc: OverrideError) -> JSONResponse:
    """B-Sprint13b2-7 (AE-59): App-weiter Handler fuer Override-Exceptions.

    Rendert ``{"detail": <message>, "error_code": <CODE>, ...extras}``
    mit ``exc.http_status``. ``extras`` (room_id, zone_id, zones, ...)
    kommen aus ``exc.response_extras()`` und werden als Top-Level-
    Geschwister neben ``detail`` und ``error_code`` gerendert.

    Subklassen (override_service.py):

    - ``InvalidZoneError``                  -> 404 + INVALID_ZONE
    - ``RoomNotOccupiedError``              -> 409 + ROOM_NOT_OCCUPIED
    - ``RoomOverrideBlockedError``          -> 409 + ROOM_OVERRIDE_BLOCKED
    - ``OverrideRejectedWindowOpenError``   -> 409 + OVERRIDE_REJECTED_WINDOW_OPEN
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "detail": exc.message,
            "error_code": exc.error_code,
            **exc.response_extras(),
        },
    )


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Liveness-Probe für Monitoring und Reverse-Proxy."""
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
    }
