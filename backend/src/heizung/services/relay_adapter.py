"""Befehlsschicht fuer MClimate 16ASPM (Sprint 24, Infrarot-Pilot).

**Transport wird wiederverwendet, Befehle nicht.** Alle Funktionen hier
bauen ihre Bytes und delegieren an
``downlink_adapter.send_raw_downlink`` — dieselbe MQTT-Mechanik, die der
Vicki benutzt, mit demselben ``devEui``-im-Payload (§5.13) und demselben
Topic. Es gibt hier bewusst keine eigene MQTT-Verbindung: der Pfad ist
einmal gebaut und einmal getestet (AE-48).

**S1 ist in diesem Modul verankert, nicht nur dokumentiert.** Es gibt
**keine** Funktion, die ``0xC1 0x01`` sendet. Eingeschaltet wird
ausschliesslich ueber den Relais-Timer ``0x57``; ``0xC1`` kommt nur mit
``0x00`` vor, als Ausschaltbefehl. Wer EIN dauerhaft setzen will, muesste
dieses Modul aendern — und das faellt in der Durchsicht auf, anders als
ein Aufrufer, der einen Parameter falsch setzt.

Die Zusicherung haengt an ``relais_ein_payload``: der Timer-Befehl setzt
Byte 1 fest auf ``0x01`` und nimmt nur die Dauer als Parameter.

**Belegte Geraete-Eigenschaften** (Hersteller-Doku zum 16ASPM,
abgerufen 23.10.2026):

- **Class C** — das Geraet hoert dauerhaft, Downlinks gehen jederzeit.
  Kein Warten auf ein Empfangsfenster wie beim Vicki (Class A). Ein
  Schaltbefehl wirkt deshalb sofort, und der Waechter kann sich auf
  kurze Reaktionszeiten verlassen.
- **Downlink-fPorts 1, 2, 4-224** — fPort 1, wie beim Vicki.
- **Fuer die Erstkonfiguration empfiehlt der Hersteller bestaetigte
  Downlinks** („for critical messages, such as initial parameter setup,
  we recommend using confirmed downlinks"). Die Provisionierung (S4)
  nutzt deshalb ``confirmed=True``, die laufenden Schaltbefehle nicht:
  ein bestaetigter Downlink je Schaltvorgang waere zusaetzlicher
  Funkverkehr fuer eine Bestaetigung, die wir ueber den Uplink ohnehin
  einholen (Paket C).

**Was dieses Modul nicht tut:** es entscheidet nichts. Ob ein Relais
schalten darf (S3, Inbetriebnahme) und ob es schalten soll (Regler,
Waechter) entscheiden die Aufrufer. Hier werden nur Bytes gebaut und
verschickt.
"""

from __future__ import annotations

import logging

from heizung.services.downlink_adapter import send_raw_downlink

logger = logging.getLogger(__name__)

# --- Befehlscodes, Hersteller-Doku zum 16ASPM ---
CMD_KEEPALIVE_PERIOD_SET = 0x02
CMD_KEEPALIVE_PERIOD_GET = 0x12
CMD_VERSION_GET = 0x04
CMD_CHANGE_REASON_GET = 0x54
CMD_TIMER_SECONDS_SET = 0x57
CMD_TIMER_SECONDS_GET = 0x58
CMD_OVERHEATING_RECOVERY_SET = 0x59
CMD_OVERHEATING_RECOVERY_GET = 0x5A
CMD_POWER_RETURN_SET = 0x5E
CMD_POWER_RETURN_GET = 0x5F
CMD_RELAY_STATE_GET = 0xB1
CMD_RELAY_STATE_SET = 0xC1

#: Grenzen des Timers in Sekunden, Hersteller-Doku: „1…65 535 seconds
#: (1sec. resolution)".
TIMER_MIN_S = 1
TIMER_MAX_S = 65535

