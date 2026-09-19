"""Wiederholungsbremse fuer Alarm-Mails (Sprint 18, B-15b-1).

Ein Dauerfehler darf kein Postfach fluten. Zwei Faelle, die ohne Bremse
genau das taeten:

- **Flatternder Gesundheitszustand.** ``health_tasks`` alarmiert zwar nur
  bei der Flanke ``vorher != silent -> jetzt == silent``. Ein Vicki am Rand
  der 24-Stunden-Grenze pendelt aber zwischen ``degraded`` und ``silent``
  und erzeugt bei jedem Wechsel eine neue Flanke — im 5-Minuten-Takt.
- **Ausbleibende Belegungsliste.** Der AE-66-Watchdog ist pro Kalendertag
  idempotent, aber ueber ein langes Wochenende kaeme trotzdem jeden Tag
  eine Mail zum selben, unveraenderten Zustand.

Mechanik
--------

Ein Redis-Schluessel pro Alarm-Gegenstand mit Ablaufzeit. Wer versenden
will, fragt ``should_send`` — beim ersten Mal ``True``, danach bis zum
Ablauf ``False``. Der Schluessel wird **beim Fragen** gesetzt, nicht nach
erfolgreichem Versand: sonst wuerde ein SMTP-Fehler die Bremse offen
lassen und beim naechsten Tick erneut zustellen wollen.

Muster und Fehlerverhalten sind an ``services/resync_flag.py`` (AE-63)
angelehnt — mit **einem bewussten Unterschied**: faellt Redis aus, gibt
``resync_flag.consume`` defensiv ``False`` zurueck (lieber kein Downlink
als ein unbegruendeter). Hier ist es umgekehrt: bei Redis-Ausfall gibt
``should_send`` ``True`` zurueck. Eine verpasste Alarm-Mail ist teurer als
eine doppelte, und der Ausfall der Bremse darf den Alarm nicht mit
abschalten.

Ablaufzeiten
------------

Nicht konfigurierbar, und das mit Absicht: es sind keine Betriebs-
praeferenzen, sondern die Antwort auf die Frage "wie oft will ich an
dasselbe Problem erinnert werden". Sechs Stunden bei Geraeten — haeufig
genug, dass ein echter Ausfall nicht untergeht, selten genug, dass ein
flatterndes Geraet hoechstens vier Mails am Tag erzeugt. 20 Stunden beim
Import: knapp unter einem Tag, damit die taegliche Erinnerung erhalten
bleibt, aber ein zweiter Watchdog-Lauf am selben Tag nicht nachlegt.
"""

from __future__ import annotations

import logging

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

KEY_TEMPLATE = "alert_sent:{kind}:{subject}"

# Geraet stumm: alle 6 Stunden hoechstens eine Mail je Geraet.
TTL_DEVICE_SILENT_S = 6 * 3600
# Belegungsliste ausgeblieben: knapp unter einem Tag.
TTL_IMPORT_STALE_S = 20 * 3600

KIND_DEVICE_SILENT = "device_silent"
KIND_IMPORT_STALE = "import_stale"


def _key(kind: str, subject: str) -> str:
    return KEY_TEMPLATE.format(kind=kind, subject=subject.lower())


def should_send(kind: str, subject: str, *, ttl_s: int) -> bool:
    """Darf fuer diesen Gegenstand jetzt eine Mail raus?

    Setzt den Schluessel im selben Schritt, in dem er geprueft wird —
    ``SET NX`` ist atomar, zwei parallele Beat-Ticks koennen sich also
    nicht gegenseitig ueberholen.

    :param kind: Alarm-Gattung, z. B. ``KIND_DEVICE_SILENT``.
    :param subject: Gegenstand innerhalb der Gattung — die DevEUI beim
        Geraet, das Listendatum beim Import.
    :param ttl_s: Sperrzeit in Sekunden.
    :return: ``True`` beim ersten Mal und nach Ablauf, sonst ``False``.
        Bei Redis-Ausfall ``True`` — siehe Modul-Kopf.
    """
    try:
        # nx=True: setzt nur, wenn der Schluessel noch nicht existiert.
        # Rueckgabe ist True bei Erfolg, None wenn schon vorhanden.
        acquired = redis_client.get_redis_client().set(_key(kind, subject), "1", ex=ttl_s, nx=True)
        return bool(acquired)
    except redis.RedisError:
        logger.warning(
            "alert_throttle.should_send: Redis nicht erreichbar fuer %s/%s — "
            "Alarm wird zugestellt (lieber doppelt als gar nicht)",
            kind,
            subject,
            exc_info=True,
        )
        return True


def reset(kind: str, subject: str) -> None:
    """Loescht die Sperre. Fuer Tests und den Test-Versand-Befehl.

    Im Betrieb nicht noetig — die Ablaufzeit raeumt selbst auf.
    """
    try:
        redis_client.get_redis_client().delete(_key(kind, subject))
    except redis.RedisError:
        logger.warning("alert_throttle.reset: Redis-Fehler", exc_info=True)
