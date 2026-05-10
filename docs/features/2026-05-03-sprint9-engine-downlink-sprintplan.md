# Sprint 9 Sprintplan — Regel-Engine + Downlink

**Datum:** 2026-05-03
**Phase:** 2 (Sprintplan) — abgeleitet aus Brief `2026-05-03-sprint9-engine-downlink.md`
**Workflow:** Ultra-autonom (vereinbart 2026-05-02)

## Strategie: Walking Skeleton zuerst

Ziel: **so schnell wie moeglich End-to-End-Live-Demo** „Belegung POST → Engine → Downlink → Vicki-Display ändert Setpoint". Dann iterativ pro Layer ergänzen.

Reihenfolge ist optimiert für „minimal viable engine in 4–5 Sub-Sprints, dann Vollausbau":

1. **9.0** Codec (Backend-only, kleinstes Risiko, Voraussetzung für Reply-Verarbeitung)
2. **9.1** Celery + Redis (Infra)
3. **9.2** Downlink-Adapter (mqtt-publish + ChirpStack-Format)
4. **9.3** Engine Layer 5 (Hard Clamp) + Layer 1 (Base aus rule_config) + Hysterese — Walking Skeleton, NICHT alle 6 Layer
5. **9.4** Trigger Event-basiert (Belegungs-POST → evaluate_room.delay)
6. **9.5** Audit-Log-Persistenz + GET /rooms/{id}/engine-trace
7. **9.6** **Live-Test #1** auf heizung-test mit Vicki-001 — End-to-End-Demo
8. **9.7** Engine Layer 0 (Sommermodus) + Scheduler (Celery-Beat 60 s)
9. **9.8** Engine Layer 2 (Temporal/Vorheizen)
10. **9.9** Engine Layer 3 (Manual) + Layer 4 (Window)
11. **9.10** Frontend EngineDecisionPanel
12. **9.11** **Live-Test #2** End-to-End mit allen Layern
13. **9.12** Doku + PR + Tag `v0.1.9-engine`

---

## Sub-Sprints im Detail

### 9.0 Codec mclimate-vicki.js (fPort 1+2, Hotfix valve_position, neuer encode 0x51)

