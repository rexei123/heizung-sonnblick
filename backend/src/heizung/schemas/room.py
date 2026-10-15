"""Pydantic-Schemas fuer Zimmer-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from heizung.models.enums import Orientation, RoomStatus


class RoomCreate(BaseModel):
    """Eingabe fuer POST /api/v1/rooms."""

    number: str = Field(..., min_length=1, max_length=20, description="Zimmernummer (eindeutig)")
    display_name: str | None = Field(default=None, max_length=100)
    room_type_id: int = Field(..., gt=0)
    floor: int | None = Field(default=None, ge=-5, le=50)
    orientation: Orientation | None = None
    notes: str | None = Field(default=None, max_length=1000)


class RoomUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/rooms/{id}. Alle Felder optional.

    `status` ist hier zugaenglich, aber wird normal vom OccupancyService
    automatisch gesetzt. Manueller Eingriff fuer BLOCKED/CLEANING moeglich.
    """

    number: str | None = Field(default=None, min_length=1, max_length=20)
    display_name: str | None = Field(default=None, max_length=100)
    room_type_id: int | None = Field(default=None, gt=0)
    floor: int | None = Field(default=None, ge=-5, le=50)
    orientation: Orientation | None = None
    status: RoomStatus | None = None
    notes: str | None = Field(default=None, max_length=1000)


class RoomRead(BaseModel):
    """Ausgabe fuer GET /api/v1/rooms[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    display_name: str | None
    room_type_id: int
    floor: int | None
    orientation: Orientation | None
    status: RoomStatus
    guest_override_blocked: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime

    # Sprint 14d (R-A): Bool-Indikator „Zimmer hat >= 1 aktive Uebersteuerung"
    # fuer die Zimmer-Liste. Default False; NUR der Listen-Endpoint
    # (``list_rooms``) befuellt ihn via Batch-Aggregat
    # (``override_service.get_rooms_with_active_override``). Einzel-/Write-
    # Responses (get/create/update) lassen ihn auf False — dort nicht
    # konsumiert (RoomTable liest ausschliesslich die Liste).
    has_active_override: bool = False

    # ------------------------------------------------------------------
    # Ist und Soll der Referenzzone (15.10.2026)
    # ------------------------------------------------------------------
    # Die Uebersicht zeigt eine Temperatur je Zimmer, ein Zimmer hat aber
    # zwei bis drei Zonen. Welche die Zeile vertritt, entscheidet
    # ``services/referenzzone`` — eine feste Regel im Backend, weil sie an
    # den Zonen-Namen des Hauses haengt (dort steht die Begruendung).
    #
    # Wie ``has_active_override`` befuellt **nur** der Listen-Endpoint diese
    # Felder, per Batch-Aggregat. Einzel- und Write-Responses lassen sie auf
    # ``None`` — dort liest sie niemand, und die Zimmerseite hat die Werte
    # ohnehin je Zone (``HeatingZoneRead.mean_temperature_c`` /
    # ``engine_setpoint_c``, Sprint 14e FU-1/FU-2).

    #: Die Zone, aus der ``mean_temperature_c`` stammt. Steht in der Antwort,
    #: damit nachvollziehbar ist, **welches** Zimmer gemessen wurde — ohne
    #: dieses Feld waere ein falscher Ist-Wert nicht zuzuordnen.
    reference_zone_id: int | None = None

    #: Ist: juengster Zonen-Mittelwert ueber die gesunden, aktiven Vickis der
    #: Referenzzone (AE-51 §4.1, ``services/zone_aggregates``). Bei einer Zone
    #: mit genau einem Geraet ist das der Messwert dieses Geraets.
    mean_temperature_c: Decimal | None = None

    #: Soll: der juengste ``HARD_CLAMP``-Setpoint des **Zimmers** im
    #: 1-h-Fenster (``services/event_log``) — die Ausgabe der Engine selbst,
    #: also inklusive Vorheizen, Nachtabsenkung, zimmerweiter Uebersteuerung,
    #: Fenster-Sicherheit und Hard-Clamp. **Nicht** der vom Geraet gemeldete
    #: Wert.
    #:
    #: **Grenze, bewusst so:** einen *je Zone* abweichenden Sollwert gibt es
    #: nur bei einer **zonen-bezogenen** Uebersteuerung (AE-58 Option G); der
    #: wird beim Versand je Zone aufgesetzt und **nicht** persistiert. Die
    #: Liste zeigt dann den Zimmer-Wert, und die Spalte „Uebersteuerung"
    #: derselben Zeile sagt, dass dort eine aktive liegt. Dasselbe Feld und
    #: derselbe Helfer wie auf der Zimmerseite — damit koennen die zwei
    #: Ansichten nicht auseinanderlaufen (§5.53).
    engine_setpoint_c: Decimal | None = None

    @field_serializer("mean_temperature_c", "engine_setpoint_c")
    def _decimal_temp_to_float(self, v: Decimal | None) -> float | None:
        # §5.63: Decimal -> JSON-Zahl, nicht String. Symmetrisch zu
        # ``HeatingZoneRead._decimal_temp_to_float`` — dieselben Werte,
        # dieselbe Form.
        return None if v is None else float(v)


class RoomOverrideBlockUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/rooms/{id}/override-block-state (Sprint 12c).

    Eigener Endpoint statt Erweiterung von ``RoomUpdate``: Toggle hat
    eigene Audit-Action und Auto-Revoke-Semantik (siehe AE-58 Sprint 12c).
    """

    model_config = ConfigDict(extra="forbid")

    blocked: bool
