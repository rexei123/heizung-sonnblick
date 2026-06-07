"""Integrations-Endpoints (Sprint 15e, AE-66).

Endpoint A — Belegungs-Import-Webhook (mailparser -> Casablanca-Surrogat):
    POST /api/v1/integrations/occupancy-import   (Auth: X-Webhook-Token)
Endpoint B — Import-Status + letzte Importe (Dashboard/Detailseite Sprint 2):
    GET  /api/v1/integrations/occupancy-import/log  (Auth: Login-Session)

Zweckgebunden — KEIN generisches Webhook/api_key-Framework.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_user
from heizung.config import get_settings
from heizung.db import get_session
from heizung.models.user import User
from heizung.schemas.occupancy_import import OccupancyImportLogResponse, OccupancyImportPayload
from heizung.services.occupancy_import_service import (
    OccupancyImportRejectedError,
    get_import_log,
    reconcile_from_import,
)
from heizung.tasks.engine_tasks import evaluate_room as _evaluate_room_task

router = APIRouter(prefix="/integrations", tags=["integrations"])


async def require_webhook_token(
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),  # noqa: B008
) -> None:
    """Konstant-Zeit-Vergleich gegen ``OCCUPANCY_IMPORT_TOKEN``.

    Fehlt das Token-Setting (leer) ODER stimmt der Header nicht ueberein:
    401. Fail-closed — ohne konfiguriertes Secret nimmt der Endpoint nichts
    entgegen.
    """
    expected = get_settings().occupancy_import_token
    provided = x_webhook_token or ""
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungueltiges oder fehlendes X-Webhook-Token",
        )


@router.post(
    "/occupancy-import",
    status_code=status.HTTP_200_OK,
    summary="Taegliche Belegungsliste importieren (mailparser-Webhook)",
)
async def import_occupancy(
    payload: OccupancyImportPayload,
    request: Request,
    _token: None = Depends(require_webhook_token),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, object]:
    request_ip = request.client.host if request.client else None
    try:
        outcome = await reconcile_from_import(session, payload=payload, request_ip=request_ip)
    except OccupancyImportRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unbekannte Zimmernummer(n): {', '.join(exc.unknown_numbers)}",
        ) from exc

    # Engine-Re-Eval erst NACH dem Commit (reconcile committed selbst).
    for room_id in outcome.affected_room_ids:
        _evaluate_room_task.delay(room_id)

    if outcome.status == "already_processed":
        return {"status": "already_processed"}
    return {
        "status": "applied",
        "rooms_occupied": outcome.rooms_occupied,
        "rooms_closed": outcome.rooms_closed,
        "conflicts": outcome.conflicts,
    }


@router.get(
    "/occupancy-import/log",
    response_model=OccupancyImportLogResponse,
    summary="Import-Ampelstatus + letzte 30 Importe",
)
async def occupancy_import_log(
    _user: User = Depends(require_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> OccupancyImportLogResponse:
    settings = get_settings()
    return await get_import_log(
        session,
        expected_by_local_str=settings.occupancy_import_expected_by_local,
    )
