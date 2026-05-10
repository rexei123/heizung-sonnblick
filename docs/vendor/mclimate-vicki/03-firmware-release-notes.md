# MClimate Vicki — Firmware Release Notes (komprimiert)
**Quelle:** https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan/release-notes
**Abgerufen:** 2026-05-09

## Aktuelle FW-Versionen

| FW | Datum | Highlights |
|---|---|---|
| 4.7 | 02.02.2026 | Bugfix force-attach calibration loop |
| **4.6** | 05.11.2025 | **Heating Schedules** (20 Timer intern), Automatic Setback, 0–5 Scale, Custom offline target |
| 4.5 | 17.07.2025 | Bugfix S1 button stuck (HW <2.8) |
| 4.4 | 10.02.2025 | Fahrenheit/Celsius command, Hysterese-Default 0 °C |
| 4.3 | 01.03.2024 | **Anti-freeze** integriert, Temp-Range -5 °C, Setpoint 0.1 °C-Resolution, **Removal-from-backplate sendet sofort Uplink** |
| **4.2** | 26.07.2023 | **Open-Window-Detection mit 0.1 °C-Resolution**, PI-Algorithmus default, Force-Attach-Override |
| 4.1 | 23.02.2023 | **Backplate-Bit im Keepalive** (5. Bit, 8. Byte), Online-Bit, microstepping |
| 4.0 | 12.04.2022 | FUOTA, Proportional Algo, Remote-Reset |
| 3.5 | 02.12.2021 | Open-Window-Function added (default automatic mode!) |

## Welche FW läuft auf unseren Vickis?

**Müssen wir per ChirpStack `0x04` (getDeviceVersions) abfragen.** Erst dann
wissen wir, welche Commands verfügbar sind.

**[Annahme]** Vicki-001 bis 004 sind im EU-Markt 2024/2025 ausgeliefert,
also wahrscheinlich FW ≥ 4.3. Falls ≥ 4.2 → Open-Window-Command 0x45 verfügbar.

## Wichtige Bits zum Mitnehmen

### Backplate-Bit im Keepalive (FW ≥ 4.1)
> Added a bit to the keepalive to report whether Vicki is attached to a backplate or not.

Konkret: 5. Bit des 8. Bytes im Keepalive-Frame. Codec macht daraus
`attachedBackplate: true|false`. Im Cowork-Test heute war das Feld
durchgehend `true` — die Vicki war montiert.

### Removal sends immediate uplink (FW ≥ 4.3)
> When the device is removed from the backplate, it sends immediate uplink.

Heißt: Im Hotelbetrieb meldet der Vicki Demontage **sofort**, nicht erst
beim nächsten Keepalive. Wir können `attachedBackplate=false` als
verlässlichen Demontage-Indikator nehmen.

### Heating Schedules (FW 4.6)
> Up to 20 individual timers running internally.

**Architektur-Implikation:** In Sprint 9.15 (Profile-Konzept) müssen wir
entscheiden: Schedules in unserer Engine zentral, oder in der Vicki delegiert?
Vicki-intern = robust gegen Backend-Ausfall, aber 4 Devices × verschiedene
Profile = aufwendige Synchronisation. Backend-zentral = simpler, aber
abhängig von Connectivity. **Empfehlung: Backend-zentral, Vicki-Schedules
nicht nutzen.** Reduziert Variablen, hält single source of truth.

### Automatic Setback (FW 4.6)
> Ability to set a timeout for manual target temperature changes.

**Konflikt mit AE-45:** Wir haben unseren eigenen 7-Tage-Auto-Override-
Mechanismus für Hand-Änderungen am Vicki-Drehrad. Wenn Vicki nun selbst
einen Setback macht, kollidieren beide Logiken. **Action:** Vicki-Setback
auf disable lassen (Default), wenn FW 4.6 vorhanden.

### Force-Attach (Bug bis FW 4.7)
> Force-attach feature doesn't work properly, do not use it.

Nicht relevant für uns — wir nutzen den Befehl nicht.

## Empfehlungen für unser Projekt

1. **Sofort:** FW-Versionen aller 4 Vickis abfragen via Downlink `0x04` →
   in DB als `device.firmware_version` persistieren (neues Feld).
2. **Open-Window-Detection aktivieren** auf Vickis mit FW ≥ 4.2:
   `0x4501020F` = enabled, 10 Min closed, 1.5 °C delta.
3. **Backplate-Bit ins Backend persistieren** (`sensor_reading.attached`).
   Ohne das ist Demontage-Erkennung blind.
4. **Vicki-Schedules NICHT nutzen.** Profile-Konzept (Sprint 9.15) bleibt
   backend-zentral.
5. **Vicki-Setback NICHT aktivieren.** Konflikt mit AE-45.
