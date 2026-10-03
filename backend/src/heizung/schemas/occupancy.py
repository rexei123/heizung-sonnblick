"""Pydantic-Schemas fuer Belegungs-API (Sprint 8)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heizung.models.enums import OccupancySource


class OccupancyCreate(BaseModel):
    """Eingabe fuer POST /api/v1/occupancies."""

    room_id: int = Field(..., gt=0)
    check_in: datetime = Field(..., description="Anreisedatum + Uhrzeit (timezone-aware)")
    check_out: datetime = Field(..., description="Abreisedatum + Uhrzeit (timezone-aware)")
    guest_count: int | None = Field(default=None, ge=1, le=20)
    source: OccupancySource = OccupancySource.MANUAL
    external_id: str | None = Field(
        default=None, max_length=100, description="PMS-Reservierungsnummer (optional)"
    )

    @model_validator(mode="after")
    def _v_dates_ordered(self) -> OccupancyCreate:
        if self.check_in >= self.check_out:
            raise ValueError("check_in muss vor check_out liegen")
        return self


class OccupancyCancel(BaseModel):
    """Eingabe fuer PATCH /api/v1/occupancies/{id} (Storno).

    Sprint 8 erlaubt nur Stornieren via PATCH, keine Daten-Aenderung.
    Storno setzt is_active=False + cancelled_at=NOW.
    """

    cancel: bool = Field(..., description="Muss true sein, sonst kein Effekt")


class OccupancyRead(BaseModel):
    """Ausgabe fuer GET /api/v1/occupancies[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    check_in: datetime
    check_out: datetime
    guest_count: int | None
    source: OccupancySource
    external_id: str | None
    is_active: bool
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OccupancyListResponse(BaseModel):
    """Ausgabe fuer GET /api/v1/occupancies — Envelope, keine nackte Liste.

    Sprint 20d (B-20c-2, AE-75). Belegungen sind die **einzige** Liste im
    Projekt, die unbegrenzt waechst: ein Datensatz je Buchung, taeglicher
    PMS-Import seit dem 06.06.2026, am 02.10.2026 bereits 959 aktive. Sie
    kann deshalb nicht wie Geraete, Zimmer und Raumtypen vom Client in einer
    Schleife vollstaendig geholt werden (Sprint 20c) — sie wird echt
    paginiert.

    Echte Paginierung braucht die **Gesamtzahl**, sonst kann die Oberflaeche
    nicht sagen "100 von 959" und weiss nicht, ob noch etwas kommt. Ohne sie
    waere der Zustand derselbe wie vor 20c: eine Liste, die weniger zeigt als
    da ist, und nichts dazu sagt.

    **Warum die Gesamtzahl im Body steht und nicht in einem Header:**
    ``frontend/src/lib/api/client.ts`` gibt aus ``request<T>`` nur den
    geparsten Body zurueck (``client.ts:60``) — die Response-Header werden
    verworfen. Ein ``X-Total-Count`` kaeme im Frontend also nie an, und das
    waere nicht einmal ein Fehler, der auffaellt: "N von M" wuerde dauerhaft
    "N von 0" anzeigen. Genau diese Falle ist §5.64 (dort hat derselbe
    Wrapper das Feld ``error_code`` verschluckt, weil er nur ``body.detail``
    gelesen hat). Ein Feld im Body erzwingt die Anpassung beim Compiler.

    ``limit`` und ``offset`` kommen mit zurueck, obwohl der Aufrufer sie
    selbst geschickt hat: damit eine Antwort im Log oder im Netzwerk-Tab
    selbsterklaerend ist — wer sie sieht, weiss, **welche** Seite er hat.
    """

    items: list[OccupancyRead]
    total: int = Field(
        ...,
        ge=0,
        description=(
            "Gesamtzahl der Belegungen, die den **gleichen** Filtern entsprechen — "
            "nicht die Laenge von items."
        ),
    )
    limit: int = Field(..., description="Seitengroesse, mit der diese Antwort geholt wurde.")
    offset: int = Field(..., description="Versatz, mit dem diese Antwort geholt wurde.")
