"""Allgemeinbereiche: Vorrang, Betriebszeiten, Status (Sprint 24d).

**Der Befund, gelesen in der Produktion am 24.10.2026.** Die hausweite
``rule_config``-Zeile trägt ``t_occupied = NULL``, ``t_vacant = NULL`` und
``t_night = 19.0``. Die Kette ``ROOM > ROOM_TYPE > GLOBAL`` fällt bei NULL
weiter durch bis auf die Spalte des Raumtyps — „Belegt" und „Frei" wirken
also heute schon. **„Nacht" nicht:** die 19,0 gewinnt gegen jeden Raumtyp.
Derselbe Grund wie beim Bad-Befund vom 18.10.

**Korrektur meiner Behauptung aus 24c.** Dort stand, die Bereiche heizten
im Haus auf 18 °C. Das war aus der **Test**-Datenbank geschlossen — deren
Seed setzt alle drei Felder — und ohne Messung auf die Produktion
übertragen (§5.68, in eigener Sache).

Diese Datei prüft drei Nähte:

1. **Der Vorrang.** Für einen Allgemeinbereich stehen die Spalten des
   Raumtyps auf ROOM_TYPE-Rang und schlagen damit den Hausstandard; für
   ein Gästezimmer bleibt alles, wie es war. Das zweite ist die
   Zusicherung, die der Sprint-Brief als harten Stopp führt, und sie wird
   über **alle** buchbaren Raumtypen geprüft, nicht an einem Beispiel.
2. **Die Betriebszeit.** Außerhalb ist bei einem Bereich genau das, was
   bei einem Gästezimmer die Nacht ist — mit einer Zeitgrenze, die über
   Mitternacht laufen kann.
3. **Der Status.** Der Belegungsabgleich lässt Bereiche in Ruhe,
   Gästezimmer nicht.

Die Übersteuerung ohne Belegung (S6) steht in
``test_api_allgemeinbereiche.py``, weil ihre Zusicherungen am Endpunkt
hängen und nicht am Dienst (Lehre vom 21.10.: ein ``KeyError`` auf der
Ebene des ``dict`` belegt nichts über die Antwort der API, §5.83).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import time
from decimal import Decimal

import pytest
import pytest_asyncio
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.enums import HeatingZoneKind, RoomStatus, RuleConfigScope
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.rules.engine import evaluate_room
from heizung.services import betriebszeit, raumtyp_regel
from heizung.services.occupancy_service import sync_room_status
from heizung.services.raumtyp_regel import RegelSync

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24d"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

HAUSWEIT_FREI = 16
HAUSWEIT_NACHT = 19
"""Die hausweiten Werte, die diese Datei selbst setzt.

