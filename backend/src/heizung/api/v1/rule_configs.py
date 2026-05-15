"""rule_config-API (Sprint 9.14, AE-46; Sprint 9.17 admin-secured).

Heute nur Scope=GLOBAL. Roomtyp- und Room-Scope kommen mit Sprint 9.15/9.16
(Profile/Szenarien) — Out-of-Scope fuer 9.14.

    GET    /api/v1/rule-configs/global   -> 6 Engine-Felder + Timestamps
    PATCH  /api/v1/rule-configs/global   -> partial update, config_audit pro Feld

Audit: jeder geaenderte Feld-Wert schreibt einen Eintrag in
``config_audit`` (Service ``record_config_change``), atomar mit dem
eigentlichen UPDATE in derselben Transaktion. ``user_id`` wird seit
Sprint 9.17 aus dem eingeloggten Admin-Account uebernommen.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_admin, require_user
from heizung.db import get_session
from heizung.models.enums import RuleConfigScope
from heizung.models.rule_config import RuleConfig
from heizung.models.user import User
from heizung.schemas.rule_config import RuleConfigGlobalRead, RuleConfigGlobalUpdate
from heizung.services.config_audit_service import record_config_change

router = APIRouter(prefix="/rule-configs", tags=["rule-configs"])

AUDIT_TABLE = "rule_config"
AUDIT_SCOPE = "global"
AUDIT_SOURCE = "api"


async def _get_global_or_404(session: AsyncSession) -> RuleConfig:
    """Sucht die GLOBAL-Row (scope=global, kein room_type/room/season).

    Wenn nicht vorhanden: 404. Seed (``heizung.seed._seed_global_rule``)
    legt sie beim Deployment an; in produktiven Umgebungen sollte sie
    immer existieren.
    """
    stmt = (
        select(RuleConfig)
        .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
        .where(RuleConfig.room_type_id.is_(None))
        .where(RuleConfig.room_id.is_(None))
        .where(RuleConfig.season_id.is_(None))
    )
    rc = (await session.execute(stmt)).scalar_one_or_none()
    if rc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="rule_config_global_not_found",
        )
    return rc


@router.get(
    "/global",
    response_model=RuleConfigGlobalRead,
    summary="Globale RuleConfig lesen (6 Engine-Felder)",
)
async def get_global_rule_config(
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RuleConfig:
    return await _get_global_or_404(session)


@router.patch(
    "/global",
    response_model=RuleConfigGlobalRead,
    summary="Globale RuleConfig partiell aktualisieren (admin, config_audit pro Feld)",
)
async def update_global_rule_config(
    payload: RuleConfigGlobalUpdate,
    request: Request,
    admin: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> RuleConfig:
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Mindestens ein Feld zur Aktualisierung erforderlich",
        )

    rc = await _get_global_or_404(session)
    request_ip = request.client.host if request.client else None

    for field, new_value in updates.items():
        old_value = getattr(rc, field)
        if old_value == new_value:
            # Idempotenz: kein Audit-Spam fuer No-Op-Updates.
            continue
        setattr(rc, field, new_value)
        await record_config_change(
            session,
            source=AUDIT_SOURCE,
            table_name=AUDIT_TABLE,
            scope_qualifier=AUDIT_SCOPE,
            column_name=field,
            old_value=old_value,
            new_value=new_value,
            user_id=admin.id,
            request_ip=request_ip,
        )

    await session.commit()
    await session.refresh(rc)
    return rc
