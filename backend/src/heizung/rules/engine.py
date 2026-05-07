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
from decimal import ROUND_HALF_UP, Decimal
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
from heizung.models.sensor_reading import SensorReading
from heizung.rules.constants import FROST_PROTECTION_C
from heizung.services import override_service

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from heizung.models.room_type import RoomType

# --- Sprint 9 Konstanten (AE-32: 1.0 °C statt 0.5 °C nach Vicki-Spike) ---
HYSTERESIS_C: int = 1
HEARTBEAT_INTERVAL: timedelta = timedelta(hours=6)
MAX_SETPOINT_C: int = 30
MIN_SETPOINT_C: int = int(FROST_PROTECTION_C)

# Sprint 9.10: Reading-Alter, ab dem ein open_window-Flag als veraltet gilt
# und Layer 4 nicht mehr aktiviert. 30 Min entspricht zwei verpassten
# Vicki-Periodic-Reports (Default 15 Min) — robust gegen Einzel-Ausfall,
# eng genug, dass nach Funkloch nicht stundenlang fehlhaltend.
WINDOW_STALE_THRESHOLD_MIN: int = 30


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LayerStep:
    """Ein Pipeline-Schritt mit seinem Output. Wird in event_log persistiert
    und im Frontend Engine-Decision-Panel angezeigt.

    ``extras`` (Sprint 9.9 T3): layer-spezifische strukturierte Felder,
    die zusaetzlich zum string ``detail`` ins ``event_log.details``-JSONB
    gemerged werden (siehe ``tasks.engine_tasks``). Layer 3 nutzt das fuer
    ``source``/``expires_at``/``override_id`` — andere Layer setzen es
    aktuell nicht.

    ``setpoint_c`` (Sprint 9.10d): ``None`` bedeutet "Layer hat keinen
    eigenen Setpoint-Beitrag". Aktuell ausschliesslich Layer 0 im Inactive-
    Pfad — alle anderen Layer (Base, Temporal, Manual, Window, Clamp)
    garantieren weiterhin einen Integer-Wert, auch im Pass-Through-Fall.
    """

    layer: EventLogLayer
    setpoint_c: int | None
    reason: CommandReason
    detail: str | None = None
    extras: dict[str, Any] | None = None


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