**Keine Zahl aus dem Haus.** Welcher Wert dort steht, ist eine Einstellung
und kann sich ändern; ein Test, der 18 erwartet, prüft dann die Einstellung
und nicht die Rangfolge. Die Tests setzen die Werte deshalb selbst auf
etwas, das sich von jedem Raumtyp-Wert unterscheidet, und die Sitzung wird
am Ende zurückgerollt.
"""

BETRIEB = 21
ABSENKUNG = 17

#: Ein Tag in der Winterzeit (CET, UTC+1) — keine Sommerzeit-Mehrdeutigkeit.
#: Die Umstellung ist am 25.10.2026; dieser Tag liegt sicher danach.
TAG = "2026-11-10"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _hausstandard(
    session: AsyncSession, *, frei: int | None, nacht: int | None
) -> RuleConfig:
    """Setzt den Hausstandard für die Dauer dieses Tests.

    ``None`` heißt **leer** — und das ist der Zustand, in dem die
    Produktion am 24.10.2026 war. Ein Test, der nur den gesetzten Fall
    prüft, hätte den Befund nicht gefunden.
    """
    zeile = (
        await session.execute(
            select(RuleConfig)
            .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
            .where(RuleConfig.room_type_id.is_(None))
            .where(RuleConfig.room_id.is_(None))
            .where(RuleConfig.season_id.is_(None))
        )
    ).scalar_one_or_none()
    if zeile is None:
        zeile = RuleConfig(scope=RuleConfigScope.GLOBAL)
        session.add(zeile)
    zeile.t_vacant = None if frei is None else Decimal(frei)
    zeile.t_night = None if nacht is None else Decimal(nacht)
    await session.flush()
    return zeile


async def _zimmer(
    session: AsyncSession,
    *,
    buchbar: bool,
    betrieb: int = BETRIEB,
    absenkung: int = ABSENKUNG,
) -> tuple[int, RoomType]:
    """Ein Zimmer mit Raumtyp und einer Zone.

    ``Room.number`` ist ``VARCHAR(20)`` (§5.49): ``t24d`` (4) + Trenner +
    6 Hex = 11 Zeichen.
    """
    short = uuid.uuid4().hex[:6]
    rt = RoomType(
        name=f"{PREFIX}-{'gast' if buchbar else 'bereich'}-{short}",
        is_bookable=buchbar,
        # Bei einem Bereich ist „Betrieb" intern der Frei-Wert, und
        # „Belegt" zieht der Endpunkt beim Speichern gleich. Hier wird die
        # Engine direkt gerufen, also steht beides ausdrücklich da.
        default_t_occupied=Decimal(betrieb),
        default_t_vacant=Decimal(betrieb),
        default_t_night=Decimal(absenkung),
    )
    session.add(rt)
    await session.flush()

    room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()
    session.add(
        HeatingZone(
            room_id=room.id,
            kind=HeatingZoneKind.COMMON_AREA if not buchbar else HeatingZoneKind.BEDROOM,
            name="Bereich" if not buchbar else "Schlafzimmer",
        )
    )
    await session.flush()
    return room.id, rt


# ---------------------------------------------------------------------------
# Naht 1: der Vorrang
# ---------------------------------------------------------------------------


async def test_raumtyp_schlaegt_hausstandard_beim_bereich(db_session: AsyncSession) -> None:
    """**Abschlusskriterium 1, Tag-Hälfte.** Betrieb 21 am Raumtyp → 21 °C.

    Der Hausstandard setzt hier ausdrücklich **beide** Werte. Genau das
    ist der Fall, den die Produktion heute **nicht** hat — und der, in dem
    sich der Vorrang zeigt.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=False)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BETRIEB, (
        f"erwartet {BETRIEB} °C aus dem Raumtyp, bekommen {ergebnis.setpoint_c} °C"
    )


async def test_zweiter_bereich_mit_anderem_wert(db_session: AsyncSession) -> None:
    """Der zweite Wert ist nicht Fleiß.

    Er hält fest, dass der Sollwert aus dem **Raumtyp** kommt und nicht
    aus einer Konstante, die zufällig 21 ist.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=False, betrieb=19)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 19


async def test_gaestezimmer_nimmt_weiter_den_hausstandard(db_session: AsyncSession) -> None:
    """**Mutationsprobe M20 — und der harte Stopp des Sprint-Briefs.**

    Dasselbe Zimmer mit **buchbarem** Raumtyp: dort gewinnt der
    Hausstandard weiter. Würde der Vorrang auch hier gelten, verschöbe
    sich der wirksame Sollwert jedes Gästezimmers in dem Moment, in dem
    der Deploy durchläuft — ohne dass jemand einen Wert gesehen hat.

    Ohne diesen Test beweist der oben nichts: er wäre auch grün, wenn die
    Spalten **immer** gewinnen.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=True)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == HAUSWEIT_FREI


async def test_leerer_hausstandard_laesst_die_spalte_durch(db_session: AsyncSession) -> None:
    """Der Zustand der Produktion am 24.10.2026, für ein Gästezimmer.

    Ist das Feld hausweit **leer**, fällt die Kette auf die Spalte durch —
    auch bei einem buchbaren Raumtyp, und das war schon vor diesem Sprint
    so. Genau deshalb wirken „Belegt" und „Frei" im Haus bereits, und
    genau deshalb war meine Behauptung aus 24c falsch.
    """
    await _hausstandard(db_session, frei=None, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=True)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BETRIEB


async def test_eine_raumtyp_zeile_schlaegt_die_spalte(db_session: AsyncSession) -> None:
    """Eine ausdrückliche ROOM_TYPE-Zeile gewinnt gegen die Spalte.

    Das ist der Weg, über den ein **buchbarer** Raumtyp seinen Vorrang
    bekommt (Admin-Aktion) — und bei einem Bereich die Möglichkeit, die
    Spalte zu übersteuern, ohne sie zu ändern. Dieselbe Rangfolge wie
    beim Zimmer.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, rt = await _zimmer(db_session, buchbar=False)
    db_session.add(
        RuleConfig(scope=RuleConfigScope.ROOM_TYPE, room_type_id=rt.id, t_vacant=Decimal(24))
    )
    await db_session.flush()

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 24


async def test_zimmer_schlaegt_raumtyp(db_session: AsyncSession) -> None:
    """Die Rangfolge gilt auch nach oben: ein Zimmer-Eintrag gewinnt.

    Wer dem einzelnen Zimmer einen Wert gibt, soll ihn behalten — sonst
    hätte dieser Sprint eine Einstellmöglichkeit genommen, um eine andere
    zu geben.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=False)
    db_session.add(RuleConfig(scope=RuleConfigScope.ROOM, room_id=room_id, t_vacant=Decimal(23)))
    await db_session.flush()

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 23


