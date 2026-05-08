# REFRESH-PAYLOAD — Inhalte für Claude-Code-Auftrag

**Erstellt:** 2026-05-07 im Strategie-Chat
**Zweck:** Quelle für den Architektur-Refresh-Sprint
**Lebensdauer:** wird am Ende des Sprints (nach Tag-Vergabe) wieder gelöscht
**Bezug:** Strategie-Chat-Output zum Architektur-Refresh

Diese Datei enthält alle Markdown-Inhalte, die in Schritt 1-5 des
Refresh-Sprints in Repo-Dateien geschrieben werden. Claude Code liest
diese Datei und überträgt die jeweiligen Sektionen 1:1 in die Ziel-
Dateien. Inhalte werden NICHT zusammengefasst, NICHT umformuliert,
NICHT gekürzt.

---

# SEKTION 1 — `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`

Inhalt zwischen den Markern unten 1:1 übernehmen:

<!-- BEGIN ARCHITEKTUR-REFRESH -->

# Architektur-Refresh 2026-05-07

**Status:** Verbindlich ab 2026-05-07
**Ersetzt:** Teile von STRATEGIE.md v1.0, präzisiert ARCHITEKTUR-ENTSCHEIDUNGEN.md
**Gilt für:** Alle Arbeiten ab Sprint 9.11

## Zweck

Nach 9 Sprints Implementierung und einer vollständigen Cowork-Inventarisierung
des Betterspace-Referenzsystems (46 Screens in 2 Durchgängen) wurde der
Stand des Projekts gegen die ursprüngliche Strategie geprüft. Dieses Dokument
fasst zusammen:

1. Was die Strategie bereits korrekt vorgesehen hat (Bestätigung)
2. Was die Strategie nicht oder anders gesehen hatte (Korrektur)
3. Wie der Sprint-Plan ab Sprint 9.11 angepasst wird

Dieses Dokument ist ab heute die **gemeinsame Bezugsquelle** für die drei
KI-Rollen (Strategie-Chat, Claude Code, Cowork). Bei Konflikten zwischen
diesem Dokument und älteren Dokumenten gilt dieses.

---

## 1. Was die Strategie korrekt vorgesehen hat

Die ursprüngliche Strategie (April 2026, Version 1.0) war architektonisch
solide. Cowork bestätigt:

- **Drei-Ebenen-Hierarchie** Global → Raumtyp → Raum (STRATEGIE §6.3) — exakt
  das, was Betterspace praktiziert
- **Reine Engine-Funktion** mit Layer-Pipeline (AE-06, AE-31) — sauberer
  als Betterspace-Sammelsurium aus 21 Algorithmen
- **Auditierbarkeit pro Layer** (AE-08) — vollständiger Trace, Betterspace
  hat nur einen einfachen Algorithmenverlauf
- **`scenario`/`scenario_assignment` als orthogonale Schicht** (AE-27) —
  direkte Inspiration durch Betterspace, gleiche Idee
- **Saisonale Konfiguration über `season_id`** (AE-26) — Betterspace bestätigt
  Saison-Konzept
- **Manueller Setpoint als zeitlich begrenzter Override** (AE-29) — exakt
  Betterspace „Manuelle Steuerung mit automatischer Deaktivierung"
- **DSGVO-saubere Reservation** ohne Gastnamen (AE-03) — Cowork: Betterspace
  zeigt Klarnamen, wir sind hier sauberer
- **Wetterdaten ab Tag 1** + Multi-Mandanten + API-First — alles Vorteile
  gegenüber Betterspace

## 2. Was korrigiert werden muss

Drei substantielle Korrekturen plus mehrere Klarstellungen.

### 2.1 Frostschutz zweistufig (statt absolut)

**Bisherige Strategie (§6.2 R8):** „Harte Untergrenze bei 10 °C. Nicht
verhandelbar, nicht konfigurierbar. Systemkonstante."

**Neue Strategie:** Zweistufig.

- **Hard-Cap im Code:** `FROST_PROTECTION_C = Decimal("10.0")` in
  `backend/src/heizung/rules/constants.py`. Niemand kann das per UI
  unterschreiten.
