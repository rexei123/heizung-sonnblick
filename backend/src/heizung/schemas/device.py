"""Pydantic-Schemas fuer Devices-API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

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
        normalized = _normalize_eui(v)
        # _normalize_eui validiert + lowercased; bei valid-Input nie None.
        # `or v` ist Defensiv-Fallback, falls _normalize_eui sich aendert.
        return normalized if normalized is not None else v

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
    firmware_version: str | None = None
    created_at: datetime
    updated_at: datetime


class DeviceAssignZoneRequest(BaseModel):
    """Request body fuer PUT /api/v1/devices/{device_id}/heating-zone."""

    heating_zone_id: int = Field(..., gt=0, description="Ziel-Heizzone")

    model_config = ConfigDict(extra="forbid")


class DeviceAssignZoneResponse(BaseModel):
    """Response fuer PUT und DELETE - heating_zone_id ist None nach Detach.

    ``device_id`` ist als alias auf ``Device.id`` gemappt; der Parameter-Pfad
    der API spricht von ``device_id``, das ORM-Feld heisst nur ``id``.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    device_id: int = Field(..., validation_alias="id")
    dev_eui: str
    heating_zone_id: int | None
    label: str | None
    updated_at: datetime


class HardwareStatusResponse(BaseModel):
    """Hardware-Status-Snapshot fuer ein Geraet (Sprint 9.13c, B-LT-2-followup-1).

    Bewertet die letzten ``window_minutes`` Minuten ``sensor_reading``-Frames
    auf das Vicki-Codec-Feld ``attached_backplate``. Datenquelle ist dieselbe
    wie fuer Engine-Layer-4-Detached, aber als reine Lese-Aggregation
    (kein Engine-Pfad, kein Cache).
    """

    status: Literal["active", "inactive"] = Field(
        ...,
        description="active wenn mindestens ein True-Frame im Fenster, sonst inactive",
    )
    last_seen: datetime | None = Field(
        default=None,
        description="Juengster Frame mit attached_backplate=true im Fenster (None falls keiner)",
    )
    frames_in_window: int = Field(
        ...,
        ge=0,
        description="Anzahl Frames mit attached_backplate IS NOT NULL im Fenster",
    )
    window_minutes: int = Field(
        ...,
        gt=0,
        description="Fenster-Groesse in Minuten (heute 30, Quelle: WINDOW_STALE_THRESHOLD_MIN)",
    )
