# Heizungssteuerung Hotel Sonnblick

Eigenständige, cloud-basierte Heizungssteuerung für das Hotel Sonnblick Kaprun. Steuert LoRaWAN-Thermostate (MClimate Vicki, Milesight WT102) belegungsabhängig und ersetzt das bestehende Betterspace-System.

**Status:** Sprint 9.8 abgeschlossen (Engine-Walking-Skeleton: Layer 0/1/2/5 + Hysterese fertig, Layer 3/4 offen). Sprint 9.8c (Hygiene-Sprint) abgeschlossen.

## Systeme

| Umgebung | URL | Server |
|---|---|---|
| Test | https://heizung-test.hoteltec.at | Hetzner CPX22 |
| Main | https://heizung.hoteltec.at | Hetzner CPX32 |

DNS-Hosting: Hetzner Online / konsoleH (siehe [`docs/RUNBOOK.md`](docs/RUNBOOK.md) §9). TLS via Let's Encrypt durch Caddy.

## Dokumentation

- [`STATUS.md`](STATUS.md) — Sprint-Stand, Tags, offene Punkte
- [`docs/STRATEGIE.md`](docs/STRATEGIE.md) — Strategiepapier v1.0
- [`docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`](docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md) — ADR-Log (AE-01 bis AE-38)
- [`docs/SPEC-FRAMEWORK.md`](docs/SPEC-FRAMEWORK.md) — Verbindliche Code- und Doku-Regeln
- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — 5-Phasen-Feature-Flow mit User-Gates
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — Operations, Rescue-Mode, UFW, GHCR-PAT, Domain, LoRaWAN-Pipeline
- [`docs/Design-Strategie-2.0.1.docx`](docs/Design-Strategie-2.0.1.docx) — Verbindliche UI-Richtlinie
- [`docs/features/`](docs/features/) — Feature-Briefe pro Sprint
- [`infra/deploy/SERVER-SETUP.md`](infra/deploy/SERVER-SETUP.md) — Hetzner-Setup-Anleitung

## Stack

