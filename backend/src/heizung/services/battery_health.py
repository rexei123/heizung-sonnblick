"""Sprint 15d — Batterie als additive Health-Dimension (AE-65).

Reine Funktion ``battery_health_state`` plus benannte Schwellen-Konstanten.
Eine **orthogonale dritte Achse** neben dem persistierten ``device.health_state``
(offline/implausible, AE-53): ``battery_state`` wird NICHT in ``health_state``
gefaltet, sondern als eigenes Read-Feld in ``DeviceRead`` exponiert
(``api/v1/devices.py``) und vom Dashboard-Aggregat ``battery_low_count``
(``services/dashboard_aggregates.py``) konsumiert. Die offline/implausible-
Pfade in ``tasks/health_tasks.py`` bleiben unangetastet.

Schwellen (AE-65):
  ok        : battery_percent >= warn_threshold (Default 20, konfigurierbar)
  warn      : battery_percent <  warn_threshold
  kritisch  : battery_percent <  BATTERY_CRITICAL_PCT (10, fix)
  unbekannt : battery_percent is None (kein Reading / Codec-NULL)

``warn_threshold`` kommt aus ``global_config.alert_battery_warn_percent`` —
B-15b-1s Schwellwert, hier erstmals als Health-Status verdrahtet OHNE Email/
Alarm (aktiver Versand bleibt B-15b-1). ``BATTERY_CRITICAL_PCT`` ist bewusst
NICHT konfigurierbar: Hardware-Sicherheits-Untergrenze am steilen Knie der
2xAA-Alkaline-Kennlinie (§5.72).

Prozent ist eine Integer-Anzeige (kein Decimal nötig); der Schwellen-Vergleich
läuft sauber gegen ``int``.
"""

from __future__ import annotations

from typing import Literal

# Fixe, nicht konfigurierbare Kritisch-Schwelle (AE-65). Unter 10 % liegt die
# 2xAA-Alkaline-Kennlinie im steilen Lebensend-Knie (§5.72) — Wechsel dringend.
BATTERY_CRITICAL_PCT = 10

# Defensiver Fallback, wenn die GlobalConfig-Singleton-Row fehlt (frische DB
# ohne Seed). Spiegelt den DB-Default von ``alert_battery_warn_percent``
# (Migration 0003a) — keine im Vergleichspfad hartkodierte Schwelle, sondern
# eine benannte Fallback-Konstante nur für den Row-fehlt-Fall.
DEFAULT_BATTERY_WARN_PCT = 20

BatteryHealthState = Literal["ok", "warn", "kritisch", "unbekannt"]


def battery_health_state(pct: int | None, warn_threshold: int) -> BatteryHealthState:
    """Reine Abbildung Batterie-Prozent -> Health-Zustand (AE-65).

    Reihenfolge ist verbindlich: ``unbekannt`` vor ``kritisch`` vor ``warn``
    vor ``ok``. ``kritisch`` ist absolut (gegen ``BATTERY_CRITICAL_PCT``) und
    schlägt ``warn`` auch dann, wenn ``warn_threshold`` <= 10 gesetzt wäre.

    Args:
        pct: Jüngster ``sensor_reading.battery_percent`` (0..100) oder ``None``.
        warn_threshold: ``global_config.alert_battery_warn_percent`` (Default 20).

    Returns:
        ``"unbekannt"`` wenn ``pct`` None, sonst ``"kritisch"``/``"warn"``/``"ok"``
        nach Schwelle.
    """
    if pct is None:
        return "unbekannt"
    if pct < BATTERY_CRITICAL_PCT:
        return "kritisch"
    if pct < warn_threshold:
        return "warn"
    return "ok"
