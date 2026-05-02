# CONTEXT — Heizungssteuerung Hotel Sonnblick

**Boot-Anker fuer KI-Sessions.** Lies das ZUERST. Dann erst CLAUDE.md, dann Sprint-spezifische Doku.
**Halte das File schlank** (Ziel < 100 Zeilen). Alte Sprints kommen NICHT hierher — die stehen in STATUS.md.
**Pflicht:** Am Ende jedes Sprints aktualisieren. Wenn das nicht passiert ist, ist der Sprint nicht "Done".

---

## Aktueller Stand

- **Letzter Tag:** `v0.1.7-frontend-dashboard` (2026-05-01)
- **Letzter Sprint abgeschlossen:** Sprint 7 Frontend-Dashboard + Sprint 8a (K-1 Caddy-Basic-Auth interim)
- **Aktiver Sprint:** Sprint 8 — Stammdaten-CRUD + Belegung (Brief + Sprintplan freigegeben am 2026-05-02)
- **Branch:** `feat/sprint8-stammdaten-belegung` (noch nicht erstellt zum Stand 2026-05-02)
- **Vor Sprint-9-Start zwingend:** Vicki-Setpoint-Downlink-Spike (siehe `docs/working/2026-05-02-vicki-downlink-spike.md`)

## Was JETZT der naechste konkrete Schritt ist

1. ✅ Vicki-Spike 2026-05-02 vollstaendig validiert (10:41 Test 21.5°, 11:06 Test 22.0°). Pipeline End-to-End funktioniert. Vicki Hardware-Limit: nur 1° Aufloesung (rundet 21.5 auf 21.0 intern). Periodic Report (fPort 1) zeigt aktuellen Setpoint im Frontend.
2. **Sprint-9-Architektur-Annahmen:** Engine quantisiert Setpoint auf ganze Grad mit `int(round(x))`. AE-32 Hysterese auf 1.0 °C statt 0.5 °C (ADR-Update mit Sprint-9-Brief). Backend nutzt Periodic Report fuer Setpoint-Ack — kein fPort-2-Codec noetig.
3. Sprint 8 Code-Arbeit laeuft: 8.1 Models fertig + verifiziert. Naechster Schritt: 8.2 Migration 0003a + 0003b.
4. Codec-Backlog: Task #86 (Vicki-Ventil 213-242% statt 0-100%), Task #87 (fPort 2 Setpoint-Reply nice-to-have). Beide nicht-blockierend.

## Architektur-Konsens (Stand 2026-05-02)

