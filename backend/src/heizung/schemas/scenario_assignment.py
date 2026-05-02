"""Pydantic-Schemas fuer Szenario-Aktivierung (Sprint 8 Tabelle, UI Sprint 10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from heizung.models.enums import ScenarioScope


class ScenarioAssignmentCreate(BaseModel):
    """Eingabe fuer POST /api/v1/scenario-assignments."""

    scenario_id: int = Field(..., gt=0)
    scope: ScenarioScope
    room_type_id: int | None = Field(default=None, gt=0)
    room_id: int | None = Field(default=None, gt=0)
    season_id: int | None = Field(default=None, gt=0)
    is_active: bool = True
    parameters: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _v_scope_consistency(self) -> ScenarioAssignmentCreate:
        if self.scope == ScenarioScope.GLOBAL and (
            self.room_type_id is not None or self.room_id is not None
        ):
            raise ValueError("scope=global darf weder room_type_id noch room_id setzen")
        if self.scope == ScenarioScope.ROOM_TYPE and (
            self.room_type_id is None or self.room_id is not None
        ):
            raise ValueError("scope=room_type braucht room_type_id und kein room_id")
        if self.scope == ScenarioScope.ROOM and (
            self.room_id is None or self.room_type_id is not None
        ):
            raise ValueError("scope=room braucht room_id und kein room_type_id")
        return self


class ScenarioAssignmentUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/scenario-assignments/{id}.

    Scope + FKs nicht aenderbar — wenn anderer Scope gewuenscht, neuer
    Eintrag anlegen, alten loeschen.
    """

    is_active: bool | None = None
    parameters: dict[str, Any] | None = None
    season_id: int | None = Field(default=None, gt=0)


class ScenarioAssignmentRead(BaseModel):
    """Ausgabe fuer GET /api/v1/scenario-assignments[/{id}]."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scenario_id: int
    scope: ScenarioScope
    room_type_id: int | None
    room_id: int | None
    season_id: int | None
    is_active: bool
    parameters: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
