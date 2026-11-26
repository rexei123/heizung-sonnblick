"""Tagesplan an Datenbank, Engine und Endpunkt (21.11.2026).

Vier Naehte, und jede hat ihren eigenen Grund, hier und nicht woanders zu
stehen:

1. **Die Tabelle.** Die ``EXCLUDE``-Bedingung ist die einzige Zusicherung,
   die auch bei zwei gleichzeitigen Anfragen haelt (§5.60). Sie laesst sich
   nur gegen eine echte Datenbank pruefen — ``int4range`` und
   ``btree_gist`` gibt es in keinem Nachbau.
2. **Die Engine.** Der Plan aendert den Sollwert, den ein Bereich bekommt.
   Das ist der Pflicht-Stop dieses Sprints, und die Proben liegen auf den
   Minuten der Grenzen, nicht in der Mitte der Fenster.
3. **Der Endpunkt.** Eine Zusicherung ueber die Antwort der API wird an
   der API geprueft (§5.83) — ein ``ValidationError`` im Schema belegt
   nicht, mit welchem Status geantwortet wird.
4. **Der Verlauf.** Das Absenk-Band muss aus den Luecken des Plans kommen.
   Sonst zeichnet die Anzeige die Betriebszeit weiter, nach der nicht mehr
   geregelt wird — und das ist der Fall, fuer den
   ``rules/config_resolve`` ueberhaupt ausgelagert wurde (§5.53).

**Die Sommerzeit hat eine eigene Gruppe.** Ein Fenster ist Wanduhrzeit:
„07:00" ist im Maerz und im November dieselbe Zeile und derselbe
Zeitpunkt auf der Wand, aber ein anderer in UTC. Wer in UTC vergliche,
bekaeme eine Stunde Verschiebung an zwei Tagen im Jahr — und die Proben
unten wuerden es sehen (§5.65).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi import params
from freezegun import freeze_time
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.api.v1.rooms import set_tagesplan
from heizung.auth.dependencies import require_admin
from heizung.db import get_session
from heizung.main import app
from heizung.models.business_audit import BusinessAudit
from heizung.models.enums import HeatingZoneKind, OverrideSource
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.tagesplan import TagesplanFenster
from heizung.rules.engine import evaluate_room
from heizung.rules.tagesplan import lade_fenster
from heizung.services import betriebszeit
from heizung.services import tagesplan as tagesplan_service
from heizung.services.room_history import lade_verlauf
from heizung.uhrzeit import parse_minuten

DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL/DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "tp"

pytestmark = pytest.mark.skipif(not DB_URL, reason=SKIP_REASON)

BETRIEB = 21
ABSENKUNG = 17
MORGENS = 25
TAGS = 22

#: Ein Tag in der Winterzeit (CET, UTC+1). Die Umstellung 2026 liegt am
#: 25.10. und am 29.03.; dieser Tag liegt sicher dazwischen.
TAG = "2026-11-10"

#: Mitternacht dieses Tages, als Zeitpunkt. **Jede Frist in dieser Datei
#: haengt hieran und nicht an ``datetime.now()``.**
#:
#: Der Grund ist ein roter Test vom 25.11.2026: die Uebersteuerung bekam
#: ihre Frist aus der echten Uhr (damals der 25.11.), beurteilt wurde sie
#: aber unter ``freeze_time`` am 10.11. — eine Frist zwei Wochen in der
#: **Zukunft**, die auch nach dem „Vorziehen" noch lief. Der Test, der den
#: Ablauf pruefen sollte, hat nie einen gesehen. Das ist §5.82: eine halb
#: gefaelschte Zeitquelle ist schlimmer als keine. Wer eine Frist gegen
#: eine eingefrorene Uhr prueft, rechnet sie aus **derselben** Uhr.
TAG_BEGINN = datetime.fromisoformat(f"{TAG}T00:00:00+01:00")


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    """``alembic upgrade head`` im Thread, einmal pro Modul."""
    if not DB_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DB_URL or "")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(setup_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Eine Sitzung, die am Ende **zurueckgerollt** wird.

    Damit bleibt von den Zimmern und Raumtypen dieser Tests nichts
    stehen — §5.39: eine vergessene ``rule_config``-Zeile hat am
    24.10.2026 jeden Engine-Test im selben Lauf auf einen anderen
    Sollwert gezogen.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()


async def _bereich(
    session: AsyncSession,
    *,
    buchbar: bool = False,
    betrieb: int = BETRIEB,
    absenkung: int = ABSENKUNG,
) -> int:
    """Ein Zimmer mit Raumtyp und einer Zone.

    ``Room.number`` ist ``VARCHAR(20)`` (§5.49): ``tp`` (2) + Trenner +
    6 Hex = 9 Zeichen.
    """
    short = uuid.uuid4().hex[:6]
    rt = RoomType(
        name=f"{PREFIX}-{'gast' if buchbar else 'bereich'}-{short}",
        is_bookable=buchbar,
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
    return room.id


async def _plan(session: AsyncSession, room_id: int, *fenster: tuple[str, str, int]) -> None:
    await tagesplan_service.ersetze(
        session,
        room_id,
        [
            tagesplan_service.NeuesFenster(
                von_minute=parse_minuten(von),
                bis_minute=parse_minuten(bis),
                temperatur=Decimal(temperatur),
            )
            for von, bis, temperatur in fenster
        ],
    )


async def _betriebszeit(session: AsyncSession, room_id: int, *, von: str, bis: str) -> None:
    await betriebszeit.setze(
        session,
        room_id,
        von=betriebszeit.parse_uhrzeit(von),
        bis=betriebszeit.parse_uhrzeit(bis),
    )


def _temporal(ergebnis: object) -> object:
    layers = ergebnis.layers  # type: ignore[attr-defined]
    return next(s for s in layers if s.layer.value == "temporal_override")


def _ortszeit(wann: datetime, zeitzone: str) -> str:
    """Ein Zeitpunkt in der Zeitzone des Hauses, als ``TT.MM. HH:MM``.

    Die Baender kommen in UTC — sie zeichnen auf einer UTC-Achse. Geprueft
    wird gegen die **Wanduhrzeit**, denn das ist die Zusage: ein Fenster
    06:00-21:00 beginnt um 06:00 Ortszeit (§5.65).
    """
    return wann.astimezone(ZoneInfo(zeitzone)).strftime("%d.%m. %H:%M")


# ---------------------------------------------------------------------------
# Naht 1: die Tabelle
# ---------------------------------------------------------------------------


async def test_zwei_fenster_stossen_aneinander_an(db_session: AsyncSession) -> None:
    """06:00-08:00 und 08:00-21:00 duerfen koexistieren.

    Das ist der Plan aus dem Wunsch des Betreibers. Haette die
    ``EXCLUDE``-Bedingung einen geschlossenen Bereich genommen
    (``int4range(von, bis, '[]')``), waere genau er nicht speicherbar.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS), ("08:00", "21:00", TAGS))

    fenster = await lade_fenster(db_session, room_id)
    assert [(f.von_text, f.bis_text) for f in fenster] == [("06:00", "08:00"), ("08:00", "21:00")]


