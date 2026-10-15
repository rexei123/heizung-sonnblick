"""Die Referenzzone-Regel der Zimmeruebersicht (15.10.2026).

Reine Funktion, also ohne Datenbank — diese Tests laufen auch ohne
``TEST_DATABASE_URL``. Der Datenbank-Pfad (``referenzzonen_pro_zimmer``)
und der Listen-Endpoint stehen in ``test_zimmerliste_ist_soll.py``.

**Die Faelle kommen aus der echten Zimmerliste**
(``scripts/seed_data/Zimmerliste_seed.csv``, gezaehlt am 15.10.2026:
45 Zimmer, 103 Zonen) und nicht aus der Vorstellung:

- 41 Zimmer mit einem ``Schlafzimmer``
- 4 Suiten mit ``Schlafzimmer L`` + ``Schlafzimmer R`` (52, 54, 102, 202)
- 9 davon unabhaengige Zimmer mit zusaetzlichem ``Kinderzimmer``
- jedes Zimmer mit ``Bad``
- **kein** Zimmer ohne Schlafzimmer — der Fall ist trotzdem geprueft,
  weil eine neue Zone ueber die Oberflaeche dazukommen kann und die
  Liste dann „–" zeigen muss statt abzustuerzen.
"""

from __future__ import annotations

from heizung.services.referenzzone import REFERENZ_NAMEN, waehle_referenzzone


def test_einfaches_schlafzimmer_gewinnt_gegen_bad() -> None:
    # Der Normalfall: 41 von 45 Zimmern.
    assert waehle_referenzzone([(10, "Bad"), (11, "Schlafzimmer")]) == 11


def test_zwei_schlafzimmer_nimmt_das_linke() -> None:
    # Zimmer 52, 54, 102, 202. „R" ist nie die Referenz, auch nicht, wenn
    # es in der Eingabe zuerst steht.
    zonen = [(21, "Schlafzimmer R"), (20, "Schlafzimmer L"), (22, "Bad")]
    assert waehle_referenzzone(zonen) == 20


def test_kinderzimmer_ist_nie_die_referenz() -> None:
    # 9 Suiten. Das Kinderzimmer ist im Schema ebenfalls ``bedroom``
    # (seed_rooms.KIND_MAP) — ueber ``kind`` waere der Fall nicht zu
    # trennen, ueber den Namen schon.
    zonen = [(31, "Kinderzimmer"), (30, "Schlafzimmer"), (32, "Bad")]
    assert waehle_referenzzone(zonen) == 30


def test_nur_kinderzimmer_und_bad_ergibt_keine_referenz() -> None:
    # Kommt in der Seed-Liste nicht vor. Erwartung ist ``None`` und keine
    # Notloesung: ein Kinderzimmer als Ersatz-Referenz waere eine Zahl,
    # die aussieht wie das Schlafzimmer.
    assert waehle_referenzzone([(41, "Kinderzimmer"), (42, "Bad")]) is None


def test_zimmer_ohne_schlafzimmer_ergibt_keine_referenz() -> None:
    assert waehle_referenzzone([(51, "Bad")]) is None


def test_zimmer_ohne_zonen_ergibt_keine_referenz() -> None:
    assert waehle_referenzzone([]) is None


def test_namen_sind_exakt_und_nicht_als_praefix_gemeint() -> None:
    # „Schlafzimmer Nord" ist kein Treffer. Begruendung: ein
    # Praefix-Vergleich wuerde auch ``Schlafzimmer R`` greifen lassen, und
    # damit haenge die Auswahl an der Reihenfolge der Zeilen.
    assert waehle_referenzzone([(61, "Schlafzimmer Nord")]) is None


def test_gleicher_name_zweimal_waehlt_deterministisch_die_kleinere_id() -> None:
    # Das Schema verbietet es (``uq_heating_zone_room_name``); die Funktion
    # sieht das Schema nicht. Wichtig ist nur, dass dieselbe Eingabe immer
    # dieselbe Zone liefert (S2) — nicht, welche.
    zonen = [(72, "Schlafzimmer"), (71, "Schlafzimmer")]
    assert waehle_referenzzone(zonen) == 71
    assert waehle_referenzzone(list(reversed(zonen))) == 71


def test_reihenfolge_der_eingabe_aendert_nichts() -> None:
    zonen = [(80, "Schlafzimmer"), (81, "Kinderzimmer"), (82, "Bad")]
    erwartet = waehle_referenzzone(zonen)
    assert erwartet == 80
    for drehung in range(len(zonen)):
        gedreht = zonen[drehung:] + zonen[:drehung]
        assert waehle_referenzzone(gedreht) == erwartet


def test_referenz_namen_prioritaet_steht_fest() -> None:
    # Schutz gegen ein versehentliches Umsortieren: das einfache
    # ``Schlafzimmer`` muss vor ``Schlafzimmer L`` stehen, sonst wuerde in
    # einem Zimmer mit beidem (gibt es heute nicht) das linke gewinnen.
    assert REFERENZ_NAMEN == ("Schlafzimmer", "Schlafzimmer L")
