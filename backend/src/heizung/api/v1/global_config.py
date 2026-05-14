"""Hotel-globale Konfiguration als Singleton-API (Sprint 8.6, AE-28).

    GET    /api/v1/global-config            -> immer Singleton-Row id=1
    PATCH  /api/v1/global-config            -> Partial-Update, min. 1 Feld

Singleton wird vom Seed (oder Migration 0003a) angelegt. Wenn die Row
fehlt, wird sie beim ersten GET on-the-fly mit Defaults erzeugt — robust
gegen Setup-Reihenfolge-Probleme.

Sprint 9.14 (AE-46): PATCH schreibt pro geaendertem Feld einen
``config_audit``-Eintrag, atomar mit dem UPDATE in derselben Transaktion.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.global_config import GlobalConfig
from heizung.schemas.global_config import GlobalConfigRead, GlobalConfigUpdate
from heizung.services.config_audit_service import record_config_change

router = APIRouter(prefix="/global-config", tags=["global-config"])

SINGLETON_ID = 1
AUDIT_TABLE = "global_config"
AUDIT_SCOPE = "singleton"
AUDIT_SOURCE = "api"


async def _get_or_create_singleton(session: AsyncSession) -> GlobalConfig:
    """Holt die Singleton-Row, legt sie mit Defaults an wenn nicht vorhanden."""
    cfg = await session.get(GlobalConfig, SINGLETON_ID)
    if cfg is None:
        cfg = GlobalConfig(id=SINGLETON_ID)
        session.add(cfg)
        await session.commit()
        await session.refresh(cfg)
    return cfg


@router.get(
    "",
    response_model=GlobalConfigRead,
    summary="Hotel-globale Konfiguration lesen",
)
async def get_global_config(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> GlobalConfig:
    return await _get_or_create_singleton(session)


# AUTH_TODO_9_17: NextAuth-Schutz fuer PATCH-Handler einfuegen, sobald
# Sprint 9.17 NextAuth bereitstellt. Bis dahin ist der Endpoint offen
# und wird per ``request_ip`` in ``config_audit`` getrackt.
@router.patch(
    "",
    response_model=GlobalConfigRead,
    summary="Hotel-globale Konfiguration partiell aktualisieren",
)
async def update_global_config(
    payload: GlobalConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> GlobalConfig:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )

    cfg = await _get_or_create_singleton(session)
    request_ip = request.client.host if request.client else None

    for field, new_value in updates.items():
        old_value = getattr(cfg, field)
        if old_value == new_value:
            continue
        setattr(cfg, field, new_value)
        await record_config_change(
            session,
            source=AUDIT_SOURCE,
            table_name=AUDIT_TABLE,
            scope_qualifier=AUDIT_SCOPE,
            column_name=field,
            old_value=old_value,
            new_value=new_value,
            request_ip=request_ip,
        )

    await session.commit()
    await session.refresh(cfg)
    return cfg
