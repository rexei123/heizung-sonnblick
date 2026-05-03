"""Pydantic-Schemas fuer event_log (Sprint 9.5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from heizung.models.enums import CommandReason, EventLogLayer


class EventLogRead(BaseModel):
    """Eine Layer-Zeile aus event_log fuer das Engine-Decision-Panel (Sprint 9.10)."""

    model_config = ConfigDict(from_attributes=True)

    time: datetime
    room_id: int
    evaluation_id: uuid.UUID
    layer: EventLogLayer
    device_id: int | None
    setpoint_in: Decimal | None
    setpoint_out: Decimal | None
    reason: CommandReason | None
    details: dict[str, Any] | None
