"""Sprint 15d T4 — Pure-Function-Tests fuer ``services/battery_health.py`` (AE-65).

Kein DB / kein I/O — reine Schwellen-Logik. Prueft die vier Zustaende an den
Grenzen und die Wirkung der konfigurierbaren ``warn_threshold``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from heizung.services.battery_health import (
    BATTERY_CRITICAL_MAX_V,
    BATTERY_CRITICAL_PCT,
    BATTERY_JUMP_V,
    BATTERY_MIN_SAMPLES,
    BATTERY_OK_MIN_V,
    DEFAULT_BATTERY_WARN_PCT,
    battery_health_state,
    battery_stage_from_volts,
    oberer_median,
)


def test_constants_match_adr_65() -> None:
    """Schutz gegen versehentliches Verschieben der AE-65-Schwellen."""
    assert BATTERY_CRITICAL_PCT == 10
    assert DEFAULT_BATTERY_WARN_PCT == 20


@pytest.mark.parametrize(
    ("pct", "expected"),
    [
        (None, "unbekannt"),  # kein Reading / Codec-NULL
        (0, "kritisch"),  # Untergrenze
        (9, "kritisch"),  # direkt unter der Kritisch-Schwelle
        (10, "warn"),  # exakt 10 ist NICHT mehr kritisch (10 < 10 falsch), aber < 20
        (15, "warn"),
        (19, "warn"),  # direkt unter der Warn-Schwelle
        (20, "ok"),  # exakt an der Warn-Schwelle ist ok (>= 20)
        (50, "ok"),
        (100, "ok"),  # Codec-Saettigung
    ],
)
def test_battery_health_state_default_threshold(pct: int | None, expected: str) -> None:
    """Default-Schwelle 20: ok>=20, warn 10..19, kritisch <10, None unbekannt."""
    assert battery_health_state(pct, DEFAULT_BATTERY_WARN_PCT) == expected


def test_warn_threshold_shifts_the_warn_boundary() -> None:
    """Anderer Config-Wert verschiebt die warn/ok-Grenze (AE-65)."""
    # Hoehere Schwelle (25): 24 ist jetzt warn, 25 ist ok.
    assert battery_health_state(24, 25) == "warn"
    assert battery_health_state(25, 25) == "ok"
    # Niedrigere Schwelle (15): 14 ist warn, 15 ist ok.
    assert battery_health_state(14, 15) == "warn"
    assert battery_health_state(15, 15) == "ok"


def test_kritisch_is_absolute_and_beats_warn() -> None:
    """``kritisch`` (< 10) schlaegt ``warn`` auch bei sehr kleiner Schwelle.

    Selbst wenn ``warn_threshold`` <= 10 gesetzt waere, bleibt < 10 kritisch —
    die Reihenfolge im Mapping ist verbindlich.
    """
    assert battery_health_state(5, 5) == "kritisch"
    assert battery_health_state(9, 10) == "kritisch"
    assert battery_health_state(8, 8) == "kritisch"


# ---------------------------------------------------------------------------
# Sprint 20 (AE-69): Stufen ueber die Spannung
# ---------------------------------------------------------------------------


def test_spannungs_konstanten_entsprechen_ae_69() -> None:
    """Schutz gegen versehentliches Verschieben der AE-69-Schwellen.

    Die Werte stammen aus der Freigabe vom 30.09.2026 und sind gegen die
    MClimate-Spec geprueft (Betriebsbereich 2.7-3.6 VDC, Wechselempfehlung
    < 2.8 V, ``docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md:2539``).
    """
    assert Decimal("3.0") == BATTERY_OK_MIN_V
    assert Decimal("2.8") == BATTERY_CRITICAL_MAX_V
    assert BATTERY_MIN_SAMPLES == 3
    assert Decimal("0.3") == BATTERY_JUMP_V


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        (None, "unbekannt"),  # Mindest-Stichprobe nicht erreicht
        ("2.0", "kritisch"),  # unterster Codec-Schritt (Nibble 0)
        ("2.6", "kritisch"),
        ("2.7", "kritisch"),  # Spec-Untergrenze des Geraetebetriebs
        ("2.8", "kritisch"),  # Grenze inklusiv: Hersteller sagt "< 2.8 wechseln"
        ("2.9", "warn"),  # der einzige schwach-Schritt
        ("3.0", "ok"),  # Grenze inklusiv
        ("3.1", "ok"),  # frische Alkaline (Geraet 101)
        ("3.2", "ok"),
        ("3.5", "ok"),  # Codec-Saettigung, frische Lithium (Geraet 002)
    ],
)
def test_battery_stage_from_volts_jeder_codec_schritt(volts: str | None, expected: str) -> None:
    """Erwartungswerte aus der Spezifikation, nicht aus einem Lauf (§5.79)."""
    v = None if volts is None else Decimal(volts)
    assert battery_stage_from_volts(v) == expected


def test_alle_16_codec_schritte_haben_eine_stufe() -> None:
    """Kein Nibble-Wert faellt durch — Vollstaendigkeit statt Stichprobe.

    Der Codec kann nur diese 16 Werte liefern (``V = 2 + nibble * 0.1``).
    Wer eine Grenze verschiebt, sieht hier sofort, welche Schritte kippen.
    """
    stufen = {
        str(Decimal("2.0") + Decimal(n) / 10): battery_stage_from_volts(
            Decimal("2.0") + Decimal(n) / 10
        )
        for n in range(16)
    }
    assert stufen == {
        "2.0": "kritisch",
        "2.1": "kritisch",
        "2.2": "kritisch",
        "2.3": "kritisch",
        "2.4": "kritisch",
        "2.5": "kritisch",
        "2.6": "kritisch",
        "2.7": "kritisch",
        "2.8": "kritisch",
        "2.9": "warn",
        "3.0": "ok",
        "3.1": "ok",
        "3.2": "ok",
        "3.3": "ok",
        "3.4": "ok",
        "3.5": "ok",
    }


def test_schwach_ist_genau_ein_rasterschritt_breit() -> None:
    """Die Arithmetik, die die Stufen-Wahl begrenzt.

    Zwischen ``kritisch <= 2.8`` und ``ok >= 3.0`` liegt bei 0.1-V-Raster
    genau ein Wert. Eine vierte Stufe ist deshalb nicht einfuehrbar, ohne
    die Grenzen auseinanderzuziehen — und nach oben ist bei 3.1 V (frische
    Alkaline) Schluss, nach unten bei 2.7 V (Geraete-Minimum).

    Der Test ist eine Rechnung, keine Beobachtung: er faellt, sobald die
    Grenzen so verschoben werden, dass "schwach" mehr oder weniger als
    einen Schritt umfasst — dann ist die Begruendung in AE-69 nachzuziehen.
    """
    raster = [Decimal("2.0") + Decimal(n) / 10 for n in range(16)]
    schwach = [v for v in raster if battery_stage_from_volts(v) == "warn"]
    assert schwach == [Decimal("2.9")]


def test_volle_batterie_ist_nie_leer() -> None:
    """Die Anforderung des Hotels, als Test.

    Referenzwerte aus dem Feldtest 28.-30.09.2026: Geraet 101 frische
    Alkaline 3.1 V, Geraet 002 Lithium 3.5 V. Beide muessen "ok" sein —
    unter der alten Prozent-Skala waren sie das auch (65 % / 100 %), unter
    der ersten Schwellen-Variante (OK >= 3.1) waere 3.1 V die Grenze selbst
    gewesen, also ein Rasterschritt vom Daueralarm entfernt.
    """
    assert battery_stage_from_volts(Decimal("3.1")) == "ok"
    assert battery_stage_from_volts(Decimal("3.5")) == "ok"


def test_kritisch_braucht_2_8_volt_oder_weniger() -> None:
    """Der Befund zu Geraet 001, als Test festgehalten.

    Gemeldet wurde "001 mit Alkaline stand auf kritisch" bei 3.0 V. Das ist
    mit keiner der beiden Skalen vereinbar: 3.0 V war unter der Prozent-
    Kennlinie 50 % und damit "ok", und ist nach AE-69 ebenfalls "ok". Die
    Stufe "kritisch" setzt <= 2.8 V voraus.

    Die Erklaerung ist der Lastabfall: 001 hatte ein klemmendes Ventil mit
    ``lowMotorConsumption``, und die Prozent-Anzeige stammte immer aus dem
    **letzten** Frame. Genau dagegen wirkt der 24-h-Median (T3).
    """
    assert battery_stage_from_volts(Decimal("3.0")) == "ok"
    assert battery_stage_from_volts(Decimal("2.9")) == "warn"
    assert battery_stage_from_volts(Decimal("2.8")) == "kritisch"


# ---------------------------------------------------------------------------
# Sprint 20 T3 — oberer_median (reine Funktion, ohne DB)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("werte", "erwartet"),
    [
        # Ungerade: der echte Median.
        (["2.9"], "2.9"),
        (["2.8", "2.9", "3.0"], "2.9"),
        (["3.0", "2.8", "2.9"], "2.9"),  # Eingabe-Reihenfolge ist irrelevant
        (["2.7", "2.8", "2.9", "3.0", "3.1"], "2.9"),
        # Gerade: der HOEHERE der beiden mittleren.
        (["2.8", "2.9"], "2.9"),
        (["2.8", "2.9", "3.0", "3.1"], "3.0"),
        (["2.6", "3.5"], "3.5"),
        # Lastabfall am Rand aendert den Median nicht.
        (["3.0", "3.0", "3.0", "2.6"], "3.0"),
        (["3.0"] * 23 + ["2.6"], "3.0"),
    ],
)
def test_oberer_median(werte: list[str], erwartet: str) -> None:
    """Erwartungswerte aus der Definition, nicht aus einem Lauf (§5.79)."""
    assert oberer_median([Decimal(v) for v in werte]) == Decimal(erwartet)


def test_oberer_median_bei_gerader_zahl_ist_nie_der_untere() -> None:
    """Die Richtung der Rundungskante, als Eigenschaft geprueft.

    Fuer jede gerade Stichprobe gilt: das Ergebnis ist der obere der beiden
    mittleren Werte. Das ist die Vorgabe "volle Batterie nie als leer" an
    der Stelle, an der sie ueberhaupt wirksam wird — bei ungerader
    Stichprobe gibt es keine Wahl.
    """
    for n in range(1, 13):
        werte = [Decimal("2.0") + Decimal(i) / 10 for i in range(2 * n)]
        sortiert = sorted(werte)
        unterer = sortiert[n - 1]
        oberer = sortiert[n]
        assert oberer_median(werte) == oberer
        assert oberer_median(werte) != unterer


def test_oberer_median_leere_eingabe_wirft() -> None:
    """Die Mindest-Stichprobe wird beim Aufrufer geprueft, nicht hier.

    Ein stiller Rueckgabewert (0, None) waere die gefaehrlichere Variante:
    0.0 V wuerde als "kritisch" gelesen, obwohl gar nichts gemessen wurde.
    """
    with pytest.raises(IndexError):
        oberer_median([])
