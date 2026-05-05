# Feature-Brief Sprint 8 — Stammdaten-CRUD + Belegungs-Verwaltung

**Datum:** 2026-05-02
**Phase:** 1 (Definition) — freigegeben durch User-OK auf Master-Plan vom 2026-05-02
**Workflow-Modus:** Ultra-autonom (vereinbart 2026-05-02). Kein Phase-Gate pro Sub-Sprint, nur Findings auf Test-Server gehen an User.
**Vorgaenger:** Sprint 7 (Frontend-Dashboard, Tag `v0.1.7-frontend-dashboard`), Sprint 8a (K-1 Caddy-Basic-Auth)
**Folge-Sprint:** Sprint 9 — Regel-Engine + Downlink

---

## 1. Ziel (1-2 Saetze, aus Anwendersicht)

Der Hotelier kann im UI **Raumtypen anlegen**, **Zimmer mit Heizzonen pflegen**, **Geraete den Zonen zuordnen** und **Belegungen eintragen**. Damit ist die fachliche Basis fuer die Regel-Engine in Sprint 9 vollstaendig — die Engine kann ab Sprint 9 fuer jeden konfigurierten Raum einen Soll-Setpoint berechnen.

## 2. Nutzer / Rollen

- **Admin** (im Interim K-1: jeder mit Caddy-Basic-Auth-Login). Sprint 14 ersetzt das durch echte User-Rollen.

## 3. Akzeptanzkriterien (als Checkliste, ueberpruefbar)

- [ ] Raumtypen-CRUD: Liste, Anlegen, Bearbeiten, Loeschen (nur wenn 0 verknuepfte Raeume), Validierung der Default-Temperaturen.
- [ ] Zimmer-CRUD: Liste, Anlegen, Bearbeiten, Loeschen (nur wenn 0 aktive Belegungen). Pflichtfelder: number (eindeutig), room_type. Optional: floor, orientation, notes.
- [ ] Heizzonen-CRUD: pro Zimmer 1..n Zonen anlegen (kind, name, is_towel_warmer).
- [ ] Geraete-zu-Zone-Zuordnung: bestehendes Geraet (Sprint 6.10) einer Zone zuweisen oder Zuweisung loesen.
- [ ] Belegungen-CRUD: Liste mit Filtern (heute, naechste 7 Tage, ab Datum, nach Raum). Anlegen mit room_id + check_in + check_out + guest_count. Stornieren via soft-delete (`is_active = false`, `cancelled_at = NOW`).
- [ ] Beim Anlegen einer Belegung wird `room.status` auf `RESERVED` (zukuenftig) oder `OCCUPIED` (jetzt) gesetzt. Bei Storno: `status` zurueck auf `VACANT`.
- [ ] Hotel-Stammdaten (Singleton `global_config`): Admin kann hotel_name, timezone, default_checkin_time, default_checkout_time, alert_email pflegen.
- [ ] Migration 0003 laeuft idempotent, hat einen Roundtrip-Test (upgrade -> downgrade -> upgrade).
- [ ] Seed-Skript erweitert: 3 Default-Raumtypen (Schlafzimmer/Studio/Tagungsraum), 1 `global_config`-Row mit Defaults, 8 System-Szenarien (default_active, ohne Aktivierung).
- [ ] API-Integration-Tests (pytest) fuer alle CRUD-Endpoints (Happy + 1 Negative Path pro Route).
- [ ] Playwright-E2E: Raumtyp anlegen, Zimmer anlegen, Belegung anlegen, Belegung stornieren — durchgehender Flow.
- [ ] Build gruen, Tests gruen, Deploy auf `heizung-test.hoteltec.at` erfolgreich, K-1-Caddy-Auth funktioniert weiter.

## 4. Abgrenzung (Was ist NICHT Teil dieses Sprints?)

- KEINE Regel-Engine. `manual_setpoint_event` und `event_log` werden als Tabellen angelegt (Migration 0003), aber NICHT von der Engine verwendet (Engine kommt in Sprint 9).
- KEINE Szenarien-UI. `scenario` und `scenario_assignment` werden als Tabellen angelegt, aber das UI dafuer ist Sprint 10.
- KEINE Saison-UI. `season`-Tabelle wird angelegt, UI ist Sprint 10.
- KEIN Sommermodus-UI. Spalten in `global_config` werden angelegt (`summer_mode_active`, `summer_mode_starts_on`, `summer_mode_ends_on`), aber kein UI-Schalter (Sprint 10).
- KEINE Floorplan-View (Sprint 11).
- KEINE Mobile-First-Optimierung (Sprint 12).
- KEINE PMS-Connector. Belegung ist manuell-only.
- KEIN Downlink. Setpoint-Aenderungen werden NICHT zum Vicki gesendet (Sprint 9).
- KEINE Ersatz-Auth. K-1 Caddy-Basic-Auth bleibt.

## 5. Edge Cases und Fehlerfaelle

