# Sprint 9.10 — Window-Detection (Engine Layer 4) + AE-40 Task-Lock

**Datum:** 2026-05-06
**Branch:** `feat/sprint9.10-window-detection`
**PR:** #100
**Tag:** `v0.1.9-rc3-window-detection` (vergeben nach Merge auf `develop`).

## Ziel
Engine reagiert in Sicherheits-Geschwindigkeit auf offene Fenster: Vicki-Codec-Flag `openWindow` wird persistiert, Layer 4 wertet das jüngste Reading je Gerät aus und fährt den Setpoint bei aktivem Fenster auf System-Frostschutz. Zusätzlich wird der Race-Condition-Brandherd zwischen Reading-Trigger und 60-s-Beat (AE-40) durch einen Cluster-weiten Redis-SETNX-Lock geschlossen.

## Tasks

| Task | Beschreibung | Status | Branch-Commit |
|---|---|---|---|
| T1 | `sensor_reading.open_window` (Migration `0009`, Schema/Model, Subscriber-Mapping) | erledigt | `7959e1d` |
| T2 | Engine **Layer 4** `layer_window_open` + 15 DB-Tests inkl. 29.9/30.1-Min-Boundary | erledigt | `40a2368` |
| T3 | MQTT-Subscriber triggert `evaluate_room.delay` nach Reading-Persist | erledigt | `500efa0` |
| T3.5 | **eingeschoben** — Redis-SETNX-Lock + Token + Lua-Release (AE-40) | erledigt | `4206cc6` |
| T4 | Frontend Window-Indicator (`extractWindowOpenSince` Pure-Funktion + DOM-Marker) | erledigt | `4518f31` |
| T5 | Sprint-Doku: STATUS, CLAUDE.md §5.18-5.20, ADR-Update, Sprint-Brief | erledigt | `646fdf9` (+ Nachzügler) |

T3.5 wurde nach T3 nachgezogen, weil der frische Reading-Trigger erst die latente Race-Condition aus Sprint 9.6 (siehe §5.20) aktiv freilegte — ohne Lock hätte Layer 4 ab T3 doppelte ControlCommands erzeugt.

## Architektur-Entscheidungen

- **Layer-4-Position** zwischen Layer 3 (Manual-Override) und Layer 5 (Hard-Clamp). Override darf Window-Detection NICHT umgehen — manueller 25 °C-Befehl bei offenem Fenster gewinnt nicht. Layer 5 cappt zusätzlich auf `room_type.max_temp_celsius`, bleibt unberührt.
- **Reading-Trigger statt Beat-Tick** — `evaluate_room.delay` direkt nach Reading-Persist im Subscriber. Layer 4 reagiert im Sekunden- statt Minuten-Bereich. Ohne Trigger wäre die Fensterauf-Latenz bis zu 60 s.
- **Redis-SETNX mit Token + Lua-Release** (AE-40) — atomic Mutex Cluster-weit. Token im Value verhindert Release durch fremden Worker (Crash-Sicherheit). TTL=30 s ≥ `task_time_limit` → Self-Healing bei OOM/Container-Kill/SIGKILL ohne externes Cleanup. Bei Lock-Miss: `apply_async(countdown=5)` statt Drop.
- **`MIN_SETPOINT_C` als Frostschutz-Quelle** — kein separates `frost_protection_setpoint`-Feld. `MIN_SETPOINT_C = int(FROST_PROTECTION_C)` aus `rules/constants.py` ist die einzige Wahrheit; Layer 4 setzt darauf, Layer 5 cappt nach unten auf denselben Wert. Spätere Hotel-Konfigurierbarkeit erfordert dann nur eine Quellen-Änderung.
- **Stateless aus letztem Reading** — keine `window_open_state`-Tabelle. Layer 4 liest pro Eval `DISTINCT ON (device_id) … ORDER BY time DESC` und filtert auf `WINDOW_STALE_THRESHOLD_MIN`. Vorteile: keine Migrations-Last, kein State-Drift bei Worker-Restart, idempotent. Nachteil: O(zonen) DB-Roundtrip pro Eval — vertretbar bei 45 Räumen.

## Verwandte ADRs / Lessons

- **AE-40** (Redis-SETNX-Lock) — neue Worker-Crash-Recovery-Sektion: explizite OOM/Container-Kill/SIGKILL/Power-Loss-Aufzählung, "selbstheilend ohne externes Cleanup".
- **CLAUDE.md §5.18** — `uuid.uuid4().hex[:8]`-Suffix in Test-Fixtures (Anlass: zu langer Layer-4-Suffix sprengte `room.number VARCHAR(20)`, kippte 7 DB-Tests).
- **CLAUDE.md §5.19** — Pflicht-Live-DB-Verify zwischen Migration und Folge-Task (Anlass: Skip-Pfad ohne `TEST_DATABASE_URL` verbarg den `String(20)`-Bug bis zum Folge-Task).
- **CLAUDE.md §5.20** — Aspirative Code-Kommentare als Doku-Drift (Anlass: `celery_app.py:60-61` versprach SETNX-Lock seit Sprint 9.6, geliefert erst 9.10 — 3 Sprints Race-Condition aktiv).

## Test-Coverage

- T1: 3 Pure-Function-Tests (Mapping)
- T2: 15 DB-Tests (Layer 4 Boundary, occupancy_state, Layer-5-Cap-Interaktion)
- T3: 2 DB-Tests (Trigger / unbekannte DevEUI)
- T3.5: 8 Pure-Function-Tests (fakeredis) + Live-Smoke (10× try_acquire, 5× evaluate_room-Burst)
- T4: 2 DOM-Marker-Beweise (positiv / negativ via `react-dom/server`)

CI-Stand bei Merge: **190 passed mit `TEST_DATABASE_URL`, 140 + 62 skipped ohne**. Mypy strict clean.

## Live-Smokes

- Vicki-Uplink mit `openWindow=true` → Engine-Decision-Panel zeigt Layer-4-Eintrag, Setpoint = MIN_SETPOINT_C (= 5 °C).
- 5× `evaluate_room.delay` parallel → 1 ok + 4 `lock_busy_retriggered` + nachfolgende Re-Trigger-Wave (siehe `backend/scripts/smoke_engine_lock.py`).

## Backlog (B-9.10-1..6)

- B-9.10-1: Notification bei Window-Open länger als X Min (occupancy_state-Feld dafür schon im Trace).
- B-9.10-2: hotel-konfigurierbares `WINDOW_STALE_THRESHOLD_MIN` via `global_config`.
- B-9.10-3: Layer-4-Activations als event_log-Eintrag (heute nur Trace).
- B-9.10-4: ❌ entfällt — durch AE-40 erledigt.
- B-9.10-5: `services/_common.py` für gemeinsame Lock-/Session-Helper.
- B-9.10-6: psycopg2 in dev-deps oder asyncpg-only-Pfad in `test_manual_override_model.py` / `test_migrations_roundtrip.py`.
