"""Hotel-globale Konfiguration als Singleton-API (Sprint 8.6, AE-28).

    GET    /api/v1/global-config            -> immer Singleton-Row id=1
    PATCH  /api/v1/global-config            -> Partial-Update, min. 1 Feld

Singleton wird vom Seed (oder Migration 0003a) angelegt. Wenn die Row
fehlt, wird sie beim ersten GET on-the-fly mit Defaults erzeugt — robust
gegen Setup-Reihenfolge-Probleme.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.global_config import GlobalConfig
from heizung.schemas.global_config import GlobalConfigRead, GlobalConfigUpdate

router = APIRouter(prefix="/global-config", tags=["global-config"])

SINGLETON_ID = 1


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


@router.patch(
    "",
    response_model=GlobalConfigRead,
    summary="Hotel-globale Konfiguration partiell aktualisieren",
)
async def update_global_config(
    payload: GlobalConfigUpdate,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> GlobalConfig:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )

    cfg = await _get_or_create_singleton(session)
    for field, value in updates.items():
        setattr(cfg, field, value)
    await session.commit()
    await session.refresh(cfg)
    return cfg
