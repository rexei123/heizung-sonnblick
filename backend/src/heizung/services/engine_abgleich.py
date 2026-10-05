"""Drosselung und Zaehler fuer den Engine-Abgleich (Sprint 20f, T3).

**Der Befund.** Die Hysterese vergleicht den neuen Sollwert mit dem
**letzten selbst gesendeten**, nicht mit dem, den das Geraet meldet
(``rules/engine.py:795-827``). Hat die Engine zuletzt 18 geschickt und will
wieder 18, ist ``delta = 0`` und sie schweigt — unabhaengig davon, was am
Geraet steht. Die Geraete **048** und **057** standen deshalb nach einer
Montage-Drehung auf 20 °C, waehrend der Engine-Soll 18 °C war und kein
Override existierte. Korrigiert wurde per Hand ueber die Queue.

Die Engine kannte also ihren eigenen Willen, aber nicht den Zustand des
Geraets. Der Abgleich schliesst das: weicht der **gemeldete** Sollwert vom
Engine-Soll ab und es gibt keinen aktiven Override, wird erneut gesendet.

**Warum das eine Drosselung braucht, und zwar zwingend.** Jeder Downlink
ist eine Motorbewegung und kostet Batterie (§0 S4). Ein Geraet an der
Funkgrenze bestaetigt womoeglich nie — ohne Grenze wuerde die Engine es
dann bei **jedem** Tick anfunken, also jede Minute, bis die Batterie leer
ist. Genau dieses Verhalten waere der teure Weg, einen Befund zu beheben.

Zwei Grenzen, beide hier:

1. **Hoechstens eine Nachsendung je Geraet je 30 Minuten.** Ein ``SET NX``
   mit TTL, dieselbe Mechanik wie ``alert_throttle``.
2. **Nach drei erfolglosen Versuchen Schluss.** Ein Zaehler, der steigt,
   solange das Geraet den Wert nicht uebernimmt, und der **geloescht** wird,
   sobald es ihn meldet. Beim dritten Mal gibt es einen Audit-Eintrag und
   eine Warnung statt eines vierten Downlinks.

Daraus folgt der schlechteste Fall, den die Akzeptanzkriterien nennen: eine
Handverstellung in einem unbelegten Zimmer steht nach **spaetestens 45 min**
wieder auf dem Engine-Soll — 30 min Drosselung plus eine Keepalive-Periode,
bis das Geraet den neuen Wert meldet.

**Verhalten bei Redis-Ausfall: nicht senden.** Das ist die Gegenrichtung zu
``alert_throttle``, wo ein Ausfall zu "lieber doppelt zustellen" fuehrt. Eine
Mail doppelt zu schicken kostet Aufmerksamkeit; einen Downlink ohne
funktionierende Drosselung zu schicken kostet Batterie und Motorbewegungen,
und zwar bei jedem Tick. Wo die Grenze nicht nachweisbar steht, wird nicht
gesendet (§0 S4, S6). Der Abgleich ist eine Nachbesserung, kein
Sicherheitsmelder — er darf warten.

Mechanik analog zu ``engine_lock`` (AE-40) und ``resync_flag`` (AE-63):
synchroner Redis-Client, fork-safe Pool, eigene Connection pro Aufruf. Die
Aufrufer im Worker legen ihn per ``asyncio.to_thread`` daneben, damit der
Event-Loop nicht blockiert.
"""

from __future__ import annotations

import logging
from typing import cast

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

# Sperrzeit je Geraet. 30 Minuten: lang genug, dass drei Versuche sich ueber
# eineinhalb Stunden verteilen und nicht in einer Minute verbrennen, kurz
# genug, dass eine Abweichung nicht einen halben Tag stehen bleibt.
DROSSEL_TTL_S = 1800

# Nach so vielen erfolglosen Versuchen wird nicht mehr gesendet.
MAX_VERSUCHE = 3

# Der Zaehler haelt deutlich laenger als die Drosselung, sonst beginnt die
# Zaehlung bei jedem Versuch von neuem und die Grenze greift nie. Vier
# Stunden deckt drei Versuche im 30-Minuten-Abstand mit Reserve.
ZAEHLER_TTL_S = 14400

_DROSSEL = "engine:abgleich:drossel:{dev_eui}"
_ZAEHLER = "engine:abgleich:versuche:{dev_eui}"


def _drossel_key(dev_eui: str) -> str:
    return _DROSSEL.format(dev_eui=dev_eui.lower())


