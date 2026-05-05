# Uebergabe-Status — Heizungssteuerung Hotel Sonnblick

Stand: 2026-05-05, nach Sprint 9.8 (Engine Layer 0+1+2+5).

---

## 1. Projekt-Ueberblick

Selbststeuernde LoRaWAN-Heizungssteuerung als Ersatz fuer Betterspace im
Hotel Sonnblick. Sobald ein Hotelier eine Belegung anlegt, berechnet die
Engine den Soll-Setpoint pro Raum (Frostschutz, Vorheizen, Nachtabsenkung,
manuelle Override) und sendet einen Downlink an die mclimate-Vicki-TRVs
ueber ChirpStack/MQTT. Hotelier sieht im Web-UI die aktuellen Raum-
Setpoints, Belegungen, Stammdaten und das Engine-Decision-Panel mit dem
Layer-Trace (warum die Engine welchen Setpoint gewaehlt hat).

Hauptfunktionen: Devices/Stammdaten/Belegungen-CRUD, Engine mit 6-Layer-
Pipeline (Layer 3+4 noch offen), automatische Setpoint-Anpassung,
Engine-Audit-Log, ChirpStack-Integration, Mosquitto-MQTT-Bridge.

## 2. Tech-Stack

### Backend (`backend/`)

- **Sprache:** Python 3.12, strict Typing
- **Framework:** FastAPI >=0.110, Uvicorn[standard] >=0.27
- **DB:** PostgreSQL 16 mit TimescaleDB (`timescale/timescaledb:latest-pg16`)
- **ORM:** SQLAlchemy >=2.0, asyncpg >=0.29, Alembic >=1.13 (Migrationen)
- **Validierung:** Pydantic[email] >=2.6, pydantic-settings >=2.2
- **Worker:** Celery >=5.3 + Redis >=5.0 (Broker + Scheduler-Beat)
- **MQTT:** aiomqtt >=2.3 (Sub/Pub gegen Mosquitto)
- **HTTP:** httpx >=0.27
- **Logging:** python-json-logger >=2.0
- **Dev-Tools:** pytest >=8.0, pytest-asyncio >=0.23, ruff >=0.3, mypy >=1.9

### Frontend (`frontend/`)

- **Sprache:** TypeScript 5.6.3, strict
- **Framework:** Next.js 14.2.15 (App Router, typedRoutes)
- **React:** 18.3.1 + react-dom 18.3.1
- **State:** @tanstack/react-query 5.100.5
- **Styling:** Tailwind 3.4.14 + tailwind-merge 2.5.4
- **Charts:** recharts 3.8.1
- **Icons:** Material Symbols (Google Fonts) — keine Emojis
- **E2E:** @playwright/test 1.48.2
- **Lint:** eslint 8.57.1 + eslint-config-next 14.2.15

### Externe Services im Compose

- **ChirpStack v4** (`chirpstack/chirpstack:4`) + `chirpstack-postgres` 16-alpine
- **chirpstack-gateway-bridge:4** (Basic-Station fuer UG65)
- **Mosquitto 2** (`eclipse-mosquitto:2`) — MQTT-Broker mit Auth (passwd+ACL)
- **Redis 7-alpine** — Celery-Broker
- **Caddy 2-alpine** — Reverse-Proxy + Auto-TLS + Basic-Auth

### Lokale Werkzeuge

- **Node:** vom User-System (gepruegt 14.2.15-Build OK auf Linux-CI)
- **npm:** vom User-System
- **Python:** 3.12 in CI, lokal Sandbox 3.10 (siehe UEBERGABE-OFFENE-PUNKTE)

## 3. Projektstruktur

### Backend `backend/src/heizung/`

```
heizung/
├── api/v1/          FastAPI-Router (devices, rooms, room_types, heating_zones,
│                    occupancies, global_config, engine-trace)
├── drivers/         Codec-Wrapper (mclimate-vicki via JS-Codec)
├── models/          SQLAlchemy-ORM-Modelle (15 Tabellen)
├── rules/           Engine: 6-Layer-Pipeline + Hysterese + Defaults
├── schemas/         Pydantic-Request/Response-Schemata
├── services/        OccupancyService, MQTT-Subscriber, Downlink-Adapter
└── tasks/           Celery-Tasks (evaluate_room, evaluate_due_rooms)
```

### Frontend `frontend/src/`

