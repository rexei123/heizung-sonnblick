# Heizungssteuerung Hotel Sonnblick

Eigenständige, cloud-basierte Heizungssteuerung für das Hotel Sonnblick Kaprun. Steuert LoRaWAN-Thermostate (MClimate Vicki, Milesight WT102) belegungsabhängig und ersetzt das bestehende Betterspace-System.

**Status:** Sprint 1 · Infrastruktur im Aufbau

## Systeme

| Umgebung | URL | Server |
|---|---|---|
| Test | https://test.heizung.hotel-sonnblick.at | Hetzner CX22 |
| Main | https://heizung.hotel-sonnblick.at | Hetzner CX32 |

## Dokumentation

- [`docs/STRATEGIE.md`](docs/STRATEGIE.md) — Vollständiges Strategiepapier v1.0
- [`docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`](docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md) — Architektur-Entscheidungen
- [`docs/Design-Strategie-2.0.1.docx`](docs/Design-Strategie-2.0.1.docx) — Verbindliche UI-Richtlinie (Patch-Änderungen als Änderungsnachverfolgung)
- [`docs/CHANGELOG-Design-Strategie.md`](docs/CHANGELOG-Design-Strategie.md) — Was sich von v2.0 zu v2.0.1 geändert hat
- [`infra/deploy/SERVER-SETUP.md`](infra/deploy/SERVER-SETUP.md) — Schritt-für-Schritt-Anleitung für Hetzner-Setup

## Stack

- **Backend:** Python 3.12, FastAPI, PostgreSQL 16 + TimescaleDB, SQLAlchemy 2.0, Celery + Redis
- **Frontend:** Next.js (App Router), TypeScript, Tailwind + shadcn/ui, Roboto, Material Symbols
- **Edge:** Milesight UG65 Gateway (ChirpStack + Node-RED)
- **Infrastruktur:** Hetzner Cloud (DE), Docker Compose, Caddy (Reverse-Proxy + Let's Encrypt)
- **CI/CD:** GitHub Actions

## Lokale Entwicklung

Voraussetzungen: Docker, Docker Compose.

```bash
cp .env.example .env
docker compose up -d
```

- API: http://localhost:8000 · OpenAPI-Doku: http://localhost:8000/docs
- Web-UI: http://localhost:3000

Tests:

```bash
docker compose exec api pytest
```

Frontend lokal (ohne Docker):

```bash
cd frontend && npm install && npm run dev
```

## Projektstruktur

```
backend/           FastAPI-Anwendung, Regel-Engine, Geräte-Treiber
frontend/          Next.js Admin-UI (Grundgerüst steht, Features folgen in Sprint 2)
infra/caddy/       Caddyfiles für test + main
infra/deploy/      Production-Compose, Deploy-Skript, Server-Setup-Anleitung
docs/              Strategiepapier, Architektur-Entscheidungen, Design-Strategie
.github/workflows/ CI/CD-Pipelines (Backend, Frontend, Deploy-Test, Deploy-Main)
```

## Lizenz

Proprietär. © 2026 Hotel Sonnblick Kaprun. Siehe [`LICENSE`](LICENSE).
