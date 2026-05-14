"""Pydantic-Schemas fuer rule_config-API (Sprint 9.14, AE-46).

Scope-Reduktion: heute nur die 6 Engine-gelesenen Felder editierbar
(``t_occupied``, ``t_vacant``, ``t_night``, ``night_start``, ``night_end``,
``preheat_minutes_before_checkin``). Die uebrigen 8 ``rule_config``-Spalten
existieren in der DB, werden aber von keinem Engine-Layer gelesen
(siehe Phase-0-Befund C1) und bleiben darum bewusst aus der API-Domain
ausgeschlossen, bis ein Sprint sie aktiviert.

PATCH-Validierung folgt Brief 9.14 T2:
  - Temperatur-Ranges typsicher als ``Decimal`` (keine ``float``)
  - ``night_start != night_end`` (Engine wuerde sonst Null-Fenster sehen)
  - Nachtfenster ueber Mitternacht ist explizit erlaubt (``night_start >
    night_end`` ist OK)
"""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleConfigGlobalRead(BaseModel):
    """Ausgabe fuer GET /api/v1/rule-configs/global — die 6 Engine-Felder
    plus ID + Timestamps."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    t_occupied: Decimal | None
    t_vacant: Decimal | None
    t_night: Decimal | None
    night_start: time | None
    night_end: time | None
    preheat_minutes_before_checkin: int | None
    created_at: datetime
    updated_at: datetime


class RuleConfigGlobalUpdate(BaseModel):
    """Eingabe fuer PATCH /api/v1/rule-configs/global. Alle Felder optional.

    Mindestens 1 Feld noetig — sonst 422 (geprueft im Handler).
    Range-Grenzen aus Brief 9.14 T2.
    """

    model_config = ConfigDict(extra="forbid")

    t_occupied: Decimal | None = Field(default=None, ge=Decimal("16.0"), le=Decimal("26.0"))
    t_vacant: Decimal | None = Field(default=None, ge=Decimal("10.0"), le=Decimal("22.0"))
    t_night: Decimal | None = Field(default=None, ge=Decimal("14.0"), le=Decimal("22.0"))
    night_start: time | None = None
    night_end: time | None = None
    preheat_minutes_before_checkin: int | None = Field(default=None, ge=0, le=240)

    @model_validator(mode="after")
    def _v_night_window(self) -> RuleConfigGlobalUpdate:
        # Wenn BEIDE im selben Payload gesetzt werden: sie muessen
        # unterschiedlich sein. Ein Wert allein (oder None) ist OK —
        # Patch-Semantik laesst das andere Feld unveraendert.
        if (
            self.night_start is not None
            and self.night_end is not None
            and self.night_start == self.night_end
        ):
            raise ValueError(
                "night_start und night_end muessen unterschiedlich sein "
                "(Nullfenster sonst); ueber Mitternacht ist erlaubt."
            )
        return self
