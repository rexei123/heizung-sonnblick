"""Nach dem Umschalten liefert die Engine den Raumtyp-Sollwert (Sprint 24c).

**Das Abschlusskriterium, Backend-Hälfte.** Die beiden Pilot-Zimmer
haben vor dem 24.10. einen Sollwert von **10 °C** bekommen: der Layer
Geräte-Sicherheit erkannte die unmontierte Vicki als abgenommen und
erzwang Frostschutz. Mit der Rolle „nur messen" fällt das Gerät aus
dieser Schicht, und der Sollwert des Raumtyps gilt.

Dieser Test fährt die **ganze** Engine (``rules.engine.evaluate_room``),
nicht nur die Schicht. Der Unterschied zählt: die Schicht einzeln zu
prüfen beantwortet nicht, ob am Ende der Pipeline der gewünschte Wert
herauskommt — die Kappung in Layer 5 könnte ihn noch bewegen, und bei
einem Raumtyp mit engen Grenzen täte sie das auch.

**Mutationsprobe M16** greift hier an: Rolle gesetzt, aber die
Geräte-Sicherheit filtert weiter → der Trace bleibt bei 10 °C.

**Nachtrag vom 24.10.2026, und eine Korrektur in eigener Sache.** Die
erste Fassung dieses Tests war einzeln grün und in der vollen Suite rot
mit 18 °C. Ich habe daraus geschlossen, die Bereiche heizten **im Haus**
auf den hausweiten Frei-Sollwert — und das war falsch: die 18 °C kamen
aus dem Seed der **Test**-Datenbank. In der Produktion trägt die
hausweite Zeile für „Belegt" und „Frei" ``NULL``, die Kette fällt dort
also auf die Spalte des Raumtyps durch, und Bar und Rezeption fahren 21
bzw. 19 °C. Eine korrelierte Beobachtung für einen Befund genommen, ohne
die andere Variable zu prüfen (§5.68).

Seit Sprint 24d stehen die Spalten eines **nicht buchbaren** Raumtyps
ohnehin auf ROOM_TYPE-Rang (``rules.engine.bereichs_kette``) und schlagen
damit auch einen gesetzten Hausstandard. Die Hülle unten legt deshalb
**wahlweise** zusätzlich eine ``rule_config``-Zeile an — beide Wege
müssen zum selben Sollwert führen, und ``test_ohne_raumtyp_eintrag...``
hält genau das fest.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind, RuleConfigScope
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.models.sensor_reading import SensorReading
from heizung.rules.engine import FROST_PROTECTION_C, evaluate_room

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24c"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

#: Die beiden echten Raumtypen des Hauses, mit ihren Sollwerten.
BAR_SOLL = 21
REZEPTION_SOLL = 19


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _pilot_zimmer(
    session: AsyncSession,
    *,
    marker: str,
    soll: int,
    measure_only: bool,
    raumtyp_eintrag: bool = True,
) -> int:
    """Ein nicht buchbares Zimmer mit einer unmontierten Vicki.

    Der Aufbau ist der von „Bar" und „Rezeption": Raumtyp nicht buchbar,
    eine Zone, ein Gerät, das zwei frische Frames mit
    ``attached_backplate=False`` meldet — es liegt auf dem Tisch.

    ``Room.number`` ist ``VARCHAR(20)`` (§5.49): ``t24c`` (4) + Marker
    (<= 4) + 4 Hex + zwei Trenner = höchstens 14 Zeichen.
    """
    short = uuid.uuid4().hex[:4]
    rt = RoomType(
        name=f"{PREFIX}-rt-{marker}-{short}",
        is_bookable=False,
        # Alle drei Sollwerte auf denselben Wert: das Zimmer ist nicht
        # buchbar, also gibt es kein "belegt" und kein "frei" im Sinne
        # einer Buchung. Welchen Zweig Layer 1 nimmt, soll das Ergebnis
        # dieses Tests nicht verschieben.
        default_t_occupied=Decimal(soll),
        default_t_vacant=Decimal(soll),
        default_t_night=Decimal(soll),
    )
    session.add(rt)
    await session.flush()

    # **Der Eintrag, der den Sollwert wirklich setzt.** Ohne ihn gewinnt
    # die hausweite GLOBAL-Zeile (siehe Kopf) — die Spalten oben sind nur
    # die Vorgabe *unter* GLOBAL. ``raumtyp_eintrag=False`` prüft genau
    # diesen Fall.
    if raumtyp_eintrag:
        session.add(
            RuleConfig(
                scope=RuleConfigScope.ROOM_TYPE,
                room_type_id=rt.id,
                t_occupied=Decimal(soll),
                t_vacant=Decimal(soll),
                t_night=Decimal(soll),
            )
        )
        await session.flush()

    room = Room(number=f"{PREFIX}-{marker}-{short}", room_type_id=rt.id)
    session.add(room)
    await session.flush()

    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
    session.add(zone)
    await session.flush()

    dev = Device(
        dev_eui=f"beef{uuid.uuid4().hex[:12]}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"{marker}-fuehler",
        heating_zone_id=zone.id,
        health_state="healthy",
        measure_only=measure_only,
    )
    session.add(dev)
    await session.flush()

    jetzt = datetime.now(tz=UTC)
    for minuten in (10, 5):
        session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=minuten),
                device_id=dev.id,
                temperature=Decimal("20.0"),
                # Unmontiert: zwei frische, übereinstimmende Frames. Genau
                # die Bedingung, die die Schicht als "abgenommen" liest.
                attached_backplate=False,
            )
        )
    await session.flush()
    return room.id


# ---------------------------------------------------------------------------
# Das Abschlusskriterium
# ---------------------------------------------------------------------------


async def test_bar_liefert_21_statt_10(db_session: AsyncSession) -> None:
    """Zimmer „Bar", Raumtyp „Raum intern" (21 °C), Fühler-Rolle gesetzt."""
    room_id = await _pilot_zimmer(db_session, marker="bar", soll=BAR_SOLL, measure_only=True)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BAR_SOLL, (
        f"erwartet {BAR_SOLL} °C aus dem Raumtyp, bekommen {ergebnis.setpoint_c} °C"
    )
    assert ergebnis.setpoint_c != FROST_PROTECTION_C


async def test_rezeption_liefert_19_statt_10(db_session: AsyncSession) -> None:
    """Zimmer „Rezeption", Raumtyp „Raum mit Exit" (19 °C).

    Der zweite Wert ist nicht Fleiß: er hält fest, dass der Sollwert aus
    dem **Raumtyp** kommt und nicht aus einer Konstante, die zufällig 21
    ist.
    """
    room_id = await _pilot_zimmer(db_session, marker="rez", soll=REZEPTION_SOLL, measure_only=True)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == REZEPTION_SOLL


async def test_ohne_rolle_bleibt_es_bei_10(db_session: AsyncSession) -> None:
    """**Mutationsprobe M16 in Testform — und der Befund vom 24.10.**

    Dasselbe Zimmer, dieselben Frames, nur **ohne** die Rolle: hier
    **muss** der Frostschutz greifen. Ohne diesen Test beweisen die
    beiden oben nichts — sie wären auch grün, wenn die Schicht aus einem
    anderen Grund nicht triggert.

    Und er beschreibt genau den Zustand, in dem „Bar" und „Rezeption"
    vor dem 24.10. waren.
    """
    room_id = await _pilot_zimmer(db_session, marker="ohne", soll=BAR_SOLL, measure_only=False)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == FROST_PROTECTION_C, (
        "ohne die Rolle muss die Geräte-Sicherheit weiter Frostschutz erzwingen"
    )


async def test_die_schicht_fuehrt_den_fuehler_nicht_als_abgenommen(
    db_session: AsyncSession,
) -> None:
    """Auch der Trace soll ihn nicht nennen.

    ``detached_devices`` landet im Schicht-Trace, und der Hotelier liest
    ihn. Ein Fühler, der dort als abgenommen steht, ist ein Befund, der
    keiner ist — und er verdeckt die echten.
    """
    room_id = await _pilot_zimmer(db_session, marker="trc", soll=BAR_SOLL, measure_only=True)

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    detached = [s for s in ergebnis.layers if s.layer.value == "device_detached"]
    assert len(detached) == 1, "die Schicht schreibt immer einen Schritt (§5.23)"
    assert detached[0].extras["detached_devices"] == []
    assert detached[0].detail == "no_devices_in_zone"


async def test_ohne_raumtyp_eintrag_gilt_die_spalte(db_session: AsyncSession) -> None:
    """**Beide Wege führen zum selben Wert** (Sprint 24d).

    Dasselbe Zimmer mit Fühler-Rolle, aber **ohne** ``rule_config``-Zeile
    im Scope ``ROOM_TYPE``. Seit 24d stehen die Spalten eines nicht
    buchbaren Raumtyps selbst auf diesem Rang — der hausweite Wert
    verliert also auch dann, wenn er gesetzt ist.

    Der Test setzt den hausweiten Frei-Sollwert ausdrücklich auf etwas
    anderes, damit er die **Rangfolge** prüft und nicht die Einstellung
    des Hauses. Die Sitzung wird zurückgerollt; der Stand des Hauses
    bleibt unberührt.

    In der ersten Fassung (24c) erwartete dieser Test hier den hausweiten
    Wert. Das war die Rangfolge **vor** diesem Sprint, und sie galt für
    Bereiche genauso wie für Gästezimmer.
    """
    hausweit = 16
    assert hausweit != BAR_SOLL, "sonst prüft der Test nicht, welcher Scope gewinnt"

    zeile = (
        await db_session.execute(
            select(RuleConfig)
            .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
            .where(RuleConfig.room_type_id.is_(None))
            .where(RuleConfig.room_id.is_(None))
            .where(RuleConfig.season_id.is_(None))
        )
    ).scalar_one_or_none()
    if zeile is None:
        zeile = RuleConfig(scope=RuleConfigScope.GLOBAL)
        db_session.add(zeile)
    zeile.t_vacant = Decimal(hausweit)
    await db_session.flush()

    room_id = await _pilot_zimmer(
        db_session,
        marker="glob",
        soll=BAR_SOLL,
        measure_only=True,
        raumtyp_eintrag=False,
    )

    ergebnis = await evaluate_room(db_session, room_id)

    assert ergebnis is not None
    assert ergebnis.setpoint_c == BAR_SOLL, (
        "die Spalte eines Allgemeinbereichs schlaegt den Hausstandard"
    )
    assert ergebnis.setpoint_c != FROST_PROTECTION_C, "die Rolle wirkt trotzdem"
