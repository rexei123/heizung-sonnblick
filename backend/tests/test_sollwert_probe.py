"""Sprint 23 T1a — die Sollwert-Probe fuer den Pflicht-Stop 107.

**Warum es diese Probe gibt.** Der Pflicht-Stop zu T1 sah vor, einen
Sollwert *ueber* der Obergrenze per Uebersteuerung zu setzen, um die
Hersteller-Aussage zu pruefen („die Grenze gilt nur fuer das Drehrad").
Das ist in 107 nicht durchfuehrbar: das Zimmer ist **frei**, und eine
Uebersteuerung verlangt einen eingecheckten Gast (AE-58). Befund des
Betreibers vom 26.10.2026.

Die Probe nimmt stattdessen den Fall, der im Betrieb ohnehin vorkommt:
einen **Frostschutz von 10 Grad** per Funk, wie ihn der Sommerbetrieb und
die Fenster-Sicherheit schicken. Damit prueft sie dieselbe Frage an der
Stelle, an der sie wirklich zaehlt.

Geprueft wird hier die **Warte- und Urteilslogik**, und zwar mit einer
virtuellen Uhr: Uhr und Warten kommen als **ein** Wert (``Clock``). Zwei
getrennte Einhaengepunkte liessen sich einzeln ersetzen, und genau daran
ist Sprint 19 fuenfzehn Minuten echter Wartezeit aufgesessen
(Paragraph 5.82) — der Zaehltest unten ist die Gegenprobe dazu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from heizung.scripts import geraetegrenzen as werkzeug
from heizung.scripts.pairing.clock import virtual_clock
from heizung.services.downlink_adapter import setpoint_bytes

START = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
GESENDET = START - timedelta(seconds=5)


@dataclass
class _Messwert:
    """Doppelgaenger fuer ``SensorReading`` — nur die drei Felder, die
    ``_warte_auf_readback`` anfasst: ``time``, ``setpoint`` und (ueber den
    Aufrufer) ``device_id``."""

    time: datetime
    setpoint: Decimal | None


def _mit_messwerten(monkeypatch: pytest.MonkeyPatch, folge: list[_Messwert | None]) -> list[int]:
    """Haengt eine Folge von Messwerten ein und zaehlt die Abfragen.

    Die Liste wird der Reihe nach abgearbeitet; ist sie leer, kommt der
    letzte Wert weiter zurueck. So laesst sich „erst nichts, dann der
    alte Wert, dann der neue" abbilden — die Reihenfolge, die im Betrieb
    vorkommt.
    """
    zaehler = [0]
    rest = list(folge)
    letzter: _Messwert | None = None

    async def fake(device_id: int) -> _Messwert | None:
        nonlocal letzter
        zaehler[0] += 1
        if rest:
            letzter = rest.pop(0)
        return letzter

    monkeypatch.setattr(werkzeug, "_juengster_messwert", fake)
    return zaehler


async def test_zielwert_wird_erkannt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der gute Fall: das Geraet meldet die 10 — Aussage bestaetigt."""
    _mit_messwerten(
        monkeypatch,
        [None, _Messwert(START + timedelta(minutes=2), Decimal("10.0"))],
    )
    urteil, gemeldet, wann = await werkzeug._warte_auf_readback(
        1,
        gesendet_um=GESENDET,
        ziel_c=10,
        timeout_s=900,
        intervall_s=20,
        clock=virtual_clock(START),
    )
    assert urteil == "ziel"
    assert gemeldet == Decimal("10.0")
    assert wann is not None


async def test_untergrenze_gemeldet_ist_der_stopp_fall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der Fall, der T1 stoppt.

    Das Geraet meldet 15 statt 10 — also seine Untergrenze. Dann klemmt
    es **auch Funk-Sollwerte** an der Grenze, und ein Frostschutz kaeme
    nicht mehr durch. Die Probe muss das als Abweichung melden und darf
    es nicht als „noch nicht angekommen" durchgehen lassen.
    """
    _mit_messwerten(monkeypatch, [_Messwert(START + timedelta(minutes=1), Decimal("15.0"))])
    urteil, gemeldet, _ = await werkzeug._warte_auf_readback(
        1,
        gesendet_um=GESENDET,
        ziel_c=10,
        timeout_s=900,
        intervall_s=20,
        clock=virtual_clock(START),
    )
    assert urteil == "abweichend"
    assert gemeldet == Decimal("15.0")


async def test_alter_uplink_vor_dem_befehl_zaehlt_nicht(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ein Messwert **vor** dem Senden ist keine Antwort darauf.

    Dieselbe Regel wie bei der Kindersicherung (24c): ohne den
    Zeitvergleich waere die juengste Meldung die vom Keepalive davor, und
    sie sagt „21 Grad" — was bis zur Sekunde vorher richtig war.
    """
    _mit_messwerten(
        monkeypatch,
        [_Messwert(GESENDET - timedelta(minutes=5), Decimal("21.0"))],
    )
    urteil, gemeldet, _ = await werkzeug._warte_auf_readback(
        1,
        gesendet_um=GESENDET,
        ziel_c=10,
        timeout_s=120,
        intervall_s=20,
        clock=virtual_clock(START),
    )
    assert urteil == "keine_antwort"
    assert gemeldet is None


async def test_keine_antwort_ist_kein_befund_ueber_die_grenze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stille heisst Funk, Duty-Cycle oder Batterie — nicht „Grenze klemmt"."""
    _mit_messwerten(monkeypatch, [None])
    urteil, gemeldet, wann = await werkzeug._warte_auf_readback(
        1,
        gesendet_um=GESENDET,
        ziel_c=10,
        timeout_s=300,
        intervall_s=20,
        clock=virtual_clock(START),
    )
    assert urteil == "keine_antwort"
    assert gemeldet is None
    assert wann is None


async def test_die_schleife_laeuft_so_oft_wie_das_fenster_erlaubt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die Gegenprobe zu Paragraph 5.82.

    Fenster 300 s, Abstand 20 s — also hoechstens 16 Durchlaeufe. Lief
    die Schleife mit einer **halb** gefaelschten Zeitquelle (``sleep``
    ersetzt, ``now`` nicht), waere sie so schnell wie die Datenbank
    antwortet und wuerde Tausende Male laufen, bis das Fenster in echter
    Zeit abgelaufen ist.

    Ohne diesen Zaehltest kommt derselbe Fehler beim naechsten Fake
    zurueck, und wieder sieht man nur eine Gesamtlaufzeit.
    """
    zaehler = _mit_messwerten(monkeypatch, [None])
    await werkzeug._warte_auf_readback(
        1,
        gesendet_um=GESENDET,
        ziel_c=10,
        timeout_s=300,
        intervall_s=20,
        clock=virtual_clock(START),
    )
    assert zaehler[0] <= 300 // 20 + 1, f"{zaehler[0]} Durchlaeufe — Zeitquelle halb gefaelscht?"
    assert zaehler[0] >= 2, "die Schleife hat gar nicht gewartet"


def test_der_probewert_ist_der_frostschutz() -> None:
    """10 Grad ist kein beliebiger Wert.

    Es ist genau der, der im Betrieb per Funk an ein Zimmer mit
    Untergrenze 15 oder ein Bad mit 18 geht — im Sommerbetrieb und bei der
    Fenster-Sicherheit. Die Probe fragt also den Fall, der eintreten wird,
    und nicht irgendeinen.
    """
    assert werkzeug.PROBE_WERT_C == 10
    # Und die Bytes dazu, damit der Probelauf sie zeigen kann.
    assert setpoint_bytes(10).hex() == "510064"
