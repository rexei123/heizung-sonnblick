"""Regel-Engine: Setpoint-Berechnung pro Raum.

Sprint 9.3 (Walking Skeleton, 2026-05-03):
Layer 1 Base + Layer 5 Hard Clamp + Hysterese-Check.
Layer 0 Sommermodus, Layer 2 Temporal, Layer 3 Manual, Layer 4 Window
folgen in Sprint 9.7-9.9. Architektur ist so vorbereitet, dass Layer
einfach in der Pipeline ergaenzt werden koennen.

Designprinzip:
- Pure Functions wo moeglich (deterministisch, ohne DB-Zugriff testbar).
- DB-Lookup bewusst getrennt in ``_load_room_context``.
- ``evaluate_room`` ist die einzige API nach aussen — bekommt nur die
  Session, holt selbst alles was sie braucht.

Engine-Output (``RuleResult``) ist NUR Berechnung. Persistenz von
``event_log`` + Senden des Downlinks macht der Caller (Sprint 9.4 Trigger
plus Sprint 9.5 Audit-Persistenz).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, EventLogLayer, RoomStatus, RuleConfigScope
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.rule_config import RuleConfig
from heizung.rules.constants import FROST_PROTECTION_C

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.models.room_type import RoomType

# --- Sprint 9 Konstanten (AE-32: 1.0 °C statt 0.5 °C nach Vicki-Spike) ---
HYSTERESIS_C: int = 1
HEARTBEAT_INTERVAL: timedelta = timedelta(hours=6)
MAX_SETPOINT_C: int = 30
MIN_SETPOINT_C: int = int(FROST_PROTECTION_C)


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LayerStep:
    """Ein Pipeline-Schritt mit seinem Output. Wird in event_log persistiert
    und im Frontend Engine-Decision-Panel angezeigt."""

    layer: EventLogLayer
    setpoint_c: int
    reason: CommandReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Ergebnis einer Engine-Eval. Wird vom Celery-Task konsumiert."""

    room_id: int
    setpoint_c: int
    layers: tuple[LayerStep, ...]
    base_reason: CommandReason


@dataclass(frozen=True, slots=True)
class HysteresisDecision:
    """Trennt Berechnung (Engine) von Aktion (Trigger)."""

    should_send: bool
    reason: str


@dataclass(slots=True)
class _RoomContext:
    """Was die Engine pro Raum braucht. Aus DB geladen, dann pure-functional."""

    room: Room
    room_type: RoomType
    rule_configs: list[RuleConfig] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pure Layer-Funktionen
# ---------------------------------------------------------------------------


def _resolve_t(field_name: str, ctx: _RoomContext) -> Decimal | None:
    """RuleConfig-Hierarchie: ROOM > ROOM_TYPE > GLOBAL.

    NULL-Spalten = vererbt; durchlaufen die Hierarchie weiter.
    Saisonale Eintraege (`season_id IS NOT NULL`) werden in Sprint 10
    nach Saison-Aktivitaet gefiltert. Sprint 9.3 ignoriert Saison
    bewusst und nimmt alle ein.
    """
    by_scope = {
        RuleConfigScope.ROOM: [],
        RuleConfigScope.ROOM_TYPE: [],
        RuleConfigScope.GLOBAL: [],
    }
    for rc in ctx.rule_configs:
        by_scope[rc.scope].append(rc)

    for scope in (RuleConfigScope.ROOM, RuleConfigScope.ROOM_TYPE, RuleConfigScope.GLOBAL):
        for rc in by_scope[scope]:
            value: Decimal | None = getattr(rc, field_name, None)
            if value is not None:
                return value
    return None


def layer_base_target(ctx: _RoomContext) -> LayerStep:
    """Layer 1: Setpoint aus Status + RuleConfig-Hierarchie.

    Status -> Sollwert-Mapping:
      OCCUPIED       -> t_occupied (default room_type.default_t_occupied)
      RESERVED       -> t_vacant   (Vorheizen kommt in Layer 2 separat)
      VACANT         -> t_vacant
      CLEANING       -> t_vacant
      BLOCKED        -> Frostschutz (Engine signalisiert: Raum offline)
    """
    status = ctx.room.status
    if status == RoomStatus.BLOCKED:
        return LayerStep(
            layer=EventLogLayer.BASE_TARGET,
            setpoint_c=int(FROST_PROTECTION_C),
            reason=CommandReason.FROST_PROTECTION,
            detail="status=blocked",
        )

    if status == RoomStatus.OCCUPIED:
        t = _resolve_t("t_occupied", ctx) or ctx.room_type.default_t_occupied
        reason = CommandReason.OCCUPIED_SETPOINT
    else:  # vacant, reserved, cleaning
        t = _resolve_t("t_vacant", ctx) or ctx.room_type.default_t_vacant
        reason = CommandReason.VACANT_SETPOINT

    return LayerStep(
        layer=EventLogLayer.BASE_TARGET,
        setpoint_c=_quantize(t),
        reason=reason,
        detail=f"status={status.value}",
    )


