"""Pure-Function-Tests fuer den Zweipunktregler (Sprint 24, Paket D).

Kein DB, keine Wanduhr: ``now`` ist Pflicht-Argument des Reglers, und
die Zeiten sind absolut. Deshalb gibt es hier auch keine Zeitbombe
(§5.59) — der Regler liest nie ``datetime.now``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from heizung.rules.zweipunkt import (
    Entscheidung,
    Schaltbefehl,
    Zonenzustand,
    ZweipunktSchwellen,
    einschalt_versatz,
    entscheide,
)

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)

#: Die Vorgaben aus den Settings, hier als Literale. Bewusst **nicht**
#: aus ``get_settings()`` gelesen: dieser Test prueft den Regler, nicht
#: die Konfiguration. Waeren die Werte importiert, wuerde ein geaenderter
#: Vorgabewert die Erwartungen stillschweigend mitverschieben, und der
#: Test pruefte nur noch, dass sich nichts geaendert hat (§5.79).
SCHWELLEN = ZweipunktSchwellen(
    ein_delta_k=Decimal("0.5"),
    aus_delta_k=Decimal("0.3"),
    min_lauf=timedelta(minutes=10),
    min_pause=timedelta(minutes=10),
)

#: Ein Zustand, dessen Mindestzeit sicher abgelaufen ist.
LANG_AUS = Zonenzustand(ein=False, seit=NOW - timedelta(hours=1))
LANG_EIN = Zonenzustand(ein=True, seit=NOW - timedelta(hours=1))


def ent(
    ist: Decimal | None,
    zustand: Zonenzustand,
    *,
    soll: Decimal = Decimal("21.0"),
    veraltet: bool = False,
    now: datetime = NOW,
) -> Entscheidung:
    return entscheide(
        ist=ist,
        soll=soll,
        zustand=zustand,
        schwellen=SCHWELLEN,
        now=now,
        fuehler_veraltet=veraltet,
    )


# ---------------------------------------------------------------------------
# Die beiden Schwellen
# ---------------------------------------------------------------------------


def test_unter_der_ein_schwelle_wird_eingeschaltet() -> None:
    """Soll 21,0 - 0,5 = 20,5. Bei 20,4 muss es einschalten."""
    e = ent(Decimal("20.4"), LANG_AUS)
    assert e.befehl is Schaltbefehl.EIN
    assert e.grund == "unter_ein_schwelle"


def test_genau_auf_der_ein_schwelle_wird_eingeschaltet() -> None:
    """20,5 ist der Rand, und er gehoert zum EIN.

    ``ist <= soll - ein_delta`` ist mit Absicht einschliesslich: ein
    Rand, der zu keiner Seite gehoert, waere ein Totband von einem
    Hundertstel Grad, in dem niemand erklaeren kann, warum nichts
    passiert.
    """
    assert ent(Decimal("20.5"), LANG_AUS).befehl is Schaltbefehl.EIN


def test_knapp_ueber_der_ein_schwelle_bleibt_aus() -> None:
    """20,51 liegt im Totband — kein Einschalten."""
    e = ent(Decimal("20.51"), LANG_AUS)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "im_totband"


def test_ueber_der_aus_schwelle_wird_ausgeschaltet() -> None:
    """Soll 21,0 + 0,3 = 21,3. Bei 21,4 muss es ausschalten."""
    e = ent(Decimal("21.4"), LANG_EIN)
    assert e.befehl is Schaltbefehl.AUS
    assert e.grund == "ueber_aus_schwelle"


def test_genau_auf_der_aus_schwelle_wird_ausgeschaltet() -> None:
    assert ent(Decimal("21.3"), LANG_EIN).befehl is Schaltbefehl.AUS


def test_knapp_unter_der_aus_schwelle_bleibt_ein() -> None:
    e = ent(Decimal("21.29"), LANG_EIN)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "im_totband"


def test_das_totband_ist_asymmetrisch() -> None:
    """0,5 K nach unten, 0,3 K nach oben — und das ist Absicht.

    Dieser Test haelt die **Asymmetrie** fest, nicht die Zahlen. Wer sie
    zu einem gemeinsamen Delta vereinfacht, laesst ihn fallen und muss
    die Begruendung in ``config.py`` lesen, bevor er ihn anpasst.
    """
    soll = Decimal("21.0")
    assert ent(soll - Decimal("0.4"), LANG_AUS).befehl is Schaltbefehl.UNVERAENDERT
    assert ent(soll - Decimal("0.5"), LANG_AUS).befehl is Schaltbefehl.EIN
    assert ent(soll + Decimal("0.2"), LANG_EIN).befehl is Schaltbefehl.UNVERAENDERT
    assert ent(soll + Decimal("0.3"), LANG_EIN).befehl is Schaltbefehl.AUS


def test_im_totband_bleibt_jeder_zustand_wie_er_ist() -> None:
    """Das Totband haelt **beide** Zustaende — es ist keine Richtung."""
    assert ent(Decimal("21.0"), LANG_EIN).befehl is Schaltbefehl.UNVERAENDERT
    assert ent(Decimal("21.0"), LANG_AUS).befehl is Schaltbefehl.UNVERAENDERT


def test_kein_doppelter_befehl_bei_erfuelltem_zustand() -> None:
    """Unter der Schwelle **und** schon ein: kein zweiter Downlink.

    Jeder Downlink ist Sendezeit (§0 S4). Die Entscheidung ist trotzdem
    nicht ``im_totband`` — der Grund sagt, dass die Lage erkannt wurde.
    """
    assert ent(Decimal("19.0"), LANG_EIN).grund == "bereits_ein"
    assert ent(Decimal("25.0"), LANG_AUS).grund == "bereits_aus"


# ---------------------------------------------------------------------------
# Mindestlaufzeit und Mindestpause
# ---------------------------------------------------------------------------


def test_mindestlaufzeit_verhindert_das_ausschalten() -> None:
    """Seit 9 min ein, Ist weit ueber der Schwelle: trotzdem kein AUS."""
    frisch_ein = Zonenzustand(ein=True, seit=NOW - timedelta(minutes=9))
    e = ent(Decimal("25.0"), frisch_ein)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "min_lauf_600s"


def test_nach_der_mindestlaufzeit_wird_ausgeschaltet() -> None:
    """Genau 10 min sind erreicht — ``<`` ist ausschliesslich."""
    gerade_reif = Zonenzustand(ein=True, seit=NOW - timedelta(minutes=10))
    assert ent(Decimal("25.0"), gerade_reif).befehl is Schaltbefehl.AUS


def test_mindestpause_verhindert_das_einschalten() -> None:
    """Seit 9 min aus, Zone zu kalt: trotzdem kein EIN."""
    frisch_aus = Zonenzustand(ein=False, seit=NOW - timedelta(minutes=9))
    e = ent(Decimal("15.0"), frisch_aus)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "min_pause_600s"


def test_nach_der_mindestpause_wird_eingeschaltet() -> None:
    gerade_reif = Zonenzustand(ein=False, seit=NOW - timedelta(minutes=10))
    assert ent(Decimal("15.0"), gerade_reif).befehl is Schaltbefehl.EIN


def test_mindestzeit_schlaegt_die_schwelle() -> None:
    """Der Vorrang, ausdruecklich.

    Ohne ihn taktet ein Relais an einer traegen Zone im Minutenabstand.
    Dieser Test ist die Mutationsprobe M5 in Testform: wird die
    Mindestlaufzeit entfernt, faellt er.
    """
    frisch_ein = Zonenzustand(ein=True, seit=NOW - timedelta(minutes=1))
    assert ent(Decimal("30.0"), frisch_ein).befehl is Schaltbefehl.UNVERAENDERT


def test_ohne_vorzustand_greift_keine_mindestzeit() -> None:
    """``seit = None`` heisst noch nie geschaltet — dann gibt es nichts
    zu schuetzen, und der erste Befehl darf sofort gehen."""
    nie = Zonenzustand(ein=False, seit=None)
    assert ent(Decimal("15.0"), nie).befehl is Schaltbefehl.EIN


# ---------------------------------------------------------------------------
# Zwangs-AUS (S5)
# ---------------------------------------------------------------------------


def test_fehlender_istwert_schaltet_aus() -> None:
    e = ent(None, LANG_EIN)
    assert e.befehl is Schaltbefehl.AUS
    assert e.grund == "kein_istwert"


def test_veralteter_fuehler_schaltet_aus() -> None:
    e = ent(Decimal("15.0"), LANG_EIN, veraltet=True)
    assert e.befehl is Schaltbefehl.AUS
    assert e.grund == "fuehler_veraltet"


def test_zwangs_aus_bricht_die_mindestlaufzeit() -> None:
    """**Die Zusicherung S5, und sie ist der Grund fuer die Ausnahme.**

    Seit einer Minute ein, Fuehler weg. Wenn die Mindestlaufzeit hier
    gewinnen wuerde, waere „Fuehler veraltet -> Relais aus" bis zu neun
    Minuten lang unwahr. Eine Sicherheitsaussage mit einem
    Neun-Minuten-Loch ist keine.

    Das ist die Mutationsprobe M4 in Testform.
    """
    frisch_ein = Zonenzustand(ein=True, seit=NOW - timedelta(minutes=1))
    assert ent(None, frisch_ein).befehl is Schaltbefehl.AUS
    assert ent(Decimal("15.0"), frisch_ein, veraltet=True).befehl is Schaltbefehl.AUS


def test_zwangs_aus_auf_bereits_aus_sendet_nichts() -> None:
    """Kein Downlink ohne Wirkung — der Grund bleibt aber erhalten.

    Das Audit soll die **Lage** beschreiben (Fuehler weg), nicht nur die
    Reaktion. Sonst steht bei einem ausgefallenen Fuehler
    ``im_totband`` im Protokoll.
    """
    e = ent(None, LANG_AUS)
    assert e.befehl is Schaltbefehl.UNVERAENDERT
    assert e.grund == "kein_istwert"


def test_fehlender_istwert_schlaegt_den_veraltungs_hinweis() -> None:
    """Beide Faelle zugleich: der fehlende Wert wird genannt.

    Reihenfolge ist Absicht — ``kein_istwert`` ist die unmittelbarere
    Aussage, und sie stimmt auch dann, wenn die Veraltungs-Rechnung
    selbst fehlerhaft waere.
    """
    assert ent(None, LANG_EIN, veraltet=True).grund == "kein_istwert"


# ---------------------------------------------------------------------------
# Decimal
# ---------------------------------------------------------------------------


def test_rechnet_in_decimal_ohne_float_drift() -> None:
    """Der Grund fuer ``Decimal``, an einem Wert, der in float scheitert.

    ``21.0 - 0.5`` ist in IEEE-754 nicht exakt 20,5. Mit ``float``
    entscheidet an diesem Rand die Rundung des letzten Bits, und die
    Entscheidung waere nicht reproduzierbar.
    """
    e = ent(Decimal("20.50"), LANG_AUS, soll=Decimal("21.00"))
    assert e.befehl is Schaltbefehl.EIN

    # Und mit zwei Nachkommastellen, wie sie aus ``Numeric(5,2)`` kommen.
    assert ent(Decimal("20.49"), LANG_AUS, soll=Decimal("20.99")).befehl is Schaltbefehl.EIN


# ---------------------------------------------------------------------------
# Versatz beim Einschalten
# ---------------------------------------------------------------------------


def test_erstes_relais_wartet_nicht() -> None:
    assert einschalt_versatz(0, timedelta(minutes=2)) == timedelta(0)


def test_versatz_waechst_je_relais() -> None:
    assert einschalt_versatz(1, timedelta(minutes=2)) == timedelta(minutes=2)
    assert einschalt_versatz(3, timedelta(minutes=2)) == timedelta(minutes=6)


def test_negativer_index_ist_ein_fehler() -> None:
    with pytest.raises(ValueError, match="index"):
        einschalt_versatz(-1, timedelta(minutes=2))
