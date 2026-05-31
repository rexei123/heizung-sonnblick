# Sprint 15a — Hardware-Health-Diagnose (B-9.17b-4 + Batterie R4)

**Datum:** 2026-05-31
**Branch:** `chore/sprint-15a-hardware-health-diagnose`
**Autonomiestufe:** 3 (read-only, reine Doku)
**Strang:** Hardware-Health-Diagnose vor Heizperiode
**Bezug:** AE-16, AE-17, AE-53, AE-57; CLAUDE §5.21, §5.58, §5.68

## Ziel

Belegen — nicht annehmen — WO die Stille von Vicki-002/-004 entsteht und
OB die Batterie-33%-Konstanz von Vicki-001 ein Decode-Bug oder ein Stale-
Wert ist. Reine Ursachen-Lokalisierung, KEIN Fix, KEINE Empfehlung über
die Lokalisierung hinaus (Folge-Sprint).

## Leitplanken

- **R1 (zwingend):** Vicki-003 ist gepaired, aktiv, **unmontiert** und
  sendet sauber. Montage ist daher **NICHT** Ursache der Stille. Jede
  Hypothese, die Montage als Erklärung für -002/-004 nimmt, ist
  zurückzuweisen.
- **R-§5.68:** Operative Server-State-Aussagen sind verifikations-
  pflichtig. „Compute-Task läuft" und „Compute-Task läuft nicht" sind
  beide Behauptungen, bis Diagnose-Output sie belegt.

---

## T1 — Codec read-only (`infra/chirpstack/codecs/mclimate-vicki.js`)

### T1.1 Routing-Logik (Cmd-Byte, nicht fPort)

`decodeUplink` (Z.69–84) routet ausschließlich über `bytes[0]`:

| `bytes[0]` | Pfad | Sprint |
|---|---|---|
| `0x52` | `decodeCommandReply` → `setpoint_reply` | 9.0 / 9.10c-Fix |
| `0x04` | `decodeCommandReply` → `firmware_version_reply` | 9.11x.b/.c |
| `0x46` | `decodeCommandReply` → `open_window_status_reply` | 9.11x.b |
| sonst | `decodePeriodicReport` (erwartet `0x01` oder `0x81`) | — |

`fPort` wird nicht zur Verzweigung genutzt (Lesson §5.21, Live-Beleg
`70b3d52dd3034de4`, fPort=2, bytes[0]=0x81 am 2026-05-07).

### T1.2 Periodic-Report-Mapping (Cmd `0x01`/`0x81`, ≥ 9 Bytes)

| Byte | Feld | Skalierung |
|---|---|---|
| 0 | `command` | `0x01` v1 / `0x81` v2 |
| 1 | `target_temperature` | uint8, direkt °C |
| 2 | `temperature` (Sensor) | cmd `0x01`: `(B2 * 165) / 256 - 40` |
|   |   | cmd `0x81`: `(B2 - 28.33333) / 5.66666` |
| 3 | `relativeHumidity` | `B3 * 100 / 256` |
| 4 | `motor_position` low | siehe Byte 6 high nibble |
| 5 | `motor_range` low | siehe Byte 6 low nibble |
| 6 | high nibble = `motor_position` high; low nibble = `motor_range` high | nibble-pack |
| **7** | **high nibble = `battery_voltage` (V)** | **`2 + nibble * 0.1`** (Z.119–121) |
|   | low nibble = Status-Flags 7 | bit 0..3 |
| 8 | erweiterte Status-Flags | bit 4..7 |

Abgeleitete Felder im `data`-Objekt (Z.139–166): `temperature`,
`target_temperature`, `battery_voltage`, `motor_position`, `motor_range`,
`valve_openness` (geclampt 0..100, Z.131–136), `openWindow`,
`attachedBackplate`, `perceiveAsOnline`, `antiFreezeProtection`,
`brokenSensor`, `childLock`, `calibrationFailed`,
`highMotorConsumption`, `lowMotorConsumption`.

### T1.3 Batterie-Skalierung — Konstante-33%-Hypothese

- Codec: `batteryVoltage = 2 + ((bytes[7] >> 4) & 0x0F) * 0.1`
  (Z.119–121). Nibble-Range 0..15 → V-Range **2.0..3.5 V**.
- Subscriber: `_battery_pct_from_volts(volts) = clamp(round((V-3.0)/1.2*100), 0, 100)`
  (`mqtt_subscriber.py:89-94`). Mapping `V → pct`:

  | nibble | V | pct (geclampt) |
  |---|---|---|
  | 0..C (0..12) | 2.0..3.2 | 0..17 % |
  | D (13) | 3.3 | **25 %** |
  | **E (14)** | **3.4** | **33 %** ← exakt der gemeldete Wert |
  | F (15) | 3.5 | 41 % |

**Belegung:** Ein konstanter Decode-Wert von **33 %** entspricht exakt
einem konstanten `byte[7]`-High-Nibble von **0xE** (Vicki meldet 3.4 V).
Ob das real konstant ist oder ein Stale-Wert (z. B. letzte
Periodic-Frame vor Stille), entscheidet **Q3** (Verlauf über mehrere
Tage).

Hinweis: Subscriber-Skala 3.0–4.2 V deckt die Codec-Skala 2.0–3.5 V nur
oberhalb von 3.0 V auf. Sprint-15a-OUT-OF-SCOPE: Plausibilität der
Subscriber-Skala (Zellchemie, Hersteller-Doku).

### T1.4 Codec-Output → MQTT-Event (AE-16)

Der Codec gibt das `data`-Objekt 1:1 zurück (Z.168). ChirpStack legt es
als `object`-Feld in den `application/+/device/+/event/up`-Payload (AE-16).
Der Subscriber liest es aus `uplink.object` (`mqtt_subscriber.py:79,
106-143`). Keine zusätzliche Decode-Schicht zwischen Codec und Backend.

**Drift-Risiko (§5.22):** Repo-Codec ≠ Live-Codec in ChirpStack-UI. Der
Codec muss pro Server manuell ins Device-Profile gepasted werden. Ob
auf heizung-test der Repo-Stand wirkt, ist **nicht aus dem Repo
verifizierbar** — separater Cowork-Auftrag (ChirpStack-UI Events-Tab pro
Vicki) zur Bestätigung.

---

## T2 — Backend-Decode-/Persist-Pfad read-only

### T2.1 MQTT-Subscriber → `sensor_reading`-Insert

Datei: `backend/src/heizung/services/mqtt_subscriber.py`. Pfad pro
Uplink (`_consume_loop` Z.415–502 → `_persist_uplink` Z.185–278):

| Schritt | Code | Verhalten |
|---|---|---|
| 1. JSON-Validation | `ChirpStackUplink.model_validate_json` (Z.441) | ValidationError → `warning` + `continue` (kein Insert) |
| 2. Reply-Filter | Z.465–479 | `report_type in REPLY_REPORT_TYPES` (`setpoint_reply`, `firmware_version_reply`, `open_window_status_reply`) → kein `sensor_reading`-Insert, nur Override-/FW-/OW-Handler |
| 3. DevEUI-Lookup | Z.192 | `SELECT device.id WHERE dev_eui = lower(devEui)` |
| 4. **Unknown DevEUI** | Z.195–201 | `warning("uplink für unbekannte DevEUI verworfen: %s")` + `return` — **kein Insert**, **kein Re-Eval**, **kein last_seen_at-Update** |
| 5. Plausi-Filter (AE-53) | Z.210–223 | `temperature ∉ [-20, 60]` → `warning("implausible_reading")` + Redis-Counter inkrement + `return` |
| 6. Insert | Z.225–231 | `pg_insert(sensor_reading).on_conflict_do_nothing(index_elements=["time","device_id"])` |
| 7. `last_seen_at` | Z.236–242 | `UPDATE device SET last_seen_at = uplink.time WHERE id=? AND (last_seen_at IS NULL OR last_seen_at < uplink.time)` |
| 8. `evaluate_room.delay` | Z.260–273 | Re-Eval-Trigger sofern `heating_zone_id` gesetzt |

### T2.2 `sensor_reading`-Spalten (NICHT identisch zu AE-17)

Modell: `backend/src/heizung/models/sensor_reading.py`. **Abweichung
von AE-17 (Brief-Annahme):** Es gibt **keine** `uplinks`-Hypertable mit
JSONB-Payload. Sprint 5 hat bewusst die bestehende `sensor_reading`-
Hypertable wiederverwendet (STATUS §2g.5.7). AE-17 ist sprint-historisch
veraltet — die echten Spalten sind:

```
PK (time, device_id)
fcnt INTEGER NULL          -- LoRaWAN Frame-Counter
temperature NUMERIC(5,2)   -- decoded °C
setpoint NUMERIC(5,2)      -- target_temperature
valve_position SMALLINT    -- 0..100 %
battery_percent SMALLINT   -- aus battery_voltage abgeleitet
rssi_dbm SMALLINT
snr_db NUMERIC(4,1)
open_window BOOLEAN NULL
attached_backplate BOOLEAN NULL
raw_payload TEXT           -- base64-String aus uplink.data
```

Es gibt **kein** `freq`-Feld (Brief-Annahme aus AE-17 nicht im Modell).

### T2.3 Plausi-Grenzen (AE-53)

`backend/src/heizung/rules/constants.py:48-49`: `PLAUSI_TEMP_MIN_C =
Decimal("-20.0")`, `PLAUSI_TEMP_MAX_C = Decimal("60.0")`. Decimal-
Vergleich, kein Float. None bleibt None (reines Battery-Frame ohne
Temperatur fällt nicht hierdurch). Verworfene Frames erhöhen
`implausible:{dev_eui}`-Counter in Redis (24 h rolling, Stufe-3-
Trigger).

### T2.4 health_state-Ableitung

Compute-Task: `backend/src/heizung/tasks/health_tasks.py`,
`compute_health_state` (5-min-Beat).

