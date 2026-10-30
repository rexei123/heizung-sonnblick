"""Redis-Flag fuer prompten Re-Sync eines Geraets (Sprint 15c, AE-63).

Ein Schluessel je Geraet. Steht er, erzwingt der naechste Engine-Lauf im
``engine_tasks._dispatch_downlinks_per_zone``-Loop **genau einen** Downlink
mit dem Engine-Sollwert und uebergeht dafuer die Hysterese; danach loescht
der Konsument den Schluessel (consume-once).

Gebraucht wird das immer dann, wenn das Geraet von seinem Sollwert
abgewichen ist, **ohne** dass sich der Wille der Engine geaendert hat. Die
Hysterese vergleicht gegen den **zuletzt selbst gesendeten** Wert, findet
``delta = 0`` und schweigt — der Abweichung zum Trotz.

TTL 1 h als Sicherheitsnetz: bleibt das Geraet offline oder laeuft der
Engine-Tick aus anderem Grund nicht, raeumt Redis den Schluessel selber
auf — keine Dauer-Bypaesse.

Mechanik analog zu ``engine_lock`` (Sprint 9.10 T3.5, AE-40): synchroner
Redis-Client, fork-safe Pool, eigene Connection pro Call.

## Der Schluessel traegt seinen Grund (Sprint 23 T4-A2b)

Bis zum 30.10.2026 stand im Wert ``"1"``, und es gab genau einen Grund:
den Geraete-Neustart. Inzwischen sind es drei, und sie werden **nicht**
gleich protokolliert:

| Grund | Anlass | ``control_command.reason`` |
|---|---|---|
| ``reboot`` | fcnt-Reset, gedrifteter Sollwert (AE-63) | ``reboot_resync`` |
| ``sperre`` | Drehung bei Gast-Sperre abgewiesen (T4-A2b) | der Grund des Laufs |
| ``probe`` | Sollwert-Probe gibt das Zimmer zurueck | der Grund des Laufs |

**Warum der Grund in den Wert gehoert und nicht in einen zweiten
Schluessel.** Alle drei wollen dasselbe: einen Downlink mit dem
Engine-Sollwert, ohne die Hysterese. Zwei Schluessel waeren zwei
Mechaniken fuer eine Wirkung (Paragraph 5.53), und bei zwei gesetzten
Flaggen zwei Downlinks fuer eine Abweichung — also genau der
Hardware-Schaden, den Paragraph 0 S4 verbietet.

**Warum nicht einfach ueberall ``reboot_resync`` protokollieren.** Weil
es dann im Audit stuende, und es waere falsch: niemand hat neu gestartet.
Ein ``control_command``, der einen Neustart behauptet, der nicht
stattgefunden hat, ist eine Behauptung in einer Quelle, die spaeter als
Beleg gelesen wird (Paragraph 5.68). Einen **eigenen** Enum-Wert je Grund
kann es dafuer nicht geben: ``CommandReason`` haengt an einer
``CHECK``-Beschraenkung mit ``length=30``, jeder neue Wert waere eine
Migration (Paragraph 5.45) — und fuer eine Audit-Nuance ist das die
falsche Waehrung. Deshalb bleibt es bei ``base_reason`` plus dem Grund im
Hysterese-Text, genau wie beim Engine-Abgleich.

**Der letzte Grund gilt.** Setzen zwei Anlaesse hintereinander, bevor der
Engine-Lauf konsumiert, ueberschreibt der zweite den ersten. Das ist kein
Verlust: beide wollen denselben Downlink, und der Grund, der naeher am
Ereignis liegt, ist der bessere Bericht. Deterministisch ist es auch
(Paragraph S2) — kein Vorrang-Geflecht, das man nachlesen muesste.
"""

from __future__ import annotations

import logging

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

RESYNC_KEY_TEMPLATE = "resync_pending:{dev_eui}"
RESYNC_TTL_S = 3600

#: Geraete-Neustart via fcnt-Reset (Sprint 15c, AE-63). Der einzige Grund,
#: der im ``control_command`` einen eigenen ``reason`` traegt — er ist
#: keine Nuance, sondern ein Befund ueber das Geraet.
GRUND_REBOOT = "reboot"

