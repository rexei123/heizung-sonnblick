# Status-Bericht Heizungssteuerung Hotel Sonnblick

Stand: 2026-04-21, laufender Sprint 0 (Baseline). Letzte Aktualisierung bei Sprint 0.5.

---

## 1. Was läuft produktiv

### Test-System
- **URL:** https://157-90-17-150.nip.io
- **Hetzner:** CPX22, `157.90.17.150`
- **Tailscale:** `heizung-test` = `100.82.226.57`
- **Branch:** `develop`, **GHCR-Tag:** `develop`
- **Deploy-Mode:** GHCR Pull-Deploy via systemd-Timer, 5-Min-Intervall
- **Status:** ✅ Läuft, alle Container up

### Main-System
- **URL:** https://157-90-30-116.nip.io
- **Hetzner:** CPX32, `157.90.30.116`
- **Tailscale:** `heizung-main` = `100.82.254.20`
- **Branch:** `main`, **GHCR-Tag:** `main`
- **Deploy-Mode:** Identisch zu Test (Pull-Deploy + Auto-Migration)
- **Status:** ✅ Läuft, alle Container up, Auto-Migration erfolgreich gelaufen

### Entwicklungs-Client
- **Hostname:** `work02` (Tailscale = `100.78.38.29`)
- **Git-Repo:** `C:\Users\User\dev\heizung-sonnblick`
- **SSH-Key:** `$HOME\.ssh\id_ed25519_heizung`

---

## 2. Was heute (2026-04-20) erledigt wurde

- **#17** Auto-Migration im Backend-Entrypoint (alembic upgrade head vor uvicorn)
- **#18** GHCR: GitHub Actions baut Docker-Images bei jedem Push
- **#19** Pull-basierter Deploy auf Test-Server (systemd-Timer statt SSH-Push)
- **#20** Main-Server auf gleichen Stand gebracht (Tailscale + GHCR Pull-Deploy + Auto-Migration)
- **#21** RUNBOOK.md für Troubleshooting im Repo (`docs/RUNBOOK.md`)

**Letzter Commit auf `main`:** `b5438d4` — docs: add RUNBOOK with Hetzner rescue procedures

---

## 2a. Sprint 0 Baseline (2026-04-21, laufend)

Ziel: Arbeits-Framework einführen und technische Blocker für den neuen 5-Phasen-Workflow beseitigen. Branch: `chore/sprint0-baseline`.

- ✅ **0.1 Line-Endings:** `.gitattributes` mit LF/CRLF-Regeln eingeführt — Commit `71e54b0`
- ✅ **0.2 Branch-Sync:** `develop` auf Stand `main` gezogen (content-equal, Force-Push)
- ✅ **0.3 Repo-Cleanup:** Rescue-Leftovers entfernt, `.gitignore` gehärtet — Commit `89457a2`
- ✅ **0.4 Playwright E2E:** `@playwright/test` 1.48.2, `playwright.config.ts`, 2 Smoke-Tests, neuer CI-Job `e2e` — Commit `d1a36e6`
- 🔄 **0.5 STATUS-Update:** läuft (dieser Commit)
- ⏳ **0.6 Merge & Tag:** PR `chore/sprint0-baseline → main`, CI grün, Deploy-Test Staging, Tag `v0.1.0-baseline`, Branch-Protection auf `main`

**Parallel eingeführt:**
- `docs/SPEC-FRAMEWORK.md` — verbindliche Regeln (Code, Security, DoD, Doku-Pflicht)
- `docs/WORKFLOW.md` — 5-Phasen-Feature-Flow mit expliziten User-Gates
- `docs/features/2026-04-21-sprint0-baseline.md` — Feature-Brief dieses Sprints

---

## 3. Offene Punkte (nicht blockierend, nicht kritisch)

### 3.1 Sicherheit / Hardening
- ⚠️ **PAT-Rotation nötig:** Der GitHub-PAT wurde heute im Chat exponiert. Muss neu generiert und auf beiden Servern + in GHA-Secrets aktualisiert werden. Der alte Token ist weiterhin gültig, bis er manuell widerrufen wird.
- ⚠️ **UFW auf Main deaktiviert:** Musste während der Rescue-Aktion deaktiviert werden, um Lockout zu beheben. Neu aktivieren mit RUNBOOK §8 (Reihenfolge zwingend: `ufw allow in on tailscale0` + `ufw allow 80/443` VOR `ufw enable`).