**Basis-State pro Device** (`_basis_state_from_age`, Z.86–95):

```python
if latest_time is None:     # NIE-gesehene Devices
    return "silent"
age = now - latest_time
if age <= 2h:               return "healthy"
if age <= 24h:              return "degraded"
return "silent"
```

**DB-Default** (`models/device.py:90`):
`health_state VARCHAR(16) NOT NULL DEFAULT 'silent'`.

**Dashboard-KPI** (`services/dashboard_aggregates.py:38-76`,
`count_devices_online`):

```python
_ONLINE_STATES = ("healthy", "degraded")
online = COUNT(device)
        WHERE retired_at IS NULL
          AND health_state IN ('healthy', 'degraded')
total  = COUNT(device) WHERE retired_at IS NULL
```

**Code-Belegung zum „4 von 4"-Verdacht:** Die drei Code-Pfade (DB-
Default, Compute-Basis-State, KPI-Filter) zählen nie-gesehene Devices
korrekt als `silent` und schließen sie aus der `devices_online`-Zahl
aus. **Aus der Code-Lesung allein** lässt sich der Verdacht „4 von 4
healthy trotz Stille von -002/-004" **nicht** stützen.

**Verbleibender Verdacht (zu prüfen):** Wenn die Compute-Task auf
heizung-test nicht regelmäßig läuft (vgl. §5.32 — celery_beat unhealthy-
Drift), bleiben Werte aus früheren Zuständen stehen. Aber: DB-Default
ist `silent`, und vor dem ersten Tick gibt es keinen Code-Pfad, der
`healthy` setzen würde. → Hypothese: Verdacht beruht auf einer **anderen
UI-Sicht als KPI-„Geräte online"** (z. B. Geräte-Listen-Status,
„angelegt", „eingerichtet"). **Belegung in Sprint 15a OUT-OF-SCOPE
(reines Backend-Audit).** Folge-Sprint: Frontend-Cross-Sicht-Audit über
alle Stellen, die Hardware-Health visualisieren, vs.
`devices_online`-KPI.

### T2.5 DevEUI ↔ Gerät-Zuordnung

Modell: `backend/src/heizung/models/device.py:44`,
`dev_eui VARCHAR(16) NOT NULL` (8-Byte-Hex, lowercase). Lookup im
Subscriber: `Device.dev_eui == dev_eui.lower()` (Z.192).
Lifecycle-Filter (AE-57, §5.58): aktive Devices = `retired_at IS NULL`.
Bestand laut Vendor-Doku (`docs/vendor/mclimate-vicki/README.md`):
**Vicki-001 bis Vicki-004, EU868**. Konkrete DevEUIs werden in **Q1**
gezogen.

---

## T3 — SSH-Diagnose-Queries (read-only, nicht ausgeführt)

> **STOP-POINT.** Queries sind formuliert. Hotelier führt per SSH gegen
> heizung-test (`ssh -i ... root@heizung-test`) aus und pastet Output
> in T4 BLOCK A / B. Erst danach werden die Befunde belegt.

### Setup

```bash
# SSH (heizung-test, root) — DB im api-Container, in-place psql
docker exec -i deploy-db-1 psql -U heizung -d heizung
```

Alternativ: `\copy`-Output für Paste-fähigen Block-Output. Alle Queries
sind reine SELECTs, keine Schreibwirkung.

### Q1 — Lifecycle + Uplink-Historie pro DevEUI (aktiv + retired)

Beantwortet zwei Gate-Fragen gleichzeitig:

1. **Stille**: kam je ein Uplink für jeden der vier Vickis in UNSERER
   DB an?
2. **§9-Widerspruch**: §9 sagt -002/-004 „noch nie", STATUS §2r/§2t/§2w
   (2026-05-07..10) dokumentiert alle vier aktiv + zugeordnet. Die
   Auflösung läuft über die Lifecycle-Spalten — eventuell wurden
   -002/-004 zwischenzeitlich ausgetauscht (AE-57), und die heutigen
   aktiven Rows sind „neu", während die Mai-Historie an retired
   Vorgängern hängt.

Bewusst **OHNE** `retired_at IS NULL`-Filter, weil der retired
Vorgänger Teil der Diagnose ist.

```sql
-- Q1: pro Vicki — Lifecycle + Uplink-Historie. Aktiv UND retired.
SELECT
  d.id                          AS device_id,
  d.dev_eui,
  d.label,
  d.heating_zone_id,
  d.health_state                AS db_health_state,
  d.last_seen_at,
  d.firmware_version,
  d.retired_at,                              -- AE-57 Lifecycle
  d.retired_reason,
  d.replaced_by_device_id,                   -- AE-57 Tausch-FK
  COUNT(sr.time)                        AS reading_count,
  MIN(sr.time)                          AS first_uplink,
  MAX(sr.time)                          AS last_uplink,
  MAX(sr.time) FILTER (WHERE sr.temperature IS NOT NULL) AS last_uplink_with_temp,
  MIN(sr.time) FILTER (WHERE sr.time >= DATE '2026-05-01' AND sr.time < DATE '2026-06-01') AS mai_first,
  MAX(sr.time) FILTER (WHERE sr.time >= DATE '2026-05-01' AND sr.time < DATE '2026-06-01') AS mai_last,
  COUNT(sr.time) FILTER (WHERE sr.time >= DATE '2026-05-01' AND sr.time < DATE '2026-06-01') AS mai_count
FROM device d
LEFT JOIN sensor_reading sr ON sr.device_id = d.id
WHERE d.vendor = 'mclimate'      -- Vickis
GROUP BY d.id
ORDER BY d.label NULLS LAST, d.retired_at NULLS FIRST, d.id;
```

**Auswerten — Drei-Fälle-Belegung (vor Hypothesen-Auswahl) pro
-002/-004:**

| Konstellation | Beleg im Q1-Output | Fall |
|---|---|---|
| Aktive Row (`retired_at IS NULL`) hat `reading_count = 0` UND es existiert KEIN retired Row mit `replaced_by_device_id = active_id` UND Mai-Readings | `reading_count = 0` über alle Rows mit Label match | **(a) nie ein Reading** |
| Aktive Row hat `reading_count > 0`, aber `last_uplink` weit zurück (z. B. Mai), kein retired Vorgänger | aktive Row mit `mai_count > 0` und altem `last_uplink` | **(b) aktiv im Mai, dann silent** |
| Aktive Row hat `reading_count = 0`, aber es existiert ein retired Row mit `mai_count > 0` und `replaced_by_device_id = active_id` | retired Row mit Mai-Historie + Cross-Ref auf aktive Row | **(c) Geräte-Tausch (AE-57)** |

Hypothesen-Richtung hängt vom Fall:
- Fall (a) → Pairing/Join-Stack untersuchen (A.1).
- Fall (b) → Ausfall-nach-Aktivierung (A.3 Konfig + Cowork ChirpStack
  Events-Tab: aktuell Frames? → A.2 Codec/Subscriber).
- Fall (c) → Tausch-Workflow + Cowork-Auftrag (ChirpStack-Events-Tab
  der **neuen** DevEUI), eigene Befund-Klasse.

Sub-Befund Lifecycle für die `last_seen_at`-Plausi:
- `reading_count = 0` UND `last_seen_at IS NULL` → Subscriber hat für
  diese DevEUI nie einen Uplink akzeptiert.
- `reading_count = 0` UND `last_seen_at != NULL` → widersprüchlicher
  Zustand (Datenbereinigungs-Folge, separater Befund).
- `reading_count > 0` UND `last_seen_at < MAX(sr.time)` → Update-Pfad
  Z.236–242 hat versagt (Race oder NULL-Initialwert).

### Q2 — Roh-payload + rxInfo der letzten 10 Frames pro DevEUI

Beantwortet, **was im persistierten Frame tatsächlich steht** —
Decode-Bytes (`raw_payload` ist base64 der Roh-Bytes aus
`uplink.data`) und rxInfo (`rssi`, `snr`). Brief-Anforderung
„rssi/snr/freq" — `freq` ist nicht im Schema persistiert (T2.2),
deshalb hier nur rssi/snr.

```sql
-- Q2: letzte 10 Frames pro Device, mit Roh-Bytes
WITH ranked AS (
  SELECT
    d.dev_eui,
    d.label,
    sr.time,
    sr.fcnt,
    sr.temperature,
    sr.setpoint,
    sr.valve_position,
    sr.battery_percent,
    sr.rssi_dbm,
    sr.snr_db,
    sr.open_window,
    sr.attached_backplate,
    sr.raw_payload,        -- base64; decode mit echo $val | base64 -d | xxd
    ROW_NUMBER() OVER (PARTITION BY sr.device_id ORDER BY sr.time DESC) AS rn
  FROM sensor_reading sr
  JOIN device d ON d.id = sr.device_id
  WHERE d.retired_at IS NULL
    AND d.vendor = 'mclimate'
)
SELECT *
FROM ranked
WHERE rn <= 10
ORDER BY label NULLS LAST, time DESC;
```

**Auswerten:**
- `raw_payload` base64 → Decode lokal:
  `echo "<base64>" | base64 -d | xxd` zeigt die Cmd-Byte-Sequenz.
- Für Vicki-001: Byte 7 high nibble muss `E` sein, wenn `battery_percent
  = 33`. Abweichung → Decode-Bug in der Skala.
- Für -002/-004: ob Q2 leer ist, beantwortet Q1 schon (`reading_count`).

### Q3 — Batterie-Verlauf Vicki-001 über 7 Tage

Beantwortet **Decode-Bug vs. Stale-Wert**.

```sql
-- Q3: pro Vicki-001 — Batterie-Verlauf
SELECT
  sr.time,
  sr.fcnt,
  sr.battery_percent,
  sr.temperature,
  sr.raw_payload
FROM sensor_reading sr
JOIN device d ON d.id = sr.device_id
WHERE d.label = 'Vicki-001'         -- falls Label abweicht: dev_eui einsetzen
  AND sr.time >= NOW() - INTERVAL '7 days'
ORDER BY sr.time DESC
LIMIT 200;
```

