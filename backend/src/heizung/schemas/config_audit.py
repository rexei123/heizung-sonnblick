"""Pydantic-Schema fuer config_audit (Sprint 9.14, AE-46).

Read-only — Schreibzugriff erfolgt ausschliesslich ueber den Service
``record_config_change`` aus dem PATCH-Handler heraus, nicht via API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ConfigAuditRead(BaseModel):
    """Audit-Eintrag fuer Settings-Aenderungen (read-only)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    user_id: int | None
    source: str
    table_name: str
    scope_qualifier: str | None
    column_name: str
    old_value: Any
    new_value: Any
    request_ip: str | None
