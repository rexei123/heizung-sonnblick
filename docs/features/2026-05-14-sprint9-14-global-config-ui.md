# Brief für Claude Code — Sprint 9.14 (Globale Temperaturen + Zeiten UI)

> Archivkopie des Sprint-Briefs zur Nachvollziehbarkeit. Der eigentliche
> Stand nach Abschluss ist in `STATUS.md` §2ad und `ARCHITEKTUR-
> ENTSCHEIDUNGEN.md` AE-46 dokumentiert.

## Pflicht-Vorlauf

1. SESSION-START.md, CLAUDE.md §0+§0.1, STATUS.md §1, SPRINT-PLAN.md
   Sprint 9.14 lesen.
2. Phase-0-Befund-Datei lesen: `docs/features/2026-05-12-sprint9-14-phase0.md`
   (auf develop nach PR #142).
3. develop HEAD per `git log --oneline -3` verifizieren.
4. Autonomiestufe: 2 (Standard). Stop nur bei Architektur-Abweichung
   von diesem Brief.

## Ziel

Hotelier kann 6 Engine-Parameter und 0–N `global_config`-Werte über zwei
Tabs unter `/einstellungen/temperaturen-zeiten` ändern. Engine übernimmt
die neuen Werte beim nächsten Beat-Tick (≤ 60 s). Jede Änderung landet
in der neuen `config_audit`-Tabelle.

Keine Betterspace-Parität. Nur was die Engine heute liest, ist editierbar.

## Branch + PR

- Branch: `feat/sprint9-14-global-config-ui`
- PR-Base: `develop` (Pflicht laut CLAUDE.md §3.11)
- Tag-Vorschlag nach DoD-Abschluss: `v0.1.12-global-config-ui`
  (Strategie-Chat-Freigabe abwarten)

## Architektur-Entscheidungen (verbindlich)

- **AE-1:** `rule_config` bleibt typisiert. PATCH ist typed, keine
  EAV-Erweiterung. Pydantic-Schema mit den 6 Engine-gelesenen Feldern.
- **AE-2:** Audit-Trail in eigener Tabelle `config_audit`. `event_log`
  bleibt unverändert (Engine-Decisions-Domain). Schema in T1.
- **AE-3:** Auto-Save-on-Blur statt Save-Button. Kein `save`-Glyph nötig.
  Validierung clientseitig (Zod) + serverseitig (Pydantic).
- **AE-4:** Keine Auth-Implementierung in 9.14. PATCH-Routen bekommen
  Code-Marker `# AUTH_TODO_9_17` und loggen Request-IP in `config_audit`.
  NextAuth-Integration ist Sprint 9.17.
- **AE-5:** Sommermodus-Toggle NICHT in 9.14. Kommt mit 9.16.
- **AE-6:** Klima-Tab gestrichen. Nur 2 Tabs: „Globale Zeiten",
  „Globale Temperaturen".

Diese 6 Entscheidungen sind in T7 als ADR AE-46 in
`docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` festgehalten.

## Tasks

### T1 — Backend: `config_audit`-Tabelle + Service

- Alembic-Migration `0011_config_audit` (Schema siehe Brief-Original).
- SQLAlchemy-Model `heizung/models/config_audit.py`.
- Pydantic-Schema `heizung/schemas/config_audit.py` (Read-Only).
- Service `record_config_change(...)` in
  `heizung/services/config_audit_service.py` — atomar mit dem
  eigentlichen UPDATE in derselben Transaktion.

### T2 — Backend: `PATCH /api/v1/rule-configs/global`

- Neuer Router `heizung/api/v1/rule_configs.py`.
- `GET /api/v1/rule-configs/global` + `PATCH /api/v1/rule-configs/global`.
- 6 Engine-Felder mit Range-Validierung (`t_occupied` 16–26,
  `t_vacant` 10–22, `t_night` 14–22, `preheat_minutes_before_checkin`
  0–240). `Decimal`, kein `float`. Nachtfenster-Konsistenz:
  `night_start != night_end`; Wrap über Mitternacht erlaubt.
- Pro geändertem Feld: `config_audit`-Eintrag.
- `# AUTH_TODO_9_17` als Kommentar direkt am Router.

### T3 — Backend: `PATCH /api/v1/global-config` erweitern

- Bestehende Felder editierbar lassen.
- `config_audit`-Hook einbauen analog T2.
- Keine neuen Felder editierbar machen.
- `# AUTH_TODO_9_17`.

### T4 — Frontend: `InlineEditCell` extrahieren

- Pfad: `frontend/src/components/inline-edit-cell.tsx`.
- Props: `value`, `variant`, `validator` (Zod), `onSave`, `format?`,
  `ariaLabel?`, `onSaveError?`.
- Verhalten: Klick → Edit-Mode → Tab/Blur → Validate → Save. Esc =
  Abbrechen. Validate-Fehler inline, Save-Fehler über Toast-Callback.
- Bestehendes `LabelCell` in `/devices/page.tsx` bleibt unangetastet
  (eigene Edit-Button-Interaktion, nicht klick-direkt).

### T5 — Frontend: `/einstellungen/temperaturen-zeiten` Page

- shadcn-Tabs (`components/ui/tabs.tsx`, neue Deps `zod` +
  `@radix-ui/react-tabs`).
- Tab 1 „Globale Zeiten": `night_start`, `night_end`,
  `preheat_minutes_before_checkin`.
- Tab 2 „Globale Temperaturen": `t_occupied`, `t_vacant`, `t_night`.
- Daten-Load: `GET /api/v1/rule-configs/global` beim Mount.
- Save: `PATCH` mit nur dem geänderten Feld.
- Toast „Gespeichert — Engine übernimmt in ≤ 60 s".

### T6 — Tests

- 5 Backend-Tests in `tests/test_api_rule_configs.py`:
  - Range-Validierung
  - `config_audit` pro Feld
  - Decimal (kein Float)
  - Nachtfenster
  - Engine liest neuen Wert nach PATCH (kein Cache)
- Playwright-E2E in `tests/e2e/temperaturen-zeiten.spec.ts`: Tabs,
  Edit-Mode, Out-of-Range-Block, Save → Toast → Reload-Persistenz.

### T7 — Doku

- `STATUS.md` §2ad (Brief sagte §2v, ist bereits Sprint 9.11 — §2ad
  als nächster freier Buchstabe nach §2ac genommen).
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` AE-46 anlegen.
- Diese Brief-Kopie unter `docs/features/2026-05-14-sprint9-14-
  global-config-ui.md`.

## Akzeptanzkriterien

1. Hotelier kann auf `/einstellungen/temperaturen-zeiten` alle 6 Werte
   ändern.
2. Out-of-Range-Eingabe wird abgelehnt (Frontend + Backend).
3. Engine liest neuen Wert beim nächsten Beat-Tick (verifiziert über
   Engine-Decision-Trace in `/zimmer/[id]`).
4. Jede Änderung erzeugt `config_audit`-Eintrag mit
   `{ts, source=API, table, column, old, new, request_ip}`.
5. Bestehendes `/devices`-Inline-Edit funktioniert unverändert
   (`LabelCell` unangetastet).
6. Decimal-Konvention überall, kein Float in Setpoint-Pfaden.

## Definition of Done

- Backend: ruff + ruff format --check + mypy strict + pytest grün
- Frontend: tsc + eslint + build grün, Playwright-Smoke grün
- CI grün auf HEAD
- PR `feat/sprint9-14-global-config-ui` → develop, gemerged via PR
- Branch lokal + remote gelöscht
- STATUS.md §2ad + ADR AE-46 vorhanden

## Out of Scope (verbindlich)

- Klima-Tab
- Sommermodus-Toggle in UI
- Auth/NextAuth-Integration
- UI für `config_audit`-History-Anzeige
- Editierbarkeit der 8 ungenutzten `rule_config`-Felder
  (`setback_minutes_after_checkout`, `long_vacant_*`,
  `guest_override_*`, `window_open_*`)
- Visual-Review durch Cowork (separater Auftrag nach Code-Complete)

## Risiken

- **R1:** `InlineEditCell`-Refactor bricht `/devices`. Mitigation:
  `LabelCell` als Wrapper behalten, Tests in `/devices` laufen
  lassen. — Tatsächlich umgesetzt: `LabelCell` unangetastet, neue
  Komponente parallel.
- **R2:** `night_start`/`night_end`-Validation für Fenster über
  Mitternacht. Mitigation: Test explizit (22:00 → 06:00 erlaubt).
- **R3:** Phase-0 hat `global_config`-Spaltenliste nicht vollständig
  geliefert. Falls T3 entdeckt, dass keine Engine-relevanten Felder
  editierbar sind: T3 streichen, Brief-Frage an Strategie-Chat
  eskalieren. — Phase-0 hatte die Liste komplett; T3 ist eine
  reine `config_audit`-Erweiterung des bestehenden Handlers.
