"""Sprint 18 / T2 — Sammelmail statt Einzelmails.

Kern der Zusage: **eine Mail je Lauf**, nie eine je Geraet. Faellt das
Gateway aus, kippen alle Vickis im selben Tick auf ``silent`` — ohne
Aggregation waeren das 104 Mails in einer Minute.

Keine DB, kein SMTP: ``mailer.send_mail`` und der Redis-Client werden
ersetzt. Geprueft wird, **wie oft** versendet wird und **was** drinsteht.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import redis

from heizung.services import alert_throttle, health_alerts, mailer, redis_client

JETZT = datetime(2026, 9, 19, 8, 0, 0, tzinfo=UTC)
LETZTER_UPLINK = datetime(2026, 9, 17, 22, 30, 0, tzinfo=UTC)


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


class _BrokenRedis:
    def set(self, *args: Any, **kwargs: Any) -> None:
        raise redis.ConnectionError("simulierter Ausfall")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise redis.ConnectionError("simulierter Ausfall")


class _Postfach:
    """Sammelt, was ``send_mail`` bekommen haette."""

    def __init__(self) -> None:
        self.mails: list[dict[str, str]] = []

    def __call__(self, *, recipient: str | None, subject: str, body: str) -> mailer.MailResult:
        self.mails.append({"recipient": recipient or "", "subject": subject, "body": body})
        return mailer.MailResult(True, None, "Testzustellung")


@pytest.fixture
def postfach(monkeypatch: pytest.MonkeyPatch) -> _Postfach:
    p = _Postfach()
    monkeypatch.setattr(health_alerts.mailer, "send_mail", p)
    return p


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    return fake


def _transition(nr: int, *, reason: str = health_alerts.REASON_OFFLINE) -> dict[str, Any]:
    """Ein Uebergang, wie ``health_tasks`` ihn sammelt."""
    return {
        "device_id": nr,
        "dev_eui": f"70b3d57ed000{nr:04x}",
        "reason": reason,
        "device_name": f"{nr:03d}",
        "room_name": str(100 + nr),
        "zone_name": "Schlafzimmer",
        "triggered_at": JETZT,
        "last_uplink_at": LETZTER_UPLINK,
        "implausible_count_24h": None,
    }


def _transitions(anzahl: int) -> list[dict[str, Any]]:
    return [_transition(i) for i in range(1, anzahl + 1)]


# ---------------------------------------------------------------------------
# Die drei geforderten Mengen
# ---------------------------------------------------------------------------


def test_ein_geraet_eine_mail_mit_einzelheiten(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(1), recipient="chef@example.com"
    )

    assert gemeldet == 1
    assert len(postfach.mails) == 1
    mail = postfach.mails[0]
    # Einzelfall: Geraetename im Betreff, damit man ihn am Sperrbildschirm sieht.
    assert "001" in mail["subject"]
    assert "Zimmer 101" in mail["subject"]
    assert "70b3d57ed0000001" in mail["body"]
    assert "Batterien leer" in mail["body"]


def test_sieben_geraete_eine_mail_mit_liste(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(7), recipient="chef@example.com"
    )

    assert gemeldet == 7
    assert len(postfach.mails) == 1, "genau eine Mail, nicht sieben"
    body = postfach.mails[0]["body"]
    assert "7 Thermostate" in postfach.mails[0]["subject"]
    # Unter der Kurzform-Schwelle: jedes Geraet mit Einzelheiten.
    for i in range(1, 8):
        assert f"70b3d57ed000{i:04x}" in body
    assert "Letzte Meldung" in body


def test_fuenfzehn_geraete_eine_mail_in_kurzform(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(15), recipient="chef@example.com"
    )

    assert gemeldet == 15
    assert len(postfach.mails) == 1
    body = postfach.mails[0]["body"]
    assert "15 Thermostate" in body
    # Kurzform: Zimmerliste ja, Einzelheiten nein.
    assert "101" in body and "115" in body
    assert "70b3d57ed0000001" not in body, "keine DevEUIs in der Kurzform"
    assert "Letzte Meldung" not in body
    # Stattdessen der Hinweis auf die gemeinsame Ursache.
    assert "Gateway" in body


# ---------------------------------------------------------------------------
# Bremse und Randfaelle
# ---------------------------------------------------------------------------


def test_zweiter_lauf_meldet_dieselben_geraete_nicht_erneut(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """Die Bremse wirkt weiterhin pro Geraet, trotz Sammelversand."""
    health_alerts.handle_silent_transitions(_transitions(3), recipient="chef@example.com")
    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(3), recipient="chef@example.com"
    )

    assert gemeldet == 0
    assert len(postfach.mails) == 1, "kein zweiter Versand"


def test_nur_das_neue_geraet_kommt_in_die_zweite_mail(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """Ein frisches Geraet hebt die Sperre der anderen NICHT auf."""
    health_alerts.handle_silent_transitions(_transitions(3), recipient="chef@example.com")
    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(4), recipient="chef@example.com"
    )

    assert gemeldet == 1
    assert len(postfach.mails) == 2
    zweite = postfach.mails[1]["body"]
    assert "70b3d57ed0000004" in zweite
    assert "70b3d57ed0000001" not in zweite


def test_leere_liste_erzeugt_keine_mail(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    gemeldet = health_alerts.handle_silent_transitions([], recipient="chef@example.com")

    assert gemeldet == 0
    assert postfach.mails == []


def test_ohne_empfaenger_keine_mail(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    """Keine Alarm-Adresse hinterlegt: Logger ja, Mail nein."""
    gemeldet = health_alerts.handle_silent_transitions(_transitions(5), recipient=None)

    assert gemeldet == 0
    assert postfach.mails == []


def test_stufe_3_kommt_nicht_in_die_mail(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    """Implausible Messwerte sind ein anderer Vorgang — in Sprint 18
    bewusst Logger-only."""
    gemischt = [
        _transition(1),
        _transition(2, reason=health_alerts.REASON_IMPLAUSIBLE),
        _transition(3, reason=health_alerts.REASON_IMPLAUSIBLE),
    ]

    gemeldet = health_alerts.handle_silent_transitions(gemischt, recipient="chef@example.com")

    assert gemeldet == 1
    body = postfach.mails[0]["body"]
    assert "70b3d57ed0000001" in body
    assert "70b3d57ed0000002" not in body


def test_nur_stufe_3_erzeugt_gar_keine_mail(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    nur_stufe3 = [_transition(i, reason=health_alerts.REASON_IMPLAUSIBLE) for i in (1, 2)]

    gemeldet = health_alerts.handle_silent_transitions(nur_stufe3, recipient="chef@example.com")

    assert gemeldet == 0
    assert postfach.mails == []


def test_bei_redis_ausfall_trotzdem_nur_eine_mail(
    postfach: _Postfach, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der eigentliche Gewinn der Aggregation.

    Ohne Redis laesst ``alert_throttle`` alles durch (bewusst, siehe dort).
    Vor T2 waeren das 104 Einzelmails gewesen. Jetzt ist es eine.
    """
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _BrokenRedis())

    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(104), recipient="chef@example.com"
    )

    assert gemeldet == 104
    assert len(postfach.mails) == 1


