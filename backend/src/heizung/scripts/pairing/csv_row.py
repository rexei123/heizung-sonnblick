"""Pydantic-Modell fuer eine Zeile aus dem Mass-Pairing-CSV (Sprint 13a).

CSV-Quelle ist ``docs/inventar/Zimmer_Geraete_Liste.xlsx`` (Master-
Inventar). Hotelier exportiert das relevante Sheet als CSV und uebergibt
es dem Pre-Pairing-Skript (``heizung.scripts.pair_devices import <csv>``).

Pool-Konvention (Reserve-Geraete ohne Zone-Zuordnung):
``zimmer_nummer`` und ``zone_label`` sind beide ``None``. Validierung
erzwingt diese Konsistenz — gemischter Pool-Status (eines gesetzt,
das andere leer) ist Daten-Inkonsistenz und wird abgewiesen.

LoRaWAN-Identifier-Konvention (CLAUDE.md §5.13): ``dev_eui`` und
``app_key`` werden in lowercase normalisiert (ChirpStack erwartet
lowercase im MQTT-Topic + Payload). ``app_eui`` folgt derselben Regel.

Sprint 17 (E4/C2) — drei optionale Metadaten-Spalten
------------------------------------------------------

Die Hardware-Erfassung 2026-09 liefert je Vicki vier Werte: DevEUI,
AppKey, AppEUI und Seriennummer, dazu eine eigene Durchnummerierung
001-104. DevEUI und AppKey standen schon in der CSV; die drei uebrigen
kommen hier dazu — alle **optional**, damit Bestands-CSVs ohne diese
Spalten unveraendert weiterlaufen.

Abbildung auf die ``device``-Tabelle (**ohne Migration**, Entscheidung
Strategie-Chat 2026-09-17):

===================  ==========================  ==========================
CSV-Spalte           Device-Spalte               Begruendung
===================  ==========================  ==========================
``serial_number``    ``device.hardware_number``  AE-61 definiert die Spalte
                     ``VARCHAR(64)``             woertlich als Hersteller-
                                                 Seriennummer (Beispiel
                                                 ``MDC5419731K6UF``); der
                                                 Partial-Unique-Index aus
                                                 Migration 0020 ist genau
                                                 dafuer gedacht.
``hardware_nummer``  ``device.label``            Die Durchnummerierung
                     ``VARCHAR(200)``            001-104 ist ein Anzeige-
                                                 name, kein Hersteller-
                                                 Merkmal. ``label`` traegt
                                                 ihn heute schon
                                                 ("Vicki-001") und ist die
                                                 Quelle fuer den
                                                 ChirpStack-Geraetenamen
                                                 (D5).
``app_eui``          ``device.app_eui``          1:1, ``VARCHAR(16)``.
                                                 Bis Sprint 16 von keinem
                                                 Pfad befuellt.
===================  ==========================  ==========================

Normalisierung (alle Werte vorher ``strip()``, siehe ``csv_parser``):

- ``dev_eui`` / ``app_eui``: 16 Hex-Zeichen, **lowercase** — ChirpStack-
  Konvention.
- ``app_key``: 32 Hex-Zeichen, lowercase.
- ``serial_number``: **UPPERCASE**. Hersteller drucken die Nummer in
  Grossbuchstaben auf den Aufkleber; der Partial-Unique-Index auf
  ``hardware_number`` ist case-sensitiv, also muss die Schreibweise
  deterministisch sein, sonst legen ``mdc123`` und ``MDC123`` zwei
  Eintraege an.
- ``hardware_nummer``: nur getrimmt. Kein Case-Zwang und keine
  Zero-Padding-Normalisierung — der Wert ist Anzeigetext, und ein
  stilles Umschreiben von "1" auf "001" waere eine Annahme ueber die
  Hotelier-Konvention, die wir nicht treffen.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")

# Excel-Export schreibt aus einer Text-Zelle "52" gern "52.0", sobald die
# Spalte einmal als Zahl formatiert war. Der Seed-Pfad faengt das seit
# Sprint 15 ab (``seed_rooms._coerce_int``); der Pairing-Pfad tat es nicht
# (B-Sprint13a-3). Nur die Form "<Ziffern>.<Nullen>" wird gekuerzt — aus
# "52.5" wird NICHT "52", das waere stilles Datenverbiegen.
_TRAILING_ZERO_DECIMAL = re.compile(r"^(-?\d+)\.0+$")


def _normalize_hex16(value: str, field: str) -> str:
    """LoRaWAN-EUI: 16 Hex-Zeichen, lowercase-normalisiert."""
    if not _HEX16.fullmatch(value):
        raise ValueError(f"{field} muss 16 Hex-Zeichen sein (8 Byte)")
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

    ``hardware_nummer``, ``app_eui`` und ``serial_number`` sind optional
    (Sprint 17 / E4) — Bestands-CSVs ohne diese Spalten bleiben gueltig.
    """

    stockwerk: int | None = Field(
        default=None,
        description="Stockwerk-Nummer (z.B. 1, 2, 3). None bei Reserve-Pool.",
    )
    zimmer_nummer: str | None = Field(
        default=None,
        max_length=20,
        description="Zimmer-Nummer im Hotel (z.B. '101', '207'). None bei Reserve-Pool. "
        "String, nicht int — ``room.number`` ist VARCHAR(20) und laesst "
        "'101A' oder 'DG' zu (B-Sprint13a-2).",
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
    app_key: str | None = Field(
        default=None,
        description="LoRaWAN AppKey (16 Byte hex, 32 Zeichen). Wird lowercase "
        "normalisiert. Fuer den Import Pflicht — das erzwingt ``parse_csv`` "
        "mit ``require_app_key=True``. Fuer ``assign`` (Sprint 17 / C8) nicht: "
        "die Montage-CSV wird ohne AppKey-Spalte exportiert, damit das "
        "Geheimnis nicht ein zweites Mal ueber den Tisch wandert.",
    )

    # --- Sprint 17 (E4/C2): optionale Metadaten ---------------------------

    hardware_nummer: str | None = Field(
        default=None,
        max_length=200,
        description="Eigene Durchnummerierung 001-104. Wird auf device.label "
        "abgebildet und ist die Quelle fuer den ChirpStack-Geraetenamen (D5). "
        "Nur getrimmt, keine Case-/Padding-Normalisierung.",
    )
    app_eui: str | None = Field(
        default=None,
        description="LoRaWAN AppEUI/JoinEUI (8 Byte hex, 16 Zeichen). "
        "Wird lowercase normalisiert. Ziel: device.app_eui.",
    )
    serial_number: str | None = Field(
        default=None,
        max_length=64,
        description="Hersteller-Seriennummer vom Aufkleber (z.B. MDC5419731K6UF). "
        "Wird UPPERCASE normalisiert. Ziel: device.hardware_number (AE-61).",
    )

    @field_validator("zimmer_nummer", mode="before")
    @classmethod
    def _v_zimmer_nummer(cls, v: object) -> str | None:
        """Als String fuehren, ``"52.0"`` auf ``"52"`` kuerzen (B-Sprint13a-3).

        ``mode="before"``, damit auch ein int aus einer anderen Quelle
        durchlaeuft. Nicht-numerische Nummern (``"101A"``, ``"DG"``) bleiben
        unangetastet — das ist der Punkt an B-Sprint13a-2.
        """
        if v is None:
            return None
        text = str(v).strip()
        if not text:
            return None
        match = _TRAILING_ZERO_DECIMAL.fullmatch(text)
        return match.group(1) if match else text

    @field_validator("dev_eui")
    @classmethod
    def _v_dev_eui(cls, v: str) -> str:
        return _normalize_hex16(v, "dev_eui")

    @field_validator("app_key")
    @classmethod
    def _v_app_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_hex32(v)

    @field_validator("app_eui")
    @classmethod
    def _v_app_eui(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return _normalize_hex16(v, "app_eui")

    @field_validator("serial_number")
    @classmethod
    def _v_serial_number(cls, v: str | None) -> str | None:
        """UPPERCASE — der Partial-Unique-Index auf ``hardware_number`` ist
        case-sensitiv, also muss die Schreibweise deterministisch sein."""
        if v is None:
            return None
        return v.upper()

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