def layer_summer_mode(ctx: _RoomContext) -> LayerStep:
    """Layer 0: Sommermodus-Fast-Path (AE-31, AE-34).

    Sprint 9.10d: Layer ist always-on, liefert IMMER einen LayerStep — auch
    im inaktiven Fall —, damit das Engine-Decision-Panel pro Eval einen
    Trace-Eintrag fuer Layer 0 zeigt. Der Fast-Path-Skip (Layer 1-4
    ueberspringen) wird vom Caller via ``ctx.summer_mode_active`` gesteuert,
    NICHT mehr ueber ``is None``.

    Aktiv (``summer_mode_active=True``): Setpoint ``FROST_PROTECTION_C``,
    Reason ``SUMMER_MODE``, ``detail="summer_mode_active=true"``.

    Inaktiv: Passthrough-Marker mit ``setpoint_c=None`` (Layer 0 hat keinen
    eigenen Setpoint-Beitrag — der finale Wert kommt aus Layer 1+), Reason
    ``SUMMER_MODE``, ``detail="summer_mode_inactive"``. T2.5 (Sprint 9.10d):
    None statt MIN_SETPOINT_C-Platzhalter, weil Layer 0 als erste Schicht
    kein "in" hat und die Pass-Through-Konvention setpoint_in==setpoint_out
    hier nicht greift.
    """
    if ctx.summer_mode_active:
        return LayerStep(
            layer=EventLogLayer.SUMMER_MODE_FAST_PATH,
            setpoint_c=int(FROST_PROTECTION_C),
            reason=CommandReason.SUMMER_MODE,
            detail="summer_mode_active=true",
        )
    return LayerStep(
        layer=EventLogLayer.SUMMER_MODE_FAST_PATH,
        setpoint_c=None,
        reason=CommandReason.SUMMER_MODE,
        detail="summer_mode_inactive",
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
) -> LayerStep:
    """Layer 2: Zeitsteuerung — Vorheizen + Nachtabsenkung.

    **Vorheizen (gewinnt bei Konflikt):**
    Wenn Status=RESERVED und naechste Belegung beginnt in [now, now+preheat_min]
    -> Setpoint wie OCCUPIED (Gast soll in einen warmen Raum kommen).

    **Nachtabsenkung:**
    Wenn Status=OCCUPIED und Uhrzeit in [night_start, night_end]
    -> Setpoint = ``t_night``.

    Sprint 9.10d: Layer ist always-on, liefert IMMER einen LayerStep — auch
    im no-effect-Fall. Im Passthrough-Pfad bleiben ``setpoint_c`` und
    ``reason`` aus ``base_step`` unveraendert; ``detail`` haelt einen
    snake_case-Token fest WARUM kein Eingriff erfolgte:
        - ``no_upcoming_arrival``    keine Belegung mit anstehender Anreise
        - ``outside_preheat_window`` Belegung existiert, aber check_in zu
                                     weit weg oder schon vorbei
        - ``outside_night_setback``  OCCUPIED, Nachtfenster konfiguriert,
                                     aktuelle Zeit liegt ausserhalb
        - ``temporal_inactive``      Fallback (Status nicht RESERVED/OCCUPIED,
                                     oder noetige Konfiguration fehlt)

    Time-Berechnung in lokaler Hotel-Zeitzone (default Europe/Vienna in
    global_config). Sprint 9.8 vereinfacht: nutzt now (UTC) direkt — Hotelier
    kann Sprint 13+ via global_config.timezone konfigurieren.
    """
    detail_token: str | None = None

    # --- VORHEIZEN ---
    if ctx.room.status == RoomStatus.RESERVED:
        occ = ctx.next_occupancy
        if occ is None:
            detail_token = "no_upcoming_arrival"
        else:
            preheat_min = _resolve_field("preheat_minutes_before_checkin", ctx)
            if preheat_min is not None and preheat_min > 0:
                preheat_window_start = occ.check_in - timedelta(minutes=int(preheat_min))
                if preheat_window_start <= now < occ.check_in:
                    t_occupied = (
                        _resolve_field("t_occupied", ctx) or ctx.room_type.default_t_occupied
                    )
                    return LayerStep(
                        layer=EventLogLayer.TEMPORAL_OVERRIDE,
                        setpoint_c=_quantize(t_occupied),
                        reason=CommandReason.PREHEAT_CHECKIN,
                        detail=(
                            f"preheat: check_in={occ.check_in.isoformat()} "
                            f"window_start={preheat_window_start.isoformat()}"
                        ),
                    )
                detail_token = "outside_preheat_window"

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
            detail_token = "outside_night_setback"

    return LayerStep(
        layer=EventLogLayer.TEMPORAL_OVERRIDE,
        setpoint_c=base_step.setpoint_c,
        reason=base_step.reason,
        detail=detail_token or "temporal_inactive",
        extras=None,
    )


async def layer_manual_override(
    session: AsyncSession,
    room_id: int,
    *,
    prev_setpoint_c: int,
    prev_reason: CommandReason,
) -> LayerStep:
    """Layer 3: Manual Override (Sprint 9.9 T3).

    Liefert IMMER einen ``LayerStep`` (auch im no-op-Fall) fuer Trace-
    Transparenz im Engine-Decision-Panel. Wenn kein aktiver Override
    existiert, wird ``prev_setpoint_c`` und ``prev_reason`` durchgereicht
    und ``extras["source"]`` ist ``None``.

    Aktive Override -> Setpoint = override.setpoint, Reason = MANUAL,
    extras enthaelt source/expires_at/override_id fuer Frontend.
    """
    override = await override_service.get_active(session, room_id)
    if override is None:
        return LayerStep(
            layer=EventLogLayer.MANUAL_OVERRIDE,
            setpoint_c=prev_setpoint_c,
            reason=prev_reason,
            detail="no active override",
            extras={"source": None, "expires_at": None, "override_id": None},
        )
    return LayerStep(
        layer=EventLogLayer.MANUAL_OVERRIDE,
        setpoint_c=_quantize(override.setpoint),
        reason=CommandReason.MANUAL,
        detail=f"override_id={override.id} source={override.source.value}",
        extras={
            "source": override.source.value,
            "expires_at": override.expires_at.isoformat(),
            "override_id": override.id,
        },
    )


async def layer_window_open(
    session: AsyncSession,
    room_id: int,
    *,
    prev_setpoint_c: int,
    prev_reason: CommandReason,
    room_status: RoomStatus,
    now: datetime,
) -> LayerStep:
    """Layer 4: Fenster-Sicherheit (Sprint 9.10 T2).

    Liefert IMMER einen ``LayerStep`` (auch im no-op-Fall), damit das
    Engine-Decision-Panel pro Eval einen Trace-Eintrag fuer Layer 4 zeigt.

    Aktiv: mindestens ein Geraet im Raum hat ein **frisches** Reading
    (Alter <= ``WINDOW_STALE_THRESHOLD_MIN``) mit ``open_window=True``.
    Setpoint -> ``MIN_SETPOINT_C`` (= System-Frostschutz aus
    ``rules/constants.py``), Reason -> ``WINDOW_OPEN``.

    Passthrough: ``prev_setpoint_c`` / ``prev_reason`` unveraendert. ``detail``
    haelt fest WARUM kein Eingriff erfolgte (no_readings / stale_reading /
    no_open_window) — wichtig fuer Operator-Diagnose.

    ``extras`` ist immer befuellt mit ``open_zones`` (Liste mit
    ``zone_id`` + ``reading_at``) und ``occupancy_state`` (occupied/vacant
    abgeleitet aus ``room_status``). ``occupancy_state`` beeinflusst
    Layer 4 NICHT — es wird nur fuer einen spaeteren Notification-Sprint
    mitgeschrieben (Doppel-Auswertung gegen Layer 1 vermieden).

    NULL-Werte in ``open_window`` (alter Codec / Vicki ohne Sensor) gelten
    als ``False`` und aktivieren Layer 4 NICHT.

    Signatur weicht bewusst vom Layer-3-Vorbild ab: ``room_status`` und
    ``now`` werden vom Caller mitgegeben, statt erneut DB-Roundtrip oder
    ``datetime.now()`` intern. Macht Tests deterministisch und nutzt den
    bereits geladenen ``ctx.room.status``.
    """
    threshold = now - timedelta(minutes=WINDOW_STALE_THRESHOLD_MIN)
    occupancy_state = "occupied" if room_status == RoomStatus.OCCUPIED else "vacant"

    # DISTINCT ON (device_id) liefert pro Geraet das juengste Reading.
    # JOIN-Pfad SensorReading -> Device -> HeatingZone -> room_id grenzt
    # auf Devices dieses Raums ein. Devices ohne heating_zone (Provisioning)
    # fallen durch den INNER JOIN raus — das ist gewollt.
    stmt = (
        select(
            SensorReading.device_id,
            SensorReading.time,
            SensorReading.open_window,
            Device.heating_zone_id,
        )
        .join(Device, Device.id == SensorReading.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    rows = (await session.execute(stmt)).all()

    open_zones: list[dict[str, Any]] = []
    fresh_count = 0
    for _device_id, reading_time, open_window, zone_id in rows:
        if reading_time < threshold:
            continue
        fresh_count += 1
        if open_window is True:
            open_zones.append({"zone_id": zone_id, "reading_at": reading_time.isoformat()})

    if open_zones:
        return LayerStep(
            layer=EventLogLayer.WINDOW_SAFETY,
            setpoint_c=MIN_SETPOINT_C,
            reason=CommandReason.WINDOW_OPEN,
            detail=f"open_zones={[z['zone_id'] for z in open_zones]}",
            extras={"open_zones": open_zones, "occupancy_state": occupancy_state},
        )

    if not rows:
        detail = "no_readings"
    elif fresh_count == 0:
        detail = "stale_reading"
    else:
        detail = "no_open_window"

    return LayerStep(
        layer=EventLogLayer.WINDOW_SAFETY,
        setpoint_c=prev_setpoint_c,
        reason=prev_reason,
        detail=detail,
        extras={"open_zones": [], "occupancy_state": occupancy_state},
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
    # Sprint 9.10d: Layer 0 ist always-on und liefert immer einen LayerStep —
    # die Fast-Path-Entscheidung steuert ``ctx.summer_mode_active`` direkt.
    summer = layer_summer_mode(ctx)
    if ctx.summer_mode_active:
        # Aktiver Pfad garantiert setpoint_c=FROST_PROTECTION_C.
        clamp = layer_clamp(_require_setpoint(summer), ctx, prev_reason=summer.reason)
        return RuleResult(
            room_id=room_id,
            setpoint_c=_require_setpoint(clamp),
            layers=(summer, clamp),
            base_reason=summer.reason,
        )

    base = layer_base_target(ctx)

    # Sprint 9.8: Layer 2 Temporal (Vorheizen + Nachtabsenkung).
    now = datetime.now(tz=UTC)
    temporal = layer_temporal(base, ctx, now=now)

    # Sprint 9.9 T3: Layer 3 Manual-Override. Laeuft IMMER (auch no-op),
    # damit das Engine-Decision-Panel stets zeigt, ob ein Override anliegt.
    # Sprint 9.10d: temporal ist nun always-on und reicht im no-effect-Fall
    # base.setpoint/base.reason als Passthrough durch — kein None-Fallback noetig.
    manual = await layer_manual_override(
        session,
        room_id,
        prev_setpoint_c=_require_setpoint(temporal),
        prev_reason=temporal.reason,
    )

    # Sprint 9.10 T2: Layer 4 Window-Detection. Ueberschreibt JEDEN
    # vorherigen Setpoint (auch Manual-Override) auf Frostschutz, wenn ein
    # frisches Reading open_window=True meldet. Sicherheit > Komfort.
    window = await layer_window_open(
        session,
        room_id,
        prev_setpoint_c=_require_setpoint(manual),
        prev_reason=manual.reason,
        room_status=ctx.room.status,
        now=now,
    )

    clamp = layer_clamp(_require_setpoint(window), ctx, prev_reason=window.reason)

    layers_tuple: tuple[LayerStep, ...] = (summer, base, temporal, manual, window, clamp)

    return RuleResult(
        room_id=room_id,
        setpoint_c=_require_setpoint(clamp),
        layers=layers_tuple,
        base_reason=window.reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _quantize(value: Decimal | float | int) -> int:
    """Vicki-Hardware: nur ganze Grad.

    Sprint 9.8b: Pythons builtin ``round()`` macht Banker's Rounding
    (22.5 -> 22). Test ``test_global_used_when_no_room_or_room_type_override``
    erwartet aber 22.5 -> 23 (Half-Up). Decimal+ROUND_HALF_UP ist
    deterministisch und erwartungskonform.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _safe_int(value: Decimal | None, *, default: int) -> int:
    if value is None:
        return default
    return _quantize(value)


def _require_setpoint(step: LayerStep) -> int:
    """Engt den Typ ``int | None`` auf ``int`` ein.

    Sprint 9.10d T2.5: nur Layer 0 inactive darf ``setpoint_c=None`` haben.
    Layer 1+ (Base, Temporal, Manual, Window, Clamp) garantieren immer
    einen Integer-Setpoint. Helper macht diese Invariante an Call-Sites
    explizit und liefert mypy einen narrowed Typ.
    """
    if step.setpoint_c is None:
        msg = f"layer={step.layer.value} hat setpoint_c=None — invariant violation"
        raise AssertionError(msg)
    return step.setpoint_c
