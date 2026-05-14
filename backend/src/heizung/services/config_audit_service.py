"""Service fuer config_audit (Sprint 9.14, AE-46).

Schreibt einen Audit-Eintrag pro geaendertem Feld einer Settings-
Aenderung. Aufrufer ist verantwortlich, die Aufrufe innerhalb der
SELBEN Transaktion wie das eigentliche UPDATE zu kapseln — damit
Audit + Daten atomar sind.

JSONB-Serialisierung: ``Decimal`` als String (volle Praezision),
``time``/``date``/``datetime`` als ISO-String. Primitives (int, str,
bool, None, dict, list) passieren unveraendert durch.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from heizung.models.config_audit import ConfigAudit

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_jsonable(value: Any) -> Any:
    """JSONB-vertraegliche Repraesentation."""
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


async def record_config_change(
    session: AsyncSession,
    *,
    source: str,
    table_name: str,
    column_name: str,
    old_value: Any,
    new_value: Any,
    scope_qualifier: str | None = None,
    user_id: int | None = None,
    request_ip: str | None = None,
) -> None:
    """Persistiert eine Settings-Aenderung im config_audit.

    Aufruf MUSS innerhalb derselben ``session``-Transaktion erfolgen,
    in der auch das eigentliche UPDATE auf ``table_name`` passiert. Der
    Service ``session.add()`` allein committed nicht — der aufrufende
    Endpoint ist fuer den Commit zustaendig.
    """
    entry = ConfigAudit(
        source=source,
        table_name=table_name,
        scope_qualifier=scope_qualifier,
        column_name=column_name,
        old_value=_to_jsonable(old_value),
        new_value=_to_jsonable(new_value),
        user_id=user_id,
        request_ip=request_ip,
    )
    session.add(entry)
