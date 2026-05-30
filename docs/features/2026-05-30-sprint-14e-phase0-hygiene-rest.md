# Sprint 14e — Phase-0-Audit: Hygiene-Rest aus 14a/b/c (FU-1, FU-2, FU-3)

**Datum:** 2026-05-30
**Branch:** `chore/sprint-14e-phase0`
**Basis:** develop @ `8be7db6` (Sprint 14d STATUS-Doku-Nachzieher merged)
**Stufe:** 3 (read-only Audit, kein Code-/Schema-/Migration-Touch)
**Scope (Strategie-Chat 2026-05-30):** FU-1 Zone-Ist-Temp · FU-2 Engine-
Setpoint aus Trace (AE-31/S3/AE-55, KEIN neues Speicherfeld) · FU-3 Inline-
Edit Stammdaten (name Admin / room_type Admin+Warnung+Audit). FU-14c-3
display_name **gestrichen**, kein Audit.

---

## Zusammenfassung

- **FU-1 ist S.** Pure-Function-Aggregat (`aggregate_zone_readings`) existiert
  und ist bereits **produktiv** im Dashboard im Einsatz. Backend-Aufgabe:
  `HeatingZoneRead` um `mean_temperature_c` erweitern, per-Zone-Enrichment im
  Zonen-Endpoint (Pattern Sprint 14d FU-5). Frontend: ZoneCard-Header.
- **FU-2 ist M, kein Reißleinen-Kandidat.** Schema (`event_log`) trägt den
  finalen Setpoint als **Top-Level-Spalte** `setpoint_out` in der `HARD_CLAMP`-
  Layer-Row — nicht in `details`-JSONB. PK `(time, room_id, evaluation_id,
  layer)` bestätigt. Zone↔Room ist n:1, alle Zonen eines Zimmers teilen
  denselben Engine-Setpoint (AE-51 §4.2 symmetrische Vicki-Setpoints). Bestand
  liefert nur `GET /rooms/{id}/engine-trace` (per-Room-Last-N, kein Batch).
  Batch-Helper für N Zonen via `DISTINCT ON (room_id) … ORDER BY time DESC`
  auf der Hypertable, gedeckt vom Index `ix_event_log_room_time`.
- **FU-3 zerfällt in S (Zone-Name) + M (room_type).** PATCH-Endpoints +
  Schemas + Generic-InlineEditCell-Pattern + role-aware `useAuth` existieren
  bereits. Engine-Wirkung von `room_type` ist real (RuleConfigs ROOM_TYPE-
  Scope, `engine.py:856`) — Warn-Pflicht fachlich begründet.
  `record_business_action`/`record_config_change` sind etablierte Helper.
- **Block-Gesamt: M** (oberer Rand). 14e-Bündel tragbar.

---

## §A — FU-1 Zone-Aggregat-Ist-Temp 🟢

### Bestand

- **Aggregat-Helper (pure):** `backend/src/heizung/rules/aggregation.py:61`
  `aggregate_zone_readings(readings: list[ReadingForAggregate]) ->
  (Decimal | None, bool | None)` — arithmetisches Mittel über `healthy`-
  gefilterte Readings, ROUND_HALF_EVEN auf 0.1 °C (AE-51 §4.1).
- **Konsument heute:** `services/dashboard_aggregates.py:36` (Import), `:155`
  (Aufruf). KPI „Ø Raumtemperatur" auf Dashboard (Sprint 14c). Per-Device
  letzte Readings via `DISTINCT ON device_id`, dann pro Zone aggregiert —
  produktive Batch-Form.
- **`_load_room_context` (engine):** `rules/engine.py:833-892` lädt Room +
  RoomType + RuleConfigs + GlobalConfig + next_occupancy. **Lädt keine
  SensorReadings.** Helper-Docstring `aggregation.py:13-18` bestätigt: „noch
  nicht in der Engine-Read-Pipeline integriert; Ist-Temp ist heute kein
  Engine-Input." Layer 4 Window-Detection nutzt eigenes OR-Aggregat.
- **`HeatingZoneRead` (Schema):** `schemas/heating_zone.py:49-67` —
  `id, room_id, kind, name, is_towel_warmer, health_state, created_at,
  updated_at, active_override` (Sprint 14d). **Kein** Ist-Temp-Feld.
