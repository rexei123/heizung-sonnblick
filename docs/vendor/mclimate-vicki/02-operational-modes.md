# MClimate Vicki — Operational Modes & Temperature Control Algorithms
**Quelle:** https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan/vicki-lorawan-device-communication-protocol/operational-modes-and-temperature-control-algorithm
**Abgerufen:** 2026-05-09

## 4 Operational Modes

| Mode | ID | Beschreibung | Default |
|---|---|---|---|
| Offline | — | Nicht netzverbunden, internal algorithm steuert | Auto-Fallback |
| Manual control | `00` | Server gibt motorPosition direkt vor | Default f.w. ≤ 3.4 |
| Automatic temperature control | `01` | Server gibt targetTemperature, internal algo steuert | **Default f.w. ≥ 3.5** |
| Automatic with external temp reading | `02` | Externer Sensor + Server-Target | nur explizit |

**Set-Command:** `0x0D{XX}` — z.B. `0x0D01` für Auto.
**Get-Command:** `0x18` → Response `0x18{XX}`.

## Temperature Control Algorithms

| Algorithm | f.w. | Default |
|---|---|---|
| Equal Directional | < 4.2 | deprecated |
| Proportional | 4.0–4.2 | Default 4.0+ |
| Proportional Integral (PI) | ≥ 4.2 | **Default 4.2+** |

**Set:** `0x2C{XX}` (00=Proportional, 02=PI)
**Get:** `0x2B` → Response `0x2B{XX}`

In f.w. ≥ 4.3 ist nur noch PI verfügbar.

## Heating vs Cooling Mode

**Set:** `0x1E00` heating (default), `0x1E01` cooling.
**Get:** `0x1F` → Response `0x1F{XX}`

Wichtig für unseren Sommermodus: Cooling-Mode könnte relevant werden, wenn
in Zukunft Klimaanlagen-Domain dazukommt. Aktuell auf heating belassen.

## Wichtig für unseren Use-Case

- Vicki im Hotel sollte in Mode `01` (Auto) laufen — Server schickt Setpoint,
  Vicki regelt lokal mit PI-Algorithmus.
- Mode `02` (External Temp) wäre relevant, wenn wir später externe Raumsensoren
  einsetzen, weil HK-Wärme den Vicki-Sensor verfälscht. Open-Window-Detection
  funktioniert in Mode `02` aber weiterhin nur über internen Sensor.
- Cooling-Mode auf heating belassen.