async def test_eine_ueberschneidung_weist_die_datenbank_ab(db_session: AsyncSession) -> None:
    """**Die Zusicherung, die auch bei zwei Admins gleichzeitig haelt.**

    Pydantic prueft die Eingabe **einer** Anfrage. Zwei Anfragen, die
    einzeln gueltig sind und zusammen nicht, faengt nur die Datenbank
    (§5.60) — und ohne sie entschiede die Reihenfolge der Zeilen ueber
    den Sollwert (§0 S2).
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "10:00", MORGENS))

    db_session.add(
        TagesplanFenster(room_id=room_id, von_minute=480, bis_minute=1260, temperatur=Decimal(TAGS))
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_zwei_bereiche_duerfen_dieselbe_zeit_haben(db_session: AsyncSession) -> None:
    """Die Bedingung gilt **je Zimmer** (``room_id WITH =``).

    Bar und Rezeption duerfen beide von 06:00 bis 08:00 heizen. Ohne den
    Gleichheitsteil waere die Tabelle hausweit eindeutig — und das zweite
    Zimmer haette nie einen Plan bekommen.
    """
    bar = await _bereich(db_session)
    rezeption = await _bereich(db_session)
    await _plan(db_session, bar, ("06:00", "08:00", MORGENS))
    await _plan(db_session, rezeption, ("06:00", "08:00", TAGS))

    assert len(await lade_fenster(db_session, bar)) == 1
    assert len(await lade_fenster(db_session, rezeption)) == 1


@pytest.mark.parametrize(
    ("von_minute", "bis_minute", "temperatur", "warum"),
    [
        (480, 480, 22, "ein Fenster ohne Dauer"),
        (600, 480, 22, "Ende vor dem Beginn"),
        (0, 1441, 22, "ueber das Ende des Tages hinaus"),
        (-1, 480, 22, "vor dem Beginn des Tages"),
        (360, 480, 9, "unter der Geraetegrenze"),
        (360, 480, 31, "ueber der Geraetegrenze"),
    ],
)
async def test_die_bedingungen_der_tabelle_greifen(
    db_session: AsyncSession, von_minute: int, bis_minute: int, temperatur: int, warum: str
) -> None:
    """Die ``CHECK``-Bedingungen, einzeln angegriffen.

    Sie sind nicht Zierde: der Dienst schreibt, was das Schema durchlaesst,
    und ein Fenster ohne Dauer waere eine Zeile, die nie gilt und trotzdem
    in der Oberflaeche steht (§5.77).
    """
    room_id = await _bereich(db_session)
    db_session.add(
        TagesplanFenster(
            room_id=room_id,
            von_minute=von_minute,
            bis_minute=bis_minute,
            temperatur=Decimal(temperatur),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_der_plan_verschwindet_mit_dem_zimmer(db_session: AsyncSession) -> None:
    """``ON DELETE CASCADE`` — ein geloeschtes Zimmer hat keine Zeiten mehr.

    Ohne die Kaskade blockierte der Fremdschluessel das Loeschen eines
    Zimmers, und zwar erst beim naechsten Mal, wenn jemand einen Plan
    angelegt hat.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    await db_session.execute(text("DELETE FROM room WHERE id = :r"), {"r": room_id})
    await db_session.flush()

    assert await lade_fenster(db_session, room_id) == []


