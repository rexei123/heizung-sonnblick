"""Sprint 9.3 — Engine-Skeleton Pure-Function-Tests.

Layer 1 (Base) + Layer 5 (Clamp) + Hysterese. Kein DB-Zugriff,
deshalb auch keine pytest-postgresql noetig.

DB-Wrapper-Tests (``_load_room_context``, ``_last_command_for_room``,
``evaluate_room``) folgen in Sprint 9.5 zusammen mit Audit-Persistenz —
dort lohnt sich die Integration-Test-Setup-Investition.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from heizung.models.enums import CommandReason, EventLogLayer, RoomStatus, RuleConfigScope
from heizung.rules.constants import FROST_PROTECTION_C
from heizung.rules.engine import (
    HEARTBEAT_INTERVAL,
    HYSTERESIS_C,
    MAX_SETPOINT_C,
    _is_in_night_window,
    _RoomContext,
    hysteresis_decision,
    layer_base_target,
    layer_clamp,
    layer_summer_mode,
    layer_temporal,
)

# ---------------------------------------------------------------------------
# Fixtures (lightweight: SimpleNamespace statt SQLAlchemy)
# ---------------------------------------------------------------------------


def _make_room_type(
    *,
    occupied: float = 21.0,
    vacant: float = 18.0,
    night: float = 19.0,
    min_c: float | None = None,
    max_c: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        default_t_occupied=Decimal(str(occupied)),
        default_t_vacant=Decimal(str(vacant)),
        default_t_night=Decimal(str(night)),
        min_temp_celsius=Decimal(str(min_c)) if min_c is not None else None,
        max_temp_celsius=Decimal(str(max_c)) if max_c is not None else None,
    )


def _make_room(status: RoomStatus = RoomStatus.OCCUPIED) -> SimpleNamespace:
    return SimpleNamespace(id=1, status=status)


def _make_rule_config(
    scope: RuleConfigScope,
    *,
    t_occupied: float | None = None,
    t_vacant: float | None = None,
    t_night: float | None = None,
    night_start: time | None = None,
    night_end: time | None = None,
    preheat_minutes_before_checkin: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        scope=scope,
        t_occupied=Decimal(str(t_occupied)) if t_occupied is not None else None,
        t_vacant=Decimal(str(t_vacant)) if t_vacant is not None else None,
        t_night=Decimal(str(t_night)) if t_night is not None else None,
        night_start=night_start,
        night_end=night_end,
        preheat_minutes_before_checkin=preheat_minutes_before_checkin,
    )


def _make_occupancy(check_in: datetime, *, check_out: datetime | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        check_in=check_in,
        check_out=check_out or check_in + timedelta(days=1),
    )


def _ctx(
    *,
    status: RoomStatus = RoomStatus.OCCUPIED,
    room_type: SimpleNamespace | None = None,
    rule_configs: list[SimpleNamespace] | None = None,
    summer_mode_active: bool = False,
    next_occupancy: SimpleNamespace | None = None,
) -> _RoomContext:
    return _RoomContext(
        room=_make_room(status),
        room_type=room_type or _make_room_type(),
        rule_configs=rule_configs or [],
        summer_mode_active=summer_mode_active,
        next_occupancy=next_occupancy,
    )


# ---------------------------------------------------------------------------
# Layer 0 Sommermodus (Sprint 9.7)
# ---------------------------------------------------------------------------


def test_summer_mode_inactive_emits_passthrough_step() -> None:
    """Sprint 9.10d T2.5 + Sprint 9.16 (AE-49): Layer 0 ist always-on,
    im Inactive-Pfad ``setpoint_c=None`` mit ``detail="summer_mode_inactive"``.
    Reason ist seit 9.16 ``SCENARIO_SUMMER_MODE`` (vorher SUMMER_MODE)."""
    step = layer_summer_mode(_ctx(summer_mode_active=False))
    assert step is not None
    assert step.layer == EventLogLayer.SUMMER_MODE_FAST_PATH
    assert step.setpoint_c is None
    assert step.detail == "summer_mode_inactive"
    assert step.reason == CommandReason.SCENARIO_SUMMER_MODE
    assert step.extras == {
        "source": "scenario_assignment",
        "scenario_code": "summer_mode",
    }


def test_summer_mode_active_returns_frost_protection() -> None:
    """Aktiv -> alle Raeume bekommen Frostschutz, reason=scenario_summer_mode
    (Sprint 9.16, AE-48)."""
    step = layer_summer_mode(_ctx(summer_mode_active=True))
    assert step is not None
    assert step.layer == EventLogLayer.SUMMER_MODE_FAST_PATH
    assert step.setpoint_c == int(FROST_PROTECTION_C)
    assert step.reason == CommandReason.SCENARIO_SUMMER_MODE
    assert step.detail == "summer_mode_active=true"
    assert step.extras == {
        "source": "scenario_assignment",
        "scenario_code": "summer_mode",
    }


def test_summer_mode_overrides_room_status() -> None:
    """Selbst Belegt-Status fuehrt im Sommermodus zu Frostschutz."""
    step = layer_summer_mode(_ctx(status=RoomStatus.OCCUPIED, summer_mode_active=True))
    assert step is not None
    assert step.setpoint_c == int(FROST_PROTECTION_C)


# ---------------------------------------------------------------------------
# Layer 1 Base Target
# ---------------------------------------------------------------------------


def test_base_occupied_uses_room_type_default() -> None:
    step = layer_base_target(_ctx(status=RoomStatus.OCCUPIED))
    assert step.layer == EventLogLayer.BASE_TARGET
    assert step.setpoint_c == 21
    assert step.reason == CommandReason.OCCUPIED_SETPOINT


def test_base_vacant_uses_room_type_default() -> None:
    step = layer_base_target(_ctx(status=RoomStatus.VACANT))
    assert step.setpoint_c == 18
    assert step.reason == CommandReason.VACANT_SETPOINT


def test_base_reserved_uses_vacant_target() -> None:
    """Reserved == Zimmer steht bereit, aber Vorheizen kommt erst in Layer 2."""
    step = layer_base_target(_ctx(status=RoomStatus.RESERVED))
    assert step.setpoint_c == 18
    assert step.reason == CommandReason.VACANT_SETPOINT


def test_base_cleaning_uses_vacant_target() -> None:
    step = layer_base_target(_ctx(status=RoomStatus.CLEANING))
    assert step.setpoint_c == 18


def test_base_blocked_falls_to_frost_protection() -> None:
    step = layer_base_target(_ctx(status=RoomStatus.BLOCKED))
    assert step.setpoint_c == int(FROST_PROTECTION_C)
    assert step.reason == CommandReason.FROST_PROTECTION
    assert "blocked" in step.detail


def test_room_scope_overrides_room_type_default() -> None:
    """ROOM-Scope hat Vorrang vor ROOM_TYPE und vor RoomType-Default."""
    rcs = [
        _make_rule_config(RuleConfigScope.ROOM_TYPE, t_occupied=22.0),
        _make_rule_config(RuleConfigScope.ROOM, t_occupied=23.0),
        _make_rule_config(RuleConfigScope.GLOBAL, t_occupied=20.0),
    ]
    step = layer_base_target(_ctx(rule_configs=rcs))
    assert step.setpoint_c == 23  # room scope


def test_global_used_when_no_room_or_room_type_override() -> None:
    rcs = [_make_rule_config(RuleConfigScope.GLOBAL, t_occupied=22.5)]
    step = layer_base_target(_ctx(rule_configs=rcs))
    assert step.setpoint_c == 23  # 22.5 round-half-up -> 23


def test_null_in_room_falls_through_to_global() -> None:
    """Wenn ROOM-Eintrag NULL fuer dieses Feld hat, weiter zu GLOBAL."""
    rcs = [
        _make_rule_config(RuleConfigScope.ROOM, t_occupied=None),  # NULL fuer occupied
        _make_rule_config(RuleConfigScope.GLOBAL, t_occupied=22.0),
    ]
    step = layer_base_target(_ctx(rule_configs=rcs))
    assert step.setpoint_c == 22


# ---------------------------------------------------------------------------
# Layer 5 Hard Clamp
# ---------------------------------------------------------------------------


def test_clamp_within_range_passes_prev_reason() -> None:
    """Sprint 9.6b: Wenn Wert nicht clamped -> prev_reason durchreichen."""
    step = layer_clamp(21, _ctx(), prev_reason=CommandReason.OCCUPIED_SETPOINT)
    assert step.layer == EventLogLayer.HARD_CLAMP
    assert step.setpoint_c == 21
    assert step.reason == CommandReason.OCCUPIED_SETPOINT
    assert "within" in step.detail


def test_clamp_within_range_passes_vacant_reason() -> None:
    """Sprint 9.6b: vacant-Setpoint bleibt vacant, nicht hardcoded occupied."""
    step = layer_clamp(18, _ctx(), prev_reason=CommandReason.VACANT_SETPOINT)
    assert step.setpoint_c == 18
    assert step.reason == CommandReason.VACANT_SETPOINT


def test_clamp_above_max_caps() -> None:
    step = layer_clamp(35, _ctx(), prev_reason=CommandReason.OCCUPIED_SETPOINT)
    assert step.setpoint_c == MAX_SETPOINT_C
    assert "clamped" in step.detail
    # Reason vom Layer davor bleibt — nur die Zahl wurde gedeckelt
    assert step.reason == CommandReason.OCCUPIED_SETPOINT


def test_clamp_below_frost_lifts_to_frost_protection() -> None:
    """Setpoint < FROST_PROTECTION -> Reason ueberschrieben auf FROST_PROTECTION."""
    step = layer_clamp(5, _ctx(), prev_reason=CommandReason.OCCUPIED_SETPOINT)
    assert step.setpoint_c == int(FROST_PROTECTION_C)
    assert step.reason == CommandReason.FROST_PROTECTION


def test_clamp_room_type_max_respected() -> None:
    """Bad mit max_temp=25 bekommt 25, nicht MAX_SETPOINT_C=30."""
    step = layer_clamp(
        28,
        _ctx(room_type=_make_room_type(max_c=25.0)),
        prev_reason=CommandReason.OCCUPIED_SETPOINT,
    )
    assert step.setpoint_c == 25


def test_clamp_room_type_min_below_frost_is_ignored() -> None:
    """Auch wenn room_type.min_temp=8 — System-Frostschutz hat Vorrang."""
    step = layer_clamp(
        7,
        _ctx(room_type=_make_room_type(min_c=8.0)),
        prev_reason=CommandReason.VACANT_SETPOINT,
    )
    assert step.setpoint_c == int(FROST_PROTECTION_C)
    assert step.reason == CommandReason.FROST_PROTECTION


# ---------------------------------------------------------------------------
# Layer 2 Temporal — Vorheizen + Nachtabsenkung (Sprint 9.8)
# ---------------------------------------------------------------------------


def test_night_window_helper_no_wrap() -> None:
    """01:00–05:00: Nacht zwischen 01 und 05."""
    assert _is_in_night_window(time(2, 0), time(1, 0), time(5, 0)) is True
    assert _is_in_night_window(time(0, 30), time(1, 0), time(5, 0)) is False
    assert _is_in_night_window(time(5, 0), time(1, 0), time(5, 0)) is False


def test_night_window_helper_with_wrap() -> None:
    """22:00–06:00: Nacht ueber Mitternacht."""
    assert _is_in_night_window(time(23, 0), time(22, 0), time(6, 0)) is True
    assert _is_in_night_window(time(2, 0), time(22, 0), time(6, 0)) is True
    assert _is_in_night_window(time(21, 59), time(22, 0), time(6, 0)) is False
    assert _is_in_night_window(time(6, 0), time(22, 0), time(6, 0)) is False


def test_temporal_no_match_emits_temporal_inactive() -> None:
    """Sprint 9.10d: OCCUPIED ohne Nachtfenster-Config -> Passthrough mit
    detail="temporal_inactive" (keine Konfiguration -> kein spezifischerer
    Token)."""
    base = layer_base_target(_ctx(status=RoomStatus.OCCUPIED))
    now = datetime(2026, 5, 4, 14, 0, tzinfo=UTC)  # Nachmittag
    step = layer_temporal(base, _ctx(status=RoomStatus.OCCUPIED), now=now)
    assert step is not None
    assert step.layer == EventLogLayer.TEMPORAL_OVERRIDE
    assert step.setpoint_c == base.setpoint_c
    assert step.reason == base.reason
    assert step.detail == "temporal_inactive"
    assert step.extras is None


def test_temporal_preheat_active() -> None:
    """RESERVED + check_in in 30 Min + preheat=60 Min -> Vorheizen aktiv."""
    now = datetime(2026, 5, 4, 13, 30, tzinfo=UTC)
    occ = _make_occupancy(check_in=now + timedelta(minutes=30))
    rcs = [_make_rule_config(RuleConfigScope.GLOBAL, preheat_minutes_before_checkin=60)]
    ctx = _ctx(status=RoomStatus.RESERVED, rule_configs=rcs, next_occupancy=occ)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.layer == EventLogLayer.TEMPORAL_OVERRIDE
    assert step.reason == CommandReason.PREHEAT_CHECKIN
    assert step.setpoint_c == 21  # default occupied


def test_temporal_preheat_too_early_emits_outside_window() -> None:
    """Sprint 9.10d: RESERVED + check_in in 90 Min + preheat=60 Min -> NICHT
    in Window. detail="outside_preheat_window" (Config existiert, Zeit-
    fenster aber nicht erfuellt)."""
    now = datetime(2026, 5, 4, 12, 30, tzinfo=UTC)
    occ = _make_occupancy(check_in=now + timedelta(minutes=90))
    rcs = [_make_rule_config(RuleConfigScope.GLOBAL, preheat_minutes_before_checkin=60)]
    ctx = _ctx(status=RoomStatus.RESERVED, rule_configs=rcs, next_occupancy=occ)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.setpoint_c == base.setpoint_c
    assert step.reason == base.reason
    assert step.detail == "outside_preheat_window"


def test_temporal_reserved_without_occupancy_emits_no_upcoming_arrival() -> None:
    """Sprint 9.10d: RESERVED aber keine ctx.next_occupancy -> spezifisches
    detail="no_upcoming_arrival"."""
    now = datetime(2026, 5, 4, 13, 30, tzinfo=UTC)
    rcs = [_make_rule_config(RuleConfigScope.GLOBAL, preheat_minutes_before_checkin=60)]
    ctx = _ctx(status=RoomStatus.RESERVED, rule_configs=rcs, next_occupancy=None)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.setpoint_c == base.setpoint_c
    assert step.reason == base.reason
    assert step.detail == "no_upcoming_arrival"


def test_temporal_preheat_no_config_emits_temporal_inactive() -> None:
    """Sprint 9.10d: RESERVED + occ aber keine preheat-Config -> Fallback
    detail="temporal_inactive" (Config fehlt, keine spezifischere Aussage
    moeglich)."""
    now = datetime(2026, 5, 4, 13, 30, tzinfo=UTC)
    occ = _make_occupancy(check_in=now + timedelta(minutes=10))
    ctx = _ctx(status=RoomStatus.RESERVED, next_occupancy=occ)  # keine rule_configs
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.setpoint_c == base.setpoint_c
    assert step.reason == base.reason
    assert step.detail == "temporal_inactive"


def test_temporal_night_setback_active() -> None:
    """OCCUPIED in Nachtfenster -> t_night."""
    now = datetime(2026, 5, 4, 23, 30, tzinfo=UTC)
    rcs = [
        _make_rule_config(
            RuleConfigScope.GLOBAL,
            t_night=19.0,
            night_start=time(22, 0),
            night_end=time(6, 0),
        )
    ]
    ctx = _ctx(status=RoomStatus.OCCUPIED, rule_configs=rcs)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.reason == CommandReason.NIGHT_SETBACK
    assert step.setpoint_c == 19


def test_temporal_night_setback_outside_window_emits_outside_token() -> None:
    """Sprint 9.10d: OCCUPIED am Nachmittag -> kein Setback.
    detail="outside_night_setback" (Config existiert, Zeitfenster nicht)."""
    now = datetime(2026, 5, 4, 14, 0, tzinfo=UTC)
    rcs = [
        _make_rule_config(
            RuleConfigScope.GLOBAL,
            t_night=19.0,
            night_start=time(22, 0),
            night_end=time(6, 0),
        )
    ]
    ctx = _ctx(status=RoomStatus.OCCUPIED, rule_configs=rcs)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.setpoint_c == base.setpoint_c
    assert step.reason == base.reason
    assert step.detail == "outside_night_setback"


def test_temporal_night_setback_only_when_occupied_emits_temporal_inactive() -> None:
    """Sprint 9.10d: VACANT in Nachtfenster -> Layer 2 ohne aktiven Pfad.
    Status weder RESERVED noch OCCUPIED -> Fallback "temporal_inactive"."""
    now = datetime(2026, 5, 4, 23, 30, tzinfo=UTC)
    rcs = [
        _make_rule_config(
            RuleConfigScope.GLOBAL,
            t_night=19.0,
            night_start=time(22, 0),
            night_end=time(6, 0),
        )
    ]
    ctx = _ctx(status=RoomStatus.VACANT, rule_configs=rcs)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.setpoint_c == base.setpoint_c
    assert step.reason == base.reason
    assert step.detail == "temporal_inactive"


def test_temporal_preheat_wins_over_night() -> None:
    """RESERVED + check_in 30 Min + preheat 60 + Nachtzeit -> Vorheizen
    gewinnt (Konflikt-Resolution)."""
    now = datetime(2026, 5, 4, 23, 30, tzinfo=UTC)  # Nachtzeit
    occ = _make_occupancy(check_in=now + timedelta(minutes=30))
    rcs = [
        _make_rule_config(
            RuleConfigScope.GLOBAL,
            preheat_minutes_before_checkin=60,
            t_night=19.0,
            night_start=time(22, 0),
            night_end=time(6, 0),
        )
    ]
    ctx = _ctx(status=RoomStatus.RESERVED, rule_configs=rcs, next_occupancy=occ)
    base = layer_base_target(ctx)
    step = layer_temporal(base, ctx, now=now)
    assert step is not None
    assert step.reason == CommandReason.PREHEAT_CHECKIN
    assert step.setpoint_c == 21


# ---------------------------------------------------------------------------
# Hysterese
# ---------------------------------------------------------------------------


def test_hysteresis_no_previous_command_sends() -> None:
    d = hysteresis_decision(prev_setpoint_c=None, prev_issued_at=None, new_setpoint_c=21)
    assert d.should_send is True
    assert d.reason == "no_previous_command"


def test_hysteresis_small_delta_recent_holds() -> None:
    """Delta=0, frischer Command -> kein Send (Battery)."""
    now = datetime.now(tz=UTC)
    recent = now - timedelta(minutes=10)
    d = hysteresis_decision(prev_setpoint_c=21, prev_issued_at=recent, new_setpoint_c=21, now=now)
    assert d.should_send is False
    assert "hysteresis" in d.reason


def test_hysteresis_delta_meets_threshold_sends() -> None:
    """|22-21| = 1 == HYSTERESIS_C -> sendet (>=)."""
    now = datetime.now(tz=UTC)
    d = hysteresis_decision(
        prev_setpoint_c=21,
        prev_issued_at=now - timedelta(minutes=30),
        new_setpoint_c=21 + HYSTERESIS_C,
        now=now,
    )
    assert d.should_send is True
    assert "delta" in d.reason


def test_hysteresis_heartbeat_after_long_silence_sends() -> None:
    """Selbst Delta=0 nach > HEARTBEAT_INTERVAL -> erneut senden (re-sync)."""
    now = datetime.now(tz=UTC)
    old = now - HEARTBEAT_INTERVAL - timedelta(minutes=5)
    d = hysteresis_decision(prev_setpoint_c=21, prev_issued_at=old, new_setpoint_c=21, now=now)
    assert d.should_send is True
    assert "heartbeat" in d.reason


@pytest.mark.parametrize(
    ("prev", "new", "should"),
    [
        (21, 21, False),  # delta=0
        (21, 22, True),  # delta=1 == threshold
        (21, 23, True),  # delta=2 > threshold
        (20, 19, True),  # delta=1 abwaerts
    ],
)
def test_hysteresis_delta_table(prev: int, new: int, should: bool) -> None:
    now = datetime.now(tz=UTC)
    recent = now - timedelta(minutes=15)
    d = hysteresis_decision(
        prev_setpoint_c=prev, prev_issued_at=recent, new_setpoint_c=new, now=now
    )
    assert d.should_send is should
