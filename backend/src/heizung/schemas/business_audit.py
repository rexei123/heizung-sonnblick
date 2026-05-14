"""Pydantic-Schema fuer business_audit (Sprint 9.17, AE-50).

Read-only — Schreibzugriff erfolgt ueber den Service
``record_business_action`` aus den Endpoint-Handlern heraus, nicht via API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class BusinessAuditRead(BaseModel):
    """Audit-Eintrag fuer operative Mitarbeiter-Aktionen (read-only)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ts: datetime
    user_id: int | None
    action: str
    target_type: str
    target_id: int | None
    old_value: Any
    new_value: Any
    request_ip: str | None
