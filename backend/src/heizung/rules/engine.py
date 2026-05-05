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
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.enums import CommandReason, EventLogLayer, RoomStatus, RuleConfigScope
from heizung.models.global_config import GlobalConfig
from heizung.models.heating_zone import HeatingZone
from heizung.models.occupancy import Occupancy
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
    summer_mode_active: bool = False
    # Sprint 9.8: naechste aktive Belegung (fuer Vorheizen-Logik). NULL wenn
    # keine zukuenftige oder laufende Belegung existiert.
    next_occupancy: Occupancy | None = None


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
    by_scope: dict[RuleConfigScope, list[RuleConfig]] = {
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


def layer_summer_mode(ctx: _RoomContext) -> LayerStep | None:
    """Layer 0: Sommermodus-Fast-Path (AE-31, AE-34).

    Wenn ``global_config.summer_mode_active`` true ist, ueberspringt die
    Engine ALLE anderen Layer (1-4) und setzt direkt Frostschutz. Layer 5
    (Hard Clamp) laeuft trotzdem als Sicherheits-Check.

    Returns ``None`` wenn Sommermodus inaktiv — Caller faehrt mit
    Layer 1 weiter.
    """
    if not ctx.summer_mode_active:
        return None
    return LayerStep(
        layer=EventLogLayer.SUMMER_MODE_FAST_PATH,
        setpoint_c=int(FROST_PROTECTION_C),
        reason=CommandReason.SUMMER_MODE,
        detail="summer_mode_active=true",
    )


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


def _resolve_field(field_name: str, ctx: _RoomContext) -> Any:
    """Generische RuleConfig-Hierarchie ROOM > ROOM_TYPE > GLOBAL fuer ein
    beliebiges Feld (Decimal, time, int)."""
    by_scope: dict[RuleConfigScope, list[RuleConfig]] = {
        RuleConfigScope.ROOM: [],
        RuleConfigScope.ROOM_TYPE: [],
        RuleConfigScope.GLOBAL: [],
    }
    for rc in ctx.rule_configs:
        by_scope[rc.scope].append(rc)
    for scope in (RuleConfigScope.ROOM, RuleConfigScope.ROOM_TYPE, RuleConfigScope.GLOBAL):
        for rc in by_scope[scope]:
            value = getattr(rc, field_name, None)
            if value is not None:
                return value
    return None


def _is_in_night_window(now_local_time: time, night_start: time, night_end: time) -> bool:
    """Liegt die Uhrzeit im Nacht-Fenster? Faehrt korrekt ueber Mitternacht.

    Beispiel: night_start=22:00, night_end=06:00 -> "Nacht" wenn t>=22:00 ODER t<06:00.
    Beispiel: night_start=01:00, night_end=05:00 -> "Nacht" wenn 01:00<=t<05:00.
    """
    if night_start <= night_end:
        # Kein Wrap: gleiches Datum
        return night_start <= now_local_time < night_end
    # Wrap ueber Mitternacht
    return now_local_time >= night_start or now_local_time < night_end


def layer_temporal(
    base_step: LayerStep,
    ctx: _RoomContext,
    *,
    now: datetime,
) -> LayerStep | None:
    """Layer 2: Zeitsteuerung — Vorheizen + Nachtabsenkung.

    **Vorheizen (gewinnt bei Konflikt):**
    Wenn Status=RESERVED und naechste Belegung beginnt in [now, now+preheat_min]
    -> Setpoint wie OCCUPIED (Gast soll in einen warmen Raum kommen).

    **Nachtabsenkung:**
    Wenn Status=OCCUPIED und Uhrzeit in [night_start, night_end]
    -> Setpoint = ``t_night``.

    Returns ``None`` wenn weder Vorheizen noch Nacht aktiv — Caller behaelt
    Layer-1-Output.

    Time-Berechnung in lokaler Hotel-Zeitzone (default Europe/Vienna in
    global_config). Sprint 9.8 vereinfacht: nutzt now (UTC) direkt — Hotelier
    kann Sprint 13+ via global_config.timezone konfigurieren.
    """
    # --- VORHEIZEN ---
    occ = ctx.next_occupancy
    if occ is not None and ctx.room.status == RoomStatus.RESERVED:
        preheat_min = _resolve_field("preheat_minutes_before_checkin", ctx)
        if preheat_min is not None and preheat_min > 0:
            preheat_window_start = occ.check_in - timedelta(minutes=int(preheat_min))
            if preheat_window_start <= now < occ.check_in:
                t_occupied = _resolve_field("t_occupied", ctx) or ctx.room_type.default_t_occupied
                return LayerStep(
                    layer=EventLogLayer.TEMPORAL_OVERRIDE,
                    setpoint_c=_quantize(t_occupied),
                    reason=CommandReason.PREHEAT_CHECKIN,
                    detail=(
                        f"preheat: check_in={occ.check_in.isoformat()} "
                        f"window_start={preheat_window_start.isoformat()}"
                    ),
                )

    # --- NACHTABSENKUNG ---
    if ctx.room.status == RoomStatus.OCCUPIED:
        night_start = _resolve_field("night_start", ctx)
        night_end = _resolve_field("night_end", ctx)
        if night_start is not None and night_end is not None:
            now_t = now.time()
            if _is_in_night_window(now_t, night_start, night_end):
                t_night = _resolve_field("t_night", ctx) or ctx.room_type.default_t_night
                return LayerStep(
                    layer=EventLogLayer.TEMPORAL_OVERRIDE,
                    setpoint_c=_quantize(t_night),
                    reason=CommandReason.NIGHT_SETBACK,
                    detail=(
                        f"night_setback: now={now_t.isoformat()} "
                        f"window=[{night_start.isoformat()},{night_end.isoformat()}]"
                    ),
                )

    return None


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
    """Eager-Load Room + RoomType + ALLE Hierarchie-RuleConfigs + GlobalConfig.

    Sprint 9.8a Bugfix: ``room.rule_configs`` (Relationship) liefert NUR
    ROOM-Scope-Eintraege (FK ``rule_config.room_id = room.id``). ROOM_TYPE-
    und GLOBAL-Scope-Configs wurden vorher NIE geladen — ``_resolve_field``
    fiel immer auf den Hardcoded-Default. Bug fiel nicht auf, weil Layer 1
    immer ``room_type.default_t_occupied`` als Fallback hatte; Layer 2 (9.8)
    braucht Hierarchie-Felder OHNE Default (preheat, night_*) und triggerte
    deshalb nie.
    """
    stmt = select(Room).where(Room.id == room_id).options(joinedload(Room.room_type))
    result = await session.execute(stmt)
    room: Room | None = result.unique().scalar_one_or_none()
    if room is None:
        return None

    # Alle relevanten RuleConfigs ueber alle drei Scopes:
    # GLOBAL immer, ROOM_TYPE wenn matching, ROOM nur fuer dieses Zimmer.
    rc_stmt = select(RuleConfig).where(
        (RuleConfig.scope == RuleConfigScope.GLOBAL)
        | (
            (RuleConfig.scope == RuleConfigScope.ROOM_TYPE)
            & (RuleConfig.room_type_id == room.room_type_id)
        )
        | ((RuleConfig.scope == RuleConfigScope.ROOM) & (RuleConfig.room_id == room_id))
    )
    rule_configs = list((await session.execute(rc_stmt)).scalars().all())

    # Sprint 9.7: Sommermodus-Flag aus Singleton-global_config.
    cfg = await session.get(GlobalConfig, 1)
    summer_active = bool(cfg.summer_mode_active) if cfg else False

    # Sprint 9.8: naechste aktive Belegung fuer Vorheizen-Logik.
    now = datetime.now(tz=UTC)
    next_occ_stmt = (
        select(Occupancy)
        .where(Occupancy.room_id == room_id)
        .where(Occupancy.is_active.is_(True))
        .where(Occupancy.check_out > now)
        .order_by(Occupancy.check_in)
        .limit(1)
    )
    next_occ = (await session.execute(next_occ_stmt)).scalar_one_or_none()

    return _RoomContext(
        room=room,
        room_type=room.room_type,
        rule_configs=rule_configs,
        summer_mode_active=summer_active,
        next_occupancy=next_occ,
    )


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

    # Sprint 9.7: Layer 0 Sommermodus-Fast-Path. Skip Layers 1-4 wenn aktiv.
    summer = layer_summer_mode(ctx)
    if summer is not None:
        clamp = layer_clamp(summer.setpoint_c, ctx, prev_reason=summer.reason)
        return RuleResult(
            room_id=room_id,
            setpoint_c=clamp.setpoint_c,
            layers=(summer, clamp),
            base_reason=summer.reason,
        )

    base = layer_base_target(ctx)

    # Sprint 9.8: Layer 2 Temporal (Vorheizen + Nachtabsenkung).
    now = datetime.now(tz=UTC)
    temporal = layer_temporal(base, ctx, now=now)
    if temporal is not None:
        clamp = layer_clamp(temporal.setpoint_c, ctx, prev_reason=temporal.reason)
        return RuleResult(
            room_id=room_id,
            setpoint_c=clamp.setpoint_c,
            layers=(base, temporal, clamp),
            base_reason=temporal.reason,
        )

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
