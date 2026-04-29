# Claude-Kontext Heizungssteuerung Hotel Sonnblick

Dieses File wird automatisch geladen. Lies es **vor jeder Aktion** im Repo.

## 1. Identität & Stand

- **Projekt:** Heizungssteuerung für Hotel Sonnblick (Mandatar: hotelsonnblick@gmail.com)
- **Repo:** https://github.com/rexei123/heizung-sonnblick (public)
- **Lokales Working Copy:** `C:\Users\User\dev\heizung-sonnblick` (synced mit Cowork-Mount)
- **Aktueller Sprint:** **Sprint 6 in Arbeit** (Hardware-Pairing). Server-Stack vorbereitet, Pairing 2026-04-29 mit IT-Mitarbeiter geplant.
- **Letzter Tag:** `v0.1.5-lorawan-foundation`
- **Pairing-Tagesplan:** `docs/working/sprint6-pairing-anleitung.md` (zuerst lesen am Pairing-Tag!)
- **Produktivumgebungen:** `https://heizung.hoteltec.at` (Main), `https://heizung-test.hoteltec.at` (Test)

## 2. Pflicht-Lektüre vor Sprint-Arbeit

In dieser Reihenfolge:

1. `STATUS.md` — Gesamtstand, alle Sprints, aktuelle URLs, Tags
2. `docs/SPEC-FRAMEWORK.md` — verbindliche Code- und Doku-Regeln
3. `docs/WORKFLOW.md` — 5-Phasen-Feature-Flow mit User-Gates
4. `docs/RUNBOOK.md` — Operations, Rescue, UFW, GHCR-PAT, Domain
5. `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log
6. `docs/working/sprint5-execution-plan.md` — **wenn Sprint 5 läuft**

## 3. Goldene Regeln

1. **5-Phasen-Workflow:** Brief → Sprintplan → User-Gate → Execution → Tag. Keine Schritte überspringen.
2. **Branch-Naming:** `feat/sprintN-<slug>` für Features, `chore/<slug>` für Wartung, `fix/<slug>` für Bugs.
3. **Tag-Pattern:** `v0.<minor>.<sprint>-<slug>` (z. B. `v0.1.5-lorawan-foundation`).
4. **Commit-Trailer:** `Co-Authored-By: Claude` nur wenn explizit gewünscht.
5. **Doku-Pflicht:** Jeder Sprint hat einen Feature-Brief in `docs/features/YYYY-MM-DD-sprintN-<slug>.md`. STATUS.md wird am Ende jedes Sprints ergänzt.
6. **Sprache:** Deutsch, Sie-Form, sachlich.
7. **Befehl-Markierung:** Jeden Befehl explizit als **PowerShell (lokal)** oder **SSH (Server)** kennzeichnen.
8. **Kritisches Denken:** Bei besseren Alternativen widersprechen. Nicht Ja-Sager sein.
9. **Kein Schreiben in main/develop direkt:** Branch-Protection ist aktiv, immer über PR.
10. **Cowork-Mount = Windows-Repo:** Edits in `/sessions/.../mnt/heizung-sonnblick/` landen direkt in `C:\Users\User\dev\heizung-sonnblick\`.

## 4. Operations-Highlights

- **SSH-Key:** `$HOME\.ssh\id_ed25519_heizung` (zwingend `-i ...`-Flag, Default-Key passt nicht)
- **Server-Hostnames:** `heizung-test`, `heizung-main` (Tailscale MagicDNS)
- **Container-Stack:** api, web, db (timescaledb), redis, caddy — Compose-File: `docker-compose.prod.yml` (zwingend `-f`)
- **Deploy:** GHCR Pull über systemd-Timer (5 Min), KEIN Push-Deploy
- **DNS:** Hetzner Online (konsoleH), NS `ns1.your-server.de`/`ns.second-ns.com`/`ns3.second-ns.de` — NICHT Hetzner Cloud DNS
- **UFW:** aktiv auf beiden Servern, Port 22/80/443 + tailscale0 erlaubt
- **PAT-Type:** Classic PAT (Fine-grained unterstützt GHCR nicht)

## 5. Aktuelle Backlog-Punkte

- Caddy `fmt --overwrite` (kosmetisch, mit Sprint 6 wenn Caddy-Touch fuer ChirpStack-UI ohnehin)
- `~/.ssh/config`-Eintraege auf work02
- Caddy: `/_health` als oeffentlicher Health-Endpoint trennen vom internen `/api/*`-Routing
- CI-Mirror-Workflow `frontend-ci-skip.yml` aufraeumen, wenn Branch-Protection-Matcher smarter wird
- ChirpStack-Bootstrap-Skript (Tenant + App + DeviceProfile + Codec) fuer reproduzierbares Setup nach `docker compose down -v` (Sprint 6 oder spaeter)
- `.github/CODEOWNERS` einrichten, wenn weitere Mitwirkende dazukommen