async def test_zwei_fenster_lassen_sich_tauschen(db_session: AsyncSession) -> None:
    """**Der Grund fuer ``PUT`` mit der ganzen Liste.**

    06:00-08:00 (25) und 08:00-10:00 (22) werden zu 06:00-08:00 (22) und
    08:00-10:00 (25). Jeder Einzelschritt waere eine Ueberschneidung, ganz
    gleich mit welchem man anfaengt — der vollstaendige Austausch in einer
    Transaktion ist es nicht.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS), ("08:00", "10:00", TAGS))
    await _plan(db_session, room_id, ("06:00", "08:00", TAGS), ("08:00", "10:00", MORGENS))

    fenster = await lade_fenster(db_session, room_id)
    assert [int(f.temperatur) for f in fenster] == [TAGS, MORGENS]


async def test_ein_leerer_plan_loescht(db_session: AsyncSession) -> None:
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    await _plan(db_session, room_id)

    assert await lade_fenster(db_session, room_id) == []


# ---------------------------------------------------------------------------
# Naht 2: die Engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ortszeit", "erwartet", "warum"),
    [
        ("05:59", ABSENKUNG, "eine Minute vor dem ersten Fenster"),
        ("06:00", MORGENS, "die erste Minute gehoert dazu"),
        ("07:59", MORGENS, "die letzte Minute des ersten Fensters"),
        ("08:00", TAGS, "die Grenze gehoert dem folgenden Fenster"),
        ("20:59", TAGS, "die letzte Minute des zweiten Fensters"),
        ("21:00", ABSENKUNG, "das Ende gehoert nicht mehr dazu"),
        ("03:00", ABSENKUNG, "mitten in der Nacht"),
    ],
)
async def test_der_plan_setzt_den_sollwert(
    db_session: AsyncSession, ortszeit: str, erwartet: int, warum: str
) -> None:
    """Der Wunsch des Betreibers, an sieben Zeitpunkten.

    Die Proben liegen **auf den Minuten der Grenzen**. Eine Pruefung um
    07:00 und 12:00 waere auch mit einem um eine Stunde verschobenen
    Fenster gruen (Lehre aus Sprint 24d).
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS), ("08:00", "21:00", TAGS))

    with freeze_time(f"{TAG}T{ortszeit}:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == erwartet, f"{ortszeit} ({warum})"


async def test_der_plan_schlaegt_die_betriebszeit(db_session: AsyncSession) -> None:
    """**Die Entscheidung dieses Sprints, in einem Test.**

    Die Bar hat Betriebszeit 15:00-24:00 — ohne Plan waere es um 07:00
    Absenkung. Mit einem Fenster 06:00-08:00 gilt der Plan, und zwar
    **statt** der Betriebszeit und nicht neben ihr.

    Waeren beide wirksam, muesste eine Regel entscheiden, welche bei einer
    Ueberschneidung gewinnt — und die koennte niemand sehen.
    """
    room_id = await _bereich(db_session)
    await _betriebszeit(db_session, room_id, von="15:00", bis="24:00")
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == MORGENS


async def test_in_der_luecke_gilt_die_absenkung_des_raumtyps(db_session: AsyncSession) -> None:
    """„Sonst Absenkung" — und es ist derselbe Wert wie vorher.

    Kein neues Feld: die Luecke nimmt ``t_night`` aus derselben Kette, die
    auch die Nachtabsenkung nimmt (``_absenk_schritt``). Deshalb steht hier
    ein Raumtyp mit einem **anderen** Absenkwert als dem hausweiten — eine
    Zahl, die zufaellig stimmt, belegt nichts.
    """
    room_id = await _bereich(db_session, absenkung=14)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))

    with freeze_time(f"{TAG}T12:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 14


async def test_ohne_plan_bleibt_alles_wie_vorher(db_session: AsyncSession) -> None:
    """**Die Zusicherung des Betreibers: kein Verhaltenswechsel ohne Plan.**

    Dieselbe Bar, dieselbe Betriebszeit, kein Fenster — und damit genau
    das Verhalten von Sprint 24d: um 07:00 Absenkung, um 16:00 Betrieb.

    Dieser Test ist auch die Probe fuer den Auszug von ``_absenk_schritt``
    (§5.47): er muss verhaltensneutral gewesen sein.
    """
    room_id = await _bereich(db_session)
    await _betriebszeit(db_session, room_id, von="15:00", bis="24:00")

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        nachts = await evaluate_room(db_session, room_id)
    with freeze_time(f"{TAG}T16:00:00+01:00"):
        tags = await evaluate_room(db_session, room_id)

    assert nachts is not None and tags is not None
    assert (nachts.setpoint_c, tags.setpoint_c) == (ABSENKUNG, BETRIEB)


async def test_ein_gaestezimmer_ohne_plan_bleibt_unberuehrt(db_session: AsyncSession) -> None:
    """Die 47 Zimmer des Hauses haben keinen Plan und bekommen keinen.

    Geprueft wird der Normalweg: ein buchbares Zimmer, frei, ohne
    Belegung — der Frei-Sollwert, unveraendert.
    """
    room_id = await _bereich(db_session, buchbar=True)

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BETRIEB


async def test_der_trace_nennt_das_fenster(db_session: AsyncSession) -> None:
    """**S3.** Wer „25 statt 22" fragt, muss die Antwort im Trace finden.

    Ohne die Marke stuende dort „Frei-Sollwert 25" und daneben ein
    Raumtyp, der 21 sagt — und die Herkunft der Zahl waere nicht
    auffindbar (derselbe Befund wie am 24.10.2026, der
    ``sollwert_quelle`` noetig gemacht hat).
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    fenster = await lade_fenster(db_session, room_id)

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    schritt = _temporal(ergebnis)
    assert schritt.detail is not None  # type: ignore[attr-defined]
    assert f"tagesplan_fenster: id={fenster[0].id}" in schritt.detail  # type: ignore[attr-defined]
    assert "fenster=[06:00,08:00)" in schritt.detail  # type: ignore[attr-defined]
    extras = schritt.extras  # type: ignore[attr-defined]
    assert extras is not None
    assert extras["sollwert_quelle"] == "tagesplan"
    assert extras["tagesplan_fenster_id"] == fenster[0].id
    assert extras["betriebsbereich"] is True


async def test_der_trace_nennt_die_luecke(db_session: AsyncSession) -> None:
    """Die Luecke ist eine Absenkung und sagt das auch.

    ``reason`` bleibt ``night_setback`` (§5.45: kein neuer Enum-Wert fuer
    eine Beschriftung), unterschieden wird im ``detail``. Die Oberflaeche
    nennt es bei einem Bereich ohnehin „Absenkung".
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))

    with freeze_time(f"{TAG}T12:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    schritt = _temporal(ergebnis)
    assert schritt.reason.value == "night_setback"  # type: ignore[attr-defined]
    assert "tagesplan_luecke" in (schritt.detail or "")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Naht 2b: die Sommerzeit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("zeitpunkt", "warum"),
    [
        ("2026-03-28T07:00:00+01:00", "Tag vor der Vorstellung, CET"),
        ("2026-03-30T07:00:00+02:00", "Tag nach der Vorstellung, CEST"),
        ("2026-10-24T07:00:00+02:00", "Tag vor der Rueckstellung, CEST"),
        ("2026-10-26T07:00:00+01:00", "Tag nach der Rueckstellung, CET"),
    ],
)
async def test_das_fenster_ist_wanduhrzeit(
    db_session: AsyncSession, zeitpunkt: str, warum: str
) -> None:
    """07:00 ist 07:00 — im Maerz, im Oktober, vor und nach der Umstellung.

    **Das ist die Probe gegen den Vergleich in UTC.** Dieselbe Wanduhrzeit
    ist an diesen vier Tagen 06:00 bzw. 05:00 UTC. Wer ``now.time()`` ohne
    ``astimezone`` vergliche, waere an zwei der vier Tage eine Stunde
    daneben — und zwar lautlos (§5.65, AE-60).
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))

    with freeze_time(zeitpunkt):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == MORGENS, warum


async def test_die_uebersprungene_stunde_verschiebt_das_fenster_nicht(
    db_session: AsyncSession,
) -> None:
    """Am 29.03.2026 gibt es kein 02:30 Ortszeit — 03:30 gibt es.

    Ein Fenster 02:00-04:00 ist an diesem Tag **eine Stunde kuerzer**, und
    das ist richtig so: der Betreiber meint die Wanduhr, und ``ZoneInfo``
    liefert sie. Eine Speicherung in UTC wuerde das Fenster stattdessen
    zweimal im Jahr **verschieben**.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("02:00", "04:00", MORGENS))

    # 03:30 CEST = 01:30 UTC, also die erste Minute nach dem Sprung.
    with freeze_time("2026-03-29T03:30:00+02:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == MORGENS


# ---------------------------------------------------------------------------
# Naht 2c: die Uebersteuerung
# ---------------------------------------------------------------------------
#
# **Nachgezogen am 25.11.2026 auf Nachfrage des Betreibers.** Der Auftrag
# nannte „Uebersteuerung schlaegt Tagesplan wie bisher" als Punkt, und
# #421 sogar ausdruecklich als „zu pruefen beim Bauen": dass eine
# Uebersteuerung den Plan nicht **dauerhaft** gewinnt — derselbe Fehler,
# den #414 im Relais-Pfad behoben hat, nur in der anderen Richtung.
#
# Gebaut war die Reihenfolge richtig (Schicht 3 kommt nach Schicht 2, und
# daran hat dieser PR nichts angefasst), geprueft war sie fuer den Plan
# **nicht**. Eine Reihenfolge, die nur deshalb haelt, weil niemand sie
# umgestellt hat, ist eine Annahme und kein Befund.


async def _zone_id(session: AsyncSession, room_id: int) -> int:
    zone = (
        await session.execute(select(HeatingZone.id).where(HeatingZone.room_id == room_id))
    ).scalar_one()
    return int(zone)


async def _uebersteuerung(
    session: AsyncSession,
    room_id: int,
    *,
    wert: int,
    zone_id: int | None = None,
    laeuft_bis: datetime | None = None,
) -> int:
    """Eine laufende Uebersteuerung, wie die Rezeption sie anlegt.

    ``frontend_bereich`` mit Frist — die Quelle, die ein Allgemeinbereich
    ueberhaupt annimmt (Sprint 24d, S6). Angelegt wird sie hier direkt in
    der Sitzung und nicht ueber den Endpunkt: geprueft wird die **Engine**,
    und der Weg durch die API hat seine eigenen Tests
    (``test_api_allgemeinbereiche``).

    Die Frist liegt ohne Angabe am **Ende des eingefrorenen Tages** und
    deckt damit jede Uhrzeit, die hier geprueft wird. Warum nicht
    ``datetime.now()``: siehe ``TAG_BEGINN``.
    """
    eintrag = ManualOverride(
        room_id=room_id,
        heating_zone_id=zone_id,
        setpoint=Decimal(wert),
        source=OverrideSource.FRONTEND_BEREICH,
        expires_at=laeuft_bis if laeuft_bis is not None else TAG_BEGINN + timedelta(days=1),
    )
    session.add(eintrag)
    await session.flush()
    return eintrag.id


async def test_eine_uebersteuerung_schlaegt_das_fenster(db_session: AsyncSession) -> None:
    """**Schicht 3 schlaegt Schicht 2** — auch wenn Schicht 2 ein Fenster ist.

    Um 07:00 gilt das Fenster mit 25 °C. Eine laufende Uebersteuerung auf
    19 °C gewinnt trotzdem: wer die Bar auf 19 stellt, will 19, auch wenn
    der Plan 25 sagt.

    Geprueft wird **beides** — der Sollwert und der Trace. Dass Schicht 2
    weiterhin das Fenster liefert, ist der Teil, der den Plan nach dem
    Ablauf wieder wirksam macht; eine Schicht 2, die bei laufender
    Uebersteuerung nichts mehr tut, waere nach dem Ablauf stumm.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    await _uebersteuerung(db_session, room_id, wert=19)

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 19, "die Uebersteuerung gilt"
    schritt = _temporal(ergebnis)
    assert schritt.setpoint_c == MORGENS, (  # type: ignore[attr-defined]
        "Schicht 2 liefert weiter das Fenster — sie wird nur ueberstimmt"
    )
    manuell = next(s for s in ergebnis.layers if s.layer.value == "manual_override")
    assert manuell.setpoint_c == 19


async def test_nach_dem_ablauf_gilt_wieder_das_fenster(db_session: AsyncSession) -> None:
    """**Der Punkt aus #421: der Plan darf nicht dauerhaft verlieren.**

    Setzen → 19. Ablauf → wieder 25, aus dem Fenster. Der Ablauf wird
    **vorgezogen** statt abgewartet: zwei Stunden Wartezeit in einem Test
    waeren keine Pruefung, sondern eine Zeitreise mit Risiko (§5.59).

    **Beide Uhren muessen dieselbe sein.** Beim ersten Lauf stand hier
    ``datetime.now() - 1 min``, also der 25.11.2026 — beurteilt wird aber
    unter ``freeze_time`` am 10.11., und damit lag die „vorgezogene" Frist
    zwei Wochen in der Zukunft. Der Test war rot und hatte recht: so haette
    er nie einen Ablauf gesehen (§5.82). Die Frist kommt deshalb aus
    ``TAG_BEGINN``, derselben Uhr, gegen die die Engine vergleicht.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    override_id = await _uebersteuerung(db_session, room_id, wert=19)

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        waehrend = await evaluate_room(db_session, room_id)
    assert waehrend is not None
    assert waehrend.setpoint_c == 19

    eintrag = await db_session.get(ManualOverride, override_id)
    assert eintrag is not None
    # 06:00 Ortszeit — eine Stunde vor dem Zeitpunkt, der beurteilt wird.
    eintrag.expires_at = TAG_BEGINN + timedelta(hours=6)
    await db_session.flush()

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        danach = await evaluate_room(db_session, room_id)

    assert danach is not None
    assert danach.setpoint_c == MORGENS, "nach dem Ablauf gilt wieder das Fenster"
    assert danach.zone_overrides == {}


async def test_eine_zonen_uebersteuerung_laesst_das_zimmer_beim_fenster(
    db_session: AsyncSession,
) -> None:
    """Eine **Zonen**-Uebersteuerung wirkt nur auf ihre Zone (AE-58 Option G).

    Der Zimmerwert bleibt der des Fensters, der Zonenwert steht in
    ``zone_overrides``. Das ist der Fall, den die Oberflaeche anlegt, und
    der Dispatch liest ihn je Geraet — faellt er auf den Zimmerwert
    zusammen, heizt die ganze Bar auf den Wunsch fuer eine Ecke.
    """
    room_id = await _bereich(db_session)
    zone_id = await _zone_id(db_session, room_id)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    await _uebersteuerung(db_session, room_id, wert=19, zone_id=zone_id)

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.zone_overrides.get(zone_id) == 19
    assert ergebnis.setpoint_c == MORGENS, "das Zimmer folgt weiter dem Fenster, nur die Zone nicht"


async def test_die_uebersteuerung_schlaegt_auch_die_luecke(db_session: AsyncSession) -> None:
    """Die Gegenprobe in der Luecke: 12:00, Absenkung 17 → Uebersteuerung 22.

    Ohne diese Haelfte waere der Test auch gruen, wenn die Uebersteuerung
    nur gegen **hoehere** Werte gewinnt. Sie gewinnt gegen beide Zweige
    der Schicht 2, und das ist der Punkt.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    await _uebersteuerung(db_session, room_id, wert=22)

    with freeze_time(f"{TAG}T12:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == 22
    schritt = _temporal(ergebnis)
    assert schritt.setpoint_c == ABSENKUNG  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Naht 4: der Verlauf
# ---------------------------------------------------------------------------


async def test_der_verlauf_zeichnet_die_luecken_des_plans(db_session: AsyncSession) -> None:
    """Das Band kommt aus dem Plan, nicht aus der Betriebszeit.

    Beides steht am Zimmer, und bis zum 21.11.2026 haette die Anzeige die
    Betriebszeit weitergezeichnet — ein Band, nach dem die Engine nicht
    mehr regelt. Genau diese Abweichung sollte ``rules/config_resolve``
    verhindern (§5.53); mit dem Plan braucht sie eine zweite Antwort.
    """
    room_id = await _bereich(db_session)
    await _betriebszeit(db_session, room_id, von="15:00", bis="24:00")
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS), ("08:00", "21:00", TAGS))
    room = await db_session.get(Room, room_id)
    assert room is not None

    jetzt = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=jetzt)

    assert verlauf.night_start is None, (
        "mit einem Plan gibt es kein einzelnes Fenster — eine Uhrzeit hier "
        "waere eine Zeit, nach der nicht geregelt wird"
    )
    # Das Fenster ist 09.11. 13:00 bis 10.11. 13:00 Ortszeit (CET). Die
    # Luecken des Plans sind 00:00-06:00 und 21:00-24:00 — darin liegen
    # genau zwei, und sie stossen an Mitternacht aneinander.
    spannen = [
        (_ortszeit(b.start, verlauf.timezone), _ortszeit(b.end, verlauf.timezone))
        for b in verlauf.night_bands
    ]
    assert spannen == [
        ("09.11. 21:00", "10.11. 00:00"),
        ("10.11. 00:00", "10.11. 06:00"),
    ], spannen


async def test_ohne_plan_zeichnet_der_verlauf_die_betriebszeit(db_session: AsyncSession) -> None:
    """Die Gegenprobe: ohne Fenster bleibt alles, wie es war.

    ``night_window`` traegt die Betriebszeit, und das Band haengt an ihr.
    """
    room_id = await _bereich(db_session)
    await _betriebszeit(db_session, room_id, von="15:00", bis="24:00")
    room = await db_session.get(Room, room_id)
    assert room is not None

    jetzt = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    verlauf = await lade_verlauf(db_session, room=room, bereich="24h", jetzt=jetzt)

    assert verlauf.night_start is not None
    assert verlauf.night_start.hour == 0, "night_start ist das Ende des Betriebs (24:00 -> 00:00)"
    assert verlauf.night_end is not None
    assert verlauf.night_end.hour == 15


# ---------------------------------------------------------------------------
# Naht 3: der Endpunkt
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class _Aufbau:
    def __init__(self, room_id: int, room_type_id: int) -> None:
        self.room_id = room_id
        self.room_type_id = room_type_id


async def _aufbauen(maker: async_sessionmaker[AsyncSession], *, buchbar: bool) -> _Aufbau:
    async with maker() as session:
        room_id = await _bereich(session, buchbar=buchbar)
        room = await session.get(Room, room_id)
        assert room is not None
        room_type_id = room.room_type_id
        await session.commit()
        assert room_type_id is not None
        return _Aufbau(room_id, room_type_id)


async def _abraeumen(maker: async_sessionmaker[AsyncSession], aufbau: _Aufbau) -> None:
    """Auch die Audit-Zeilen und die ``rule_config`` des Raumtyps (§5.39)."""
    async with maker() as session:
        await session.execute(
            text("DELETE FROM business_audit WHERE target_type = 'room' AND target_id = :r"),
            {"r": aufbau.room_id},
        )
        await session.execute(
            text("DELETE FROM event_log WHERE room_id = :r"), {"r": aufbau.room_id}
        )
        await session.execute(
            text("DELETE FROM heating_zone WHERE room_id = :r"), {"r": aufbau.room_id}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": aufbau.room_id})
        await session.execute(
            text("DELETE FROM rule_config WHERE room_type_id = :t"), {"t": aufbau.room_type_id}
        )
        await session.execute(
            text("DELETE FROM room_type WHERE id = :t"), {"t": aufbau.room_type_id}
        )
        await session.commit()


@pytest_asyncio.fixture
async def bereich_api(setup_engine: AsyncEngine) -> AsyncIterator[_Aufbau]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    aufbau = await _aufbauen(maker, buchbar=False)
    try:
        yield aufbau
    finally:
        await _abraeumen(maker, aufbau)


@pytest_asyncio.fixture
async def gastzimmer_api(setup_engine: AsyncEngine) -> AsyncIterator[_Aufbau]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    aufbau = await _aufbauen(maker, buchbar=True)
    try:
        yield aufbau
    finally:
        await _abraeumen(maker, aufbau)


WUNSCH = {
    "fenster": [
        {"von": "06:00", "bis": "08:00", "temperatur": 25.0},
        {"von": "08:00", "bis": "21:00", "temperatur": 22.0},
    ]
}


async def test_put_speichert_und_get_liest(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau
) -> None:
    """Der Wunsch des Betreibers, einmal durch die API."""
    resp = await http_client.put(f"/api/v1/rooms/{bereich_api.room_id}/tagesplan", json=WUNSCH)
    assert resp.status_code == 200, resp.text

    gelesen = await http_client.get(f"/api/v1/rooms/{bereich_api.room_id}/tagesplan")
    assert gelesen.status_code == 200, gelesen.text
    koerper = gelesen.json()
    assert [(f["von"], f["bis"]) for f in koerper["fenster"]] == [
        ("06:00", "08:00"),
        ("08:00", "21:00"),
    ]
    assert koerper["fenster"][0]["temperatur"] == 25.0, (
        '§5.63: eine JSON-Zahl, kein String — sonst rechnet der Browser "25.0" + 1 zu "25.01"'
    )
    assert isinstance(koerper["fenster"][0]["temperatur"], float)


async def test_ein_fenster_bis_vierundzwanzig_uhr_kommt_so_zurueck(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau
) -> None:
    """„bis 24:00" bleibt „24:00" und wird nicht zu „00:00".

    Das ist der Grund fuer die Minuten-Spalten. Als ``time`` gespeichert
    waere das Ende Mitternacht **vor** dem Beginn.
    """
    resp = await http_client.put(
        f"/api/v1/rooms/{bereich_api.room_id}/tagesplan",
        json={"fenster": [{"von": "15:00", "bis": "24:00", "temperatur": 22.0}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fenster"][0]["bis"] == "24:00"


async def test_ein_leerer_plan_loescht_am_endpunkt(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau
) -> None:
    await http_client.put(f"/api/v1/rooms/{bereich_api.room_id}/tagesplan", json=WUNSCH)
    resp = await http_client.put(
        f"/api/v1/rooms/{bereich_api.room_id}/tagesplan", json={"fenster": []}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["fenster"] == []


async def test_dasselbe_zweimal_geschickt_ergibt_dasselbe(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau
) -> None:
    """**§0 S2, Idempotenz.** ``PUT`` ist kein Anlegen.

    Zweimal derselbe Plan darf nicht vier Fenster ergeben — und mit vier
    Fenstern waere es eine Ueberschneidung, also eine 409 beim zweiten
    Speichern.
    """
    erst = await http_client.put(f"/api/v1/rooms/{bereich_api.room_id}/tagesplan", json=WUNSCH)
    zweit = await http_client.put(f"/api/v1/rooms/{bereich_api.room_id}/tagesplan", json=WUNSCH)

    assert erst.status_code == 200, erst.text
    assert zweit.status_code == 200, zweit.text
    assert len(zweit.json()["fenster"]) == 2


async def test_ein_gaestezimmer_bekommt_keinen_plan(
    http_client: httpx.AsyncClient, gastzimmer_api: _Aufbau
) -> None:
    """**Die Schranke.** 422, mit Begruendung im Text.

    Technisch liest die Engine die Tabelle an jedem Zimmer; dass ein
    Gaestezimmer keinen Plan bekommt, entscheidet **dieser** Endpunkt.
    """
    resp = await http_client.put(f"/api/v1/rooms/{gastzimmer_api.room_id}/tagesplan", json=WUNSCH)

    assert resp.status_code == 422, resp.text
    assert "Allgemeinbereiche" in resp.text


async def test_ein_gaestezimmer_darf_gelesen_werden(
    http_client: httpx.AsyncClient, gastzimmer_api: _Aufbau
) -> None:
    """Lesen ist kein Fehler — es gibt dort keinen Plan, und das ist eine Antwort.

    Die Zimmerseite fragt den Plan fuer jedes Zimmer ab; eine 422 waere
    dort ein roter Kasten fuer einen Normalfall.
    """
    resp = await http_client.get(f"/api/v1/rooms/{gastzimmer_api.room_id}/tagesplan")

    assert resp.status_code == 200, resp.text
    assert resp.json()["fenster"] == []


async def test_eine_ueberschneidung_wird_am_endpunkt_abgewiesen(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau
) -> None:
    """422 **und** ein Satz, der die Stelle nennt (§5.64-Familie).

    Ein „unprocessable entity" ohne Text waere eine Fehlermeldung, nach
    der man die Ueberschneidung selbst suchen muss.
    """
    resp = await http_client.put(
        f"/api/v1/rooms/{bereich_api.room_id}/tagesplan",
        json={
            "fenster": [
                {"von": "06:00", "bis": "10:00", "temperatur": 25.0},
                {"von": "08:00", "bis": "21:00", "temperatur": 22.0},
            ]
        },
    )

    assert resp.status_code == 422, resp.text
    assert "ueberschneiden" in resp.text


async def test_ein_fenster_ueber_mitternacht_wird_abgewiesen(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau
) -> None:
    resp = await http_client.put(
        f"/api/v1/rooms/{bereich_api.room_id}/tagesplan",
        json={"fenster": [{"von": "23:00", "bis": "01:00", "temperatur": 22.0}]},
    )

    assert resp.status_code == 422, resp.text
    assert "Mitternacht" in resp.text


async def test_jede_aenderung_steht_im_audit(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau, setup_engine: AsyncEngine
) -> None:
    """**S3.** Mit altem und neuem Stand, in Uhrzeiten.

    Der Eintrag traegt ``von``/``bis`` als Text und nicht als Minutenzahl:
    „360" ist keine Uhrzeit, und das Protokoll liest ein Mensch.
    """
    await http_client.put(f"/api/v1/rooms/{bereich_api.room_id}/tagesplan", json=WUNSCH)
    await http_client.put(
        f"/api/v1/rooms/{bereich_api.room_id}/tagesplan",
        json={"fenster": [{"von": "06:00", "bis": "08:00", "temperatur": 25.0}]},
    )

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        zeilen = (
            (
                await session.execute(
                    select(BusinessAudit)
                    .where(BusinessAudit.action == "ROOM_DAY_PLAN_SET")
                    .where(BusinessAudit.target_id == bereich_api.room_id)
                    .order_by(BusinessAudit.ts)
                )
            )
            .scalars()
            .all()
        )

    assert len(zeilen) == 2, "jede Aenderung schreibt eine Zeile, nicht nur die erste"

    def fenster(wert: object) -> list[dict[str, str]]:
        assert isinstance(wert, dict)
        liste = wert["fenster"]
        assert isinstance(liste, list)
        return liste

    assert fenster(zeilen[0].old_value) == []
    assert fenster(zeilen[0].new_value)[0] == {
        "von": "06:00",
        "bis": "08:00",
        "temperatur": "25.0",
    }
    assert len(fenster(zeilen[1].old_value)) == 2, "der alte Stand ist der von vorher"
    assert len(fenster(zeilen[1].new_value)) == 1


def test_der_endpunkt_traegt_die_rollenpruefung() -> None:
    """**Mutationsprobe.** ``require_admin`` muss am Bauteil haengen.

    Unter ``AUTH_ENABLED=false`` liefert ``get_current_user`` einen
    Admin — eine Anfrage ohne Sitzung belegt hier also nichts (Lehre aus
    24b). Geprueft wird deshalb die Abhaengigkeit selbst: wer die Pruefung
    in die Oberflaeche verlegt und sie hier entfernt, macht diesen Test
    rot.
    """
    sig = inspect.signature(set_tagesplan)
    abhaengigkeiten = [
        p.default.dependency
        for p in sig.parameters.values()
        if isinstance(p.default, params.Depends)
    ]
    assert require_admin in abhaengigkeiten


async def test_ein_unbekanntes_zimmer_ist_vierhundertvier(
    http_client: httpx.AsyncClient,
) -> None:
    resp = await http_client.get("/api/v1/rooms/999999999/tagesplan")
    assert resp.status_code == 404, resp.text


async def test_der_plan_wirkt_ohne_neustart(
    http_client: httpx.AsyncClient, bereich_api: _Aufbau, setup_engine: AsyncEngine
) -> None:
    """**Abschlusskriterium.** Gespeichert, und die Engine rechnet damit.

    Der Weg von der Oberflaeche bis zum Sollwert, in einem Test: ``PUT``,
    dann ``evaluate_room`` zu einer Uhrzeit im Fenster. Zwei gruene Haelften
    beweisen nicht, dass die Naht dazwischen haelt (§5.83).
    """
    resp = await http_client.put(
        f"/api/v1/rooms/{bereich_api.room_id}/tagesplan",
        json={"fenster": [{"von": "06:00", "bis": "08:00", "temperatur": 25.0}]},
    )
    assert resp.status_code == 200, resp.text

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        with freeze_time(f"{TAG}T07:00:00+01:00"):
            ergebnis = await evaluate_room(session, bereich_api.room_id)
        await session.rollback()

    assert ergebnis is not None
    assert ergebnis.setpoint_c == MORGENS


async def test_zwoelf_fenster_lassen_sich_speichern(
    db_session: AsyncSession,
) -> None:
    """Zwoelf Fenster lassen sich speichern — die Grenze ist nicht zu eng.

    ``MAX_FENSTER`` ist eine Aussage ueber die Eingabe und darf den
    Normalfall nicht treffen. Zwoelf halbstuendige Abschnitte sind mehr,
    als ein Haus braucht, und muessen trotzdem gehen.
    """
    room_id = await _bereich(db_session)
    fenster = tuple((f"{stunde:02d}:00", f"{stunde:02d}:30", TAGS) for stunde in range(8, 20))
    await _plan(db_session, room_id, *fenster)

    assert len(await lade_fenster(db_session, room_id)) == 12


async def test_die_engine_liest_den_plan_eines_fremden_zimmers_nicht(
    db_session: AsyncSession,
) -> None:
    """Der Plan der Bar gilt nicht fuer die Rezeption.

    Eine Abfrage ohne ``room_id``-Filter waere gruen, solange nur ein
    Zimmer einen Plan hat — und im Haus hat die Bar als erste einen.
    """
    bar = await _bereich(db_session)
    rezeption = await _bereich(db_session)
    await _plan(db_session, bar, ("06:00", "08:00", MORGENS))
    await _betriebszeit(db_session, rezeption, von="15:00", bis="24:00")

    with freeze_time(f"{TAG}T07:00:00+01:00"):
        ergebnis = await evaluate_room(db_session, rezeption)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == ABSENKUNG, (
        "die Rezeption hat keinen Plan — um 07:00 gilt ihre Absenkung"
    )


async def test_der_plan_wird_nach_beginn_geordnet_gelesen(db_session: AsyncSession) -> None:
    """Die Reihenfolge kommt aus der Abfrage, nicht aus der Eingabe.

    ``fenster_bei`` nimmt das erste passende; ohne stabile Ordnung waere
    die Wahl bei einer (unmoeglichen) Ueberschneidung nicht deterministisch.
    """
    room_id = await _bereich(db_session)
    await _plan(
        db_session,
        room_id,
        ("18:00", "22:00", TAGS),
        ("06:00", "08:00", MORGENS),
        ("08:00", "12:00", TAGS),
    )

    fenster = await lade_fenster(db_session, room_id)
    assert [f.von_text for f in fenster] == ["06:00", "08:00", "18:00"]


async def test_zeitgleiche_zweite_anfrage_laeuft_in_die_bedingung(
    db_session: AsyncSession, setup_engine: AsyncEngine
) -> None:
    """Zwei Sitzungen, beide fuer sich gueltig, zusammen nicht.

    Das ist der Fall, fuer den die ``EXCLUDE``-Bedingung da ist: die
    Pruefung im Schema sieht nur **eine** Anfrage. Die zweite Sitzung
    schreibt ein Fenster, das mit dem der ersten ueberlappt, und die
    Datenbank weist es ab.
    """
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    room_id = await _bereich(db_session)
    await db_session.commit()
    try:
        async with maker() as erste:
            erste.add(
                TagesplanFenster(
                    room_id=room_id, von_minute=360, bis_minute=600, temperatur=Decimal(MORGENS)
                )
            )
            await erste.commit()

        async with maker() as zweite:
            zweite.add(
                TagesplanFenster(
                    room_id=room_id, von_minute=480, bis_minute=720, temperatur=Decimal(TAGS)
                )
            )
            with pytest.raises(IntegrityError):
                await zweite.commit()
    finally:
        async with maker() as aufraeumen:
            room = await aufraeumen.get(Room, room_id)
            room_type_id = room.room_type_id if room else None
            await aufraeumen.execute(
                text("DELETE FROM heating_zone WHERE room_id = :r"), {"r": room_id}
            )
            await aufraeumen.execute(text("DELETE FROM room WHERE id = :r"), {"r": room_id})
            if room_type_id is not None:
                await aufraeumen.execute(
                    text("DELETE FROM room_type WHERE id = :t"), {"t": room_type_id}
                )
            await aufraeumen.commit()


async def test_ein_plan_ohne_luecke_senkt_nie_ab(db_session: AsyncSession) -> None:
    """00:00-24:00 in zwei Fenstern: es gibt keine Absenkung mehr.

    Der Fall ist zulaessig und gewollt — ein Bereich, der durchlaeuft, aber
    morgens waermer. Wichtig ist, dass dann **kein** Absenk-Band im
    Verlauf erscheint und die Engine zu keiner Minute ``t_night`` nimmt.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("00:00", "12:00", MORGENS), ("12:00", "24:00", TAGS))

    with freeze_time(f"{TAG}T03:00:00+01:00"):
        nachts = await evaluate_room(db_session, room_id)
    with freeze_time(f"{TAG}T23:59:00+01:00"):
        spaet = await evaluate_room(db_session, room_id)

    assert nachts is not None and spaet is not None
    assert (nachts.setpoint_c, spaet.setpoint_c) == (MORGENS, TAGS)