def test_versandfehler_wirft_nicht(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein nicht erreichbarer SMTP-Server darf den Health-Beat nicht kippen."""

    def _scheitert(**kwargs: Any) -> mailer.MailResult:
        return mailer.MailResult(False, "SMTPConnectError", "Server nicht erreichbar")

    monkeypatch.setattr(health_alerts.mailer, "send_mail", _scheitert)

    gemeldet = health_alerts.handle_silent_transitions(
        _transitions(2), recipient="chef@example.com"
    )

    # Gemeldet wurde trotzdem — die Bremse ist gesetzt, die Zahl stimmt.
    assert gemeldet == 2


def test_geraet_ohne_zimmer_erscheint_als_pool(postfach: _Postfach, fake_redis: _FakeRedis) -> None:
    """Pool-Geraete haben keine Zone und kein Zimmer. Die Mail darf davon
    nicht durcheinandergeraten — im Eingangstest sind alle 104 im Pool."""
    t = _transition(1)
    t["room_name"] = None
    t["zone_name"] = None

    health_alerts.handle_silent_transitions([t], recipient="chef@example.com")

    assert "Pool" in postfach.mails[0]["body"]


def test_kurzform_schwelle_greift_genau_ab_zehn(
    postfach: _Postfach, fake_redis: _FakeRedis
) -> None:
    """Neun Geraete noch mit Einzelheiten, zehn schon in Kurzform."""
    health_alerts.handle_silent_transitions(_transitions(9), recipient="chef@example.com")
    assert "Letzte Meldung" in postfach.mails[0]["body"]

    for t in _transitions(9):
        alert_throttle.reset(alert_throttle.KIND_DEVICE_SILENT, t["dev_eui"])

    health_alerts.handle_silent_transitions(_transitions(10), recipient="chef@example.com")
    assert "Letzte Meldung" not in postfach.mails[1]["body"]