- **Backend:** Python 3.12, FastAPI ≥0.110, PostgreSQL 16 + TimescaleDB, SQLAlchemy 2.0 (async), Celery 5.3 + Redis 5.0 (Worker + Beat-Scheduler), aiomqtt 2.3
- **Engine:** 6-Layer-Pipeline. Implementiert: Layer 0 (Sommermodus), 1 (Base), 2 (Temporal: Vorheizen + Nachtabsenkung), 5 (Hard-Clamp), Hysterese. Offen: Layer 3 (Manual-Override), Layer 4 (Window/Fenster-offen).
- **Datenmodell:** 14 SQLAlchemy-Modelle (Stammdaten, Engine, Telemetrie), 5 Migrationen (0001-0004 inkl. 0003a/b)
- **Frontend:** Next.js 14.2 (App Router), TypeScript 5.6 strict, Tailwind 3.4, Roboto + Material Symbols Outlined (selbst gehostet, DSGVO-konform), TanStack Query 5, Recharts 3
- **LoRaWAN:** ChirpStack v4 (eigener Container, eigene Postgres-Instanz), Eclipse Mosquitto v2 als MQTT-Broker, 4 MClimate-Vicki TRV im Test-Hotel-LAN gepaired
- **Edge:** Milesight UG65 Gateway (Packet-Forwarder zu ChirpStack)
- **Infrastruktur:** Hetzner Cloud (DE), 13 Compose-Services + 2 Init-Sidecars, Caddy (Reverse-Proxy + Let's Encrypt), Tailscale-VPN für SSH
- **CI/CD:** GitHub Actions, GHCR Pull-Deploy via systemd-Timer

## Lokale Entwicklung

Voraussetzungen: Docker Desktop oder Docker Engine + Docker Compose v2.

```bash
cp .env.example .env
docker compose up -d
```

Services und Ports:

| Service | URL | Hinweis |
|---|---|---|
| API | http://localhost:8000 | OpenAPI: `/docs`, ReDoc: `/redoc` |
| Web-UI | http://localhost:3000 | |
| ChirpStack | http://localhost:8080 | Login `admin` / `admin` (initial) |
| Mosquitto | tcp://127.0.0.1:1883 | Lokal anonym, ACL aktiv im Prod-Compose |
| Postgres (Heizung) | localhost:5432 | |
| Postgres (ChirpStack) | nur intern | eigenes Volume `chirpstack_db` |

Tests:

```bash
docker compose exec api pytest
```

Frontend lokal (ohne Docker):

```bash
cd frontend && npm install && npm run dev
```

LoRaWAN-Mock-Uplink testen (Pipeline-Validierung):

```bash
# Siehe infra/chirpstack/test-uplinks/README.md
docker run --rm --network heizung-sonnblick_default \
  -v "${PWD}/infra/chirpstack/test-uplinks:/data:ro" \
  eclipse-mosquitto:2 \
  mosquitto_pub -h mosquitto -p 1883 \
  -t "application/<app-id>/device/<dev-eui>/event/up" \
  -f /data/vicki-status-001.json
```

## Projektstruktur

```
backend/                  FastAPI-Anwendung, Regel-Engine, Geräte-Treiber, MQTT-Subscriber
frontend/                 Next.js Admin-UI: Devices-Liste/Detail, Zimmer mit Engine-Tab, Raumtypen, Belegungen, Hotel-Stammdaten
infra/caddy/              Caddyfiles für test + main
infra/chirpstack/         ChirpStack-Konfig, Codecs, Postgres-Init, Bootstrap-Test-Payloads
infra/mosquitto/          Mosquitto-Konfig + ACL
infra/deploy/             Production-Compose, Deploy-Skript, Server-Setup-Anleitung
docs/                     Strategiepapier, ADRs, RUNBOOK, Feature-Briefs, Working-Plans
.github/workflows/        CI/CD-Pipelines (Backend-CI, Frontend-CI, Deploy-Test, Deploy-Main)
```

## Tags und Sprints

| Tag | Sprint | Inhalt |
|---|---|---|
| `v0.1.0-baseline` | 0 | Repo-Hygiene, Playwright, Branch-Protection |
| `v0.1.1-pat-rotation` | 1 | GHCR-PAT-Rotation, RUNBOOK §6.1 |
| `v0.1.2-web-healthcheck` | 2 | `/api/health` + Dockerfile-HEALTHCHECK |
| `v0.1.3-ufw-reactivation` | 3 | UFW aktiv auf beiden Servern |
| `v0.1.4-domain-hoteltec` | 4 | Domain-Umschaltung auf hoteltec.at, Let's-Encrypt-TLS |
| `v0.1.5-lorawan-foundation` | 5 | ChirpStack + Mosquitto + MQTT-Subscriber + Sensor-Readings-API |
| `v0.1.6-hardware-pairing` | 6 | UG65-Gateway, ChirpStack-Stack, Mosquitto-MQTT-Auth, deploy-pull-Hardening, vier MClimate-Vicki gepaired, Codec produktiv |
| `v0.1.7-frontend-dashboard` | 7 | Frontend `/devices` + Detail-View mit Recharts, TanStack Query 30s-Refresh, Design-Tokens, /healthz-Trennung |
| `v0.1.8-stammdaten` | 8 | CRUD Raumtypen/Zimmer/Heizzonen/Belegungen/Hotel-Settings, Design-Strategie 2.0.1 Tokens + Buttons + ConfirmDialog |
| `v0.1.9-rc1-walking-skeleton` | 9 | Engine 6-Layer-Skelett (Layer 0/1/2/5 + Hysterese), Downlink-Adapter, Frontend Engine-Decision-Panel |

## Lizenz

Proprietär. © 2026 Hotel Sonnblick Kaprun. Siehe [`LICENSE`](LICENSE).
