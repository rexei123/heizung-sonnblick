"""Pydantic-Modell fuer eine Zeile aus dem Mass-Pairing-CSV (Sprint 13a).

CSV-Quelle ist ``docs/inventar/Zimmer_Geraete_Liste.xlsx`` (Master-
Inventar, 110 Vickis: 105 verbaut + 5 Reserve). Hotelier exportiert
das relevante Sheet als CSV und uebergibt es dem Pre-Pairing-Skript
(``heizung.scripts.pair_devices import <csv>``).

Pool-Konvention (Reserve-Geraete ohne Zone-Zuordnung):
``zimmer_nummer`` und ``zone_label`` sind beide ``None``. Validierung
erzwingt diese Konsistenz — gemischter Pool-Status (eines gesetzt,
das andere leer) ist Daten-Inkonsistenz und wird abgewiesen.

LoRaWAN-Identifier-Konvention (CLAUDE.md §5.13): ``dev_eui`` und
``app_key`` werden in lowercase normalisiert (ChirpStack erwartet
lowercase im MQTT-Topic + Payload).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")


def _normalize_hex16(value: str) -> str:
    """LoRaWAN-DevEUI: 16 Hex-Zeichen, lowercase-normalisiert."""
    if not _HEX16.fullmatch(value):
        raise ValueError("dev_eui muss 16 Hex-Zeichen sein (8 Byte)")
    return value.lower()


def _normalize_hex32(value: str) -> str:
    """LoRaWAN-AppKey: 32 Hex-Zeichen, lowercase-normalisiert."""
    if not _HEX32.fullmatch(value):
        raise ValueError("app_key muss 32 Hex-Zeichen sein (16 Byte)")
    return value.lower()


class PairingCsvRow(BaseModel):
    """Eine Zeile aus dem Mass-Pairing-CSV.

    Felder ``stockwerk``, ``zimmer_nummer``, ``zimmer_typ``, ``zone_label``
    sind nullable fuer Reserve-Pool-Geraete (Sprint 17 Pre-Pairing-Workflow,
    RUNBOOK §10h). Active-Geraete haben alle vier Felder gesetzt.

    ``dev_eui`` und ``app_key`` sind Pflicht und werden lowercase
    normalisiert (Repo-Konvention CLAUDE.md §5.13).
    """

    stockwerk: int | None = Field(
        default=None,
        description="Stockwerk-Nummer (z.B. 1, 2, 3). None bei Reserve-Pool.",
    )
    zimmer_nummer: int | None = Field(
        default=None,
        description="Zimmer-Nummer im Hotel (z.B. 101, 207). None bei Reserve-Pool.",
    )
    zimmer_typ: str | None = Field(
        default=None,
        max_length=100,
        description="Raumtyp-Bezeichnung aus dem Master-Inventar. "
        "Informativ — Zone-Lookup laeuft ueber zimmer_nummer + zone_label.",
    )
    zone_label: str | None = Field(
        default=None,
        max_length=100,
        description="Zone-Name innerhalb des Zimmers (z.B. 'Schlafzimmer', 'Bad'). "
        "None bei Reserve-Pool.",
    )
    dev_eui: str = Field(
        ...,
        description="LoRaWAN DevEUI (8 Byte hex, 16 Zeichen). Wird lowercase normalisiert.",
    )
    app_key: str = Field(
        ...,
        description="LoRaWAN AppKey (16 Byte hex, 32 Zeichen). Wird lowercase normalisiert.",
    )

    @field_validator("dev_eui")
    @classmethod
    def _v_dev_eui(cls, v: str) -> str:
        return _normalize_hex16(v)

    @field_validator("app_key")
    @classmethod
    def _v_app_key(cls, v: str) -> str:
        return _normalize_hex32(v)

    @model_validator(mode="after")
    def _v_pool_consistency(self) -> PairingCsvRow:
        """zimmer_nummer und zone_label muessen beide gesetzt oder beide None sein.

        Gemischter Pool-Status (eines da, anderes leer) ist Daten-
        Inkonsistenz im Master-Inventar.
        """
        zimmer_set = self.zimmer_nummer is not None
        zone_set = self.zone_label is not None
        if zimmer_set != zone_set:
            raise ValueError(
                "Pool-Inkonsistenz: zimmer_nummer und zone_label muessen "
                "beide gesetzt sein (Active) oder beide None (Reserve-Pool). "
                f"Aktuell: zimmer_nummer={self.zimmer_nummer!r}, "
                f"zone_label={self.zone_label!r}."
            )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_pool_device(self) -> bool:
        """True wenn das Geraet im Reserve-Pool steht (keine Zone-Zuordnung).

        Aequivalent zu ``zimmer_nummer is None`` — Pool-Konsistenz wird
        vom ``_v_pool_consistency``-Model-Validator erzwungen.
        """
        return self.zimmer_nummer is None