def _zaehler_key(dev_eui: str) -> str:
    return _ZAEHLER.format(dev_eui=dev_eui.lower())


def versuche(dev_eui: str) -> int:
    """Wie viele erfolglose Nachsendungen stehen fuer dieses Geraet?

    ``0`` auch bei Redis-Ausfall — die Entscheidung, ob ueberhaupt gesendet
    wird, trifft ``darf_senden``, und die sagt dann Nein.
    """
    try:
        rohwert = redis_client.get_redis_client().get(_zaehler_key(dev_eui))
    except redis.RedisError:
        logger.warning(
            "engine_abgleich.versuche: Redis nicht erreichbar fuer %s",
            dev_eui,
            exc_info=True,
        )
        return 0
    if rohwert is None:
        return 0
    try:
        return int(cast("int | str", rohwert))
    except (TypeError, ValueError):
        return 0


def darf_senden(dev_eui: str) -> bool:
    """Darf fuer dieses Geraet **jetzt** eine Nachsendung raus?

    Prueft und setzt die Sperre in einem Schritt (``SET NX``), damit zwei
    gleichzeitige Ticks sich nicht ueberholen. Prueft **vorher** den Zaehler:
    ist die Grenze erreicht, wird die Sperre gar nicht gesetzt — sonst
    verschiebte ein Aufruf, der ohnehin nicht senden darf, das Zeitfenster
    des naechsten.

    :return: ``True`` genau dann, wenn gesendet werden darf. Bei
        Redis-Ausfall ``False`` (siehe Modul-Kopf).
    """
    if versuche(dev_eui) >= MAX_VERSUCHE:
        return False
    try:
        gesetzt = redis_client.get_redis_client().set(
            _drossel_key(dev_eui), "1", ex=DROSSEL_TTL_S, nx=True
        )
        return bool(gesetzt)
    except redis.RedisError:
        logger.warning(
            "engine_abgleich.darf_senden: Redis nicht erreichbar fuer %s — "
            "es wird NICHT gesendet (ohne Drosselung kostet ein Abgleich "
            "Batterie bei jedem Tick)",
            dev_eui,
            exc_info=True,
        )
        return False


def versuch_gezaehlt(dev_eui: str) -> int:
    """Zaehlt eine Nachsendung und gibt den neuen Stand zurueck.

    Wird **nach** dem Senden gerufen. Der Zaehler ist absichtlich nicht an
    den Erfolg des Downlinks gebunden, sondern an das Ausbleiben der
    Wirkung: geloescht wird er erst, wenn das Geraet den Wert meldet
    (``erfolg_gemeldet``). Ein Downlink, der im Gateway verschwindet, zaehlt
    damit mit — und das ist richtig, denn er hat nichts bewirkt (§5.76).
    """
    try:
        client = redis_client.get_redis_client()
        stand = int(cast("int", client.incr(_zaehler_key(dev_eui))))
        # TTL nur beim ersten Hochzaehlen setzen, sonst verschiebt sich das
        # Fenster mit jedem Versuch nach hinten und laeuft nie ab.
        if stand == 1:
            client.expire(_zaehler_key(dev_eui), ZAEHLER_TTL_S)
        return stand
    except redis.RedisError:
        logger.warning(
            "engine_abgleich.versuch_gezaehlt: Redis nicht erreichbar fuer %s",
            dev_eui,
            exc_info=True,
        )
        return 0


def erfolg_gemeldet(dev_eui: str) -> None:
    """Loescht den Zaehler — das Geraet steht auf dem Engine-Soll.

    Wird bei jedem Tick fuer jedes uebereinstimmende Geraet gerufen, nicht
    nur nach einer Nachsendung. Das ist der Aufraeum-Pfad: ein Geraet, das
    aus eigener Kraft wieder zusammenpasst (etwa weil ein verzoegerter
    Downlink doch angekommen ist), beginnt beim naechsten Mal wieder bei
    null statt mit verbrauchten Versuchen.

    Die Drosselung bleibt stehen. Sie laeuft von selbst ab, und ein Geraet,
    das gerade zusammenpasst, braucht ohnehin keine Nachsendung.
    """
    try:
        redis_client.get_redis_client().delete(_zaehler_key(dev_eui))
    except redis.RedisError:
        logger.warning(
            "engine_abgleich.erfolg_gemeldet: Redis nicht erreichbar fuer %s",
            dev_eui,
            exc_info=True,
        )
