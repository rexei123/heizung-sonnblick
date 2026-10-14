"""Sprint 21 A1 — die Nacht-Baender, und die Zeitumstellung darin.

``nacht_baender`` rechnet das in **Ortszeit** konfigurierte Nachtfenster in
UTC-Zeitspannen um, damit das Diagramm sie ohne eigene Zeitzonen-Rechnung
hinterlegen kann.

**Warum diese Datei existiert.** Die Umrechnung haette auch im Browser
stehen koennen — aus ``Intl.DateTimeFormat`` zurueckgerechnet, ohne
Testlauf, weil das Frontend keinen Unit-Test-Rahmen hat. Das ist die
Fehlerklasse aus §5.79: ein Zeitwert, dessen Einheit niemand prueft, und
ein Band, das zwei Stunden daneben liegt, ohne dass es auffaellt. Hier
rechnet ``zoneinfo`` — dieselbe Bibliothek wie in der Engine (§5.65,
AE-60) — und die Zeitumstellung ist gefahren, nicht gehofft.

Die beiden DST-Faelle sind echte Daten des Hauses: Europe/Vienna stellt am
**29.03.2026** vor (02:00 -> 03:00) und am **25.10.2026** zurueck
(03:00 -> 02:00), jeweils der letzte Sonntag im Monat.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from heizung.services.room_history import nacht_baender

WIEN = "Europe/Vienna"


def _spanne(band: object) -> float:
    """Dauer eines Bandes in Stunden."""
    return (band.end - band.start).total_seconds() / 3600  # type: ignore[attr-defined]


def test_ohne_konfiguration_keine_baender() -> None:
    """Kein Nachtfenster heisst kein Band — nicht ein Band ueber alles."""
    von = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert (
        nacht_baender(
            von=von, bis=von + timedelta(days=1), tz_name=WIEN, night_start=None, night_end=None
        )
        == []
    )
    assert (
        nacht_baender(
            von=von,
            bis=von + timedelta(days=1),
            tz_name=WIEN,
            night_start=time(22, 0),
            night_end=None,
        )
        == []
    )


def test_fenster_ueber_mitternacht_ergibt_ein_band_je_nacht() -> None:
    """22:00 bis 06:00, drei Tage Fenster: ein Band je Nacht.

    Gezaehlt wird mit dem Band, das **vor** dem Fenster beginnt und
    hineinreicht — es ist der Grund, warum die Schleife einen Tag frueher
    anfaengt. Ohne das fehlte am linken Rand genau die Nacht, die man
    morgens ansieht.
    """
    von = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)  # Montag Mittag
    bis = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    baender = nacht_baender(
        von=von, bis=bis, tz_name=WIEN, night_start=time(22, 0), night_end=time(6, 0)
    )

    assert len(baender) == 3, [(b.start, b.end) for b in baender]
    for b in baender:
        assert von <= b.start < b.end <= bis
        assert _spanne(b) == 8.0
    # 22:00 MESZ = 20:00 UTC
    assert baender[0].start == datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
    assert baender[0].end == datetime(2026, 10, 6, 4, 0, tzinfo=UTC)


def test_fenster_innerhalb_eines_tages_mit_zuschnitt_an_beiden_raendern() -> None:
    """01:00 bis 05:00 bleibt am selben Kalendertag — und wird an beiden
    Fensterraendern zugeschnitten.

    Diese Erwartung habe ich beim ersten Schreiben falsch gesetzt (zwei
    volle Baender), und der Lauf hat es gemeldet. Richtig ist: 01:00 MESZ
    ist 23:00 UTC des Vortags, das erste Band beginnt also **vor** dem
    Fenster und das letzte endet **danach**. Drei Baender, davon zwei
    beschnitten — der Fall, der in der Oberflaeche am rechten Rand jeden
    Tag auftritt.
    """
    von = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    bis = datetime(2026, 10, 7, 0, 0, tzinfo=UTC)
    baender = nacht_baender(
        von=von, bis=bis, tz_name=WIEN, night_start=time(1, 0), night_end=time(5, 0)
    )
    assert [_spanne(b) for b in baender] == [3.0, 4.0, 1.0]
    assert baender[0].start == von, "links beschnitten"
    assert baender[-1].end == bis, "rechts beschnitten"
    assert baender[1].start == datetime(2026, 10, 5, 23, 0, tzinfo=UTC), "01:00 MESZ"


def test_band_wird_auf_das_fenster_zugeschnitten() -> None:
    """Ein Band, das vor ``von`` beginnt, startet bei ``von``.

    Sonst zeichnet das Diagramm ueber seinen linken Rand hinaus, und die
    Flaeche steht fuer eine Zeit, die gar nicht gezeigt wird.
    """
    # Fenster beginnt mitten in der Nacht: 02:00 UTC = 04:00 MESZ.
    von = datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    bis = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    baender = nacht_baender(
        von=von, bis=bis, tz_name=WIEN, night_start=time(22, 0), night_end=time(6, 0)
    )
    assert len(baender) == 1
    assert baender[0].start == von, "zugeschnitten, nicht weggelassen"
    assert baender[0].end == datetime(2026, 10, 6, 4, 0, tzinfo=UTC)
    assert _spanne(baender[0]) == 2.0


def test_rueckstellung_im_oktober_macht_die_nacht_neun_stunden() -> None:
    """**Die Nacht vom 24. auf den 25.10.2026 ist in UTC neun Stunden lang.**

    Ortszeit 22:00 MESZ (UTC+2) = 20:00 UTC; Ortszeit 06:00 am 25.10. ist
    schon MEZ (UTC+1) = 05:00 UTC. Wer die Umrechnung mit einem festen
    Versatz baut, bekommt hier acht Stunden und ein Band, das eine Stunde
    zu frueh endet.
    """
    von = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
    bis = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    baender = nacht_baender(
        von=von, bis=bis, tz_name=WIEN, night_start=time(22, 0), night_end=time(6, 0)
    )
    assert len(baender) == 1
    assert baender[0].start == datetime(2026, 10, 24, 20, 0, tzinfo=UTC)
    assert baender[0].end == datetime(2026, 10, 25, 5, 0, tzinfo=UTC)
    assert _spanne(baender[0]) == 9.0


def test_vorstellung_im_maerz_macht_die_nacht_sieben_stunden() -> None:
    """Und die Gegenrichtung: 28. auf 29.03.2026 sind sieben Stunden.

    22:00 MEZ (UTC+1) = 21:00 UTC, 06:00 MESZ (UTC+2) = 04:00 UTC. Die
    uebersprungene Stunde (02:00-03:00 lokal) existiert nicht, und das
    Band ist entsprechend kuerzer — nicht laenger.
    """
    von = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)
    bis = datetime(2026, 3, 29, 12, 0, tzinfo=UTC)
    baender = nacht_baender(
        von=von, bis=bis, tz_name=WIEN, night_start=time(22, 0), night_end=time(6, 0)
    )
    assert len(baender) == 1
    assert baender[0].start == datetime(2026, 3, 28, 21, 0, tzinfo=UTC)
    assert baender[0].end == datetime(2026, 3, 29, 4, 0, tzinfo=UTC)
    assert _spanne(baender[0]) == 7.0


def test_sieben_tage_ergeben_sieben_baender() -> None:
    """Die Zusage fuer den 7-Tage-Bereich: je Nacht eines, keines doppelt,
    keine Ueberschneidung."""
    bis = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
    von = bis - timedelta(days=7)
    baender = nacht_baender(
        von=von, bis=bis, tz_name=WIEN, night_start=time(22, 0), night_end=time(6, 0)
    )
    assert len(baender) == 7
    # ``strict=False``: die zweite Liste ist um eins kuerzer, das ist der
    # Zweck des Paarlaufs.
    for vorher, nachher in zip(baender, baender[1:], strict=False):
        assert vorher.end < nachher.start, "Baender duerfen sich nicht beruehren"
