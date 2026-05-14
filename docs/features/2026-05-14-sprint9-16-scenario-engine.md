# Brief für Claude Code — Sprint 9.16 (Szenario-Engine + Sommermodus)

> Archivkopie des Sprint-Briefs zur Nachvollziehbarkeit. Der eigentliche
> Stand nach Abschluss ist in `STATUS.md` §2ae und
> `ARCHITEKTUR-ENTSCHEIDUNGEN.md` AE-49 dokumentiert (Brief sagte AE-48 —
> bereits durch Vicki-Downlink-Helper belegt; pragmatisch AE-49 genommen).

## Ziel

Sommermodus wird auf die Szenario-Infrastruktur (`scenario` +
`scenario_assignment`) umgestellt. Layer 0 der Engine liest künftig aus
`scenario_assignment` statt aus `global_config.summer_mode_active`. Die
alte Spalte wird gedroppt — atomare Migration mit Daten-Erhalt.

Sommermodus erscheint als erste Karte auf `/szenarien`. Aktivierung
über `ConfirmDialog` (Brief: AlertDialog) mit klarem Wirkungs-Hinweis.
`/einstellungen/temperaturen-zeiten` zeigt einen Warn-Banner bei
aktivem Sommermodus.

AE-31 wird als historisch markiert. AE-49 dokumentiert die tatsächlich
laufende Engine-Pipeline. Kein Engine-Refactor — nur Doku, die der
Realität entspricht.

## Architektur-Entscheidungen (verbindlich)

- **AE-1:** Sommermodus auf `scenario_assignment` migrieren,
  `global_config.summer_mode_active` droppen. Atomare Alembic-Migration
  mit Daten-Erhalt (Auf-Ab-Auf-Pflicht-Stop vor T2).
- **AE-2:** Layer 0 strukturell unverändert; nur die Datenquelle
  wechselt. Reason ⇒ `SCENARIO_SUMMER_MODE`.
- **AE-3:** Keine Erweiterung von Layer 2 mit Szenario-Auflösung in
  9.16. Kommt mit 9.16b nach erstem Winter mit Live-Daten.
- **AE-4:** UI-Card auf `/szenarien`. Warn-Banner auf
  `/einstellungen/temperaturen-zeiten` mit Link.
- **AE-5:** AlertDialog für Aktivieren UND Deaktivieren — kein
  Inline-Toggle.
- **AE-6:** AE-31 als historisch markieren; neuer ADR (AE-49)
  dokumentiert die laufende Pipeline.

## Tasks

1. **T1** Migration `0012_summer_mode_scenario` mit Daten-Erhalt
   (Pflicht-Stop nach Auf-Ab-Auf-Test).
2. **T2** Model + Schema-Cleanup (`global_config.summer_mode_active` weg).
3. **T3** Engine Layer 0 → Helper `is_summer_mode_active` aus
   `scenario_assignment` (Pflicht-Stop nach Tests).
4. **T4** Router `api/v1/scenarios.py` (GET / activate / deactivate)
   mit `config_audit`-Hook + `# AUTH_TODO_9_17`.
5. **T5** shadcn Switch + Card installieren (AlertDialog bereits da).
6. **T6** `ScenarioCard`-Komponente mit Switch + ConfirmDialog.
7. **T7** Route `/szenarien` (ersetzt Stub).
8. **T8** Warn-Banner auf `/einstellungen/temperaturen-zeiten`.
9. **T9** Doku: AE-31 historisch, AE-49 neu (Brief: AE-48), STATUS
   §2ae (Brief: §2af), B-9.16-1 Backlog, Brief-Kopie.
10. **T10** Tests (Backend API + Layer 0 + Frontend Playwright).

## Akzeptanzkriterien

1. Migration läuft atomar, übersteht Auf-Ab-Auf-Zyklus.
2. `global_config.summer_mode_active` existiert nicht mehr in DB +
   Code.
3. Layer 0 reagiert auf `scenario_assignment`, Trace zeigt neuen
   Reason.
4. Hotelier kann auf `/szenarien` Sommermodus aktivieren/deaktivieren
   über ConfirmDialog.
5. Bei aktivem Sommermodus zeigt `/einstellungen/temperaturen-zeiten`
   einen Warn-Banner mit Link.
6. Jede (De-)Aktivierung erzeugt `config_audit`-Eintrag.
7. AE-31 historisch, AE-49 dokumentiert laufende Pipeline.
8. Engine übernimmt Szenario-Änderung beim nächsten Beat-Tick
   (≤ 60 s).

## Out of Scope (verbindlich)

- Auth/NextAuth (Sprint 9.17).
- Weitere Szenarien + Saison-UI + volle Szenario-Resolution
  (Sprint 9.16b).
- Engine-Refactor Layer 2/3/4 (nur Doku-Drift via AE-49).
- UI für `config_audit`-History.

## Brief-Abweichungen (nachgezogen während Umsetzung)

- **R3 Phase-0-Drift `scenario_assignment`:** Brief-Spaltennamen
  `scope_ref_id` / `active` / `activated_at` existieren nicht.
  Tatsächliche Spalten: `room_type_id` / `room_id` / `season_id`
  (nullable FKs analog `rule_config`), `is_active`. ScenarioScope-
  Enum-Werte lowercase (`global` statt `GLOBAL`). Migration
  entsprechend angepasst; `ON CONFLICT` durch `WHERE NOT EXISTS`
  ersetzt (zuverlässiger bei NULL-FKs im Composite-UNIQUE).
- **AE-48 vergeben:** Sprint 9.11x.b nutzt AE-48 für die
  Vicki-Downlink-Helper-Architektur. Neuer ADR wurde als **AE-49**
  angelegt.
- **STATUS §2af → §2ae:** §2ad ist der letzte vergebene Eintrag
  (Sprint 9.14); §2ae ist der nächste freie Buchstabe.
