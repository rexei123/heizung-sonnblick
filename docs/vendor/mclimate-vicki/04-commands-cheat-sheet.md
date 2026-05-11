# MClimate Vicki — Commands Cheat Sheet
**Quelle:** https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan/vicki-lorawan-device-communication-protocol/command-cheat-sheet
**Abgerufen:** 2026-05-09

## Uplinks (von Vicki an Server)

| Hex | FW | Name |
|---|---|---|
| `81` | ≥3.5 | **Keep-alive** (neue Temp-Formel) — unsere Vickis senden das alle 10 Min |
| `01` | <3.5 | Keep-alive (alte Temp-Formel) |
| `28` | ≥3.5 | **Manual target temp change** (Gast dreht am Vicki-Drehrad) |
| `A6` | ≥4.6 | External crystal not working |

## Configuration Commands (Server → Vicki)

### Setup / Network (alle FW)
| Hex | Name |
|---|---|
| `02` | Set keep-alive period |
| `03` | Recalibrate motor |
| `04` | Read device hardware and software version |
| `10` | Set network join retry period |
| `11` | Set uplink messages type (confirmed/unconfirmed) |
| `1C` | Set radio communication watch-dog parameters |
| `30` | Device reset |

### Operational Mode + Algorithm
| Hex | FW | Name |
|---|---|---|
| `0D` | All | Set device online operational mode (00=manual, 01=auto, 02=auto+ext) |
| `1E` | All | Set primary mode (00=heating default, 01=cooling) |
| `2C` | ≥3.5 | Set temperature control algorithm (00=Proportional, 02=PI) |

### Temperature
| Hex | FW | Name |
|---|---|---|
| `0E` | ≥3.5 | Set target temperature (1 °C resolution) |
| `51` | ≥4.3 | Set target temperature 0.1 °C resolution |
| `08` | All | Set temperature ranges (min/max) |
| `0F` | ≥3.5 | External temperature sensor reading 1.0 |
| `3C` | ≥4.2 | External temperature sensor reading 0.1 |
| `53` | ≥4.3 | Set internal temperature offset |

### Open-Window-Detection — KERN FÜR UNSEREN BEFUND
| Hex | FW | Name | Default |
|---|---|---|---|
| `06` | All | Set open-window 1.0 °C accuracy | **disabled** |
| `45` | ≥4.2 | **Set open-window 0.1 °C accuracy** | **disabled** |
| `13` | All | Get open-window 1.0 |
| `46` | ≥4.2 | Get open-window 0.1 |

### Anti-Freeze (FW ≥ 4.3)
| Hex | Name |
|---|---|
| `49` | Set anti-freeze parameters |
| `4A` | Get anti-freeze parameters |

### Valve Position
| Hex | FW | Name |
|---|---|---|
| `2D` | ≥3.5 | Set motor position only (Manual mode) |
| `31` | ≥3.5 | Set motor position + target temp |
| `4E` | ≥4.3 | Set valve openness in % |
| `4F` | ≥4.3 | Set valve openness range (min/max %) |
| `0B` | ≥3.5 | Force-close (overvoltage detection) |
| `47` | ≥4.2 | Set force-attach (BUGGY in 4.5/4.6, OK in 4.7) |

### PI-Algorithm-Tuning (FW ≥ 4.2)
| Hex | Name |
|---|---|
| `36`/`37` | GET/SET Proportional gain |
| `3D`/`3E` | GET/SET Integral gain |
| `40`/`41` | GET/SET PI run period |
| `42`/`43` | GET/SET temperature hysteresis (Thys) |
| `4C`/`4D` | GET/SET Maximum allowed Integral value |

### Heating Schedules (FW ≥ 4.6, Vicki-intern, **NICHT NUTZEN**)
| Hex | Name |
|---|---|
| `59`/`5A` | Set/Get heating event details |
| `6B`/`6C` | Activate/deactivate heating events |
| `5B`/`5C` | Heating season start/end dates |
| `61`/`62` | Automatic setback temperature |
| `65`/`66` | Target setpoint when offline |

### Time (FW ≥ 4.6)
| Hex | Name |
|---|---|
| `5D`/`5E` | Set/Get device time |
| `5F`/`60` | Set/Get device time zone |
| `6D`/`6E` | Automatic time syncing via LoRaWAN |

### Sonstiges
| Hex | FW | Name |
|---|---|---|
| `07` | All | Child lock |
| `34`/`35` | ≥4.1 | Child lock behavior when offline |
| `33` | ≥4.1 | Set LoRaWAN AppEUI & AppKey |
| `55`/`56` | ≥4.4 | LED display temperature units (°C/°F) |
| `57` | ≥4.4 | Set target temperature in Fahrenheit |

## Konkrete Downlinks für unser Setup

### 1. Firmware-Version aller Vickis abfragen
**Command:** `0x04`

**Reply-Format (korrigiert 2026-05-11, Sprint 9.11x.c):**

Die ursprüngliche Vendor-Doku-Beschreibung
`0x04{HW_major}{HW_minor}{FW_major}{FW_minor}` ist **ungenau**. Echte
Vicki-Hardware sendet 3 Bytes mit Nibble-Split, plus optional einen
eingebetteten Keep-alive-Frame (Cmd `0x81`) im selben Uplink:

```
Byte 0  : 0x04 (Reply-Cmd)
Byte 1  : HW-Version  — high-nibble=Major, low-nibble=Minor
          (z.B. 0x26 → HW 2.6)
Byte 2  : FW-Version  — high-nibble=Major, low-nibble=Minor
          (z.B. 0x44 → FW 4.4)
Byte 3+ : optional eingebetteter Periodic-Keep-alive-Frame,
          siehe Periodic-v2-Layout (Cmd 0x81)
```

**Quelle:** empirische Beobachtung Vicki MC-LW-V02-BI-RUGGED am
2026-05-11, Roh-Bytes `04 26 44 81 14 97 62 a2 a2 11 e0 30`.
Vicki-001 hat damit HW 2.6, FW 4.4. Drift-Schutz im Backend via
`backend/tests/test_codec_mirror.py::test_decode_fw_reply_*`-Wachposten.

### 2. Open-Window-Detection aktivieren (FW ≥ 4.2)
**Command:** `0x4501020F`
- Byte 1 = 01 → enabled
- Byte 2 = 02 → 02 × 5 = 10 Min Ventil zu
- Byte 3 = 0F → 15 / 10 = 1.5 °C Delta

Aggressivere Variante: `0x4501020A` für 1.0 °C Delta (aber unter 1.5 °C
gibt es im Hotelbetrieb mehr Falsch-Positive).

### 3. Open-Window-Status abfragen
**Command:** `0x46`
Vicki antwortet `0x46{enabled}{duration}{delta}`.

### 4. Auto-Mode bestätigen
**Command:** `0x18` → erwartet Response `0x1801` (auto mode).

### 5. PI-Algorithmus bestätigen (FW ≥ 4.3 nur PI)
**Command:** `0x2B` → erwartet `0x2B02` (PI).