async def test_ein_plan_hindert_den_verlauf_am_band(db_session: AsyncSession) -> None:
    """Gegenprobe zum vorigen Test, in der Anzeige.

    **Die Betriebszeit steht hier ausdruecklich**, und zwar eine, die ein
    Band erzeugen wuerde (15:00-24:00, also Absenkung von 00:00 bis
    15:00). Ohne sie waere der Test auch gruen, wenn der Verlauf den Plan
    gar nicht liest — dann faende er einfach kein Nachtfenster. Eine
    leere Erwartung, die aus zwei Gruenden erfuellt sein kann, prueft den
    falschen (Paragraph 5.55).
    """
    room_id = await _bereich(db_session)
    await _betriebszeit(db_session, room_id, von="15:00", bis="24:00")
    await _plan(db_session, room_id, ("00:00", "12:00", MORGENS), ("12:00", "24:00", TAGS))
    room = await db_session.get(Room, room_id)
    assert room is not None

    verlauf = await lade_verlauf(
        db_session, room=room, bereich="24h", jetzt=datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    )

    assert verlauf.night_bands == [], "ein Plan ohne Luecke hat keine Absenkung"


async def test_eine_woche_zeichnet_sieben_naechte(db_session: AsyncSession) -> None:
    """Der 7-Tage-Bereich: die Luecken wiederholen sich je Tag.

    Gerechnet wird ueber die lokalen Kalendertage, einen Tag vor dem
    Fenster beginnend — sonst fehlte das Band, das am Vortag um 21:00
    anfaengt und in das Fenster hineinreicht.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "21:00", TAGS))
    room = await db_session.get(Room, room_id)
    assert room is not None

    verlauf = await lade_verlauf(
        db_session, room=room, bereich="7d", jetzt=datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    )

    # Zwei Luecken je Tag (00:00-06:00, 21:00-24:00) ueber acht beruehrte
    # Kalendertage, am Rand zugeschnitten: mehr als zehn, weniger als 20.
    assert 10 < len(verlauf.night_bands) < 20, len(verlauf.night_bands)
    assert all(b.start < b.end for b in verlauf.night_bands)
    assert all(verlauf.von <= b.start and b.end <= verlauf.bis for b in verlauf.night_bands), (
        "ein Band darf nicht ueber das Fenster hinausragen"
    )


async def test_die_baender_folgen_der_sommerzeit(db_session: AsyncSession) -> None:
    """Am Tag der Rueckstellung bleibt 06:00 die Wanduhrzeit 06:00.

    Das Band endet dort, wo der Betrieb beginnt — und das ist eine
    Wanduhrzeit, nicht ein UTC-Zeitpunkt. ``datetime.combine`` mit
    ``tzinfo`` liefert sie; ein Rechnen mit ``timedelta`` auf Mitternacht
    UTC waere an diesem Tag eine Stunde daneben.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "21:00", TAGS))
    room = await db_session.get(Room, room_id)
    assert room is not None

    # 25.10.2026 ist der Tag der Rueckstellung in Europe/Vienna.
    verlauf = await lade_verlauf(
        db_session, room=room, bereich="24h", jetzt=datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
    )

    enden = {
        b.end.astimezone(ZoneInfo(verlauf.timezone)).strftime("%H:%M") for b in verlauf.night_bands
    }
    assert "06:00" in enden, enden


async def test_der_dienst_committet_nicht(db_session: AsyncSession) -> None:
    """**§5.61.** Die Transaktion gehoert dem Aufrufer.

    Wuerde ``ersetze`` selbst committen, stuende der Plan auch dann in der
    Datenbank, wenn der Audit-Eintrag danach scheitert — eine Aenderung
    ohne Spur.
    """
    room_id = await _bereich(db_session)
    await _plan(db_session, room_id, ("06:00", "08:00", MORGENS))
    await db_session.rollback()

    assert await lade_fenster(db_session, room_id) == []
