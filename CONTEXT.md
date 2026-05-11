# CONTEXT — Heizungssteuerung Hotel Sonnblick

**Boot-Anker fuer KI-Sessions.** Lies das ZUERST. Dann erst CLAUDE.md, dann Sprint-spezifische Doku.
**Halte das File schlank** (Ziel < 100 Zeilen). Alte Sprints kommen NICHT hierher — die stehen in STATUS.md.
**Pflicht:** Am Ende jedes Sprints aktualisieren. Wenn das nicht passiert ist, ist der Sprint nicht "Done".

> **Hinweis ab 2026-05-07:** Code-Sessions starten zusätzlich mit der
> Trigger-Phrase aus `docs/SESSION-START.md`. CONTEXT.md bleibt Boot-Anker
> für Strategie-Chat-Sessions, ergänzt SESSION-START für die Code-Rolle.

---

## Aktueller Stand (2026-05-11)

- **Letzter Tag:** `v0.1.9-rc6-live-test-2` (2026-05-11, develop) — Sprint-9.11-Familie geschlossen, Engine-Pipeline live verifiziert mit Hardware-Kältepack (AE-47-Bestätigung), AE-45-Auto-Override live demonstriert. Auf main bleibt `v0.1.8-stammdaten`.
- **Letzte Sprints abgeschlossen:** 9.11a (Geräte-Zuordnungs-API), 9.11x/x.b/x.c (Backplate-Persistenz + Vicki-Downlink-Helper + FW-Decoder-Fix), 9.11y (Synthetic-Tests + Inferred-Window-Logger).
- **Sprint 9.12 zurückgestellt** 2026-05-11 (Frostschutz pro Raumtyp — kein realer Schmerz, AE-42 zurückgestellt, R8 wieder globale Konstante, siehe STATUS.md §2aa). Tag-Slot `v0.1.10` bewusst ungenutzt.
- **Aktueller Mini-Sprint:** 9.12.1 Doku-Refresh (dieser Sprint).
- **Nächster echter Sprint:** 9.13 Geräte-Pairing-UI + Sidebar-Migration (BR-2, AE-43).

## Was JETZT der naechste konkrete Schritt ist

1. Sprint 9.13 starten: Pairing-Wizard `/devices/pair` (TA1, Multi-Step ohne bestehendes Pattern, von Grund auf bauen) + Detach-Button im `/zimmer/[id]/geraete`-Tab (TA2, API existiert seit 9.11a) + Sidebar-Migration auf 14 Einträge in 5 Gruppen (TB1-TB4) + Empty-State-Stubs für Profile/Szenarien/Saison/Gateway/API/Temperaturverlauf/Benutzer (TB2)
2. 9.13-Voraussetzungen erfüllt: 9.11a-API liefert PUT/DELETE `/devices/{id}/heating-zone`. shadcn/ui ist installiert (Sprint 9.8d) — Sheet-/Drawer-Komponenten nutzbar für Mobile-Sidebar-Verhalten
3. Nach 9.13: 9.14 Globale Temperaturen+Zeiten-UI, 9.15 Profile, 9.16 Szenarien+Saison, 9.17 NextAuth (vor Go-Live)

## Architektur-Konsens (Stand 2026-05-11)

- **Source-of-Truth-Hierarchie** (CLAUDE.md §0.2): `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` schlägt STRATEGIE.md, SPRINT-PLAN.md ist verbindlich für aktuelle Sprints.
- **Engine:** 6-Schichten-Pipeline (AE-31): Layer 0 Sommer (9.7) / 1 Base / 2 Temporal / 3 Manual (9.9) / 4 Window-Detection (9.10 + 9.11x Detached + 9.11y Inferred-Logger off-pipeline) / 5 Hard-Clamp + Hysterese.
- **Hardware-Realität (CLAUDE.md §5.27 + AE-45 + AE-47):** Vicki-Open-Window-Detection im Default disabled (durch 9.11x.b-Bulk-Aktivierung gesetzt), Algorithmus-Trägheit live bestätigt. Layer-4-Triggers: `open_window` (Vicki-Flag), `device_detached` (Backplate-Bit), passiv `inferred_window` (Off-Pipeline-Logger).
- **Vicki-Downlinks** über MQTT (AE-48), nicht gRPC. Helper in `backend/src/heizung/services/downlink_adapter.py` mit `send_raw_downlink` + typisierten Wrappern.
- **Stabilitätsregeln S1-S6** (CLAUDE.md §0, AE-44) verbindlich. Autonomie-Default Stufe 2 (CLAUDE.md §0.1).
- **Datenmodell:** 14 Modelle, Migrations 0001-0004 + 0008-0010. `room_type.frost_protection_c` NICHT vorhanden (AE-42 zurückgestellt).
- **UI:** AppShell mit 200 px Sidebar (heute 6 flache Einträge, Soll 14 in 5 Gruppen — Migration in 9.13). shadcn/ui-konform mit `@radix-ui` (seit 9.8d).
- **Sprint-Bogen ab 9.13:** 9.13 Pairing-UI+Sidebar → 9.14 Global-Settings → 9.15 Profile → 9.16 Szenarien+Saison → 9.17 NextAuth → 9.18 Dashboard → 9.19 Analytics → 9.20 API+Webhooks → 9.21 Gateway-UI → 10 Hygiene → 11 PMS-Casablanca → 12 Production-Migration → 13 Wetter → 14 v1.0.0 Go-Live.