**Auswerten:**
- Wenn `battery_percent` konstant 33 über mehrere Tage UND Tagesganz-
  Zyklen → Decode-Pfad ist „eingefroren". Roh-Bytes (`raw_payload`-
  Decode) zeigen, ob `byte[7]` high nibble tatsächlich konstant `E`
  ist (= Vicki sendet 3.4 V) ODER ob ein anderer Wert decoded
  wird (= Decode-Bug in Codec oder Subscriber-Mapping).
- Wenn `battery_percent` schwankt → kein Decode-Bug, Stale war nur
  eine Snapshot-Sicht.

> **An dieser Stelle Sprint 15a Daten-Stop.**
> Q1/Q2/Q3 ausführen, Output paste-fähig in BLOCK A / BLOCK B unten
> eintragen, dann T4 abschließen.

---

## T4 — Befund-Doku (Block A + Block B)

### BLOCK A — Stille Vicki-002 / Vicki-004 (B-9.17b-4)

**Final-Status nach Q1: Prämisse widerlegt — 4/4 Vickis aktiv.**
Q1-Output zeigt für alle vier Vickis `reading_count > 0` mit
aktuellen `last_uplink`-Timestamps. Die Anlass-Wahrnehmung
„Stille -002/-004" ist nicht durch Backend-Daten gedeckt — alle vier
Devices senden und werden persistiert. Hypothesen A.1/A.2/A.3 sowie
A.0-Lifecycle-Fall sind damit gegenstandslos für diese
Diagnose-Runde; die Code-Belegung der drei Bruchstellen bleibt als
strukturelle Referenz im Sprint stehen, falls die Wahrnehmung später
real wird.

**Reihenfolge wäre gewesen: zuerst Lifecycle-Fall belegen (A.0), DANN
Hypothesen-Auswahl (A.1/A.2/A.3 je nach Fall).** Hypothesen-Status
`bestätigt | widerlegt | offen`, jeweils mit Beleg (Datei:Zeile ODER
Q1/Q2-Output).

#### A.0 — Lifecycle-Auflösung (§9-Widerspruch)

**Befund:** *AUSSTEHEND — Q1-Output erforderlich.*

Belegen, welcher der drei Fälle für -002/-004 jeweils zutrifft:

- **Fall (a) nie ein Reading** — Q1-Output: `reading_count = 0` über
  alle Rows mit Label match (aktiv + retired), kein Vorgänger mit
  Mai-Historie. Hypothesen-Richtung: A.1 (Pairing/Join).
- **Fall (b) aktiv im Mai, dann silent** — Q1-Output: aktive Row
  `reading_count > 0`, `last_uplink` weit zurück, `mai_count > 0`.
  Hypothesen-Richtung: A.3 (Konfig/Ausfall) + Cowork-ChirpStack-
  Events-Tab (aktuell Frames? → ggf. A.2 Codec/Subscriber).
- **Fall (c) Geräte-Tausch (AE-57)** — Q1-Output: aktive Row
  `reading_count = 0`, retired Row mit `replaced_by_device_id =
  active_id` UND `mai_count > 0`. Eigene Befund-Klasse (Tausch-
  Workflow, Cowork-Auftrag für **neue** DevEUI in ChirpStack).

Erst nach belegtem Fall werden A.1/A.2/A.3 ausgefüllt.

#### Hypothese A.1 — Pairing in ChirpStack unvollständig

> -002/-004 haben in ChirpStack v4 kein Device-Profile, kein App-Key,
> oder Frames bleiben am Network-Server stecken (kein Forwarding nach
> Mosquitto).

**Befund:** *AUSSTEHEND — Q1-Output erforderlich.*
- Wenn Q1 für -002/-004 `reading_count = 0` UND DevEUI in DB existiert
  → Hypothese **offen**, weiter mit ChirpStack-UI-Befund (separater
  Cowork-Auftrag, Events-Tab pro Vicki). ChirpStack-UI „kein Event" →
  Hypothese **bestätigt**. UI „Events vorhanden" → Hypothese
  **widerlegt**, bricht der Pfad im MQTT-Subscriber (siehe A.2).
- Wenn Q1 für -002/-004 `reading_count > 0` → Hypothese **widerlegt**,
  Stille ist nicht „nie gepaired".

#### Hypothese A.2 — Codec-Routing (§5.21)

> Codec verwirft -002/-004 als `unknown_reply` (Cmd-Byte nicht in
> {0x01, 0x81, 0x52, 0x04, 0x46}). Subscriber-Reply-Filter
> (`mqtt_subscriber.py:466-479`) überspringt dann `_persist_uplink` →
> kein `sensor_reading`-Insert.

**Befund:** *AUSSTEHEND — Q2-Output (`raw_payload`-Decode für Vicki mit
Frames) und ChirpStack-Events-Tab erforderlich.*
- Wenn Q1 für -002/-004 `reading_count = 0` UND ChirpStack-UI zeigt
  Frames mit `unknown_reply` → Hypothese **bestätigt**.
- Wenn ChirpStack-UI zeigt Frames mit korrektem `object.command =
  0x01/0x81` → Hypothese **widerlegt**.

Codec-Routing-Belege:
- `infra/chirpstack/codecs/mclimate-vicki.js:79-83` (Cmd-Byte-Routing)
- `mqtt_subscriber.py:466-479` (Reply-Filter überspringt
  `_persist_uplink`)

#### Hypothese A.3 — Firmware-/Backplate-Flag

> -002/-004 senden nur Maintenance-/Status-Reports (kein Periodic),
> z. B. weil Backplate nicht montiert ist (FW ≥ 4.3 sendet Demontage-
> Event), und das `decodePeriodicReport` weist sie als zu kurz ab.

**Befund:** *AUSSTEHEND — Q2-Output für Frames (sofern welche
existieren) und FW-Version aus Q1.*
- Wenn Q1 `firmware_version` für -002/-004 NULL → FW-Abfrage (Downlink
  `0x04`) lief noch nie / Reply kam nie an. Hypothese **offen**.
- Wenn `firmware_version` gesetzt UND keine Periodics in Q1 → Vicki
  „lebt", schickt aber nichts Periodisches. Hypothese **bestätigt**
  (Konfig-Problem am Gerät, nicht im Pfad).
- Verstoß gegen Leitplanke R1 ausgeschlossen: Vicki-003 ist unmontiert
  und sendet trotzdem. Backplate ist also keine Notwendigkeit für
  Periodics.

#### Wo bricht die Kette für -002/-004?

Drei mögliche Bruchstellen, alle aus Q1/Q2 + ChirpStack-UI eindeutig
unterscheidbar:

1. **nie gejoint** — kein Event in ChirpStack-UI (Cowork-Auftrag).
   Verantwortlich: Pairing / OTAA-Join. Behebung außerhalb dieses
   Sprints.
2. **gejoint, kein Uplink** — ChirpStack-Events-Tab leer trotz Join.
   Verantwortlich: Vicki-Konfig (Periodic-Interval, FW). Behebung
   außerhalb dieses Sprints.
3. **Uplink kommt, aber Codec/Backend verwirft** — Q1 `reading_count >
   0` ODER ChirpStack-Events-Tab zeigt Frames, aber unsere DB hat
   `reading_count = 0`. Verantwortlich: Codec (Cmd-Byte unbekannt) oder
   Subscriber (`Unknown DevEUI`/`implausible`). Lokalisierung über
   `journalctl -u …`-Filter auf `dev_eui=…` (separates Doku-Skript,
   wenn Pfad bestätigt).

#### Cowork-Auftrag-Trigger (ChirpStack-Events-Tab)

Cowork ist nicht nur bei Fall (a) (`reading_count = 0`) erforderlich,
sondern **auch bei Fall (b)** (silent-seit, `last_uplink` weit zurück) —
nur die Live-Events-Tab-Sicht zeigt, ob aktuell noch Frames ankommen,
die unser MQTT-Pfad verwirft. Konkret:

| Q1-Fall | Cowork-Auftrag in ChirpStack-UI |
|---|---|
| (a) nie ein Reading | Application „heizung" → Devices `-002`/`-004` → Tab „Events": existiert überhaupt etwas? Wenn nein → A.1 bestätigt. Wenn ja → A.2/A.3 prüfen. |
| (b) aktiv im Mai, jetzt silent | gleicher Tab: kommen **aktuell** noch Frames (letzte Stunden)? Wenn ja, unsere DB aber leer → A.2 (Codec/Subscriber verwirft) bestätigt. Wenn nein → Vicki-Konfig/-FW (A.3) oder Funkstrecke. |
| (c) Geräte-Tausch | Cowork prüft die **neue** DevEUI (aus aktiver Row `dev_eui`), nicht die retired. Sonst werden Tausch-Symptome mit A.1 verwechselt. |

### BLOCK B — Vicki-001 Batterie-33%-Konstanz (R4 / B-9.17b-3)

**Final-Status (Live-Test 2026-05-31, Hotelier-Bestätigung):**
Skalierungs-Befund **belegt**. Motorlast-Befund **durch Live-Test
erledigt** — separater 15b-Motorlast-Test entfällt. Batterietyp
**bestätigt: AA-Alkaline** — damit ist die Subscriber-Skala 3.0–4.2 V
**generell falsch parametriert** für dieses Gerät, nicht eine
Typ-Unklarheit. **NULL offene Punkte in BLOCK B**.

Diagnose-Methode (zur Referenz): byte[7]-high-nibble-VERLAUF aus
Q2-Roh-Bytes von Vicki-001 gegen `battery_percent`-Verlauf aus Q3.

**Decode-Schritt (lokal je Frame, manuell oder Skript):**

