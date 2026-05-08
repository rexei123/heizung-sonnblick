> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprintplan Sprint 8 — Stammdaten-CRUD + Belegungs-Verwaltung

**Datum:** 2026-05-02
**Phase:** 2 (Sprintplan) — freigegeben durch Master-Plan-OK + Ultra-Autonom-Modus
**Bezug:** Feature-Brief `2026-05-02-sprint8-stammdaten-belegung.md`
**Branch:** `feat/sprint8-stammdaten-belegung`
**Geschaetzte Gesamtdauer:** 10-14 h Arbeitsblock (Claude-Side)

---

## Sprint-Schnitt-Reihenfolge

Backend vor Frontend, Datenmodell vor Logik, Migration vor allem anderen. Pro Sub-Sprint: Build + Tests + Commit, kein Sammel-Push.

| # | Titel | Backend/Frontend | Schaetzung |
|---|---|---|---|
| 8.1 | Migration 0003a Stammdaten + Singleton | Backend | 90 Min |
| 8.2 | Migration 0003b event_log Hypertable | Backend | 30 Min |
| 8.3 | Models + Schemas + Seed-Erweiterung | Backend | 60 Min |
| 8.4 | API: Raumtyp + Zimmer + Heizzone CRUD | Backend | 90 Min |
| 8.5 | API: Belegung CRUD (mit Storno + Konflikt-Check) | Backend | 60 Min |
| 8.6 | API: global_config GET/PATCH | Backend | 30 Min |
| 8.7 | API: Geraet-zu-Zone Zuordnung | Backend | 30 Min |
| 8.8 | API-Integration-Tests (pytest-postgresql) | Backend | 90 Min |
| 8.9 | Frontend: Raumtypen-Seite | Frontend | 60 Min |
| 8.10 | Frontend: Zimmer-Seite + Detail-Drawer | Frontend | 90 Min |
| 8.11 | Frontend: Belegungen-Seite | Frontend | 60 Min |
| 8.12 | Frontend: Hotel-Stammdaten-Seite | Frontend | 30 Min |
| 8.13 | Playwright-E2E + Sidebar-Eintraege | Frontend | 60 Min |
| 8.14 | PR + CI + Test-Deploy + STATUS+CONTEXT-Update | Ops | 60 Min |

---

## Sprint 8.1 — Migration 0003a Stammdaten + Singleton

**Ziel:** Schema-Erweiterung deployt, Roundtrip getestet.

**Dateien:**
- `backend/alembic/versions/0003a_stammdaten_schema.py`
- `backend/src/heizung/models/season.py`
- `backend/src/heizung/models/scenario.py`
- `backend/src/heizung/models/scenario_assignment.py`
- `backend/src/heizung/models/global_config.py`
- `backend/src/heizung/models/manual_setpoint_event.py`
- `backend/src/heizung/models/__init__.py` (Imports)
- `backend/src/heizung/models/enums.py` (neue Enums: `ScenarioScope`, `ManualOverrideScope`, `EventLogLayer`)

**Schritte:**
1. Models schreiben mit allen Constraints (CHECK fuer Singleton, scope-Konsistenz, UNIQUE).
2. `alembic revision --autogenerate -m "0003a stammdaten schema"`. Manuelles Review der Migration.
3. Singleton-CHECK-Constraint per Hand setzen (autogenerate erkennt das nicht): `op.execute("ALTER TABLE global_config ADD CONSTRAINT ck_global_config_singleton CHECK (id = 1)")`.
4. Index auf `(room_id, check_in, check_out)` fuer occupancy ergaenzen (Konflikt-Check-Performance).
5. `alembic upgrade head` lokal, dann `alembic downgrade base`, dann wieder `alembic upgrade head` -> Roundtrip ok.

**Neue Tests:**
- `backend/tests/test_migrations.py` mit `test_0003a_roundtrip`. Skipt wenn keine DB verfuegbar.

**DoD:**
- [ ] Migration laeuft auf lokal frischer DB.
- [ ] Roundtrip-Test gruen.
- [ ] Models importierbar (`pytest backend/tests/test_models.py` gruen).
- [ ] Commit + Push.

