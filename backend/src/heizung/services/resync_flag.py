"""Redis-Flag fuer prompten Re-Sync nach Vicki-Reboot (Sprint 15c, AE-63).

Vicki startet nach Reboot (Batteriewechsel, Power-Cycle) den LoRaWAN-
Frame-Counter neu bei 0 und faehrt mit dem letzten internen Setpoint hoch
— der kann mehrere Grad vom Engine-Sollwert gedriftet sein. Der Auto-
Detect-Override-Pfad (``device_adapter.handle_uplink_for_override``,
AE-45) wuerde diesen gedrifteten Setpoint als source=DEVICE-Override
adoptieren (M1 — Raum heizt bis zu 7 Tage nicht nach).

Der Reboot-Gate in ``device_adapter.handle_uplink_for_override`` setzt
stattdessen diesen Redis-Key, der im naechsten Engine-Tick im
``engine_tasks._dispatch_downlinks_per_zone``-Loop konsumiert wird —
genau EIN Downlink wird mit Hysterese-Bypass forciert (Re-Sync auf
Engine-Soll), danach loescht der Konsument den Key (consume-once).

TTL 1 h als Sicherheitsnetz: wenn der Vicki nach Reboot offline bleibt
oder der Engine-Tick aus anderem Grund nicht laeuft, raeumt Redis den
Key selber auf — keine Dauer-Bypaesse.

Mechanik analog zu ``engine_lock`` (Sprint 9.10 T3.5, AE-40): synchroner
Redis-Client, fork-safe Pool, eigene Connection pro Call.
"""

from __future__ import annotations

import logging

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

RESYNC_KEY_TEMPLATE = "resync_pending:{dev_eui}"
RESYNC_TTL_S = 3600


def _key(dev_eui: str) -> str:
    return RESYNC_KEY_TEMPLATE.format(dev_eui=dev_eui.lower())


def mark_pending(dev_eui: str, *, ttl_s: int = RESYNC_TTL_S) -> bool:
    """Setzt ``resync_pending:{dev_eui}`` mit TTL. True bei Erfolg.

    Falls Redis nicht erreichbar: Logger-Warning, return False. Aufrufer
    kann auswerten ob das Flag wirklich gesetzt wurde — bei False bleibt
    der Re-Sync auf den naechsten 60-s-Beat-Tick angewiesen.
    """
    try:
        redis_client.get_redis_client().set(_key(dev_eui), "1", ex=ttl_s)
        return True
    except redis.RedisError:
        logger.warning(
            "resync_flag.mark_pending: redis-fehler fuer dev_eui=%s",
            dev_eui,
            exc_info=True,
        )
        return False


def consume(dev_eui: str) -> bool:
    """Atomarer Check+Delete: True wenn Flag gesetzt war (und jetzt geloescht).

    Nutzt ``GETDEL`` (Redis 6.2+). Atomar — kein Race zwischen GET und DEL,
    auch nicht bei zwei parallelen ``_dispatch_downlinks_per_zone`` (z.B.
    bei zwei Vickis derselben Zone in derselben Eval).

    Bei Redis-Fehler: Logger-Warning, return False (defensive — kein
    forcierter Downlink ohne Beleg, dass das Flag wirklich gesetzt war).
    """
    try:
        result = redis_client.get_redis_client().getdel(_key(dev_eui))
        return result is not None
    except redis.RedisError:
        logger.warning(
            "resync_flag.consume: redis-fehler fuer dev_eui=%s",
            dev_eui,
            exc_info=True,
        )
        return False