## Workflow-Modus

- Trigger-Phrase pro Code-Session (siehe `docs/SESSION-START.md`): »Architektur-Refresh aktiv ab 2026-05-07. Lies docs/SESSION-START.md und bestätige.« Die Session beginnt mit der Pflicht-Bestätigung im definierten Format.
- Autonomie-Default Stufe 2 (CLAUDE.md §0.1). Sprint-Brief kann Stufe 1 (Engine-Touch, Hardware-Pfad) oder Stufe 3 (reine Doku) explizit setzen.
- Pflicht-Stops: Brief-Abweichung, Phase-0-Befund, S1-Verstoß-Verdacht, Test-Failure außerhalb Task, fremde Datei-Errors, vor PR/Tag/Live-Deploy, S1-S6-Verdacht.

## Bekannte Stolperfallen (Quintessenz aus CLAUDE.md §5)

- `gh pr create` braucht IMMER `--base develop` (CLAUDE.md §3.11) — sonst Default `main`, Branch-Modell gebrochen.
- `gh pr merge` triggert `build-images.yml` nicht zuverlaessig (§5.10) — nach Frontend-/Backend-Merge ggf. manuell `gh workflow run build-images.yml --ref develop`.
- `gh pr checks --watch` zeigt manchmal stale concurrency-cancel'd Runs (§5.25) — bei Merge-Fail »Required status check in progress« zweiten Watch-Durchlauf abwarten.
- ChirpStack-Codec-Deploy ist NICHT automatisch (§5.22) — Repo-Codec-Touch erfordert UI-Re-Paste auf jedem Server, Verify im Events-Tab.
- Vicki-Codec-Routing über `bytes[0]` Cmd-Byte, NICHT fPort (§5.21).
- Engine-Trace-Konsistenz: alle Layer schreiben immer LayerStep, auch Pass-Through (§5.23).
- `ruff check` und `ruff format --check` sind verschiedene CI-Gates (§5.24) — vor Push beide laufen lassen oder lokale Pre-Push-Toolchain nutzen (CLAUDE.md §6).
- Frontend AppShell NICHT in Page-Komponenten wrappen (§5.8).
- `deploy-pull.sh` git-fetch scheitert mit "dubious ownership" (§5.7) — `git config --system --add safe.directory /opt/heizung-sonnblick` (system, nicht global).

## Server-Stand

- **heizung-test:** `https://heizung-test.hoteltec.at` — `:develop`-Pull, K-1 Caddy-Basic-Auth aktiv, 4 Vickis (alle 4 mit `firmware_version=4.4`, Open-Window-Detection aktiviert in 9.11x.b) + 1 UG65 live. ChirpStack-UI: `https://cs-test.hoteltec.at`.
- **heizung-main:** `https://heizung.hoteltec.at` — `:main`-Pull, alter Sprint-9.8a-Stand, B-9.11x-2 (Sanierung vor v0.2.0) noch offen.
- **MQTT-Broker:** `heizung-test:1883` (anonymous, Backlog).

## Wichtige Doku-Links

- `docs/SESSION-START.md` — Pflicht-Pre-Read pro Session (Code-Rolle: SESSION-START + CLAUDE.md + SPRINT-PLAN + STATUS §1 + Brief)
- `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` — Master nach Refresh
- `docs/SPRINT-PLAN.md` — verbindlicher Sprint-Plan ab 9.11
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log inkl. AE-42 (zurückgestellt), AE-43-48
- `docs/STRATEGIE.md` — Vollstrategie v1.1 (Header-Hinweis 2026-05-11)
- `docs/RUNBOOK.md` — Operations + Rescue + §10e Vicki-Downlink-Konfiguration
- `docs/vendor/mclimate-vicki/` — Hersteller-Doku (FW-Tabelle, Command-Cheat-Sheet)
- `STATUS.md` §2aa — jüngster Sprint-Eintrag (Sprint 9.12 zurückgestellt)
- `CLAUDE.md` — Stabilitätsregeln + Lessons (Pflicht-Lektüre, §5.x)

---

*Aktualisiert 2026-05-11 (Sprint 9.12.1 Doku-Refresh). Nächste Aktualisierung: nach Sprint-9.13-Abschluss.*