- **Master-Plan freigegeben:** `docs/working/2026-05-02-master-plan-heizungssteuerung.md`
- **ADRs AE-26 bis AE-35:** in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` v1.3
- **Datenmodell-Erweiterung Migration 0003:** `season`, `scenario`, `scenario_assignment`, `global_config` (Singleton), `manual_setpoint_event`, `event_log` (Hypertable), plus `room_type.max_temp/min_temp/long_vacant_hours`
- **Engine:** 5-Schichten-Pipeline (AE-06) erweitert um Layer 0 Sommermodus + Saison-Resolution in Layer 1
- **UI:** 6-Bereiche-Sidebar (Heute / Zimmer / Regeln / Geraete / Analyse / Einstellungen). Alte Sprint-7-Sidebar wird in Sprint 11 abgeloest.
- **Sprint-Bogen:** 8 Stammdaten -> 9 Engine -> 10 Saison/Szenarien/Sommermodus -> 11 Dashboard/Floorplan/shadcn -> 12 Mobile/PWA -> 13 Pilot-Reife.

## Workflow-Modus

- **Ultra-autonom** vereinbart 2026-05-02. Keine Phase-Gates pro Sub-Sprint. User meldet sich nur bei Findings auf Test-Server. Claude arbeitet Brief, Sprintplan, Code, Tests, PR autonom durch.

## Memory-Disziplin (gegen Wiederholungs-Schlaufen)

- Bei jedem neuen Chat zuerst CONTEXT.md, dann CLAUDE.md, dann das in CONTEXT verlinkte aktuelle Sprint-Doku.
- STATUS.md ist Historie. NICHT bei jedem Boot komplett lesen. Nur den Top-Bereich (aktueller Stand) checken.
- Bei jeder Sprint-Schliessung: CONTEXT.md aktualisieren VOR dem Tag.
- Bei jedem ADR: AE-Nummer in CONTEXT.md unter "Architektur-Konsens" referenzieren.

## Bekannte Stolperfallen (Quintessenz aus CLAUDE.md §5)

- Cowork-Mount sync ist nicht zuverlaessig — Edits via Sandbox sofort in PowerShell `git diff --stat <file>` verifizieren.
- PS5 + Bash-Skripte: BOM-Toedlich. ASCII-only oder `[System.IO.File]::WriteAllText` mit `UTF8Encoding $false`.
- Branch-Naming `chore/<slug>` schreitet im Cowork-Mount fehl — flacher Name `chore-<slug>` als Workaround. Branch-Erstellung IMMER in PowerShell.
- Sandbox-git landet NICHT im Windows-Repo. Branch + Commit + Push: PowerShell.
- `gh pr merge --merge` aendert SHA — Sync-PRs immer ERST nach main-Merge erstellen, nie davor.
- ChirpStack v4 macht keine `${VAR}`-Substitution in TOML — `envsubst`-Sidecar (AE-20).
- ChirpStack-Goja JS-Engine ist strict-mode — alle Variablen mit `var` deklarieren (Lessons Sprint 6.8).

## Server-Stand

- **heizung-test:** `https://heizung-test.hoteltec.at` — `:develop`-Pull, K-1 Caddy-Basic-Auth aktiv, 4 Vicki + 1 UG65 live
- **heizung-main:** `https://heizung.hoteltec.at` — `:main`-Pull, K-1 Caddy-Basic-Auth aktiv
- **ChirpStack-UI Test:** `https://cs-test.hoteltec.at`
- **MQTT-Broker:** `heizung-test:1883` (anonymous, Backlog M-14 echte Auth)

## Backlog (priorisiert, nicht in den naechsten 6 Sprints)

- K-4 ChirpStack ohne root
- K-5 CSP-Header in Caddyfiles (gemeinsames Snippet, M-2 mit erledigt)
- H-6 SHA-Pinning fuer GHCR-Tags (eigener Sprint, build-images.yml + deploy-pull synchron)
- H-8 Backup-Strategie `pg_dump` + Off-Site (Sprint 13 spaeter, evtl. vorgezogen als Hotfix-Sprint)
- WT101 Milesight Codec + Pairing (eigener Sprint)
- Vicki-002 Reichweite verbessern (RSSI -114, naeher zum UG65 stellen)
- Frontend-CI-Skip-Hack (H-7) entfernen, sobald Branch-Protection-Matcher smarter wird
- ChirpStack-Bootstrap-Skript (Tenant + App + DeviceProfile + Codec) fuer reproduzierbares Setup

## Wichtige Doku-Links

- `docs/STRATEGIE.md` — Vollstrategie v1.0
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log v1.3
- `docs/working/2026-05-02-master-plan-heizungssteuerung.md` — aktueller Master-Plan
- `docs/SPEC-FRAMEWORK.md` — Code-/Sicherheits-/DoD-Regeln
- `docs/WORKFLOW.md` — 5-Phasen-Feature-Flow (Ultra-Autonom-Modus 2026-05-02 vereinbart)
- `docs/RUNBOOK.md` — Operations + Rescue
- `STATUS.md` — Sprint-Historie (Append-only-Log, NICHT als Boot-Doku lesen)
- `CLAUDE.md` — Goldene Regeln + Lessons Learned (Pflicht-Lektuere fuer KI-Boot)

---

*Aktualisiert 2026-05-02 nach Master-Plan-Freigabe. Naechste Aktualisierung: nach Vicki-Spike-Resultat.*
