"""Pydantic-Schemas fuer den Belegungs-Import-Webhook (Sprint 15e, AE-66).

Eingabe ist das von mailparser.io erzeugte JSON (Format "Nested - array of
objects", "One request per email"). Strikt: fehlende Pflichtfelder -> 422,
unbekannte Top-Level-Felder werden ignoriert (``extra="ignore"``).

Datums-Konvention der Liste (Sprint 15e-1): ``Anreise`` kommt real OHNE Jahr
(``TT.MM.``), ``Abreise`` MIT Jahr (``TT.MM.JJJJ``). Beide Formen werden
defensiv akzeptiert; das fehlende Jahr leitet ``resolve_stay_dates`` ab.
``received_at`` ist die naive Lokal-Zeit (Europe/Vienna) aus mailparser; der
Datumsteil ist das ``list_date``. UTC-Konversion erst im Service (§5.65).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_RECEIVED_FMT = "%Y-%m-%d %H:%M:%S"

# Anreise kommt real OHNE Jahr ("04.06."), Abreise MIT Jahr ("06.06.2026").
# Beide Formen werden defensiv akzeptiert (Sprint 15e-1); das fehlende Jahr
# leitet resolve_stay_dates aus dem Partner-Datum / list_date ab.
_PARTIAL_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})?$")


def parse_partial_date(raw: str) -> tuple[int, int, int | None]:
    """``"04.06."`` -> ``(4, 6, None)``; ``"06.06.2026"`` -> ``(6, 6, 2026)``.

    Akzeptiert ``TT.MM.`` (ohne Jahr) und ``TT.MM.JJJJ``. Validiert Tag/Monat
    (Schaltjahr als Basis, damit ``29.02.`` ohne Jahr nicht faelschlich
    abgelehnt wird). Wirft ``ValueError`` bei ungueltigem Format/Bereich.
    """
    m = _PARTIAL_DATE_RE.match(raw.strip())
    if m is None:
        raise ValueError(f"Ungueltiges Datum '{raw}', erwartet TT.MM. oder TT.MM.JJJJ")
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else None
    date(year if year is not None else 2024, month, day)  # Bereichs-Check
    return day, month, year


def resolve_stay_dates(anreise_raw: str, abreise_raw: str, list_date: date) -> tuple[date, date]:
    """Leitet (anreise, abreise) als volle Datumswerte ab (Sprint 15e-1).

    - Anker-Jahr = Jahr der Abreise, sonst der Anreise, sonst aus ``list_date``.
    - Ein fehlendes Jahr bekommt das Anker-Jahr.
    - Liegt die so gebildete Anreise NACH der Abreise, war die Anreise im
      Vorjahr (Jahreswechsel) -> Anreise-Jahr minus 1.
    - Ein explizit geliefertes Anreise-Jahr wird vertraut (kein Vorjahr-Wrap).
    """
    a_day, a_month, a_year = parse_partial_date(anreise_raw)
    b_day, b_month, b_year = parse_partial_date(abreise_raw)

    anchor = b_year if b_year is not None else (a_year if a_year is not None else list_date.year)
    abreise = date(b_year if b_year is not None else anchor, b_month, b_day)

    if a_year is not None:
        anreise = date(a_year, a_month, a_day)
    else:
        anreise = date(anchor, a_month, a_day)
        if anreise > abreise:
            anreise = date(anchor - 1, a_month, a_day)
    return anreise, abreise


class OccupancyImportEntry(BaseModel):
    """Ein Zeileneintrag der Belegungsliste."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    zimmer: str = Field(alias="Zimmer", min_length=1)
    # Roh-String; Jahr-Ableitung (Anreise ggf. ohne Jahr) im Service via
    # resolve_stay_dates. Hier nur Format-/Bereichs-Validierung.
    anreise: str = Field(alias="Anreise")
    abreise: str = Field(alias="Abreise")
    aufenthaltstyp: str | None = Field(default=None, alias="Aufenthaltstyp")

    @field_validator("anreise", "abreise", mode="before")
    @classmethod
    def _validate_de_date(cls, v: object) -> str:
        if not isinstance(v, str):
            raise ValueError("Datum muss als String TT.MM. oder TT.MM.JJJJ kommen")
        s = v.strip()
        parse_partial_date(s)  # Format-/Bereichs-Check -> 422 bei Murks
        return s


class OccupancyImportPayload(BaseModel):
    """Gesamter Webhook-Body (eine E-Mail = ein Request)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1, description="mailparser-Request-ID -> external_id / Idempotenz")
    received_at: datetime = Field(
        description="Naive Lokal-Zeit Europe/Vienna; Datumsteil = list_date"
    )
    liste: list[OccupancyImportEntry] = Field(default_factory=list)

    @field_validator("received_at", mode="before")
    @classmethod
    def _parse_received_at(cls, v: object) -> object:
        if isinstance(v, datetime):
            return v
        if not isinstance(v, str):
            raise ValueError("received_at muss String 'YYYY-MM-DD HH:MM:SS' sein")
        try:
            return datetime.strptime(v.strip(), _RECEIVED_FMT)
        except ValueError as exc:
            raise ValueError(f"Ungueltiges received_at '{v}' (YYYY-MM-DD HH:MM:SS)") from exc


# ---------------------------------------------------------------------------
# Lese-Endpoint (GET .../log) — Vertrag fuer Sprint 2 (Frontend), fix.
# ---------------------------------------------------------------------------


class OccupancyImportLogRow(BaseModel):
    """Ein Eintrag der ``imports``-Liste (letzte 30, neueste zuerst)."""

    received_at: datetime
    list_date: date
    external_id: str
    rooms_occupied: int
    rooms_closed: int
    conflicts: int
    result: str  # "applied" | "rejected"


class OccupancyImportLogResponse(BaseModel):
    """Antwort von GET /api/v1/integrations/occupancy-import/log."""

    status: str  # "green" | "yellow" | "red"
    last_success_at: datetime | None
    expected_by_local: str  # "HH:MM"
    today_received: bool
    imports: list[OccupancyImportLogRow]
