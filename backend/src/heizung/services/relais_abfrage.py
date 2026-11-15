"""Drosselung der Zustandsabfrage ``0xB1`` (14.11.2026).

**Warum es diese Bremse braucht.** Seit dem 14.11. fragt der Waechter
nach dem Zustand, wenn er ihn nicht kennt oder ihm nicht mehr glaubt —
auch dann, wenn AUS gewuenscht ist. Ein Relais, das dauerhaft schweigt
(ausgesteckt, defekt, ausser Funkreichweite), wuerde damit in **jedem**
Durchlauf gefragt, also jede Minute.

Was das kostet: bei DR1 und einem Byte Nutzlast sind das rund 0,66
Sekunden Sendezeit je Downlink, also etwa **16 Minuten je Tag** fuer ein
einziges stummes Geraet. Das ist mehr als ein Prozent der Zeit und damit
jenseits der Grenze, die das Gateway auf den meisten Baendern einhalten
muss. Es waere derselbe Fehler wie die feste Frist von 60 Sekunden, die
am 01.11. sieben Downlinks in sieben Minuten erzeugt hat (§_frist im
Waechter) — nur mit einem Lese- statt einem Schaltbefehl.

**Der Abstand ist das Veraltungs-Fenster selbst** (Vorgabe 25 min). Mehr
waere eine zweite Zahl ohne eigene Begruendung; weniger kann nichts
bringen, weil das Geraet von sich aus alle zehn Minuten meldet und eine
Antwort innerhalb des Fensters den Zustand ohnehin wieder frisch macht.
Ein stummes Relais kostet damit rund 57 Lese-Downlinks am Tag statt
1440.

**Bei Redis-Ausfall wird nicht gefragt.** Das ist die Gegenrichtung zu
``provision_lauf``, und der Grund ist die Richtung des Schadens: eine
unterbliebene Abfrage haelt ein Relais aus (kalter Raum), eine
ungedrosselte Abfrage verbrennt die Funkzeit des ganzen Hauses. Praktisch
ist die Entscheidung ohnehin eher Form als Wirkung — Redis ist der Broker
dieses Tasks, ohne Redis laeuft der Durchlauf gar nicht.

Mechanik wie ``engine_lock`` (AE-40), ``resync_flag`` (AE-63) und
``provision_lauf``: synchroner Redis-Client, eigene Verbindung je Aufruf,
im Worker per ``asyncio.to_thread`` daneben.
"""

from __future__ import annotations

import logging

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

_SCHLUESSEL = "relais:zustandsabfrage:{device_id}"


def _key(device_id: int) -> str:
    return _SCHLUESSEL.format(device_id=device_id)


def darf_fragen(device_id: int, *, abstand_s: int) -> bool:
    """Prueft und merkt in einem Schritt, ob jetzt gefragt werden darf.

    ``SET NX`` mit Ablauf: der erste Aufruf im Fenster bekommt ``True``
    und setzt die Marke, jeder weitere bekommt ``False``, bis sie
    ablaeuft. Pruefen und Merken getrennt zu machen waere eine Luecke
    zwischen zwei Durchlaeufen (S2) — und zwei Worker-Forks greifen auf
    denselben Schluessel zu.

    ``abstand_s`` ist Pflicht-Argument (§5.73): ein Default waere eine
    zweite Wahrheit neben dem Veraltungs-Fenster und liefe beim ersten
    Nachjustieren stumm auseinander.

    :return: ``True``, wenn gefragt werden darf. ``False``, wenn im
        Fenster schon gefragt wurde — oder wenn Redis nicht erreichbar
        ist (siehe Modul-Kopf).
    """
    if abstand_s < 1:
        # Kein Fenster heisst keine Drosselung. Das waere genau der
        # Zustand, gegen den dieses Modul gebaut ist, also lieber ein
        # lautes Nein als eine stille Schleuse.
        logger.error(
            "relais_abfrage.darf_fragen: abstand_s=%s ist kein Fenster — es wird nicht gefragt",
            abstand_s,
        )
        return False
    try:
        gesetzt = redis_client.get_redis_client().set(_key(device_id), "1", ex=abstand_s, nx=True)
        return bool(gesetzt)
    except redis.RedisError:
        logger.warning(
            "relais_abfrage.darf_fragen: Redis nicht erreichbar fuer device_id=%s — "
            "es wird nicht gefragt (die Drosselung ist ein Tor)",
            device_id,
            exc_info=True,
        )
        return False