```
src/
├── app/             Next.js App-Router (eine page.tsx pro Route)
│   ├── belegungen/
│   ├── devices/[device_id]/
│   ├── einstellungen/hotel/
│   ├── healthz/
│   ├── raumtypen/
│   ├── zimmer/[id]/
│   └── (root page.tsx)
├── components/
│   ├── patterns/    AppShell, RoomForm, OccupancyForm, HeatingZoneList,
│   │                EngineDecisionPanel, RoomTypeForm
│   └── ui/          Button, ConfirmDialog (kein shadcn-CLI, eigene Tokens)
└── lib/api/         API-Client, TypeScript-Typen, TanStack-Hooks
```

### Infra `infra/`

- `chirpstack/` — TOML-Templates (envsubst-rendered), Codecs (JS)
- `caddy/Caddyfile.test` + `Caddyfile.main` — Reverse-Proxy-Konfig pro Stage
- `mosquitto/config/` — Production-Konfig mit Auth-User
- `deploy/` — `docker-compose.prod.yml`, `.env.example`, `deploy-pull.sh`

## 4. Datenmodell

SQLAlchemy 2.0 Models (kein Prisma — Backend-Stack ist Python). Tabellen
unter `backend/src/heizung/models/`:

- **device** — Vicki-TRV oder anderer LoRaWAN-Sensor mit DevEUI, Status, Heating-Zone-Bezug
- **heating_zone** — Logische Heizgruppe innerhalb eines Raums (z.B. Wand-Heizkoerper Sued)
- **room** — Hotelzimmer mit Status (vacant/reserved/occupied/cleaning/blocked), `last_evaluated_at`, `next_transition_at`
- **room_type** — Raumkategorie (Doppelzimmer, Suite, Bad) mit Default-Setpoints
- **occupancy** — Belegung mit check_in/check_out, is_active, optionaler Gast-Info
- **rule_config** — Regelparameter auf 3 Scopes (GLOBAL, ROOM_TYPE, ROOM) + Saison
- **global_config** — Singleton (id=1) fuer Hotel-weite Settings (Sommermodus, Timezone)
- **manual_setpoint_event** — Gast/Personal-Override mit Ablauf (Layer 3, noch nicht in Engine eingehaengt)
- **scenario** + **scenario_assignment** — Szenarien-Geruest fuer Sprint 10 (noch nicht aktiv)
- **season** — Saison-Definitionen (z.B. Winter/Sommer-Saetze) — Sprint 10
- **sensor_reading** — Hypertable, alle Vicki-Uplinks (Temperatur, Batterie, Valve-Position)
- **event_log** — Hypertable, ein Eintrag pro Engine-Layer-Schritt (Audit + KI-Vorbereitung)
- **control_command** — Versendeter Setpoint pro Device, mit Reason + Hysterese-Kontext
- **enums** — Enum-Definitionen fuer Status/Layer/Reason (kein Tabelle, nur Code)

Migrationen: `backend/alembic/versions/` — aktuell `0004_room_eval_timestamps.py`.

## 5. Routen-Uebersicht

### Frontend-Pages (User-facing)

- `/` — Dashboard-Startseite
- `/zimmer` — Tabelle aller Zimmer mit Filter
- `/zimmer/[id]` — Zimmer-Detail mit Tabs (Stammdaten, Belegungen, Engine, Devices)
- `/raumtypen` — Master-Detail-CRUD fuer Raumtypen
- `/belegungen` — Belegungen-Liste + Form
- `/einstellungen/hotel` — Hotel-weite Settings (global_config)
- `/devices` — Geraeteliste
- `/devices/[device_id]` — Geraete-Detail mit Reading-Chart
- `/healthz` — Frontend-Healthcheck (kein User-Inhalt, fuer Caddy/Compose)

### Backend-API-Endpoints (`/v1/...`)

- `/v1/devices/*` — CRUD Devices, GET `/uplinks` fuer Reading-History
- `/v1/rooms/*` — CRUD Rooms, GET `/engine-trace` fuer Layer-History (Sprint 9.4-5)
- `/v1/room-types/*` — CRUD Raumtypen
- `/v1/heating-zones/*` — CRUD Heating-Zones + Device-Zuordnung
- `/v1/occupancies/*` — CRUD Belegungen + Auto-Status-Update via OccupancyService
- `/v1/global-config` — GET/PATCH Hotel-weite Settings
- `/healthz` — Backend-Healthcheck

## 6. Authentifizierung

**Status Sprint 9:** Aktuell **Single-Tenant Hotel-Setup** ohne User-Konten.

- **Caddy Basic-Auth** (`HOTEL_BASIC_AUTH_HASH` in `.env`, bcrypt) schuetzt
  `/api/*`, `/openapi.json`, `/docs` (siehe `infra/caddy/Caddyfile.{test,main}`).
  Wirkt fuer Hotel-Mitarbeiter als Single-Sign-On vor dem gesamten Backend.
- **Frontend** ist hinter dem gleichen Basic-Auth-Vorwall (Tab im Browser
  bleibt offen).
