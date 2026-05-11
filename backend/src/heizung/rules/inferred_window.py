"""Passiver Inferred-Window-Detector (AE-47 §Passiver Trigger, Sprint 9.11y).

Backend-Algorithmus, der einen Temperatur-Sturz im Raum bei stehendem
Heizungs-Setpoint als ``inferred_window``-Hinweis erkennt. **Greift NICHT
in die Engine-Pipeline ein** — Layer 4 reagiert weiterhin ausschliesslich
auf die zwei Hardware-Trigger (Vicki ``open_window``, ``attached_backplate``).

Der Detector ist Inferenz, nicht Steuerung. AE-47 §Begruendung: "Inferenz
darf beobachten, aber nicht steuern, bevor sie sich produktiv bewaehrt hat."
Der Output wird ausschliesslich ins ``event_log`` als
``inferred_window_observation``-Layer geschrieben (siehe
``tasks.engine_tasks.log_inferred_window_event``).

Trigger-Logik (AE-47 §Passiver Trigger):
    - Lookback: ``INFERRED_WINDOW_LOOKBACK_MIN`` (10 Min)
    - Δ-T-Schwelle: ``INFERRED_WINDOW_DELTA_C_MIN`` (0.5 °C)
    - Stehender Setpoint: kein ControlCommand mit anderem Setpoint im
      Lookback-Fenster
    - Pro Device der Zone: mindestens 2 frische SensorReadings im
      Lookback-Fenster mit ``temperature IS NOT NULL`` (analog Hysterese
      9.11x Layer-4-Detached)
    - Δ-T = ``oldest_temp - newest_temp`` (fallende Richtung — Raum kuehlt)
    - Trigger feuert wenn IRGENDEIN Device Δ-T >= Schwelle hat (OR-
      Semantik, analog Vicki-Hardware-Window-Trigger).

Wiederholte Treffer (3+ in 30 Min) im selben Raum ohne Vicki-Trigger
deuten auf Hardware-Schwaeche der Vicki — Diagnose-Pfad fuer
Service-Techniker, nicht Engine-Input.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from heizung.models.control_command import ControlCommand
from heizung.models.device import Device
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


INFERRED_WINDOW_LOOKBACK_MIN: int = 10
INFERRED_WINDOW_DELTA_C_MIN: Decimal = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class InferredWindowResult:
    """Ergebnis einer Inferred-Window-Detection.

    Wird **nur** zur Protokollierung in ``event_log`` verwendet — keine
    Setpoint-Aktion abgeleitet.
    """

    room_id: int
    detected_at: datetime
    delta_c: Decimal  # max ueber alle Devices der Zone
    devices_observed: list[str]  # dev_eui-Liste der Devices mit >= 2 frischen Frames
    setpoint_c: int | None  # aktueller stehender Setpoint (None wenn nie gesendet)


async def detect_inferred_window(
    session: AsyncSession,
    room_id: int,
    now: datetime,
) -> InferredWindowResult | None:
    """Prueft AE-47 §Passiver Trigger. Liefert ``None`` wenn nicht ausgeloest.

    Bedingungen fuer Trigger:
      1. Stehender Setpoint im Lookback (alle ControlCommand-Setpoints
         gleich, oder kein neuer ControlCommand im Lookback).
      2. Mindestens ein Device der Zone hat >= 2 frische SensorReadings
         (``temperature IS NOT NULL``) im Lookback.
      3. Δ-T (``oldest_temp - newest_temp``) eines solchen Devices
         >= ``INFERRED_WINDOW_DELTA_C_MIN``.

    Greift nicht in Engine-Pipeline ein — reine Read-Only-Diagnose.
    """
    threshold = now - timedelta(minutes=INFERRED_WINDOW_LOOKBACK_MIN)

    # --- Bedingung 1: stehender Setpoint im gesamten Lookback ---
    # "Stehend" heisst: zum Zeitpunkt JEDES SensorReadings im Lookback
    # war derselbe Setpoint aktiv. Naive Pruefung nur "CCs im Lookback
    # alle gleich" verpasst Wechsel an der Lookback-Boundary (Beispiel:
    # 20.0-CC vor 30 Min, 18.0-CC gerade jetzt — Window enthaelt nur
    # 18.0, aber zum aeltesten SensorReading war 20.0 aktiv).
    #
    # Korrekt: Setpoint-Werte im Lookback PLUS Pre-Window-Baseline (letzter
    # CC vor threshold) muessen sich auf hoechstens einen Wert reduzieren.
    in_window_stmt = (
        select(ControlCommand.target_setpoint)
        .join(Device, Device.id == ControlCommand.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .where(ControlCommand.issued_at >= threshold)
    )
    in_window_setpoints = {row[0] for row in (await session.execute(in_window_stmt)).all()}

    pre_window_stmt = (
        select(ControlCommand.target_setpoint)
        .join(Device, Device.id == ControlCommand.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .where(ControlCommand.issued_at < threshold)
        .order_by(ControlCommand.issued_at.desc())
        .limit(1)
    )
    pre_window_sp = (await session.execute(pre_window_stmt)).scalar_one_or_none()

    all_setpoints: set[Decimal] = set(in_window_setpoints)
    if pre_window_sp is not None:
        all_setpoints.add(pre_window_sp)

    if len(all_setpoints) > 1:
        return None  # Wechsel an Boundary oder innerhalb Window

    # Stehender Setpoint fuer Audit-Trail: der eine Wert in all_setpoints
    # (falls existiert), sonst None. Bei stehendem Wert ist es egal,
    # ob er aus in_window oder pre_window kommt — beide sind gleich.
    setpoint_decimal = next(iter(all_setpoints), None)
    setpoint_c: int | None = int(setpoint_decimal) if setpoint_decimal is not None else None

    # --- Bedingung 2+3: pro Device Δ-T berechnen ---
    # Alle frischen SensorReadings mit temperature IS NOT NULL fuer
    # Devices dieser Zone. Pro Device oldest_temp und newest_temp
    # ermitteln, Δ-T = oldest - newest (Falling-Richtung).
    sr_stmt = (
        select(
            Device.id,
            Device.dev_eui,
            SensorReading.time,
            SensorReading.temperature,
        )
        .join(Device, Device.id == SensorReading.device_id)
        .join(HeatingZone, HeatingZone.id == Device.heating_zone_id)
        .where(HeatingZone.room_id == room_id)
        .where(SensorReading.time >= threshold)
        .where(SensorReading.temperature.is_not(None))
        .order_by(Device.id, SensorReading.time)
    )
    rows = (await session.execute(sr_stmt)).all()

    # Aggregiere pro Device.
    frames_by_dev: dict[int, list[tuple[datetime, Decimal, str]]] = {}
    for dev_id, dev_eui, time, temp in rows:
        if temp is None:
            continue
        frames_by_dev.setdefault(dev_id, []).append((time, temp, dev_eui))

    max_delta: Decimal = Decimal("0")
    devices_observed: list[str] = []
    for frames in frames_by_dev.values():
        if len(frames) < 2:
            continue
        # Frames sind nach time ASC sortiert -> [0] oldest, [-1] newest.
        oldest_temp = frames[0][1]
        newest_temp = frames[-1][1]
        delta = oldest_temp - newest_temp  # positiv bei Fall
        if delta >= INFERRED_WINDOW_DELTA_C_MIN:
            devices_observed.append(
                frames[0][2]
            )  # dev_eui (alle frames eines devs haben gleichen eui)
            if delta > max_delta:
                max_delta = delta

    if not devices_observed:
        return None

    return InferredWindowResult(
        room_id=room_id,
        detected_at=now,
        delta_c=max_delta,
        devices_observed=devices_observed,
        setpoint_c=setpoint_c,
    )
