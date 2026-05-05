# Uebergabe — technische Schulden

Stand: 2026-05-05, nach Sprint 9.8.

Ehrliche Sammlung ohne Priorisierung. Bewertung erfolgt extern.

---

## 1. Type-Suppressions

### TypeScript

- `@ts-nocheck`: **0 Vorkommen**
- `@ts-ignore`: **0 Vorkommen**
- `eslint-disable`: **0 Vorkommen**
- `any`-Types in TypeScript: **0 Vorkommen** (TanStack-Hooks und API-Client durchgaengig typisiert; die Schemas in `frontend/src/lib/api/types.ts` sind handgepflegt aus Pydantic-Schemata, kein Generator)

### Python

- `# type: ignore[*]`: **5 Vorkommen** (siehe Detail unten)
- `# noqa: B008`: ~30 Vorkommen, alle in `backend/src/heizung/api/v1/*.py`
  fuer FastAPI-`Depends(...)` / `Query(default=...)` / `Path(...)` —
  Library-Pattern, nicht vermeidbar
- `# noqa: ARG001`: 2 Vorkommen in `tasks/engine_tasks.py` fuer `bind=True`
  Celery-Tasks (self wird nicht genutzt, ist aber Pflicht)
- `# noqa: N815`: 5 Vorkommen in `services/mqtt_subscriber.py` fuer
  ChirpStack-camelCase-Felder (`devEui`, `fCnt`, `fPort`, `rxInfo`,
  `deviceInfo`)

### Detail `# type: ignore`

| Datei | Zeile | Kommentar |
|---|---|---|
| `backend/tests/test_engine_skeleton.py` | 96 | `_RoomContext(...)  # type: ignore[arg-type]` — Test-Helper instanziiert mit Mock-Objekten |
| `backend/tests/test_downlink_adapter.py` | 62 | `build_downlink_message(21.5, "00")  # type: ignore[arg-type]` — gewollt falscher Aufruf zur Validierungspruefung |
| `backend/tests/test_config.py` | 50 | `Settings(_env_file=None)  # type: ignore[call-arg]` — pydantic-settings Private-API |
| `backend/tests/test_config.py` | 59 | `Settings(environment="prod")  # type: ignore[arg-type]` — gewollt invalider Wert fuer Validation-Test |
| `backend/src/heizung/config.py` | 92 | `return Settings()  # type: ignore[call-arg]` — pydantic-settings laedt Felder aus ENV, mypy sieht das nicht |

### Mypy-Override

- `pyproject.toml [[tool.mypy.overrides]]` mit
  `disable_error_code = ["untyped-decorator"]` fuer `heizung.celery_app`
  + `heizung.tasks.*` — Celery-Decorators haben keine Type-Stubs.
  Dokumentiert in Sprint 9.8a.

---

## 2. TODO/FIXME-Kommentare

`grep -rE "(TODO|FIXME)" backend/src frontend/src` liefert **0 Treffer**.

Hinweis: Backlog-Items werden im Repo NICHT als TODO im Code gefuehrt,
sondern in `STATUS.md` und `CLAUDE.md` §6 "Aktuelle Backlog-Punkte".

---

## 3. Auffaelligkeiten

### Datei > 500 Zeilen

| Datei | Zeilen |
|---|---|
| `backend/src/heizung/rules/engine.py` | 508 |

Engine waechst pro Layer um 60-100 Zeilen — nach Layer 3+4 (Sprint 9.9)
ueber 700 Zeilen. Auftrennung in `engine/` mit
`layer_summer.py / layer_base.py / layer_temporal.py / layer_clamp.py`
+ `engine.py` als Pipeline-Orchestrator ist als Refactoring-Kandidat im
Backlog (noch nicht Sprint-eingeplant).

### Doppelte Funktionsnamen / Logik

`grep`-basierte Heuristik in `services/` + `rules/`: **keine Duplikate**.

Im `engine.py` existieren `_resolve_t` (alt, nur Decimal) und
`_resolve_field` (neu, generisch). `_resolve_t` ist semantisch ein
Spezialfall von `_resolve_field`. Konsolidierung waere moeglich, ist
aber funktional nicht falsch.

### Komponenten ohne Typen