- Raumtyp loeschen mit verknuepften Raeumen: 409 Conflict mit Fehlermeldung "Raumtyp ist mit X Zimmern verknuepft".
- Zimmer loeschen mit aktiven Belegungen: 409 Conflict.
- Belegung mit `check_in >= check_out`: 422 mit klarer Meldung.
- Belegung mit `check_in` in der Vergangenheit + `check_out` in der Zukunft: erlaubt (rueckwirkend Eintragen).
- Zwei aktive Belegungen fuer den gleichen Raum mit ueberlappendem Zeitraum: 409 Conflict.
- Geraet mit `vendor=manual` (Mock fuer Tests) zu Zone zuordnen: erlaubt.
- Zone-Loeschen mit zugeordnetem Geraet: Geraet bleibt mit `heating_zone_id = NULL` (SET NULL).
- `global_config`-PATCH ohne Felder: 422 mit Hinweis "mindestens ein Feld noetig".
- Migration 0003 auf Server ohne TimescaleDB-Extension: muss sauber fehlschlagen (event_log ist Hypertable).

## 6. Datenmodell-Aenderungen (Migration 0003)

Vollstaendige Spec im Master-Plan §4.2. Hier kompakt:

**Neue Tabellen:**
- `season`: id, name, starts_on, ends_on, is_active, notes, created_at, updated_at
- `scenario`: id, code (UNIQUE), name, description, is_system, default_active, parameter_schema JSONB, created_at, updated_at
- `scenario_assignment`: id, scenario_id FK, scope ENUM, room_type_id FK NULL, room_id FK NULL, season_id FK NULL, is_active, parameters JSONB, created_at, updated_at
- `global_config`: id PK CHECK = 1, hotel_name, timezone, default_checkin_time, default_checkout_time, summer_mode_active, summer_mode_starts_on, summer_mode_ends_on, alert_email, created_at, updated_at
- `manual_setpoint_event`: id, scope, room_type_id FK NULL, room_id FK NULL, target_setpoint_celsius, starts_at, ends_at, reason, is_active, created_at
- `event_log` (TimescaleDB Hypertable): time, room_id FK, device_id FK NULL, evaluation_id UUID, layer ENUM, setpoint_in, setpoint_out, reason, details JSONB

**Erweiterungen bestehender Tabellen:**
- `room_type`: + max_temp_celsius NUMERIC(4,1) NULL, + min_temp_celsius NUMERIC(4,1) NULL, + treat_unoccupied_as_vacant_after_hours INT NULL
- `rule_config`: + season_id FK NULL (zur Saison-Resolution gemaess AE-26)

## 7. UI-Skizze / Komponenten

**Routen (Next.js App Router):**
- `/raumtypen` — Master-Detail-Layout. Liste links, Form rechts.
- `/zimmer` — Tabellen-Liste mit Spalten (Nummer, Raumtyp, Etage, Status, Geraete-Count). Klick oeffnet Drawer.
- `/zimmer/[id]` — Detail mit Tabs (Stammdaten, Heizzonen, Geraete, Belegungen).
- `/belegungen` — Liste mit Filtern + Anlege-Dialog.
- `/einstellungen/hotel` — Settings-Layout mit gruppierten Cards fuer global_config.

**Komponenten (NEU):**
- `RoomTypeForm` — Form mit Validierung (Zod), Speichern -> PATCH/POST.
- `RoomForm` — analog, mit Auswahl Raumtyp.
- `HeatingZoneList` — Inline-Liste auf Zimmer-Detail, Add/Remove.
- `DeviceAssignmentSelect` — Dropdown der unzugeordneten Geraete + Loesen-Button.
- `OccupancyForm` — Datepicker fuer check_in/check_out, GuestCount-Spinner.
- `OccupancyList` — Tabelle mit Status-Badge, Storno-Button.
- `GlobalConfigForm` — Settings-Form mit drei Cards (Allgemein, Zeiten, Alerts).
- `DiffModal` — Generisches Bestaetigungs-Modal "Sie aendern X von Y auf Z. Auswirkung: Z Zimmer betroffen."

**Sidebar-Vorgriff:** Sprint 7-Sidebar bleibt vorerst bestehen. Refactoring auf 6-Bereiche-Struktur (AE-35) ist Sprint 11. Bis dahin werden die neuen Routen unter "STEUERUNG" und "ÜBERSICHT" eingehaengt.

## 8. Abhaengigkeiten (externe Services, andere Features)

- TimescaleDB-Extension fuer `event_log` Hypertable.
- Vorhandene Devices-CRUD-API (Sprint 6.10) — wird ergaenzt um Zone-Zuordnung.
- shadcn/ui ist NICHT Pflicht (kommt erst Sprint 11). Plain Tailwind reicht.
- TanStack Query v5 (vorhanden seit Sprint 7) wird fuer alle neuen Hooks verwendet.

## 9. Risiken

