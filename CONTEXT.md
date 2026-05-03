# CONTEXT — Heizungssteuerung Hotel Sonnblick

**Boot-Anker fuer KI-Sessions.** Lies das ZUERST. Dann erst CLAUDE.md, dann Sprint-spezifische Doku.
**Halte das File schlank** (Ziel < 100 Zeilen). Alte Sprints kommen NICHT hierher — die stehen in STATUS.md.
**Pflicht:** Am Ende jedes Sprints aktualisieren. Wenn das nicht passiert ist, ist der Sprint nicht "Done".

---

## Aktueller Stand

- **Letzter Tag:** `v0.1.8-stammdaten` (geplant nach Merge Sprint 8.15)
- **Letzter Sprint abgeschlossen:** Sprint 8 (Stammdaten + Belegung) — Backend 8.1-8.7, Frontend 8.9-8.12, E2E 8.13
- **Aktiver Sprint:** Sprint 8.15 Hotfix (Design-Strategie 2.0.1: Umlaute, Add-/Destructive-Buttons, Schriftgroessen 12/14/16). Branch `chore-sprint8-15-design-fixes`, Brief `docs/features/2026-05-03-sprint8.15-design-fixes.md`. Build + Lint gruen.
- **Vor Sprint-9-Start:** Spike-OK liegt vor (Vicki nimmt Downlinks an, 1° Aufloesung). Sprint 9 kann starten — sobald 8.15 gemerged + getagged ist.

## Was JETZT der naechste konkrete Schritt ist

1. Sprint 8.15 Branch + Commit + Push + PR auf develop (PowerShell-Block beim User)
2. Browser-Verifikation auf Test-Server via Claude-in-Chrome nach Pull-Timer
3. Tag `v0.1.8-stammdaten` setzen
4. Sprint 9 Code starten
5. Codec-Backlog Task #86 / #87 weiterhin offen, nicht-blockierend
6. Sprint 8.8 (Integration-Tests gegen echte Postgres) auf Sprint 13 verschoben

## Architektur-Konsens (Stand 2026-05-02)

- **Master-Plan freigegeben:** `docs/working/2026-05-02-master-plan-heizungssteuerung.md`
- **ADRs AE-26 bis AE-35:** in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` v1.3
- **Datenmodell-Erweiterung Migration 0003:** `season`, `scenario`, `scenario_assignment`, `global_config` (Singleton), `manual_setpoint_event`, `event_log` (Hypertable), plus `room_type.max_temp/min_temp/long_vacant_hours`
- **Engine:** 5-Schichten-Pipeline (AE-06) erweitert um Layer 0 Sommermodus + Saison-Resolution in Layer 1
- **UI:** 6-Bereiche-Sidebar (Heute / Zimmer / Regeln / Geraete / Analyse / Einstellungen). Alte Sprint-7-Sidebar wird in Sprint 11 abgeloest.
- **Sprint-Bogen:** ✅ 8 Stammdaten -> 9 Engine (naechster) -> 10 Saison/Szenarien/Sommermodus -> 11 Dashboard/Floorplan/shadcn -> 12 Mobile/PWA -> 13 Pilot-Reife (inkl. Integration-Tests H-4).
- **Sprint-8-Inkremente:** 8.1 Models, 8.2 Migrationen, 8.3 Schemas+Seed, 8.4 API rooms/types/zones, 8.5 Belegungs-API + OccupancyService, 8.6 global_config-API, 8.7 Device-Zone (existing), 8.9 Frontend Raumtypen, 8.10 Zimmer + Detail-Tabs, 8.11 Belegungen, 8.12 Hotel-Stammdaten, 8.13 Playwright-E2E + Doku, 8.14 Tag.

## Workflow-Modus

- **Ultra-autonom** vereinbart 2026-05-02. Keine Phase-Gates pro Sub-Sprint. User meldet sich nur bei Findings auf Test-Server. Claude arbeitet Brief, Sprintplan, Code, Tests, PR autonom durch.

## Memory-Disziplin (gegen Wiederholungs-Schlaufen)

- Bei jedem neuen Chat zuerst CONTEXT.md, dann CLAUDE.md, dann das in CONTEXT verlinkte aktuelle Sprint-Doku.
- STATUS.md ist Historie. NICHT bei jedem Boot komplett lesen. Nur den Top-Bereich (aktueller Stand) checken.
- Bei jeder Sprint-Schliessung: CONTEXT.md aktualisieren VOR dem Tag.
- Bei jedem ADR: AE-Nummer in CONTEXT.md unter "Architektur-Konsens" referenzieren.

## Browser-Tests: IMMER Claude-fuer-Chrome (mcp__Claude_in_Chrome__*) nutzen

**Pflicht (User-Wunsch 2026-05-03):** Wenn UI getestet werden muss (Sprint-Abnahme, Bug-Reproduktion, Verifikation), Claude oeffnet selbst den Browser via MCP-Tools (`mcp__Claude_in_Chrome__navigate`, `read_page`, `find`, `form_input`, etc.). Nicht den User durchklicken lassen. Wenn ein Tool nicht aufrufbar ist (Permission, Verbindung, Schema): SOFORT melden, nicht stillschweigend zur User-Schritt-Anleitung wechseln. User fixt dann.

## Bekannte Stolperfallen (Quintessenz aus CLAUDE.md §5)

- Cowork-Mount sync ist nicht zuverlaessig — Edits via Sandbox sofort in PowerShell `git diff --stat <file>` verifizieren.
- PS5 + Bash-Skripte: BOM-Toedlich. ASCII-only oder `[System.IO.File]::WriteAllText` mit `UTF8Encoding $false`.
- Branch-Naming `chore/<slug>` schreitet im Cowork-Mount fehl — flacher Name `chore-<slug>` als Workaround. Branch-Erstellung IMMER in PowerShell.
- Sandbox-git landet NICHT im Windows-Repo. Branch + Commit + Push: PowerShell.
- `gh pr merge --merge` aendert SHA — Sync-PRs immer ERST nach main-Merge erstellen, nie davor.
- ChirpStack v4 macht keine `${VAR}`-Substitution in TOML — `envsubst`-Sidecar (AE-20).
- ChirpStack-Goja JS-Engine ist strict-mode — alle Variablen mit `var` deklarieren (Lessons Sprint 6.8).
- **deploy-pull.sh git fetch scheitert mit "dubious ownership"** — auf neuen Servern oder nach OS-Updates `git config --global --add safe.directory /opt/heizung-sonnblick` als root setzen. Pull-Timer schweigt sonst stundenlang. Logs via `journalctl -u heizung-deploy-pull -n 50`.
- **Frontend AppShell NICHT in Page-Komponenten wrappen** — `frontend/src/app/layout.tsx` macht das bereits. Doppelt -> Sidebar zweimal nebeneinander gerendert. Sprint-7-Pattern (`/devices`) ist die korrekte Vorlage.
- **Pull-Timer + Image-Tag-Caching:** `docker compose up -d` ohne `--force-recreate` startet Container nicht neu, wenn das `:develop`-Tag das gleiche heisst. Bei verdaechtigem alten UI-Stand: `docker compose pull web && docker compose up -d --force-recreate web`.

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
