"""Pure-Function-Tests fuer ``services/battery_health.py`` (AE-65 / AE-72 / AE-73).

Kein DB / kein I/O — reine Schwellen-Logik und die Median-Auswahl. Die
Bewertung ueber das 24-h-Fenster braucht Postgres und steht in
``test_battery_voltage_db.py``.

Sprint 20 hat die Prozent-Variante (``battery_health_state``) samt ihrer
konfigurierbaren Schwelle entfernt; die Tests dazu sind mit ihr gegangen.

Sprint 20b (AE-73) hat die beiden Spannungs-Grenzen aus dem Code in die
Settings verschoben und nach unten gesetzt (2.9 / 2.6 statt 3.0 / 2.8).
Die Tests hier pruefen deshalb **zwei** Dinge getrennt:

* die **Abbildung** Spannung -> Stufe, gegen explizit uebergebene Grenzen —
  sie muss fuer jede Konfiguration stimmen, nicht nur fuer die Vorgabe;
* die **Vorgabewerte** selbst, als Schutz gegen versehentliches Verschieben.

Dass die Abbildung gegen uebergebene und nicht gegen gelesene Grenzen
geprueft wird, ist der Punkt: ein Test, der die Settings liest, ist auch
dann gruen, wenn der Vergleich an der falschen Grenze haengt.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from heizung.config import Settings, get_settings
from heizung.services.battery_health import (
    BATTERY_JUMP_V,
    BATTERY_MIN_SAMPLES,
    BatterySchwellen,
    battery_schwellen,
    battery_stage_from_volts,
    oberer_median,
)

# Die Vorgabe aus AE-73, als Testkonstante. Steht hier ausgeschrieben und
# wird NICHT aus den Settings gelesen: dieser Wert ist die Erwartung, gegen
# die der Settings-Default geprueft wird (§5.79 — Erwartungswert aus der
# Spezifikation, nicht aus dem Lauf).
AE73 = BatterySchwellen(ok_min_v=Decimal("2.9"), critical_max_v=Decimal("2.6"))

# Die Vorgabe aus AE-72, also der Stand vor Sprint 20b. Wird gebraucht, um
# zu belegen, dass die Abbildung von den uebergebenen Grenzen abhaengt und
# nicht von einer eingebauten Zahl.
AE72 = BatterySchwellen(ok_min_v=Decimal("3.0"), critical_max_v=Decimal("2.8"))

# ---------------------------------------------------------------------------
# Sprint 20 (AE-72): Stufen ueber die Spannung
# ---------------------------------------------------------------------------


def test_vorgabe_schwellen_entsprechen_ae_73() -> None:
    """Schutz gegen versehentliches Verschieben der Vorgabewerte.

    Die Werte stammen aus der Freigabe vom 01.10.2026 (AE-73) und liegen
    **unter** der Hersteller-Wechselempfehlung von "< 2.8 V": die Zelle
    wird bewusst bis an den Ausfall ausgenutzt, weil das Haus thermisch
    saniert ist und jeder Wechsel einen Gang kostet.

    Dass ``kritisch <= 2.6 V`` unterhalb der Spec-Untergrenze von 2.7 VDC
    liegt, ist Teil der Entscheidung und kein Versehen — AE-73 nennt die
    Folge: bei "Tauschen" kann das Ventil schon stehen.
    """
    assert battery_schwellen() == AE73
    assert BATTERY_MIN_SAMPLES == 3
    assert Decimal("0.3") == BATTERY_JUMP_V


def test_schwellen_kommen_aus_den_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der Punkt von AE-73: die Grenzen sind ohne Code-Aenderung verstellbar.

    Gesetzt werden die **alten** AE-72-Werte. Damit prueft der Test nicht
    nur, dass irgendein Wert ankommt, sondern dass der gelesene Wert die
    Abbildung tatsaechlich verschiebt: 2.9 V ist unter AE-73 "ok" und unter
    AE-72 "warn".
    """
    monkeypatch.setenv("BATTERY_OK_MIN_V", "3.0")
    monkeypatch.setenv("BATTERY_CRITICAL_MAX_V", "2.8")
    get_settings.cache_clear()
    try:
        schwellen = battery_schwellen()
        assert schwellen == AE72
        assert battery_stage_from_volts(Decimal("2.9"), schwellen) == "warn"
        assert battery_stage_from_volts(Decimal("2.9"), AE73) == "ok"
    finally:
        get_settings.cache_clear()


