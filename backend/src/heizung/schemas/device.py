"""Pydantic-Schemas fuer Devices-API."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from heizung.models.enums import DeviceKind, DeviceVendor

_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")


def _normalize_eui(value: str | None) -> str | None:
    """LoRaWAN-EUIs konsistent in lowercase-hex speichern."""
    if value is None:
        return None
    if not _HEX16.fullmatch(value):
        raise ValueError("EUI muss 16 Hex-Zeichen sein")
    return value.lower()


class DeviceCreate(BaseModel):
    """Eingabe fuer POST /api/v1/devices."""

    dev_eui: str = Field(
        ..., description="LoRaWAN DevEUI (8 Byte hex, 16 Zeichen, case-insensitive)"
    )
    app_eui: str | None = Field(
        default=None, description="LoRaWAN AppEUI/JoinEUI (optional, 16 Hex-Zeichen)"
    )
    kind: DeviceKind = Field(..., description="thermostat | sensor")
    vendor: DeviceVendor = Field(..., description="mclimate | milesight | manual")
    model: str = Field(..., min_length=1, max_length=50)
    label: str | None = Field(default=None, max_length=200)
    heating_zone_id: int | None = Field(
        default=None,
        description="FK auf heating_zone.id; NULL solange ungeordnet (Provisioning).",
    )
    is_active: bool = True

    @field_validator("dev_eui")
    @classmethod
    def _v_dev_eui(cls, v: str) -> str:
        return _normalize_eui(v) or v  # type: ignore[return-value]

    @field_validator("app_eui")
    @classmethod
    def _v_app_eui(cls, v: str | None) -> str | None:
        return _normalize_eui(v)


class DeviceUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/devices/{id}. Alle Felder optional."""

    app_eui: str | None = None
    kind: DeviceKind | None = None
    vendor: DeviceVendor | None = None
    model: str | None = Field(default=None, min_length=1, max_length=50)
    label: str | None = Field(default=None, max_length=200)
    heating_zone_id: int | None = None
    is_active: bool | None = None

    @field_validator("app_eui")
    @classmethod
    def _v_app_eui(cls, v: str | None) -> str | None:
        return _normalize_eui(v)


class DeviceRead(BaseModel):
    """Ausgabe fuer GET /api/v1/devices und /devices/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    dev_eui: str
    app_eui: str | None
    kind: DeviceKind
    vendor: DeviceVendor
    model: str
    label: str | None
    heating_zone_id: int | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime
