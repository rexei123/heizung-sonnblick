"""Pydantic-Schemas fuer Manual-Override-API (Sprint 9.9, Engine Layer 3).

Erlaubt im ``Create``-Schema **nicht** die Quelle ``device`` — Drehring-
Overrides werden ausschliesslich vom ``device_adapter`` aus dem MQTT-
Subscriber-Pfad erzeugt; das Frontend setzt nur ``frontend_*``-Quellen.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from heizung.models.enums import OverrideSource

FrontendOverrideSource = Literal[
    "frontend_4h",
    "frontend_midnight",
    "frontend_checkout",
]


class ManualOverrideCreate(BaseModel):
    """Eingabe fuer ``POST /api/v1/rooms/{room_id}/overrides``."""

    setpoint: Decimal = Field(
        ...,
        ge=Decimal("5.0"),
        le=Decimal("30.0"),
        description="Soll-Setpoint in degC, 1 Nachkommastelle (5.0 bis 30.0).",
    )
    source: FrontendOverrideSource = Field(
        ...,
        description="Override-Quelle. 'device' ist intern reserviert "
        "(device_adapter) und im Create-Schema bewusst nicht erlaubt.",
    )
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("setpoint", mode="after")
    @classmethod
    def _quantize_setpoint(cls, v: Decimal) -> Decimal:
        """Quantize auf 1 Nachkommastelle (Banker's Rounding, ROUND_HALF_EVEN).

        Beispiel: ``21.55 -> 21.6``, ``21.45 -> 21.4`` (halb gerade).
        """
        return v.quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)


class ManualOverrideRevoke(BaseModel):
    """Eingabe fuer ``DELETE /api/v1/overrides/{id}``."""

    revoked_reason: str | None = Field(default=None, max_length=500)


class ManualOverrideResponse(BaseModel):
    """Ausgabe fuer GET-Endpoints. Bildet ``ManualOverride``-ORM 1:1 ab."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    setpoint: Decimal
    source: OverrideSource
    expires_at: datetime
    reason: str | None
    created_at: datetime
    created_by: str | None
    revoked_at: datetime | None
    revoked_reason: str | None
