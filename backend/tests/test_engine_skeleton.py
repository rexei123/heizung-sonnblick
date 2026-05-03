"""Sprint 9.3 — Engine-Skeleton Pure-Function-Tests.

Layer 1 (Base) + Layer 5 (Clamp) + Hysterese. Kein DB-Zugriff,
deshalb auch keine pytest-postgresql noetig.

DB-Wrapper-Tests (``_load_room_context``, ``_last_command_for_room``,
``evaluate_room``) folgen in Sprint 9.5 zusammen mit Audit-Persistenz —
dort lohnt sich die Integration-Test-Setup-Investition.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from heizung.models.enums import CommandReason, EventLogLayer, RoomStatus, RuleConfigScope
from heizung.rules.constants import FROST_PROTECTION_C
from heizung.rules.engine import (
    HEARTBEAT_INTERVAL,
    HYSTERESIS_C,
    MAX_SETPOINT_C,
    _RoomContext,
    hysteresis_decision,
    layer_base_target,
    layer_clamp,
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
    scope: RuleConfigScope, *, t_occupied: float | None = None, t_vacant: float | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        scope=scope,
        t_occupied=Decimal(str(t_occupied)) if t_occupied is not None else None,
        t_vacant=Decimal(str(t_vacant)) if t_vacant is not None else None,
    )


def _ctx(
    *,
    status: RoomStatus = RoomStatus.OCCUPIED,
    room_type: SimpleNamespace | None = None,
    rule_configs: list[SimpleNamespace] | None = None,
) -> _RoomContext:
    return _RoomContext(  # type: ignore[arg-type]
        room=_make_room(status),
        room_type=room_type or _make_room_type(),
        rule_configs=rule_configs or [],
    )


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


def test_clamp_within_range_passes_through() -> None:
    step = layer_clamp(21, _ctx())
    assert step.layer == EventLogLayer.HARD_CLAMP
    assert step.setpoint_c == 21
    assert "within" in step.detail


def test_clamp_above_max_caps() -> None:
    step = layer_clamp(35, _ctx())
    assert step.setpoint_c == MAX_SETPOINT_C
    assert "clamped" in step.detail


def test_clamp_below_frost_lifts_to_frost() -> None:
    step = layer_clamp(5, _ctx())
    assert step.setpoint_c == int(FROST_PROTECTION_C)
    assert step.reason == CommandReason.FROST_PROTECTION


def test_clamp_room_type_max_respected() -> None:
    """Bad mit max_temp=25 bekommt 25, nicht MAX_SETPOINT_C=30."""
    step = layer_clamp(28, _ctx(room_type=_make_room_type(max_c=25.0)))
    assert step.setpoint_c == 25


def test_clamp_room_type_min_below_frost_is_ignored() -> None:
    """Auch wenn room_type.min_temp=8 — System-Frostschutz hat Vorrang."""
    step = layer_clamp(7, _ctx(room_type=_make_room_type(min_c=8.0)))
    assert step.setpoint_c == int(FROST_PROTECTION_C)


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
