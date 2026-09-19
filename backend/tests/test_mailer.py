"""Sprint 18 / T3 — SMTP-Versand.

Kein Netzwerk: ``_deliver`` wird ersetzt, sonst wuerde jeder Test eine
echte Verbindung aufbauen. Fuer die drei ``SMTP_SECURITY``-Varianten
werden stattdessen ``smtplib.SMTP`` und ``smtplib.SMTP_SSL`` ersetzt —
dort ist gerade die Frage, **welche** Klasse mit **welchen** Schritten
verwendet wird.

Drei Zusagen, die hier gepinnt sind:

1. ``send_mail`` **wirft nie**. Ein fehlgeschlagener Alarm darf den
   Health-Beat oder den Import-Watchdog nicht abbrechen.
2. Das Passwort landet **nirgends** — nicht im Log, nicht im Ergebnis.
3. Die Sicherheitsvariante bestimmt den Verbindungsaufbau, und ``none``
   macht wirklich kein STARTTLS (sonst waere der Schalter eine Luege).
"""

from __future__ import annotations

import logging
import smtplib
from typing import Any

import pytest

from heizung.services import mailer

GEHEIM = "streng-geheimes-passwort-xyz"


class _Settings:
    """Nur die Felder, die ``mailer`` liest."""

    def __init__(self, **kwargs: Any) -> None:
        self.smtp_enabled = kwargs.get("enabled", True)
        self.smtp_host = kwargs.get("host", "mail.example.com")
        self.smtp_port = kwargs.get("port", 587)
        self.smtp_user = kwargs.get("user", "alarm@example.com")
        self.smtp_password = kwargs.get("password", GEHEIM)
        self.smtp_from = kwargs.get("sender", "")
        self.smtp_security = kwargs.get("security", "starttls")
        self.smtp_timeout_seconds = kwargs.get("timeout", 20)


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> _Settings:
    s = _Settings(**kwargs)
    monkeypatch.setattr(mailer, "get_settings", lambda: s)
    return s


class _FakeServer:
    """Zeichnet auf, was auf der Verbindung passiert ist."""

    def __init__(self, protokoll: list[str], *args: Any, **kwargs: Any) -> None:
        self.protokoll = protokoll
        self.protokoll.append(f"connect:{args[0]}:{args[1]}:timeout={kwargs.get('timeout')}")

    def __enter__(self) -> _FakeServer:
        return self

    def __exit__(self, *args: Any) -> None:
        self.protokoll.append("close")

    def starttls(self, context: Any = None) -> None:
        self.protokoll.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.protokoll.append(f"login:{user}")

    def send_message(self, msg: Any) -> None:
        self.protokoll.append(f"send:{msg['To']}")


def _fake_smtp(protokoll: list[str], marke: str) -> Any:
    def _factory(*args: Any, **kwargs: Any) -> _FakeServer:
        protokoll.append(f"klasse:{marke}")
        return _FakeServer(protokoll, *args, **kwargs)

    return _factory


# ---------------------------------------------------------------------------
# Die drei Sicherheitsvarianten
# ---------------------------------------------------------------------------


def test_starttls_baut_klartext_auf_und_ruestet_nach(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, security="starttls", port=587)
    protokoll: list[str] = []
    monkeypatch.setattr(smtplib, "SMTP", _fake_smtp(protokoll, "SMTP"))

    result = mailer.send_mail(recipient="chef@example.com", subject="Test", body="Text")

    assert result.sent is True
    assert protokoll == [
        "klasse:SMTP",
        "connect:mail.example.com:587:timeout=20",
        "starttls",
        "login:alarm@example.com",
        "send:chef@example.com",
        "close",
    ]


def test_ssl_nutzt_smtp_ssl_und_kein_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, security="ssl", port=465)
    protokoll: list[str] = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", _fake_smtp(protokoll, "SMTP_SSL"))

    result = mailer.send_mail(recipient="chef@example.com", subject="Test", body="Text")

    assert result.sent is True
    assert "klasse:SMTP_SSL" in protokoll
    assert "starttls" not in protokoll, "implizites TLS braucht kein Upgrade"
    assert "connect:mail.example.com:465:timeout=20" in protokoll


def test_none_macht_wirklich_kein_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sonst waere der Schalter eine Luege: wer ``none`` waehlt, weil sein
    Relay kein TLS kann, bekaeme trotzdem einen STARTTLS-Versuch."""
    _patch_settings(monkeypatch, security="none", port=25)
    protokoll: list[str] = []
    monkeypatch.setattr(smtplib, "SMTP", _fake_smtp(protokoll, "SMTP"))

    result = mailer.send_mail(recipient="chef@example.com", subject="Test", body="Text")

    assert result.sent is True
    assert "starttls" not in protokoll


def test_ohne_benutzer_keine_anmeldung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein Relay im eigenen Netz verlangt oft keine Anmeldung. Ein
    ``login('')`` waere dort ein Fehler."""
    _patch_settings(monkeypatch, user="", sender="alarm@example.com")
    protokoll: list[str] = []
    monkeypatch.setattr(smtplib, "SMTP", _fake_smtp(protokoll, "SMTP"))

    result = mailer.send_mail(recipient="chef@example.com", subject="Test", body="Text")

    assert result.sent is True
    assert not any(e.startswith("login") for e in protokoll)