- **Per-Vicki-Temp (Bestand):** `schemas/device.py:145` `DeviceLatestReadingRead`
  liefert `temperature: number | null` pro Gerät (Sprint 14a). Frontend
  `ZoneCard` rendert pro Gerät `ThermostatBubble` mit Ist-Temp (sichtbar im
  Heizzonen-Tab) — Per-Vicki-Sicht existiert, **Aggregat fehlt im UI**.

### Befund

Zone-Aggregat ist Greenfield für `HeatingZoneRead`. Pattern Sprint 14d FU-5
(per-Zone-Enrichment im `_build_zone_read` Helper, `api/v1/heating_zones.py:36`)
direkt übertragbar. Backend-Aufgabe: `HeatingZoneRead.mean_temperature_c:
Decimal | None` (field_serializer → float, §5.63), Enrichment via
`aggregate_zone_readings` über DeviceReadings der Zone-Devices.

### Aufwand

**S.** Backend additiv (Schema-Feld + Enrichment-Helper, keine Migration,
existierender Pure-Helper). Frontend ZoneCard-Header erweitern (zwei Slots
Name+Badge vs. neuer Aggregat-Slot — §5.66 Multi-Badge-Cell-Lesson beachten,
falls Header verbreitert wird).

### Offene Architektur-Entscheide für Implementation-Brief

- **Quelle Reading:** DeviceLatestReading (heute schon in `DeviceRead`
  enriched) wiederverwenden oder eigene SensorReading-Query pro Zone?
  Wiederverwenden ist billiger, aber koppelt FU-1 an die `latest_reading`-
  Form. Empfehlung: eigener kleiner Helper `_collect_zone_latest_readings`
  parallel zu `dashboard_aggregates._collect_zone_aggregates`, gibt
  `dict[zone_id, (Decimal, bool|None)]` für `_build_zone_read`.
- **Sichtbarkeit bei `health_state == "no_device"`:** Aggregat ist `None`.
  Frontend rendert „—" oder blendet den Slot aus? Brief klärt.

---

## §B — FU-2 Engine-Setpoint aus Trace 🟠

### Bestand

- **`event_log`-Schema:** `backend/src/heizung/models/event_log.py:36-103`
  Hypertable, PK `(time, room_id, evaluation_id, layer)` (`:40-72`).
  **`setpoint_out: Numeric(4, 1)` ist Top-Level-Spalte (`:80`)**, NICHT in
  `details`-JSONB. Index `ix_event_log_room_time` `(room_id, time)` `:100`.
- **HARD_CLAMP-Schreibung:** `tasks/engine_tasks.py:212-240` — pro Engine-
  Evaluation eine Row pro Layer; HARD_CLAMP-Row trägt zusätzlich
  `downlink_per_device` + `downlink_zone_status` in `details`. `setpoint_out`
  = `layer.setpoint_c` (finaler quantisierter Setpoint, AE-55 P1).
- **Enum:** `EventLogLayer.HARD_CLAMP = "hard_clamp"` (`models/enums.py:189`).
- **Mapping Zone↔Room:** `HeatingZone.room_id` (n:1). event_log ist **per-
  Room**, **nicht** per-Zone. Konsequenz: alle Zonen eines Zimmers teilen
  denselben `setpoint_out` der jüngsten HARD_CLAMP-Row (AE-51 §4.2:
  symmetrische Vicki-Setpoints; D7-Drift bewusst, keine Zone-PK-Erweiterung).
- **Read-Endpoint Bestand:** `api/v1/rooms.py:238-262` `GET
  /rooms/{room_id}/engine-trace?limit=N` liefert per-Room die letzten N
  Layer-Rows. **Kein Batch**, **keine `WHERE layer = …`-Filter**, kein
  Setpoint-Last-Aggregat.