def layer_clamp(
    prev_setpoint_c: int,
    ctx: _RoomContext,
    *,
    prev_reason: CommandReason,
) -> LayerStep:
    """Layer 5: Final Hard-Clamp. Garantiert Frostschutz, schuetzt vor
    Engine-Bugs. Beruecksichtigt room_type.min_temp_celsius / max_temp_celsius
    falls gesetzt — sonst System-Defaults.

    Sprint 9.6b Fix: ``prev_reason`` (aus base_target/temporal/window) wird
    durchgereicht, wenn der Clamp den Wert nicht aenderte. Vorher hardcoded
    ``OCCUPIED_SETPOINT`` -> falsches UI-Label fuer alle nicht-Occupied-Status.
    """
    rt_min = _safe_int(ctx.room_type.min_temp_celsius, default=MIN_SETPOINT_C)
    rt_max = _safe_int(ctx.room_type.max_temp_celsius, default=MAX_SETPOINT_C)

    # System-Frostschutz hat IMMER Vorrang vor room_type-Override.
    floor = max(rt_min, MIN_SETPOINT_C)
    ceiling = min(rt_max, MAX_SETPOINT_C)

    clamped = max(floor, min(ceiling, prev_setpoint_c))
    if clamped == prev_setpoint_c:
        detail = f"within [{floor},{ceiling}]"
    else:
        detail = f"clamped from {prev_setpoint_c} to {clamped} (range [{floor},{ceiling}])"

    # Reason: wenn Clamping nach unten auf MIN_SETPOINT_C zieht -> FROST_PROTECTION.
    # Sonst die Reason vom Layer davor weiterreichen (vacant_setpoint bleibt
    # vacant_setpoint, occupied_setpoint bleibt occupied_setpoint, etc.).
    if clamped == MIN_SETPOINT_C and prev_setpoint_c < MIN_SETPOINT_C:
        reason = CommandReason.FROST_PROTECTION
    else:
        reason = prev_reason

    return LayerStep(
        layer=EventLogLayer.HARD_CLAMP,
        setpoint_c=clamped,
        reason=reason,
        detail=detail,
    )


def hysteresis_decision(
    prev_setpoint_c: int | None,
    prev_issued_at: datetime | None,
    new_setpoint_c: int,
    *,
    now: datetime | None = None,
) -> HysteresisDecision:
    """Entscheidet, ob ein Downlink gesendet wird.

    AE-32 (Sprint 9 Brief §3): |neu - alt| < HYSTERESIS_C UND letzter
    Befehl < 6 h zurueck -> KEIN Downlink (Battery sparen).

    - Kein vorheriger Befehl -> immer senden (Initial-Sync).
    - Aenderung >= HYSTERESIS_C -> immer senden.
    - Aenderung < HYSTERESIS_C aber Heartbeat ueberschritten -> senden
      (damit Vicki sich nach Reboot oder Drehring-Override re-syncht).
    """
    if prev_setpoint_c is None or prev_issued_at is None:
        return HysteresisDecision(should_send=True, reason="no_previous_command")

    delta = abs(new_setpoint_c - prev_setpoint_c)
    if delta >= HYSTERESIS_C:
        return HysteresisDecision(should_send=True, reason=f"delta={delta}")

    now = now or datetime.now(tz=UTC)
    age = now - prev_issued_at
    if age >= HEARTBEAT_INTERVAL:
        return HysteresisDecision(should_send=True, reason=f"heartbeat age={age}")

    return HysteresisDecision(
        should_send=False,
        reason=f"hysteresis: delta={delta} < {HYSTERESIS_C} und age={age} < {HEARTBEAT_INTERVAL}",
    )


# ---------------------------------------------------------------------------
# DB-Wrapper
# ---------------------------------------------------------------------------


async def _load_room_context(session: AsyncSession, room_id: int) -> _RoomContext | None:
    """Eager-Load Room + RoomType + alle relevanten RuleConfigs."""
    stmt = (
        select(Room)
        .where(Room.id == room_id)
        .options(joinedload(Room.room_type), joinedload(Room.rule_configs))
    )
    result = await session.execute(stmt)
    room: Room | None = result.unique().scalar_one_or_none()
    if room is None:
        return None
    return _RoomContext(room=room, room_type=room.room_type, rule_configs=list(room.rule_configs))


async def _last_command_for_room(
    session: AsyncSession, room_id: int
) -> tuple[int, datetime] | None:
    """Letzter erfolgreich gesendeter ControlCommand fuer ein Device des Raums.

    Hysterese arbeitet auf der Pro-Raum-Ebene (Engine-Output ist 1 Setpoint
    pro Raum). Wenn ein Raum mehrere Devices hat, ist der juengste Command
    eines beliebigen Device der Vergleichswert — bei Multi-Device-Raeumen
    bleibt das in Sprint 9 ein bekannter Approximationsfehler (Backlog).
    """
    stmt = (
        select(ControlCommand.target_setpoint, ControlCommand.issued_at)
        .join(Device, Device.id == ControlCommand.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .where(ControlCommand.sent_to_gateway_at.is_not(None))
        .order_by(ControlCommand.issued_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    setpoint, issued_at = row
    return _quantize(setpoint), issued_at


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def evaluate_room(session: AsyncSession, room_id: int) -> RuleResult | None:
    """Engine-Eval fuer einen Raum.

    :param session: aktive AsyncSession (vom Caller getragen).
    :param room_id: Raum-ID.
    :return: ``RuleResult`` oder ``None`` wenn Raum nicht existiert.
    """
    ctx = await _load_room_context(session, room_id)
    if ctx is None:
        return None

    base = layer_base_target(ctx)
    clamp = layer_clamp(base.setpoint_c, ctx, prev_reason=base.reason)

    return RuleResult(
        room_id=room_id,
        setpoint_c=clamp.setpoint_c,
        layers=(base, clamp),
        base_reason=base.reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quantize(value: Decimal | float | int) -> int:
    """Vicki-Hardware: nur ganze Grad. Standard Round-Half-Up reicht."""
    return int(round(float(value)))


def _safe_int(value: Decimal | None, *, default: int) -> int:
    if value is None:
        return default
    return _quantize(value)