**Rollback:** `alembic downgrade -1`.

---

## Sprint 8.2 — Migration 0003b event_log Hypertable

**Ziel:** event_log als TimescaleDB-Hypertable angelegt.

**Dateien:**
- `backend/alembic/versions/0003b_event_log_hypertable.py`
- `backend/src/heizung/models/event_log.py`

**Schritte:**
1. Model schreiben (PRIMARY KEY (time, room_id, evaluation_id, layer)).
2. Migration mit `op.execute("SELECT create_hypertable('event_log', 'time', chunk_time_interval => INTERVAL '7 days')")`.
3. Index `ix_event_log_room_time` (room_id, time DESC).
4. Roundtrip-Test (mit Hypertable-Cleanup im downgrade).

**DoD:** wie 8.1.
**Rollback:** `alembic downgrade -1`.

---

## Sprint 8.3 — Models + Schemas + Seed-Erweiterung

**Ziel:** Pydantic-Schemas fuer alle neuen Entitaeten + Seed-Skript fuellt Stammdaten.

**Dateien:**
- `backend/src/heizung/schemas/room_type.py`, `room.py`, `heating_zone.py`, `occupancy.py`, `season.py`, `scenario.py`, `global_config.py`, `manual_setpoint_event.py`
- `backend/src/heizung/seed.py` (erweitern, idempotent halten)

**Schritte:**
1. Pro Entitaet: `*Create`, `*Update`, `*Out` Pydantic-Modelle. Validierungen mit `@field_validator`.
2. Seed um 8 System-Szenarien (`is_system=True`, default_active gemaess Annahmen-Liste) und 1 `global_config`-Row.
3. Seed-Idempotenz-Test: zweimaliges Ausfuehren liefert gleichen DB-Stand.

**DoD:**
- [ ] Schemas validieren Edge-Cases (negative Temp, ungueltige Enum-Werte).
- [ ] Seed-Idempotenz-Test gruen.

---

## Sprint 8.4 — API: Raumtyp + Zimmer + Heizzone CRUD

**Ziel:** Backend-Endpoints fuer Stammdaten-Pflege.

**Dateien:**
- `backend/src/heizung/api/v1/room_types.py` (neu)
- `backend/src/heizung/api/v1/rooms.py` (neu)
- `backend/src/heizung/api/v1/heating_zones.py` (neu)
- `backend/src/heizung/api/v1/__init__.py` (Router-Aggregator erweitern)

**Endpoints:**
- `GET /api/v1/room-types`, `POST`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` (Verknuepfung-Check)
- `GET /api/v1/rooms`, `POST`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}` (Belegungs-Check)
- `GET /api/v1/rooms/{room_id}/heating-zones`, `POST`, `PATCH /{zone_id}`, `DELETE /{zone_id}`

**Path-Validation gemaess QA-Audit K-2:** `Path(..., gt=0, le=2_147_483_647)`.

**DoD:**
- [ ] Alle Endpoints im OpenAPI sichtbar.
- [ ] Smoke-Test: jeder Endpoint via `curl` einmal.
- [ ] Async + SQLAlchemy 2.0 Style.

---

## Sprint 8.5 — API: Belegung CRUD

**Ziel:** Belegungen anlegen, listen, stornieren. Konflikt-Check bei Ueberlapp.

**Dateien:**
- `backend/src/heizung/api/v1/occupancies.py` (neu)
- `backend/src/heizung/services/occupancy_service.py` (neu — Konflikt-Check und Status-Update)

**Endpoints:**
- `GET /api/v1/occupancies?from=&to=&room_id=&active=true`
- `POST /api/v1/occupancies`
- `GET /api/v1/occupancies/{id}`
- `PATCH /api/v1/occupancies/{id}` (nur cancel, keine Daten-Aenderung in Sprint 8 — sonst zu komplex mit Storno-Logik)
- `DELETE /api/v1/occupancies/{id}` -> 405 (nicht erlaubt). Storno via PATCH.