| Risiko | Eintritt | Impact | Mitigation |
|---|---|---|---|
| Migration 0003 mit 6 neuen Tabellen plus Spalten ist gross. Roundtrip-Probleme moeglich | mittel | hoch | Migration in zwei Files splitten falls noetig: 0003a Stammdaten, 0003b event_log. Roundtrip-Test in CI. |
| Singleton-Constraint via CHECK in Postgres bei Concurrent INSERTs | gering | mittel | UPSERT-Pattern in Seed: `INSERT ... ON CONFLICT (id) DO NOTHING`. |
| Belegungs-Ueberlapp-Check teuer bei vielen Belegungen | gering (Hotel mit < 100 aktive) | mittel | DB-Index auf `(room_id, check_in, check_out)` plus Application-Logic-Check. |
| `event_log` Hypertable-Migration scheitert lokal ohne TimescaleDB | hoch (lokale Dev-Umgebung) | mittel | Lokal-Compose hat schon TimescaleDB. Doku-Hinweis fuer neue Dev-Setups. |
| Frontend-Routen-Anzahl waechst stark (5 neue), Sprint-7-Sidebar wird voll | hoch | gering | Vorlaeufig akzeptabel, Refactoring Sprint 11. |
| `global_config` als Singleton: was wenn Multi-Hotel-Mandantenfaehigkeit kommt | mittel | hoch | Strategie A3 nennt das langfristig. Bei Mandantenfaehigkeit wird die Singleton-CHECK durch `hotel_id PK` ersetzt. Kein Show-Stopper jetzt. |
| User aendert Raumtyp-Defaults nach Belegung — wirkt das rueckwirkend? | hoch | mittel | Designentscheidung: Default-Aenderungen wirken auf naechste Engine-Evaluation. Doku-Hinweis im DiffModal. |

## 10. Offene Fragen / Annahmen

**Annahmen** (alle als `[Annahme]` markiert, gehen ohne Rueckfrage in den Code):

- [Annahme] **Anzahl Raumtypen MVP:** 3 (Schlafzimmer, Studio, Tagungsraum) wie aus Betterspace-Screenshot, plus 2 Heizzone-Defaults pro Schlafzimmer (Schlafzimmer + Bad). Hotelier kann beliebig viele anlegen.
- [Annahme] **Anzahl Zimmer:** Strategie sagt 45. Seed legt KEINE Zimmer an. Hotelier legt selbst an. (Alternative: Bulk-Import via CSV waere Sprint 14+ Feature.)
- [Annahme] **Sprache der API-Validierung:** Englisch (FastAPI-Default), Frontend uebersetzt selbst (i18n via Konstanten). Konsistent mit Sprint 7.
- [Annahme] **Time-Format in API:** ISO 8601 UTC. Frontend formatiert in `Europe/Vienna` (aus global_config.timezone).
- [Annahme] **Hotel-Defaults im Seed:**
  - hotel_name = "Hotel Sonnblick"
  - timezone = "Europe/Vienna"
  - default_checkin_time = 14:00
  - default_checkout_time = 11:00
  - summer_mode_active = false
  - alert_email = "hotelsonnblick@gmail.com"
- [Annahme] **System-Szenarien (Stammdaten-Seed):** 8 Eintraege passend zu R1-R7 + Tagabsenkung. `is_system = true`, `default_active = true` fuer R1/R3/R4/R8, false fuer Tagabsenkung (Hotelier muss bewusst aktivieren).
- [Annahme] **Belegungs-UI ohne Kalender:** Liste + Form reicht in Sprint 8. FullCalendar-Integration ist Sprint 11.
- [Annahme] **Branch-Naming:** `feat/sprint8-stammdaten-belegung` (kein flacher Workaround noetig, da `feat/`-Subdirectory schon mehrfach erfolgreich).

**Wirklich offene Fragen** (warten auf User-Antwort, NICHT autonom annehmen):

- KEINE. Alles annehmbar. User-OK zum Master-Plan deckt die Architektur-Fragen ab.

---

## 11. Definition of Done fuer den ganzen Sprint

- [ ] Alle Akzeptanzkriterien (§3) erfuellt.
- [ ] Migration 0003 deployt auf `heizung-test`.
- [ ] Backend-Tests gruen (alle vorhandenen + neu hinzugekommene CRUD-Tests).
- [ ] Frontend-Build gruen, Playwright-E2E gruen.
- [ ] PR auf `develop` gemerged, Tag `v0.1.8-stammdaten` gesetzt.
- [ ] CONTEXT.md aktualisiert mit neuem Stand.
- [ ] STATUS.md ergaenzt um Sprint-8-Eintrag.
- [ ] User wurde benachrichtigt, dass Sprint 8 abnahme-bereit auf Test-Server steht.

---

*Phase 1 (Definition) abgeschlossen. Phase 2 (Sprintplan) folgt in `docs/features/2026-05-02-sprint8-stammdaten-belegung-sprintplan.md`.*
