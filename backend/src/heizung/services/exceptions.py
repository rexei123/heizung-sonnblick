"""Lifecycle-Exception-Hierarchie (B-Sprint13b2-4, AE-59).

Custom-Exceptions fuer Lifecycle-Operationen (replace, retire). Alle
erben von ``LifecycleError``, das einen ``error_code``-ClassVar traegt.

App-weiter FastAPI-Handler in ``heizung.main`` rendert
``{"detail": <message>, "error_code": <CODE>}``:

- ``DeviceNotFound`` -> 404 Not Found
- alle anderen -> 409 Conflict

Frontend-Mapping in ``frontend/src/lib/api/error-codes.ts`` (Konstanten
identisch zu ``error_code``-Werten unten).

Scope (Strategie-Setzung 2026-05-24): ausschliesslich Lifecycle-
Endpoints (Pool, Replace, Retire). ``overrides.py``-Pattern (Sprint
12c ``error_code``-Key vs Sprint 12a ``error``-Key) bleibt
unangetastet — Konsolidierung in B-Sprint13b2-7.
"""

from __future__ import annotations

from typing import ClassVar


class LifecycleError(Exception):
    """Basis-Exception fuer alle Lifecycle-Fehler.

    ``error_code`` ist ClassVar (pro Subklasse fix), wird vom
    App-weiten FastAPI-Handler in den Response-Body geschrieben.
    """

    error_code: ClassVar[str] = "LIFECYCLE_ERROR"  # Fallback, sollte nie greifen

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DeviceNotFound(LifecycleError):  # noqa: N818 — Brief-Signatur, AE-57/AE-59-Konvention
    """Device-ID existiert nicht in der DB. HTTP 404."""

    error_code: ClassVar[str] = "DEVICE_NOT_FOUND"


class DeviceStateError(LifecycleError):
    """Device-Zustand erlaubt die Operation nicht (bereits retired,
    nicht zugewiesen, ...). HTTP 409.

    Drei Trigger-Stellen (Phase-0 §1): replace alt bereits retired,
    replace alt nicht zugewiesen, retire bereits retired.
    """

    error_code: ClassVar[str] = "DEVICE_STATE_ERROR"


class PoolDeviceUnavailable(LifecycleError):  # noqa: N818 — Brief-Signatur, AE-57/AE-59-Konvention
    """Pool-Device nicht verfuegbar (Pre-Check oder Race-Schutz im
    UPDATE-rowcount=0). HTTP 409.

    Zwei Trigger-Stellen (Phase-0 §1): Pre-Check ``new`` hat Zone
    oder ist retired; Race-Guard nach UPDATE.
    """

    error_code: ClassVar[str] = "POOL_DEVICE_UNAVAILABLE"


class SelfReplacementError(LifecycleError):
    """Replace mit ``old_id == new_id`` ist nicht erlaubt. HTTP 409.

    Ersetzt den inline-``ValueError("Selbst-Tausch nicht erlaubt")``
    aus Sprint 13b.1 (``device_service.replace_device`` Z.126 in der
    Pre-Refactor-Fassung).
    """

    error_code: ClassVar[str] = "SELF_REPLACEMENT_FORBIDDEN"