**Wichtig:**
- Beim POST: `room.status` updaten (RESERVED wenn check_in > NOW, OCCUPIED wenn check_in <= NOW < check_out).
- Beim Storno: `room.status` zurueck auf VACANT (wenn keine andere aktive Belegung).
- Konflikt-Check: SQL-Query auf overlap, Index-genutzt.

**DoD:**
- [ ] Konflikt-Check loest 409 aus mit klarer Fehlermeldung.
- [ ] Status-Auto-Update funktioniert.

---

## Sprint 8.6 — API: global_config GET/PATCH

**Ziel:** Hotel-Stammdaten lesen + aendern.

**Dateien:**
- `backend/src/heizung/api/v1/global_config.py` (neu)

**Endpoints:**
- `GET /api/v1/global-config` (immer Singleton, kein {id}).
- `PATCH /api/v1/global-config` (Partial-Update, mind. 1 Feld noetig).

**DoD:**
- [ ] PATCH ohne Felder -> 422.
- [ ] PATCH mit allen Feldern -> 200, alle Updates sichtbar.

---

## Sprint 8.7 — API: Geraet-zu-Zone Zuordnung

**Ziel:** Bestehende Devices-API um Zuordnungs-Endpoint ergaenzen.

**Dateien:**
- `backend/src/heizung/api/v1/devices.py` (erweitern)

**Endpoints:**
- `PATCH /api/v1/devices/{id}` bekommt optionales Feld `heating_zone_id` (NULL = loesen).

**DoD:**
- [ ] Bestehender Devices-Test bleibt gruen.
- [ ] Neuer Test fuer Zuordnung.

---

## Sprint 8.8 — API-Integration-Tests (pytest-postgresql)

**Ziel:** Erste echte HTTP+DB-Tests gemaess QA-Audit H-4.

**Dateien:**
- `backend/tests/conftest.py` (Fixture fuer Test-DB)
- `backend/tests/integration/test_room_types_api.py`
- `backend/tests/integration/test_rooms_api.py`
- `backend/tests/integration/test_occupancies_api.py`
- `backend/tests/integration/test_global_config_api.py`
- `backend/pyproject.toml` (Dev-Dep `pytest-postgresql`)

**Mindest-Coverage:** Pro Endpoint Happy + 1 Negative.

**Edge-Cases mit Tests:**
- Raumtyp loeschen mit verknuepften Zimmern -> 409
- Zimmer-Nummer doppelt -> 409
- Belegung mit check_in > check_out -> 422
- Belegung-Konflikt -> 409
- global_config-PATCH leer -> 422
- Path-Param zu gross -> 422 (gemaess K-2)

**DoD:**
- [ ] CI-Run auf `feat/sprint8-stammdaten-belegung` gruen.
- [ ] Alle 32+ neue Integration-Tests gruen lokal.

---

## Sprint 8.9-8.13 — Frontend

Reihenfolge: API-Hooks (TanStack Query) -> Pages -> Komponenten -> E2E.

### 8.9 Raumtypen-Seite

**Dateien:**
- `frontend/src/lib/api/room-types.ts` (Types + queries.ts)
- `frontend/src/lib/queries/use-room-types.ts`
- `frontend/src/app/raumtypen/page.tsx`
- `frontend/src/components/room-type-form.tsx`

**Layout:** Master-Detail. Liste links (Sidebar des Inhalts), Form rechts.

**DoD:** Vollstaendiger CRUD im Browser, mit Validierungs-Errors aus API.

### 8.10 Zimmer-Seite + Detail-Drawer

**Dateien:**
- `frontend/src/lib/api/rooms.ts`, `heating-zones.ts`
- `frontend/src/lib/queries/use-rooms.ts`, `use-heating-zones.ts`
- `frontend/src/app/zimmer/page.tsx` (Tabelle)
- `frontend/src/app/zimmer/[id]/page.tsx` (Detail mit Tabs)
- `frontend/src/components/room-form.tsx`
- `frontend/src/components/heating-zone-list.tsx`
- `frontend/src/components/device-assignment-select.tsx`

**Layout:** Tabelle mit Filter (Raumtyp, Status). Klick -> `/zimmer/[id]`. Detail mit Tabs (Stammdaten, Heizzonen, Geraete, Belegungen).