- **ChirpStack-UI** (`cs-test.hoteltec.at`) eigene Basic-Auth via
  `CHIRPSTACK_BASIC_AUTH_HASH`.
- **MQTT** (`mosquitto.prod.conf`): drei User mit ACL — `chirpstack` (publish),
  `gateway-ug65` (publish) und `heizung-api` (subscribe) — Passwoerter in `.env`.
- **NextAuth ist NICHT eingebaut.** Rollen-System (Admin/Personal/Gast) steht
  als Sprint 11+ im Backlog (siehe `docs/working/2026-05-02-master-plan-...md`).

Berechtigung im Backend-Code: derzeit KEINE Per-Endpoint-Pruefung. Vertraut
dem Caddy-Wall. Bei Multi-Tenant-Erweiterung muss das nachgezogen werden
(siehe UEBERGABE-SCHULDEN.md).

## 7. Externe Dienste

- **ChirpStack v4** (selbst gehostet) — LoRaWAN-Network-Server
- **mclimate Vicki TRV** (Hardware) — LoRaWAN-Thermostatventil
- **Milesight UG65** (Hardware) — LoRaWAN-Gateway via Basic Station
- **Open-Meteo** (`api.open-meteo.com`) — Wetter (kein API-Key noetig,
  Lat/Lon in `.env`)
- **Hetzner Cloud** — Hosting (zwei CPX22-VMs heizung-test, heizung-main)
- **Hetzner DNS Console** (konsoleH) — Authoritative NS fuer hoteltec.at
- **GitHub** (`rexei123/heizung-sonnblick`) — Repo + Actions + GHCR
- **Tailscale** — VPN-Mesh, MagicDNS fuer SSH-Hostnames

### Zugangsdaten-Pfade (KEINE Werte hier)

- Server-`.env`: `/opt/heizung-sonnblick/infra/deploy/.env` (auf beiden Servern)
- Caddy-Volumes: `caddy_data` (Cert-Cache, persistent)
- DB-Volume: `db_data` (`/var/lib/postgresql/data` im db-Container)
- ChirpStack-DB-Volume: `chirpstack_db`
- SSH-Key lokal: `$HOME\.ssh\id_ed25519_heizung` (zwingend `-i`-Flag)
- GitHub-PAT lokal: in `gh auth status` hinterlegt
- GHCR-Pull-Secret: `~/.docker/config.json` auf den Servern (durch
  `docker login ghcr.io` mit Classic-PAT eingerichtet)
- Mosquitto-Passwort-File: in Volume `mosquitto/config/passwd`

## 8. Deploy-Setup

### Umgebungen

| Stage | Domain | Server (Tailscale) | Branch | Image-Tag |
|-------|--------|-------------------|--------|-----------|
| Test | `heizung-test.hoteltec.at` | `heizung-test` | `develop` | `:develop` |
| Main | `heizung.hoteltec.at` | `heizung-main` | `main` | `:develop` (sic — wird in Sprint 10+ auf `:main` umgestellt) |

ChirpStack-UI nur auf Test: `cs-test.hoteltec.at` (Basic-Auth davor).

### Deploy-Pipeline (Pull-basiert)

1. **PR auf `develop`** → Backend-CI + Frontend-CI laufen
2. **Merge** → `build-images.yml` baut `heizung-api` + `heizung-web` und pusht
   nach GHCR mit Tags `:develop` und `:develop-<sha7>`
3. **Server-Timer** `heizung-deploy-pull.timer` (alle 5 Min) ruft
   `/usr/local/bin/deploy-pull.sh` auf — `git fetch + reset --hard` plus
   `docker compose pull && up -d`
4. Caddy macht Auto-TLS + Reverse-Proxy + Basic-Auth

Manueller Deploy (nach Merge): `gh workflow run build-images.yml --ref develop`
+ `docker compose pull && docker compose up -d --force-recreate <service>`.

### Compose-File

`infra/deploy/docker-compose.prod.yml` (zwingend `-f` beim compose-Aufruf).
Services: `db`, `redis`, `mosquitto`, `chirpstack-postgres`, `chirpstack-init`,
`chirpstack-gateway-bridge-init`, `chirpstack-gateway-bridge`, `chirpstack`,
`api`, `celery_worker`, `celery_beat`, `web`, `caddy`.

### Backup

PostgreSQL-Dump aktuell **manuell** ueber `docker exec deploy-db-1 pg_dump`.
Letzter Backup: `/opt/heizung-backup/heizung-20260504-0541.sql.gz` (30 KB,
gzip-OK). Cronjob noch nicht eingerichtet (Backlog H-8 / Off-Site-Backup).
