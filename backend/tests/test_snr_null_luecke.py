"""Die 0-dB-Luecke: protojson laesst ``snr: 0`` weg (Befund 07.10.2026).

**Der Befund.** Die Signal-Kachel der Geraeteseite zeigte fuer Geraet 001
"–" statt eines SNR-Werts. Messung ueber sieben Tage:

    zeilen 1004 | mit_snr 976 | genau_null 0 | kleinster -8.0 | mit_rssi 1004

Drei Zahlen zusammen sind der Beleg:

1. ``mit_rssi = zeilen`` — ``rxInfo`` war in **jedem** Frame da. Es fehlt
   nicht der Block, sondern ein Feld darin.
2. ``kleinster = -8.0`` — negative Werte kommen durch, also kein Vorzeichen-
   oder Typproblem.
3. ``genau_null = 0`` in 976 Messwerten, obwohl 001 nachweislich um 0 dB
   funkt. Ein Wert, der nie auftritt, obwohl er der haeufigste sein muesste.

**Ursache:** ``[integration.mqtt] json = true`` in ``chirpstack.toml``.
ChirpStack serialisiert ueber protojson, und protojson laesst Felder mit
Default-Wert weg.

**Was zuerst verdaechtig war und es nicht ist**, weil es in der Diagnose
Zeit gekostet hat und beim naechsten Mal nicht wieder kosten soll:

- ``formatSnr`` im Frontend prueft ausdruecklich auf ``null``/``undefined``,
  nicht auf Falsyness — ``formatSnr(0)`` liefert ``"0.0 dB"``.
- Die ``{hint ? … : null}``-Pruefung auf der Geraeteseite ist zwar eine
  Falsy-Pruefung, arbeitet aber auf dem **formatierten String**, und
  ``"0.0 dB"`` ist truthy.
- Der Readings-Endpunkt sortiert ``time DESC``, ``readings[0]`` ist also der
  neueste Frame und nicht der aelteste.
- Einen Zod-Spiegel gibt es fuer diesen Endpunkt nicht, es kann also nichts
  gestrippt worden sein (§5.64 war hier nicht die Ursache).

Reine Funktionstests, keine Datenbank.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from heizung.services.mqtt_subscriber import (
    ChirpStackUplink,
    _map_to_reading,
    _RxInfo,
    _snr_db,
)


def uplink_mit_rxinfo(rx: dict[str, object] | None) -> ChirpStackUplink:
    """Ein Periodic-Report-Uplink mit genau diesem ``rxInfo``-Eintrag.

    ``rx=None`` erzeugt einen Uplink **ohne** ``rxInfo`` — der Fall, in dem
    wir ueber den Empfang nichts wissen.
    """
    daten: dict[str, object] = {
        "deviceInfo": {"devEui": "70b3d52dd3033393"},
        "fCnt": 110,
        "fPort": 2,
        "time": "2026-10-07T09:00:00Z",
        "object": {"report_type": "periodic", "temperature": 21.4, "target_temperature": 21},
        "data": "gRKdYZmZEeAw",
    }
    if rx is not None:
        daten["rxInfo"] = [rx]
    return ChirpStackUplink.model_validate(daten)


# ---------------------------------------------------------------------------
# 1. Die Luecke selbst
# ---------------------------------------------------------------------------


def test_fehlendes_snr_bei_vorhandenem_rxinfo_ist_null_db() -> None:
    """**Der Befund als Test.** Block da, Feld weg -> 0 dB, nicht NULL.

    Genau die Form, in der ChirpStack einen Frame mit SNR 0 liefert: das
    Feld steht nicht im JSON.
    """
    rx = _RxInfo.model_validate({"rssi": -85})

    assert _snr_db(rx) == Decimal("0")


def test_ohne_rxinfo_bleibt_snr_null() -> None:
    """**Die Grenze des Schlusses, und sie ist der wichtigere Teil.**

    Ohne ``rxInfo`` wissen wir ueber den Empfang nichts — dort waere eine 0
    eine Behauptung statt einer Luecke. Der ganze Fix haengt daran, dass die
    Messung ``mit_rssi = zeilen`` gezeigt hat; ohne diese Zahl waere er
    nicht zulaessig gewesen.
    """
    assert _snr_db(None) is None


def test_negative_werte_kommen_unveraendert_durch() -> None:
    """Der Beleg, dass die Luecke nur den Default-Wert betrifft.

    ``kleinster = -8.0`` in der Messung: protojson laesst 0 weg, nicht die
    negativen Werte. Ein Fix, der auf alles reagiert, was "klein" aussieht,
    waere falsch.
    """
    rx = _RxInfo.model_validate({"rssi": -90, "snr": -8.0})

    assert _snr_db(rx) == Decimal("-8.0")


def test_ausdrueckliche_null_bleibt_null() -> None:
    """Steht die 0 doch im JSON, aendert sich nichts.

    Relevant, falls ein spaeterer ChirpStack-Stand ``EmitUnpopulated``
    setzt oder ein anderer Erzeuger dazukommt: dann kommt derselbe Wert auf
    dem anderen Weg, und das Ergebnis muss dasselbe sein.
    """
    rx = _RxInfo.model_validate({"rssi": -90, "snr": 0})

    assert _snr_db(rx) == Decimal("0")


@pytest.mark.parametrize("wert", [7.5, 9.8, 0.5, -0.5, -12.25])
def test_bestandswerte_unveraendert(wert: float) -> None:
    """Gegenprobe gegen einen Fix, der mehr tut als er soll."""
    rx = _RxInfo.model_validate({"rssi": -88, "snr": wert})

    assert _snr_db(rx) == Decimal(str(wert))


# ---------------------------------------------------------------------------
# 2. Im Mapping, also auf dem Weg in die Spalte
# ---------------------------------------------------------------------------


def test_mapping_schreibt_null_db_statt_null() -> None:
    """Der Pfad, der die Spalte fuellt — nicht nur die Hilfsfunktion.

    Ohne diesen Test waere ein Fix gruen, der die Funktion richtig macht und
    sie an der Aufrufstelle nicht benutzt.
    """
    uplink = uplink_mit_rxinfo({"rssi": -85})

    werte = _map_to_reading(uplink, device_id=7)

    assert werte["snr_db"] == Decimal("0")
    assert werte["rssi_dbm"] == -85


def test_mapping_ohne_rxinfo_laesst_beide_felder_null() -> None:
    """Ohne Empfangsdaten bleibt auch ``rssi_dbm`` NULL.

    ``rssi`` bekommt **keine** Luecken-Regel: 0 dBm am Empfaenger waere
    1 mW, physikalisch nicht vorstellbar, und die Messung zeigt
    ``mit_rssi = zeilen``. Eine Regel fuer einen Fall, der nicht vorkommt,
    waere eine Annahme mehr (§0 S6).
    """
    uplink = uplink_mit_rxinfo(None)

    werte = _map_to_reading(uplink, device_id=7)

    assert werte["snr_db"] is None
    assert werte["rssi_dbm"] is None