#: ``0x5E``-Werte. Die Vorgabe des Geraets ist ``last_state`` — ein
#: nicht konfiguriertes Relais kommt nach einem Stromausfall in seinem
#: **alten** Zustand zurueck. Deshalb ist ``off`` Teil der
#: Provisionierung und nicht eine Reaktion des Servers (S4, AE-78 §4).
POWER_RETURN_LAST_STATE = 0x00
POWER_RETURN_ON = 0x01
POWER_RETURN_OFF = 0x02

#: Ab dieser Firmware liefert das Geraet ``0x54`` (Grund der
#: Zustandsaenderung) und die Timer-Befehle ``0x55``-``0x58``. Darunter
#: faellt der Waechter auf die Zustandsaenderung im Keepalive zurueck
#: (Paket B, letzter Punkt).
FIRMWARE_MIT_TIMER = (1, 4)


class RelayCommandError(ValueError):
    """Ein Befehl ist mit unzulaessigen Parametern aufgerufen worden.

    Eigene Klasse und keine blanke ``ValueError``, damit ein Aufrufer sie
    von einem Programmierfehler unterscheiden kann — und damit sie im
    API-Pfad gezielt auf 422 abgebildet werden kann.
    """


def firmware_hat_timer(firmware_version: str | None) -> bool:
    """Ob die Firmware die Timer- und Grund-Befehle kennt (>= 1.4).

    ``None`` oder ein unlesbarer Wert ergibt **False**. Das ist die
    sichere Richtung: der Waechter faellt dann auf die Erkennung ueber
    den Zustandswechsel zurueck, statt sich auf ``0x54`` zu verlassen,
    das vielleicht nie kommt. Eine unbekannte Firmware als „kann alles"
    zu behandeln waere ein Waechter, der stumm nichts tut.
    """
    if not firmware_version:
        return False
    teile = firmware_version.split(".")
    if len(teile) < 2:
        return False
    try:
        major, minor = int(teile[0]), int(teile[1])
    except ValueError:
        return False
    return (major, minor) >= FIRMWARE_MIT_TIMER


def relais_ein_payload(sekunden: int) -> bytes:
    """``0x57 01 <HH> <LL>`` — EIN fuer ``sekunden``, danach Rueckfall.

    **Byte 1 ist festverdrahtet ``0x01``.** Der Befehl kann nur
    einschalten; ein Timer-AUS (``0x57 00 ...``) hat in dieser Anwendung
    keinen Fall und wuerde die Zusicherung S1 verwaessern, weil dann zwei
    Bedeutungen am selben Code haengen.
    """
    if not isinstance(sekunden, int) or isinstance(sekunden, bool):
        raise RelayCommandError(f"sekunden muss eine ganze Zahl sein, ist {sekunden!r}")
    if sekunden < TIMER_MIN_S or sekunden > TIMER_MAX_S:
        raise RelayCommandError(f"sekunden {sekunden} ausserhalb [{TIMER_MIN_S}, {TIMER_MAX_S}]")
    return bytes([CMD_TIMER_SECONDS_SET, 0x01, sekunden >> 8, sekunden & 0xFF])


def relais_aus_payload() -> bytes:
    """``0xC1 00`` — AUS. Der einzige Gebrauch von ``0xC1`` hier (S1).

    Nebenwirkung laut Doku: ``0xC1`` **bricht einen laufenden Timer ab**
    („The relay timer is deactivated when setting the relay state with
    command C1"). Das ist gewollt — AUS soll sofort und endgueltig sein,
    nicht nach Ablauf eines Timers.
    """
    return bytes([CMD_RELAY_STATE_SET, 0x00])


def zustand_nach_stromrueckkehr_payload(modus: str) -> bytes:
    """``0x5E <modus>`` — was das Relais nach Stromrueckkehr tut."""
    werte = {
        "last_state": POWER_RETURN_LAST_STATE,
        "on": POWER_RETURN_ON,
        "off": POWER_RETURN_OFF,
    }
    if modus not in werte:
        raise RelayCommandError(f"modus muss einer von {sorted(werte)} sein, ist {modus!r}")
    return bytes([CMD_POWER_RETURN_SET, werte[modus]])


