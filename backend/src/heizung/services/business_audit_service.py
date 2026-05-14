"""Service fuer business_audit (Sprint 9.17, AE-50).

Schreibt einen Audit-Eintrag pro operativer Aktion (Belegungs-CRUD,
Manual-Override-Set/Clear, Password-Change). Atomar mit dem
eigentlichen UPDATE — der Aufrufer haelt den Commit zurueck.

JSONB-Serialisierung folgt demselben Pattern wie
``config_audit_service`` (Decimal als String, time/date/datetime als
ISO).
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from heizung.models.business_audit import BusinessAudit

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | time | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_to_jsonable(v) for v in value]
    return value


async def record_business_action(
    session: AsyncSession,
    *,
    user_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None,
    old_value: Any,
    new_value: Any,
    request_ip: str | None = None,
) -> None:
    """Persistiert eine operative Aktion in business_audit.

    Aufruf MUSS innerhalb derselben ``session``-Transaktion erfolgen,
    in der auch das eigentliche UPDATE passiert. ``session.add()``
    allein committed nicht — der aufrufende Endpoint ist fuer Commit
    zustaendig.
    """
    entry = BusinessAudit(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        old_value=_to_jsonable(old_value),
        new_value=_to_jsonable(new_value),
        request_ip=request_ip,
    )
    session.add(entry)