def test_schwellen_sind_decimal_nicht_float(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der env-String wird exakt gelesen, nicht ueber ``float``.

    2.9 hat in IEEE-754 keine exakte Darstellung, und der Vergleich laeuft
    genau auf diesem Rasterpunkt. Die Gleichheit gegen ``Decimal("2.9")``
    ist deshalb Teil der Zusicherung, nicht Kosmetik: die Grenze ist
    inklusiv, also entscheidet exakt dieser Wert zwischen "ok" und "warn".
    """
    monkeypatch.setenv("BATTERY_OK_MIN_V", "2.9")
    get_settings.cache_clear()
    try:
        schwellen = battery_schwellen()
        assert isinstance(schwellen.ok_min_v, Decimal)
        assert schwellen.ok_min_v == Decimal("2.9")
        assert battery_stage_from_volts(Decimal("2.9"), schwellen) == "ok"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("ok_min", "critical_max"),
    [
        ("2.9", "2.9"),  # gleich: der Grenzwert waere kritisch UND ok
        ("2.9", "3.0"),  # vertauscht: keine Stufe "schwach", alles kippt
        ("2.6", "2.9"),  # die AE-73-Werte in der falschen Reihenfolge
    ],
)
def test_settings_lehnen_ungeordnete_schwellen_ab(
    monkeypatch: pytest.MonkeyPatch, ok_min: str, critical_max: str
) -> None:
    """Ein Tippfehler in der ``.env`` ist ein Start-Fehler, keine Warnung.

    Ohne diese Pruefung entscheidet die Reihenfolge der Vergleiche in
    ``battery_stage_from_volts``, was bei ``critical_max >= ok_min``
    herauskommt — die Konfiguration haette dann eine Wirkung, die niemand
    aus ihr ablesen kann.

    Der Fehler faellt beim Hochfahren und steht im Container-Log. Das ist
    die unbequemere, aber richtige Variante: eine Batterie-Anzeige, die
    nach einem Tippfehler stumm das Gegenteil meldet, ist schlimmer als
    eine API, die nicht startet.
    """
    monkeypatch.setenv("BATTERY_OK_MIN_V", ok_min)
    monkeypatch.setenv("BATTERY_CRITICAL_MAX_V", critical_max)
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError, match="BATTERY_CRITICAL_MAX_V"):
            Settings()  # type: ignore[call-arg]
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        ("3.0", "ok"),
        ("2.9", "ok"),  # Grenze inklusiv
        ("2.8", "warn"),
        ("2.7", "warn"),  # Spec-Untergrenze des Geraetebetriebs
        ("2.6", "kritisch"),  # Grenze inklusiv
        ("2.5", "kritisch"),
    ],
)
def test_grenzwerte_der_freigabe(volts: str, expected: str) -> None:
    """Die sechs Werte aus dem Auftrag vom 01.10.2026, einzeln.

    Erwartungswerte aus der Freigabe, nicht aus einem Lauf (§5.79).
    """
    assert battery_stage_from_volts(Decimal(volts), AE73) == expected


@pytest.mark.parametrize(
    ("volts", "expected"),
    [
        (None, "unbekannt"),  # Mindest-Stichprobe nicht erreicht
        ("2.0", "kritisch"),  # unterster Codec-Schritt (Nibble 0)
        ("2.5", "kritisch"),
        ("2.6", "kritisch"),  # Grenze inklusiv
        ("2.7", "warn"),  # Spec-Untergrenze des Geraetebetriebs
        ("2.8", "warn"),  # Hersteller-Wechselempfehlung "< 2.8 V"
        ("2.9", "ok"),  # Grenze inklusiv
        ("3.0", "ok"),
        ("3.1", "ok"),  # frische Alkaline (Geraet 101)
        ("3.2", "ok"),
        ("3.5", "ok"),  # Codec-Saettigung, frische Lithium (Geraet 002)
    ],
)
def test_battery_stage_from_volts_jeder_codec_schritt(volts: str | None, expected: str) -> None:
    """Erwartungswerte aus der Spezifikation, nicht aus einem Lauf (§5.79)."""
    v = None if volts is None else Decimal(volts)
    assert battery_stage_from_volts(v, AE73) == expected


def test_alle_16_codec_schritte_haben_eine_stufe() -> None:
    """Kein Nibble-Wert faellt durch — Vollstaendigkeit statt Stichprobe.

    Der Codec kann nur diese 16 Werte liefern (``V = 2 + nibble * 0.1``).
    Wer eine Grenze verschiebt, sieht hier sofort, welche Schritte kippen.

    Geprueft gegen die AE-73-Vorgabe. Die Verschiebung gegenueber AE-72 ist
    an dieser Tabelle am besten zu sehen: 2.7 und 2.8 V waren "kritisch"
    und sind jetzt "warn", 2.9 V war "warn" und ist jetzt "ok".
    """
    stufen = {
        str(Decimal("2.0") + Decimal(n) / 10): battery_stage_from_volts(
            Decimal("2.0") + Decimal(n) / 10, AE73
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
        "2.7": "warn",
        "2.8": "warn",
        "2.9": "ok",
        "3.0": "ok",
        "3.1": "ok",
        "3.2": "ok",
        "3.3": "ok",
        "3.4": "ok",
        "3.5": "ok",
    }


def test_schwach_ist_zwei_rasterschritte_breit() -> None:
    """Die Arithmetik hinter der Verschiebung aus AE-73.

    Zwischen ``kritisch <= 2.6`` und ``ok >= 2.9`` liegen bei 0.1-V-Raster
    genau zwei Werte. Unter AE-72 (2.8 / 3.0) war es **einer** — "schwach"
    war eine Durchgangsstufe, die ein Geraet in einem einzigen
    Rasterschritt durchlaufen konnte.

    Das ist der praktische Gewinn der Verschiebung und nicht nur eine
    Zahlenaenderung: bei einem Uplink alle zehn Minuten sind zwei Schritte
    ein echtes Vorwarnfenster, in dem der Hausmeister einen Gang planen
    kann, statt ihn zu machen.

    Der Test ist eine Rechnung, keine Beobachtung: er faellt, sobald die
    Vorgabe so verschoben wird, dass "schwach" mehr oder weniger als zwei
    Schritte umfasst — dann ist die Begruendung in AE-73 nachzuziehen.
    """
    raster = [Decimal("2.0") + Decimal(n) / 10 for n in range(16)]
    schwach = [v for v in raster if battery_stage_from_volts(v, AE73) == "warn"]
    assert schwach == [Decimal("2.7"), Decimal("2.8")]

    # Gegenprobe gegen den Stand vor Sprint 20b: dort war es einer.
    schwach_ae72 = [v for v in raster if battery_stage_from_volts(v, AE72) == "warn"]
    assert schwach_ae72 == [Decimal("2.9")]


def test_volle_batterie_ist_nie_leer() -> None:
    """Die Anforderung des Hotels, als Test.

    Referenzwerte aus dem Feldtest 28.-30.09.2026: Geraet 101 frische
    Alkaline 3.1 V, Geraet 002 Lithium 3.5 V. Beide muessen "ok" sein —
    unter der alten Prozent-Skala waren sie das auch (65 % / 100 %), unter
    der ersten Schwellen-Variante (OK >= 3.1) waere 3.1 V die Grenze selbst
    gewesen, also ein Rasterschritt vom Daueralarm entfernt.

    Die Anforderung ist unter AE-73 mit mehr Abstand erfuellt als unter
    AE-72: zwischen 2.9 V und dem frischen Alkaline-Zustand liegen jetzt
    zwei Rasterschritte statt einem.
    """
    assert battery_stage_from_volts(Decimal("3.1"), AE73) == "ok"
    assert battery_stage_from_volts(Decimal("3.5"), AE73) == "ok"


def test_befund_geraet_001_bleibt_ok() -> None:
    """Der Befund zu Geraet 001, als Test festgehalten.

    Gemeldet wurde "001 mit Alkaline stand auf kritisch" bei 3.0 V. Das ist
    mit keiner Skala vereinbar: 3.0 V war unter der Prozent-Kennlinie 50 %
    und damit "ok", ist nach AE-72 "ok" und nach AE-73 erst recht.

    Die Erklaerung ist der Lastabfall: 001 hatte ein klemmendes Ventil mit
    ``lowMotorConsumption``, und die Prozent-Anzeige stammte immer aus dem
    **letzten** Frame. Genau dagegen wirkt der 24-h-Median (T3).

    Unter AE-73 braucht "kritisch" <= 2.6 V. Ein Lastabfall auf 2.6 V oder
    tiefer bleibt moeglich — er wird nicht durch die Schwelle abgefangen,
    sondern durch den Median.
    """
    assert battery_stage_from_volts(Decimal("3.0"), AE73) == "ok"
    assert battery_stage_from_volts(Decimal("2.7"), AE73) == "warn"
    assert battery_stage_from_volts(Decimal("2.6"), AE73) == "kritisch"


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