**Aktueller Bug-Stand:**
- Codec macht KEINE fPort-Unterscheidung (alles wird als Periodic Report parsed). fPort 2 (Command-Replies vom Vicki) wird falsch verarbeitet.
- `valveOpenness` kann negativ werden, wenn `motorPosition > motorRange` (Task #86).
- `encodeDownlink` produziert `0x02 + (t*2)` — falsches Command-Byte. Vicki erwartet `0x51 + (t*10 in 2-Byte BE)` laut Spike (Task #87).
- Vicki-Setpoint-Reply (Command 0x52, 3 Bytes auf fPort 2) wird nicht decoded.

**Tasks:**
- [ ] Codec-Rewrite mit `if (input.fPort === 1) { decode periodic report } else if (input.fPort === 2) { decode command-reply (0x52) }`
- [ ] `valveOpenness` clampen auf `[0, 100]`
- [ ] `encodeDownlink` auf Command 0x51 + 2-Byte-BE-Setpoint*10, fPort 1
- [ ] Codec-Tests neu in `infra/chirpstack/codecs/test-mclimate-vicki.js` (Node-only, kein Framework — `console.assert`)
- [ ] Codec auf `cs-test.hoteltec.at` deployen (über ChirpStack-API oder UI)
- [ ] Live-Verifikation: Vicki-001 Periodic Report → SensorReading.temperature passt; `mosquitto_pub` simuliert 0x52-Reply → Subscriber-Log zeigt korrekten Decode

**Dauer:** 2–3 h
**PR:** `feat/sprint9.0-codec-fport2`
**Risiken:** Codec-Update auf ChirpStack-Server muss live laufen — wenn falsch, brechen alle 4 Vicki-Decodes. Mitigation: Test-Strings vor Deploy gegen ChirpStack-Codec-Tester.

### 9.1 Celery + Redis-Setup, Worker-Container

- [ ] `pyproject.toml`: `celery[redis]` + `flower` (optional) ergänzen
- [ ] `backend/src/heizung/celery_app.py` mit Broker = `redis://redis:6379/0`, Backend = `redis://redis:6379/1`
- [ ] Stub-Task `evaluate_room(room_id: int)` (returns dict, schreibt noch nichts)
- [ ] `docker-compose.prod.yml`: neuer Service `celery_worker` (Image = api, Command = `celery -A heizung.celery_app worker --concurrency=2 --loglevel=info`)
- [ ] Healthcheck: `celery -A heizung.celery_app inspect ping`
- [ ] Pytest: `test_celery_app.py` — Task ist registriert, kann `.delay()` aufrufen (ohne Worker-Run)

**Dauer:** 2 h
**PR:** `feat/sprint9.1-celery`

### 9.2 Downlink-Adapter

- [ ] `backend/src/heizung/services/downlink_adapter.py` mit `async def send_setpoint(dev_eui: str, setpoint_c: int) -> str` (Returns: command-id)
- [ ] Encoded `0x51 + (setpoint*10 high) + (setpoint*10 low)` als base64 → JSON-Payload `{"data": "<base64>", "fPort": 1, "confirmed": false}`
- [ ] Publish via `aiomqtt` auf `application/<APP_ID>/device/<DevEUI>/command/down`
- [ ] `CHIRPSTACK_APP_ID` als Setting (env: `CHIRPSTACK_APP_ID`)
- [ ] Pytest mit Mock-MQTT-Client (Patch `aiomqtt.Client`)

**Dauer:** 2 h
**PR:** `feat/sprint9.2-downlink`

### 9.3 Engine Layer 5 + Layer 1 + Hysterese (Walking Skeleton)

- [ ] `backend/src/heizung/rules/engine.py` mit `async def evaluate_room(room_id: int) -> RuleResult`
- [ ] `RuleResult` Dataclass: `setpoint_c: int`, `layers: list[LayerStep]`, `should_send_downlink: bool`
- [ ] `LayerStep` Dataclass: `name`, `setpoint_c`, `reason`
- [ ] Layer 1 (Base): liest `rule_config` für Raum-Status (`occupied` → `default_t_occupied`, `vacant` → `default_t_vacant`, etc.)
- [ ] Layer 5 (Clamp): `max(FROST_PROTECTION_C, min(MAX_TEMP_C, setpoint))` (FROST=10, MAX=30)
- [ ] Hysterese-Check: vergleicht mit letztem `control_command`, returns `should_send_downlink=False` wenn `|new - old| < 1.0` UND `last_change < 6h`
- [ ] Pytest 8+ Tests (occupied/vacant/blocked, frostschutz greift, hysterese hält, max greift)

**Dauer:** 3 h
**PR:** `feat/sprint9.3-engine-skeleton`

### 9.4 Trigger Event-basiert

- [ ] In `api/v1/occupancies.py` und `api/v1/global_config.py`: nach erfolgreichem POST/PATCH `evaluate_room.delay(room_id)` für betroffene Räume
- [ ] In `services/occupancy_service.py.sync_room_status`: nach Status-Wechsel ebenfalls Trigger
- [ ] Pytest: API-POST mit Mock-Celery zeigt `delay()`-Aufruf

**Dauer:** 2 h
**PR:** `feat/sprint9.4-event-trigger`

### 9.5 Audit-Log + Engine-Trace-API

- [ ] Engine schreibt nach Eval pro Layer eine Row in `event_log` (event_type=`engine_layer`, payload=JSON mit name/setpoint/reason)
- [ ] Außerdem: 1 Row `engine_eval` mit Final-Result + ob Downlink gesendet
- [ ] Outgoing Downlink: `control_command` mit `setpoint_c`, `sent_at`, `dev_eui`
- [ ] `GET /api/v1/rooms/{id}/engine-trace?limit=50` — neuestes zuerst
- [ ] Pytest 4+ Tests

**Dauer:** 2 h
**PR:** `feat/sprint9.5-audit-trace`

### 9.6 LIVE-TEST #1 (End-to-End Walking Skeleton)

- [ ] Deploy auf heizung-test, Pull-Verifikation per Image-ID-Check (CLAUDE.md §5.11)
- [ ] Belegung POST für Zimmer mit Vicki-001 → Logs zeigen: Trigger → Engine → Downlink → MQTT-Topic
- [ ] Vicki-001 Display ändert Setpoint innerhalb 60 s (Class A Uplink-Fenster)
- [ ] Audit-Log API liefert sauberen Trace
- [ ] Wenn rot: Bug-Diagnose, dann Fix, dann erneuter Test

**Dauer:** 2 h
**KEIN PR** — wenn rot: separater Hotfix-PR

### 9.7 Sommermodus (Layer 0) + Scheduler

- [ ] Layer 0: wenn `global_config.summer_mode_active = true` → Setpoint = FROST_PROTECTION_C, Skip Layer 1–4
- [ ] Celery-Beat-Service `celery_beat` im Compose (Image = api, Command = `celery -A heizung.celery_app beat --loglevel=info`)
- [ ] Periodic Task „evaluate_due_rooms" alle 60 s — sucht Räume mit `next_transition_at <= now`
- [ ] `next_transition_at`-Spalte in `room` (Migration 0004)
- [ ] Pytest 4+ Tests

**Dauer:** 3 h
**PR:** `feat/sprint9.7-summer-scheduler`

### 9.8 Layer 2 Temporal (Vorheizen + Nachtabsenkung)

- [ ] Layer 2 liest `rule_config.preheat_minutes_before_checkin` und `rule_config.night_setback_*`
- [ ] Vorheizen: 60 Min vor Check-in → Setpoint hochziehen auf `default_t_occupied`
- [ ] Nachtabsenkung: 22:00–06:00 → Setpoint = `default_t_night`
- [ ] Konflikt-Lösung: Vorheizen gewinnt vor Nachtabsenkung (Reihenfolge in Code)
- [ ] Pytest 6+ Tests

**Dauer:** 4 h
**PR:** `feat/sprint9.8-temporal`

### 9.9 Layer 3 Manual + Layer 4 Window

- [ ] Layer 3a: aktive `manual_setpoint_event` (UI Sprint 10) overrides Layer 1+2
- [ ] Layer 3b: Vicki-Setpoint vom Drehring (aus fPort 2 0x52, persistiert via 9.5/9.7) — wird respektiert wenn jünger als 30 Min
- [ ] Layer 4: wenn letzter Reading `openWindow=true` → Frostschutz für 5 Min
- [ ] Pytest 6+ Tests

**Dauer:** 3 h
**PR:** `feat/sprint9.9-manual-window`

### 9.10 Frontend EngineDecisionPanel

- [ ] Neuer Tab „Engine" im Zimmer-Detail (`/zimmer/[id]`)
- [ ] Hook `useEngineTrace(roomId)` mit Refetch alle 30 s
- [ ] Schicht-Trace-Tabelle (Layer-Name, Setpoint, Reason)
- [ ] Letzter Downlink + ack-Status
- [ ] Strategie-konform mit `Button`/Tokens aus Sprint 8.15
- [ ] Playwright-Smoke

**Dauer:** 3–4 h
**PR:** `feat/sprint9.10-engine-panel`

### 9.11 LIVE-TEST #2 (alle Layer aktiv)

- [ ] Sommermodus AN/AUS → Setpoint switcht auf 10 °C / Default
- [ ] Vorheizen 60 Min vor Check-in → Vicki ändert auf 21 °C
- [ ] Window-Open simuliert → Setpoint geht auf 10 °C
- [ ] Manueller Drehring am Vicki → Engine respektiert für 30 Min
- [ ] Frontend Engine-Panel zeigt alle Übergänge

**Dauer:** 2 h

### 9.12 Doku + PR + Tag

- [ ] STATUS.md Sprint 9
- [ ] CONTEXT.md auf Sprint 10
- [ ] AE-32 in ARCHITEKTUR-ENTSCHEIDUNGEN.md (Hysterese 1 °C statt 0.5 °C, mit Spike-Begründung)
- [ ] AE-36 (neuer ADR): Walking-Skeleton-Reihenfolge der Engine-Layer
- [ ] PR develop → main
- [ ] Tag `v0.1.9-engine`
- [ ] Build-Trigger + Image-Pull-Verifikation auf heizung-main

**Dauer:** 1–2 h

---

## Gesamt: ca. 30 h Code + 4 h Live-Tests + 2 h Doku = **~36 h** über 12 Sub-Sprints.

## Hartes Pflicht-Programm (Lessons Sprint 8.15)

Vor jedem PR-Push:
1. Konfig-File-Check: `git diff --stat <alle geaenderte yml/toml/config-Files>` — wenn 0 changed obwohl Edit gemacht: PowerShell `WriteAllText` statt Sandbox-Edit.
2. Nach Merge: `gh workflow run build-images.yml --ref develop` + `gh run watch`.
3. Nach Server-Pull: `docker images ghcr.io/rexei123/heizung-web --format` + ID-Vergleich.
