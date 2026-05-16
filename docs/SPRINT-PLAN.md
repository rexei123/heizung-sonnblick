# Sprint-Plan — Heizungssteuerung Hotel Sonnblick

**Status:** Verbindlich ab 2026-05-15
**Letzte Aktualisierung:** 2026-05-15 (Strategie-Refresh nach
Auth-Cutover-Erfolg)
**Ersetzt:** Alle Sprint-Briefe in `docs/features/` mit Datum vor 2026-05-07
**Bezug:** `docs/STRATEGIE-REFRESH-2026-05-15.md` (Phasen-Logik),
`docs/ARCHITEKTUR-REFRESH-2026-05-07.md` (Architektur-Master)

## Phasen-Logik (verbindlich ab 2026-05-15)

Nach Auth-Cutover-Erfolg auf heizung-test (Tag `v0.1.14-auth`,
2026-05-15) wurde die Sprint-Reihenfolge auf Stabilisierung-vor-
Features umgestellt. Sechs Phasen mit klaren Abschluss-Kriterien:

| Phase | Zeitraum | Sprints | Inhalt |
|---|---|---|---|
| 1 Stabilisierung | Mai-Juni 2026 | 10, 10a, 10b, 10c | CI-Hygiene, Vicki-Diagnose, Code-Fixes, Polish |
| 2 Live-Beobachtung | Juni-Juli 2026 | — | Hotelier produktiv auf heizung-test, Befund-Sprints ad-hoc |
| 3 Frostschutz | Juli 2026 | 11 | AE-42-Reaktivierung, Engine Layer 5 nutzt `min_temp_celsius` |
| 4 heizung-main-Migration | Juli-August 2026 | 12 | B-9.11x-2, Auth-Cutover analog 9.17a/b, Backup-Cron |
| 5 PMS-Casablanca | August 2026 | 13 | Casablanca-Anbindung, Fallback manuelle Pflege |
| 6 Go-Live | September 2026 | 14 | Tag v1.0.0, produktiv vor Heizperiode 01.10.2026 |
| 7 Features | Winter 2026+ | 15+ | Nach Hotelier-Bedarf: Dashboard, Analytics, API-Keys, Gateway-UI, Wetter, ... |

**Heizperiode-Start:** 1. Oktober 2026, Hotel Sonnblick Kaprun.
Phasen-Plan hat zwei Wochen Puffer pro Phase.

Details siehe `docs/STRATEGIE-REFRESH-2026-05-15.md`.

## Konventionen

- **Sprint-Nummern** entsprechen der Zeit-Reihenfolge (Variante 2
  aus Strategie-Refresh)
- **Sub-Sprints** mit Suffix a/b/c für Hotfixes oder Aufteilungen
  (z. B. 10a, 10b, 10c)
- **Autonomie-Stufen** nach CLAUDE.md §0.1: 1=Engine-Concurrency,
  2=Standard, 3=Markdown-only
- **Definition of Done** gilt pro Sprint zusätzlich zu globaler DoD
- **Meilensteine** sind harte Tags, die nie ohne Strategie-Chat-
  Freigabe gesetzt werden
- **Priorität:** 🔴 blockierend, 🟠 vor Heizperiode klärungsbedürftig,
  🟡 wichtig, 🟢 nice-to-have

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

# SPRINT 9.11x — Backplate-Persistenz + Layer-4-Detached-Trigger

