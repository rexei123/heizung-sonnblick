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

Schritt 2, gebaut am 27.11.2026
-------------------------------

**Der Anlass ist eine Messung, die der Betreiber angestossen hat.** Am
05.11.2026 meldete er Zimmer 306: ein Gast, der sichtbar oft lueftet,
Einbrueche um 3 bis 4 Grad — und in 30 Tagen bei 13.179 Meldungen
**0x** ``open_window = true``. Die Analyse bestaetigte die Einbrueche:
**49 Stueck ab 1,5 Grad, davon 37 mit oeffnendem Ventil**
(``docs/status/2026-11-05-fenstererkennung-stand-lesbar.md``).

Diese 37 sind der Unterschied, um den es hier geht. Ein Temperaturfall
allein sagt nichts: ein Raum, dessen Sollwert gerade abgesenkt wurde,
kuehlt genauso. Ein Temperaturfall, bei dem das Ventil **aufgeht**, sagt
etwas — das Geraet versucht gegenzuheizen und kommt nicht nach. Das ist
Waermeverlust, und die haeufigste Ursache dafuer ist ein offenes Fenster.

Trigger-Logik
-------------

- Lookback: ``INFERRED_WINDOW_LOOKBACK_MIN`` (**25 Min**)
- Δ-T-Schwelle: ``INFERRED_WINDOW_DELTA_C_MIN`` (**1,5 °C**)
- Stehender Setpoint: kein ControlCommand mit anderem Setpoint im
  Lookback-Fenster
- Pro Device der Zone: mindestens 2 frische SensorReadings im
  Lookback-Fenster mit ``temperature IS NOT NULL``
- Δ-T = ``oldest_temp - newest_temp`` (fallende Richtung — Raum kuehlt)
- **Und das Ventil muss aufgehen** (siehe unten)
- Trigger feuert, wenn IRGENDEIN Device beides erfuellt (OR-Semantik
  ueber die Geraete, analog Vicki-Hardware-Window-Trigger).

**Warum 25 statt 10 Minuten.** Vorgabe des Betreibers. Zehn Minuten sind
bei einer Meldung alle paar Minuten zwei bis drei Messwerte — ein Fall
ueber 1,5 Grad ist darin selten, und ein geoeffnetes Fenster wirkt
langsamer als zehn Minuten. 25 Minuten fassen das Ereignis, ohne in die
naechste Absenkung zu reichen.

**Warum 1,5 statt 0,5 Grad.** Der Pruefsatz des Betreibers sind die 49
Einbrueche **ab 1,5 Grad**; mit 0,5 waere der Detektor nicht gegen ihn
vergleichbar. Dazu kommt die Mechanik: ueber 25 Minuten ist ein halbes
Grad normale Abkuehlung, und ein Melder, der die meldet, meldet den
ganzen Tag.

Die Ventilstellung als Unterscheider
------------------------------------

``sensor_reading.valve_position`` ist die Ventilstellung in Prozent, wie
das Geraet sie meldet. Als „geht auf" gilt:

* ein Anstieg um mindestens ``VENTIL_OEFFNET_MIN_PP`` Prozentpunkte
  zwischen der aeltesten und der juengsten Meldung des Fensters,
* **oder** eine juengste Stellung von mindestens
  ``VENTIL_WEIT_OFFEN_PROZENT``.

**Der zweite Fall ist nicht Beiwerk.** Ein Ventil, das schon ganz offen
steht, kann nicht weiter aufgehen; ohne diesen Zweig waere genau der
deutlichste Waermeverlust unsichtbar — das Geraet heizt mit allem, was es
hat, und der Detektor sieht „kein Anstieg".

**Die Prozentpunkte gegen Rauschen.** Ein Ventil wackelt um ein bis zwei
Punkte; ein Schwellwert von 0 haette daraus ein Ereignis gemacht.

**Ohne Ventilmeldungen gibt es keinen Treffer.** Nicht, weil nichts
passiert waere, sondern weil wir es nicht unterscheiden koennen — und ein
Melder, der meldet, wenn er nichts unterscheiden kann, ist genau der
Laerm, den dieser Schritt vermeiden soll (Paragraph 5.55).

**Dieser Schritt bleibt passiv** (AE-47): kein Setpoint, kein Downlink,
keine Schicht in der Pipeline. Nur eine Zeile im ``event_log``.
Wiederholte Treffer im selben Raum ohne Vicki-Trigger deuten auf
Hardware-Schwaeche des Geraets — Diagnose-Pfad, nicht Engine-Input.
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


#: Lookback des Detektors. **25 Minuten ab 27.11.2026** (Schritt 2,
#: Vorgabe des Betreibers) — vorher 10.
INFERRED_WINDOW_LOOKBACK_MIN: int = 25

#: Temperaturfall, ab dem der Detektor hinsieht. **1,5 Grad ab
#: 27.11.2026** — vorher 0,5. Begruendung im Modulkopf: der Pruefsatz des
#: Betreibers sind die 49 Einbrueche ab 1,5 Grad, und ueber 25 Minuten ist
#: ein halbes Grad normale Abkuehlung.
INFERRED_WINDOW_DELTA_C_MIN: Decimal = Decimal("1.5")

