"""Paketverlust aus Luecken im Frame-Zaehler (02.11.2026).

Die Rechnung ist eine reine Funktion ueber eine **zeitlich geordnete**
Reihe von Zaehlern — keine Datenbank, keine Uhr, also auch keine
Zeitbombe (§5.59).

Der Fall, der sie noetig gemacht hat, steht als eigener Test: Relais 109
hatte am 01.11.2026 vor einem Neustart ``fCnt`` 8 und danach ``fCnt``
13 — vier Frames fehlten, und das sind rund 30 %.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from heizung.services.paketverlust import rechne


def test_lueckenlose_reihe_hat_keinen_verlust() -> None:
    v = rechne([1, 2, 3, 4, 5], stunden=24)
    assert v.empfangen == 5
    assert v.erwartet == 5
    assert v.verloren == 0
    assert v.anteil == Decimal("0.0")
    assert v.neustarts == 0


def test_der_fall_vom_relais_109() -> None:
    """**Der Anlass.** Vier Frames zwischen 8 und 13 sind verloren.

    Gemessen hat das der Betreiber am 01.11.2026 von Hand aus den
    ChirpStack-Ereignissen: letzter Uplink vor dem Neustart ``fCnt`` 8,
    naechster ``fCnt`` 13. Dass die Zahl rund 30 % ergibt, ist der Grund
    fuer die ganze Anzeige.
    """
    v = rechne([5, 6, 7, 8, 13, 14], stunden=24)
    assert v.empfangen == 6
    assert v.erwartet == 10, "5 bis 14 sind zehn Frames"
    assert v.verloren == 4
    assert v.anteil == Decimal("40.0")


def test_eine_ruecksetzung_ist_kein_verlust() -> None:
    """Ein Neustart setzt den Zaehler zurueck (§5.71).

    Ohne die Teilung waere die Spanne 1 bis 4000 — eine Luecke von
    knapp viertausend Frames, obwohl nichts verloren ging.
    """
    v = rechne([3998, 3999, 4000, 0, 1, 2], stunden=24)
    assert v.neustarts == 1
    assert v.empfangen == 6
    assert v.erwartet == 6
    assert v.verloren == 0
    assert v.anteil == Decimal("0.0")


def test_die_schwelle_aus_5_71_gilt_hier_nicht() -> None:
    """``is_reboot_frame`` verlangt zusaetzlich einen **kleinen** Zaehler.

    Das ist dort richtig — es geht um die Uebernahme eines
    Drehring-Werts, und die soll vorsichtig sein. Hier wird gerechnet:
    jedes Sinken ist eine Ruecksetzung, denn ein Zaehler, der hochzaehlt,
    kann nicht sinken. Mit der Schwelle waere dieser Fall eine Luecke von
    knapp dreitausend Frames.
    """
    v = rechne([4000, 4001, 1200, 1201], stunden=24)
    assert v.neustarts == 1
    assert v.verloren == 0


def test_mehrfachempfang_ist_kein_verlust() -> None:
    """Derselbe Zaehler zweimal: zwei Gateways, ein Frame."""
    v = rechne([7, 8, 8, 9], stunden=24)
    assert v.doppelt == 1
    assert v.empfangen == 3
    assert v.erwartet == 3
    assert v.verloren == 0


def test_ein_einzelner_frame_hat_keinen_anteil() -> None:
    """``None`` ist nicht 0 %.

    Bei einem Frame gibt es keine Luecke, die man sehen koennte. Eine
    Null davor waere eine Behauptung ueber einen Funk, der nicht
    gemessen wurde — dieselbe Unterscheidung wie bei der Batterie, wo
    unter drei Messwerten „unbekannt" steht und nicht „in Ordnung"
    (§5.73).
    """
    assert rechne([5], stunden=24).anteil is None
    assert rechne([], stunden=24).anteil is None
    assert rechne([None, None], stunden=24).anteil is None


def test_zeilen_ohne_zaehler_gehen_nicht_in_die_rechnung() -> None:
    """``fcnt`` ist nullable — der Bestandspfad des Subscribers.

    Eine solche Zeile als Empfang zu zaehlen wuerde den Verlust zu
    niedrig ausweisen, sie als Luecke zu zaehlen zu hoch. Sie wird
    deshalb gezaehlt und ausgewiesen, aber nicht gerechnet.
    """
    v = rechne([1, None, 2, None, 3], stunden=24)
    assert v.ohne_zaehler == 2
    assert v.empfangen == 3
    assert v.erwartet == 3
    assert v.verloren == 0


def test_verlust_vor_und_nach_einer_ruecksetzung_zaehlt_zusammen() -> None:
    """Beide Teile werden getrennt gerechnet und dann summiert.

    Je Teil eine Spanne — sonst wuerde die Ruecksetzung die Luecke
    davor verschlucken.
    """
    v = rechne([1, 4, 0, 3], stunden=24)
    assert v.neustarts == 1
    assert v.empfangen == 4
    assert v.erwartet == 8, "1 bis 4 sind vier, 0 bis 3 sind vier"
    assert v.verloren == 4
    assert v.anteil == Decimal("50.0")


def test_der_anteil_wird_auf_eine_stelle_gerundet() -> None:
    """Zwei Stellen waeren Scheinpraezision bei dreissig Frames."""
    v = rechne([1, 3, 4, 5, 6, 7, 8, 9, 10], stunden=24)
    assert v.erwartet == 10
    assert v.verloren == 1
    assert v.anteil == Decimal("10.0")


# ---------------------------------------------------------------------------
# Das Werkzeug: ``--seit`` ist Ortszeit
# ---------------------------------------------------------------------------


def test_seit_wird_als_ortszeit_gelesen() -> None:
    """Der Mensch tippt die Uhrzeit, die an seiner Wand steht.

    Das Relais kam am 02.11.2026 um **07:05 Ortszeit** in die Dose. Als
    UTC gelesen waere das Fenster im Winter eine Stunde zu lang und im
    Sommer zwei — dieselbe Falle wie in §5.65, nur am Eingang des
    Werkzeugs statt im Regler.
    """
    from heizung.scripts.funkqualitaet import _parse_seit

    gelesen = _parse_seit("2026-11-02 07:05")
    assert gelesen == datetime(2026, 11, 2, 6, 5, tzinfo=UTC), "07:05 MEZ sind 06:05 UTC"

    # Im Sommer sind es zwei Stunden. Der Test haelt fest, dass die
    # Umrechnung ueber ZoneInfo laeuft und keine feste Zahl ist.
    assert _parse_seit("2026-07-02 07:05") == datetime(2026, 7, 2, 5, 5, tzinfo=UTC)


def test_eine_angegebene_zone_wird_respektiert() -> None:
    """Wer ``+00:00`` tippt, meint UTC und bekommt UTC."""
    from heizung.scripts.funkqualitaet import _parse_seit

    assert _parse_seit("2026-11-02T07:05+00:00") == datetime(2026, 11, 2, 7, 5, tzinfo=UTC)