Alle Frontend-Komponenten unter `frontend/src/components/` sind
TypeScript mit explizitem Props-Interface. Keine `any` und keine
fehlenden Props-Types gefunden.

### API-Routen ohne Input-Validierung (Pydantic)

Alle `backend/src/heizung/api/v1/*.py` importieren ihre Request-Schemata
aus `heizung.schemas.*`. Beispiel (devices.py):

```
from heizung.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate
```

`heizung.schemas.*` sind alle `pydantic.BaseModel`. Damit ist
Input-Validierung durchgaengig vorhanden. **Keine Routen ohne Schema.**

### API-Routen ohne Auth-Check

**ALLE Routen** haben aktuell **keinen** per-Endpoint-Auth-Check (kein
NextAuth, kein FastAPI-`Depends(get_current_user)`). Schutz erfolgt
ausschliesslich ueber **Caddy Basic-Auth** (`HOTEL_BASIC_AUTH_HASH`)
auf `/api/*`, `/openapi.json`, `/docs` (siehe `Caddyfile.{test,main}`).

Konsequenz: Multi-Tenant-Faehigkeit aktuell nicht moeglich, jeder
Hotel-Mitarbeiter mit Basic-Auth-Login hat Vollzugriff. Sprint 11+
(Backlog) plant NextAuth oder FastAPI-Native-Auth.

---

## 4. Standard-Bausteine

### Tests

- **Backend:** 10 Test-Dateien unter `backend/tests/test_*.py`
  - `test_celery_app.py`, `test_codec_vicki.py`, `test_config.py`,
    `test_devices_api.py`, `test_downlink_adapter.py`,
    `test_engine_skeleton.py`, `test_migrations_roundtrip.py`,
    `test_models.py`, `test_mqtt_subscriber.py`, `test_uplinks_api.py`
  - Letzter CI-Run gruen (Backend-CI auf develop, PR #81)
  - 103 + Vorheizen-Layer-Tests = ~112 Test-Cases (genaue Anzahl im
    pytest-Output nach Lokal-Setup)
- **Frontend:** 3 Playwright-Spec-Files unter `frontend/tests/e2e/`
  - `devices.spec.ts`, `smoke.spec.ts`, `sprint8.spec.ts`
  - Smoke-Tests, kein integratives CRUD gegen echte API
  - CI-Run via `frontend-ci.yml` (e2e-Job)

### README

- **Vorhanden:** `README.md` (4824 Bytes)
- **Status:** veraltet — Stand "Sprint 6 in Arbeit" (aktuell Sprint 9.8)
- **Aktualisierungs-Backlog:** ja, sollte Sprint-9-Ende eingebaut werden

### .env.example

- **Vorhanden:** `infra/deploy/.env.example` (zentrale Compose-Konfig)
- **Backend separat:** kein eigener `backend/.env.example` — Backend-ENV
  kommt durch `infra/deploy/.env` via Compose `env_file:`
- **Vollstaendigkeit:** alle ENV-Variablen aus Production stehen drin,
  mit Platzhaltern (`__bitte-aendern__`) und Kurzkommentaren

### CI-Pipeline

`.github/workflows/`:

- `backend-ci.yml` — ruff lint + ruff format-check + mypy + pytest
- `frontend-ci.yml` — eslint + tsc --noEmit + next build + playwright e2e
- `frontend-ci-skip.yml` — Skip-Mirror fuer Branch-Protection wenn keine
  Frontend-Aenderungen (siehe Backlog "frontend-ci-skip aufraeumen")
- `build-images.yml` — baut + pusht `heizung-api` + `heizung-web` nach GHCR

### Backup-System

- **Manuell** moeglich via `docker exec deploy-db-1 pg_dump`
- **Letzter Backup:** `/opt/heizung-backup/heizung-20260504-0541.sql.gz`
  (30 KB, gzip-Integritaet OK, Sprint 9.7-Vorbereitung)
- **Cronjob/Timer:** **NICHT eingerichtet**
- **Off-Site-Replikation:** **NICHT eingerichtet**
- **Backlog:** H-8 ("Off-Site DB-Backup") + TimescaleDB-spezifisches Tool
  (siehe `CLAUDE.md` §6)
