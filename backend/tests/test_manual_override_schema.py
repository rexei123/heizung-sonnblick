"""Pydantic-Tests fuer ManualOverride-Schemas (Sprint 9.9 T1).

Reine Validierungs-Logik, kein DB-Zugriff. Decken die Brief-Akzeptanz-
kriterien:

- ``setpoint`` ausserhalb 5..30 wird abgelehnt
- ``setpoint`` 21.55 -> 21.6 quantized
- ``source = 'device'`` ist im Create-Schema NICHT erlaubt
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from heizung.schemas.manual_override import (
    ManualOverrideCreate,
    ManualOverrideRevoke,
)


def _valid_create_payload() -> dict[str, object]:
    return {
        "setpoint": Decimal("21.5"),
        "source": "frontend_4h",
        "reason": "Wunsch der Rezeption",
    }


def test_create_minimal_payload() -> None:
    o = ManualOverrideCreate(**_valid_create_payload())
    assert o.setpoint == Decimal("21.5")
    assert o.source == "frontend_4h"
    assert o.reason == "Wunsch der Rezeption"


def test_create_reason_optional() -> None:
    payload = _valid_create_payload()
    payload.pop("reason")
    o = ManualOverrideCreate(**payload)
    assert o.reason is None


def test_create_quantizes_two_decimals_to_one() -> None:
    """21.55 -> 21.6 (Banker's Rounding, halb gerade)."""
    o = ManualOverrideCreate(**(_valid_create_payload() | {"setpoint": Decimal("21.55")}))
    assert o.setpoint == Decimal("21.6")


def test_create_quantizes_two_decimals_banker_rounding_down() -> None:
    """21.45 -> 21.4 (Banker's Rounding zur geraden Ziffer)."""
    o = ManualOverrideCreate(**(_valid_create_payload() | {"setpoint": Decimal("21.45")}))
    assert o.setpoint == Decimal("21.4")


def test_create_rejects_setpoint_below_min() -> None:
    with pytest.raises(ValidationError):
        ManualOverrideCreate(**(_valid_create_payload() | {"setpoint": Decimal("4.9")}))


def test_create_rejects_setpoint_above_max() -> None:
    with pytest.raises(ValidationError):
        ManualOverrideCreate(**(_valid_create_payload() | {"setpoint": Decimal("30.1")}))


def test_create_accepts_setpoint_at_lower_bound() -> None:
    o = ManualOverrideCreate(**(_valid_create_payload() | {"setpoint": Decimal("5.0")}))
    assert o.setpoint == Decimal("5.0")


def test_create_accepts_setpoint_at_upper_bound() -> None:
    o = ManualOverrideCreate(**(_valid_create_payload() | {"setpoint": Decimal("30.0")}))
    assert o.setpoint == Decimal("30.0")


def test_create_rejects_device_source() -> None:
    """`device` ist intern (device_adapter) und im Create-Schema verboten."""
    with pytest.raises(ValidationError):
        ManualOverrideCreate(**(_valid_create_payload() | {"source": "device"}))


def test_create_accepts_frontend_4h() -> None:
    o = ManualOverrideCreate(**(_valid_create_payload() | {"source": "frontend_4h"}))
    assert o.source == "frontend_4h"


def test_create_accepts_frontend_midnight() -> None:
    o = ManualOverrideCreate(**(_valid_create_payload() | {"source": "frontend_midnight"}))
    assert o.source == "frontend_midnight"


def test_create_accepts_frontend_checkout() -> None:
    o = ManualOverrideCreate(**(_valid_create_payload() | {"source": "frontend_checkout"}))
    assert o.source == "frontend_checkout"


def test_create_rejects_unknown_source() -> None:
    with pytest.raises(ValidationError):
        ManualOverrideCreate(**(_valid_create_payload() | {"source": "frontend_forever"}))


def test_create_rejects_reason_too_long() -> None:
    with pytest.raises(ValidationError):
        ManualOverrideCreate(**(_valid_create_payload() | {"reason": "x" * 501}))


def test_revoke_minimal() -> None:
    r = ManualOverrideRevoke()
    assert r.revoked_reason is None


def test_revoke_with_reason() -> None:
    r = ManualOverrideRevoke(revoked_reason="auto: guest checked out")
    assert r.revoked_reason == "auto: guest checked out"


def test_revoke_rejects_reason_too_long() -> None:
    with pytest.raises(ValidationError):
        ManualOverrideRevoke(revoked_reason="x" * 501)