async def test_trace_nennt_die_quelle_und_den_betrieb(db_session: AsyncSession) -> None:
    """**Abschlusskriterium 2, Trace-Hälfte.**

    Der Trace trug bis hierher den Wert und nicht seine Herkunft — und
    daran war nicht zu sehen, warum ein Zimmer den hausweiten Wert
    bekommt, wenn auf seiner Raumtyp-Seite etwas anderes steht.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=False)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    basis = [s for s in ergebnis.layers if s.layer.value == "base_target"]
    assert len(basis) == 1, "Layer 1 schreibt immer genau einen Schritt (§5.23)"
    extras = basis[0].extras
    assert extras is not None
    assert extras["sollwert_quelle"] == "raumtyp"
    assert extras["betriebsbereich"] is True


async def test_trace_nennt_hausweit_beim_gaestezimmer(db_session: AsyncSession) -> None:
    """Die Marke folgt der Wirklichkeit und nicht der Absicht."""
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=True)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    basis = next(s for s in ergebnis.layers if s.layer.value == "base_target")
    assert basis.extras is not None
    assert basis.extras["sollwert_quelle"] == "global"
    assert basis.extras["betriebsbereich"] is False


# ---------------------------------------------------------------------------
# Naht 2: die Betriebszeit
# ---------------------------------------------------------------------------


async def _mit_betriebszeit(
    session: AsyncSession, *, von: str, bis: str, buchbar: bool = False
) -> int:
    room_id, _ = await _zimmer(session, buchbar=buchbar)
    await betriebszeit.setze(
        session,
        room_id,
        von=betriebszeit.parse_uhrzeit(von),
        bis=betriebszeit.parse_uhrzeit(bis),
    )
    return room_id


@pytest.mark.parametrize(
    ("ortszeit", "erwartet", "warum"),
    [
        ("06:30", ABSENKUNG, "vor der Oeffnung"),
        ("07:30", BETRIEB, "kurz nach der Oeffnung"),
        ("21:59", BETRIEB, "letzte Minute des Betriebs"),
        ("22:01", ABSENKUNG, "kurz nach dem Schliessen"),
    ],
)
async def test_rezeption_07_bis_22(
    db_session: AsyncSession, ortszeit: str, erwartet: int, warum: str
) -> None:
    """Betriebszeit 07:00–22:00, vier Zeitpunkte.

    Die Grenzen sind absichtlich **knapp** gewählt (06:30/07:30,
    21:59/22:01): eine Prüfung um 03:00 und 12:00 wäre auch mit einem um
    eine Stunde verschobenen Fenster grün.
    """
    await _hausstandard(db_session, frei=None, nacht=None)
    room_id = await _mit_betriebszeit(db_session, von="07:00", bis="22:00")

    with freeze_time(f"{TAG}T{ortszeit}:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == erwartet, f"{ortszeit} ({warum})"


@pytest.mark.parametrize(
    ("ortszeit", "erwartet", "warum"),
    [
        ("14:59", ABSENKUNG, "vor der Oeffnung"),
        ("15:01", BETRIEB, "kurz nach der Oeffnung"),
        ("23:30", BETRIEB, "spaet, aber offen"),
        ("23:59", BETRIEB, "letzte Minute des Betriebs"),
        ("00:01", ABSENKUNG, "nach Mitternacht"),
    ],
)
async def test_bar_15_bis_24(
    db_session: AsyncSession, ortszeit: str, erwartet: int, warum: str
) -> None:
    """Betriebszeit 15:00–**24:00**, fünf Zeitpunkte.

    **Mutationsprobe M27** greift bei 23:30 und 23:59 an: ein Fenster, das
    über Mitternacht falsch gerechnet wird, senkt die Bar genau dann ab,
    wenn sie voll ist.

    „24:00" ist die Eingabe des Betreibers und wird auf 00:00 abgebildet.
    Das Fenster der Absenkung läuft damit von 00:00 bis 15:00 und wrappt
    **nicht** — die Mitternachts-Frage liegt hier auf der anderen Seite
    als bei der Rezeption, und beide Fälle stehen deshalb da.
    """
    await _hausstandard(db_session, frei=None, nacht=None)
    room_id = await _mit_betriebszeit(db_session, von="15:00", bis="24:00")

    with freeze_time(f"{TAG}T{ortszeit}:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == erwartet, f"{ortszeit} ({warum})"


async def test_ohne_betriebszeit_bleibt_der_betrieb_sollwert(
    db_session: AsyncSession,
) -> None:
    """Ein Bereich ohne eigene Betriebszeit wird nicht abgesenkt.

    Fehlt das Fenster, greift die Kette weiter (Raumtyp, dann hausweit) —
    und ist auch dort nichts gesetzt, gilt der Betrieb-Sollwert rund um
    die Uhr. Das ist der Zustand **vor** dem Eintrag des Betreibers und
    darf kein Frostschutz und keine Absenkung sein.
    """
    await _hausstandard(db_session, frei=None, nacht=None)
    room_id, _ = await _zimmer(db_session, buchbar=False)

    with freeze_time(f"{TAG}T03:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BETRIEB


async def test_gaestezimmer_wird_unbelegt_nicht_abgesenkt(db_session: AsyncSession) -> None:
    """**Mutationsprobe M24, Gegenrichtung.**

    Die Zeitsteuerung gilt für einen Bereich **ohne** Belegung — aber für
    ein Gästezimmer unverändert nur **mit**. Ein leeres Zimmer liegt schon
    auf dem Frei-Sollwert; es zusätzlich abzusenken wäre eine
    Verhaltensänderung an einem Pfad, den dieser Sprint nicht anfassen
    soll.
    """
    await _hausstandard(db_session, frei=None, nacht=None)
    room_id = await _mit_betriebszeit(db_session, von="07:00", bis="22:00", buchbar=True)

    with freeze_time(f"{TAG}T03:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BETRIEB, (
        "ein unbelegtes Gaestezimmer darf nicht in die Absenkung fallen"
    )


async def test_absenkung_traegt_ihren_grund_im_trace(db_session: AsyncSession) -> None:
    """Auch außerhalb der Betriebszeit sagt der Trace, dass es ein Bereich ist.

    Ohne die Marke hieße der Grund in der Oberfläche „Nachtabsenkung" —
    für eine Bar um 01:00 eine Aussage über die Uhrzeit und nicht über den
    Betrieb.
    """
    await _hausstandard(db_session, frei=None, nacht=None)
    room_id = await _mit_betriebszeit(db_session, von="15:00", bis="24:00")

    with freeze_time(f"{TAG}T03:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    schritt = next(s for s in ergebnis.layers if s.layer.value == "temporal_override")
    assert schritt.reason.value == "night_setback"
    assert schritt.extras is not None
    assert schritt.extras["betriebsbereich"] is True


async def test_vierundzwanzig_uhr_ist_mitternacht() -> None:
    """Reine Funktion, keine Datenbank: ``24:00`` → ``00:00``."""
    assert betriebszeit.parse_uhrzeit("24:00") == time(0, 0)
    assert betriebszeit.parse_uhrzeit("00:00") == time(0, 0)
    assert betriebszeit.parse_uhrzeit("15:00") == time(15, 0)
    assert betriebszeit.parse_uhrzeit(" 07:30 ") == time(7, 30)


@pytest.mark.parametrize("eingabe", ["25:00", "7:00", "24:01", "", "abc", "12:60"])
async def test_unsinn_wird_abgewiesen(eingabe: str) -> None:
    """Und zwar laut.

    ``7:00`` ist bewusst dabei: eine fehlende führende Null ist der
    häufigste Tippfehler, und sie stillschweigend zu dulden hieße, zwei
    Schreibweisen zu haben, von denen eine nirgends dokumentiert ist.
    """
    with pytest.raises(betriebszeit.BetriebszeitError):
        betriebszeit.parse_uhrzeit(eingabe)


async def test_halbe_betriebszeit_wird_abgewiesen(db_session: AsyncSession) -> None:
    """Ein Fenster mit einem Ende und ohne Anfang ist keins.

    Die Engine würde es stillschweigend ignorieren (sie prüft beide
    Grenzen auf ``not None``), und damit stünde in der Oberfläche eine
    Zeit, die nichts tut (§5.77).
    """
    room_id, _ = await _zimmer(db_session, buchbar=False)
    with pytest.raises(betriebszeit.BetriebszeitError):
        await betriebszeit.setze(db_session, room_id, von=time(7, 0), bis=None)


async def test_betriebszeit_loeschen_laesst_die_sollwerte_stehen(
    db_session: AsyncSession,
) -> None:
    """Löschen nimmt nur das Fenster mit, nicht die übrige Zeile.

    In derselben ``rule_config``-Zeile kann ein Sollwert für **dieses**
    Zimmer stehen. Ihn beim Löschen der Betriebszeit mitzunehmen wäre ein
    Datenverlust, den niemand am Knopf erwartet.
    """
    room_id, _ = await _zimmer(db_session, buchbar=False)
    await betriebszeit.setze(db_session, room_id, von=time(7, 0), bis=time(22, 0))
    zeile = await betriebszeit.lade_zimmer_zeile(db_session, room_id)
    assert zeile is not None
    zeile.t_vacant = Decimal(22)
    await db_session.flush()

    await betriebszeit.setze(db_session, room_id, von=None, bis=None)

    assert zeile.night_start is None
    assert zeile.night_end is None
    assert zeile.t_vacant == Decimal("22.0")


# ---------------------------------------------------------------------------
# Naht 3: Status und Abgleich
# ---------------------------------------------------------------------------


async def test_belegungsabgleich_laesst_einen_bereich_in_ruhe(
    db_session: AsyncSession,
) -> None:
    """**Mutationsprobe M21 in Testform.**

    Ein Bereich hat keine Belegung. Ein abgeleitetes „frei" wäre dort
    keine Aussage, sondern eine Verwechslung — und es würde die Marke
    „Allgemeinbereich" in der Liste überschreiben.

    Der Ausgangszustand ist bewusst ``reserved``: ein Wert, den der
    Abgleich **sonst** anfassen würde. Bliebe die Schutzklausel aus,
    stünde danach ``vacant`` da.
    """
    room_id, _ = await _zimmer(db_session, buchbar=False)
    room = await db_session.get(Room, room_id)
    assert room is not None
    room.status = RoomStatus.RESERVED
    await db_session.flush()

    await sync_room_status(db_session, room_id)

    assert room.status == RoomStatus.RESERVED


async def test_belegungsabgleich_gleicht_ein_gaestezimmer_weiter_ab(
    db_session: AsyncSession,
) -> None:
    """Die Gegenprobe. Ohne sie prüfte der Test oben nur, dass nichts passiert."""
    room_id, _ = await _zimmer(db_session, buchbar=True)
    room = await db_session.get(Room, room_id)
    assert room is not None
    room.status = RoomStatus.RESERVED
    await db_session.flush()

    await sync_room_status(db_session, room_id)

    assert room.status == RoomStatus.VACANT


# ---------------------------------------------------------------------------
# Die Vorschau und die Freigabe-Aktion
# ---------------------------------------------------------------------------


async def test_vorschau_nennt_angezeigt_wirksam_und_quelle(db_session: AsyncSession) -> None:
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    _, rt = await _zimmer(db_session, buchbar=False)

    befunde = await raumtyp_regel.wirksamkeit(db_session)
    mein = next(b for b in befunde if b.room_type_id == rt.id)

    frei = next(f for f in mein.felder if f.feld == "default_t_vacant")
    assert frei.angezeigt == Decimal(BETRIEB)
    assert frei.wirksam == Decimal(BETRIEB)
    assert frei.quelle == "raumtyp"
    assert mein.wuerde_sich_aendern is False


async def test_vorschau_zeigt_die_abweichung_beim_gaestezimmer(
    db_session: AsyncSession,
) -> None:
    """Der Fall, für den die Vorschau und die Freigabe-Aktion gebaut sind."""
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    _, rt = await _zimmer(db_session, buchbar=True)

    befunde = await raumtyp_regel.wirksamkeit(db_session)
    mein = next(b for b in befunde if b.room_type_id == rt.id)

    frei = next(f for f in mein.felder if f.feld == "default_t_vacant")
    assert frei.angezeigt == Decimal(BETRIEB)
    assert frei.wirksam == Decimal(HAUSWEIT_FREI)
    assert frei.quelle == "global"
    assert mein.zeile_vorhanden is False
    assert mein.wuerde_sich_aendern is True


async def test_die_freigabe_aktion_legt_die_zeile_an(db_session: AsyncSession) -> None:
    """Und erst sie. Das Speichern allein tut es nicht."""
    _, rt = await _zimmer(db_session, buchbar=True)

    assert await raumtyp_regel.synchronisiere_raumtyp(db_session, rt) == RegelSync.UEBERSPRUNGEN
    assert await raumtyp_regel.lade_raumtyp_zeile(db_session, rt.id) is None

    assert (
        await raumtyp_regel.synchronisiere_raumtyp(db_session, rt, anlegen_erlaubt=True)
        == RegelSync.ANGELEGT
    )
    assert await raumtyp_regel.lade_raumtyp_zeile(db_session, rt.id) is not None


async def test_das_nachziehen_laesst_fremde_felder_stehen(db_session: AsyncSession) -> None:
    """Nur die drei Sollwerte, nichts anderes.

    In derselben Zeile können ein Nachtfenster oder eine Fenster-Schwelle
    stehen — gesetzt an einer anderen Stelle der Oberfläche. Das Formular
    für den Raumtyp kennt sie nicht und darf sie deshalb nicht verlieren.
    """
    _, rt = await _zimmer(db_session, buchbar=True)
    await raumtyp_regel.synchronisiere_raumtyp(db_session, rt, anlegen_erlaubt=True)
    zeile = await raumtyp_regel.lade_raumtyp_zeile(db_session, rt.id)
    assert zeile is not None
    zeile.window_open_drop_celsius = Decimal("2.5")
    await db_session.flush()

    rt.default_t_vacant = Decimal(22)
    await raumtyp_regel.synchronisiere_raumtyp(db_session, rt)

    assert zeile.window_open_drop_celsius == Decimal("2.5")
    assert zeile.t_vacant == Decimal("22.0")


async def test_hausstandard_nutzung_zaehlt_eigene_werte(db_session: AsyncSession) -> None:
    """Die Zahl neben dem Feld auf der globalen Seite.

    Ein Bereich hat für die drei Sollwerte immer einen eigenen Wert (die
    Spalte steht auf ROOM_TYPE-Rang) — für das Nachtfenster dagegen nicht,
    solange ihm niemand eine Betriebszeit gibt. Der Test prüft beides an
    einem Aufbau, damit der Unterschied nicht verloren geht.
    """
    await _hausstandard(db_session, frei=HAUSWEIT_FREI, nacht=HAUSWEIT_NACHT)
    room_id, _ = await _zimmer(db_session, buchbar=False)

    vorher = {b.feld: b for b in await raumtyp_regel.hausstandard_nutzung(db_session)}
    assert vorher["t_vacant"].raumtypen_eigen >= 1
    assert vorher["night_start"].zimmer_eigen == 0

    await betriebszeit.setze(db_session, room_id, von=time(15, 0), bis=time(0, 0))

    nachher = {b.feld: b for b in await raumtyp_regel.hausstandard_nutzung(db_session)}
    assert nachher["night_start"].zimmer_eigen == 1, (
        "ein Zimmer mit Betriebszeit hat eine eigene Einstellung fuer das Fenster"
    )


# ---------------------------------------------------------------------------
# Test-Isolation (§5.39)
# ---------------------------------------------------------------------------


async def test_diese_datei_hinterlaesst_keine_rule_config_zeilen(
    db_session: AsyncSession,
) -> None:
    """Der Wächter gegen genau den Fehler, der 24c rot gemacht hat.

    Am 24.10.2026 hat ein fremder Test die hausweite ``rule_config``-Zeile
    angelegt und nicht abgeräumt; jeder Engine-Test danach im selben Lauf
    bekam damit einen anderen Sollwert — unsichtbar, solange keiner darauf
    stand (§5.39).

    Diese Datei arbeitet ausschließlich in einer Sitzung, die am Ende
    zurückgerollt wird. Der Test belegt das, statt es zu behaupten.
    """
    offen = await db_session.scalar(
        select(RuleConfig)
        .join(RoomType, RoomType.id == RuleConfig.room_type_id)
        .where(RoomType.name.like(f"{PREFIX}-%"))
        .limit(1)
    )
    assert offen is None, (
        "eine rule_config-Zeile dieser Datei ist in der Datenbank geblieben — "
        "eine Fixture committet, wo sie zurückrollen sollte"
    )

    zimmer_zeilen = await db_session.scalar(
        select(RuleConfig)
        .join(Room, Room.id == RuleConfig.room_id)
        .where(Room.number.like(f"{PREFIX}-%"))
        .limit(1)
    )
    assert zimmer_zeilen is None, "eine Betriebszeit-Zeile ist geblieben"