### 3.2 Operations
- ℹ️ **`web`-Container zeigt `(unhealthy)`** trotz funktionierender App (auf Test und Main). Healthcheck im Dockerfile oder docker-compose.yml muss überprüft werden. Kosmetisch, kein Funktionsproblem.
- ℹ️ **DNS-Umschaltung:** Externer IT muss `test.heizung.hotel-sonnblick.at` → `157.90.17.150` und `heizung.hotel-sonnblick.at` → `157.90.30.116` setzen. Dann auf Servern nur `PUBLIC_HOSTNAME` in `/opt/heizung-sonnblick/infra/deploy/.env` ändern und `docker compose up -d caddy` (Let's Encrypt holt sich Zertifikat automatisch).

### 3.3 Cleanup
- ✅ Rescue-Leftovers entfernt (`fix-ssh.sh`, `fix2.sh`, `setup-ssh.sh`, `erich.pub`) — Sprint 0.3, Commit `89457a2`
- ✅ Cowork-Workspace auf lokales Repo `C:\Users\User\dev\heizung-sonnblick` umgestellt (Google-Drive-Sync-Problematik eliminiert)

---

## 4. Architektur-Stand

### Backend (FastAPI + PostgreSQL/TimescaleDB)
- Domain-Model vollständig: Zimmer, Raumtypen, Gäste, Belegungen, Geräte, Events
- Alembic-Migration 0001_initial deployed auf beiden Servern
- Seed-Daten: 45 Zimmer + Raumtypen eingespielt
- Unit-Tests grün

### Frontend (Next.js 14.2 App Router + Tailwind)
- Grundgerüst mit Design-Strategie 2.0.1 (Rosé `#DD3C71`, Roboto, Material Symbols Outlined)
- AppShell mit 200 px Sidebar
- Caddy-Reverse-Proxy konfiguriert
- **Hinweis:** shadcn/ui ist derzeit **nicht** installiert. Runtime-Deps sind `next`, `react`, `react-dom`, `clsx`, `tailwind-merge`. Einführung von shadcn/ui wird separat entschieden, wenn erste Komponenten es brauchen.
- Playwright E2E eingerichtet (Smoke-Tests) + CI-Job `e2e` in `.github/workflows/frontend-ci.yml`

### Infrastruktur
- Docker Compose: api, web, postgres, redis, caddy (5 Container pro Umgebung)
- CI/CD: GitHub Actions baut Images bei Push auf `develop`/`main`, published nach GHCR
- Deploy: systemd-Timer auf Server zieht neue Images alle 5 Min
- SSH-Zugang nur über Tailscale (Public-IP als Fallback via `id_ed25519_heizung`)

---

## 5. Wichtige Dokumente im Repo

- `docs/STRATEGIE.md` — Gesamtkonzept, Architektur, Roadmap
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log
- `docs/Design-Strategie-2.0.1.docx` — UI-Richtlinie (verbindlich)
- `docs/RUNBOOK.md` — Troubleshooting, Rescue-Mode, SSH-Fehlerbilder, UFW-Hardening (NEU heute)

---

## 6. Nächste Schritte

**Unmittelbar (Abschluss Sprint 0):**
1. Sprint 0.6 — PR, CI-Grün, Staging-Smoke, Merge auf `main`, Tag `v0.1.0-baseline`, GitHub-Branch-Protection auf `main` aktivieren (User-Aktion)

**Sprint 3 (inhaltlich, nach Abschluss Sprint 0):**
1. **PAT rotieren** — Sicherheitshygiene, 10 Min Arbeit
2. **UFW auf Main re-aktivieren** nach RUNBOOK §8
3. **Healthcheck für web-Container fixen** — Next.js liefert `/api/health` oder bauen wir es
4. **LoRaWAN-Integration** starten: ChirpStack auf Milesight UG65 Gateway, erstes Pairing mit MClimate Vicki (Referenzgerät)
5. **Regel-Engine** (8 Kernregeln) implementieren — startet mit Frostschutz + belegungsabhängige Temperatur

---

## 7. Schmerzpunkte aus heute (Lessons Learned)

- Hetzner Web Console (noVNC) zerlegt `|`, `:` wegen US-Keyboard-Layout → nie für Multi-Character-Commands
- Rescue-Mode NUR mit komplettem Fix-Block (UFW + sshd_config.d + authorized_keys + fail2ban) in einem Shot, nie inkrementell
- Google Drive Sync zwischen Cowork-Workspace und Windows-Client ist unzuverlässig → Dev-Arbeit muss direkt im lokalen Git-Repo laufen
- Memory-Einträge dazu:
  - `feedback_hetzner_ops.md` — 10 Regeln für Hetzner-Operations
  - `reference_paths.md` — Cowork-Workspace-Pfad + SSH-Keys
  - `project_deploy_state.md` — aktueller Deploy-Stand

---

## 8. Zugangsdaten-Übersicht (Pfade, keine Secrets)

| Zweck | Pfad / Referenz |
|---|---|
| SSH-Key Hetzner/Tailscale | `$HOME\.ssh\id_ed25519_heizung` |
| SSH-Key GitHub | `$HOME\.ssh\id_ed25519_github` |
| Git-Repo lokal | `C:\Users\User\dev\heizung-sonnblick` |
| GHCR-Registry | `ghcr.io/rexei123/heizung-{api,web}` |
| Hetzner Cloud Console | https://console.hetzner.cloud |
| Tailscale Admin | https://login.tailscale.com/admin/machines |
| GitHub Repo | https://github.com/rexei123/heizung-sonnblick |

Secrets liegen in:
- Servern: `/opt/heizung-sonnblick/infra/deploy/.env`
- GitHub Actions: Repository Secrets
- Keine Secrets in Git, keine Secrets in diesem Bericht.