- **Dashboard-Beispiel:** `services/dashboard_aggregates.py:100-104` macht
  `select(func.max(EventLog.time)).where(EventLog.layer ==
  EventLogLayer.HARD_CLAMP)` (Tick-Last für KPI „Letzter Algorithmen-Lauf").
  Liefert NUR den Timestamp, nicht den Setpoint.

### Batch-Skizze (Zone-Liste eines Zimmers, KEIN Code)

```sql
SELECT DISTINCT ON (room_id) room_id, time, setpoint_out, reason
FROM event_log
WHERE layer = 'hard_clamp' AND room_id = ANY(:room_ids)
ORDER BY room_id, time DESC;
```

Index-Pfad: `ix_event_log_room_time` deckt `(room_id, time DESC)`-Sort + 
Filter. Für die Zimmer-Detail-Seite ist `:room_ids` ein einzelner Wert →
trivial. Bei kommenden Cross-Sichten (Dashboard-KPI 7+) wäre `ANY(...)` mit
mehreren IDs robust. Performance auf Hypertable: chunk-pruning via
`time`-Partition; HARD_CLAMP-Filter selektiv (~1/N Layer-Rows pro Evaluation).

### Befund + Aufwand

**M, kein Reißleinen-Kandidat.**

- Backend: neuer Service-Helper `event_log_service.latest_hard_clamp_per_room`
  (Batch), `HeatingZoneRead.engine_setpoint_c: Decimal | None`, Enrichment in
  `_build_zone_read` (`api/v1/heating_zones.py:36`). Pure Read auf bestehende
  Hypertable, keine Migration, kein neuer Write-Pfad. S3/AE-31/AE-55-konform:
  einzige Quelle der Wahrheit bleibt das Engine-Trace.
- Frontend: ZoneCard-Header zeigt den per-Room-shared Engine-Setpoint pro
  Zone (alle Zonen eines Zimmers tragen denselben Wert — fachlich korrekt).
- Edge-Case: vor erster Engine-Evaluation existiert keine HARD_CLAMP-Row →
  `None`. UI rendert „—" / „noch nicht evaluiert" (Brief klärt Wording).

**Reißleinen-Erwägung (R3):** Wenn ein zweiter Konsument (Dashboard-Kachel,
Cross-Room-Sicht) auftaucht, der pro Aufruf 45 Räume in einer Query holen
soll, ist der Batch-Helper gut investiert. Kippt M auf L erst, falls
ChirpStack-Backfill-Job rückwirkend Setpoints rebroadcast → out of scope.

### Offene Architektur-Entscheide für Implementation-Brief

- **`Decimal`-Serialisierung:** field_serializer → float (§5.63-Konvention,
  identisch zu `ZoneActiveOverrideRead.setpoint_celsius`).
- **Bei aktivem Override:** ZoneCard zeigt heute (Sprint 14d FU-5) den
  Override-Setpoint im Banner. Bei FU-2 + aktivem Override: Override-Setpoint
  als „aktuell wirksam", Engine-Setpoint als „regulär ohne Übersteuerung"?
  Klare Sicht-Trennung in der UI nötig — Brief klärt Wording + Layout.
- **Mehr-Layer-Sicht (Sub-Slot):** Nicht in 14e. Engine-Decision-Panel
  bleibt als Diagnose-Detail. ZoneCard zeigt nur den finalen Setpoint.

---

## §C — FU-3 Inline-Edit Zone-Stammdaten + Room.room_type 🟢/🟠

### Bestand

- **PATCH Zone:** `api/v1/heating_zones.py:152-182`
  `PATCH /rooms/{rid}/heating-zones/{zid}`, Dep `require_admin` (`:161`),
  Schema `HeatingZoneUpdate` (`schemas/heating_zone.py:41-46`): optional
  `kind`, `name`, `is_towel_warmer`. **Name ist live PATCH-fähig** —
  Backend-Aufgabe 0.
- **PATCH Room:** `api/v1/rooms.py:136-167`
  `PATCH /rooms/{rid}`, Dep `require_admin` (`:144`), Schema `RoomUpdate`
  (`schemas/room.py:23-36`): optional `number, display_name, room_type_id,
  floor, orientation, status, notes`. **`room_type_id` ist live PATCH-fähig**
  — Backend-Aufgabe 0. Verifikation existiert via `_ensure_room_type_exists`
  (`api/v1/rooms.py:154-155`).
- **Bestand Audit-Service:**
  - `services/business_audit_service.py:38` `record_business_action(*,
    user_id, action, target_type, target_id, old_value, new_value,
    request_ip)` — atomar in derselben Session/Transaction.
  - `services/config_audit_service.py:40` `record_config_change(*, source,
    table_name, column_name, old_value, new_value, scope_qualifier, …)` —
    für Settings-Drift (RuleConfig-Stil).
  - Pattern-Vorbild (operative Aktion): `api/v1/rooms.py:220-228`
    `ROOM_OVERRIDE_BLOCK_TOGGLED` im Sperr-Toggle (Sprint 12c/AE-58). →
    Empfehlung für room_type-Wechsel: **`record_business_action`** mit
    `action="ROOM_TYPE_CHANGED"`, `target_type="room"`,
    `old_value/new_value={"room_type_id": …}`.
- **Inline-Edit-Pattern (Generic):**
  `frontend/src/components/inline-edit-cell.tsx:1-60` — Sprint 9.14 T4 /
  AE-46 / AE-3 Auto-Save-on-Blur, Variants `text/number/time/decimal`, Zod-
  Validator-Slot. Heute genutzt in `app/einstellungen/temperaturen-zeiten/
  page.tsx`.
- **Inline-Edit-Pattern (Devices / 14a-Stil):**
  `frontend/src/app/devices/page.tsx:220-289` `LabelCell` (Klick → Input →
  Enter/Blur → `useUpdateDevice.mutateAsync({label: next})`, Esc abbrechen,
  Save-Error inline). Direktes Vorbild für Zone-Name auf der Zone-Card.
- **Role-Gating Frontend:** `contexts/auth-context.tsx:95` `useAuth()` mit
  `user.role: "admin" | "mitarbeiter"` (`lib/api/types.ts:434`). Bereits in
  `components/patterns/app-shell.tsx:167,180` für die Header-Anzeige genutzt.
  → Affordance-Gating via `user.role === "admin"`-Conditional.

### Engine-Wirkung von `room_type` (warum die Warnung Pflicht ist)

`_load_room_context` (`rules/engine.py:833-860`) lädt RuleConfigs über drei
Scopes: GLOBAL immer + **ROOM_TYPE** wenn `RuleConfig.room_type_id ==
room.room_type_id` (`:855-857`) + ROOM wenn passend. Ein `room_type`-Wechsel
ändert sofort die effektiven Felder, die `_resolve_field` auflöst —
typischerweise `t_occupied`, `t_vacant`, `t_night_setback_offset`,
`t_frost_protection`. Konsequenz: nach dem Save übernimmt die nächste
Engine-Evaluation (≤ 60 s, Heartbeat `engine_tasks.py:255`) die neuen Soll-
Werte. Hotelier muss informiert sein, dass das auch Zimmer mit aktiver
Belegung trifft.

### Aufwand

| Sub-FU | Beschreibung | Klasse |
|---|---|---|
| FU-3a | Zone-Name inline-edit auf ZoneCard, Admin-only, ohne Warnung | **S** |
| FU-3b | Room.room_type inline-Select auf Zimmer-Detail-Header, Admin-only, ConfirmDialog (Bestand), `record_business_action`-Eintrag in der PATCH-Transaktion (Endpoint-Patch nötig — heute schreibt PATCH /rooms keinen Audit-Eintrag) | **M** |
| **Block-Gesamt** | FU-3a + FU-3b | **M** (oberer Rand) |

Kein Reißleinen-Kandidat: PATCH-Endpoints und Schemas existieren, kein neues
Audit-Modell, kein Migration-Bedarf, keine Engine-Logik-Änderung.

### Offene Architektur-Entscheide für Implementation-Brief

- **FU-3a Scope:** Brief sagt „name = Admin". Soll `kind` / `is_towel_warmer`
  in 14e mitkommen (Schema deckt sie, ConfirmDialog nicht nötig) oder strikt
  14e = nur Name? Empfehlung: nur Name, kind/towel mit dem 14f-Block
  reaktiviert (alte B-14b-FU-3-Beschreibung „Name/Kind/Handtuchtrockner" war
  breiter). Brief klärt.
- **FU-3b Confirmation-Wording:** Vorschlag „**Raumtyp ändern?** Engine-Soll-
  Werte (Belegt/Leer/Nacht/Frostschutz) wechseln sofort auf die Werte des
  neuen Raumtyps. Betrifft auch belegte Zimmer." — Brief friert den Wortlaut.
- **FU-3b Audit-Form:** `business_audit` (Empfehlung, operative Aktion,
  parallel zum override-block-Pattern) **oder** `config_audit` (formal-
  config-Drift)? Empfehlung business_audit, weil pro-Zimmer-Aktion mit
  user_id-Kontext sinnvoll ist und der Verlauf im Hotelier-UI später als
  „Wer hat wann den Raumtyp gewechselt?" relevant wird.
- **Affordance-Sichtbarkeit für Mitarbeiter:** Read-only-Wert anzeigen oder
  ganz ausblenden? Empfehlung: read-only-Wert sichtbar, kein Edit-Cursor,
  kein 401-Trigger beim Klick (UX-Klarheit vor Defense-in-depth).
- **request_ip-Quelle:** im PATCH-Handler via FastAPI `Request` injizieren
  (Pattern aus `api/v1/rooms.py:175` `set_override_block_state(request:
  Request, …)`).

---

## §D — Out of Scope

- **FU-14c-3 `User.display_name`** (Migration + Schema + Users-API + Form +
  Dashboard-Greeting): **gestrichen per Strategie-Chat 2026-05-30**. Nicht
  Teil von 14e. Backlog-Eintrag B-14c-FU-3 bleibt formal offen, Status
  „zurückgestellt".
- **FU-3 kind/is_towel_warmer:** möglicherweise 14f (siehe §C Offene
  Entscheide).
- **Mehr-Zonen-Engine-Setpoint-Sub-Trace (Layer-Aufschlüsselung):** bleibt
  Engine-Decision-Panel-Domäne, nicht 14e.

---

## §E — Aufwands-Tabelle

| FU | Inhalt | Klasse | Reißleine? |
|---|---|---|---|
| FU-1 | Zone-Ist-Temp auf ZoneCard | **S** | nein |
| FU-2 | Engine-Setpoint auf ZoneCard | **M** | nein (R3 nicht ausgelöst) |
| FU-3a | Zone-Name inline-edit Admin | **S** | nein |
| FU-3b | Room.room_type inline-edit Admin + Warnung + Audit | **M** | nein |
| **Block 14e** | Bündel | **M (oberer Rand)** | tragbar |

---

## §F — Offene Risiken / Drift-Funde

- **R1 (Engine-Setpoint vs. Override-Setpoint UI-Trennung):** ZoneCard hat
  seit 14d FU-5 schon einen Override-Banner. FU-2 ergänzt einen zweiten
  Setpoint-Wert (regulär). Layout/Wording-Klarheit wichtig, damit Hotelier
  nicht zwei Zahlen nebeneinander missversteht. Brief klärt R1.
- **R2 (Aggregat ohne Reading):** FU-1 zeigt `None` wenn alle Vickis
  silent/degraded. UI muss expliziten „—"-State haben, nicht 0.0 °C
  rendern.
- **R3 (Batch-N-Skalierung FU-2):** heute nur per-Zimmer-Detail, also N=1.
  Keine Reißleine aktiv. Wenn 14f Cross-Sicht-Kachel mit Setpoint pro Zimmer
  baut, ist der Batch-Helper bereits passend.
- **R4 (PATCH /rooms ohne Audit heute):** Bestand-PATCH-Handler
  (`api/v1/rooms.py:141-167`) ist Audit-frei. FU-3b ergänzt
  `record_business_action` für `room_type_id`. Andere Felder
  (`display_name`, `number`, `floor`, `orientation`, `status`, `notes`)
  bleiben Audit-frei — bewusste Scope-Eingrenzung. Brief dokumentiert.
- **R5 (Affordance-Gating Konsistenz):** Frontend hat heute kein zentrales
  Admin-Affordance-Pattern (eher pro Komponente). 14e wäre der erste
  Inline-Edit-Konsument mit role-aware Affordance auf der Zimmer-Detail-
  Seite — Pattern-Etablierung; Brief friert die exakte Form (Conditional-
  Rendering vs. CSS-disabled-Hint).
- **Keine S1-Drift:** keine aspirativen Kommentare / Race / TODO in
  Steuerlogik gefunden. Helper `aggregate_zone_readings` Docstring nennt
  „noch nicht in der Engine-Read-Pipeline integriert" als Absichtserklärung
  — ist die Ausgangslage von FU-1, kein Doku-Drift im Sinn §5.20.

---

**Stop-Point:** Phase-0-Audit abgeschlossen. Kein Code-/Schema-/Migration-/
Test-Touch. Warte auf Strategie-Chat-Freigabe für 14e-Implementation-Brief
(inkl. R1–R5 + FU-3a-Scope-Entscheid + FU-3b-Wording).
