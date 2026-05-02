"""Pydantic-Schemas fuer Szenario-Stammdaten (Sprint 8 Tabelle, UI Sprint 10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScenarioCreate(BaseModel):
    """Eingabe fuer POST /api/v1/scenarios.

    Custom-Szenarien sind Phase 2 — System-Szenarien werden nur via Seed
    angelegt. Endpoint trotzdem hier, damit Custom-Szenarien spaeter ohne
    Code-Aenderung moeglich sind.
    """

    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    is_system: bool = False
    default_active: bool = False
    parameter_schema: dict[str, Any] | None = None
    default_parameters: dict[str, Any] | None = None


class ScenarioUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/scenarios/{id}.

    `code` und `is_system` sind nicht aenderbar — Sicherheits-Vorkehrung
    gegen Veraenderung von System-Stammdaten via API.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    default_active: bool | None = None
    parameter_schema: dict[str, Any] | None = None
    default_parameters: dict[str, Any] | None = None


class ScenarioRead(BaseModel):
    """Ausgabe fuer GET /api/v1/scenarios[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None
    is_system: bool
    default_active: bool
    parameter_schema: dict[str, Any] | None
    default_parameters: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