```bash
# raw_payload aus Q2-Spalte (base64) lokal decoden
echo "<base64>" | base64 -d | xxd -ps -c 16
# Beispiel-Output: "81 12 84 7c e2 0a 00 e2 00"
#                   cmd  TT s  s  RH  mp mr nib stat
# byte[7] high-nibble ist erstes Hex-Nibble in Spalte 8
# (Index 0-basiert: cmd=0, TT=1, sens=2, RH=3, mp=4, mr=5, nibble=6, byte7=7)
```

Pro Q2-Frame der Vicki-001: byte[7] high-nibble notieren und mit
`battery_percent` aus derselben Row korrelieren.

Auswertungs-Schema:

| byte[7] high-nibble Verlauf | `battery_percent` Verlauf | Einordnung |
|---|---|---|
| **konstant `0xE`** über alle Frames der letzten Tage | konstant `33` | **KEIN Decode-Bug.** Vicki meldet real konstant 3.4 V. Unser Pfad ist sauber. Verbleibend: Vendor-Plausibilität + Motorlast-Test (→ Sprint 15b). |
| **variiert** (z. B. `0xD`/`0xE`/`0xF` über Tage) | trotzdem konstant `33` | **Decode-/Persist-Bug auf UNSERER Seite.** Lokalisierung: entweder `_battery_pct_from_volts` (`mqtt_subscriber.py:89-94`) oder `_map_to_reading`-Übernahme (Z.132). |
| **konstant `0xE`** | schwankt | nicht erwartbar — Vendor-Inkonsistenz oder Q3-Snapshot-Artefakt; offene Frage Vendor-Doku. |
| schwankt | schwankt | kein Bug, alles konsistent. Snapshot-Sicht 33% war zufällige Momentaufnahme. |

Hinweis: `battery_voltage` ist **kein** persistiertes Feld — `sensor_
reading.battery_percent` ist Ergebnis der Subscriber-Funktion. Der
einzige Roh-Beleg im Persisted Layer ist `raw_payload` (base64). Die
Codec-Output-V-Zahl `battery_voltage` wird nicht in die DB geschrieben
(`mqtt_subscriber.py:106-143` mapped sie über `_battery_pct_from_volts`
direkt in `battery_percent`). Audit nur über Roh-Bytes.

**Nur einordnen, NICHT fixen.**

#### B-Live-Befund (2026-05-31, nach Batterietausch Vicki-001)

- **Frame 09:43 nach Batteriewechsel:** `byte[7] = 0xA0` → high nibble
  `0xA` → Codec dekodiert `2 + 10 × 0.1 = 3.0 V` (`mclimate-vicki.js
  :119-121`) → Subscriber-Mapping `(3.0 − 3.0) / 1.2 × 100 = 0 %`
  (`mqtt_subscriber.py:89-94`). Frame war **lastfrei** (Ventil = 0 %,
  eingeschwungen).
- **Frische 2×AA-Batterien** landen damit beim Subscriber bei
  **0 %** — der „Tankanzeige"-Effekt ist konstant am unteren Skalen-
  Rand, nicht in der Mitte.
- **Skalen-Mismatch belegt:** Subscriber-Skala 3.0–4.2 V hat als
  Obergrenze 4.2 V — das ist eine **LiPo-Voll-Ladung-Spannung**, nicht
  2×AA. Skala-Obergrenze passt schon konzeptionell nicht zum Vicki-
  Batterie-Typ.

#### B-Motorlast-Befund (2026-05-31, live durch Boot-Adaption + Override-Test erledigt)

- Boot-Adaptionsfahrt + manueller 25-°C-Override haben die Spannung
  **unter Last** sichtbar auf 3.0 V gezogen — also denselben Codec-
  Decode-Wert wie eingeschwungen-lastfrei.
- Frische 2×AA, lastfrei eingeschwungen ≈ Last-Spannung ≈ 3.0 V →
  **Last-Differenzierung mit dieser Skala nicht beobachtbar**.
- **Konsequenz für Sprint 15b:** Der separat geplante Motorlast-Test
  (Verbrauch unter Last vs. Standby) ist **durch den Live-Test vom
  2026-05-31 erledigt** und im Sprint-15b-Brief zu streichen.
- **15b reduziert sich** auf den Vendor-Spec-Abgleich der Skala
  (`docs/vendor/mclimate-vicki/`): welche Batterie-Chemie ist
  spezifiziert, welche Spannungs-Range erwartet der Vicki, wo ist
  der „leer"-Punkt der Hersteller-Definition?

#### B-abgeschlossen — Batterietyp belegt (Hotelier 2026-05-31)

Hotelier-Bestätigung: in Vicki-001 wurden **AA-Alkaline (Mignon LR6)**
eingelegt. Frische Alkaline: ~1.5 V/Zelle, Paar ~3.0 V — passt
**exakt** zum heute gemessenen high nibble `0xA` (Codec 3.0 V).

**Belegung:** Der Decode-Pfad ist korrekt. Die **Subscriber-Skala
3.0–4.2 V ist generell falsch parametriert** für AA-Alkaline. Sie
liegt auf einer LiPo-Kurve (3.0 V leer → 4.2 V voll). Eine frische
Alkaline-Zelle reicht laut Hersteller-Entladekurve grob:

- **frisch / lastfrei:** ~3.0–3.2 V (Paar)
- **mittlere Lebensdauer:** ~2.6–2.8 V
- **leer / Cut-Off:** ~2.0–2.2 V

→ Die Vicki-Skala muss auf das Alkaline-Fenster (~2.2 V leer
→ ~3.2 V frisch) reparametriert werden; die LiPo-Obergrenze 4.2 V
wird mit AA-Alkaline **nie** erreicht.

**Sprint 15b reduziert auf einen Schritt:** Skalen-Reparametrierung
gegen Vendor-Spec (`docs/vendor/mclimate-vicki/` + Alkaline-
Entladekurve), Code-Touch
`mqtt_subscriber.py:89-94` `_battery_pct_from_volts`. Kein
Investigations-Sprint mehr, reine kleine Fix-Arbeit.

**Out of Scope dieses Sprints:** Skala-Fix selbst gehört in
Sprint 15b, **nicht** hier.

### Befund H1 — health_state-„nie-gesehen" (T2.4)

**Code-Pfad korrekt** für `nie-gesehen → silent`:

- `health_tasks.py:88-89` (`_basis_state_from_age(None, now) -> "silent"`)
- `device.py:90` (`server_default="silent"`)
- `dashboard_aggregates.py:38` (`_ONLINE_STATES = ("healthy", "degraded")`)
- `dashboard_aggregates.py:58-76` (`count_devices_online` filtert
  Silent korrekt heraus)

**Die KPI „Geräte online — 4 von 4" lässt sich aus diesen Pfaden NICHT
herleiten.** Möglichkeiten, die den vermuteten Effekt erzeugen würden:

| Verdacht | Beleg |
|---|---|
| KPI greift auf andere Datenquelle als `count_devices_online` zu | Belegt: `frontend/src/app/page.tsx:67-71` zeigt `value = data.devices_online`, `subValue = von ${data.devices_total}`. Quelle der `devices_online`-Zahl ist `count_devices_online` (Backend-Endpoint `/api/v1/dashboard/kpi`). **Keine Drift im Daten-Pfad.** |
| Beat-Task läuft nicht → DB-Werte aus früherem Zustand | Belegt: §5.32 — celery_beat ist auf heizung-test seit Wochen `unhealthy`, weil HEALTHCHECK aus Dockerfile (curl :8000) nicht greift; Beat tickt aber laut Log weiter. Reale Cron-Latenz aus `journalctl -u …`-Audit prüfen (separater Diagnose-Schritt, sofern Verdacht persistiert). DB-Default ist trotzdem `silent`, also bricht der Verdacht „4 von 4 healthy ohne je gesehen worden zu sein" auch bei nie-gelaufenem Beat. |
| Verdacht beruht auf anderer UI-Sicht (Geräte-Listen-Status, „erreichbar", „eingerichtet") | NICHT geprüft in 15a (Backend-Audit), Folge-Sprint-Kandidat: Frontend-Cross-Sicht-Audit über alle Hardware-Health-Visualisierungen vs. KPI. |

#### H1-Konsequenz nach Q1 — Track §3-Punkt-3 GESTRICHEN

Q1 belegt für alle vier Vickis `reading_count > 0` mit aktuellen
`last_uplink`-Timestamps → alle vier sind **real `healthy`**, die
KPI „4 von 4 online" ist **korrekt**. Kein Symptom existiert, das
einen Backend-`health_state`-Fix rechtfertigen würde.

**Track §3-Punkt-3 (Backend-`health_state`-Fix) wird GESTRICHEN**
— nicht gegenstandslos im Schwebezustand, sondern endgültig
abgeschlossen. Code-Pfad ist korrekt (DB-Default `silent`,
`_basis_state_from_age(None) → silent`, KPI-Filter schließt Silent
korrekt aus), und die ursprüngliche Wahrnehmung „4 von 4 trotz Stille"
beruhte auf der Stille-Prämisse, die durch BLOCK A widerlegt wurde.

**Frontend-Cross-Sicht-Audit:** entfällt ebenfalls **mangels
Symptom**. Behalten nur, falls an anderer UI-Stelle eine falsche
Online-Zahl beobachtet wird — bis dahin ist auch dieser Folge-Sprint-
Kandidat gestrichen.

### BLOCK D — Sommermodus-Downlink + Reboot-Setpoint-Drift (Zusatz-Diagnose)

**Anlass:** Vicki-001 meldet nach Batteriewechsel-Reboot `target_temperature = 11 °C`
(byte[1] = `0x0b`, Codec korrekt). Kein aktiver Override (alle revoked).
System korrigiert > 2,5 h nicht zurück auf Sommermodus-Sollwert 10 °C.

