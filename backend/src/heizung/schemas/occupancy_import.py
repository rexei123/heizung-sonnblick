"""Pydantic-Schemas fuer den Belegungs-Import-Webhook (Sprint 15e, AE-66).

Eingabe ist das von mailparser.io erzeugte JSON (Format "Nested - array of
objects", "One request per email"). Strikt: fehlende Pflichtfelder -> 422,
unbekannte Top-Level-Felder werden ignoriert (``extra="ignore"``).

Datums-Konvention der Liste: ``TT.MM.JJJJ``. ``received_at`` ist die naive
Lokal-Zeit (Europe/Vienna) aus mailparser; der Datumsteil ist das
``list_date``. UTC-Konversion passiert erst im Service (§5.65).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DATE_FMT = "%d.%m.%Y"
_RECEIVED_FMT = "%Y-%m-%d %H:%M:%S"


class OccupancyImportEntry(BaseModel):
    """Ein Zeileneintrag der Belegungsliste."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    zimmer: str = Field(alias="Zimmer", min_length=1)
    anreise: date = Field(alias="Anreise")
    abreise: date = Field(alias="Abreise")
    aufenthaltstyp: str | None = Field(default=None, alias="Aufenthaltstyp")

    @field_validator("anreise", "abreise", mode="before")
    @classmethod
    def _parse_de_date(cls, v: object) -> object:
        if isinstance(v, date) and not isinstance(v, datetime):
            return v
        if not isinstance(v, str):
            raise ValueError("Datum muss als String TT.MM.JJJJ kommen")
        try:
            return datetime.strptime(v.strip(), _DATE_FMT).date()
        except ValueError as exc:
            raise ValueError(f"Ungueltiges Datum '{v}', erwartet TT.MM.JJJJ") from exc


class OccupancyImportPayload(BaseModel):
    """Gesamter Webhook-Body (eine E-Mail = ein Request)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1, description="mailparser-Request-ID -> external_id / Idempotenz")
    received_at: datetime = Field(
        description="Naive Lokal-Zeit Europe/Vienna; Datumsteil = list_date"
    )
    liste: list[OccupancyImportEntry] = Field(default_factory=list)

    @field_validator("received_at", mode="before")
    @classmethod
    def _parse_received_at(cls, v: object) -> object:
        if isinstance(v, datetime):
            return v
        if not isinstance(v, str):
            raise ValueError("received_at muss String 'YYYY-MM-DD HH:MM:SS' sein")
        try:
            return datetime.strptime(v.strip(), _RECEIVED_FMT)
        except ValueError as exc:
            raise ValueError(f"Ungueltiges received_at '{v}' (YYYY-MM-DD HH:MM:SS)") from exc


# ---------------------------------------------------------------------------
# Lese-Endpoint (GET .../log) — Vertrag fuer Sprint 2 (Frontend), fix.
# ---------------------------------------------------------------------------


class OccupancyImportLogRow(BaseModel):
    """Ein Eintrag der ``imports``-Liste (letzte 30, neueste zuerst)."""

    received_at: datetime
    list_date: date
    external_id: str
    rooms_occupied: int
    rooms_closed: int
    conflicts: int
    result: str  # "applied" | "rejected"


class OccupancyImportLogResponse(BaseModel):
    """Antwort von GET /api/v1/integrations/occupancy-import/log."""

    status: str  # "green" | "yellow" | "red"
    last_success_at: datetime | None
    expected_by_local: str  # "HH:MM"
    today_received: bool
    imports: list[OccupancyImportLogRow]
