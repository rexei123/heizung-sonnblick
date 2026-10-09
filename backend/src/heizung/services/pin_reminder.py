"""Erinnerung an einen gesetzten Rueckfallpunkt (Sprint 20g, H-6 T10).

Ein ``PIN_SHA`` in ``infra/deploy/.env`` haelt den Server auf einem Commit.
Das ist der Zweck des Rueckfallpunkts (AE-77, RUNBOOK §10u) — und seine
Gefahr: **der Server zieht keine Merges mehr.** Wer den Pin setzt, weiss
das. Wer ihn eine Woche spaeter vergessen hat, merkt es daran, dass
Aenderungen nicht ankommen — und sucht den Fehler woanders.

Deshalb: Mail nach **sieben Tagen**, danach woechentlich, solange der Pin
steht.

Erinnerung, nicht Alarm
-----------------------

Ein gesetzter Pin ist eine Entscheidung, kein Fehler. Der Text sagt
deshalb nicht "Problem", sondern was gilt, was das heisst und wie man es
beendet. Ein Alarm, der eine bewusste Entscheidung anmahnt, wird nach dem
zweiten Mal weggeklickt (§5.79).

Woher der Pin kommt
-------------------

Aus der **Umgebung** des Containers (``settings.pin_sha``): ``.env`` ist
per ``env_file`` an api, worker und beat gehaengt. Damit traegt die
Umgebung den Pin, mit dem der **laufende** Stand deployt wurde — nicht
den, den jemand gerade in die Datei geschrieben hat. Das ist die richtige
Groesse: ein Pin, dessen Deploy noch nicht gelaufen ist (etwa weil die
Deploy-Sperre steht, §10p), wirkt nicht und soll nicht erinnern.

Woher die Zeit kommt
--------------------

Aus ``global_config.pin_sha_seen_at`` (Migration 0028). Weder die Umgebung
noch das Skript koennen sagen, **seit wann** der Pin steht:
``deploy-pull.sh`` laeuft alle fuenf Minuten und muesste den Zustand in
eine Datei legen, die der naechste ``git reset --hard`` entfernt; Redis hat
in diesem Stack kein Volume und verliert bei jedem Neustart alles — eine
Sieben-Tage-Uhr waere dort der stille Ausfall aus §5.76.

**Die Uhr startet bei einem Pin-Wechsel nicht neu.** Gemessen wird "der
Server folgt dem Branch nicht", und das haelt an, wenn der Pin von einem
Commit zum naechsten wandert. Sonst koennte man die Erinnerung beliebig
hinausschieben, indem man neu pinnt.

Die erste Mail kommt von dieser Uhr, der Rhythmus danach von
``alert_throttle`` (TTL sieben Tage). Zwei Mechanismen, weil sie zwei
verschiedene Fragen beantworten: "ist es lange genug her" und "habe ich
schon erinnert".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from heizung.config import get_settings
from heizung.models.global_config import GlobalConfig
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.services import alert_throttle, mail_status, mailer

logger = logging.getLogger(__name__)

# Nicht konfigurierbar, wie die TTLs in ``alert_throttle``: das ist keine
# Betriebspraeferenz, sondern die Antwort auf "ab wann ist ein Pin
# vergessen statt gesetzt". Eine Woche ist lange genug, dass niemand
# waehrend eines laufenden Fixes behelligt wird, und kurz genug, dass der
# Sprung beim Loesen ueberschaubar bleibt.
REMINDER_AFTER_DAYS = 7


def _lokales_datum(at: datetime, tz_name: str) -> str:
    """``"01.10.2026"`` — Kalendertag in Hotel-Ortszeit.

    Ein reines Datum, bewusst **ohne** Uhrzeit: die Mail vergleicht es mit
    keiner Schwelle, und eine Uhrzeit haette hier ein Zeitzonen-Kuerzel
    gebraucht (§5.79), ohne etwas zu erklaeren.
    """
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - unbekannte Zone darf nichts kippen
        tz = ZoneInfo(DEFAULT_HOTEL_TIMEZONE)
    return at.astimezone(tz).strftime("%d.%m.%Y")


def _body(*, pin: str, tage: int, seit: str) -> str:
    return "\n".join(
        [
            f"Der Server läuft seit {tage} Tagen auf einem festgesetzten Stand",
            f"(seit {seit}, Commit {pin}).",
            "",
            "Was das heißt: Der Server zieht keine Merges mehr. Alles, was seither",
            "entwickelt wurde, ist nicht auf dem Server — auch Korrekturen nicht.",
            "Die Heizung regelt unverändert weiter, mit dem Code von damals.",
            "",
            "Das ist kein Fehler. Ein festgesetzter Stand ist eine Entscheidung,",
            "und solange der Grund besteht, ist sie richtig. Je länger er steht,",
            "desto größer wird allerdings der Sprung, den der Server beim Lösen",
            "macht — und desto weniger weiß man, ob der Sprung funktioniert.",
            "",
            "Wenn der Grund erledigt ist: RUNBOOK §10u, Schritt 6 (Pin leeren,",
            "Deploy anstoßen, prüfen). Ein Handgriff, drei Minuten.",
            "",
            "Diese Erinnerung wiederholt sich wöchentlich, solange der Pin steht.",
        ]
    )


async def run_pin_reminder(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Prueft den Pin-Zustand, pflegt die Uhr und erinnert faellig.

    Committet **nicht** — der Aufrufer besitzt die Transaktion (§5.61).

    :returns: Bericht fuer das Log. ``aktion`` ist einer von
        ``kein_pin`` · ``uhr_gestartet`` · ``laeuft`` · ``erinnert`` ·
        ``gebremst`` · ``kein_empfaenger`` · ``keine_config``.
    """
    jetzt = now or datetime.now(tz=UTC)
    pin = get_settings().pin_sha

    gc = await session.get(GlobalConfig, 1)
    if gc is None:
        # Kein Seed — kein Empfaenger und keine Ablage. Nur melden; diese
        # Datei legt die Singleton-Row nicht an (wie ``mail_status``).
        logger.warning("pin_reminder: keine global_config-Row, nichts zu tun")
        return {"aktion": "keine_config", "pin": pin}

    if pin is None:
        if gc.pin_sha_seen is not None or gc.pin_sha_seen_at is not None:
            # Pin geloest: Uhr loeschen und die Bremse freigeben, damit die
            # naechste Pin-Periode nicht an einem alten Schluessel haengt.
            logger.info("pin_reminder: Pin geloest (war %s), Uhr zurueckgesetzt", gc.pin_sha_seen)
            gc.pin_sha_seen = None
            gc.pin_sha_seen_at = None
            alert_throttle.reset(alert_throttle.KIND_PIN_ACTIVE, alert_throttle.SUBJECT_PIN_ACTIVE)
        return {"aktion": "kein_pin", "pin": None}

    if gc.pin_sha_seen_at is None:
        # Erster Lauf mit diesem Pin-Zustand: Uhr starten, nicht erinnern.
        gc.pin_sha_seen = pin
        gc.pin_sha_seen_at = jetzt
        logger.info("pin_reminder: Pin %s erstmals gesehen, Uhr gestartet", pin)
        return {"aktion": "uhr_gestartet", "pin": pin, "seit": jetzt.isoformat()}

    if gc.pin_sha_seen != pin:
        # Pin gewandert. SHA nachziehen, Uhr NICHT — gemessen wird der
        # Zustand, nicht der einzelne Commit (siehe Modul-Docstring).
        logger.info("pin_reminder: Pin %s -> %s, Uhr laeuft weiter", gc.pin_sha_seen, pin)
        gc.pin_sha_seen = pin

    alter = jetzt - gc.pin_sha_seen_at
    if alter < timedelta(days=REMINDER_AFTER_DAYS):
        return {
            "aktion": "laeuft",
            "pin": pin,
            "tage": alter.days,
            "faellig_ab_tagen": REMINDER_AFTER_DAYS,
        }

    if not alert_throttle.should_send(
        alert_throttle.KIND_PIN_ACTIVE,
        alert_throttle.SUBJECT_PIN_ACTIVE,
        ttl_s=alert_throttle.TTL_PIN_ACTIVE_S,
    ):
        return {"aktion": "gebremst", "pin": pin, "tage": alter.days}

    if not gc.alert_email:
        # Die Bremse ist schon gesetzt (``should_send`` setzt beim Fragen).
        # Das verschiebt die naechste Gelegenheit um eine Woche — richtig
        # so: ohne Empfaenger aendert ein Versuch je Stunde nichts, ausser
        # das Log zu fuellen.
        logger.warning("pin_reminder: Pin %s seit %d Tagen, aber kein alert_email", pin, alter.days)
        return {"aktion": "kein_empfaenger", "pin": pin, "tage": alter.days}

    result = mailer.send_mail(
        recipient=gc.alert_email,
        subject=f"Heizung: Stand festgesetzt seit {alter.days} Tagen",
        body=_body(
            pin=pin,
            tage=alter.days,
            seit=_lokales_datum(gc.pin_sha_seen_at, gc.timezone),
        ),
    )
    # Pflicht fuer jeden Alarmweg (§5.76, Docstring von ``mail_status``):
    # ohne diese Zeile waere der neue Weg unbeobachtet.
    await mail_status.record_attempt(session, result)
    logger.info("pin_reminder: erinnert, pin=%s tage=%d sent=%s", pin, alter.days, result.sent)
    return {"aktion": "erinnert", "pin": pin, "tage": alter.days, "sent": result.sent}
