> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprint 9.9 — Manual-Override (Engine Layer 3)

**Datum:** 2026-05-06
**Branch:** `feat/sprint9-9-manual-override`
**PR:** #97
**Tag:** keiner — Final-Tag `v0.1.9-engine` kommt nach Sprint 9.10–9.12.

## Ziel
Engine berücksichtigt manuelle Setpoint-Übersteuerungen aus zwei
Quellen mit definierten Ablaufzeiten und Sicherheitsnetzen. Quelle
und Hardware sind via Adapter-Schicht abstrahiert — Engine kennt
nur generische Override-Records (siehe AE-39).

## Annahmen
- Vicki-Codec liefert nur `target_temperature` (uint8 in Periodic, decimal in Setpoint-Reply) — keine Quellen-Unterscheidung.
  → Diff-Strategie gegen `ControlCommand` mit Toleranz-Modi.
- `global_config.default_checkout_time` (existierend, default `11:00`) und `timezone` (default `Europe/Vienna`).
- Hotelleitung-Hard-Override ist Sprint 10+; Sprint 9.9 deckt nur Drehknopf + Rezeption.
- Setpoint Decimal(4,1), nie Float.

## Tasks T1–T10

| Task | Beschreibung | Branch-Commit |
|---|---|---|
| T1 | Datenmodell + Alembic-Migration `0008_manual_override` | `2ba7693` |
| T2 | `services/override_service` Domain-Logik (8 Funktionen) | `d1bb99e` |
| T3 | Engine Layer 3 in `rules/engine.py` + Pipeline-Integration | `bdb2af7` |
| T4 | REST-API `/api/v1/rooms/{id}/overrides` und `/api/v1/overrides/{id}` | `534d708` |
| T5 | `services/device_adapter` Diff-Detection + `mqtt_subscriber`-Hook | `a3e32aa` |
| T6 | `services/override_pms_hook` Auto-Revoke beim Auszug | `cc09a34` |
| T7 | `tasks/override_cleanup_tasks` Daily-Cleanup-Job (`crontab(hour=3, minute=0)`) | `d3274d7` |
| T8 | Frontend Override-UI auf `/zimmer/[id]` (5. Tab „Übersteuerung") | `e5aed26` |
| T9 | Engine-Decision-Panel um Layer-3-Anzeige erweitert | siehe T10-Commit |
| T10 | Doku, AE-39, STATUS.md, CLAUDE.md, PR-Merge | siehe Merge-Commit |

(Plus mehrere `fix:`/`chore:`-Commits für ruff-Format-Hygiene, siehe PR-History.)

## Datenmodell

```
room (existing)
  ├── manual_override (neu, Sprint 9.9)
  │     id BIGINT PK
  │     room_id BIGINT FK -> room.id ON DELETE CASCADE
  │     setpoint NUMERIC(4,1)
  │     source VARCHAR(30) CHECK in (device|frontend_4h|frontend_midnight|frontend_checkout)
  │     expires_at TIMESTAMPTZ
  │     reason TEXT
  │     created_at TIMESTAMPTZ
  │     created_by VARCHAR(255)
  │     revoked_at TIMESTAMPTZ NULL
  │     revoked_reason VARCHAR(500) NULL
  │     INDEX (room_id, created_at) WHERE revoked_at IS NULL
  │
  └── occupancy (existing, gelesen via next_active_checkout/checkin)
```

## Adapter-Pattern (siehe AE-39)

```
[Vicki Uplink, fPort 1/2]                    [Frontend Form, /zimmer/[id]]
        │                                              │
[mqtt_subscriber]                            [api/v1/overrides POST]
        │                                              │
[device_adapter.handle_uplink_for_override]            │
        │                                              │
        └──────────► [override_service.create] ◄───────┘
                              │
                       manual_override (DB)
                              │
                  ┌───────────┴───────────────┐
[engine.layer_manual_override]      [override_service.get_history]
[engine.evaluate_room]              [REST GET /api/v1/rooms/{id}/overrides]
                              │
                       Setpoint-Stack + EventLog (Layer-3-Eintrag mit extras)
```

## Override-Quellen + Default-Ablauf

| Quelle | Trigger | Default-Ablauf | Toleranz (Diff) |
|---|---|---|---|
| `device` | Vicki-Uplink mit `target_temperature` ≠ letzter ControlCommand | bis Check-Out aus PMS, sonst `now + 7 d` | 0.6 °C (fPort 1) / 0.1 °C (fPort 2) |
| `frontend_4h` | Rezeption setzt im UI „Für 4 Stunden" | `now + 4 h` | — |
| `frontend_midnight` | Rezeption setzt „Bis Mitternacht" | heute 23:59 lokal (`global_config.timezone`) | — |
| `frontend_checkout` | Rezeption setzt „Bis Check-Out" | `next_active_checkout(room)` (422, wenn keine aktive Belegung) | — |

## Sicherheitsnetze

- **7-Tage-Hard-Cap:** alle `expires_at` werden auf `now + 7 d` gekappt; Cap-Event wird in `logger.warning` festgehalten (event_log-Wrapper Backlog).
- **PMS-Auto-Revoke:** `OCCUPIED → VACANT` ohne Folgegast in 4 h → `override_service.revoke_device_overrides` (nur `source=device`, Frontend bleibt).
- **Daily-Cleanup:** celery_beat-Task `heizung.cleanup_expired_overrides` 03:00 UTC setzt `revoked_at = expires_at` für alle abgelaufenen, `revoked_reason = "auto: expired"`. Records bleiben für Audit.
- **Acknowledgment-Window (60 s):** Vicki-Reply innerhalb 60 s nach `sent_to_gateway_at` ist erwarteter Engine-Ack, kein Override.

## Test-Coverage

| Modul | Tests | Anmerkung |
|---|---|---|
| `manual_override`-Modell | 7 (DB) + 16 (Pydantic) | T1, skip ohne `TEST_DATABASE_URL` |
| `override_service` | 8 (pure) + 11 (DB) | T2 |
| Engine Layer 3 | 5 (DB) | T3 |
| REST-API | 8 (httpx.AsyncClient + DB) | T4 |
| `device_adapter` | 8 (DB) | T5 |
| `override_pms_hook` | 5 (DB) | T6 |
| `override_cleanup_tasks` | 2 (DB) | T7 |
| Frontend | manuelle Live-QA (T10) | T8/T9 |

CI-Stand zum Sprint-Abschluss: **Mypy 60 source files clean, 152 passed + 27 skipped (DB-Tests in CI alle aktiv), Coverage 67 %.**

## Bekannte Backlog-Punkte

- **`services/event_log`-Wrapper** für strukturierte Cap-/Revoke-Events außerhalb der Engine-Pipeline (heute nur `logger.warning`).
- **`tasks/_session.py`** als gemeinsame `_task_session`-Quelle (aktuell in `engine_tasks.py` und `override_cleanup_tasks.py` dupliziert).
- **`acknowledged_at`-Population** in `mqtt_subscriber` für Setpoint-Reply (fPort 2, 0x52) — heute nur Logged.
- **Mobile-Tab-Layout:** 5 Tabs auf `/zimmer/[id]` brauchen auf schmalen Screens ggf. Wrap/Scroll.
- **`apiClient.delete`-Body:** Frontend sendet `revoked_reason` aktuell nicht mit; Hotel-driven-Reason im Aufhebe-Dialog ist Sprint-10+-Erweiterung.
- **Casablanca-PMS-Polling:** existiert noch nicht; aktueller Hook in `sync_room_status` deckt nur den API-Pfad. Sprint 10+.

## Live-QA

T10-Smoke-Test nach Merge:
- `https://heizung-test.hoteltec.at/healthz` 200
- `GET /api/v1/rooms/1/overrides` returnt Liste
- Frontend `/zimmer/1` zeigt 5. Tab „Übersteuerung"; Anlage `frontend_4h` ergibt sofort Engine-Decision-Panel-Eintrag mit Layer-3-Source-Badge.
