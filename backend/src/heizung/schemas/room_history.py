"""Antwort-Schema fuer den Zimmer-Verlauf (Sprint 21 A1).

Der Verlauf ist **serverseitig zusammengefasst**: 24 Stunden in
Zehn-Minuten-Eimern, 7 Tage in Stunden-Eimern. Das ist keine Optimierung
nebenbei, sondern der Punkt — bei vier Geraeten und Zehn-Minuten-Takt
liegen in einer Woche rund 4000 Messwerte je Zimmer, und ein Diagramm, das
sie alle zieht, zeichnet Rauschen und laedt lange.

**Decimal als Zahl, nicht als Zeichenkette.** Jedes Temperatur-Feld hat
einen ``field_serializer`` auf ``float``, wie im Haus ueblich
(``schemas/device.py``). Der Hotfix #272 war genau dieser Fehler an anderer
Stelle: Pydantic gibt ``Decimal`` sonst als ``"21.40"`` aus, und ein
Diagramm zeichnet daraus eine Linie auf 0, ohne zu klagen. Ein
struktureller Test haelt das fest.
"""

from datetime import datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer

from heizung.models.enums import HeatingZoneKind


class HistoryPunkt(BaseModel):
    """Ein Eimer einer Zone: Mittel der Ist-Temperatur, Maximum des Sollwerts."""

    model_config = ConfigDict(from_attributes=True)

    t: datetime
    temperature: Decimal | None = None
    setpoint: Decimal | None = None

    @field_serializer("temperature", "setpoint")
    def _decimal_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None


class HistoryZone(BaseModel):
    """Eine Linie je Zone. Zonen ohne Messwerte im Fenster kommen mit
    leerer ``points``-Liste mit — sonst verschwindet eine Zone aus der
    Legende, und der Leser haelt sie fuer nicht vorhanden statt fuer
    stumm."""

    zone_id: int
    name: str
    kind: HeatingZoneKind
    points: list[HistoryPunkt]


class NachtFenster(BaseModel):
    """Aufgeloestes Nachtfenster in **Ortszeit** (``timezone`` unten).

    Aufgeloest heisst: durch die Kette ROOM > ROOM_TYPE > GLOBAL gelaufen
    (``rules/config_resolve``), also derselbe Wert, nach dem die Engine
    regelt. ``start > end`` ist zulaessig und normal (22:00 bis 06:00).
    """

    start: time
    end: time


class NachtBand(BaseModel):
    """Eine Absenkungs-Phase als **Zeitspanne** (UTC), schon auf das Fenster
    zugeschnitten.

    Der Unterschied zu ``NachtFenster`` oben: dort steht die
    Konfiguration (``22:00:00``), hier stehen die tatsaechlichen Phasen im
    Fenster (``2026-10-07T20:00:00Z`` bis ``...T04:00:00Z``). Die
    Oberflaeche zeichnet diese Liste und rechnet nichts um — die Umrechnung
    Ortszeit -> UTC samt Sommerzeit macht der Server mit ``zoneinfo``,
    dieselbe Bibliothek wie die Engine (§5.65).
    """

    start: datetime
    end: datetime


class RoomHistoryRead(BaseModel):
    """Der Verlauf eines Zimmers fuer ein Zeitfenster.

    ``range_from``/``range_to`` sind UTC-Zeitstempel und begrenzen das
    Fenster halboffen (``>= from``, ``< to``). Sie stehen in der Antwort,
    damit die Oberflaeche nicht selbst rechnet, was der Server gemeint hat
    — und damit ein Beleg aus einer Datei spaeter noch einzuordnen ist.

    ``timezone`` gehoert dazu, weil ``night_window`` Ortszeit ist. Eine
    Uhrzeit ohne ihre Zone neben einer anderen Uhrzeit ist die Falle aus
    §5.79: dort hat genau das zu einer falsch gesetzten Schwelle gefuehrt.
    """

    room_id: int
    range: Literal["24h", "7d"]
    bucket_minutes: int
    range_from: datetime
    range_to: datetime
    timezone: str
    night_window: NachtFenster | None = None
    night_bands: list[NachtBand] = []
    zones: list[HistoryZone]
