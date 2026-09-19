"""SMTP-Versand fuer Betriebsalarme (Sprint 18, B-15b-1).

Bis Sprint 17 gab es im gesamten Backend **keinen** Mailversand. Alarme
landeten im Container-Log, wo sie niemand liest: ``emit_health_alert`` war
ein Logger-Stub, der AE-66-Watchdog schrieb ein Audit ohne Leser, und
``global_config.alert_email`` war ein Schalter ohne Konsumenten. Dieses
Modul schliesst die Luecke.

Warum ``smtplib`` aus der Standardbibliothek
--------------------------------------------

Kein neues Abhaengigkeits-Glied fuer eine Aufgabe, die die Standard-
bibliothek seit Jahrzehnten kann. §5.29 (passlib) ist die Lesson dazu: eine
Wrapper-Library ist ein verstecktes Stabilitaetsrisiko, wenn die darunter
liegende API direkt und stabil ist.

Der Aufruf ist **synchron**. Beide Konsumenten laufen im Celery-Worker,
nicht im FastAPI-Event-Loop — dort ist blockierendes I/O richtig. Ein
``smtp_timeout_seconds`` begrenzt jeden Versuch, damit ein haengender
Server den Beat-Tick nicht festhaelt.

Zugangsdaten und Empfaenger sind getrennt
-----------------------------------------

- **Zugangsdaten** (Host, Port, Benutzer, Passwort) kommen aus der
  Umgebung. Nie aus der Datenbank, nie als Argument, nie im Log.
- **Empfaenger** kommt aus ``global_config.alert_email``. Er ist eine
  Hotelier-Einstellung und gehoert in die Oberflaeche.

Drei Sicherheitsvarianten
-------------------------

``SMTP_SECURITY`` waehlt zwischen:

- ``starttls`` (Vorgabe, Port 587): Klartext-Verbindung, dann Upgrade.
- ``ssl`` (Port 465): implizites TLS ab dem ersten Byte.
- ``none``: ohne Verschluesselung. Nur fuer einen Relay im selben Netz
  vertretbar — ueber das Internet gingen Passwort und Inhalt offen.

Was dieses Modul NICHT tut
--------------------------

Es kennt keine Wiederholungsbremse. Ob ein Alarm ueberhaupt raus soll,
entscheidet ``services/alert_throttle.py`` vor dem Aufruf. Diese Trennung
ist Absicht: der Versand soll nichts verschlucken, und die Bremse soll
nichts versenden.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from heizung.config import get_settings

logger = logging.getLogger(__name__)

# Der Versand meldet Erfolg oder Grund — er wirft nicht. Ein fehlgeschlagener
# Alarm darf den Health-Beat oder den Import-Watchdog nicht abbrechen; beide
# haben wichtigere Aufgaben als die Zustellung.
SKIP_DISABLED = "smtp_deaktiviert"
SKIP_NO_HOST = "kein_smtp_host"
SKIP_NO_RECIPIENT = "kein_empfaenger"


@dataclass(frozen=True, slots=True)
class MailResult:
    """Ergebnis eines Versandversuchs.

    :param sent: ``True`` nur, wenn der Server die Nachricht angenommen hat.
    :param reason: ``None`` bei Erfolg, sonst ein Kurzgrund fuer das Log.
    :param detail: Klartext fuer den Menschen — beim Test-Befehl die
        eigentliche Ausgabe, im Alarm-Pfad die Logzeile.
    """

    sent: bool
    reason: str | None = None
    detail: str = ""


def _build_message(*, sender: str, recipient: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _deliver(msg: EmailMessage) -> None:
    """Oeffnet die Verbindung passend zur gewaehlten Sicherheitsvariante.

    Ausgelagert, damit die Tests genau diese Funktion ersetzen koennen und
    der Rest des Moduls ohne Netzwerk pruefbar bleibt.
    """
    s = get_settings()
    context = ssl.create_default_context()

    if s.smtp_security == "ssl":
        with smtplib.SMTP_SSL(
            s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context
        ) as server:
            if s.smtp_user:
                server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
        return

    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as server:
        if s.smtp_security == "starttls":
            server.starttls(context=context)
        if s.smtp_user:
            server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)


REDACTED = "<entfernt>"


def _redact(text: str) -> str:
    """Entfernt das SMTP-Passwort aus einem Fehlertext.

    Warum das noetig ist: ``smtplib``-Ausnahmen tragen die **Server-
    Antwort** im Text. Manche Anbieter echoen bei einem fehlgeschlagenen
    ``AUTH PLAIN`` Teile der uebergebenen Zugangsdaten zurueck, und der
    Fehlertext landet sonst ungefiltert im Container-Log — wo er bei der
    naechsten Diagnose in einem Screenshot auftaucht.

    Der Anlass ist nicht hypothetisch: am 19.09. war der Inhalt der .env
    in einem Screenshot sichtbar (B-18-2). Ein Alarm-Pfad, der genau
    dieses Passwort bei jedem Fehlversuch ins Log schreibt, waere die
    zuverlaessigste Art, es dort erneut hinzubekommen — und zwar
    ausgerechnet dann, wenn jemand wegen eines Problems hinsieht.

    Bewusst simpel: kein Muster-Raten, sondern ein Ersetzen des konkreten
    Wertes aus der Konfiguration. Ein zu cleverer Filter wuerde
    Fehlertexte unlesbar machen, ohne mehr Sicherheit zu bringen.
    """
    s = get_settings()
    if s.smtp_password and s.smtp_password in text:
        text = text.replace(s.smtp_password, REDACTED)
    return text


def send_mail(*, recipient: str | None, subject: str, body: str) -> MailResult:
    """Versendet eine Nachricht. Wirft nicht — meldet.

    :param recipient: Zieladresse, ueblicherweise ``global_config.alert_email``.
        ``None`` oder leer bedeutet "kein Empfaenger eingetragen" und ist
        kein Fehler, sondern ein Konfigurationszustand.
    :param subject: Betreff, einzeilig.
    :param body: Textkoerper.
    :return: ``MailResult``. ``sent=False`` heisst nie "kaputt" allein —
        ``reason`` unterscheidet Konfiguration von Stoerung.
    """
    s = get_settings()

    if not s.smtp_enabled:
        return MailResult(False, SKIP_DISABLED, "SMTP ist nicht aktiviert (SMTP_ENABLED).")
    if not s.smtp_host:
        return MailResult(False, SKIP_NO_HOST, "Kein SMTP_HOST gesetzt.")
    if not recipient:
        return MailResult(
            False,
            SKIP_NO_RECIPIENT,
            "Keine Alarm-Adresse hinterlegt — in den Einstellungen unter 'Alarm-Email' eintragen.",
        )

    sender = s.smtp_from or s.smtp_user
    if not sender:
        return MailResult(
            False,
            SKIP_NO_HOST,
            "Weder SMTP_FROM noch SMTP_USER gesetzt — kein Absender bestimmbar.",
        )

    msg = _build_message(sender=sender, recipient=recipient, subject=subject, body=body)

    try:
        _deliver(msg)
    except Exception as exc:  # noqa: BLE001 — jeder Fehler wird gemeldet, keiner geworfen
        text = _redact(str(exc)[:200])
        logger.warning("mail_send_failed", extra={"error_type": type(exc).__name__, "error": text})
        return MailResult(False, type(exc).__name__, f"{type(exc).__name__}: {text}")

    logger.info("mail_sent", extra={"subject": subject})
    return MailResult(True, None, f"Nachricht an {recipient} uebergeben.")
