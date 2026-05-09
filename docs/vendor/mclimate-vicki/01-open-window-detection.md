# MClimate Vicki — Open Window Detection
**Quelle:** https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan/vicki-lorawan-device-communication-protocol/open-window-detection
**Abgerufen:** 2026-05-09

## Funktionsprinzip (offizielle Aussage von MClimate)

> The open window detection function works by looking for a sudden drop in temperature.
> The detection algorithm takes readings every 1 minute, if the temperature dropped
> more than the threshold value, the valve is closed.
>
> **Therefore, it's not 100% reliable and can be affected by outdoor temperature,
> position of the device on the radiator, position of the radiator in the room
> and more factors.**

## Default-Verhalten — KRITISCH FÜR UNSEREN BEFUND

- **Default-Status: DISABLED.** Open Window Detection ist aus Werk **deaktiviert**.
- Default-Temperatur-Delta wenn aktiviert: 1.0 °C in 1 Minute (sehr aggressiv)
- Default-Dauer: 10 Min Ventil zu

Das erklärt unseren Test 2 vollständig: Die Vicki sendet `openWindow=false`
weil die Funktion nie aktiviert wurde.

## Konfiguration via LoRaWAN-Downlink

### Firmware >= 4.2 (delta-Genauigkeit 0.1 °C)

**SET-Command Byte 0:** `0x45`
- Byte 1: 1 = enable, 0 = disable
- Byte 2: Dauer × 5 Min (Default 2 = 10 Min)
- Byte 3: Delta × 10 (z.B. 0x0F = 1.5 °C; Minimum 0.2 °C)

**Beispiel:** `0x4501060D`
- enable
- 0x06 × 5 = 30 Min
- 0x0D / 10 = 1.3 °C Delta

**GET-Command:** `0x46` → Response `0x4601020F` heißt enabled, 10 Min, 1.5 °C

### Firmware < 4.2 (delta-Genauigkeit 1.0 °C)

**SET-Command Byte 0:** `0x06`
- Byte 1: enable/disable
- Byte 2: Dauer × 5 Min
- Byte 3+4: Motor-Position + Delta in Celsius

**Beispiel:** `0x0601041C23` enable, 20 Min, 540 Steps, 3 °C
**Beispiel disable:** `0x0600041C23`

## Warnung aus Doku

> If you are in "02 – Online automatic control mode with external temperature reading"
> mode the Vicki will use an external temperature reading. **It will still use its
> internal readings to determine whether or not the window has been opened**, not
> the external temperature measurement.

→ Externer Temperatur-Sensor hilft nicht für Open-Window-Detection.

## Was das für unser Projekt bedeutet

1. **Sofort-Action:** Wir können die Vicki via Downlink konfigurieren —
   Open Window Detection aktivieren mit niedrigem Delta (z.B. 0.5 °C).
2. **Realismus:** Selbst dann ist die Erkennung laut Hersteller "not 100% reliable" —
   das deckt sich mit unserer Beobachtung. Backend-Eigenlogik bleibt notwendig.
3. **Strategie:** Hybrid — Vicki-Hardware-Erkennung als schneller Trigger (1 Min
   Granularität, lokal vor Ort) + Backend-Eigenlogik als Fallback und
   Plausibilitäts-Check (Trend über 5–10 Min im sensor_reading-Hypertable).
