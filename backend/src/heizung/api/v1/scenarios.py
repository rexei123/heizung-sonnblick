"""Szenario-API (Sprint 9.16, AE-49).

    GET   /api/v1/scenarios
    POST  /api/v1/scenarios/{code}/activate    body: {"scope": "global"}
    POST  /api/v1/scenarios/{code}/deactivate  body: {"scope": "global"}

Heute nur ``scope=global``. ``room_type`` / ``room`` liefern 400 mit
Hinweis auf Sprint 9.16b. Jede (De-)Aktivierung erzeugt einen
``config_audit``-Eintrag, atomar mit dem UPDATE in derselben Transaktion.

AUTH_TODO_9_17: Heute kein Auth-Schutz. NextAuth-Integration ist
Sprint 9.17 — bis dahin loggt der Handler ``request.client.host`` als
``request_ip``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import get_session
from heizung.models.enums import ScenarioScope
from heizung.models.scenario import Scenario
from heizung.models.scenario_assignment import ScenarioAssignment
from heizung.schemas.scenario import ScenarioRead
from heizung.services.config_audit_service import record_config_change

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

AUDIT_TABLE = "scenario_assignment"
AUDIT_COLUMN = "is_active"
AUDIT_SOURCE = "api"


class ScenarioToggleRequest(BaseModel):
    """Body fuer (De-)Aktivierung. Heute nur ``scope='global'``."""

    model_config = ConfigDict(extra="forbid")
    scope: Literal["global"]


class ScenarioListItem(ScenarioRead):
    """Erweitert ``ScenarioRead`` um den aktuellen GLOBAL-Aktivierungs-
    Status (UI braucht das fuer die Card-Anzeige)."""

    current_global_assignment_active: bool


async def _get_scenario_or_404(session: AsyncSession, code: str) -> Scenario:
    stmt = select(Scenario).where(Scenario.code == code)
    scen = (await session.execute(stmt)).scalar_one_or_none()
    if scen is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"scenario '{code}' nicht gefunden",
        )
    return scen


async def _get_global_assignment(
    session: AsyncSession, scenario_id: int
) -> ScenarioAssignment | None:
    stmt = (
        select(ScenarioAssignment)
        .where(ScenarioAssignment.scenario_id == scenario_id)
        .where(ScenarioAssignment.scope == ScenarioScope.GLOBAL)
        .where(ScenarioAssignment.room_type_id.is_(None))
        .where(ScenarioAssignment.room_id.is_(None))
        .where(ScenarioAssignment.season_id.is_(None))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _audit_payload(scenario_code: str, scope: str, is_active: bool) -> dict[str, object]:
    return {
        "scenario_code": scenario_code,
        "scope": scope,
        "is_active": is_active,
    }


@router.get(
    "",
    response_model=list[ScenarioListItem],
    summary="Szenario-Liste mit aktuellem GLOBAL-Aktivierungs-Status",
)
async def list_scenarios(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[ScenarioListItem]:
    scens = list((await session.execute(select(Scenario).order_by(Scenario.id))).scalars().all())
    items: list[ScenarioListItem] = []
    for scen in scens:
        asgn = await _get_global_assignment(session, scen.id)
        items.append(
            ScenarioListItem.model_validate(
                {
                    "id": scen.id,
                    "code": scen.code,
                    "name": scen.name,
                    "description": scen.description,
                    "is_system": scen.is_system,
                    "default_active": scen.default_active,
                    "parameter_schema": scen.parameter_schema,
                    "default_parameters": scen.default_parameters,
                    "created_at": scen.created_at,
                    "updated_at": scen.updated_at,
                    "current_global_assignment_active": bool(asgn and asgn.is_active),
                }
            )
        )
    return items


async def _set_active(
    session: AsyncSession,
    *,
    code: str,
    request: Request,
    new_active: bool,
) -> ScenarioAssignment:
    scen = await _get_scenario_or_404(session, code)
    asgn = await _get_global_assignment(session, scen.id)

    if asgn is None:
        old_active = False
        asgn = ScenarioAssignment(
            scenario_id=scen.id,
            scope=ScenarioScope.GLOBAL,
            is_active=new_active,
        )
        session.add(asgn)
    else:
        old_active = asgn.is_active
        if old_active == new_active:
            # Idempotent: kein Audit-Spam, kein Commit noetig.
            return asgn
        asgn.is_active = new_active

    request_ip = request.client.host if request.client else None
    await record_config_change(
        session,
        source=AUDIT_SOURCE,
        table_name=AUDIT_TABLE,
        scope_qualifier="global",
        column_name=AUDIT_COLUMN,
        old_value=_audit_payload(code, "global", old_active),
        new_value=_audit_payload(code, "global", new_active),
        request_ip=request_ip,
    )
    await session.commit()
    await session.refresh(asgn)
    return asgn


def _reject_non_global(scope: str) -> None:
    if scope != "global":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"scope='{scope}' wird heute nicht unterstuetzt; "
                "nur 'global' (kommt in Sprint 9.16b)."
            ),
        )


# AUTH_TODO_9_17: NextAuth-Schutz fuer beide POST-Handler einfuegen,
# sobald Sprint 9.17 NextAuth bereitstellt. Bis dahin ist der Endpoint
# offen und wird per ``request_ip`` in ``config_audit`` getrackt.
@router.post(
    "/{code}/activate",
    response_model=ScenarioListItem,
    summary="Szenario global aktivieren (idempotent)",
)
async def activate_scenario(
    payload: ScenarioToggleRequest,
    request: Request,
    code: str = Path(..., min_length=1, max_length=50),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ScenarioListItem:
    _reject_non_global(payload.scope)
    asgn = await _set_active(session, code=code, request=request, new_active=True)
    scen = await _get_scenario_or_404(session, code)
    return ScenarioListItem.model_validate(
        {
            "id": scen.id,
            "code": scen.code,
            "name": scen.name,
            "description": scen.description,
            "is_system": scen.is_system,
            "default_active": scen.default_active,
            "parameter_schema": scen.parameter_schema,
            "default_parameters": scen.default_parameters,
            "created_at": scen.created_at,
            "updated_at": scen.updated_at,
            "current_global_assignment_active": asgn.is_active,
        }
    )


# AUTH_TODO_9_17: siehe activate_scenario.
@router.post(
    "/{code}/deactivate",
    response_model=ScenarioListItem,
    summary="Szenario global deaktivieren (idempotent)",
)
async def deactivate_scenario(
    payload: ScenarioToggleRequest,
    request: Request,
    code: str = Path(..., min_length=1, max_length=50),
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ScenarioListItem:
    _reject_non_global(payload.scope)
    asgn = await _set_active(session, code=code, request=request, new_active=False)
    scen = await _get_scenario_or_404(session, code)
    return ScenarioListItem.model_validate(
        {
            "id": scen.id,
            "code": scen.code,
            "name": scen.name,
            "description": scen.description,
            "is_system": scen.is_system,
            "default_active": scen.default_active,
            "parameter_schema": scen.parameter_schema,
            "default_parameters": scen.default_parameters,
            "created_at": scen.created_at,
            "updated_at": scen.updated_at,
            "current_global_assignment_active": asgn.is_active,
        }
    )