def zustand_nach_ueberhitzung_payload(modus: str) -> bytes:
    """``0x59 <modus>`` — Zustand nach Erholung vom Ueberhitzungsschutz.

    **AUS ist hier ``0x01``, nicht ``0x02``.** Bei ``0x5E`` ist AUS die
    ``0x02``; dieser Befehl kennt nur zwei Werte und gar kein „ON". Wer
    die Zuordnung von ``0x5E`` uebernimmt, sendet mit ``0x02`` einen
    Wert, den die Doku nicht fuehrt — und erfaehrt es nicht, weil ein
    unbekannter Parameter nichts meldet.

    Deshalb ist die Zuordnung hier eine eigene Tabelle und nicht die von
    ``zustand_nach_stromrueckkehr_payload`` wiederverwendet. Zwei
    aehnliche Befehle mit verschiedenen Werten sind genau die Stelle, an
    der eine geteilte Tabelle Schaden anrichtet.
    """
    werte = {"last_state": 0x00, "off": 0x01}
    if modus not in werte:
        raise RelayCommandError(
            f"modus muss einer von {sorted(werte)} sein, ist {modus!r} (0x59 kennt kein 'on')"
        )
    return bytes([CMD_OVERHEATING_RECOVERY_SET, werte[modus]])


def keepalive_periode_payload(minuten: int) -> bytes:
    """``0x02 <minuten>`` — Keepalive-Periode des Geraets.

    **Die Vorgabe des Geraets ist nicht dokumentiert** (AE-78 §3). Sie
    wird deshalb bei der Provisionierung ausdruecklich gesetzt, statt
    sich auf einen Wert zu verlassen, den niemand kennt: der Waechter
    und die Veraltungs-Pruefung (S5) rechnen beide mit ihr.
    """
    if not isinstance(minuten, int) or isinstance(minuten, bool):
        raise RelayCommandError(f"minuten muss eine ganze Zahl sein, ist {minuten!r}")
    if minuten < 1 or minuten > 255:
        raise RelayCommandError(f"minuten {minuten} ausserhalb [1, 255]")
    return bytes([CMD_KEEPALIVE_PERIOD_SET, minuten])


# --- Versand ---------------------------------------------------------------


async def relais_ein_fuer(dev_eui: str, sekunden: int) -> str:
    """Schaltet EIN, befristet auf ``sekunden`` (S1)."""
    topic = await send_raw_downlink(dev_eui, relais_ein_payload(sekunden))
    logger.info("relais ein dev_eui=%s sekunden=%s", dev_eui.lower(), sekunden)
    return topic


async def relais_aus(dev_eui: str) -> str:
    """Schaltet AUS und bricht einen laufenden Timer ab."""
    topic = await send_raw_downlink(dev_eui, relais_aus_payload())
    logger.info("relais aus dev_eui=%s", dev_eui.lower())
    return topic


async def frage_zustand(dev_eui: str) -> str:
    """``0xB1`` — Zustand abfragen. Antwort kommt im naechsten Uplink."""
    return await send_raw_downlink(dev_eui, bytes([CMD_RELAY_STATE_GET]))


async def frage_timer(dev_eui: str) -> str:
    """``0x58`` — Zustand **und Restlaufzeit** abfragen.

    Die Restlaufzeit ist der Grund, warum diese Abfrage neben ``0xB1``
    steht: sie sagt, ob ueberhaupt ein Timer laeuft. Der Waechter kann
    damit pruefen, statt zu schliessen.
    """
    return await send_raw_downlink(dev_eui, bytes([CMD_TIMER_SECONDS_GET]))