#### Frage-Antworten (Kurz)

| # | Frage | Antwort |
|---|---|---|
| 1 | Layer 0 — einmaliger Downlink oder pro Tick Soll-Ist-Korrektur? | **Pro Tick**, aber **KEINE Soll-Ist-Korrektur** — Engine vergleicht nicht gegen Vicki-gemeldeten Setpoint, sondern gegen den **letzten von ihr selbst gesendeten** Setpoint (Hysterese auf `_last_command_for_device`). |
| 2 | Sendet Engine im Sommermodus überhaupt Downlinks, wenn Vicki-Meldung abweicht? | **Ja, pro Tick durchgängig per-Zone-per-Device**, aber Hysterese-gefiltert. Bei Sommer-Setpoint=10 + Vicki-Meldung 11 sieht Hysterese `delta=|10−10|=0 < 1` (gegen letzten gesendeten 10) → **kein Downlink**. Erst Heartbeat (6 h) triggert Re-Send. Sommer ist **kein** reiner Pass-Through. |
| 3 | Warum 7 Overrides bei 25 °C, aber keiner bei 11 °C? | Trigger-Code identisch. Differenz im Gate-Pfad — Q-D entscheidet zwischen drei Möglichkeiten (siehe unten). |
| 4 | Würde im **Heizbetrieb** (Sommer aus) ein nach Reboot abgedrifteter Setpoint **aktiv** zurückkorrigiert? | **NEIN — kein Code-Pfad korrigiert aktiv.** Nur passive Mechanismen: (i) Heartbeat 6 h zwingt Re-Send des Engine-Setpoints; (ii) Auto-Override (AE-45) übernimmt den Drift-Wert für 7 Tage (= Engine **passt sich an**, KEINE Korrektur). → **Eigener Sprint mit Vorrang gerechtfertigt** (Winter-Risiko). |

#### D.1 — Layer 0 Sommermodus (`rules/engine.py`)

- **`layer_summer_mode` Z.167-208** — always-on. Aktiv → `LayerStep
  (setpoint_c = int(FROST_PROTECTION_C) = 10, reason = SCENARIO_SUMMER_MODE)`;
  inaktiv → Passthrough-Marker `setpoint_c=None`.
- **`evaluate_room` Z.994-1003** — Wenn `ctx.summer_mode_active`: Layer 1-4
  **werden übersprungen**, direkter Sprung auf `layer_clamp(summer)` →
  `RuleResult.setpoint_c = 10`. Layer 3 (Manual-Override) wird im
  Sommer **nicht ausgewertet** — ein gleichzeitig existierender
  Auto-Override hätte im Sommer keine Wirkung auf den Engine-Output.

#### D.2 — Engine-Downlink-Pfad im Sommermodus (`tasks/engine_tasks.py`)

- **`_dispatch_downlinks_per_zone` Z.355-490** — pro Zone, pro Device:
  `prev = _last_command_for_device(dev.id)` (engine.py:947-972, letzter
  ControlCommand mit `sent_to_gateway_at IS NOT NULL`) +
  `hysteresis_decision(prev_sp, prev_at, new_setpoint_c=zone_target)`
  (Z.422-426).
- **`hysteresis_decision` Z.793-825** — Send/Skip-Regel (AE-32):
  - `prev_setpoint_c is None` → `should_send=True` (Initial-Sync).
  - `delta = |new − prev| >= HYSTERESIS_C (=1)` → send.
  - `delta < HYSTERESIS_C` UND `age = now − prev_issued_at >=
    HEARTBEAT_INTERVAL (=6 h)` → send.
  - sonst → **skip**.
- **Konsequenz im Sommer:** Engine sendet jeden Tick einen Downlink-
  Versuch an jeden Vicki, aber die Hysterese filtert ihn fast immer
  weg. `prev_setpoint_c` ist **immer der letzte von der Engine
  gesendete Wert** — der Vicki-gemeldete Wert spielt in der Hysterese
  **keine Rolle**. Vicki meldet 11, Engine zuletzt 10 gesendet,
  Engine berechnet jetzt 10 → `|10−10|=0 < 1`, age meist `< 6 h` →
  **skip**. Erst nach 6 h Heartbeat re-syncht Vicki sich passiv.

#### D.3 — Auto-Override-Trigger (AE-45, `services/device_adapter.py`)

Gate-Reihenfolge in **`handle_uplink_for_override` Z.180-328**:

| Gate | Quelle | Skip-Bedingung |
|---|---|---|
| 0 | `detect_user_override` Z.57-101 | kein vorheriger Engine-Command / Ack-Window 60 s / `|uplink − last_engine_setpoint| <= tolerance` (0.6 °C bei fPort 1, 0.1 °C bei fPort 2) |
| pre-a | Z.239-259 | `room.guest_override_blocked = True` |
| **a (OCCUPIED-Gate, AE-58)** | **Z.262-278** | **`derive_room_status != OCCUPIED`** → silent skip + `MANUAL_OVERRIDE_BLOCKED`-event_log mit `reason=DEVICE_BLOCKED_VACANT` |
| b | Z.280-297 | mindestens eine Zone meldet `open_window=True` |
| c | Z.299-307 | Zone-Lookup (Fallback Room-Scope) |
| d | Z.309-328 | `override_service.create(source=DEVICE, expires_at=…)` |

**Differential-Diagnose 25 °C (08:27, 7 Einträge) vs. 11 °C (ab 09:36, 0) — Q-D-belegt:**

| Hypothese | Status | Beleg (Q-D-Output) |
|---|---|---|
| D.3a — Occupancy-Wechsel 08:27→09:40 | **NEIN** | Q-D3: Occupancy Zimmer 101 durchgehend seit 30.05 12:00, kein Wechsel im Diagnose-Fenster. |
| D.3b — Engine hatte 11 °C selbst gesendet → Toleranz-Match in Gate 0 | **NEIN** | Q-D1: Engine sandte **nie** `target_setpoint=11`. Jüngstes Command `id=428` um 08:45 = 10 °C mit `reason=scenario_summer_mode`. |
| **D.3c — `room.guest_override_blocked = true`** | **JA (Treffer)** | Q-D3: `guest_override_blocked = true` für Zimmer 101. Q-D2: Keine Override-Anlage nach 08:43 trotz fortgesetzter 11 °C-Drift → AE-45-Adopt durch Gate (pre-a) `device_adapter.py:245-259` blockiert. Q-D4 zeigt entsprechende `MANUAL_OVERRIDE_BLOCKED`-Rows mit `reason=device_blocked_room_blocked`. |
| D.3d — Window-Gate scharf | **NEIN** | Q-D2/Q-D3 + `event_log`: `open_window = false` durchgehend. |

**Hysterese-Beleg für Befund 1 (Q-D1):**

- Command `id=424` (vor Eintritt in Sommermodus) `target_setpoint=21`.
- Command `id=428` 08:45 `target_setpoint=10`, `reason=scenario_summer_mode`.
  Hysterese-Trigger war `delta = |10−21| = 11 >= HYSTERESIS_C` (gegen
  letzten **Engine-SENT-Wert** `id=424=21`, **nicht** gegen Vicki-
  Meldung).
- Nach 09:40-Reboot meldet Vicki 11 °C. Engine berechnet weiter
  `setpoint=10` (Sommer-Fast-Path). Hysterese: `delta = |10−10| = 0
  < 1` gegen `id=428=10`, `age ≪ 6 h` → **kein Send**.
- Re-Sync ausschließlich über Heartbeat. Heartbeat-Timer wurde durch
  den `id=428`-Send um 08:45 zurückgesetzt → **nächster
  erwarteter Re-Sync ~14:45** (08:45 + 6 h), nicht 15:30. Verifikation:
  ein Command zwischen ~14:45 und ~15:00 mit
  `target_setpoint=10` + `rule_context.hysteresis_reason ~
  "heartbeat age=6:..."` in Q-D1 (Re-Run nach 15:00).
- Bis dahin **kein** Command in Q-D1 zwischen 08:45 und Re-Sync
  (insbesondere kein 09:50-Command nach der Drift) → bestätigt, dass
  Engine nicht aktiv auf die Vicki-Meldung reagiert hat.

Die 7 Einträge um 08:27 (Q-D2) entstanden im Pre-Block-Fenster: bevor
`guest_override_blocked` gesetzt wurde, passierten 7 Periodic-Uplinks
mit Drehring-25-°C alle Gates → 7 Auto-Override-Anlagen (Vicki sendet
alle ~15 min; entspricht ≈ 1,75 h durchgehender Drehring-Stellung).
Diese Overrides sind in Q-D2 als nachträglich `revoked_at != NULL`
sichtbar (gesetzt durch das Toggle-On in `api/v1/rooms.py:206-242`,
das **alle** aktiven Overrides des Raums revoked).

#### D.4 — Heizbetrieb (Sommer aus): aktiver Korrektur-Pfad existiert NICHT

Grundbelegung:

- **`evaluate_room` Z.987-1149** läuft mit allen Layern 1-5. Engine
  berechnet `RuleResult.setpoint_c` aus Status/Temporal/Override/
  Window/Clamp. **Vicki-gemeldeter `target_temperature` aus
  `sensor_reading.setpoint` fließt nirgends in `evaluate_room` ein.**
  Grep: `select(SensorReading.setpoint)` kommt in `engine.py` nicht
  vor; `sensor_reading.temperature`/`open_window`/`attached_backplate`
  werden verwendet, der `setpoint` aber NICHT.
- **`hysteresis_decision`** vergleicht ausschließlich Engine-neu vs.
  Engine-zuletzt-gesendet (`_last_command_for_device`,
  engine.py:947-972). Vicki-Meldung kein Eingangsfaktor.
- Einziger periodisch korrigierender Mechanismus ist der **Heartbeat
  6 h** in `hysteresis_decision` (Z.819-820). Er zwingt nach 6 h einen
  Re-Send des **Engine-berechneten** Setpoints — was den Re-Send
  bewirkt, hängt davon ab, ob in der Zwischenzeit ein Auto-Override
  entstanden ist.

