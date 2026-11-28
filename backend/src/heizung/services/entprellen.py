"""Entprellen der Sollwert-Befehle (Sprint 25 T1, gebaut 27.11.2026).

**Der Anlass steht im Brief vom 05.11.2026.** Aendert die Steuerung ihren
Wunsch zweimal kurz hintereinander — erst 20, dann 25 innerhalb von
hundert Sekunden —, gehen **zwei** Downlinks hinaus und das Ventil fuehrt
**zwei** Bewegungen aus. Die erste davon war ueberfluessig, und sie kostet
Batterie und Motorlauf. 125 solche Faelle lagen dem Brief zugrunde.

Die Gegenmassnahme ist eine Wartezeit: je Geraet wird die erste Aenderung
**gesammelt** statt gesendet, und erst der naechste Tick nach Ablauf des
Fensters schickt den dann gueltigen Wert. Aus 20 nach 25 wird ein Publish
mit 25; aus 20 nach 25 nach 20 wird **keiner**.

Warum der Tick die Uhr ist und keine eigene Aufgabe
---------------------------------------------------

Die naheliegende Form waere ein Celery-Auftrag mit ``countdown``, der nach
sechzig Sekunden den gemerkten Wert schickt. Dagegen sprechen zwei Dinge:

1. **Der gemerkte Wert waere der alte.** Der Auftrag muesste senden, was
   vor einer Minute gewollt war. Der Tick dagegen rechnet den Wunsch neu
   und schickt den **jetzt** gueltigen — und das ist der Punkt des
   Entprellens.
2. **Ein zweiter Schreibpfad an die Hardware.** Heute geht jeder Sollwert
   durch genau eine Stelle (``engine_tasks._dispatch``). Ein Auftrag, der
   daneben publiziert, waere der zweite — und zwei Pfade zur selben
   Geraete-Warteschlange sind der Fall, den Paragraph 0 S4 verbietet.

Die Engine laeuft im Minutentakt. Mit ``fenster_s = 60`` geht ein Wert
also beim naechsten Tick hinaus, der mindestens eine Minute nach der
ersten Aenderung liegt: **60 bis 120 Sekunden**, genau die Spanne aus dem
Brief. Die Wartezeit ist damit eine Folge des Takts und keine zweite Uhr,
die man synchron halten muesste.

Was gesammelt wird und was nicht
--------------------------------

* **Nur Sollwerte** (``0x51``). ``0x07`` (Kindersicherung), ``0x08``
  (Grenzen) und ``0x45``/``0x46`` (Fenstererkennung) laufen ueber
  ``downlink_adapter`` und beruehren dieses Modul nicht. Vorgabe des
  Betreibers, und sie ist die bessere Reihenfolge: Class A stellt in
  Einreihungsfolge zu, Konfigurationsbefehle kommen also **vor** einem
  entprellten Sollwert an — Grenzen zuerst, dann der Wert, der sie
  einhalten muss.
* **Der Boost umgeht das Fenster.** Er ist die eine Sollwertaenderung, die
  der Gast sofort spueren soll; eine Minute Wartezeit waere genau dort
  teuer, wo jemand auf Wirkung wartet und sonst noch einmal drueckt. Ein
  Boost **loescht** dabei den Merker (``verwirf``), statt ihn zu
  ignorieren — sonst folgte dem sofortigen Boost eine Minute spaeter der
  gesammelte alte Wert und naehme ihn zurueck.

Bei Redis-Ausfall wird **gesendet**
-----------------------------------

Pflicht aus Paragraph 0 S5: ein Puffer, der bei Stoerung Befehle
verschluckt, ist schlimmer als der Zustand ohne ihn. Faellt Redis aus,
faellt das Entprellen **zum Senden hin** aus — die Anlage verhaelt sich
dann wie vor dem 27.11.2026, mit einer Zeile im Protokoll.

Das ist die **andere** Richtung als bei ``engine_abgleich.darf_senden``,
und der Unterschied ist Absicht: dort verhindert die Sperre eine
Nachsendung, die Batterie kostet und nichts bewirkt — ohne Sperre lieber
nicht senden. Hier verzoegert der Merker einen Befehl, den die Steuerung
**will** — ohne Merker lieber senden.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import cast

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

#: Schluessel-Vorsilbe. Eigener Raum neben ``engine_abgleich`` und
#: ``resync_flag``, damit ein ``KEYS``-Blick im Betrieb die drei
#: auseinanderhalten kann.
_VORSILBE = "entprell:sollwert:"

#: Obergrenze fuer die Lebensdauer eines Merkers. Fuenfzehn Minuten: lang
#: genug fuer jedes sinnvolle Fenster, kurz genug, dass ein Merker nach
#: einem Ausfall des Taktgebers nicht ewig stehenbleibt und den naechsten
#: echten Wunsch um Stunden verschiebt. **Ein Zustand, der plausibel
#: einfriert, ist das Fehlerbild aus Paragraph 5.76.**
_MERKER_TTL_S = 900


def _key(dev_eui: str) -> str:
    return f"{_VORSILBE}{dev_eui}"


@dataclass(frozen=True, slots=True)
class Urteil:
    """Was mit diesem Sollwert geschehen soll."""

    #: ``True`` = jetzt senden. ``False`` = gesammelt, der naechste Tick
    #: entscheidet neu.
    senden: bool
    #: Kurzer Grund fuer den Trace. Wandert in ``hysteresis_reason`` und
    #: damit in ``details`` des ``hard_clamp``-Eintrags (Paragraph 5.44),
    #: wo die Abnahme ihn liest.
    grund: str
    #: Alter des Merkers in Sekunden, gerundet. ``None``, wenn es keinen
    #: gab oder Redis nicht erreichbar war.
    alter_s: int | None = None


def pruefe(dev_eui: str, setpoint_c: int, *, fenster_s: int) -> Urteil:
    """Sammeln oder senden — und den Merker in einem Schritt nachziehen.

    Der erste Aufruf fuer ein Geraet legt den Merker und sammelt. Jeder
    weitere Aufruf innerhalb des Fensters **ueberschreibt den Wert** und
    sammelt weiter. Der erste Aufruf nach Ablauf des Fensters loescht den
    Merker und sagt „senden".

    **Der gesammelte Wert wird nicht zurueckgegeben**, und das ist kein
    Versehen: gesendet wird, was der Tick **jetzt** will. Der Merker haelt
    den Wert nur fuer das Protokoll — damit nach einem ueberfluessigen
    Publish nachlesbar ist, was unterwegs verworfen wurde.

    ``fenster_s <= 0`` schaltet das Entprellen ab (Vorgabe in den
    Settings ist 60). Dann wird immer gesendet, ohne Redis anzufassen —
    ein abgeschalteter Mechanismus soll auch keinen Zustand hinterlassen.

    :return: ``Urteil``. Bei Redis-Ausfall ``senden=True`` (siehe
        Modulkopf, Paragraph 0 S5).
    """
    if fenster_s <= 0:
        return Urteil(senden=True, grund="entprellen_aus")

    jetzt = int(time.time())
    try:
        client = redis_client.get_redis_client()
        # ``cast``: die Stubs von redis-py geben fuer den
        # synchronen Client ``Awaitable | dict`` zurueck. Der
        # Client hier ist synchron (``redis.Redis``), wie in
        # ``engine_abgleich``.
        roh = cast("dict[str, str]", client.hgetall(_key(dev_eui)))
    except redis.RedisError:
        logger.warning(
            "entprellen.pruefe: Redis nicht erreichbar fuer %s — es wird "
            "GESENDET (ein Puffer, der bei Stoerung Befehle verschluckt, "
            "ist schlimmer als keiner; Paragraph 0 S5)",
            dev_eui,
            exc_info=True,
        )
        return Urteil(senden=True, grund="entprellen_ohne_redis")

    seit = _zu_int(roh.get("seit") if roh else None)
    if seit is None:
        _merke(dev_eui, setpoint_c=setpoint_c, seit=jetzt)
        return Urteil(senden=False, grund=f"entprellt_gesammelt fenster={fenster_s}s", alter_s=0)

    alter = max(0, jetzt - seit)
    if alter >= fenster_s:
        verwirf(dev_eui)
        return Urteil(senden=True, grund=f"entprellt_abgelaufen alter={alter}s", alter_s=alter)

    _merke(dev_eui, setpoint_c=setpoint_c, seit=seit)
    return Urteil(
        senden=False,
        grund=f"entprellt_gesammelt alter={alter}s fenster={fenster_s}s",
        alter_s=alter,
    )


def verwirf(dev_eui: str) -> None:
    """Loescht den Merker. Fehler werden protokolliert, nicht geworfen.

    **Drei Aufrufer, drei Gruende:**

    * Das Fenster ist abgelaufen und der Wert geht hinaus.
    * Die Steuerung will **nichts** senden (die Hysterese schweigt). Dann
      muss der Merker weg, sonst gilt das Fenster beim naechsten echten
      Wunsch als schon abgelaufen — und der ginge sofort hinaus. Genau
      dieser Fall ist der Gewinn des Entprellens: 20, dann 25, dann wieder
      20 ergibt **keinen** Downlink.
    * Ein Boost. Er sendet sofort; ein stehender Merker wuerde eine Minute
      spaeter den alten Wert nachschicken und den Boost zuruecknehmen.
    """
    try:
        redis_client.get_redis_client().delete(_key(dev_eui))
    except redis.RedisError:
        logger.warning("entprellen.verwirf: Redis nicht erreichbar fuer %s", dev_eui, exc_info=True)


def _merke(dev_eui: str, *, setpoint_c: int, seit: int) -> None:
    """Schreibt Wert und Anfangszeit, ohne das Fenster zu verschieben.

    ``seit`` kommt vom Aufrufer und ist beim Nachziehen der **alte** Wert.
    Wuerde hier ``now`` stehen, verschoebe jede Aenderung das Fenster nach
    hinten — und ein Geraet, dessen Wunsch im Minutentakt wechselt,
    bekaeme nie einen Befehl. Dieselbe Falle wie bei
    ``engine_abgleich.versuch_gezaehlt`` und seiner TTL.
    """
    try:
        client = redis_client.get_redis_client()
        client.hset(_key(dev_eui), mapping={"wert": str(setpoint_c), "seit": str(seit)})
        client.expire(_key(dev_eui), _MERKER_TTL_S)
    except redis.RedisError:
        logger.warning("entprellen._merke: Redis nicht erreichbar fuer %s", dev_eui, exc_info=True)


def _zu_int(wert: object) -> int | None:
    """Robust gegen ``bytes`` und Unsinn im Schluessel.

    Ein Merker mit kaputtem Inhalt soll nicht den Tick abbrechen, sondern
    wie „kein Merker" gelesen werden. Der naechste Aufruf legt ihn neu.
    """
    if wert is None:
        return None
    if isinstance(wert, bytes):
        wert = wert.decode("utf-8", errors="replace")
    try:
        return int(str(wert))
    except ValueError:
        logger.warning("entprellen: unlesbarer Merker-Inhalt %r", wert)
        return None
