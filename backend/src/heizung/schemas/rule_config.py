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
    """Ausgabe fuer GET /api/v1/rule-configs/global — die Engine-Felder
    plus ID + Timestamps.

    Seit dem 02.11.2026 sind es **sieben**: ``boost_temperature`` ist
    dazugekommen (AE-83).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    t_occupied: Decimal | None
    t_vacant: Decimal | None
    t_night: Decimal | None
    #: Zieltemperatur eines Boosts (02.11.2026). Steht auf derselben
    #: Seite wie die drei darueber, weil es dieselbe Art von Wert ist:
    #: eine hausweite Vorgabe, die ein Raumtyp oder ein Zimmer
    #: uebersteuern kann.
    boost_temperature: Decimal | None
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
    #: Bereich 18-25, Festlegung des Betreibers vom 02.11.2026. Unten
    #: eng, weil ein Boost unter dem Belegt-Sollwert keinen Sinn hat;
    #: oben am Hoechstwert, den die Geraetegrenzen im Haus zulassen
    #: (Zimmer 15-25, Bad 18-25). Ein Boost darueber waere eine Zahl,
    #: die Layer 5 ohnehin kappt.
    boost_temperature: Decimal | None = Field(default=None, ge=Decimal("18.0"), le=Decimal("25.0"))
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


class HausstandardNutzung(BaseModel):
    """Wie oft ein hausweiter Wert wirklich zum Tragen kommt (Sprint 24d).

    Ein hausweiter Wert sieht aus wie eine Einstellung fuer das ganze Haus
    und ist eine **Vorgabe fuer den Rest** — fuer alles, was nichts
    eigenes sagt. Ohne diese Zahlen ist nicht zu sehen, ob eine Aenderung
    dort 45 Zimmer bewegt oder keines.
    """

    feld: str
    gesetzt: bool
    raumtypen_nutzen: int
    raumtypen_eigen: int
    zimmer_eigen: int