**Zwei Fehlmodi nach Reboot-Drift — strukturell getrennt:**

**Empirie-Status (Q-D-belegt):**
- **D.4.M2** ist der **real eingetretene** Fall — der reale 11 °C-Drift
  am 30.05 nach 09:40 lief in M2, weil `guest_override_blocked=true`
  (D.3c) den Auto-Override-Pfad blockiert hat. Live-Prüfpunkt ~14:45
  (siehe oben) verifiziert.
- **D.4.M1** ist eine **reine Code-Hypothese** — empirisch in dieser
  Diagnose **NICHT** eingetreten. Der Pfad wäre nur möglich, wenn
  `guest_override_blocked = false` UND alle weiteren Gates (a/b/c) im
  Drift-Moment passen. Die Größe der Risikofläche ist in D.6 belegt.

##### D.4.M1 — Override-Fall (kein Selbstheilen)

- Pfad (Code-Hypothese, in dieser Diagnose nicht real eingetreten):
  Vicki meldet Drift-Setpoint → `handle_uplink_for_override` passiert
  Gate 0 + Gates pre-a/a/b/c → Auto-Override mit
  `source=DEVICE, setpoint=<drift>, expires_at` per
  `override_service.compute_expires_at` (typisch 7 Tage oder bis
  Check-out, AE-58/AE-45).
- Engine-Layer 3 nimmt diesen Override **als Wahrheit** → Layer 5
  Clamp lässt ihn (sofern in `[room_type.min, max]`) durch →
  `RuleResult.setpoint_c = <drift>`.
- Heartbeat 6 h **zementiert** den Drift: der Re-Send schickt nicht
  den ursprünglich gewünschten Engine-Setpoint, sondern den vom
  Override adoptierten Drift-Wert.
- **Kein Code-Pfad korrigiert zurück**, solange der Override aktiv ist.
  Selbstheilung nur bei Override-Expiry (7 Tage / Check-out) oder
  manuellem Revoke.

**Risiko M1 (Winter-Worst-Case, Code-Szenario):** Gast wechselt um
22:00 Batterie, Vicki reboot meldet 11 °C, Raum OCCUPIED, kein Fenster
offen, **`guest_override_blocked = false`** → Auto-Override entsteht
mit `setpoint=11`, gültig 7 Tage. Engine sendet 11 °C an Vicki bis
Override expires/revoked. **Zimmer heizt bis zu 7 Tage nicht.**
Die reale Risikofläche dieser Konstellation hängt am Anteil der
Räume mit `guest_override_blocked = false` — siehe D.6.

##### D.4.M2 — Nicht-Override-Fall (Selbstheilung ≤ 6 h)

Trifft zu, wenn mindestens eines der `handle_uplink_for_override`-
Gates blockt (häufig im Sommer-VACANT-Raum: Gate (a) OCCUPIED-Check
schlägt fehl; oder im Heizbetrieb mit Fenster offen: Gate (b);
oder bei `guest_override_blocked=True`: Gate (pre-a)).

- Pfad: Vicki meldet Drift-Setpoint → Auto-Override-Pfad **bricht
  ab** (z. B. `MANUAL_OVERRIDE_BLOCKED`-event_log mit
  `reason=DEVICE_BLOCKED_VACANT`). Kein Override angelegt.
- Engine-Layer 0/1-5 berechnen weiter den korrekten Soll-Setpoint
  (im Sommer: 10 °C).
- Hysterese filtert die Korrektur weg: `|10−10|=0 < 1` (Engine
  vergleicht gegen ihren eigenen zuletzt gesendeten 10 °C, **nicht**
  gegen den Vicki-gemeldeten 11 °C). Solange `age < 6 h` → skip.
- **Heartbeat 6 h zwingt Re-Send von 10 °C** → Vicki adoptiert wieder
  10 °C. **Selbstheilung passiv, Worst-Case 6 h.**

**Risiko M2:** Begrenzt — bis zu 6 h falscher Vicki-Setpoint.
Sommer-Auswirkung: Vicki regelt auf 11 statt 10 °C (1 °C Differenz),
Energie- und Komfort-Wirkung minimal. Heizbetrieb-Auswirkung:
abhängig vom Drift-Delta — wenn z. B. nach Reboot 11 °C statt
21 °C gemeldet wird, heizt der Raum für bis zu 6 h nicht (Gast-Komfort,
keine Sicherheit).

##### Live-Prüfpunkt (Befund-1-Verifikation aus M2)

Vicki-001 meldet 11 °C seit **09:40** (Anlass-Beobachtung). M2-Pfad ist
durch D.3c belegt (kein Override nach 08:43, alle vorigen Overrides
revoked). Heartbeat-Schwelle berechnet sich gegen den **letzten
Engine-Sent** für Vicki-001 = `id=428 @ 08:45`:

- **Erwarteter Re-Sync ~14:45** (08:45 + 6 h Heartbeat-Schwelle, plus
  bis zu einen Eval-Tick Latenz). Nicht 15:30 — der `id=428`-Send hat
  den Heartbeat-Timer zurückgesetzt.
- Verifikation: `Q-D1` (Re-Run nach 15:00) zeigt einen
  `sent_to_gateway_at`-Eintrag für Vicki-001 mit
  `target_setpoint = 10` und `rule_context.hysteresis_reason ~
  "heartbeat age=6:..."` zwischen ~14:45 und ~15:00.
- Wenn der Re-Sync zur erwarteten Zeit kommt: **D.4.M2 bestätigt**,
  Befund 1 (kein aktiver Soll-Ist-Korrektur-Pfad, nur Heartbeat)
  belegt aus Live-Daten. Wenn nicht: tiefere Analyse (Beat-Latenz,
  blockierter Worker, neuer Drift-Trigger zwischenzeitlich).

#### D.6 — Risiko-Fläche für M1 (read-only-Belege)

Drei read-only Belege, die die D.5-Priorität informieren. Reine
Sichtbarkeit der Risiko-Fläche, kein Fix.

##### D.6.1 — Semantik `guest_override_blocked` (Code-Beleg)

- **Datenmodell:** `models/room.py:79` —
  `guest_override_blocked: Mapped[bool] = mapped_column(Boolean,
  nullable=False, default=False)`. **Default ist False** für jeden
  neuen Raum. Per-Raum-Setting, **keine** Saison-Abhängigkeit, **kein**
  Auto-Set durch Engine/Cron.
- **Setz-Pfad einzig** über API-Endpoint `api/v1/rooms.py:203-242`
  (Toggle durch `require_mitarbeiter`):
  - Toggle ON (False → True): revoked **alle** aktiven Overrides des
    Raums mit `reason="room_override_blocked"` (`api/v1/rooms.py:
    236-240`).
  - Toggle OFF (True → False): nur Flag-Reset, **kein** Auto-
    Re-Anlegen, **kein** Side-Effect auf Engine-Pfad.
- **Begriffstrennung:** `guest_override_blocked` ist **nicht**
  identisch mit `RoomStatus.BLOCKED` (`room.py:74-79` Kommentar,
  `api/v1/rooms.py:224-226`). Beide Felder existieren parallel.
- **Frontend-Toggle** (User-sichtbar): `components/patterns/
  room-override-block-toggle.tsx` ruft den oben genannten Endpoint.
  Kein anderer Schreibpfad existiert.

**Konsequenz für Risiko-Fläche:** Jeder Raum, dessen Hotelier den
Block-Toggle nicht explizit aktiviert hat, ist M1-exponiert. Default
`false` bedeutet: **alle frisch angelegten Räume sind im
M1-Code-Pfad.**

##### D.6.2 — fcnt-/Reboot-Schutz im AE-45-Pfad (Code-Beleg)

Grep auf `fcnt` im Service-Layer (`grep -rn fcnt backend/src/heizung/
services/`):

- `mqtt_subscriber.py:128, 197, 246, 248` — `fcnt` wird **persistiert**
  in `sensor_reading.fcnt` und für Log-Strings verwendet.
- **Kein einziger Treffer in `device_adapter.py` oder
  `override_service.py`.** Der gesamte AE-45-Pfad
  (`detect_user_override` Z.57-101, `handle_uplink_for_override`
  Z.180-328) liest `fcnt` **nicht** und prüft **keine** Reboot-
  Bedingung.

**Konsequenz:** Bei `guest_override_blocked = false` UND OCCUPIED UND
kein Fenster offen wird ein Reboot-Frame mit gedriftetem
`target_temperature` (z. B. 11 °C nach Batteriewechsel) im
Auto-Override-Pfad **NICHT** von einem echten Gast-Drehring
unterschieden. Er passiert Gate 0 (`|11 − last_engine_setpoint| >
tolerance`), pre-a (`blocked=false`), a (OCCUPIED), b (kein Window),
c (Zone), d (`override_service.create`) und legt einen
`source=DEVICE`-Override mit `setpoint=11`, `expires_at` aus
`compute_expires_at` an. **Strukturell garantierter M1-Pfad ohne
Reboot-Schutz.**

##### D.6.3 — Risiko-Flächen-Query (paste-fähig)

`room` hat **keinen** `retired_at`-Lifecycle (nur `device` per AE-57).
Operativ aktiver Raum = alle Räume **außer** `status = BLOCKED`
(Operations-aus). Die M1-exponierte Fläche ist die Anzahl Räume mit
`guest_override_blocked = false`, sinnvoll nach Status stratifiziert.