- **Raumtyp-Override (neu):** `room_type.frost_protection_c NUMERIC(4,1)
  NULL`. Default NULL → fällt auf Hard-Cap. Kann pro Raumtyp **höher**
  gesetzt werden (z. B. 12 °C für „Bad mit Handtuchwärmer"), niemals
  niedriger.

**Begründung:** Betterspace hat untere Temperaturgrenze pro Raumtyp
(Cowork S107 Use-Case 7). Reale Hotelbetriebe brauchen das, weil ein Bad
mit Wasserleitungen und Handtuchwärmer empfindlicher ist als ein Flur.
Hard-Cap bleibt als Sicherheitsnetz.

**Engine-Auswirkung:** Layer 0 (Sommer) und Layer 4 (Window) lesen
`room_type.frost_protection_c` falls gesetzt, sonst Hard-Cap. Layer 5
(Hard-Clamp) untere Grenze ist `MAX(min_temp_celsius, frost_protection_c,
HARD_CAP)`.

Verankert als **AE-42**.

### 2.2 Geräte-Lifecycle als eigene UI-Disziplin

**Bisherige Strategie (§8.3):** „Thermostate Master-Detail mit Drawer."

**Neue Strategie:** Geräte-Verwaltung ist ein eigener Sub-Bereich mit
mehreren Bausteinen:

- **Pairing-Wizard** (mehrstufig): Gerät auswählen → Zimmer wählen →
  Heizzone wählen (Schlafzimmer/Bad) → Label vergeben → Bestätigen
- **Inline-Edit** für Gerät-Label (analog Betterspace-PEQ-Nummer-Edit)
- **Sortierung nach Fehlerstatus** (Default beim Aufrufen der Geräte-Liste)
- **Health-Indikatoren** pro Zeile: Battery + Signal + Online-Status +
  Notification-Bell
- **Tausch-Workflow:** Gerät kann von Heizzone getrennt und neu zugewiesen
  werden (für Hardware-Tausch)

**Akuter Anlass:** Heute haben wir keine Funktion, um ein Gerät einer
Heizzone zuzuweisen. Vicki-001 ist via Cowork-Code direkt in der DB
verlinkt, Vicki-002/003/004 hängen frei. Das blockiert Sprint 9.11
Live-Test.

Verankert als **AE-43**.

### 2.3 Drei-Ebenen-Hierarchie braucht UI auf allen drei Ebenen

**Bisherige Strategie (§6.3):** Hierarchie textlich beschrieben, UI-Mapping
implizit.

**Neue Strategie:** Klare UI-Zuordnung pro Ebene:

| Ebene | Inhalt | Route |
|---|---|---|
| Global | 17 Globale Zeiten, 8 Globale Temperaturen, Klimaanlage-Sektion | `/einstellungen/temperaturen-zeiten` |
| Raumtyp | 4 Temperatur-Schwellen (Obere/Untere Grenze, Belegt, Frei) + Verhaltens-Flags + Frostschutz | `/raumtypen/[id]` |
| Raum | Manuelle Steuerung, Fenstererkennung erzwingen, Frühzeitiger Check-In, Referenztemperatur | Cog-Modal in `/zimmer/[id]` |

Heute haben wir nur Global (rudimentär als Singleton-Form) und Raumtyp
(rudimentär ohne Frostschutz). Pro-Raum-Overrides fehlen komplett.

### 2.4 Klarstellungen ohne Strategie-Änderung

- **Phasen-Konflikt:** STRATEGIE.md §9.3 nennt 7 Phasen, WORKFLOW.md
  beschreibt 5 Phasen. **Entscheidung:** WORKFLOW.md gewinnt, STRATEGIE
  wird auf 5 Phasen harmonisiert.
- **Sidebar:** STRATEGIE.md §8.3 sieht 14 Einträge in 5 Gruppen vor.
  Heute haben wir 7 flache Einträge. Migration in einem dedizierten
  UI-Sprint.
- **Sommer-Modus:** Hardware-Faktum (vom Hotelier bestätigt): im Sommer
  übernimmt Klimaanlage, Heizthermostate sind funktionslos. Layer-0-Fast-Path
  mit nur 2 LayerSteps ist daher korrekt — keine 6-Layer-Pipeline im
  Sommer nötig. Klima-Integration kommt als eigene Domain in Phase 2+.

## 3. Datenmodell-Anpassungen

| ID | Tabelle | Änderung |
|---|---|---|
| DB-1 | `room_type` | Neue Spalte `frost_protection_c NUMERIC(4,1) NULL` |
| DB-3 | `device` | Bestehende Spalte `label` reicht, neue API-Route nötig |

Keine weiteren Schemaänderungen. Bestehende Tabellen `scenario`,
`scenario_assignment`, `season`, `manual_setpoint_event`,
`global_config` werden in späteren Sprints erst aktiviert.

## 4. Engine-Pipeline-Anpassungen

| ID | Layer | Änderung |
|---|---|---|
| E-1 | Layer 0 (Sommer) | `frost_protection_c` aus `room_type` lesen, Fallback Hard-Cap |
| E-2 | Layer 4 (Window) | analog E-1 |
| E-3 | Layer 5 (Hard-Clamp) | untere Grenze `MAX(min_temp_celsius, frost_protection_c, HARD_CAP)` |

Layer 1, 2, 3 unverändert. Pipeline-Reihenfolge unverändert.

## 5. UI-Bauplan

Ergibt sich aus §2.3 und der Sidebar-Migration. Konkrete Routen:

| Route | Status | Sprint |
|---|---|---|
| `/zimmer/[id]/devices` (Tab) — Geräte zuordnen | fehlt | 9.11a |
| `/devices/pair` Pairing-Wizard | fehlt | 9.13 |
| `/devices` Liste mit Sortierung + Inline-Edit | erweitert | 9.13 |
| `/einstellungen/temperaturen-zeiten` Globale Zeiten/Temp | fehlt | 9.14 |
| `/profile` Wochentag-Schedule | fehlt | 9.15 |
| `/szenarien` Card-Grid | fehlt | 9.16 |
| `/einstellungen/saison` Sommer/Winter | fehlt | 9.16 |
| `/einstellungen/benutzer` mit NextAuth | fehlt | 9.17 |
| `/` Dashboard mit 6 KPI-Cards | leer | 9.18 |
| `/analyse/temperaturverlauf` | fehlt | 9.19 |
| `/einstellungen/api` API-Keys + Webhooks | fehlt | 9.20 |
| `/einstellungen/gateway` Gateway-Status | fehlt | 9.21 |

## 6. Sidebar-Migration

Von heute (7 flache Einträge) auf Strategie-Konform (14 Einträge in 5
Gruppen):

ÜBERSICHT
- Dashboard `/`
- Zimmerübersicht `/zimmer`
- Belegungen `/belegungen`

STEUERUNG
- Temperaturen & Zeiten `/einstellungen/temperaturen-zeiten` [NEU]
- Raumtypen `/raumtypen`
- Profile `/profile` [NEU]
- Szenarien `/szenarien` [NEU]

GERÄTE
- Thermostate `/devices`
- Pairing `/devices/pair` [NEU]
- Gateway `/einstellungen/gateway` [NEU, später]

ANALYSE
- Algorithmenverlauf — Tab in `/zimmer/[id]` (existiert)
- Temperaturverlauf `/analyse/temperaturverlauf` [NEU, später]

EINSTELLUNGEN
- Hotel `/einstellungen/hotel`
- Saison `/einstellungen/saison` [NEU, später]
- Benutzer `/einstellungen/benutzer` [mit NextAuth]
- API & Webhooks `/einstellungen/api` [NEU, später]

Migration in Sprint 9.13 (mit Geräte-Pairing).

## 7. Sprint-Plan-Adaption

Detaillierter Sprint-Plan in `docs/SPRINT-PLAN.md`. Übersicht:

| Sprint | Inhalt | Priorität |
|---|---|---|
| 9.11 | Live-Test #2 (minimal, mit DB-Hack-Zuordnung) | jetzt |
| 9.11a | API-Endpoint Geräte-Zuordnung (Quick Fix) | sofort |
| 9.12 | Frostschutz pro Raumtyp (DB + Engine + API) | hoch |
| 9.13 | Geräte-Pairing-UI + Sidebar-Migration | hoch |
| 9.14 | Globale Temperaturen + Zeiten UI | hoch |
| 9.15 | Profile (Wochentag-Schedule) | mittel |
| 9.16 | Szenarien + Saison UI | mittel |
| 9.17 | NextAuth + User-UI | hoch (vor Go-Live) |
| 9.18 | Dashboard mit KPI-Cards | mittel |
| 9.19 | Temperaturverlauf-Analytics | niedrig |
| 9.20 | API-Keys + Webhooks | niedrig |
| 9.21 | Gateway-Status-UI | niedrig |
| 10 | Hygiene-Sprint (alle B-9.10*-Backlog) | hoch (vor Final-Tag) |
| 11 | PMS-Casablanca-Integration | hoch (vor Go-Live) |
| 12 | Backup + Production-Migration | hoch (vor Go-Live) |
| 13 | Wetterdaten-Service aktivieren | mittel |
| 14 | Final-Tag `v1.0.0` + Go-Live | Meilenstein |

## 8. Was bleibt unberührt

- **Engine-Logik:** 6-Layer-Pipeline + Hysterese ist korrekt und
  auditierbar. Keine Refactors.
- **Datenbank:** alle 16 Modelle bleiben. Nur eine neue Spalte (DB-1).
- **Stabilitätsregeln S1-S6** (CLAUDE.md §0): bleiben verbindlich,
  werden zusätzlich als AE-44 ins ADR-Log gehoben.
- **Autonomie-Default Stufe 2** (CLAUDE.md §0.1): bleibt.
- **Design-Strategie 2.0.1:** bleibt verbindlich.
- **WORKFLOW.md** Phasen-Modell: bleibt verbindlich, STRATEGIE wird daran
  angepasst.

## 9. Was als veraltet markiert wird

Folgende Inhalte gelten ab heute als historisch — sie werden nicht
gelöscht, aber dürfen nicht mehr für neue Pläne herangezogen werden:

- STRATEGIE.md §6.2 R8 alte Fassung („absolut, nicht konfigurierbar")
- STRATEGIE.md §9.3 7-Phasen-Modell (gilt: WORKFLOW.md 5 Phasen)
- Alle Sprint-Briefe in `docs/features/` mit Datum vor 2026-05-07
  (gilt: SPRINT-PLAN.md)
- STATUS.md §6 alter Backlog (gilt: STATUS.md §6 nach Refresh-Update)

## 10. Wie KI-Sessions ab heute starten

Siehe `docs/SESSION-START.md`. Erste Aktion in jeder neuen Session:

> „Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."

<!-- END ARCHITEKTUR-REFRESH -->

---

# SEKTION 2 — `docs/SPRINT-PLAN.md`

Inhalt zwischen den Markern unten 1:1 übernehmen:

<!-- BEGIN SPRINT-PLAN -->

# Sprint-Plan — Heizungssteuerung Hotel Sonnblick

**Status:** Verbindlich ab 2026-05-07
**Letzte Aktualisierung:** 2026-05-07 (Architektur-Refresh)
**Ersetzt:** Alle Sprint-Briefe in `docs/features/` mit Datum vor 2026-05-07
**Bezug:** ARCHITEKTUR-REFRESH-2026-05-07.md

## Konventionen

- **Sprint-Nummern** sind fortlaufend ab 9.11 (alles davor abgeschlossen)
- **Sub-Sprints** mit Suffix a/b/c für Hotfixes oder Aufteilungen (z. B. 9.11a)
- **Autonomie-Stufen** nach CLAUDE.md §0.1: 1=Engine-Concurrency, 2=Standard,
  3=Markdown-only
- **Definition of Done** gilt pro Sprint zusätzlich zu globaler DoD
- **Meilensteine** sind harte Tags, die nie ohne Strategie-Chat-Freigabe
  gesetzt werden
- **Priorität:** 🔴 blockierend, 🟡 wichtig, 🟢 nice-to-have

## Globale Definition of Done (gilt für alle Sprints)

- Backend: ruff clean, `ruff format --check` clean, mypy strict clean,
  pytest grün
- Frontend: tsc clean, eslint clean, build erfolgreich
- CI: alle required checks grün auf HEAD
- Branch: feature → develop merged via PR, Branch gelöscht (lokal+remote)
- Doku: STATUS.md §2x ergänzt, ggf. CLAUDE.md §5.x für neue Lessons
- Tag: nur nach Strategie-Chat-Freigabe

## Aktueller Stand (Stichtag 2026-05-07)

- Engine-Pipeline 0/1/2/3/4/5 + Hysterese vollständig
- 4 Vickis liefern Sensordaten auf heizung-test
- Tag `v0.1.9-rc5-trace-consistency` auf develop
- Architektur-Refresh durchgeführt
- Geräte-Zuordnungs-Loch: nur Vicki-001 in DB zugeordnet, 002/003/004 frei

---

# SPRINT 9.11 — Live-Test #2 (Minimal)

**Priorität:** 🔴
**Geschätzte Dauer:** 2-3 h Live-Zeit + 1 h Auswertung
**Autonomiestufe:** 1
**Voraussetzung:** Sprint 9.11a (API-Endpoint für Geräte-Zuordnung)
**Tag nach Abschluss:** `v0.1.9-rc6-live-test-2`

## Ziel

Vollständige Verifikation der Engine-Pipeline (Layer 0–5 + Hysterese) auf
heizung-test mit echter Hardware. Jeder Layer wird gezielt getriggert,
Engine-Decision-Panel als QA-Tool genutzt.

## Vorgehen

Phase 0 (Pre-Test-Checks) → Test-Matrix T1-T8 mit Stop-Points →
Sprint-Bericht. **Kein Code, nur Validierung.**

## Test-Matrix

| # | Layer | Auslöser | Vicki | Erwartung |
|---|-------|----------|-------|-----------|
| T1 | L4 Window | Vicki vom HK abnehmen | 001 | open_zones populated, Setpoint = Frostschutz |
| T2 | L1 Base | Belegung occupied | 001 | Setpoint 21°C, Downlink |
| T3 | L2 Vorheizen | Belegung Check-in in 30 min | 002 | Setpoint = occupied-Vorheizwert |
| T4 | L2 Nachtabsenkung | Zeitfenster 22:00-06:00 | 003 | Setpoint = 18°C |
| T5 | L3 Manual | Manueller Setpoint via API | 004 | reason MANUAL_OVERRIDE |
| T6 | L5 Hard-Clamp | Override 30°C im Bad | 004 (Bad) | clamped auf 24°C |
| T7 | Hysterese | Kleine Setpoint-Änderung <1°C | 001 | Downlink unterdrückt |
| T8 | Trace-Vollständigkeit | beliebig | 001 | 6 LayerSteps + Hysterese-Footer |

## Definition of Done

- Pro T-Stop-Point: dokumentierter Befund Pass/Fail + Beweise
  (DB-Query, Engine-Trace, ggf. Vicki-Display)
- Sprint-Bericht in STATUS.md §2t
- Bei Bug-Fund: Hotfix-Sub-Sprint 9.11x

## Risiken

- Geräte-Zuordnungs-Loch (durch 9.11a behoben)
- Sommer-Modus aktiv → Heiz-Pipeline läuft nicht (auf heizung-test bereits
  deaktiviert, verifiziert in Phase 0)
- Hardware-Ausfälle Vicki während Test → Backlog, nicht 9.11-Stopper

---

# SPRINT 9.11a — Geräte-Zuordnungs-API (Quick Fix vor 9.11)

**Priorität:** 🔴
**Geschätzte Dauer:** 1-2 h
**Autonomiestufe:** 2
**Voraussetzung:** keine
**Tag nach Abschluss:** kein Tag (Sub-Sprint)

## Ziel

Minimal-API, um Vicki-002/003/004 produktiv einer Heizzone zuzuordnen.
Kein UI, nur Backend. Damit ist 9.11 fahrbar.

## User Stories

- Als Admin will ich via API ein Gerät einer Heizzone zuweisen können
- Als Admin will ich die Zuweisung wieder aufheben können

## Tasks

- T1: Pydantic-Schema `DeviceAssignZoneRequest`/`Response`
- T2: Route `PUT /api/v1/devices/{id}/heating-zone` mit Body
  `{ heating_zone_id }`
- T3: Route `DELETE /api/v1/devices/{id}/heating-zone` (Detach)
- T4: Pytest-Test (DB-Skip-konform): assign, re-assign, detach
- T5: Curl-Beispiele in RUNBOOK.md §11

## Definition of Done

- API funktional via curl auf heizung-test getestet
- Vicki-002/003/004 sind Heating-Zones zugewiesen (Zimmer 102/103/104
  jeweils Schlafzimmer)
- DB-Query bestätigt 4 zugeordnete Vickis
- RUNBOOK §11 dokumentiert die curl-Befehle für späteren Hardware-Tausch

---

# SPRINT 9.12 — Frostschutz pro Raumtyp

**Priorität:** 🔴
**Geschätzte Dauer:** 2-3 h
**Autonomiestufe:** 1 (Engine-Touch)
**Voraussetzung:** 9.11 abgeschlossen
**Tag nach Abschluss:** `v0.1.10-frost-protection`

## Ziel

Zweistufige Frostschutz-Logik aus AE-42 implementieren.

## Tasks

- T1: Alembic-Migration: `room_type.frost_protection_c NUMERIC(4,1) NULL`
- T2: SQLAlchemy-Model erweitern, Pydantic-Schema erweitern
- T3: Engine-Code: Helper `_resolve_frost_protection(room_type)` baut
  effective floor aus `room_type.frost_protection_c` oder Hard-Cap
- T4: Layer 0 (`layer_summer_mode`) nutzt Helper im Aktiv-Pfad
- T5: Layer 4 (`layer_window_open`) nutzt Helper bei `open_window=true`
- T6: Layer 5 (`layer_clamp`) untere Grenze =
  `MAX(min_temp_celsius, frost_protection_c, HARD_CAP)`
- T7: API-PATCH-Route `/api/v1/room-types/{id}` ergänzt um Feld
- T8: Tests: pro Layer ein Frostschutz-Override-Test
- T9: STATUS.md §2u + ARCHITEKTUR-ENTSCHEIDUNGEN.md AE-42 finalisieren

## Definition of Done (zusätzlich)

- Bad-Raumtyp im Hotel Sonnblick auf 12°C frost_protection_c gesetzt
  (verifiziert via DB-Query)
- Engine-Trace zeigt im Window-Test bei Bad-Zimmer Setpoint 12°C statt 10°C

---

# SPRINT 9.13 — Geräte-Pairing-UI + Sidebar-Migration

**Priorität:** 🔴
**Geschätzte Dauer:** 4-6 h (in 2 Tasks-Bündeln über 2 Sessions)
**Autonomiestufe:** 2
**Voraussetzung:** 9.11a (API existiert)
**Tag nach Abschluss:** `v0.1.11-device-pairing`

## Ziel

Vollständige UI für Geräte-Lifecycle plus Sidebar-Reorganisation auf
14-Eintrag-Struktur.

## Tasks Bündel A (Pairing)

- TA1: `/devices/pair` Wizard-Komponente (4 Schritte: Gerät auswählen →
  Zimmer → Heizzone → Label → Bestätigen)
- TA2: `/zimmer/[id]/devices` Tab — Liste der zugeordneten Geräte +
  „Detach"-Button
- TA3: Inline-Edit für `device.label` in `/devices`-Liste
- TA4: Sortierung `/devices` nach Fehlerstatus (Default)

## Tasks Bündel B (Sidebar-Migration)

- TB1: Sidebar-Komponente auf 5 Gruppen umbauen
- TB2: Neue Routen-Stubs anlegen (Empty-State-Pages für Profile,
  Szenarien, Saison, Gateway, API, Temperaturverlauf, Benutzer)
- TB3: Bestehende Routen in neue Gruppen einsortieren
- TB4: Mobile-Sidebar-Verhalten testen

## Definition of Done

- Pairing-Wizard funktional, alle 4 Vickis können neu zugeordnet werden
- Sidebar zeigt 14 Einträge in 5 Gruppen
- Empty-States für noch nicht implementierte Sektionen sichtbar
- Cowork-Smoketest: alle 14 Sidebar-Einträge erreichbar

---

# SPRINT 9.14 — Globale Temperaturen + Zeiten UI

**Priorität:** 🟡
**Geschätzte Dauer:** 3-4 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.13 (Sidebar)
**Tag nach Abschluss:** `v0.1.12-global-config-ui`

## Ziel

Settings-Layout für `global_config` und `rule_config` Scope=GLOBAL.

## Tasks

- T1: `/einstellungen/temperaturen-zeiten` Settings-Layout mit Sub-Nav
  (Tabs: Globale Zeiten / Globale Temperaturen / Klimaanlage)
- T2: Inline-Edit pro Wert (analog Betterspace-Pattern)
- T3: Zod-Validierung für Zeit-Werte (HH:MM) und Temperatur-Werte (Range)
- T4: API-PATCH `/api/v1/global-config` und `/api/v1/rule-configs/global`
- T5: Audit-Trail: jede Änderung in `event_log` als CONFIG_CHANGE

## Akzeptanzkriterien

- Hotelier kann globale Werte ändern, ohne Code-Deployment
- Engine liest Werte beim nächsten Beat-Tick (max 60s Verzögerung)
- Änderungs-History sichtbar im Algorithmenverlauf

---

# SPRINT 9.15 — Profile (Wochentag-Schedule)

**Priorität:** 🟡
**Geschätzte Dauer:** 4-5 h
**Autonomiestufe:** 1 (Engine-Touch — neue Layer-Quelle)
**Voraussetzung:** 9.14
**Tag nach Abschluss:** `v0.1.13-profiles`

## Ziel

Profile-Konzept einführen: wiederverwendbare Wochentag-Schedules, die
auf Räume oder Raumtypen angewendet werden können.

## Tasks

- T1: Neue Tabelle `profile` (id, name, description) + `profile_entry`
  (profile_id, weekday, time_from, time_to, t_target)
- T2: Verknüpfung `profile_id` an `rule_config` (NULL = kein Profil aktiv)
- T3: Engine-Layer 2 (Temporal) erweitert: prüft erst Profil, dann Standard-
  Nachtabsenkung
- T4: `/profile` Master-Detail mit Tabs pro Wochentag, Inline-Editierbar
- T5: Tests: Profil-Override schlägt Standard-Nacht, Profil-Lücke fällt
  auf Standard

---

# SPRINT 9.16 — Szenarien + Saison UI

**Priorität:** 🟡
**Geschätzte Dauer:** 4-5 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.15
**Tag nach Abschluss:** `v0.1.14-scenarios-seasons`

## Ziel

Aktivierung der bereits angelegten `scenario`/`scenario_assignment` plus
`season`-Tabellen.

## Tasks

- T1: `/szenarien` Card-Grid mit vordefinierten Szenarien (Wartung,
  Schließzeit, Renovierung, Sommerbetrieb)
- T2: Szenario-Aktivierung: Toggle pro Raumtyp/Raum mit
  `scenario_assignment` als Pivot
- T3: `/einstellungen/saison` Card-Grid Sommer/Winter mit Tag-Monat-Range
- T4: Saisonale `rule_config` über `season_id`-FK
- T5: Engine: Saison-Auflösung in `_load_room_context`

---

# SPRINT 9.17 — NextAuth + User-UI

**Priorität:** 🔴 (vor Go-Live)
**Geschätzte Dauer:** 5-7 h
**Autonomiestufe:** 1 (Auth-Flow)
**Voraussetzung:** 9.13 (Sidebar)
**Tag nach Abschluss:** `v0.1.15-auth`

## Ziel

NextAuth + rollenbasierte Permissions (Owner / Admin / Hotelier /
Techniker / Reception). Multi-Mandanten-fähig (Sprint 11 Vorbereitung).

## Tasks

- T1: NextAuth-Setup mit Credentials-Provider, JWT
- T2: User-Tabelle, Role-Tabelle, User-Hotel-Pivot
- T3: Middleware für Route-Protection in Next.js
- T4: API-Endpoint-Schutz mit Role-Check (FastAPI Dependency)
- T5: `/einstellungen/benutzer` Settings-Layout mit User-Liste +
  Add/Remove/Role-Edit
- T6: Login-Page mit Hotel-Auswahl (für Multi-Tenant)
- T7: Tests: Role-Matrix-Tests (5 Rollen × 5 Routen)

---

# SPRINT 9.18 — Dashboard mit KPI-Cards

**Priorität:** 🟡
**Geschätzte Dauer:** 3-4 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.17 (User-Begrüßung braucht Auth)
**Tag nach Abschluss:** `v0.1.16-dashboard`

## Ziel

Dashboard mit 6 KPI-Cards (Strategie §8.4): Belegung, Ø-Temperatur,
Geräte-Online, Energiestatus, Nächster Check-in, Außentemperatur.

## Tasks

- T1: API-Aggregations-Route `/api/v1/dashboard/kpi`
- T2: Frontend `/` mit 6 KPI-Cards
- T3: Begrüßung „Hallo, [Name]" mit User-Session
- T4: Refresh alle 60s

---

# SPRINT 9.19 — Temperaturverlauf-Analytics

**Priorität:** 🟢
**Geschätzte Dauer:** 4-5 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.18
**Tag nach Abschluss:** `v0.1.17-analytics`

## Ziel

Eigene Analytics-Seite mit Temperaturverlauf-Chart pro Zimmer/Raum,
Zeitraum-Filter, Wunsch- vs. Ist-Temperatur (analog Betterspace).

## Tasks

- T1: API `/api/v1/analytics/temperature-history` mit Zeitraum-Param
- T2: Recharts Line-Chart, Wunsch + Ist als zwei Linien
- T3: Filter: Zeitraum, Raum, Gerät
- T4: TimescaleDB-Aggregation für lange Zeiträume

---

# SPRINT 9.20 — API-Keys + Webhooks

**Priorität:** 🟢
**Geschätzte Dauer:** 4 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.17
**Tag nach Abschluss:** `v0.1.18-api-webhooks`

## Ziel

API-Keys für externe Integrationen (Sprint 11 Casablanca-PMS) und
Webhooks für Outbound-Events.

## Tasks

- T1: Tabelle `api_key` + `webhook_subscription`
- T2: Auth-Middleware für API-Key-Header
- T3: `/einstellungen/api` Settings-Layout
- T4: Webhook-Dispatcher als Celery-Task

---

# SPRINT 9.21 — Gateway-Status-UI

**Priorität:** 🟢
**Geschätzte Dauer:** 2-3 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.13
**Tag nach Abschluss:** kein eigener Tag (kleine UI-Erweiterung)

## Ziel

`/einstellungen/gateway` zeigt ChirpStack-Status, letzte Heartbeats,
verbundene Geräte.

## Tasks

- T1: API `/api/v1/gateway/status` (proxied an ChirpStack-API)
- T2: Settings-Layout mit Status-Cards
- T3: Refresh alle 30s

---

# SPRINT 10 — Hygiene-Sprint

**Priorität:** 🔴 (vor Final-Tag `v0.1.9-engine`)
**Geschätzte Dauer:** 4-5 h
**Autonomiestufe:** 2
**Voraussetzung:** 9.11 abgeschlossen (alle Live-Test-Befunde gefixt)
**Tag nach Abschluss:** `v0.1.19-hygiene`

## Ziel

Alle B-9.10*-Backlog-Punkte abräumen.

## Tasks

- T1: B-9.10d-1 detail-Konvention auf snake_case-Tokens vereinheitlichen
- T2: B-9.10d-2 mypy-Vorlast 71 Errors in tests/ beheben
- T3: B-9.10d-3 Type-Inkonsistenz Engine `int` vs. EventLog `Decimal`
- T4: B-9.10d-5 engine_tasks DB-Session per Dependency-Injection
- T5: B-9.10d-6 Pre-Push-Hook für `ruff format --check`
- T6: B-9.10-6 psycopg2-Failures
- T7: B-9.10c-1 ChirpStack-Codec-Bootstrap-Skript
- T8: B-9.11-1 celery_beat Healthcheck korrigieren

---

# SPRINT 11 — PMS-Casablanca-Integration

**Priorität:** 🔴 (vor Go-Live)
**Geschätzte Dauer:** 8-10 h (in 2-3 Sub-Sprints)
**Autonomiestufe:** 1 (externe Integration)
**Voraussetzung:** 9.17 (Auth + API-Keys)
**Tag nach Abschluss:** `v0.2.0-pms-casablanca`

## Ziel

Echte Anbindung an Casablanca-PMS, nicht nur Daten-Import. Polling oder
Event-basiert je nach API-Fähigkeit.

## Sub-Sprints (vorläufig)

- 11a: PMS-Connector-Skeleton + API-Spec lesen
- 11b: Polling-Implementation + Mapping-Layer
- 11c: Fallback-Logik + Audit + Tests

## Tasks (vorläufig, präzisiert in 11a)

- T1: Casablanca-API-Spec analysieren
- T2: Connector-Modul `backend/src/heizung/integrations/casablanca/`
- T3: Mapping PMS-Status → RoomStatus (konfigurierbar)
- T4: Polling-Scheduler oder Event-Listener
- T5: Fallback bei PMS-Ausfall: letzter bekannter Status mit Zeitstempel
- T6: Audit-Trail für jede PMS-Statusänderung

---

# SPRINT 12 — Backup + Production-Migration

**Priorität:** 🔴 (vor Go-Live)
**Geschätzte Dauer:** 4-6 h
**Autonomiestufe:** 1 (Production-Migration)
**Voraussetzung:** 11 abgeschlossen
**Tag nach Abschluss:** `v0.2.1-production-ready`

## Ziel

Heizung-test-Stand auf heizung-main übertragen. Backup-Strategie
operativ.

## Tasks

- T1: Backup-Cron auf db-Container (TimescaleDB-Backup, off-site)
- T2: Restore-Test (Disaster Recovery Drill)
- T3: heizung-main Bootstrap (Compose, .env, Caddy, ChirpStack-Codec
  via B-9.10c-2)
- T4: DNS-Switch-Plan (heizung-test → heizung-main)
- T5: Smoke-Test-Plan für heizung-main
- T6: RUNBOOK §12 Production-Migration-Sektion

---

# SPRINT 13 — Wetterdaten-Service aktivieren

**Priorität:** 🟡
**Geschätzte Dauer:** 3-4 h
**Autonomiestufe:** 2
**Voraussetzung:** 12 (Production läuft)
**Tag nach Abschluss:** `v0.2.2-weather`

## Ziel

Wetterdaten-Service operativ. Heute liegt Modell `weather_observation`
vor, aber kein Service zieht Daten.

## Tasks

- T1: Wetter-API auswählen (DWD, OpenWeather, Open-Meteo)
- T2: Celery-Task `fetch_weather_observation` alle 10 min
- T3: Korrelation mit `event_log` für spätere KI-Layer-Vorbereitung
- T4: Dashboard-KPI „Außentemperatur" lesefähig

---

# SPRINT 14 — Final-Tag `v1.0.0` + Go-Live

**Priorität:** 🎯 Meilenstein
**Geschätzte Dauer:** 1 h Tag-Vergabe + Monitoring-Setup
**Autonomiestufe:** 1
**Voraussetzung:** 13 abgeschlossen + Stabilitäts-Testperiode
**Tag nach Abschluss:** `v1.0.0`

## Ziel

Offizielles Go-Live. heizung-main läuft seit mindestens 2 Wochen
stabil mit allen Sprints integriert.

## Tasks

- T1: Final-Doku-Pass: STATUS.md auf 100% reflective state
- T2: README.md für Repo-Root
- T3: Tag `v1.0.0` mit Release-Notes
- T4: Monitoring-Alert-Schwellen final justieren
- T5: Stakeholder-Mitteilung (du + Hotelier + Techniker)

---

## Meilensteine

| Tag | Bedeutung |
|---|---|
| `v0.1.9-rc6-live-test-2` | Engine-Pipeline live verifiziert |
| `v0.1.10-frost-protection` | Frostschutz-Korrektur eingebaut |
| `v0.1.11-device-pairing` | Geräte-Verwaltung produktiv |
| `v0.1.15-auth` | Multi-User produktiv |
| `v0.1.19-hygiene` | Technische Schuld abgebaut |
| `v0.2.0-pms-casablanca` | PMS-Integration produktiv |
| `v0.2.1-production-ready` | heizung-main steht |
| `v1.0.0` | Go-Live |

## Was nach Go-Live kommt (außerhalb dieses Plans)

- Klimaanlagen-Domain (Phase 2)
- KI-Layer (Layer 6+) auf Wetter+Sensor+Event-Log-Basis
- Reporting-Modul mit Energie-Verbrauchs-Auswertung
- Multi-Hotel-Rollout (Tenant 2, 3, ...)
- iOS/Android-Apps für Hotelier-Mobile-Use

<!-- END SPRINT-PLAN -->

---

# SEKTION 3 — `docs/SESSION-START.md`

Inhalt zwischen den Markern unten 1:1 übernehmen:

<!-- BEGIN SESSION-START -->

# Session-Start — Pflicht-Pre-Read für jede KI-Session

**Status:** Verbindlich ab 2026-05-07
**Gültig für:** Strategie-Chat (Claude.ai), Claude Code, Cowork
**Bezug:** ARCHITEKTUR-REFRESH-2026-05-07.md

## Trigger-Phrase

Bei jedem neuen Chat / jeder neuen Task / jedem neuen Auftrag sagt der
User als ersten Satz:

> **„Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."**

Die KI antwortet mit:

1. Welche Dokumente sie gelesen hat (Liste)
2. Welche Rolle sie einnimmt (Strategie / Code / Cowork)
3. Welcher Sprint aktuell ist (aus STATUS.md §2 jüngster Eintrag)
4. Welche Backlog-Punkte aktuell offen sind (Top 3 nach Priorität)
5. Bestätigt, dass historische Sprint-Briefe in `docs/features/` mit
   Datum vor 2026-05-07 nicht für neue Pläne herangezogen werden

Wenn die Antwort unvollständig ist: User antwortet **„Stop, lies nochmal
SESSION-START.md."**

## Pflicht-Lese-Liste pro Rolle

### Strategie-Chat (Claude.ai-Web/App, plant + reviewt)

In dieser Reihenfolge lesen:

1. `docs/SESSION-START.md` (dieses Dokument)
2. `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` (Master)
3. `docs/SPRINT-PLAN.md` (aktueller + nächster Sprint)
4. `STATUS.md` §1 (Aktueller Stand) + §2 letzter Eintrag
5. `CLAUDE.md` §0 (Stabilitätsregeln) + §0.1 (Autonomie-Default)
6. `docs/AI-ROLES.md` (eigene Rolle)

**Was die Strategie-Chat-Rolle tut:**
- Sprint-Briefe schreiben
- Tasks in Claude-Code-Aufträge zerlegen
- Architektur-Entscheidungen mitentwickeln
- Reviews + Befunde auswerten
- Dokumentation aktualisieren

**Was sie NICHT tut:**
- Code schreiben (außer Snippets <20 Zeilen für Diskussion)
- Direkt deployen
- Eigenmächtig Sprint-Plan ändern

### Claude Code (CLI im Repo, programmiert)

In dieser Reihenfolge lesen:

1. `docs/SESSION-START.md`
2. `CLAUDE.md` (komplett — alle Lessons §5.x)
3. `docs/SPRINT-PLAN.md` (nur den aktuellen Sprint-Eintrag)
4. `STATUS.md` §1
5. Ggf. `RUNBOOK.md` für SSH/Deploy-Kontext
6. Den vom Strategie-Chat gelieferten Brief (im User-Prompt)

**Was Claude Code tut:**
- Code schreiben nach Brief 1:1
- Tests schreiben + ausführen
- Lokal builden, ruff + mypy + pytest grün halten
- Branches anlegen, committen, pushen
- PRs erstellen, mergen nach Freigabe
- Tags vergeben nach Freigabe

**Was Claude Code NICHT tut:**
- Eigenmächtig vom Brief abweichen
- Architektur ändern ohne Strategie-Chat-Freigabe
- SSH auf heizung-test (User macht das, Claude Code formuliert nur die
  Befehle)
- Sprint-Plan oder STATUS.md überschreiben außer im definierten Sprint-Doku-Task

### Cowork (Browser-Agent, testet visuell)

In dieser Reihenfolge lesen:

1. `docs/SESSION-START.md` (dieses Dokument)
2. Den vom User gelieferten Test-Brief (im Auftrag selbst)
3. `Design-Strategie-2_0_1.docx` (UI-Konventionen, falls relevant)

**Was Cowork tut:**
- Visuelles Klicken nach Auftrag
- Screenshots, JSON-Dokumentation
- Smoke-Tests von neuen UI-Strecken
- Inventarisierung externer Systeme

**Was Cowork NICHT tut:**
- Daten ändern (Speichern, Senden, Anwenden, Löschen, Reset)
- Eigenmächtige Vergleiche oder Bewertungen
- Sprint-Plan oder Architektur-Vorschläge

## Source-of-Truth-Hierarchie

Bei Konflikt zwischen Dokumenten gilt diese Reihenfolge (oben schlägt
unten):

1. `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
2. `docs/SPRINT-PLAN.md`
3. `STATUS.md` (für laufenden Stand)
4. `CLAUDE.md` (für Stabilitätsregeln + Lessons)
5. `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
6. `docs/STRATEGIE.md`
7. `docs/RUNBOOK.md`
8. `docs/WORKFLOW.md`
9. `Design-Strategie-2_0_1.docx`

Alles in `docs/features/` mit Datum vor 2026-05-07 ist **historisch** —
gilt nicht mehr für Pläne, gilt für Lessons, falls dort enthalten.

## Was als „nicht mehr gültig" markiert ist

Folgende Inhalte gelten ab 2026-05-07 als überholt:

- **STRATEGIE.md §6.2 R8 (alte Fassung)**: „Frostschutz absolut, nicht
  konfigurierbar". → Gilt jetzt: zweistufig (siehe AE-42)
- **STRATEGIE.md §9.3 (7-Phasen-Modell)**: → Gilt jetzt: 5 Phasen aus
  WORKFLOW.md
- **Alle Sprint-Briefe in `docs/features/` mit Datum vor 2026-05-07**:
  → Gilt jetzt: SPRINT-PLAN.md
- **STATUS.md §6 (alter Backlog)**: → Gilt jetzt: STATUS.md §6 nach
  Refresh-Update mit BR-1 bis BR-15

## Wenn die KI alte Logik wiedergibt

Symptom: Eine KI sagt „laut Strategie ist Frostschutz nicht konfigurierbar"
oder „nächster Sprint ist 9.11 mit allen Layern auf einmal".

Reaktion User: **„Stop. Lies ARCHITEKTUR-REFRESH-2026-05-07.md §2.1
[oder §3 / §7] und korrigiere."**

Das passiert in den ersten 2-3 Wochen häufig, weil ältere Embeddings
durchschlagen. Konsequente Korrektur durch Dokument-Verweis ist die
wirksamste Mitigation.

## Pflicht-Bestätigung am Ende

Nach Lesen der Pflicht-Liste antwortet die KI im Klartext:

```
SESSION-START bestätigt — 2026-05-07
Rolle: <Strategie / Code / Cowork>
Gelesen: <Dokumentenliste>
Aktueller Sprint laut STATUS.md §2: <Sprint-Nummer + Ziel>
Top-3-Backlog: <BR-x, BR-y, BR-z>
Historische Sprint-Briefe vor 2026-05-07: nicht für Pläne, nur Lessons
Bereit für Auftrag.
```

Erst nach dieser Bestätigung beginnt die eigentliche Arbeit.

<!-- END SESSION-START -->

---

# SEKTION 4 — `docs/AI-ROLES.md`

Inhalt zwischen den Markern unten 1:1 übernehmen:

<!-- BEGIN AI-ROLES -->

# AI-Rollen — Drei KIs, drei Aufgaben

**Status:** Verbindlich ab 2026-05-07
**Bezug:** SESSION-START.md (operative Trigger), CLAUDE.md (Stabilitätsregeln)

## Übersicht

Im Projekt arbeiten drei KI-Instanzen mit klar getrennten Aufgaben.
Jede KI hat einen eigenen Kontext, eigenen Werkzeugsatz und eigene
Limits. Diese Trennung ist Absicht — sie verhindert, dass eine KI
sich selbst freigibt oder Domänen verwischt.

| KI | Rolle | Werkzeug | Wer redet mit ihr |
|---|---|---|---|
| **Strategie-Chat** | Architekt + Sparringpartner | Claude.ai Web/App | User direkt |
| **Claude Code** | Implementierer | CLI im Repo | User direkt |
| **Cowork** | Visueller Tester | Browser-Agent | User direkt |

Alle drei reden mit dem User, **nie miteinander direkt**. Der User ist
der Synchronisations-Punkt. Wenn KI A etwas an KI B übergeben soll,
geht das immer über den User.

## Rolle 1 — Strategie-Chat

**Wer ich bin:**
Senior-Softwarearchitekt + HVAC-Spezialist + IoT-Erfahrener +
PMS-Integrationsexperte. Sparringpartner mit kritischem Denken,
kein Ja-Sager.

**Was ich tue:**
- Sprints planen und in Tasks zerlegen (1–3 h pro Task)
- Architektur-Entscheidungen mitentwickeln und hinterfragen
- Pull-Request-Reviews und Code-Reviews bei Auszügen
- Anweisungen für Claude Code formulieren (klar, knapp, prüfbar)
- Aufträge für Cowork formulieren
- Dokumentation aktualisieren (STATUS.md, ARCHITEKTUR-ENTSCHEIDUNGEN.md,
  Sprint-Briefe, ADRs)
- Vor Fehlentscheidungen, Scope Creep und unrealistischen Erwartungen
  warnen
- Befunde aus Live-Tests und Cowork-Inventarisierungen auswerten

**Was ich NICHT tue:**
- Vollständige Code-Dateien schreiben (außer Snippets <20 Zeilen)
- Direkten Zugriff auf den Server (kein SSH, kein Deploy)
- Direkten Browser-Zugriff (außer Web-Search)
- Eigenmächtig Sprint-Plan oder Architektur ändern (immer User-Freigabe)

**Pflicht-Pre-Read pro Session:** siehe SESSION-START.md → Strategie-Chat.

**Output-Format:**
Strukturierte Antworten nach Schema:
1. Ziel
2. Annahmen (gekennzeichnet als `[Annahme]`)
3. Fachliche Logik
4. Technische Architektur
5. Datenmodell (wo relevant)
6. Beispielablauf
7. Edge Cases
8. Risiken
9. Empfehlung

Bei Sprint-Briefen zusätzlich: User Stories, Tasks, Akzeptanzkriterien,
Definition of Done.

## Rolle 2 — Claude Code

**Wer er ist:**
Implementierer im Terminal-Setup. Hat Zugriff auf das Repo lokal,
führt git/npm/pytest/ruff/mypy aus, schreibt und liest Code-Dateien.

**Was er tut:**
- Code schreiben strikt nach Brief vom Strategie-Chat
- Tests schreiben, lokal ausführen, grün halten (ruff, ruff format,
  mypy strict, pytest)
- Branches anlegen, committen, pushen, PRs erstellen
- Nach User-Freigabe mergen, Tags vergeben
- Live-Verify-SSH-Befehle FORMULIEREN (nicht ausführen — User pastet
  die in seine eigene Session)

**Was er NICHT tut:**
- Eigenmächtig vom Brief abweichen (Stop-Point bei Ambiguitäten)
- SSH oder Deploy direkt
- Architektur ändern ohne neue Strategie-Chat-Brief
- Sprint-Plan oder STATUS.md überschreiben außer im definierten Doku-Task
- Direkt mit Cowork oder Strategie-Chat reden

**Autonomiestufen** (CLAUDE.md §0.1):
- **Stufe 1:** Engine-Concurrency, neue Architektur, Hardware-Pfade →
  alle Stop-Points pflicht
- **Stufe 2:** Standard-Sprints → Brief-1:1, dann Stop vor PR
- **Stufe 3:** Markdown-only, Dependency-Bumps → Auto-Continue durch
  bis PR

**Pflicht-Pre-Read pro Task:** siehe SESSION-START.md → Claude Code.

**Output-Format:**
Bericht pro Sprint-Schritt:
- Diff-Stats
- Tool-Outputs (ruff/mypy/pytest/tsc/lint)
- Welche Tests angepasst wurden + Begründung
- Auffälligkeiten oder Abweichungen vom Brief
- Stop-Point-Bestätigung („Warte auf Freigabe für …")

## Rolle 3 — Cowork

**Wer er ist:**
Browser-Agent, kann Webseiten öffnen, klicken, Screenshots machen,
strukturierte Dokumentation erzeugen.

**Was er tut:**
- Visuelle Inventarisierung externer Systeme (z. B. Betterspace)
- Smoke-Tests neuer UI-Strecken in unserem System
- UI-Verhalten in Edge Cases nachstellen (Belegung, Override, Filter)
- Screenshots zur Dokumentation oder Bug-Belege
- Strukturierte JSON-Outputs nach vorgegebenem Schema

**Was er NICHT tut:**
- Daten ändern (Speichern, Senden, Anwenden, Löschen, Reset, Übertragen)
  — bestätigte Schreib-Aktionen NUR auf expliziten User-Befehl pro
  einzelner Aktion
- Bewertungen oder Vergleiche zu anderen Systemen
- Architektur- oder Implementierungs-Vorschläge
- Direkt mit Claude Code oder Strategie-Chat reden
- Eigenmächtig Klick-Pfade improvisieren, die nicht im Auftrag stehen

**Pflicht-Pre-Read pro Auftrag:** siehe SESSION-START.md → Cowork.

**Output-Format:**
JSON nach im Auftrag spezifiziertem Schema. Plus Liefer-Bericht mit:
- Anzahl dokumentierter Screens
- Geschätzte Klick-Zeit
- Wo gestoppt und warum
- Drei größte Unsicherheiten
- Größte Überraschung

## Übergaben zwischen den Rollen

Übergaben laufen IMMER über den User. Beispiele:

**Strategie → Claude Code:**
User kopiert den Strategie-Chat-Brief in einen neuen Claude-Code-Prompt
mit voranstehendem „Architektur-Refresh aktiv ab 2026-05-07. …"

**Claude Code → Strategie:**
User kopiert Claude-Code-Bericht in den Strategie-Chat zur Auswertung.

**Strategie → Cowork:**
User kopiert den Strategie-Chat-Auftrag in einen neuen Cowork-Auftrag.

**Cowork → Strategie:**
User legt Cowork-Outputs in den Projekt-Ordner, Strategie-Chat liest
sie über project_knowledge_search.

**Wichtig:** Eine KI darf nie behaupten, mit einer anderen KI „direkt
gesprochen" zu haben. Wenn das passiert: Stop-Point, User klärt.

## Fehlerbilder und Reaktionen

| Symptom | Ursache | Reaktion |
|---|---|---|
| KI antwortet ohne SESSION-START-Bestätigung | Trigger-Phrase fehlte | User: „Lies SESSION-START.md und bestätige." |
| KI bezieht sich auf alte Strategie-Inhalte | Embedding-Drift, kein Refresh-Read | User: „Stop. Lies ARCHITEKTUR-REFRESH-2026-05-07.md §X." |
| Claude Code committet ohne PR | Brief-Abweichung | User: revert, neuer Brief mit klarem Stop-Point |
| Cowork ändert Daten | Auftrag-Verstoß | User: Stop, ggf. Daten manuell zurücksetzen |
| Strategie-Chat schreibt zu viel Code | Rollen-Verwischung | User: „Das ist Claude-Code-Job. Schreibe stattdessen einen Brief." |

## Wenn eine KI-Rolle erweitert werden muss

Wenn neue Aufgaben dazukommen (z. B. „Strategie soll auch ML-Modelle
trainieren") wird AI-ROLES.md aktualisiert, **bevor** die Aufgabe
ausgeführt wird. Erweiterung ist Strategie-Chat-Aufgabe, nie
Selbst-Erweiterung durch die jeweilige KI.

<!-- END AI-ROLES -->

---

# SEKTION 5 — STRATEGIE.md Patches

## Patch 5.1.1 — Header-Versionsstempel

Suchen: Strings `Stand: April 2026` und `Version: 1.0`
Ersetzen: `Stand: 2026-05-07 (Architektur-Refresh)` und `Version: 1.1`

Falls Suchstellen nicht textgleich gefunden: einen Hinweis-Block direkt
nach der ersten H1 oder H2 einfügen mit folgendem Inhalt:

```
> **Hinweis (2026-05-07):** Dieses Dokument wurde überarbeitet. Korrekturen
> in §6.2 R8 (Frostschutz) und §9.3 (Phasen-Modell). Die maßgebliche
> Quelle für aktuelle Pläne ist `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
> sowie `docs/SPRINT-PLAN.md`.
```

## Patch 5.1.2 — §6.2 R8 Frostschutz

Suchen: einen Block, der mit `R8 — Frostschutz` beginnt und mit der
Aussage zur Systemkonstanten 10°C endet.

Ersetzen mit:

```
R8 — Frostschutz (zweistufig, ab 2026-05-07, AE-42)

Frostschutz wird in zwei Ebenen modelliert:

1. **Hard-Cap im Code:** `FROST_PROTECTION_C = Decimal("10.0")` in
   `backend/src/heizung/rules/constants.py`. Diese Konstante kann
   niemand per UI ändern. Sie ist absoluter Boden für jeden Setpoint.

2. **Raumtyp-Override (optional):** `room_type.frost_protection_c
   NUMERIC(4,1) NULL`. Default NULL → fällt auf Hard-Cap. Kann pro
   Raumtyp **höher** gesetzt werden (z. B. 12 °C für Bad mit
   Handtuchwärmer), niemals niedriger als Hard-Cap.

Der effektive Frostschutz für einen Raum ist
`MAX(HARD_CAP, room_type.frost_protection_c)`. Engine-Layer 0 (Sommer),
Layer 4 (Window-Detection) und Layer 5 (Hard-Clamp) lesen diesen Wert.

Begründung: Cowork-Inventarisierung 2026-05-07 zeigte, dass Betterspace
untere Temperaturgrenzen pro Raumtyp führt. Reale Hotelbetriebe brauchen
das, weil Wasserleitungen in Bädern bei niedrigeren Temperaturen
empfindlicher sind als trockene Flure. Hard-Cap bleibt als Sicherheitsnetz
gegen Fehlkonfiguration.
```

## Patch 5.1.3 — §9.3 Phasen-Modell

Suchen: jeden Verweis auf `7 Phasen` oder `7-Phasen-Workflow`.

Ersetzen mit:

```
5-Phasen-Workflow (verbindlich, siehe `docs/WORKFLOW.md`)

Pro Feature/Sprint werden fünf Phasen durchlaufen:

1. Brief & Plan (Strategie-Chat)
2. Implementierung (Claude Code)
3. Tests & lokale Validierung (Claude Code)
4. PR & Review (Claude Code formuliert, User gibt frei)
5. Merge & Tag (Claude Code nach Freigabe)

Eine frühere Fassung dieses Dokuments nannte 7 Phasen. Die maßgebliche
Quelle ist `docs/WORKFLOW.md` mit 5 Phasen.
```

## Patch 5.1.4 — §8.3 Sidebar-Klarstellung

Anhängen am Ende von §8.3:

```
**Sidebar-Migration (Sprint 9.13):** Heute existieren 7 flache Einträge
in `frontend/src/components/sidebar.tsx`. Strategie-Konform sind 14
Einträge in 5 Gruppen (Übersicht / Steuerung / Geräte / Analyse /
Einstellungen). Migration in Sprint 9.13 zusammen mit Geräte-Pairing-UI.

Detaillierte Route-Liste in `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` §6.
```

---

# SEKTION 6 — `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` Patches

Anhängen am Ende der Datei (nach AE-41) drei neue Abschnitte:

## AE-42 Frostschutz zweistufig

```
## AE-42 — Frostschutz zweistufig (2026-05-07)

**Kontext:** Cowork-Inventarisierung Betterspace zeigt: untere
Temperaturgrenzen werden in der Praxis pro Raumtyp differenziert.
Bad mit Handtuchwärmer braucht andere untere Grenze als Flur.

**Entscheidung:** Frostschutz in zwei Ebenen.

1. Hard-Cap als Code-Konstante `FROST_PROTECTION_C = Decimal("10.0")`
   in `constants.py`. Nicht UI-änderbar.
2. Optionaler Override pro Raumtyp via Spalte
   `room_type.frost_protection_c NUMERIC(4,1) NULL`. Default NULL,
   fällt auf Hard-Cap. Kann höher gesetzt werden, nie niedriger.

Effektiver Frostschutz: `MAX(HARD_CAP, room_type.frost_protection_c)`.

Engine-Layer 0, 4, 5 lesen diesen Wert.

**Konsequenzen:**
- DB-Migration in Sprint 9.12 (eine neue Spalte)
- Engine-Helper `_resolve_frost_protection(room_type)` in `engine.py`
- Tests pro Layer mit Override

**Status:** akzeptiert
**Ersetzt:** ältere Fassung von R8 in STRATEGIE.md §6.2
```

## AE-43 Geräte-Lifecycle

```
## AE-43 — Geräte-Lifecycle als eigene UI-Disziplin (2026-05-07)

**Kontext:** Strategie sah „Thermostate Master-Detail mit Drawer".
Cowork zeigt: Betterspace behandelt Geräte-Verwaltung als komplexen
Workflow mit Pairing-Wizard, Inline-Edit, Sortierung, Tausch-Logik.
Akuter Anlass: heute haben wir keine Funktion, ein Gerät einer
Heizzone zuzuweisen — nur Vicki-001 ist via DB-Direkt-Edit verlinkt.

**Entscheidung:** Geräte-Verwaltung wird als eigenständiger Sub-Bereich
in der Sidebar geführt mit folgenden Bausteinen:

1. **API-Endpoint** zur Zuordnung Gerät→Heizzone (Sprint 9.11a)
2. **Pairing-Wizard** mehrstufig: Gerät → Zimmer → Heizzone → Label →
   Bestätigen (Sprint 9.13)
3. **Inline-Edit** für `device.label`
4. **Sortierung nach Fehlerstatus** als Default
5. **Health-Indikatoren** pro Zeile: Battery, Signal, Online-Status,
   Notification-Bell
6. **Tausch-Workflow:** Detach → Re-Attach via API

**Konsequenzen:**
- Neue Routen: `/devices/pair`, `/zimmer/[id]/devices`
- API-Erweiterungen: PUT/DELETE `/api/v1/devices/{id}/heating-zone`
- Sprint 9.11a (API-Quick-Fix), Sprint 9.13 (volle UI)

**Status:** akzeptiert
**Verstärkt:** STRATEGIE.md §8.3 Geräte-Sektion
```

## AE-44 Stabilitätsregeln S1-S6 als Architektur-Entscheidung

```
## AE-44 — Stabilitätsregeln S1-S6 (2026-05-07)

**Kontext:** Während Sprint 9.10b wurden sechs Stabilitätsregeln in
CLAUDE.md §0 verankert. Diese Regeln sind faktisch
Architektur-Entscheidungen, weil sie definieren, welche Klassen von
Mängeln das System nicht akzeptiert. Sie gehören daher auch ins ADR-Log.

**Entscheidung:** Folgende sechs Stabilitätsregeln gelten verbindlich
für jedes Sprint, jeden Code-Pfad und jede Architektur-Entscheidung:

- **S1:** Bekannte Race-Conditions, Doku-Drifts und TODO-Kommentare in
  Steuerlogik werden gefixt sobald scharf, nicht verschoben.
- **S2:** Determinismus + Idempotenz Pflicht (Locks, SETNX,
  Idempotenz-Checks).
- **S3:** Auditierbarkeit — jede Setpoint-Änderung im Engine-Trace
  sichtbar.
- **S4:** Hardware-Schutz — keine doppelten Downlinks, keine
  widersprüchlichen Setpoints.
- **S5:** Defensive bei externen Quellen (PMS, IoT, Netzwerk).
- **S6:** Komplexität trägt Beweislast — im Zweifel einfacher.

Eskalations-Regel: Wenn Sprint-Plan, Brief, PR oder Live-Deploy gegen
S1-S6 verstoßen würde → Strategie-Chat-Stop, kein Merge ohne explizite
Freigabe.

**Status:** akzeptiert
**Bezug:** CLAUDE.md §0 (operatives Pendant)
```

---

# SEKTION 7 — `STATUS.md` Patches

## Patch 5.3.1 — §1 Aktueller Stand

Suchen: bestehenden §1-Block mit Stichworten `Stichtag`, `Aktueller Branch`.

Ersetzen mit:

```
**Stichtag:** 2026-05-07
**Aktueller Branch:** develop, HEAD `654fbab` (Doku-Patch §5.24+§5.25)
**Letzter Tag:** `v0.1.9-rc5-trace-consistency`
**Nächster Sprint:** 9.11 Live-Test #2 (siehe `docs/SPRINT-PLAN.md`)
**Architektur-Refresh:** durchgeführt 2026-05-07, siehe
`docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
```

## Patch 5.3.2 — §2t Sprint 9.10d

Prüfen: ob §2t bereits existiert mit `grep -nE "^## 2t\." STATUS.md`.

Falls vorhanden: nichts tun.

Falls nicht: einen Eintrag analog zu §2r/§2s ergänzen, mit Inhalt:

```
## 2t. Sprint 9.10d Engine-Trace-Konsistenz (2026-05-07, abgeschlossen)

**Ziel:** Trace-Lücke in Layer 0 (Sommer) und Layer 2 (Temporal)
schließen, Hysterese im Frontend sichtbar.

**Tasks:** T1 Layer 0 always-on, T2 Layer 2 always-on, T2.5 Schema
LayerStep.setpoint_c None-Sentinel, T3 Tests-Erweiterung, T4 Hysterese-
Footer im Engine-Decision-Panel, T5 Doku.

**Architektur-Entscheidung:** `LayerStep.setpoint_c` von `int` auf
`int | None` erweitert. None ausschließlich für Layer 0 inactive.

**PR:** #103, Merge-Commit `f342600`
**Tag:** `v0.1.9-rc5-trace-consistency`
```

## Patch 5.3.3 — §2u Architektur-Refresh

Anhängen nach §2t:

```
## 2u. Architektur-Refresh 2026-05-07 (abgeschlossen)

**Anlass:** Cowork-Inventarisierung Betterspace zeigt drei Korrekturen
am ursprünglichen Strategiepapier sowie eine Reihe von im Plan
vorgesehenen, aber nicht implementierten Bausteinen.

**Ergebnis:**
- Neues Master-Dokument `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
- Neuer Sprint-Plan `docs/SPRINT-PLAN.md` (Sprint 9.11 bis 14
  Go-Live)
- Pflicht-Pre-Read pro Session `docs/SESSION-START.md`
- Rollen-Definition `docs/AI-ROLES.md`
- STRATEGIE.md auf Version 1.1
- Drei neue ADRs: AE-42 (Frostschutz zweistufig), AE-43
  (Geräte-Lifecycle), AE-44 (Stabilitätsregeln S1-S6 als ADR)

**Trigger-Phrase ab heute für jede neue Session:**
> „Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."

**Tag:** `v0.2.0-architektur-refresh` (nach Merge)
```

## Patch 5.3.4 — §6 Backlog komplett ersetzen

Den gesamten §6-Block durch folgenden Inhalt ersetzen. Wenn der
bestehende §6 mehrere Unter-Abschnitte hat, werden alle ersetzt.

```
## 6. Backlog

Sortierung: Priorität (🔴 blockierend, 🟡 wichtig, 🟢 nice-to-have),
innerhalb der Priorität nach Aufwand.

### 6.1 — Refresh-Aufgaben (BR-1 bis BR-15)

| ID | Inhalt | Sprint |
|---|---|---|
| BR-1 🔴 | Frostschutz pro Raumtyp (DB + Engine + API) | 9.12 |
| BR-2 🔴 | Geräte-Pairing-UI + Sidebar-Migration | 9.13 |
| BR-3 🟡 | Globale Temperaturen+Zeiten-UI | 9.14 |
| BR-4 🟡 | Profile-CRUD + UI | 9.15 |
| BR-5 🟡 | Szenarien-Aktivierung CRUD + UI | 9.16 |
| BR-6 🟡 | Saison-CRUD + UI | 9.16 |
| BR-7 🔴 | NextAuth + User-UI | 9.17 |
| BR-8 🟡 | Dashboard mit 6 KPI-Cards | 9.18 |
| BR-9 🟢 | Temperaturverlauf-Analytics | 9.19 |
| BR-10 🟢 | API-Keys + Webhooks | 9.20 |
| BR-11 🟢 | Gateway-Status-UI | 9.21 |
| BR-12 🟢 | KI-Layer-Hülle in Engine | nach Go-Live |
| BR-13 🔴 | PMS-Casablanca-Connector | 11 |
| BR-14 🟡 | Wetterdaten-Service aktiv | 13 |
| BR-15 🔴 | Backup + Production-Migration | 12 |

### 6.2 — Hygiene-Aufgaben (B-9.10*)

Werden im Hygiene-Sprint 10 abgearbeitet.

| ID | Inhalt | Priorität |
|---|---|---|
| B-9.10-1 | Fenster-Indikator in /zimmer-Liste | 🟡 |
| B-9.10-2 | Fehler-Übersicht für Devices (in BR-2 enthalten) | erledigt |
| B-9.10-6 | psycopg2-Failures | 🟡 |
| B-9.10c-1 | ChirpStack-Codec-Bootstrap-Skript | 🟡 |
| B-9.10c-2 | Codec-Re-Paste auf heizung-main bei Production-Migration | 🔴 (in 12) |
| B-9.10d-1 | detail-Konvention vereinheitlichen | 🟡 |
| B-9.10d-2 | mypy-Vorlast 71 Errors in tests/ | 🟡 |
| B-9.10d-3 | Type-Inkonsistenz Engine `int` vs. EventLog `Decimal` | 🟡 |
| B-9.10d-5 | engine_tasks DB-Session per Dependency-Injection | 🟢 |
| B-9.10d-6 | Pre-Push-Hook für `ruff format --check` | 🟢 |
| B-9.11-1 | celery_beat Healthcheck korrigieren | 🟡 |

### 6.3 — Operative Aufgaben

| ID | Inhalt | Priorität |
|---|---|---|
| OP-1 | Backup-Cron + Off-Site-Replikation auf db | 🔴 (in 12) |
| OP-2 | main-Branch-Strategie | 🟡 (vor 12) |
| OP-3 | heizung-test Kernel-Update | 🟢 |
| OP-4 | ~/.ssh/config Eintrag heizung-test | erledigt |
```

---

# SEKTION 8 — `CLAUDE.md` Patches

## Patch 5.4.1 — Neuer §0.2 Source-of-Truth-Hierarchie

Einfügen nach §0.1 (vor §1):

```
## §0.2 — Source-of-Truth-Hierarchie nach Architektur-Refresh 2026-05-07

Bei Konflikt zwischen Dokumenten gilt diese Reihenfolge (oben schlägt
unten):

1. `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
2. `docs/SPRINT-PLAN.md`
3. `STATUS.md` (für laufenden Stand)
4. `CLAUDE.md` (für Stabilitätsregeln + Lessons)
5. `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
6. `docs/STRATEGIE.md`
7. `docs/RUNBOOK.md`
8. `docs/WORKFLOW.md`
9. `Design-Strategie-2_0_1.docx`

Alles in `docs/features/` mit Datum vor 2026-05-07 ist historisch —
gilt nicht mehr für Pläne, gilt für Lessons.

**Trigger-Phrase pro Session** (siehe `docs/SESSION-START.md`):

> „Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."

Vor jeder Code-Änderung: Pflicht-Pre-Read aus SESSION-START.md →
Claude-Code-Rolle abarbeiten.
```

## Patch 5.4.2 — Neuer §5.26 Lesson

Anhängen nach §5.25:

```
### 5.26 — Strategie und Implementierung sauber trennen
(Architektur-Refresh 2026-05-07 Lesson)

Beim Refresh am 2026-05-07 zeigte sich: das Strategiepapier hatte vieles
korrekt vorgesehen, aber zwischen Strategie und Implementierung war ein
größerer Rückstand entstanden, als der Diff zwischen Strategie und
Referenzsystem (Betterspace).

**Lesson:** Bei jedem zweiten oder dritten Sprint kurz prüfen, ob die
implementierte Realität noch zur Strategie passt. Drift in einer
Richtung (Code holt Strategie ein, oder Strategie holt Realität ein) ist
normal — Drift in beide Richtungen gleichzeitig ist Refresh-Anlass.

**Konkret:**
- STATUS.md §1 alle 5 Sprints aktualisieren (nicht nur §2 anhängen)
- Strategie-Refresh nach Cowork-Inventarisierung oder externer Bestätigung
- Sprint-Plan und Backlog mindestens monatlich konsolidieren
```

---

# SEKTION 9 — Historische Sprint-Briefe markieren

In `docs/features/`: pro Datei mit Datum vor 2026-05-07 (im Dateinamen
oder Header) am Anfang folgenden Block einfügen:

```
> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.
```

Wichtig: Sprint-Briefe vom 2026-05-07 selbst (z. B. 9.10d) NICHT markieren.

---

# SEKTION 10 — Aufräumen am Ende

Nach erfolgreichem Tag-Vergabe `v0.2.0-architektur-refresh` löscht
Claude Code die Datei `docs/REFRESH-PAYLOAD.md` in einem separaten
kleinen Folge-Commit auf develop direkt:

```
git rm docs/REFRESH-PAYLOAD.md
git commit -m "chore: REFRESH-PAYLOAD.md entfernt nach v0.2.0-architektur-refresh"
git push origin develop
```

Die Datei diente nur als Quelle für den Refresh-Sprint und ist nach
Merge des PRs überflüssig.
