"""Welche Heizzone ein Zimmer in der Uebersicht vertritt (15.10.2026).

Die Zimmeruebersicht zeigt **eine** Ist- und eine Soll-Temperatur je
Zimmer. Ein Zimmer hat aber zwei bis drei Zonen (Schlafzimmer, Bad,
teils Kinderzimmer oder ein zweites Schlafzimmer), und die haben
verschiedene Werte. Es braucht also eine Regel, welche Zone die Zeile
vertritt.

**Die Regel ist eine Betriebsentscheidung, keine Ableitung** (Hotelier,
15.10.2026): es ist das **Schlafzimmer**. Dort schlafen die Gaeste, dort
wird eine zu kalte Temperatur zuerst bemerkt. Nicht das Bad (das laeuft
waermer) und nicht das Kinderzimmer (oft unbelegt).

**Warum die Regel hier steht und nicht im Frontend:** sie haengt an den
Zonen-Namen, und die kommen aus der Zimmerliste des Hauses
(``scripts/seed_data/Zimmerliste_seed.csv``, Spalte ``Zone_Label`` ->
``heating_zone.name``). Wer sie im Frontend aus den geladenen Zonen
erraet, muss dort die Namen kennen — und bei der naechsten Suite mit
einem neuen Label raet er falsch, ohne dass es auffaellt.

**Warum nicht ueber ``kind``:** ``HeatingZoneKind.BEDROOM`` trifft auch
das Kinderzimmer (``seed_rooms.KIND_MAP``: beide auf ``bedroom``). Der
Name ist das einzige Merkmal, das die beiden trennt.

**Bestand am 15.10.2026** (gemessen an der Seed-Liste, 45 Zimmer,
103 Zonen):

====================  =======  =========================================
Label                 Anzahl   Vorkommen
====================  =======  =========================================
``Schlafzimmer``      41       alle Zimmer ausser den vier Suiten unten
``Schlafzimmer L``    4        52, 54, 102, 202 (zwei Schlafzimmer)
``Schlafzimmer R``    4        dieselben vier
``Kinderzimmer``      9        107, 115, 207, 215, 302, 303, 306, 310, 401
``Bad``               45       jedes Zimmer
====================  =======  =========================================

Damit ist jedes der 45 Zimmer abgedeckt (41 + 4). **Der Fall „Zimmer
ohne Schlafzimmer" kommt heute nicht vor** — er ist trotzdem
implementiert und getestet, weil die Oberflaeche dann „–" zeigen muss
und nicht abstuerzen darf (eine neue Zone kommt ueber die Oberflaeche
dazu, nicht ueber die Seed-Liste).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.heating_zone import HeatingZone

#: Namen der Referenzzone in **Prioritaets-Reihenfolge**.
#:
#: ``Schlafzimmer L`` kommt nach dem einfachen ``Schlafzimmer``, weil die
#: vier Suiten mit zwei Schlafzimmern kein einfaches tragen — die
#: Reihenfolge ist also nicht „L vor R", sondern „ein Schlafzimmer, wenn
#: es eines gibt, sonst das linke". ``Schlafzimmer R`` steht bewusst
#: **nicht** in der Liste: es ist nie die Referenz, sonst waere die
#: Auswahl von der Zonen-Reihenfolge in der Datenbank abhaengig.
REFERENZ_NAMEN: tuple[str, ...] = ("Schlafzimmer", "Schlafzimmer L")


def waehle_referenzzone(zonen: Sequence[tuple[int, str]]) -> int | None:
    """Die Referenzzone aus den Zonen **eines** Zimmers.

    ``zonen`` sind ``(zone_id, name)``-Paare in beliebiger Reihenfolge.
    Rueckgabe ist die ``zone_id`` oder ``None``, wenn das Zimmer keine
    Zone mit einem Namen aus :data:`REFERENZ_NAMEN` hat.

    Reine Funktion ohne Datenbank — damit die Regel ohne Postgres
    pruefbar ist (die Tests dazu laufen auch ohne ``TEST_DATABASE_URL``).

    Bei mehreren Zonen gleichen Namens — das Schema verbietet es
    (``uq_heating_zone_room_name``), aber die Funktion sieht das Schema
    nicht — gewinnt die **kleinere** ``zone_id``, damit die Auswahl
    deterministisch ist (S2) und nicht an der Query-Reihenfolge haengt.
    """
    for name in REFERENZ_NAMEN:
        treffer = [zid for zid, zname in zonen if zname == name]
        if treffer:
            return min(treffer)
    return None


async def referenzzonen_pro_zimmer(
    session: AsyncSession,
    room_ids: Iterable[int],
) -> dict[int, int]:
    """Pro Zimmer die ``zone_id`` der Referenzzone.

    **Eine** Query ueber alle uebergebenen Zimmer (kein N+1, Pattern wie
    ``override_service.get_rooms_with_active_override``). Zimmer ohne
    Referenzzone fehlen im Ergebnis — der Konsument leitet auf ``None``.

    Gefiltert wird bereits in SQL auf :data:`REFERENZ_NAMEN`; die
    Auswahl zwischen ``Schlafzimmer`` und ``Schlafzimmer L`` trifft
    danach :func:`waehle_referenzzone`, damit die Prioritaet an **einer**
    Stelle steht und nicht halb im SQL.
    """
    ids = list(room_ids)
    if not ids:
        return {}

    stmt = select(HeatingZone.room_id, HeatingZone.id, HeatingZone.name).where(
        HeatingZone.room_id.in_(ids),
        HeatingZone.name.in_(REFERENZ_NAMEN),
    )
    rows = (await session.execute(stmt)).all()

    pro_zimmer: dict[int, list[tuple[int, str]]] = {}
    for room_id, zone_id, name in rows:
        pro_zimmer.setdefault(room_id, []).append((zone_id, name))

    ergebnis: dict[int, int] = {}
    for room_id, zonen in pro_zimmer.items():
        gewaehlt = waehle_referenzzone(zonen)
        if gewaehlt is not None:
            ergebnis[room_id] = gewaehlt
    return ergebnis