#: Eine Drehung am Rad wurde wegen der Gast-Sperre abgewiesen
#: (Sprint 23 T4-A2b). Das Geraet haelt dann einen Wert, den niemand mehr
#: will, und niemand ausser diesem Flag holt es zurueck: die Hysterese
#: sieht ``delta = 0``, und der Engine-Abgleich ist je Geraet auf eine
#: Nachsendung je 30 Minuten gedrosselt.
GRUND_SPERRE = "sperre"

#: Die Sollwert-Probe gibt ein Zimmer an die Engine zurueck
#: (``scripts/geraetegrenzen``). Sie hat ``0x51`` direkt geschickt, die
#: Hysterese weiss davon nichts.
GRUND_PROBE = "probe"

#: Was ein Schluessel aus der Zeit vor dem 30.10.2026 bedeutet.
#:
#: Beim Deploy koennen Schluessel mit dem alten Wert ``"1"`` und bis zu
#: einer Stunde Restfrist in Redis stehen. Sie kamen damals nur aus dem
#: Reboot-Gate — der wird hier also wiederhergestellt, statt den Re-Sync
#: zu verlieren oder ihn mit einem leeren Grund durchzureichen.
_ALTER_WERT = "1"


def _key(dev_eui: str) -> str:
    return RESYNC_KEY_TEMPLATE.format(dev_eui=dev_eui.lower())


def _als_grund(rohwert: object) -> str:
    """Redis-Rueckgabe zu einem Grund.

    Zur Laufzeit kommt je nach ``decode_responses`` ``bytes`` oder ``str``.
    Ein unbekannter Wert wird **nicht** verworfen: der Schluessel stand,
    also soll der Re-Sync stattfinden — nur sein Bericht ist dann der
    Rohwert, und das ist sichtbar statt stumm.
    """
    wert = rohwert.decode() if isinstance(rohwert, bytes) else str(rohwert)
    return GRUND_REBOOT if wert == _ALTER_WERT else wert


def mark_pending(dev_eui: str, *, grund: str, ttl_s: int = RESYNC_TTL_S) -> bool:
    """Setzt ``resync_pending:{dev_eui}`` mit TTL. True bei Erfolg.

    Falls Redis nicht erreichbar: Logger-Warning, return False. Aufrufer
    kann auswerten ob das Flag wirklich gesetzt wurde — bei False bleibt
    der Re-Sync auf den naechsten 60-s-Beat-Tick angewiesen.

    :param grund: einer der ``GRUND_*``-Werte, **Pflicht**. Kein Default:
        er waere die Stelle, an der ein Aufrufer seinen Grund stumm
        verliert, und der Grund entscheidet darueber, was im Audit steht.
    """
    try:
        redis_client.get_redis_client().set(_key(dev_eui), grund, ex=ttl_s)
        return True
    except redis.RedisError:
        logger.warning(
            "resync_flag.mark_pending: redis-fehler fuer dev_eui=%s grund=%s",
            dev_eui,
            grund,
            exc_info=True,
        )
        return False


def consume(dev_eui: str) -> str | None:
    """Atomarer Check+Delete: der **Grund**, wenn das Flag stand, sonst ``None``.

    Nutzt ``GETDEL`` (Redis 6.2+). Atomar — kein Race zwischen GET und DEL,
    auch nicht bei zwei parallelen ``_dispatch_downlinks_per_zone`` (z.B.
    bei zwei Vickis derselben Zone in derselben Eval).

    Die Rueckgabe ist seit Sprint 23 T4-A2b der Grund und kein ``bool``.
    Beides zugleich waere moeglich gewesen (``bool`` plus ein zweites
    ``grund(dev_eui)``), aber ein zweiter Aufruf koennte nach dem
    ``GETDEL`` nichts mehr finden — der Grund muss aus demselben
    atomaren Schritt kommen wie die Entscheidung.

    Bei Redis-Fehler: Logger-Warning, return ``None`` (defensive — kein
    forcierter Downlink ohne Beleg, dass das Flag wirklich gesetzt war).
    """
    try:
        result = redis_client.get_redis_client().getdel(_key(dev_eui))
    except redis.RedisError:
        logger.warning(
            "resync_flag.consume: redis-fehler fuer dev_eui=%s",
            dev_eui,
            exc_info=True,
        )
        return None
    if result is None:
        return None
    return _als_grund(result)