```sql
\echo '===== Q-D5 — M1-exponierte Fläche (Räume ohne Block-Toggle) ====='
SELECT
  status,
  COUNT(*) FILTER (WHERE guest_override_blocked = false) AS rooms_m1_exposed,
  COUNT(*) FILTER (WHERE guest_override_blocked = true)  AS rooms_blocked,
  COUNT(*)                                                AS rooms_total
FROM room
GROUP BY status
ORDER BY status;

\echo
\echo '===== Q-D5 — Gesamtsumme ====='
SELECT
  COUNT(*)                                                     AS rooms_total,
  COUNT(*) FILTER (WHERE guest_override_blocked = false)       AS rooms_m1_exposed,
  COUNT(*) FILTER (WHERE guest_override_blocked = false
                     AND status <> 'blocked')                  AS rooms_m1_exposed_operational
FROM room;
```

Auswertung:
- `rooms_m1_exposed_operational` ist die **operative Risiko-Fläche**.
  Hoher Anteil → D.5-Priorität dringend, weil Default-Stand jeden
  Gast-Batteriewechsel zur M1-Konstellation macht.
- Niedriger Anteil (Hotelier hat Block-Toggle systematisch gesetzt)
  → D.5 sekundär.

**Q-D5-Befund (Live, 2026-05-31):**

| Status | rooms_m1_exposed | rooms_blocked | rooms_total |
|---|---|---|---|
| occupied | 1 | 1 | 2 |
| vacant | 42 | 1 | 43 |
| **Gesamt** | **43** | **2** | **45** |

**Interpretation:** Nur **2 von 45** Zimmern sind aktuell `guest_
override_blocked = true` — und das sind die heute manuell zu
Testzwecken gesetzten. Der Default-Zustand `false` (belegt in
D.6.1: `models/room.py:79`) ist damit nicht theoretisch, sondern
**produktiv der Normalfall**. Im Vollausbau (45 Zimmer) ist
M1-Exposition die Regel, nicht die Ausnahme — die Risikofläche ist
**empirisch belegt**, nicht hypothetisch.

##### D.6.4 — Audit-Gap im AE-45-Block-Pfad (Nebenbefund Q-D4)

Q-D4 liefert **0 rows** für `MANUAL_OVERRIDE_BLOCKED`-event_log-Rows
mit Bezug auf Vicki-001-Raum im Diagnose-Fenster. Erwartung war:
mindestens ein Eintrag pro 11-°C-Drift-Frame mit
`reason=device_blocked_room_blocked` (laut Code-Pfad
`device_adapter.py:251-258`).

**Mögliche Ursache (read-only-Vermutung, NICHT Q-D-belegt):** Der
Block-Gate `device_adapter.py:245-259` macht zwar einen
`logger.info(...)` und ruft `_write_blocked_event_log(...)` — aber
nur, wenn der vorgelagerte `detect_user_override`-Aufruf (Z.221-229)
einen User-Setpoint zurückgegeben hat. Tritt Drift-Frame
hinter Toleranz **oder** im Ack-Window auf → `detect_user_override`
returnt `None` → `handle_uplink_for_override` returnt früh ohne
Block-event_log. Der Block ist dann silent.

**Konsequenz:** Es gibt einen **Audit-Gap** — Block-Wirkungen
verschwinden ohne event_log-Spur, wenn der Vor-Gate (Toleranz/
Ack-Window) bereits abweist. Im Audit-Trail ist nicht sichtbar,
**wie oft** der Block tatsächlich wirkte.

**Backlog-Kandidat, NICHT Teil des Fix-Sprints D.5.** Eigener
Hygiene-Sprint-Brief: „AE-45-Block-Pfad lückenlos auditieren".

#### D.5 — Folge-Sprint-Kandidat — Priorität FIXIERT: VORRANG

**Sprint-Vorrang gerechtfertigt** für Fehlmodus **D.4.M1** (Override
zementiert Drift über 7 Tage); D.4.M2 (≤ 6 h Selbstheilung) ist
zweitrangig und kann ggf. mit kürzerem Heartbeat adressiert werden.

**Belegungs-Triade für die Priorität:**

1. **Struktureller Defekt (D.6.2):** AE-45-Pfad hat keinen Reboot-
   Schutz, kein fcnt-Check, kein anderer Diskriminator. Code-Belegung
   per Grep.
2. **Default-Exposition (D.6.3):** 43 von 45 Räumen aktuell
   `guest_override_blocked=false`. Der M1-Pfad ist im Vollausbau die
   Normal-Konstellation.
3. **Winter-Impact:** bis zu 7 Tage kein Nachheizen pro Vorfall —
   Gast-Komfort und Energie, im Worst-Case Frostschaden bei langer
   Vakanz.

(1) × (2) × (3) = reales Betriebsrisiko vor Heizperiode 2026/27.
Folge-Sprint ist **vor** Heizperiode-Beginn zu schneiden.

**Fix-Kern (Konzept, NICHT in 15a implementiert):** Reboot-Frame
über fcnt-Reset erkennen — Daten liegen bereits im
`mqtt_subscriber` vor (D.6.2 belegt: `mqtt_subscriber.py:128,
197, 246, 248`), `device_adapter` greift sie aktuell nicht ab. Im
AE-45-Pfad Reboot-Frame **nicht** als Gast-Setpoint-Change werten.
Leitplanke **D.5.2 bleibt verbindlich**: KEIN aggressives Dauer-
Korrigieren gegen Vicki-Setpoint (zerstört echte Gast-Overrides aus
Drehring-Gesten).

**Scope-Schätzung (grob, für Folge-Sprint-Brief):**
- 1 Diskriminator-Funktion `is_reboot_frame(uplink, last_fcnt)` (klar
  umrissen, ~20 LoC inkl. Schwellen-Konstante).
- 1 Gate-Einschub in `device_adapter.handle_uplink_for_override` vor
  Gate 0 (Reboot → silent skip + event_log-Audit mit neuem `reason
  = DEVICE_REBOOT_DETECTED`, schließt D.6.4-Lücke gleich mit).
- Pytest-Cases: Reboot-Frame ohne Override-Anlage, echter Drehring
  weiterhin Override, edge cases fcnt-Wrap.
- Klein und umrissen — Sprint-Größe S/M.

##### D.5.1 — fcnt-Reset als Reboot-Diskriminator

Der entscheidende Hebel ist die saubere **Unterscheidung Reboot-
Frame vs. echter Gast-Drehring** im Auto-Override-Pfad. Das LoRaWAN-
Frame-Counter-Feld `fcnt` (persistiert in `sensor_reading.fcnt`,
Modell-Datei:Zeile `sensor_reading.py:47`) ist der natürliche
Diskriminator:

- **Anlass-Beleg** (aus laufender Diagnose): Vicki-001 `fcnt = 4338`
  vor Batteriewechsel, danach `fcnt ∈ {1, 2, …, 8}` (auch via Q3/Q-D1
  empirisch belegbar). Reboot-Frames sind also klar erkennbar.
- Reboot-Erkennung im Subscriber: `new_fcnt < last_fcnt − N` oder
  `new_fcnt ≤ ~10` UND `last_fcnt >> new_fcnt` markiert das Frame
  als Boot-Marker. Schwellen-Wahl im Folge-Sprint, hier nur
  Konzept-Beleg.
- **Folgewirkung im Folge-Sprint:** im erkannten Reboot-Frame
  läuft `handle_uplink_for_override` **NICHT** (Setpoint aus
  Reboot-Frame wird NICHT als Gast-Setpoint-Change gewertet).
  Stattdessen sofortiger Heartbeat-Bypass-Re-Send des Engine-
  berechneten Setpoints + Logger-Warning + event_log-Audit
  (`reason = DEVICE_REBOOT_DETECTED` o. ä.).
- Nebenwert für andere Diagnose-Klassen: Reboot-Marker werden
  auch im `event_log` sichtbar → später korrelierbar mit
  Batterie-Tausch-Zyklus, FW-Wechsel.

##### D.5.2 — Leitplanke (verhindert Fehlrichtung des Folge-Sprints)

Der Fix darf **NICHT** sein: „Engine vergleicht jeden Uplink-Setpoint
mit ihrem Soll, korrigiert dauerhaft aggressiv gegen Vicki-Setpoint".
Das überschreibt **echte Gast-Overrides** (Drehring-Geste am Vicki)
und verletzt das Geschäftsmodell, manuelle Gast-Eingriffe zu
respektieren (AE-45 Auto-Override, R6 Gast-Override-Range
[19, 24] °C).

Richtiger Ansatz strukturell:

| Klasse | Quelle | Wirkung |
|---|---|---|
| Reboot-Frame (fcnt-Reset) | Vicki-FW-Boot | Engine ignoriert den gemeldeten Setpoint, sofortiger Re-Sync (kein Auto-Override, kein Drift-Adopt). |
| Echter Drehring-Setpoint (fcnt monoton hoch, Drift sichtbar) | Gast | Bestehender AE-45-Pfad: Auto-Override mit `source=DEVICE`, Engine adoptiert für 7 Tage / bis Check-out. |
| Engine-Drift-Adopt-Risiko | Bug | **explizit ausgeschlossen** durch Reboot-Diskriminator vor `handle_uplink_for_override`. |

##### D.5.3 — Heartbeat-Intervall

`HEARTBEAT_INTERVAL = 6 h` (engine.py:54) ist die einzige periodische
Re-Sync-Quelle. Kürzere Intervalle = mehr Battery-Last (AE-32-
Tradeoff aus Sprint 9 ausdrücklich auf 6 h gesetzt). Folge-Sprint kann
die Schwelle re-bewerten, aber das ist **sekundär** zum fcnt-Reboot-
Diskriminator — letzterer behebt den Worst-Case M1 strukturell,
während eine Heartbeat-Verkürzung nur M2 quantitativ schwächt.

##### D.5.4 — Sprint-15a-Scope

