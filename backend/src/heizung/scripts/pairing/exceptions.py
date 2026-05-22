"""Domain-Exceptions fuer das Pre-Pairing-Skript (Sprint 13a).

Eigenes Modul (statt im Modul, das raised), damit Tests die Klassen
spezifisch importieren koennen und der CLI-Entrypoint (T6) sie sauber
fangen kann ohne den vollen Parser-Modul-Pfad anzufassen.
"""

from __future__ import annotations


class ParseError(Exception):
    """Wird gehoben wenn die CSV-Datei nicht zu validierten Rows parsen kann.

    Fail-fast bei strukturellen Problemen (zu viele Zeilen, kein
    Trennzeichen erkennbar), batch-collect bei Pydantic-Row-Errors
    (``errors`` Liste enthaelt pro fehlerhafter Zeile eine Nachricht
    ``"Zeile N: <pydantic-msg>"``).
    """

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        self.errors: list[str] = errors or []
        super().__init__(message)
