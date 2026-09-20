"""Sichtbarkeit des Mailversands (Sprint 18, T4).

Ab Sprint 18 verschickt das System Alarme. Ohne diese Datei taete es das
**still**: solange die SMTP-Werte in der ``.env`` leer sind, meldet
``mailer.send_mail`` brav ``sent=False, reason="smtp_deaktiviert"`` — und
niemand sieht es, weil die Meldung im Container-Log endet.

Das ist genau das Fehlerbild aus CLAUDE.md §5.76: ein Weg, dessen Ausfall
nur bemerkt, wer zufaellig hinsieht. Ein Alarmweg, der so ausfaellt, ist
schlimmer als keiner — er erzeugt die Annahme, man wuerde gewarnt.

Drei Felder auf der ``global_config``-Singleton beantworten die drei
Fragen, die man am Tag der Inbetriebnahme hat:

===========================  ==========================================
``last_mail_attempt_at``     Wird ueberhaupt versucht?
``last_mail_ok_at``          Hat es jemals geklappt?
``last_mail_error``          Woran haengt es gerade?
===========================  ==========================================

Warum das Schreiben hier liegt und nicht in ``mailer``
------------------------------------------------------

``mailer.send_mail`` ist synchron (die Konsumenten sind Celery-Tasks,
dort ist blockierendes I/O richtig). Ein DB-Schreibvorgang waere hier
async — und ``asyncio.run`` innerhalb eines bereits laufenden Loops
wirft. ``health_tasks`` ruft den Versand aus genau so einem Kontext.

Die Trennung ist aber auch inhaltlich richtig: der Versand soll nichts
schreiben, und das Protokoll soll nichts versenden. Dasselbe Prinzip wie
bei ``alert_throttle`` neben ``mailer``.

**Pflicht fuer neue Alarmwege:** Wer ``mailer.send_mail`` aufruft, ruft
danach ``record_attempt``. Sonst ist der neue Weg unbeobachtet — und der
naechste, der nachsieht, warum keine Mail kam, sieht den Zustand eines
*anderen* Alarms.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.global_config import GlobalConfig
from heizung.services.mailer import MailResult

logger = logging.getLogger(__name__)

# ``global_config.last_mail_error`` ist VARCHAR(200). Der Wert kommt aus
# ``MailResult.detail``, das seinerseits aus einem auf 200 Zeichen
# gekuerzten Ausnahmetext stammt — zusammen mit dem Typ-Praefix kann er
# darueber liegen. Hier wird hart geschnitten, damit ein langer
# Server-Fehlertext nicht die ganze Aufzeichnung kippt.
MAX_ERROR_LEN = 200


async def record_attempt(
    session: AsyncSession, result: MailResult, *, now: datetime | None = None
) -> None:
    """Haelt das Ergebnis eines Versandversuchs auf der Singleton-Row fest.

    Committet **nicht** — der Aufrufer besitzt die Transaktion (Repo-
    Konvention, siehe CLAUDE.md §5.61).

    Wirft nicht. Ein Fehler beim Protokollieren darf den Alarmpfad nicht
    abbrechen; das Protokoll ist die Beobachtung, nicht die Aufgabe.

    :param session: offene Session. Der Aufrufer committet.
    :param result: Rueckgabe von ``mailer.send_mail``.
    :param now: Zeitstempel, ueberschreibbar fuer Tests.
    """
    zeitpunkt = now or datetime.now(tz=UTC)

    try:
        gc = await session.get(GlobalConfig, 1)
        if gc is None:
            # Kein Seed — kein Empfaenger, also auch kein sinnvoller Versand.
            # Nur melden, nicht anlegen: diese Datei ist nicht fuer das
            # Erzeugen der Singleton zustaendig.
            logger.warning("mail_status_ohne_global_config")
            return

        gc.last_mail_attempt_at = zeitpunkt
        if result.sent:
            gc.last_mail_ok_at = zeitpunkt
            gc.last_mail_error = None
        else:
            gc.last_mail_error = _fehlertext(result)
        await session.flush()
    except Exception:  # noqa: BLE001 — siehe Docstring: nie werfen
        logger.warning("mail_status_schreiben_fehlgeschlagen", exc_info=True)


def _fehlertext(result: MailResult) -> str:
    """Kurzgrund und Klartext, auf die Spaltenbreite gekuerzt.

    Der Kurzgrund steht vorn, damit er beim Abschneiden ueberlebt — er ist
    der Teil, mit dem man in der Doku nachschlagen kann.
    """
    grund = result.reason or "unbekannt"
    text = f"{grund}: {result.detail}" if result.detail else grund
    return text[:MAX_ERROR_LEN]