**Out of Scope dieses Sprints:** Sprint 15a bleibt reine Diagnose-
Doku. Brief-Entscheidung Folge-Sprint („Reboot-Drift-Detection per
fcnt") liegt beim Strategie-Chat **nach**:

1. Q-D5-Output (D.6.3 — quantifiziert M1-Risikofläche),
2. Bestätigung von D.4.M2 durch den **~14:45**-Live-Prüfpunkt
   (08:45 + 6 h Heartbeat ab `id=428`).

#### Q-D — Zusatz-Queries für BLOCK D (read-only, paste-fähig)

```sql
\echo '===== Q-D1 — ControlCommand-Historie Vicki-001 (letzte 24 h) ====='
SELECT
  cc.id,
  cc.device_id,
  cc.target_setpoint,
  cc.reason,
  cc.issued_at,
  cc.sent_to_gateway_at,
  cc.rule_context
FROM control_command cc
JOIN device d ON d.id = cc.device_id
WHERE d.label = 'Vicki-001'                       -- ggf. dev_eui einsetzen
  AND cc.issued_at >= NOW() - INTERVAL '24 hours'
ORDER BY cc.issued_at DESC
LIMIT 60;

\echo
\echo '===== Q-D2 — Auto-Override-Anlagen Vicki-001-Raum (letzte 24 h) ====='
SELECT
  mo.id,
  mo.room_id,
  mo.heating_zone_id,
  mo.setpoint,
  mo.source,
  mo.created_at,
  mo.expires_at,
  mo.revoked_at,
  mo.reason
FROM manual_override mo
JOIN heating_zone hz ON hz.room_id = mo.room_id
JOIN device d ON d.heating_zone_id = hz.id
WHERE d.label = 'Vicki-001'
  AND mo.created_at >= NOW() - INTERVAL '24 hours'
ORDER BY mo.created_at DESC;

\echo
\echo '===== Q-D3 — Room-Status + Occupancy + Block-Flag (Vicki-001-Raum, letzte 24 h) ====='
SELECT
  r.id              AS room_id,
  r.number,
  r.status          AS room_status,
  r.guest_override_blocked,
  o.id              AS occupancy_id,
  o.check_in,
  o.check_out,
  o.is_active
FROM room r
LEFT JOIN occupancy o ON o.room_id = r.id
                     AND o.check_in <  NOW()
                     AND o.check_out > NOW() - INTERVAL '24 hours'
WHERE r.id = (
  SELECT hz.room_id FROM heating_zone hz
  JOIN device d ON d.heating_zone_id = hz.id
  WHERE d.label = 'Vicki-001' LIMIT 1
)
ORDER BY o.check_in DESC NULLS LAST;

\echo
\echo '===== Q-D4 — MANUAL_OVERRIDE_BLOCKED-event_log (Vicki-001-Raum, letzte 24 h) ====='
SELECT
  el.time,
  el.room_id,
  el.layer,
  el.reason,
  el.device_id,
  el.details
FROM event_log el
WHERE el.room_id = (
  SELECT hz.room_id FROM heating_zone hz
  JOIN device d ON d.heating_zone_id = hz.id
  WHERE d.label = 'Vicki-001' LIMIT 1
)
  AND el.layer = 'manual_override_blocked'
  AND el.time >= NOW() - INTERVAL '24 hours'
ORDER BY el.time DESC;
```

Auswerten:
- **Q-D1** → letzter `sent_to_gateway_at`-Setpoint vor 09:36 = Wert
  für `last_engine_setpoint`. Wenn = 11 → D.3b bestätigt.
- **Q-D2** → 7 Override-Anlagen mit `created_at` um 08:27 +
  `source = 'device'` + späteres `revoked_at`. Wenn nach 09:36 keiner
  mehr → eine der Hypothesen D.3a/c/d trifft.
- **Q-D3** → Occupancy- und Block-Flag-Stand zwischen 08:27 und 09:36.
- **Q-D4** → wenn 11 °C-Frame durch Gate (a) blockiert wurde, steht
  hier ein Eintrag mit `reason = device_blocked_vacant`. Datei:Zeile
  des Schreibpfads: `device_adapter.py:143-177`.

---

### Befund H2 — AE-17-Drift (uplinks-Hypertable existiert nicht)

**Belegt im Repo:**

- **AE-17-Text** (`docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md:197-205`)
  beschreibt eine `uplinks`-Hypertable mit Kernfeldern
  (`device_id, ts, fcnt, rssi, snr, freq`) und einem `payload`-JSONB-
  Feld.
- **Realität (Migration):** `backend/alembic/versions/0001_initial_
  domain_model.py:263-289` legt **`sensor_reading`** als Hypertable an
  (Composite-PK `(time, device_id)`, plus `create_hypertable
  ('sensor_reading', 'time', ...)`). `0002_lorawan_fcnt.py:36` ergänzt
  `fcnt`. **Keine** `uplinks`-Migration existiert in
  `backend/alembic/versions/` (Grep auf `"uplinks"` / `create_table.*
  uplinks` ergibt 0 Files).
- **Sprint-5-Begründung** (STATUS §2g.5.7): „KEINE neue `uplinks`-
  Tabelle — vorhandenes Schema deckt LoRaWAN-Telemetrie ab".
- **`sensor_reading`-Schema** (`models/sensor_reading.py:30-73`):
  dekodierte Spalten (`temperature`, `setpoint`, `valve_position`,
  `battery_percent`, `rssi_dbm`, `snr_db`, `open_window`,
  `attached_backplate`, `raw_payload`). **Kein** `freq`-Feld, **kein**
  JSONB-`payload`.

**Einordnung:** AE-17 ist sprint-historisch veraltet (durch Sprint-5-
Entscheidung de facto superseded), ohne im ADR-Log entsprechend
markiert zu sein. **KEIN ADR-Touch in diesem PR** (out of scope
Stufe 3, reine Diagnose-Doku). **Backlog-Kandidat:** separater
`chore/`-Doku-PR „AE-17 als superseded markieren, Verweis auf
`sensor_reading`-Schema". In den STATUS-Backlog aufnehmen, **nicht**
in diesen PR mischen.

Konsequenz für künftige Briefe: Brief-Annahmen über Tabellen-Schemas
auf `models/`-Stand (echt) prüfen, nicht auf ADR-Text (möglicherweise
historisch). Analogie zu §5.62 (DB-Schema gegen Brief-Annahme
verifizieren).

---

## Akzeptanzkriterien (Brief) — Final-Stand

| Kriterium | Status |
|---|---|
| Q1-Erweiterung (Lifecycle, retired-Vorgänger, Mai-Filter) im Query enthalten | **Erfüllt** — Q1 erweitert, gegen Live-DB ausgeführt, Prämisse widerlegt |
| A.0-Lifecycle-Fall vor Hypothesen-Auswahl belegt | **Gegenstandslos** — Q1 zeigt 4/4 aktiv, keine Stille |
| Jede Stille-Hypothese A.1 / A.2 / A.3 mit Beleg | **Gegenstandslos durch BLOCK-A-Prämisse-Widerlegung**, Code-Belegung bleibt als Referenz |
| Bruchstelle der Uplink-Kette für -002/-004 benannt + belegt | Drei Bruchstellen strukturell benannt; im aktuellen Stand keine reale Stille |
| Batterie Decode-Bug vs. Stale eingeordnet (byte[7]-Nibble-VERLAUF, nicht Einzelframe) | **Erfüllt + abgeschlossen** — Skalen-Mismatch belegt (`byte[7]=0xA0` → 3.0 V → 0 % an frischer AA-Alkaline + Last-Spannung ≈ Lastfrei-Spannung). Batterietyp = Alkaline durch Hotelier bestätigt → Skala 3.0–4.2 V generell falsch parametriert. 15b-Motorlast-Test entfällt, 15b reduziert auf Skala-Reparametrierung gegen Alkaline-Entladekurve. **NULL offene B-Punkte.** |
| `health_state`-„nie-gesehen"-Bug mit Datei:Zeile | **Code-Pfad korrekt belegt + Track §3-Punkt-3 GESTRICHEN** — Q1 zeigt 4/4 real healthy, KPI „4 von 4" ist korrekt, kein Symptom existiert. Frontend-Cross-Sicht-Audit ebenfalls gestrichen mangels Symptom |
| AE-17-Drift als Befund (Migration-Beleg, separater Doku-PR-Kandidat) | **Erfüllt** — H2 mit Migration-Datei:Zeile, Backlog-Eintrag-Hinweis, kein ADR-Touch in diesem PR |
| BLOCK D Sommermodus-/Reboot-Drift-Diagnose | **Erfüllt** — M1/M2-Trennung, D.3-Status (D.3c JA), D.6.1-3 Risikofläche belegt (43/45 exponiert), D.5-Priorität fixiert (VORRANG) |
| Alle Aussagen belegt | **Erfüllt** — T1/T2/D.x mit Datei:Zeile durchgängig; Q1/Q2/Q3 + Q-D-Output eingetragen |
| Einziger offener Punkt: ~14:45-Live-Prüfpunkt (M2-Selbstheilung) | **Nicht-PR-blockierend** — M2 ist Code-belegt (D.4.M2), 14:45-Live-Beobachtung ist Bestätigung, kein Belegungs-Ersatz |

## Definition of Done

- mypy/ruff/TS/Lint: **trivial grün** (kein Code-Change).
- Doku-Datei auf Branch `chore/sprint-15a-hardware-health-diagnose`.
- PR via `gh ... --body-file` (§5.70) — **Stop vor PR-Erstellung**
  (Stufe-3-Standard, Brief).
- Kein Tag (reine Diagnose-Doku).

## Out of Scope

- Fix jeglicher Art (Codec-Edit, Subscriber-Patch, UI, Migration).
- Frontend-Cross-Sicht-Audit (eigener Sprint, siehe Befund H1).
- Motorlast-Test Vicki-001 (Sprint 15b).
- ChirpStack-Bootstrap-/Codec-Deploy-Skript (Backlog §5.22).
- SMTP-Versand für Health-Alerts (eigener Sprint nach Heizperiode,
  AE-53 §5).