**DoD:** Tabelle paginiert ab 50 Zimmern (clientseitig reicht in Sprint 8). Tabs-Switch ohne Reload.

### 8.11 Belegungen-Seite

**Dateien:**
- `frontend/src/lib/api/occupancies.ts`
- `frontend/src/lib/queries/use-occupancies.ts`
- `frontend/src/app/belegungen/page.tsx`
- `frontend/src/components/occupancy-form.tsx`
- `frontend/src/components/occupancy-list.tsx`

**Filter:** "Heute", "Naechste 7 Tage", "Ab Datum". Default: Heute.

**DoD:** Anlegen + Stornieren funktionieren, 409-Fehler aus API werden als Toast gezeigt.

### 8.12 Hotel-Stammdaten-Seite

**Dateien:**
- `frontend/src/lib/api/global-config.ts`
- `frontend/src/lib/queries/use-global-config.ts`
- `frontend/src/app/einstellungen/hotel/page.tsx`
- `frontend/src/components/global-config-form.tsx`

**Layout:** Settings-Layout mit drei Cards (Allgemein, Standardzeiten, Alerts).

**DoD:** Form-Reset bei Cancel, Diff-Toast nach Speichern ("3 Felder aktualisiert").

### 8.13 Playwright-E2E + Sidebar-Eintraege

**Dateien:**
- `frontend/src/components/app-shell.tsx` (Sidebar erweitern)
- `frontend/tests/e2e/sprint8-stammdaten-belegung.spec.ts`

**E2E-Flow:** Raumtyp anlegen -> Zimmer mit dem Raumtyp anlegen -> Heizzone hinzufuegen -> bestehendes Geraet zuordnen -> Belegung anlegen -> Belegung stornieren -> Hotel-Stammdaten aendern.

**DoD:** Lokal gruen + auf Test-Server gruen.

---

## Sprint 8.14 — PR + CI + Test-Deploy + Doku

**Schritte:**
1. PowerShell: `git push -u origin feat/sprint8-stammdaten-belegung`
2. PR auf `develop` via `gh pr create` mit Body aus Feature-Brief Akzeptanzkriterien als Checkliste.
3. CI-Watch.
4. Merge auf `develop` -> Test-Server zieht neuen Image.
5. Smoke auf `https://heizung-test.hoteltec.at/raumtypen` etc.
6. CONTEXT.md aktualisieren ("Sprint 8 fertig auf Test, wartet auf User-Abnahme").
7. STATUS.md ergaenzen mit Sprint-8-Eintrag.
8. User-Notification: "Sprint 8 abnahme-bereit. Bitte testen und Sync-PR auf main freigeben."

---

## Pflichtuebergaben pro Sub-Sprint

- Lokaler Build gruen (`pytest backend/tests/` und `npm run build`).
- Lint sauber (`ruff check backend/src`, `npm run lint`).
- Type-Check sauber (`mypy backend/src`, `npx tsc --noEmit` im frontend).
- Commit + Push.

## Gemeinsame Konventionen

- Conventional Commits: `feat(api): add room-types CRUD endpoints`.
- Commit-Trailer NUR `Co-Authored-By: Claude` wenn ich autonom committet habe.
- Branch-Naming: `feat/sprint8-stammdaten-belegung` (kein Workaround noetig).
- API-Path-Praefix: `/api/v1/...`.
- Pydantic v2, SQLAlchemy 2.0 async.
- TanStack Query v5.
- Sprache: Deutsch im UI, Englisch im Code.

---

## Was passiert nach Sprint 8 fertig

1. Sprint 9 (Regel-Engine + Downlink) braucht Vicki-Spike-Resultat. Spike-Doku separat.
2. Sprint 10 (Saison + Szenarien + Sommermodus) baut auf den in Sprint 8 angelegten Tabellen auf.

---

*Ende Sprintplan. Beginn Phase 3 (Umsetzung) sobald User Vicki-Spike abgeschlossen hat ODER User Sprint-8-Branch-Start unabhaengig vom Spike freigibt.*