async def frage_schaltgrund(dev_eui: str) -> str:
    """``0x54`` — Grund der letzten Zustandsaenderung (FW >= 1.4).

    Die Doku definiert fuer ``0x54`` nur eine **Antwort**, keine Anfrage;
    die Befehlstabelle fuehrt den Code aber als ``Server/End device``.
    Ob die Abfrage traegt, ist am Geraet zu pruefen (AE-78) — der
    Waechter verlaesst sich nicht darauf, sondern wertet den Grund aus,
    **wenn** das Geraet ihn von selbst mitschickt.
    """
    return await send_raw_downlink(dev_eui, bytes([CMD_CHANGE_REASON_GET]))


async def setze_zustand_nach_stromrueckkehr(dev_eui: str, modus: str = "off") -> str:
    """``0x5E`` — Provisionierung (S4). Bestaetigter Downlink.

    ``confirmed=True`` nach Hersteller-Empfehlung fuer die
    Erstkonfiguration. Die Bestaetigung des LoRaWAN-Stacks sagt, dass das
    Geraet den Frame bekommen hat — **nicht**, dass die Einstellung
    sitzt. Dafuer gibt es ``frage_zustand_nach_stromrueckkehr``, und S4
    verlangt dieses Ruecklesen ausdruecklich.
    """
    topic = await send_raw_downlink(
        dev_eui, zustand_nach_stromrueckkehr_payload(modus), confirmed=True
    )
    logger.info("stromrueckkehr-zustand gesetzt dev_eui=%s modus=%s", dev_eui.lower(), modus)
    return topic


async def frage_zustand_nach_stromrueckkehr(dev_eui: str) -> str:
    """``0x5F`` — die Einstellung zurueckleasen (S4)."""
    return await send_raw_downlink(dev_eui, bytes([CMD_POWER_RETURN_GET]))


async def setze_zustand_nach_ueberhitzung(dev_eui: str, modus: str = "off") -> str:
    """``0x59`` — was das Relais nach der Erholung vom Ueberhitzungsschutz tut.

    **Der zweite Weg, auf dem ein Relais von selbst wieder EIN wird**, und
    deshalb Teil von S4 (Nachtrag 23.10.). Die Doku zur Erholung:
    das Relais sei „returned to its previous state after recovering from
    the protection event", und die Vorgabe von ``0x59`` ist
    ``last_state``. Ein Relais, das wegen Hitze abgeschaltet hat, kaeme
    nach dem Abkuehlen also zurueck, ohne dass wir etwas gesendet haben.
    """
    payload = zustand_nach_ueberhitzung_payload(modus)
    topic = await send_raw_downlink(dev_eui, payload, confirmed=True)
    logger.info(
        "ueberhitzungs-erholungszustand gesetzt dev_eui=%s modus=%s", dev_eui.lower(), modus
    )
    return topic


async def frage_zustand_nach_ueberhitzung(dev_eui: str) -> str:
    """``0x5A`` — die Einstellung zurueckleasen (S4)."""
    return await send_raw_downlink(dev_eui, bytes([CMD_OVERHEATING_RECOVERY_GET]))


async def setze_keepalive_periode(dev_eui: str, minuten: int) -> str:
    """``0x02`` — Keepalive-Periode setzen. Bestaetigter Downlink."""
    return await send_raw_downlink(dev_eui, keepalive_periode_payload(minuten), confirmed=True)


async def frage_keepalive_periode(dev_eui: str) -> str:
    """``0x12`` — Keepalive-Periode lesen."""
    return await send_raw_downlink(dev_eui, bytes([CMD_KEEPALIVE_PERIOD_GET]))


async def frage_version(dev_eui: str) -> str:
    """``0x04`` — Hardware- und Softwareversion lesen.

    Noetig fuer ``firmware_hat_timer``: unter 1.4 gibt es keine
    Timer-Befehle, und damit ist S1 auf diesem Geraet **nicht**
    erfuellbar — ein solches Relais darf nicht in Betrieb genommen
    werden.
    """
    return await send_raw_downlink(dev_eui, bytes([CMD_VERSION_GET]))