**Priorität:** 🔴
**Geschätzte Dauer:** 2-3 h
**Autonomiestufe:** 1 (Engine-Touch in Layer 4)
**Voraussetzung:** Sprint 9.11 Doku-Final abgeschlossen (PR #113), AE-47 dokumentiert
**Tag nach Abschluss:** kein eigener Tag

## Ziel

`attachedBackplate` aus Codec-Output ins Backend persistieren und Engine Layer 4 um Detached-Trigger erweitern. Reines Backend, kein Hardware-Touch — alle Tests via Synthetic-Inserts in pytest.

## Tasks

- T1: Alembic-Migration `0010_device_firmware_version_and_sensor_reading_attached_backplate`
  - `device.firmware_version VARCHAR(8) NULL`
  - `sensor_reading.attached_backplate BOOLEAN NULL`
- T2: SQLAlchemy-Modelle erweitern (`Device`, `SensorReading`)
- T3: Pydantic-Schemata erweitern (`DeviceRead`, `SensorReadingRead`)
- T4: `backend/src/heizung/services/mqtt_subscriber.py` — `_map_to_reading` ergänzen um `"attached_backplate": obj.get("attachedBackplate")`
- T5: `backend/src/heizung/rules/engine.py` Layer 4 erweitern:
  - 2-Frame-Hysterese auf `attached_backplate=false` (zwei aufeinanderfolgende `sensor_readings` für `device_id`)
  - Reason `device_detached`, Setpoint = Frostschutz
  - Bei `NULL` (Codec liefert das Feld nicht): wie bisher behandeln (kein Trigger)
- T6: Pytests:
  - 1× `attached_backplate=true` → kein Trigger
  - 1× ein einzelnes `attached_backplate=false` → kein Trigger (Hysterese-Schutz)
  - 1× zwei aufeinanderfolgende `attached=false` → `device_detached`-Reason
  - 1× `attached=NULL` über alle Frames → kein Trigger (Backwards-Compat)
- T7: Codec-Re-Paste auf heizung-test verifizieren (RUNBOOK §10c Verfahren). `attachedBackplate`-Feld ist bereits im Codec — nur prüfen, dass der aktuelle deployed Codec auf Test-Server das Feld schon emittiert. Falls nicht: Re-Paste durchführen.

## Definition of Done

- Migration grün, mypy/ruff/pytest grün
- Layer-4-Pytest-Matrix komplett
- Codec auf heizung-test verifiziert emittiert `attachedBackplate`
- `sensor_reading`-Spalte gefüllt für mindestens 1 frischen Frame pro Vicki (DB-Query-Verify nach Deploy)
- STATUS.md §2w (oder nächster freier Buchstabe) Sprint-Bericht

## Risiken

- 2-Frame-Hysterese-Logik in Layer 4 kann mit bestehender `open_window`-Logik kollidieren wenn beide Trigger gleichzeitig feuern. Mitigation: explizite Reason-Priorität im Test (`open_window` > `device_detached` > base).

---

# SPRINT 9.11x.b — Vicki-Downlink-Helper + Open-Window-Aktivierung

**Priorität:** 🔴
**Geschätzte Dauer:** 4-5 h
**Autonomiestufe:** 1 (Hardware-Befehlspfad)
**Voraussetzung:** Sprint 9.11x abgeschlossen, AE-48 dokumentiert
**Tag nach Abschluss:** kein eigener Tag (Tag in 9.11y)

## Ziel

Drei neue Vicki-Downlinks via Hybrid-Helper-Architektur (AE-48) implementieren, Bulk-Aktivierung der 4 produktiven Vickis ausführen, FW-Antwort-Parsing in `mqtt_subscriber`.

## Tasks

- T1: `backend/src/heizung/services/downlink_adapter.py` refactorn:
  - Neuer `send_raw_downlink(dev_eui, payload_bytes, fport=1, confirmed=False)`
  - `send_setpoint` nutzt `send_raw_downlink` intern
  - Bestehende Aufrufer aus `engine_tasks.py` unverändert
  - Pytest: `send_setpoint` produziert identische Bytes wie vor Refactor
- T2: Drei Wrapper in `downlink_adapter.py`:
  - `query_firmware_version(dev_eui)`
  - `set_open_window_detection(dev_eui, enabled, duration_min=10, delta_c=Decimal("1.5"))`
  - `get_open_window_detection(dev_eui)`
- T3: Decimal-Rundungs-Tests für `set_open_window_detection`:
  - `Decimal("1.5")` → byte `0x0F` (15)
  - `Decimal("1.55")` → byte `0x10` (16, ROUND_HALF_EVEN oder dokumentierte Strategie)
  - `Decimal("0.2")` → byte `0x02` (Minimum)
  - `Decimal("0.1")` → `DownlinkError` (unter Minimum)
  - `Decimal("3.0")` → byte `0x1E` (oberer plausibler Wert)
- T4: Codec-Encoder-Erweiterung in `infra/chirpstack/codecs/mclimate-vicki.js`:
  - `input.data.query_firmware_version` → `[0x04]`
  - `input.data.set_open_window_detection` (mit gleichen Bytes wie Backend-Wrapper)
  - `input.data.get_open_window_detection` → `[0x46]`
  - Pytest in Backend, der gegen Erwartungs-Bytes asserted (Drift-Schutz)
- T5: `scripts/vicki_open_window_setup.py` — One-Shot-CLI für Bulk-Aktivierung:
  - Argumente: `--dev-eui ...` oder `--all` (alle Vickis aus DB)
  - Schritt 1: `query_firmware_version()` für alle ausgewählten Vickis
  - Schritt 2: 30 s warten (auf Antwort-Uplinks)
  - Schritt 3: `device.firmware_version` aus DB lesen, FW >= 4.2 prüfen
  - Schritt 4: `set_open_window_detection(enabled=True, duration_min=10, delta_c=Decimal("1.5"))`
  - Schritt 5: 30 s warten
  - Schritt 6: `get_open_window_detection()` zur Verifikation
  - Schritt 7: Bericht (welche Vickis aktiviert, welche FW < 4.2 skipped)
- T6: `backend/src/heizung/services/mqtt_subscriber.py` erweitern:
  - cmd-Byte-Routing in `obj`-Parsing: bei `cmd=0x04` die FW-Antwort parsen und `device.firmware_version` updaten
  - bei `cmd=0x46` die Open-Window-Status-Antwort parsen und ins `event_log` loggen (Type `CONFIG_VERIFY`)
- T7: RUNBOOK §10e neue Sektion „Vicki-Konfiguration via Downlink" mit:
  - Architektur-Übersicht (verweist AE-48)
  - CLI-Aufruf-Beispiele (PowerShell + SSH)
  - Decimal-Rundungs-Charakteristik (Backlog B-9.11x.b-1 erledigt)
  - Verifikations-SQL für `device.firmware_version` + `event_log`
  - Troubleshooting (Vicki antwortet nicht innerhalb 30 s)
- T8: Cowork-Verifikations-Brief (separat vom Strategie-Chat vorbereitet, nicht in Claude Code's Scope) — alle 4 Vickis nach Bulk-Aktivierung im ChirpStack-UI prüfen, `openWindow_params` im nächsten Keepalive-Frame enthalten.

## Definition of Done

- 4 Vickis haben `device.firmware_version` gefüllt
- 4 Vickis haben Open-Window-Detection aktiviert (per Get-Verify bestätigt, im `event_log` loggt)
- Backend-Tests grün (Decimal-Rundungs-Matrix + Codec-Spiegel-Test)
- RUNBOOK §10e dokumentiert
- Cowork-Verifikation abgeschlossen

## Risiken

- FW eines Vickis < 4.2 → `0x45` schlägt fehl. Skript skipped diese Vickis und meldet in Output. Manueller Fallback auf `0x06`-Variante via RUNBOOK §10e dokumentiert (1.0 °C-Resolution).
- Codec-Re-Paste nach Encoder-Erweiterung nötig. Lesson §5.22 prüfen.
- Vicki antwortet nicht innerhalb 30 s → Skript timeoutet. Retry-Logik in T5 (max 2 Retries mit 60 s Wait).

---

# SPRINT 9.11y — Backend-Synthetic-Test + passiver Window-Logger

**Priorität:** 🔴
**Geschätzte Dauer:** 3-4 h
**Autonomiestufe:** 1 (Engine-Touch + Test-Infrastruktur)
**Voraussetzung:** 9.11x abgeschlossen
**Tag nach Abschluss:** `v0.1.9-rc6-live-test-2`

## Ziel

Layer-4-Pipeline End-to-End deterministisch testbar machen ohne Hardware-Abhängigkeit (Sommer-tauglich). Passiver Backend-Window-Logger für spätere Aktivierungs-Entscheidung (BR-16).

## Tasks

- T1: Helper `_detect_inferred_window(room_id, lookback_min=10)` — berechnet Δ Raumluft über `sensor_reading`-Hypertable mit Window-Function
- T2: Helper schreibt bei Treffer ins `event_log` mit Type `MAINTENANCE_INFERRED_WINDOW`, **kein Setpoint-Effekt**
- T3: Pytest mit künstlichen `sensor_reading`-Inserts: Layer-4-Pfad End-to-End asserted (Vicki-Trigger, Detached-Trigger, Inferred-Trigger jeweils einzeln und kombiniert)
- T4: T1 aus Sprint 9.11 als pytest abgebildet — Vicki-`openWindow=true` führt zu Frostschutz-Setpoint + Reason `open_window`
- T5: T1 erneut via Cowork-Live-Test mit Hardware-Kältepack durchführen (RUNBOOK §10e), Befund dokumentieren
- T6: STATUS.md §2v finalisieren
- T7: Tag `v0.1.9-rc6-live-test-2` nach Strategie-Chat-Freigabe

## Definition of Done

- Synthetic-Test in pytest grün, in CI lauffähig
- 3 Layer-4-Reasons im Engine-Trace: `open_window`, `device_detached`, passiv `inferred_window` im `event_log`
- Cowork-Kältepack-Test bestätigt T1 Pass mit echter Hardware
- Tag gesetzt

## Risiken

- Falsch-Positive im Inferred-Logger → Justierung der Δ-T-Schwelle in 2-Wochen-Beobachtungs-Phase
- Synthetic-Test in CI braucht TimescaleDB — bestehender Test-Setup prüfen

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

# SPRINT 9.17 — Auth + 2-Rollen-Modell + Audit (FastAPI-native)

**Priorität:** 🔴 (vor Go-Live)
**Geschätzte Dauer:** 10-12 h
**Autonomiestufe:** 1 (Auth-Flow + DB-Schema + Migrations)
**Voraussetzung:** 9.16 (Szenarien-Engine), Phase-0-Befund 2026-05-14
**Tag nach Abschluss:** `v0.1.14-auth`

## Ziel

Authentifizierung produktiv. FastAPI-native JWT-Auth in HttpOnly-
Cookie (kein NextAuth). Zwei Rollen: `admin` (alles) und
`mitarbeiter` (lesen + Belegungen + Manual-Overrides). Feature-Flag
`AUTH_ENABLED` zur kontrollierten Aktivierung. `business_audit`-
Domain für operative Aktionen, `config_audit.user_id` wird befüllt.

## Tasks

- T0: SPRINT-PLAN.md-Korrektur (dieser Eintrag)
- T1: Endpoint-Inventar (Pflicht-Stop)
- T2: Migration `0014_auth_and_business_audit` — `user`-Tabelle,
  `business_audit`, `config_audit`-FK, Bootstrap-Admin via ENV
  (Pflicht-Stop nach Auf-Ab-Auf)
- T3: Auth-Infrastruktur (JWT, bcrypt, Dependencies,
  Feature-Flag-Middleware, CLI für Password-Hash)
- T4: Auth-Endpoints `/api/v1/auth/{login,logout,me,change-password}`
  mit Rate-Limit auf login
- T5: User-Verwaltung-Endpoints `/api/v1/users/*` (admin-only,
  Bricked-System-Schutz)
- T6: Bestehende Endpoints absichern mit `require_admin` /
  `require_mitarbeiter` (Pflicht-Stop nach Grep-Verifikation)
- T7: `business_audit`-Hooks in Belegungs- und Override-Endpoints
- T8: Frontend AuthContext + Inaktivitäts-Logout (15 Min, ohne Modal)
- T9: Frontend `/login`, `/auth/change-password`,
  `/einstellungen/benutzer`
- T10: Sidebar-Stub-Cleanup (Sprint-Nummer-Badges entfernen)
- T11: Doku — ADR AE-50, STATUS §2af, Brief-Kopie + Inventar-Anhang
- T12: Tests Backend + Frontend Playwright

---

# SPRINT 9.17a — Auth-Cutover-Hotfix

**Priorität:** 🔴 (Cutover-Blocker)
**Geschätzte Dauer:** 3-4 h
**Autonomiestufe:** 2 mit zwei Pflicht-Stops (T1 + T3)
**Voraussetzung:** 9.17 gemerged (`d879fd6`), `AUTH_ENABLED=false`
**Tag nach Abschluss:** Strategie-Chat vergibt `v0.1.14-auth` NACH
9.17a-Merge UND erfolgreichem Live-Cutover auf heizung-test. Kein Tag
aus 9.17a heraus.

## Ziel

Zwei harte Cutover-Blocker (B-9.17-4, -10) und fünf UX-Defekte
(B-9.17-5, -6, -7, -8, -9) aus der Cutover-Episode 2026-05-14 beheben.
Inventar-Pflicht für Auth-Sprints in CLAUDE.md §5.30 verankern.

## Tasks

- T1: Endpoint-Inventar (Pflicht-Stop) — alle Methoden, alle Pfade,
  Soll-Dependency pro Endpoint
- T2: GET-Endpoints + übersehene mutierende Endpoints absichern mit
  neuer `require_user`-Dependency
- T3: Identitäts-kritische Endpoints unter `AUTH_ENABLED=false`
  (Pflicht-Stop) — `require_real_user`-Dependency, 503 statt
  System-User-Fallback für `/me` und `/change-password`
- T4: Frontend-Wording 401/429/503 differenzieren (B-9.17-5)
- T5: Mojibake Forced-Change-Page (B-9.17-7)
- T6: Password-Sichtbarkeits-Toggle als `<PasswordInput>` (B-9.17-8)
- T7: Forced-Change Inline-Fehler pro Feld (B-9.17-9)
- T8: Saison-Stub Verweis auf `/szenarien` (B-9.17-6)
- T9: Doku — CLAUDE.md §5.30, STATUS §2ag, SPRINT-PLAN-9.17a-Block,
  AE-50-Nachtrag, Endpoint-Inventar-Feature-Doku
- T10: Tests-Sammlung + Pre-Push-Verifikation

## Out of Scope

- Tag-Vergabe (Strategie-Chat nach Cutover-Erfolg)
- Cutover-Schritt selbst (`AUTH_ENABLED=true`-Flip) — separater
  Strategie-Chat-Block NACH 9.17a-Merge
- B-9.17-1 (E-Mail-Reset), -2 (Audit-UI), -3 (celery_beat),
  -S1 (Secret-Rotation) — andere Sprints

---

# SPRINT 9.17b — Logout-Cookie-Fix + Rate-Limit-Verifikation

**Priorität:** 🔴 (abgeschlossen, Cutover-Blocker für Tag)
**Dauer (real):** 1.5 h
**Tag:** `v0.1.14-auth` (Auth-Track-Abschluss-Tag)
**Status:** ✅ abgeschlossen 2026-05-15

## Ziel (erreicht)

Logout-Cookie-Invalidation-Bug aus 9.17a-Smoke-Test (B-9.17a-1).
FastAPI-Response-Parameter vs. explicit-Return-Pattern-Konflikt
korrigiert.

## Tasks (alle erledigt)

- T1: Logout-Endpoint Variante B (eigenes Response-Objekt + Cookie-
  Lösch-Header + return) ✅
- T2: Backend-Test prüft Set-Cookie-Header der Logout-Response ✅
- T3: Rate-Limit-Backend-Test verifiziert (Body-Assertion-
  Erweiterung in bestehendem Test) ✅
- T4: Frontend 429-Wording-Test bestätigt (bereits in 9.17a T4
  fertig, hier nur verifiziert) ✅
- T5: Doku — CLAUDE.md §5.31, STATUS §2ah, SPRINT-PLAN, AE-50-
  Querverweis ✅
- T6: Pre-Push-Verifikation + PR #151 + Merge ✅

## Lessons

- CLAUDE.md §5.31: FastAPI Response-Parameter vs. explicit
  Response-Return ist eine reale Bug-Klasse. Backend-Test, der den
  Header explizit prüft, ist Pflicht für Cookie-Endpoints.
- Browser-Smoke-Test allein hätte den Bug nicht entdeckt, weil
  Frontend-Redirect funktioniert. Cookie-Header-Audit auf HTTP-
  Ebene ist der direkte Beweis-Pfad.

---

# SPRINT 10 — CI-Hygiene + Test-Coverage (Phase 1)

**Priorität:** 🔴 (Stabilisierung vor weiteren Features)
**Geschätzte Dauer:** 6-8 h
**Autonomiestufe:** 2 (Default)
**Voraussetzung:** Tag `v0.1.14-auth` gesetzt, develop ist auf
Sprint-9.17c-Stand
**Tag nach Abschluss:** keiner (Hygiene-Sprint, kein Feature)

## Ziel

Test-Coverage und CI-Pipeline stabilisieren. psycopg2-Ignores aus
pytest entfernen. mypy-Vorlast in `tests/` deutlich reduzieren.
celery_beat-Backlog-Konsolidierung. Sidebar-Bug auf `/login` fixen.
Secrets-Rotation auf heizung-test. Backlog-Müll aufräumen.

## Tasks

- T1: psycopg2-Failures fixen (B-9.10-6, B-9.11x-1). Entweder
  `psycopg2-binary` in `pyproject.toml [dev]`-extras aufnehmen ODER
  betroffene Test-Files auf asyncpg umstellen. Empfehlung:
  `pyproject.toml` — einfacher und CI-Mirror-tauglich. Erwartete
  Diff: 3 failed + 7 errors lokal → 0 nach Fix.
- T2: Migration-Roundtrip-Tests reparieren (B-9.16-2). Hängt an T1.
- T3: celery_beat-Backlog-Konsolidierung. Drei Backlog-IDs für
  dasselbe Problem (B-9.11-4, B-9.11x-3, B-9.17-3) auf eine
  reduzieren. Healthcheck-Konfig untersuchen — entweder fixen oder
  formal als „Container-Healthcheck-Anomalie ohne Engine-
  Auswirkung" dokumentieren mit Begründung warum kein Fix nötig.
- T4: mypy-Vorlast in `tests/` reduzieren (B-9.10d-2). Ziel: 71 →
  unter 20 mypy-Errors. Keine Refactor-Aktionen außerhalb `tests/`,
  nur Type-Annotations und Cast-Fixes in Test-Files.
- T5: Sidebar-Sichtbarkeit auf `/login` fixen (B-9.17b-2). AppShell
  rendert nicht auf `/login`, `/auth/change-password` und ähnlichen
  Pre-Login-Routen.
- T6: Secrets-Rotation auf heizung-test (B-9.17-S1).
  `POSTGRES_PASSWORD` und `SECRET_KEY` rotieren. Backup .env
  vorher. Rollback-Plan dokumentiert.
- T7: Backlog-Konsolidierung in STATUS.md §6.2. Duplikate auflösen
  (celery_beat-IDs, ähnliche). Sortierung nach Priorität neu
  prüfen. Erledigte Items als ✅ markieren mit Verweis auf Sprint,
  der sie abgehakt hat.
- T8: Pre-Push-Hook für `ruff format --check` (B-9.10d-6). Husky
  oder git-Hook lokal. Verhindert §5.24-Wiederholungsfehler.
- T9: Doku — STATUS.md §2aj (neu), keine CLAUDE.md-Änderung nötig.

## Definition of Done

- pytest auf grün lokal OHNE psycopg2-Ignores (B-9.11x-1 fix
  verifiziert)
- pytest auf grün in CI ebenfalls
- mypy `tests/` < 20 Errors
- celery_beat-Backlog auf eine ID reduziert, mit klarer
  Status-Beschreibung
- `/login` rendert ohne AppShell-Sidebar (Browser-Verify)
- Secrets rotiert, Container nach Restart healthy
- STATUS.md §6.2 entrümpelt
- PR auf develop gemerged

## Out of Scope

- Code-Logik-Änderungen außerhalb des Hygiene-Themas
- Hardware-Diagnose Vicki (kommt in 10a)
- Frontend-Polish Wording-Audit (kommt in 10c)
- Frostschutz-Reaktivierung (Sprint 11)

---

# SPRINT 10a — Vicki-Diagnose (Phase 1)

**Priorität:** 🟠 (vor Heizperiode klärungsbedürftig)
**Geschätzte Dauer:** 4-6 h Diagnose, Fix-Aufwand offen je nach
Befund
**Autonomiestufe:** 1 (Hardware-Diagnose, Pflicht-Stops)
**Voraussetzung:** Sprint 10 abgeschlossen, CI grün, Backlog
konsolidiert
**Tag nach Abschluss:** keiner (Diagnose-Sprint)

## Ziel

Zwei Hardware-Befunde aus dem Auth-Cutover-Smoke-Test 2026-05-15
klären:

- B-9.17b-3 Batterie-Wert-Plausibilität (33% / 42% statt erwartetem
  Verlauf nach neuer Batterie)
- B-9.17b-4 Vicki-002 und -004 senden seit Pairing keinen Heartbeat
  („Inaktiv, noch nie")

Vicki-003 als Kontrollgruppe (gepaired, aktiv, ohne Backplate) für
beide Befunde verfügbar.

## Tasks (Phase-0-orientiert)

- T1: Diagnose Batterie-Decoder im Codec
- T2: Diagnose Subscriber-Persistierung der Batterie
- T3: Diagnose Pairing-Status Vicki-002 und -004 in ChirpStack
- T4: Hardware-Test Vicki-002/-004 in Funk-Distanz, falls
  ChirpStack-Pairing korrekt aussieht
- T5: Phase-0-Bericht mit Klassifikation: Codec-Bug, Subscriber-
  Bug, oder Hardware-Befund. Pro Variante Fix-Plan-Skizze.

## Definition of Done (Diagnose)

- Vier Vickis kategorisiert als: produktiv-fähig, mit Codec-Fix
  produktiv-fähig, oder nicht-pairing-fähig (mit Hardware-
  Begründung)
- Phase-0-Bericht in
  `docs/features/2026-05-XX-sprint-10a-vicki-diagnose.md`
- Falls Fix-Bedarf: Sprint-10b-Brief vorbereitet

---

# SPRINT 10b — Vicki-Code-Fixes (Phase 1, conditional)

> **Status (2026-05-15):** Verschoben, neue Einordnung nach
> Sprint 11. Mit der Phase-1-Restrukturierung aus Strategie-Chat
> 2026-05-15 (AE-51..AE-54, Sprint 11-14 + 14b) ist die zeitliche
> Lage von 10b offen. Doku-Spur bewusst erhalten; finale
> Einordnung erfolgt nach Sprint-11-Abschluss. Siehe
> STRATEGIE-REFRESH-2026-05-15.md §6.

**Priorität:** 🟡 (nur falls 10a Code-Fix verlangt)
**Voraussetzung:** Sprint 10a-Diagnose-Bericht
**Inhalt:** Codec-Fix oder Subscriber-Fix je nach 10a-Befund

---

# SPRINT 10c — Frontend-Polish-Reste (Phase 1, optional)

**Priorität:** 🟢
**Geschätzte Dauer:** 2-3 h
**Voraussetzung:** Sprint 10 + 10a abgeschlossen

## Tasks

- Wording-Audit aktiv/inaktiv auf weiteren Pages (B-9.13c-3)
- Cookie-Namen-Konsistenz Backend↔Doku (B-9.17b-6)
- Cache-Busting nach Frontend-Deploys (B-9.13b-1)
- `/login`-Sidebar (falls nicht in Sprint 10 erledigt)

---

# SPRINT 11-Prep — Doku-Konsolidierung Zuordnungs-Architektur (Phase 1)

**Priorität:** 🔴 (Vorbedingung für Sprint 11)
**Geschätzte Dauer:** 4-6 h (reines Doku-Schreiben + Cross-Referenz-Pflege)
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 10a abgeschlossen oder parallel laufend
**Tag nach Abschluss:** `v0.1.15-zuordnungs-architektur-doku`

## Ziel

Konsolidierte Strategie aus Strategie-Chat 2026-05-15 in alle
relevanten Doku-Dateien einarbeiten, bevor Sprint 11 startet.
Neue Master-Quelle: `docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md`.
ADRs AE-51..AE-54 (Zone-Aggregat, Fenster belegungs-abhängig,
Health-State, Engine-Zone-Isolation).

## Tasks (Skizze)

Vollbrief in eigener Datei. Hauptschritte: STRATEGIE-THERMOSTAT-
ZUORDNUNG.md anlegen, AE-51..54 in ARCHITEKTUR-ENTSCHEIDUNGEN.md
ergänzen, STRATEGIE.md / STRATEGIE-REFRESH / SPRINT-PLAN / STATUS
/ CLAUDE / SESSION-START / CHANGELOG-Design-Strategie / RUNBOOK
ergänzen, Cross-Referenz-Check, Lint, Abschluss-Bericht.

---

# SPRINT 11 — Health-State + Plausi + Zone-Isolation + Aggregat-Lesen (Phase 1)

**Priorität:** 🔴 (Phase 1, Voraussetzung Sprint 12)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 11-Prep abgeschlossen; Sprint 10/10a/b/c durch
**Tag nach Abschluss:** `v0.1.16-health-aggregat`

## Ziel

AE-51 (Aggregat-Lesen), AE-53 (Health-State-Modell + Plausi-
Filter [-20°C, 60°C] + 3-Stufen-Alarm) und AE-54 (Engine-Zone-
Isolation via `try/except`) implementieren. Mehrfach-Vicki-Zonen
lesen Ist-Temp als Mittelwert über `healthy` Vickis, Fenster-OR.

## Tasks (Skizze, Detail-Brief später)

- Migration: `device.health_state` + `heating_zone.health_state` (VARCHAR + CHECK)
- MQTT-Subscriber: Plausi-Filter [-20°C, 60°C], `implausible_reading`-Logger
- Celery-Beat: Health-State-Compute-Task (Uplink-Latenz, Plausi-Statistik, Outlier > 7°C)
- Engine `_load_room_context`: Aggregat-Lesen (Mittelwert + OR), Offline-Filterung
- Engine `evaluate_all_zones`: try/except pro Zone, Failure → Zone-Health=degraded
- Mail-Stub `logger.warning(...)` für Alarm-Stufen 2 + 3
- Tests: Aggregat-Lesen, Plausi-Verwerfen, Zone-Isolation-Failure-Modes

---

# SPRINT 12 — Mehrfach-Vicki Schreiben + Fenster belegungs-abhängig (Phase 1)

**Priorität:** 🔴 (Phase 1)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 11 abgeschlossen
**Tag nach Abschluss:** `v0.1.17-multivicki-fenster`

## Ziel

AE-51 (Schreiben symmetrisch) + AE-52 (Fenster belegungs-
abhängig) implementieren. Setpoint-Downlinks symmetrisch an alle
Vickis einer Zone. Engine Layer 4 reagiert auf `occupancy_state`:
Zone frei + Fenster offen → Frostschutz 10°C, Zone belegt + Fenster
offen → Frei-Sollwert aus Raumtyp. Override während Fenster offen
wird ignoriert (Gast und Mitarbeiter).

## Tasks (Skizze)

- Engine Layer 4: Signatur-Erweiterung um `occupancy_state`, neue Default-Quelle aus `room_type.free_target_c`
- Downlink-Adapter: symmetrisches Setpoint-Schreiben für alle Vickis einer Zone
- Override-Pfad: Ignorieren während Fenster offen (Gast via `manual_setpoint`-Field, Mitarbeiter via UI)
- Frontend: Hinweis „Fenster offen — Override wirkt nicht" auf Override-UI
- Tests: belegungs-abhängige Reaktion, Override-Ignorieren, symmetrische Downlinks

---

# SPRINT 13 — Pairing-Wizard + Mass-Pairing-CSV + Vicki-Eingangstest (Phase 1)

**Priorität:** 🟠 (Vorbedingung Phase 4b Pre-Pairing)
**Geschätzte Dauer:** 2-3 Wochen
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 12 abgeschlossen
**Tag nach Abschluss:** `v0.1.18-pairing-wizard`

## Ziel

Pairing-Wizard dreistufig (Zimmer → Zone → Label) mit
vorgeschalteter ChirpStack-Pairing-Stufe und Vicki-Eingangstest
am Wizard-Ende. Mass-Pairing-CSV-Import oder Batch-Wizard für
~100 Vickis (Vorbereitung Phase 4b im September).

## Tasks (Skizze)

- Wizard-Stufe ChirpStack-Pairing: Device-Profile + Codec via gRPC-Bootstrap
- Wizard-Stufe Zimmer → Zone → Label (bestehende Logik erweitert)
- Wizard-Stufe Vicki-Eingangstest: Setpoint hoch → Ventil hörbar auf, runter → hörbar zu
- Mass-Pairing-CSV-Import (B-11prep-2) für 100-Vicki-Batch
- Tests: CSV-Format-Validierung, Eingangstest-Verifikation, Wizard-Flow E2E

---

# SPRINT 14 — Cross-Sicht-UI + Health-Badges + Mail-Platzhalter (Phase 1)

**Priorität:** 🟠 (Phase-1-Abschluss vor 14b)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 13 abgeschlossen
**Tag nach Abschluss:** `v0.1.19-cross-sicht-ui`

## Ziel

Cross-Sicht-UI umsetzen (Geräte-Liste mit Zimmer + Zone, Zimmer-
Detail mit Zone-Karten + Thermostat-Bubbles, Zone-Detail-Sicht,
Dashboard mit Health-Indikator pro Zone). Health-Badges überall
sichtbar. Mail-Platzhalter (`logger.warning(...)`) für Alarm-
Stufen 2/3 aktivieren.

## Tasks (Skizze)

- Geräte-Liste: Spalten Zimmer + Zone als Pflicht (B-9.11x-5)
- Zimmer-Detail: Zone-Karten mit Soll/Ist + Thermostat-Bubbles (Health, Batterie, Signal)
- Zone-Detail-Sicht: Thermostat-Liste mit Health-Badge
- Dashboard: Health-Indikator pro Zone, Warnungen ohne Drill-Down
- Mail-Platzhalter aktivieren, Test gegen Logger-Output
- Tests: UI-Snapshots, Cross-Sicht-Konsistenz

---

# SPRINT 14b — arc42-Konsolidierung der Architektur-Doku (Phase 1)

**Priorität:** 🟢 (Phase-1-Abschluss, Vorbedingung Sprint 15)
**Geschätzte Dauer:** 6-8 h (4-6 h Mapping + 1-2 h Aufräumen)
**Autonomiestufe:** 3 (reine Doku, keine Code-Berührung)
**Voraussetzung:** Sprint 14 abgeschlossen; Lessons aus Vicki-Diagnose (10a/b/c) und CI-Hygiene (Sprint 10) eingearbeitet
**Tag nach Abschluss:** `v0.1.20-arc42-konsolidierung`

## Ziel

Bestehende Architektur-Dokumente (STRATEGIE.md, ARCHITEKTUR-
REFRESH-2026-05-07, STRATEGIE-REFRESH-2026-05-15, ARCHITEKTUR-
ENTSCHEIDUNGEN.md, CLAUDE.md §5 Lessons) als arc42-Skelett mit
12 Kapiteln umstrukturieren. Mapping statt Neuschreiben. Source-
of-Truth-Hierarchie (CLAUDE.md §0.2) wird strukturell und kann
entfallen.

## Tasks (Skizze)

- arc42-Skelett (12 Kapitel) als Master-Datei anlegen
- Bestehende Inhalte auf Kapitel mappen (Tabelle Quell-Doku → Ziel-Kapitel)
- CLAUDE.md §5 Lessons als Block nach Kapitel 11 verschieben
- Source-of-Truth-Hierarchie strukturell auflösen
- Diskussions-Grundlage aus Strategie-Chat 2026-05-15

## Out of Scope

- MkDocs- oder anderer Renderer-Einsatz (erst bei externer Übergabe geprüft)
- Vollständige Neuformulierung historisch gewachsener Texte

---

# SPRINT 15 — heizung-main-Migration „leer" (Phase 4)

**Priorität:** 🔴 (vor Phase 4b Pflicht)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 1 (Production-Migration)
**Voraussetzung:** Sprint 14b abgeschlossen (Doku in arc42-Form sauber)
**Tag nach Abschluss:** `v0.2.0-main-cutover`

## Ziel

heizung-main vom Sprint-9.8a-Stand auf aktuellen develop-Stand
bringen, zunächst „leer" (ohne Live-Devices). Migrationen 0005-
0014+ inkl. Sprint-11-Health-State-Migrationen anwenden, Auth-
Cutover analog 9.17a/b, Backup-Cron + Off-Site-Replikation,
Disaster-Recovery-Drill, Migrations-Trockenlauf. Vier bisherige
Vickis bleiben in Phase 4 zunächst auf heizung-test.

## Tasks (Skizze)

- B-9.11x-2 heizung-main-Sanierung
- `safe.directory`-Fix (CLAUDE.md §5.7)
- Migrationen 0005-0014+ anwenden (inkl. Health-State-Spalten aus Sprint 11)
- Auth-Bootstrap mit echten Hotel-User-Daten
- `AUTH_ENABLED=true`-Cutover analog Sprint 9.17a/b
- Backup-Cron (OP-1) + Off-Site-Replikation
- Disaster-Recovery-Drill bestanden
- Migrations-Trockenlauf gegen heizung-test-Datenstand

---

# SPRINT 16 — Test→Main-Sync + Last-Test + Bug-Fixing (Phase 4)

**Priorität:** 🔴 (vor Phase 4b Pflicht)
**Geschätzte Dauer:** 1 Woche
**Autonomiestufe:** 1
**Voraussetzung:** Sprint 15 abgeschlossen
**Tag nach Abschluss:** `v0.2.1-test-main-sync`

## Ziel

heizung-test und heizung-main funktional gleichziehen. Last-Test
mit synthetischen Sensor-Readings (Skalierung auf ~100 Vickis
verifizieren). Bug-Fixing aus Phase-2-Live-Beobachtung.

## Tasks (Skizze)

- Test→Main-Sync: Migrationen + Konfiguration angleichen
- Last-Test: synthetische Readings für ~100 Vickis, Engine-Performance + Beat-Tick-Latenz prüfen
- Bug-Fixing aus Phase-2-Live-Beobachtungs-Befunden
- Verifikation: Health-State + Plausi-Filter + Engine-Zone-Isolation unter Last

---

# SPRINT 16a — PMS-Casablanca-Integration (Phase 5, conditional)

**Priorität:** 🟠 (conditional auf FIAS-Antwort B-11prep-1)
**Geschätzte Dauer:** 2-3 Wochen
**Autonomiestufe:** 1 (externe Integration)
**Voraussetzung:** Casablanca-FIAS-Antwort liegt vor; Sprint 16 abgeschlossen
**Tag nach Abschluss:** `v0.2.2-pms-fias`

## Ziel

Casablanca-PMS-Anbindung produktiv. Belegungs-Updates kommen
automatisch im System an. Engine reagiert mit Vorheizen vor
Anreise und Setback nach Abreise. Manuelle Pflege bleibt
funktionsfähig als Fallback.

## Tasks (Skizze)

- FIAS-Antwort auswerten, Polling- vs. Event-Strategie wählen
- PMS-Adapter-Service implementieren
- Mapping PMS-Status → `occupancy`-Tabelle
- Caching mit klarer Invalidierungs-Strategie
- Audit-Trail (`business_audit`)
- Fallback bei PMS-Ausfall: letzter bekannter Stand mit Zeitstempel
- Live-Test mit echten Buchungsdaten

## Bedingung

Falls Casablanca-FIAS-Antwort bis Sprint-17-Start nicht vorliegt,
entfällt dieser Sprint. PMS-Integration rutscht in Phase 7
(Sprint 18+). Manuelle Belegungs-Pflege bleibt Fallback.

---

# SPRINT 17 — Pre-Pairing September (Phase 4b)

**Priorität:** 🔴 (Vorbedingung Phase 6 Pilot-Go-Live)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 1 (Hardware-Massen-Inbetriebnahme)
**Voraussetzung:** Sprint 16 abgeschlossen (Sprint 16a optional, falls FIAS)
**Tag nach Abschluss:** `v0.2.3-pre-pairing`

## Ziel

Mass-Pairing-Vorbereitung aller ~100 Vickis auf einem Tisch im
Hotel-Office, ohne Montage. Pro Vicki Eingangstest. Pilot-Zimmer-
Auswahl finalisiert. Schulung Hotelier. Vorbereitung Phase 6
Pilot-Go-Live Oktober Woche 1.

## Tasks (Skizze)

- Mass-Pairing-CSV-Import (aus Sprint 13) für ~100 Vickis
- Vicki-Eingangstest pro Gerät (Setpoint hoch/runter, Ventil hörbar)
- Pilot-Zimmer-Auswahl: 5 Zimmer maximaler Vielfalt (Standard + Suite + Mehrfach-Vicki + Funk-Rand + häufiger Wechsel, B-11prep-4)
- Schulung Hotelier: Rückbau-Pfad (~5 Min pro Zimmer), Pre-Pairing-Workflow, Health-Dashboard
- RUNBOOK §10f Pre-Pairing-Workflow finalisieren
- LoRaWAN-Funklast-Monitoring UG65 Setup (B-11prep-5)

---

## Meilensteine

| Tag | Bedeutung |
|---|---|
| `v0.1.9-rc6-live-test-2` | Engine-Pipeline live verifiziert |
| `v0.1.11-device-pairing` | Geräte-Verwaltung produktiv |
| `v0.1.14-auth` | Auth-Track komplett (9.17 + 9.17a + 9.17b) |
| `v0.1.15-zuordnungs-architektur-doku` | Sprint 11-Prep: Doku-Konsolidierung Zuordnungs-Architektur |
| `v0.1.16-health-aggregat` | Sprint 11: Health-State + Plausi + Zone-Isolation + Aggregat-Lesen (AE-51/53/54) |
| `v0.1.17-multivicki-fenster` | Sprint 12: Mehrfach-Vicki Schreiben + Fenster belegungs-abhängig (AE-51/52) |
| `v0.1.18-pairing-wizard` | Sprint 13: Pairing-Wizard + Mass-Pairing-CSV + Eingangstest |
| `v0.1.19-cross-sicht-ui` | Sprint 14: Cross-Sicht-UI + Health-Badges + Mail-Platzhalter |
| `v0.1.20-arc42-konsolidierung` | Sprint 14b: arc42-Doku-Konsolidierung (Phase-1-Abschluss) |
| `v0.2.0-main-cutover` | Sprint 15: heizung-main-Migration „leer" (Phase 4) |
| `v0.2.1-test-main-sync` | Sprint 16: Test→Main-Sync + Last-Test + Bug-Fixing (Phase 4) |
| `v0.2.2-pms-fias` | Sprint 16a (conditional): PMS-Casablanca-Integration (Phase 5) |
| `v0.2.3-pre-pairing` | Sprint 17: Pre-Pairing September (Phase 4b) |
| `v1.0.0-pilot` | Phase 6 Pilot-Go-Live (Oktober Woche 1, 5 Pilot-Zimmer) |
| `v1.0.0` | Vollausbau-Migration abgeschlossen (Frühjahr 2027) |

---

# Phase 7 — Features (nach Go-Live, Sprint 15+)

Reihenfolge nach realem Hotelier-Bedarf, nicht nach Plan-
Erinnerungen. Die folgenden Sprint-Skizzen stammen aus dem
Architektur-Refresh 2026-05-07 und sind als Kandidaten für Phase 7
vermerkt, ohne Sprint-Nummern (werden bei Aktivierung neu
vergeben).

## Feature-Kandidaten

### Dashboard mit KPI-Cards (alt 9.18)

**Geschätzte Dauer:** 3-4 h
**Tag-Vorschlag:** `v0.3.x-dashboard`

Dashboard mit 6 KPI-Cards (Strategie §8.4): Belegung, Ø-Temperatur,
Geräte-Online, Energiestatus, Nächster Check-in, Außentemperatur.

Tasks:
- API-Aggregations-Route `/api/v1/dashboard/kpi`
- Frontend `/` mit 6 KPI-Cards
- Begrüßung „Hallo, [Name]" mit User-Session
- Refresh alle 60s

### Temperaturverlauf-Analytics (alt 9.19)

**Geschätzte Dauer:** 4-5 h
**Tag-Vorschlag:** `v0.3.x-analytics`

Eigene Analytics-Seite mit Temperaturverlauf-Chart pro Zimmer/Raum,
Zeitraum-Filter, Wunsch- vs. Ist-Temperatur (analog Betterspace).

Tasks:
- API `/api/v1/analytics/temperature-history` mit Zeitraum-Param
- Recharts Line-Chart, Wunsch + Ist als zwei Linien
- Filter: Zeitraum, Raum, Gerät
- TimescaleDB-Aggregation für lange Zeiträume

### API-Keys + Webhooks (alt 9.20)

**Geschätzte Dauer:** 4 h
**Tag-Vorschlag:** `v0.3.x-api-webhooks`

API-Keys für externe Integrationen und Webhooks für
Outbound-Events.

Tasks:
- Tabelle `api_key` + `webhook_subscription`
- Auth-Middleware für API-Key-Header
- `/einstellungen/api` Settings-Layout
- Webhook-Dispatcher als Celery-Task

### Gateway-Status-UI (alt 9.21)

**Geschätzte Dauer:** 2-3 h
**Tag-Vorschlag:** kein eigener Tag (kleine UI-Erweiterung)

`/einstellungen/gateway` zeigt ChirpStack-Status, letzte Heartbeats,
verbundene Geräte.

Tasks:
- API `/api/v1/gateway/status` (proxied an ChirpStack-API)
- Settings-Layout mit Status-Cards
- Refresh alle 30s

### Wetterdaten-Service aktivieren (alt 13)

**Geschätzte Dauer:** 3-4 h
**Tag-Vorschlag:** `v0.3.x-weather`

Wetterdaten-Service operativ. Heute liegt Modell
`weather_observation` vor, aber kein Service zieht Daten.

Tasks:
- Wetter-API auswählen (DWD, OpenWeather, Open-Meteo)
- Celery-Task `fetch_weather_observation` alle 10 min
- Korrelation mit `event_log` für spätere KI-Layer-Vorbereitung
- Dashboard-KPI „Außentemperatur" lesefähig

### Weitere System-Szenarien (alt 9.16b, zurückgestellt)

Tagabsenkung, Wartung, Schließzeit, Renovierung. Plus volle
Szenario-Auflösung in Engine Layer 2 (ROOM > ROOM_TYPE > GLOBAL
Hierarchie analog `rule_config`). Plus Saison-UI auf
`/einstellungen/saison` mit Tag-Monat-Range und saisonaler
`rule_config` über `season_id`-FK.

### Backlog-Items als Feature-Kandidaten

- B-9.17-1 Self-Service-Passwort-Reset (via E-Mail)
- B-9.17-2 Audit-UI im Frontend
- B-9.17b-1 Server-side JWT-Blacklisting (Multi-Mandant-Pflicht)
- B-9.13a-hf2-1 Server-Side-Build-SHA-Endpoint
- B-9.11x-4 Status-Dashboard zentral (Pull-Timer + Container-Health
  + Engine-Eval)

## Was nach Go-Live kommt (außerhalb dieses Plans)

- Klimaanlagen-Domain (Phase 2)
- KI-Layer (Layer 6+) auf Wetter+Sensor+Event-Log-Basis
- Reporting-Modul mit Energie-Verbrauchs-Auswertung
- Multi-Hotel-Rollout (Tenant 2, 3, ...)
- iOS/Android-Apps für Hotelier-Mobile-Use
