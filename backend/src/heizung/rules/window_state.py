"""Window-State-Helper (Sprint 12 T4, AE-52).

Extrahiert aus ``rules/engine.py:layer_window_open``. Geteilte Quelle der
Wahrheit fuer „welche Zonen eines Raums haben gerade ein offenes Fenster"
— wird sowohl von Layer 4 (Setpoint-Logik) als auch von
``services/override_service`` (POST-/override-Reject) genutzt.

Eigenes Modul, weil:

- ``rules/engine.py`` importiert ``services.override_service`` (Layer 3).
- ``services/override_service`` muss den Helper kennen.

Direkter Import von ``rules/engine`` in ``override_service`` waere
zirkulaer. Helper in neutraler Lage in ``rules/window_state.py`` loest
das ohne Late-Import-Trick.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.rules.constants import WINDOW_STALE_THRESHOLD_MIN

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def detect_open_window_zones(
    session: AsyncSession,
    room_id: int,
    now: datetime,
) -> list[dict[str, Any]]:
    """Liefert die Liste der HeatingZones eines Raums mit gerade offenem
    Fenster.

    Eine Zone gilt als offen, wenn mindestens ein zugeordnetes Device

    - ``retired_at IS NULL`` (Sprint 13b.1, AE-57 — Lifecycle-Filter
      explizit; retired Devices duerfen den Layer 4 nicht beeinflussen),
    - ``health_state='healthy'`` (AE-53, Sprint 11 T3 — silent/degraded/
      suspicious Vickis fliessen NICHT in die Aggregation),
    - ein frisches Reading hat (Alter <= ``WINDOW_STALE_THRESHOLD_MIN``,
      Vergleich gegen ``now``),
    - dieses Reading ``open_window=True`` meldet.

    NULL-Werte in ``open_window`` (alter Codec / Vicki ohne Sensor)
    gelten als ``False`` und aktivieren NICHT.

    DISTINCT-ON-Query liefert pro Device das juengste Reading. INNER
    JOIN auf ``HeatingZone`` grenzt auf den Raum ein; Devices ohne
    ``heating_zone`` (Provisioning) fallen raus.

    :param now: Zeitpunkt-Referenz fuer den Stale-Threshold; wird vom
        Caller mitgegeben, damit Tests deterministisch sind.

    :return: Liste von ``{"zone_id": int, "reading_at": str}`` pro
        offener Zone. Leere Liste, wenn keine Zone offen ist
        (entweder Fenster zu, Reading veraltet, oder keine Devices).
        Reihenfolge nicht garantiert (DB-distinct-Order).
    """
    threshold = now - timedelta(minutes=WINDOW_STALE_THRESHOLD_MIN)
    stmt = (
        select(
            SensorReading.device_id,
            SensorReading.time,
            SensorReading.open_window,
            Device.heating_zone_id,
        )
        .join(Device, Device.id == SensorReading.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .where(Device.retired_at.is_(None))
        .where(Device.health_state == "healthy")
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    rows = (await session.execute(stmt)).all()

    open_zones: list[dict[str, Any]] = []
    for _device_id, reading_time, open_window, zone_id in rows:
        if reading_time < threshold:
            continue
        if open_window is True:
            open_zones.append({"zone_id": zone_id, "reading_at": reading_time.isoformat()})
    return open_zones
