"""Pydantic-Schemas fuer Manual-Override-API (Sprint 9.9, Engine Layer 3).

Erlaubt im ``Create``-Schema **nicht** die Quelle ``device`` — Drehring-
Overrides werden ausschliesslich vom ``device_adapter`` aus dem MQTT-
Subscriber-Pfad erzeugt; das Frontend setzt nur ``frontend_*``-Quellen.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from heizung.models.enums import OverrideSource

#: Quellen, die der Create-Endpoint annimmt.
#:
#: **``frontend_24h`` hat hier vom 20. bis 22.10.2026 gefehlt.** Fix A (#324)
#: hat den Wert eingefuehrt und das Panel darauf umgestellt, ohne diesen
#: ``Literal`` nachzuziehen. Pydantic hat die Anfrage damit mit 422 abgewiesen,
#: bevor ein Service sie sah — und die Fehlermeldung zaehlte drei Werte auf,
#: von denen keiner im Dialog steht:
#:
#:     Input should be 'frontend_4h', 'frontend_midnight' or 'frontend_checkout'
#:
#: ``test_override_quellen_spiegel.py`` haelt diese Liste seither gegen
#: ``FRONTEND_SOURCES`` im Panel, und ``test_api_overrides.py`` legt fuer jede
#: waehlbare Dauer einen Override ueber den echten Endpoint an.
#:
#: ``frontend_4h`` und ``frontend_midnight`` bleiben **angenommen**, obwohl
#: sie seit Fix A nicht mehr waehlbar sind. Sie zu entfernen waere eine
#: Verengung der API-Oberflaeche und eine eigene Entscheidung — kein Teil
#: eines Hotfixes, der eine abgewiesene Vorauswahl reparieren soll.
#:
#: ``frontend_bereich`` kam mit Sprint 24d dazu: die Uebersteuerung eines
#: Allgemeinbereichs (Bar, Rezeption, Spa). Sie braucht keine Belegung und
#: traegt ihre Dauer in ``dauer_minuten`` — bei allen anderen Quellen steckt
#: die Dauer im Namen.
FrontendOverrideSource = Literal[
    "frontend_24h",
    "frontend_checkout",
    "frontend_bereich",
    "frontend_4h",
    "frontend_midnight",
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
    dauer_minuten: int | None = Field(
        default=None,
        ge=1,
        le=24 * 60,
        description="Dauer in Minuten. Pflicht fuer 'frontend_bereich', "
        "Hoechstmass 1440 (24 h). Bei allen anderen Quellen steckt die "
        "Dauer im Namen der Quelle und dieses Feld bleibt leer.",
    )
    reason: str | None = Field(default=None, max_length=500)
    heating_zone_id: int | None = Field(
        default=None,
        gt=0,
        description="Sprint 12a (AE-58): optionaler Zone-Scope. None bedeutet "
        "Room-Scope (Backward-Compat). Bei gesetztem Wert muss die Zone "
        "demselben Raum wie der Pfad-Parameter angehoeren — sonst 404 "
        "invalid_zone.",
    )

    @model_validator(mode="after")
    def _dauer_passt_zur_quelle(self) -> ManualOverrideCreate:
        """Die Dauer ist Pflicht fuer einen Bereich und sonst verboten.

        **Beide Richtungen, und die zweite ist die wichtigere.** Ohne
        Dauer waere die Uebersteuerung eines Bereichs unbefristet — eine
        Bar, die durchheizt, bemerkt niemand (Mutationsprobe M6). Und ein
        ``dauer_minuten`` an einer Quelle, die ihre Dauer im Namen traegt,
        waere ein Feld, das der Aufrufer setzt und das wirkungslos
        verfaellt; genau die Sorte Schalter, aus der dieser Sprint
        entstanden ist (§5.77).

        Das Hoechstmass von 24 Stunden steht als ``le`` am Feld und
        zusaetzlich im Dienst (``override_service.compute_expires_at``) —
        nicht aus Misstrauen gegen Pydantic, sondern weil der Dienst auch
        von einem Aufrufer erreichbar ist, der nicht durch dieses Schema
        kommt (Mutationsprobe M8).
        """
        braucht_dauer = self.source == "frontend_bereich"
        if braucht_dauer and self.dauer_minuten is None:
            raise ValueError(
                "dauer_minuten ist Pflicht fuer die Quelle 'frontend_bereich' "
                "— eine Bereichs-Uebersteuerung ohne Ablauf gibt es nicht."
            )
        if not braucht_dauer and self.dauer_minuten is not None:
            raise ValueError(
                f"dauer_minuten gilt nur fuer 'frontend_bereich'; die Quelle "
                f"'{self.source}' traegt ihre Dauer im Namen."
            )
        return self

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
    heating_zone_id: int | None
    setpoint: Decimal
    source: OverrideSource
    expires_at: datetime
    reason: str | None
    created_at: datetime
    created_by: str | None
    revoked_at: datetime | None
    revoked_reason: str | None

    # Sprint 23 T1.7: der **wirksame** Wert, falls die Kappung greift.
    #
    # Der Gastwunsch steht in ``setpoint``; gekappt wird in Layer 5 gegen
    # die Grenzen des Raumtyps. Die Historie las bisher nur ``setpoint``
    # und behauptete damit eine Wirkung, die es nicht gibt: „30 °C, aktiv"
    # bei wirksamen 25.
    #
    # ``None`` heisst „keine Kappung" — entweder liegt der Wert in den
    # Grenzen, oder die Zeile ist nicht mehr aktiv. **Und das zweite ist
    # Absicht:** eine Bestandszeile von vorgestern gegen die *heutigen*
    # Grenzen zu rechnen wuerde eine Vergangenheit behaupten, die so nicht
    # war. Abgelaufene Zeilen zeigen weiter den gespeicherten Wert.
    #
    # Abgeleitet read-time aus dem Raumtyp (Bad-Zonen aus dem der
    # Vorlage), nichts persistiert — dieselbe Form wie
    # ``battery_voltage_median`` (AE-72). Ein zweites Feld am Override
    # waere eine zweite Wahrheit, die beim ersten Grenzen-Wechsel
    # auseinanderlaeuft.
    wirksam_gekappt_c: int | None = None
