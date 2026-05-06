"""Manual-Override-Domain-Logik (Sprint 9.9, Engine Layer 3).

Reine Domain-Schicht: kennt KEIN Casablanca, KEIN Vicki, KEIN HTTP. Nimmt
``AsyncSession`` + Werte, gibt Modelle zurueck. Konsumenten:

- ``api/v1/overrides``                 -> create / get_active / get_history / revoke (T4)
- ``services/device_adapter``          -> create(source=DEVICE) (T5)
- Casablanca-Sync-Job                  -> revoke_device_overrides (T6)
- ``tasks/cleanup_overrides``          -> cleanup_expired (T7)
- Engine Layer 3                       -> get_active (T3)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import OverrideSource
from heizung.models.global_config import GlobalConfig
from heizung.models.manual_override import ManualOverride

logger = logging.getLogger(__name__)

MIN_SETPOINT = Decimal("5.0")
MAX_SETPOINT = Decimal("30.0")
HARD_MAX_DURATION_DAYS = 7
HISTORY_LIMIT_CAP = 200
DEFAULT_TIMEZONE = "Europe/Vienna"


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _quantize(setpoint: Decimal) -> Decimal:
    return setpoint.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)


def _hard_cap(expires_at: datetime, now: datetime) -> tuple[datetime, bool]:
    """Cappt ``expires_at`` auf ``now + HARD_MAX_DURATION_DAYS``.

    Returns ``(capped_value, was_capped)``.
    """
    hard_max = now + timedelta(days=HARD_MAX_DURATION_DAYS)
    if expires_at > hard_max:
        return hard_max, True
    return expires_at, False


def compute_expires_at(
    source: OverrideSource,
    now: datetime,
    *,
    next_checkout_at: datetime | None = None,
    hotel_config: GlobalConfig | None = None,
) -> datetime:
    """Default-Ablauf je Quelle, anschliessend 7-Tage-Hard-Cap.

    - ``frontend_4h``        -> ``now + 4 h``
    - ``frontend_midnight``  -> ``heute 23:59`` Hotel-Timezone (aus
      ``hotel_config.timezone``, sonst Europe/Vienna).
    - ``frontend_checkout``  -> ``next_checkout_at`` falls gesetzt,
      sonst ``now + 7 Tage``.
    - ``device``             -> identisch zu ``frontend_checkout``.

    ``hotel_config`` ist eine ``GlobalConfig``-Singleton-Instanz; der
    Parameter heisst ``hotel_config`` (Plan-Wording), Typ ist projekt-
    seitig ``GlobalConfig``. Multi-Hotel kommt erst Sprint 11+.
    """
    if source == OverrideSource.FRONTEND_4H:
        raw = now + timedelta(hours=4)
    elif source == OverrideSource.FRONTEND_MIDNIGHT:
        tz_name = hotel_config.timezone if hotel_config is not None else DEFAULT_TIMEZONE
        tz = ZoneInfo(tz_name)
        local_now = now.astimezone(tz)
        local_midnight = local_now.replace(hour=23, minute=59, second=0, microsecond=0)
        raw = local_midnight.astimezone(UTC)
    elif source in (OverrideSource.FRONTEND_CHECKOUT, OverrideSource.DEVICE):
        if next_checkout_at is not None:
            raw = next_checkout_at
        else:
            raw = now + timedelta(days=HARD_MAX_DURATION_DAYS)
    else:
        raise ValueError(f"Unbekannte OverrideSource: {source}")

    capped, _ = _hard_cap(raw, now)
    return capped


async def create(
    session: AsyncSession,
    *,
    room_id: int,
    setpoint: Decimal,
    source: OverrideSource,
    expires_at: datetime,
    reason: str | None = None,
    created_by: str | None = None,
) -> ManualOverride:
    """Legt einen neuen Override an. ``ValueError`` bei out-of-range Setpoint."""
    quantized = _quantize(setpoint)
    if quantized < MIN_SETPOINT or quantized > MAX_SETPOINT:
        raise ValueError(
            f"Setpoint {quantized} liegt ausserhalb [{MIN_SETPOINT}, {MAX_SETPOINT}] degC"
        )

    now = _now()
    capped_expires_at, was_capped = _hard_cap(expires_at, now)
    if was_capped:
        # TODO Sprint 9.9 Backlog: dedizierter event_log-Eintrag fuer Cap-Events.
        # Bestehender ``services.event_log``-Wrapper existiert nicht; ein
        # direkter ``EventLog(...)``-Insert ausserhalb der Engine-Pipeline
        # erfordert kuenstliche evaluation_id/layer-Werte. Vorerst nur Log.
        logger.warning(
            "manual_override hard-capped: room_id=%s source=%s requested=%s capped=%s",
            room_id,
            source.value,
            expires_at.isoformat(),
            capped_expires_at.isoformat(),
        )

    override = ManualOverride(
        room_id=room_id,
        setpoint=quantized,
        source=source,
        expires_at=capped_expires_at,
        reason=reason,
        created_by=created_by,
    )
    session.add(override)
    await session.flush()
    return override


async def get_active(session: AsyncSession, room_id: int) -> ManualOverride | None:
    """Juengster nicht-revokierter, nicht-expired Override fuer den Raum."""
    now = _now()
    stmt = (
        select(ManualOverride)
        .where(ManualOverride.room_id == room_id)
        .where(ManualOverride.revoked_at.is_(None))
        .where(ManualOverride.expires_at > now)
        .order_by(ManualOverride.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_history(
    session: AsyncSession,
    room_id: int,
    *,
    limit: int = 50,
    include_expired: bool = True,
) -> list[ManualOverride]:
    """Override-Historie fuer den Raum, ``created_at DESC``.

    ``limit`` wird auf ``HISTORY_LIMIT_CAP`` (= 200) gekappt.
    """
    effective_limit = min(limit, HISTORY_LIMIT_CAP)
    stmt = (
        select(ManualOverride)
        .where(ManualOverride.room_id == room_id)
        .order_by(ManualOverride.created_at.desc())
        .limit(effective_limit)
    )
    if not include_expired:
        now = _now()
        stmt = stmt.where(ManualOverride.expires_at > now)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def revoke(
    session: AsyncSession,
    override_id: int,
    *,
    reason: str | None = None,
) -> ManualOverride:
    """Setzt ``revoked_at = now()``. ``ValueError`` bei doppeltem Revoke."""
    override = await session.get(ManualOverride, override_id)
    if override is None:
        raise ValueError(f"ManualOverride id={override_id} existiert nicht")
    if override.revoked_at is not None:
        raise ValueError(f"ManualOverride id={override_id} ist bereits revoked")
    override.revoked_at = _now()
    override.revoked_reason = reason
    await session.flush()
    return override


async def revoke_device_overrides(
    session: AsyncSession,
    room_id: int,
    *,
    reason: str = "auto: guest checked out",
) -> int:
    """Revoked alle aktiven device-Overrides fuer den Raum. Returns count."""
    now = _now()
    stmt = (
        select(ManualOverride)
        .where(ManualOverride.room_id == room_id)
        .where(ManualOverride.source == OverrideSource.DEVICE)
        .where(ManualOverride.revoked_at.is_(None))
        .where(ManualOverride.expires_at > now)
    )
    result = await session.execute(stmt)
    overrides = list(result.scalars().all())
    for override in overrides:
        override.revoked_at = now
        override.revoked_reason = reason
    if overrides:
        await session.flush()
    return len(overrides)


async def cleanup_expired(session: AsyncSession) -> int:
    """Markiert alle nicht-revokierten, abgelaufenen Overrides als revoked.

    Wird vom celery_beat-Task in T7 taeglich aufgerufen. Returns count.
    """
    now = _now()
    stmt = (
        select(ManualOverride)
        .where(ManualOverride.revoked_at.is_(None))
        .where(ManualOverride.expires_at < now)
    )
    result = await session.execute(stmt)
    overrides = list(result.scalars().all())
    for override in overrides:
        override.revoked_at = override.expires_at
        override.revoked_reason = "auto: expired"
    if overrides:
        await session.flush()
    return len(overrides)
