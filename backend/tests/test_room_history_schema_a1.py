"""Sprint 21 A1 — die Struktur der Verlauf-Antwort, ohne Datenbank.

Zwei Zusicherungen, die nichts mit Messdaten zu tun haben und deshalb
hier statt in ``test_room_history_a1.py`` stehen (dort gilt
``pytestmark = asyncio``):

1. **Decimal kommt als Zahl im JSON an.** Der Hotfix #272 war genau
   dieser Fehler an anderer Stelle.
2. **Ein Nachtfenster ueber Mitternacht ist zulaessig**, nicht ein
   Eingabefehler.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from heizung.models.enums import HeatingZoneKind
from heizung.schemas.room_history import (
    HistoryPunkt,
    HistoryZone,
    NachtFenster,
    RoomHistoryRead,
)

JETZT = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)


def test_decimal_wird_als_zahl_ausgegeben() -> None:
    """**Der Hotfix #272 als Testwand.**

    Pydantic gibt ``Decimal`` ohne ``field_serializer`` als Zeichenkette
    aus (``"21.40"``). Ein Diagramm zeichnet daraus eine Linie auf 0, ohne
    zu klagen — und genau deshalb prueft dieser Test den **Typ im JSON**
    und nicht den Wert im Modell.
    """
    antwort = RoomHistoryRead(
        room_id=1,
        range="24h",
        bucket_minutes=10,
        range_from=JETZT - timedelta(hours=24),
        range_to=JETZT,
        timezone="Europe/Vienna",
        night_window=None,
        zones=[
            HistoryZone(
                zone_id=7,
                name="Schlafzimmer",
                kind=HeatingZoneKind.BEDROOM,
                points=[
                    HistoryPunkt(t=JETZT, temperature=Decimal("21.40"), setpoint=Decimal("18.00")),
                    HistoryPunkt(t=JETZT, temperature=None, setpoint=None),
                ],
            )
        ],
    )

    rohdaten = json.loads(antwort.model_dump_json())
    punkt = rohdaten["zones"][0]["points"][0]
    assert isinstance(punkt["temperature"], float), punkt
    assert isinstance(punkt["setpoint"], float), punkt
    assert punkt["temperature"] == 21.4

    leer = rohdaten["zones"][0]["points"][1]
    assert leer["temperature"] is None, "None bleibt None und wird nicht 0.0"
    assert leer["setpoint"] is None


def test_nachtfenster_ueber_mitternacht_ist_zulaessig() -> None:
    """``22:00`` bis ``06:00`` ist der Normalfall und kein Fehler.

    Das Schema darf ``start > end`` nicht verbieten — die Engine rechnet
    dasselbe Fenster (``engine.py:_is_in_night_window``), und wer hier eine
    Pruefung einbaut, bricht die Nachtabsenkung des Hauses.
    """
    fenster = NachtFenster(start=time(22, 0), end=time(6, 0))
    rohdaten = json.loads(fenster.model_dump_json())
    assert rohdaten == {"start": "22:00:00", "end": "06:00:00"}