#: Anstieg der Ventilstellung in Prozentpunkten, der als „geht auf" gilt.
#: Fuenf, weil ein Ventil um ein bis zwei Punkte wackelt.
VENTIL_OEFFNET_MIN_PP: int = 5

#: Ab dieser Stellung gilt das Ventil als weit offen — dann braucht es
#: keinen Anstieg mehr. Ohne diesen Zweig waere der deutlichste
#: Waermeverlust unsichtbar: ein Ventil, das schon ganz offen steht, kann
#: nicht weiter aufgehen.
VENTIL_WEIT_OFFEN_PROZENT: int = 90


@dataclass(frozen=True, slots=True)
class InferredWindowResult:
    """Ergebnis einer Inferred-Window-Detection.

    Wird **nur** zur Protokollierung in ``event_log`` verwendet — keine
    Setpoint-Aktion abgeleitet.
    """

    room_id: int
    detected_at: datetime
    delta_c: Decimal  # max ueber alle Devices der Zone
    devices_observed: list[str]  # dev_eui-Liste der Devices, die ausgeloest haben
    setpoint_c: int | None  # aktueller stehender Setpoint (None wenn nie gesendet)
    #: Ventilstellung des ausloesenden Geraets am **Anfang** und am
    #: **Ende** des Fensters, in Prozent. ``None``, wenn das Geraet keine
    #: Stellung gemeldet hat — dann gibt es auch keinen Treffer, der Wert
    #: steht fuer den Fall, dass ein Aufrufer die Zahlen protokolliert.
    ventil_von: int | None = None
    ventil_bis: int | None = None


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
      4. **Und dasselbe Device hat >= 2 Ventilstellungen gemeldet, deren
         letzte „offen" bedeutet** (Anstieg um
         ``VENTIL_OEFFNET_MIN_PP`` Punkte oder >=
         ``VENTIL_WEIT_OFFEN_PROZENT``). Schritt 2 vom 27.11.2026.

    **Bedingung 4 gilt je Geraet, nicht je Zimmer.** Ein Fall an Geraet A
    und ein offenes Ventil an Geraet B sind zwei Beobachtungen und kein
    Befund; ueber die Geraete zu mischen waere die Sorte Korrelation, aus
    der Fehlalarme werden.

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

    # --- Bedingung 2+3: pro Device Δ-T und Ventilweg ---
    #
    # **Eine Abfrage, zwei Fragen.** Temperatur und Ventilstellung stehen
    # in derselben Zeile; sie getrennt zu holen waere zweimal dasselbe
    # Fenster und zwischen den beiden Abfragen kann eine Meldung
    # eintreffen (Paragraph 5.53).
    #
    # ``valve_position`` wird **nicht** auf NOT NULL gefiltert: eine
    # Meldung ohne Stellung ist trotzdem ein Temperaturmesswert. Welche
    # Zeile die Stellung traegt, entscheidet die Auswertung unten.
    sr_stmt = (
        select(
            Device.id,
            Device.dev_eui,
            SensorReading.time,
            SensorReading.temperature,
            SensorReading.valve_position,
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
    frames_by_dev: dict[int, list[tuple[datetime, Decimal, str, int | None]]] = {}
    for dev_id, dev_eui, time, temp, ventil in rows:
        if temp is None:
            continue
        frames_by_dev.setdefault(dev_id, []).append((time, temp, dev_eui, ventil))

    max_delta: Decimal = Decimal("0")
    devices_observed: list[str] = []
    ventil_von: int | None = None
    ventil_bis: int | None = None
    for frames in frames_by_dev.values():
        if len(frames) < 2:
            continue
        # Frames sind nach time ASC sortiert -> [0] oldest, [-1] newest.
        oldest_temp = frames[0][1]
        newest_temp = frames[-1][1]
        delta = oldest_temp - newest_temp  # positiv bei Fall
        if delta < INFERRED_WINDOW_DELTA_C_MIN:
            continue

        # **Der Unterscheider.** Ein Fall allein sagt nichts: ein Raum,
        # dessen Sollwert abgesenkt wurde, kuehlt genauso. Ein Fall mit
        # aufgehendem Ventil sagt, dass das Geraet gegenheizt und nicht
        # nachgekommen ist — Waermeverlust.
        stellungen = [(t, v) for t, _, _, v in frames if v is not None]
        if len(stellungen) < 2:
            # Ohne zwei Stellungen ist der Weg des Ventils unbekannt, und
            # eine Vermutung daraus waere genau der Laerm, den Schritt 2
            # vermeiden soll (Paragraph 5.55).
            continue
        von = int(stellungen[0][1])
        bis = int(stellungen[-1][1])
        if not (bis - von >= VENTIL_OEFFNET_MIN_PP or bis >= VENTIL_WEIT_OFFEN_PROZENT):
            continue

        devices_observed.append(frames[0][2])  # dev_eui, je Device gleich
        if delta > max_delta:
            max_delta = delta
            # Die Stellungen des Geraets mit dem **groessten** Fall — die
            # Zahl im Protokoll soll zum Delta daneben passen.
            ventil_von, ventil_bis = von, bis

    if not devices_observed:
        return None

    return InferredWindowResult(
        room_id=room_id,
        detected_at=now,
        delta_c=max_delta,
        devices_observed=devices_observed,
        setpoint_c=setpoint_c,
        ventil_von=ventil_von,
        ventil_bis=ventil_bis,
    )
