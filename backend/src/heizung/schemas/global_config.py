"""Pydantic-Schemas fuer global_config-API (Sprint 8, Singleton)."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class GlobalConfigUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/global-config. Alle Felder optional.

    Mindestens 1 Feld noetig — sonst 422 (gepruegt in der Service-Layer).
    """

    hotel_name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=3, max_length=50)
    default_checkin_time: time | None = None
    default_checkout_time: time | None = None
    # Sprint 9.16: ``summer_mode_active`` ist auf ``scenario_assignment``
    # umgezogen (AE-49). Aktivierung erfolgt ueber den
    # /api/v1/scenarios/{code}/activate-Endpoint, nicht mehr hier.
    summer_mode_starts_on: date | None = None
    summer_mode_ends_on: date | None = None
    alert_email: EmailStr | None = None
    alert_device_offline_minutes: int | None = Field(default=None, ge=1, le=1440)
    alert_battery_warn_percent: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _v_summer_dates_consistency(self) -> GlobalConfigUpdate:
        # Wenn EINES der Daten gesetzt wird, muss das andere auch gesetzt sein
        # ODER beide sind None. Patch-Semantik: das Feld bleibt unveraendert
        # wenn es im Payload fehlt — diese Pruefung greift nur wenn der User
        # explizit eines der beiden setzt aber nicht das andere.
        # Vollstaendige Konsistenz ist DB-Constraint (ck_global_config_summer_dates).
        if (
            self.summer_mode_starts_on is not None
            and self.summer_mode_ends_on is not None
            and self.summer_mode_starts_on > self.summer_mode_ends_on
        ):
            raise ValueError("summer_mode_starts_on muss <= summer_mode_ends_on sein")
        return self


class GlobalConfigRead(BaseModel):
    """Ausgabe fuer GET /api/v1/global-config."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    hotel_name: str
    timezone: str
    default_checkin_time: time
    default_checkout_time: time
    summer_mode_starts_on: date | None
    summer_mode_ends_on: date | None
    alert_email: str | None
    alert_device_offline_minutes: int
    alert_battery_warn_percent: int
    created_at: datetime
    updated_at: datetime
