"""Sprint 11 T6 — Health-Alert-Stub Smoke-Tests (AE-53).

Nur Aufruf-Verifikation. Audit der tatsaechlichen Log-Records erfolgt
via Code-Review von ``services/health_alerts.py`` UND via journalctl-
grep nach Deploy auf heizung-test.

Hintergrund (Sprint 11 T6 Diagnose 2026-05-18): caplog + heizung.*-
Logger-Hierarchie hat im Repo einen Propagations-Quirk (siehe Sprint
9.11x.c-Workaround in ``test_mqtt_subscriber._enable_subscriber_log_
propagation``). Statt das Workaround pro Test-Datei zu duplizieren,
verzichten wir auf Logger-Asserts und verlassen uns auf statisches
Code-Review + Live-Container-Log. Konsolidierung als wiederverwendbarer
Helper in ``tests/conftest.py`` ist T7-Backlog.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from heizung.services.health_alerts import emit_health_alert
from tests.conftest import enable_heizung_log_propagation


def test_emit_health_alert_level_2_no_exception() -> None:
    """Smoke-Test Stufe-2: kein Crash beim Aufruf."""
    emit_health_alert(
        level=2,
        device_id=1,
        dev_eui="deadbeef01",
        reason="offline_24h",
    )


def test_emit_health_alert_level_3_with_context_no_exception() -> None:
    """Smoke-Test Stufe-3: context-Dict wird akzeptiert."""
    emit_health_alert(
        level=3,
        device_id=42,
        dev_eui="cafef00d42",
        reason="implausible_readings_24h",
        context={"counter": 15},
    )


def test_health_alert_payload_full_fields(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sprint 14c T3: alle 10 Soll-Felder landen im Log-Record.

    caplog-Quirk-Workaround (§5.36 + §5.37): Propagation auf dem
    health_alerts-Logger erzwingen, sonst sieht caplog die Records nicht.
    """
    enable_heizung_log_propagation(monkeypatch, "heizung.services.health_alerts")
    triggered = datetime(2026, 5, 27, 16, 0, tzinfo=UTC)
    last_uplink = datetime(2026, 5, 26, 15, 30, tzinfo=UTC)

    with caplog.at_level(logging.WARNING, logger="heizung.services.health_alerts"):
        emit_health_alert(
            level=3,
            device_id=7,
            dev_eui="deadbeef07",
            reason="implausible_readings_24h",
            device_name="Vicki Bad",
            room_name="101",
            zone_name="Bad",
            triggered_at=triggered,
            last_uplink_at=last_uplink,
            implausible_count_24h=12,
        )

    records = [r for r in caplog.records if r.getMessage() == "health_alert"]
    assert records, "kein health_alert Log-Record erfasst (Propagation-Quirk?)"
    rec = records[-1]
    assert rec.level == 3  # type: ignore[attr-defined]
    assert rec.device_id == 7  # type: ignore[attr-defined]
    assert rec.dev_eui == "deadbeef07"  # type: ignore[attr-defined]
    assert rec.reason == "implausible_readings_24h"  # type: ignore[attr-defined]
    assert rec.device_name == "Vicki Bad"  # type: ignore[attr-defined]
    assert rec.room_name == "101"  # type: ignore[attr-defined]
    assert rec.zone_name == "Bad"  # type: ignore[attr-defined]
    assert rec.triggered_at == triggered.isoformat()  # type: ignore[attr-defined]
    assert rec.last_uplink_at == last_uplink.isoformat()  # type: ignore[attr-defined]
    assert rec.implausible_count_24h == 12  # type: ignore[attr-defined]
