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

from heizung.services.health_alerts import emit_health_alert


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