# ---------------------------------------------------------------------------
# Konfigurationszustaende sind keine Fehler
# ---------------------------------------------------------------------------


def test_deaktiviert_meldet_statt_zu_versuchen(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, enabled=False)

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert result.sent is False
    assert result.reason == mailer.SKIP_DISABLED


def test_ohne_host_meldet_statt_zu_versuchen(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, host="")

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert result.sent is False
    assert result.reason == mailer.SKIP_NO_HOST


def test_ohne_empfaenger_ist_ein_konfigurationszustand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kein Fehler, sondern "noch nichts eingetragen" — die Meldung sagt,
    wo man es eintraegt."""
    _patch_settings(monkeypatch)

    result = mailer.send_mail(recipient=None, subject="T", body="B")

    assert result.sent is False
    assert result.reason == mailer.SKIP_NO_RECIPIENT
    assert "Einstellungen" in result.detail


def test_absender_faellt_auf_benutzer_zurueck(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, sender="", user="konto@example.com")
    protokoll: list[str] = []
    gesendet: list[Any] = []

    class _Merker(_FakeServer):
        def send_message(self, msg: Any) -> None:
            gesendet.append(msg)

    def _factory(*args: Any, **kwargs: Any) -> _Merker:
        return _Merker(protokoll, *args, **kwargs)

    monkeypatch.setattr(smtplib, "SMTP", _factory)

    mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert gesendet[0]["From"] == "konto@example.com"


# ---------------------------------------------------------------------------
# Die beiden harten Zusagen
# ---------------------------------------------------------------------------


def test_wirft_nie_bei_verbindungsfehler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ein nicht erreichbarer Server darf den Alarm-Pfad nicht abbrechen."""
    _patch_settings(monkeypatch)

    def _explodiert(*args: Any, **kwargs: Any) -> None:
        raise OSError("Connection refused")

    monkeypatch.setattr(smtplib, "SMTP", _explodiert)

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert result.sent is False
    assert result.reason == "OSError"


def test_wirft_nie_bei_authentifizierungsfehler(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)

    def _explodiert(*args: Any, **kwargs: Any) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    monkeypatch.setattr(smtplib, "SMTP", _explodiert)

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert result.sent is False
    assert result.reason == "SMTPAuthenticationError"


def test_passwort_landet_weder_im_log_noch_im_ergebnis(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Die wichtigste Zusage dieses Moduls.

    smtplib-Fehlertexte tragen die Server-Antwort; bei manchen Anbietern
    steht darin der Benutzername. Das Passwort darf unter keinen Umstaenden
    irgendwo auftauchen — auch nicht, wenn die Ausnahme es enthielte.
    """
    _patch_settings(monkeypatch, password=GEHEIM)

    def _explodiert(*args: Any, **kwargs: Any) -> None:
        # Bewusst boesartig: die Ausnahme selbst traegt das Passwort.
        raise smtplib.SMTPException(f"auth failed for user with password {GEHEIM}")

    monkeypatch.setattr(smtplib, "SMTP", _explodiert)

    with caplog.at_level(logging.WARNING, logger="heizung.services.mailer"):
        result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert result.sent is False
    # Harte Zusage: das Passwort steht NIRGENDS — weder im Log noch im
    # Ergebnis, auch wenn die Ausnahme es selbst mitbringt.
    assert GEHEIM not in caplog.text
    assert GEHEIM not in result.detail
    # Der Rest des Fehlertexts bleibt lesbar, sonst waere die Meldung
    # nutzlos.
    assert "auth failed" in result.detail
    assert mailer.REDACTED in result.detail


def test_settings_passwort_wird_nie_ins_ergebnis_geschrieben(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der saubere Fall: eine Ausnahme ohne Passwort darf auch keines
    bekommen."""
    _patch_settings(monkeypatch, password=GEHEIM)

    def _explodiert(*args: Any, **kwargs: Any) -> None:
        raise smtplib.SMTPServerDisconnected("Server hat aufgelegt")

    monkeypatch.setattr(smtplib, "SMTP", _explodiert)

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert GEHEIM not in result.detail
    assert GEHEIM not in (result.reason or "")


def test_erfolgsmeldung_nennt_den_empfaenger(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    protokoll: list[str] = []
    monkeypatch.setattr(smtplib, "SMTP", _fake_smtp(protokoll, "SMTP"))

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")

    assert result.sent is True
    assert "chef@example.com" in result.detail
    assert result.reason is None
