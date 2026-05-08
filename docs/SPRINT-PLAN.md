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
