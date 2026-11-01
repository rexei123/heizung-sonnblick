"""Laeuft gerade eine Provisionierung an diesem Relais? (01.11.2026)

**Der Anlass ist ein abgebrochener Handgriff.** Die Provisionierung
schickt fuenf Downlinks mit je 15 Sekunden Pause — das sind rund 75
Sekunden. Solange sie im HTTP-Request lief, brach die Oberflaeche nach
etwa 30 Sekunden ab (``signal is aborted without reason``). Das Backend
lief weiter und hat alles gesendet; die Antwort auf ``0x5A`` kam um
10:28:28 und beide Ruecklesungen stehen seither auf bestaetigt. **Der
Handgriff war also erfolgreich und sah wie ein Fehlschlag aus** — die
teuerste Sorte Rueckmeldung, weil der naechste Schritt dann ein zweiter
Versuch ist.

Seither sendet ein Hintergrund-Auftrag, und der Request kehrt sofort
zurueck. Diese Markierung ist das Band zwischen beiden: der Endpunkt
setzt sie, der Auftrag loescht sie, und die Geraeteseite liest sie, um
„laeuft" zu zeigen.

**Sie ist zugleich ein Tor** (S2). Zwei Provisionierungen gleichzeitig
waeren zehn Downlinks ohne Pause — genau der Zustand, gegen den die Pause
gebaut ist. ``starte`` setzt deshalb mit ``SET NX``: der zweite Aufruf
bekommt ``False`` und der Endpunkt daraus ein 409.

**Bei Redis-Ausfall wird gesendet, nicht gesperrt.** Das ist die
Gegenrichtung zu ``engine_abgleich``, und sie hat denselben Grund:
dort verhindert die Drosselung Batterieverbrauch, hier ist die Markierung
nur ein Hinweis und ein Schutz gegen Doppelklick. Ein Relais, das wegen
eines Redis-Ausfalls nicht provisioniert werden kann, blockiert die
Inbetriebnahme — und die ist der Weg, auf dem ein Panel ueberhaupt erst
sicher schalten darf.

Mechanik wie ``engine_lock`` (AE-40) und ``resync_flag`` (AE-63):
synchroner Redis-Client, eigene Verbindung je Aufruf, im Worker per
``asyncio.to_thread`` daneben.
"""

from __future__ import annotations

import logging

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

#: Lebensdauer der Markierung. Fuenf Downlinks mit vier Pausen von je 15
#: Sekunden sind rund 75 Sekunden; 180 geben Luft fuer einen langsamen
#: Broker und sorgen dafuer, dass ein abgestuerzter Auftrag die Markierung
#: nicht fuer immer stehen laesst. Ein Relais ist nach drei Minuten also in
#: jedem Fall wieder bedienbar, auch wenn niemand aufgeraeumt hat.
LAUF_TTL_S = 180

_SCHLUESSEL = "relais:provisionierung:{device_id}"


def _key(device_id: int) -> str:
    return _SCHLUESSEL.format(device_id=device_id)


def starte(device_id: int) -> bool:
    """Markiert einen Lauf — und sagt, ob er starten darf.

    Prueft und setzt in einem Schritt (``SET NX``), damit zwei
    gleichzeitige Klicks sich nicht ueberholen.

    :return: ``True``, wenn dieser Aufruf den Lauf eroeffnet hat.
        ``False``, wenn schon einer laeuft. Bei Redis-Ausfall ``True``
        (siehe Modul-Kopf: die Markierung ist Hinweis und Doppelklick-
        Schutz, kein Sicherheitstor).
    """
    try:
        gesetzt = redis_client.get_redis_client().set(_key(device_id), "1", ex=LAUF_TTL_S, nx=True)
        return bool(gesetzt)
    except redis.RedisError:
        logger.warning(
            "provision_lauf.starte: Redis nicht erreichbar fuer device_id=%s — "
            "es wird trotzdem provisioniert (die Markierung ist kein Tor)",
            device_id,
            exc_info=True,
        )
        return True


def laeuft(device_id: int) -> bool:
    """Ob fuer dieses Geraet gerade ein Lauf markiert ist.

    Bei Redis-Ausfall ``False``: die Oberflaeche zeigt dann kein „laeuft",
    und das ist besser als ein „laeuft", das nie endet.
    """
    try:
        return redis_client.get_redis_client().exists(_key(device_id)) == 1
    except redis.RedisError:
        logger.warning(
            "provision_lauf.laeuft: Redis nicht erreichbar fuer device_id=%s",
            device_id,
            exc_info=True,
        )
        return False


def beende(device_id: int) -> None:
    """Loescht die Markierung. Gehoert in ein ``finally``.

    Bleibt sie stehen, laeuft sie nach ``LAUF_TTL_S`` von selbst ab — das
    ist der Grund fuer die TTL und nicht nur Hygiene.
    """
    try:
        redis_client.get_redis_client().delete(_key(device_id))
    except redis.RedisError:
        logger.warning(
            "provision_lauf.beende: Redis nicht erreichbar fuer device_id=%s — "
            "die Markierung laeuft nach %s s von selbst ab",
            device_id,
            LAUF_TTL_S,
            exc_info=True,
        )
