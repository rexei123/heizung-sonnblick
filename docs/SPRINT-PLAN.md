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
| 4 Prod-Domain-Promote | 2026-06-09 (Promote vollzogen, Sprint 15g; main-Stop C1 offen) | 15g | heizung-test→Prod-Domain statt Daten-Migration, **kein main-Strang** (AE-67); Backup lokal+Off-Site |
| 5 PMS-Casablanca | August 2026 (verschiebt sich mit Phase 4) | 13 | Casablanca-Anbindung, Fallback manuelle Pflege |
| 6 Go-Live | September 2026 (verschiebt sich mit Phase 4) | 14 | Tag v1.0.0, produktiv vor Heizperiode 01.10.2026 |
| 7 Features | Winter 2026+ | 15+ | Nach Hotelier-Bedarf: Dashboard, Analytics, API-Keys, Gateway-UI, Wetter, ... |

**Heizperiode-Start:** 1. Oktober 2026, Hotel Sonnblick Kaprun.
Phasen-Plan hat zwei Wochen Puffer pro Phase.

**Update 2026-06-09 (Sprint 15g, AE-67):** Phase 4 ist als
**Prod-Domain-Promote** umgesetzt — heizung-test (.17.150, develop-Stand)
wurde formal zur Prod-Domain `heizung.hoteltec.at` promotet, **statt** einer
heizung-main-Daten-Migration und **ohne** main-Strang. Der folgende Absatz
zum „main-Cutover" ist damit historisch (siehe AE-67; Sprint 15/16 unten
SUPERSEDED).

main-Cutover (Phase 4) ist bewusst termin- und nummernlos. Keine feste
Sprint-Nummer, kein fixes Datum — startet nach der letzten auf
heizung-test gebauten Funktion; Zeitpunkt offen, rutscht nach hinten,
wenn vorher noch ein Feature gebaut wird. Folgephasen (4b Pre-Pairing,
5 PMS, 6 Go-Live) verschieben sich mit. Einziger externer Fixpunkt:
Heizperiode 01.10.2026 als Vollausbau-Zielhorizont, NICHT als
Cutover-Gate. Im Herbst beginnt der schrittweise Einbau der ~105
Vicki-Thermostate.

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

**Priorität:** ✅ abgeschlossen 2026-05-18 (Tag `v0.1.16-health-aggregat`)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 11-Prep abgeschlossen; Sprint 10/10a/b/c durch
**Tag nach Abschluss:** `v0.1.16-health-aggregat`
**Abgeschlossen:** 2026-05-18, 9 Commits auf Branch `feature/sprint-11-health-aggregat`, PR #158 gemerged (Merge-Commit `6a8f2ae`)
**Test-Counts:** 261+1 (vor Sprint 11) → 360+1 (nach T6), +99 neue Tests
**Implementiert:** AE-51 §4.1 (Aggregat-Lesen), AE-53 (Health-State + Plausi + 3-Stufen-Alarm), AE-54 (Engine-Isolation, Room-zentrisch — Zone-granular kommt Sprint 12)

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

## Folge-Sprint-Backlog (T7-Vormerke aus Sprint 11)

- Counter-Read-Parallelisierung via `asyncio.gather` wenn ~100 Vickis produktiv (heute <20 nicht spuerbar)
- Latest-Reading-Lookup als Single-Roundtrip-Query (DISTINCT ON / Window-Function) bei >500 Devices (heute N+1 bewusst akzeptiert)
- Status-Konstanten-Cleanup: Literal-Type/Enum fuer Compute-Returns ("success"/"skipped_no_room"/"failed_marked_degraded") und silent_transitions-Reasons ("offline_24h"/"implausible_readings_24h")
- Test-Infrastruktur-Pattern: Cleanup-Fixture als wiederverwendbarer Helper in `tests/conftest.py` (Sprint 12 wird das auch brauchen)
- SMTP-Versand-Implementation als eigener Sprint nach Heizperiode 2026/27, inkl. Re-Mail-Dedupe (Redis-Key `health_alert_sent:{dev_eui}` mit TTL)
- Konsolidierung des caplog-Propagations-Workarounds in `tests/conftest.py` als `enable_heizung_log_propagation(...)`
- AE-54-Wording-Drift in ADR selbst (`docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`) per Klarstellungs-Block korrigieren (kommt in T7-Schritt zur ADR)

---

# SPRINT 12 — Mehrfach-Vicki Schreiben + Fenster belegungs-abhängig (Phase 1)

**Priorität:** ✅ abgeschlossen 2026-05-19 (Tag `v0.1.17-multivicki-fenster` nach PR-Merge)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 2 (T0 + T6 Doku) und 1 (T2-T5 Engine + Hardware-Pfad)
**Voraussetzung:** Sprint 11 abgeschlossen
**Tag nach Abschluss:** `v0.1.17-multivicki-fenster`
**Abgeschlossen:** 2026-05-19, Branch `feat/sprint-12-multivicki-fenster`, 4 Commits T2..T5 + T6-Doku, PR tbd nach `gh pr create`.

## Ziel (final umgesetzt)

AE-51 P3 (symmetrische Multi-Vicki-Setpoint-Submission, healthy-Filter,
per-Vicki-Hysterese, `asyncio.gather`+individuelles try/except) und
AE-52 (Layer 4 occupancy-aware + Override-Reject 409). Engine-Decision-
Iteration bleibt room-zentrisch (D1: keine pro-Zone-differenzierende
Engine-Logik existiert — `is_towel_warmer` ist DB-Marker ohne Konsumenten).

## Tasks (umgesetzt)

- **T0** Doku-Cleanup + Test-Helper (T0-PR #159 merged): STATUS §1+§9, SPRINT-PLAN Sprint-11-PR, AE-54-Querverweis-Fix, conftest.py `enable_heizung_log_propagation` + `purge_test_data_by_prefix`.
- **T2** Schreib-Pfad Multi-Vicki symmetrisch (`168e2b2`): `_dispatch_downlinks_per_zone`, `_get_zone_devices` (healthy-Filter, D3-Fix), `_last_command_for_device` (per-Vicki-Hysterese, D5), JSONB-Sub-Trace im HARD_CLAMP-Row (D7/AE-55). Room-Level `hysteresis_decision` aus Trace entfernt (§5.20-Drift). +7 DB-Tests.
- **T3** Layer 4 occupancy-aware (`2ee8a96`): `layer_window_open` belegungs-abhaengig (VACANT→Frostschutz, OCCUPIED→`default_t_vacant`-Setback), Override-Maskierungs-Marker, Signatur unveraendert (kleine Variante D4). +3 DB-Tests + Test 6 enhanced. D8: Reason bleibt `WINDOW_OPEN`, Differenzierung via detail+extras (Enum-Length-30-Constraint).
- **T4** Override-Reject 409 (`cd96952`): Helper `detect_open_window_zones` extrahiert in `rules/window_state.py` (D12/AE-56), `OverrideRejectedWindowOpenError` in override_service, API-409-Mapping. +8 DB-Tests (3 Helper + 3 Service + 2 API).
- **T5** E2E-Verbund (`5da9f1b`): `tests/test_sprint12_e2e.py` mit 7 Szenarien A-G (Engine-Tick A-E, HTTP F-G).
- **T6** Doku-Update (dieser Commit): STATUS §2am, CLAUDE §5.42-§5.48, AE-52-Praezisierung + AE-54-Klarstellung + AE-55 + AE-56, SPRINT-PLAN Sprint-12-Abschluss + Sprint-12a-Block + Backlog.

## Definition of Done

- ruff/mypy strict/pytest grün (Backend): 189 passed, 197 skipped (DB-Tests skip-modus lokal, CI-Pipeline fährt sie).
- Frontend unbetroffen (kein Frontend-Touch in Sprint 12 — Hinweis-UI verschoben in Sprint 12a).
- PR auf `develop` (tbd), Tag `v0.1.17-multivicki-fenster` nach Strategie-Chat-Freigabe.
- STATUS §2am-Eintrag (in diesem Commit gesetzt).

## Drift-Befunde (in CLAUDE.md §5.42-§5.48 verankert)

- **D1** Brief-Annahme „Sprint-9-Handtuchtrockner-Logik" — existiert nicht (§5.43).
- **D2** Feldname `free_target_c` existiert nicht — `default_t_vacant` (AE-52 Praezisierung).
- **D3** `_get_room_devices` filterte nicht auf health_state — neue `_get_zone_devices` mit `healthy`-Filter.
- **D7** EventLog-PK zwingt JSONB-Sub-Trace (§5.44 / AE-55).
- **D8** `CommandReason`-Length-30 zwingt detail-Differenzierung (§5.45).
- **D11** Pass-Through-Pfad Layer 4: 2 Queries (Helper + Diagnostic) — Optimierungs-Backlog.
- **D12** Helper in `rules/window_state.py` statt `engine.py` (zirk. Imports, §5.46 / AE-56).
- **D14** Override-Reject filtert auf healthy — UX-Konsequenz bei All-Unhealthy-Cluster, Sprint-12a-Frontend-Hinweis.
- **D15** `purge_test_data_by_prefix` raeumt Devices nicht — Backlog T0-Helper-Erweiterung.
- **D16** `TEST_DATABASE_URL` vs `DATABASE_URL`-Konvention (§5.48 / Backlog).

## Nicht-Ziele eingehalten

- Engine-Iteration bleibt room-zentrisch (AE-54-Klarstellung).
- Override-DB-Migration `zone_id`: verschoben nach Sprint 12a.
- Frontend Override-Panel pro Zone + Fenster-Vorpruefung: verschoben nach Sprint 12a.
- Handtuchtrockner-Spezial-Logik: weiterhin nicht im Scope.

## Folge-Sprint-Backlog (T7-Vormerke aus Sprint 12)

- **T0-Helper `purge_test_data_by_prefix` um Device-Cleanup erweitern** (D15-Folge). Aktuell raeumt der Helper nur Rooms+RoomTypes via CASCADE, Devices bleiben orphan wegen `Device.heating_zone_id`-FK mit `ondelete=SET NULL`. Lokaler `_purge_orphan_devices`-Helper in `test_sprint12_e2e.py` zeigt das Pattern. Konsolidierung in conftest.py-Helper im naechsten Hygiene-Sprint.
- **Test-Fixture-Konsolidierung `_migrate_and_seed_admin` / `_ensure_test_admin`** (D16-Folge). Sprint-12-E2E hat eigene module-scoped Migration+Admin-Fixture parallel zu conftest, weil conftest `DATABASE_URL` liest und E2E `TEST_DATABASE_URL` pinnt. Beide idempotent, aber duplizierte Logik. Zusammen mit dem env-Var-Cleanup (naechster Punkt).
- **`TEST_DATABASE_URL` vs `DATABASE_URL`-Konvention konsolidieren** (D16 / §5.48-Folge). Bestand mischt beide env Vars (`test_engine_isolation.py`: TEST_DATABASE_URL; `test_api_overrides.py`: DATABASE_URL). Sprint-12-E2E hat eine Brueckenkonvention etabliert; vollstaendige Konsolidierung im naechsten Hygiene-Sprint.
- **Layer-4-Helper Pass-Through 2-Query-Reduktion** (D11). `layer_window_open` macht im Pass-Through-Pfad jetzt 2 Queries (Helper + Diagnostic). Optimierung via Return-Tuple `(open_zones, diagnostic_counts)` — nur sinnvoll wenn Engine-Load-Profil je relevant wird (z.B. > 200 Raeume, > 60-s-Beat).
- **`_last_command_for_room` final entfernen** sobald `setpoint_in`-Lookup in `_evaluate_room_async` per-Vicki migriert wurde. Heute noch fuer Legacy-Audit aktiv (Docstring „ausschliesslich fuer Legacy-Lookups, NICHT in Decision-Pfade einbinden"). Cleanup-Sprint nach Sprint 12a oder spaeter.
- **EventLog-PK-Migration auf `(time, room_id, evaluation_id, layer, sub_entity_id)`** — nur wenn konkreter Analytics-Use-Case auftritt (D7 / AE-55). Aktuell JSONB-Aggregat in `details["downlink_per_device"]` ausreichend. Bei SQL-Analytics-Bedarf (z.B. per-Vicki-Setpoint-Verlauf ueber Wochen) eigener Migration-Sprint.

---

# SPRINT 12a — Override-Zone-Scope + AE-58 Konsolidierung (Backend-only, Phase 1-Folge)

**Priorität:** ✅ abgeschlossen 2026-05-20 (Branch `feat/sprint12a-override-zone-scope`, 7 Commits T1-T7, PR-Erstellung als naechster Schritt, Tag `v0.1.17a-override-zone-scope-backend` nach Strategie-Chat-Freigabe + Live-Verify auf heizung-test)
**Geschätzte Dauer (Brief):** 10-14 h
**Realdauer:** ~12-13 h ueber 7 Tasks
**Autonomiestufe:** 1 (DB-Migration + kritischer Service-Pfad + Hardware-Befehlspfad)
**Voraussetzung:** Sprint 12 abgeschlossen + gemerged + Tag `v0.1.17-multivicki-fenster` gesetzt
**Tag nach Abschluss:** `v0.1.17a-override-zone-scope-backend`

## Ergebnis (Sprint 12a)

AE-58 Override-Modell konsolidiert:
- Zone-Scope-Override (`manual_override.heating_zone_id`)
- OCCUPIED-Gate: Override nur in belegten Zimmern (RoomNotOccupiedError, 409 Frontend / silent skip + Audit Device)
- Mitarbeiter > Gast Prioritaet (FRONTEND_* > DEVICE)
- Window-Open trumpft alle Quellen (Layer 4 verwirft zone_overrides)
- Auto-Revoke bei Check-out fuer ALLE Quellen (`revoke_all_active_overrides` ersetzt `revoke_device_overrides`)
- Engine Layer 3 zone-aware via `RuleResult.zone_overrides` (Option G)
- AE-29 + AE-45 als abgeloest markiert (Code-Cleanup AE-29 in B-12a-1)
- AE-54-Klarstellung partiell revidiert (Layer 3 zone-aware, Layer 4/5 Room-Level mit Pass-Through)

Detail-Tasks T0-T7 + Commit-Range siehe STATUS.md §2an.

## Folge-Sprint-Backlog aus 12a (in STATUS.md §6.2 als B-12a-1..7)

- B-12a-1: AE-29 manual_setpoint_event-Cleanup (Mini-Sprint, ~2 h)
- B-12a-2: `_create_device`-Helper-Default `health_state="healthy"` (~10 Min)
- B-12a-3: Layer 4 zone-differenzierende Window-Wirkung (nach Heizperiode)
- B-12a-4: Engine soll `derive_room_status` nutzen statt `room.status` (~3-4 h)
- B-12a-5: `_get_zones_for_room`-Helper Konsolidierung (~30 Min)
- B-12a-6: Dispatch-Test mit `zone_overrides` ergaenzen (~30 Min)
- B-12a-7: `get_active_zones_bulk`-Optimierung (YAGNI, Notiz)

---

# SPRINT 12a (alt) — ORIGINAL-BRIEF-SKIZZE 2026-05-19 (HISTORISCH)

**Status:** ueberholt durch Sprint-12a-Strategie-Chat-Brief 2026-05-20
(Backend-only mit AE-58-Konsolidierung). Der urspruengliche
Sprint-12a-Brief 2026-05-19 sah Backend + Frontend in einem Sprint
vor. Die Frontend-Arbeit ist in Sprint 12b (siehe unten) verschoben.

**Originalziel (historisch):** Override-Domain auf Zone-Scope umstellen
+ Frontend-UX fuer Fenster-offen-Reject. Sprint 12 hat Schreib-Pfad
zonen-iteriert + Engine Layer 4 Window-aware gemacht; Override blieb
heute Room-scoped, das Frontend zeigte aber bereits Zonen-Granularitaet
— Mismatch.

**Folgende Original-Skizze ist NICHT mehr Plan-Basis** (siehe oben
„Ergebnis (Sprint 12a)" fuer den tatsaechlichen Inhalt nach
Brief-Update 2026-05-20):

**Priorität (historisch):** 🟠 (Phase-1-Folge, vor Sprint 13 Pairing-Wizard)
**Geschätzte Dauer (historisch):** 4-6 h
**Autonomiestufe (historisch):** 1 (DB-Migration + Frontend-Touch)
**Voraussetzung (historisch):** Sprint 12 abgeschlossen + gemerged + Tag `v0.1.17-multivicki-fenster` gesetzt
**Tag nach Abschluss (historisch):** `v0.1.17a-override-zone-scope`

> **Numerierungs-Drift Sprint 12 T6 (D17):** Brief-Wortlaut sagte
> „Sprint-13-Block NEU anlegen" — kollidiert mit bereits existentem
> Sprint 13 (Pairing-Wizard). Pragmatisch als Sprint 12a benannt
> (Sub-Sprint-Pattern wie Sprint 11-Prep), keine Cascade-Renumbering
> der nachfolgenden Sprints noetig. Tag-Slot `v0.1.17a-…` analog
> reserviert.

## Ziel

Override-Domain auf Zone-Scope umstellen + Frontend-UX fuer Fenster-
offen-Reject. Sprint 12 hat Schreib-Pfad zonen-iteriert + Engine
Layer 4 Window-aware gemacht; Override bleibt heute Room-scoped, das
Frontend zeigt aber bereits Zonen-Granularitaet — Mismatch.

## Tasks (Skizze)

- DB-Migration `manual_override.zone_id` (`heating_zone_id`)
  nullable, Default NULL. Bestehende Rows behalten NULL → Room-Scope.
  Spaeter (Sprint 12b) NOT NULL + Default-Backfill auf
  „Hauptzone des Raums".
- `services/override_service` Signatur-Erweiterung um optionalen
  `heating_zone_id`-Parameter in `create()` / `get_active()` /
  `get_history()` / `revoke_device_overrides()`. Room-Scope bleibt
  Default fuer Backward-Compat.
- API-Endpoints `/api/v1/rooms/{room_id}/overrides` um Query-Param
  `zone_id` erweitern (POST + GET). Bestehende ohne-Zone-Aufrufer
  bleiben Room-scoped.
- Engine Layer 3 (`layer_manual_override`) zone-aware: pro Zone
  nach Zone-Override suchen, Room-Fallback wenn keiner.
- **Frontend** Override-Panel pro Zone (B-LT-2-followup-1-aequivalent
  fuer Override-UI). Vor POST: GET-Aufruf an neuen Endpoint
  `/api/v1/rooms/{room_id}/window-state` (oder Query auf Layer 4
  Aggregat) — wenn Zone offen, UI deaktiviert Override-Button + zeigt
  Hinweis-Text „Fenster offen — Override nicht moeglich, bitte
  Fenster schliessen". Sprint-12-R4-Erledigung.
- **D14-Folge:** Frontend zeigt zusaetzlich Warnung bei
  All-Unhealthy-Cluster („Devices offline — Status veraltet,
  Override moeglich aber Wirkung unklar bis Hardware-Recovery").
- Tests: Migration-Roundtrip, Service-API Zone-Scope, Engine Layer 3
  zone-Lookup, Frontend Playwright (Override-Disable bei Fenster
  offen).

## Begründung

Sprint 12 hat Schreib-Pfad und Read-Helper zonen-iteriert. Override-
Tabelle ist die letzte Inkonsistenz — Frontend kann pro Zone
deaktivieren, Backend kennt aber nur Room-Override. R4 aus
Sprint 12 (Frontend sendet POST ohne Fenster-Vorpruefung →
oefter 409) wird mit dieser Vorpruefung erledigt.

## Risiken

- **R4 Sprint-12** (Frontend-Vorpruefung): wird mit Sprint 12a
  erledigt.
- DB-Migration: bestehende Override-Rows bleiben Room-scoped via
  NULL. Backward-Compat-Test in pytest noetig (alte API-Rufe ohne
  `zone_id` muessen weiter funktionieren).
- Engine Layer 3 zone-Lookup-Priorisierung: Zone-Override > Room-
  Override > kein Override. Reihenfolge dokumentieren in AE-Ergaenzung.

---

# SPRINT 12b — Frontend Zone-Override-Panels + Window-Pre-Check (Phase 1, Folge-Sprint zu 12a)

**Priorität:** ✅ abgeschlossen 2026-05-20 (Branch `feature/sprint-12b-override-zone-scope-frontend`, 6 Commits T1-T6, PR-Erstellung als naechster Schritt, Tag `v0.1.17b-override-zone-scope-frontend` nach Strategie-Chat-Freigabe + Merge)
**Geschätzte Dauer (Brief):** 6-9 h netto
**Autonomiestufe:** 2 (Frontend-Refactor, kein Hardware-Pfad)
**Voraussetzung:** Sprint 12a abgeschlossen + gemerged + Tag `v0.1.17a-override-zone-scope-backend` gesetzt
**Tag nach Abschluss:** `v0.1.17b-override-zone-scope-frontend`

## Ergebnis (Sprint 12b)

Frontend-UX an das in Sprint 12a etablierte Backend-Override-Modell (AE-58) angepasst:
- ManualOverridePanelList Container, pro Zone eine eigene `ManualOverrideZoneCard` mit eigenem Submit-Pfad (`heating_zone_id` im POST-Body)
- Optionale `ManualOverrideRoomCard` (read-only) am Listen-Anfang fuer Backward-Compat-Bestandsdaten mit `heating_zone_id === null` (Lazy-Migration aus 12a T1)
- Window-Pre-Check via `useEngineTrace`-Hook: Submit-Button + Form-Inputs disabled wenn `details.open_zones` der WINDOW_SAFETY-Layer-Row die Zone listet; „Stand: vor Xs"-Hinweis transparent (E1-Latenz-Akzeptanz)
- `mapOverrideError`-Helper (`lib/api/override-errors.ts`) mappt 409 `room_not_occupied`, 409 `override_rejected_window_open`, 404 `invalid_zone`, 422 auf deutsche User-Texte (kein ID-Leak)
- Engine-Decision-Panel: `zone_overrides_trace` aus HARD_CLAMP-Row als Pro-Zone-Setpoint-Block unter dem Layer-Trace sichtbar; neue Layer- und Reason-Werte aus Sprint 12a T4 (`manual_override_blocked`, `device_blocked_vacant`, `device_blocked_window`) in `EventLogLayer`/`CommandReason`-Unions + `LAYER_LABEL`/`REASON_LABEL`
- 5 Playwright-E2E-Cases lokal grün (Happy/Window-Blocked/Room-not-occupied/Invalid-Zone/Engine-Panel-Pro-Zone)
- Backend-Tests bleiben grün (413 passed, 1 xfailed), kein Backend-Code-Touch

Detail-Tasks T1-T6 + Commit-Range siehe STATUS.md §2ap.

**Out of Scope (per Brief E3):** room_blocked-UI-Stub. Nur Code-Anker im 12a-T3-Backend (api/v1/overrides.py `# AE-58 Sprint 12c: ...`) ist sichtbar; Frontend bleibt 12b-clean.

---

# SPRINT 12b (alt) — ORIGINAL-BRIEF-SKIZZE (HISTORISCH)

Folgende Beschreibung ist die urspruengliche Brief-Skizze aus Sprint-12a-T7-Doku-Update (2026-05-20 frueh) und wurde durch den Brief vom Strategie-Chat 2026-05-20 nach 12a-Merge praezisiert. „Ergebnis (Sprint 12b)" oben ist Plan-Basis.

**Priorität (historisch):** 🟠 (Phase-1-Folge, vor Sprint 13 Pairing-Wizard)
**Geschätzte Dauer (historisch):** 4-6 h

## Ziel

Frontend-UX an das in Sprint 12a etablierte Backend-Override-Modell
(AE-58) anpassen:

- **Zone-Override-Panels pro Zone** statt einer Card pro Raum.
  Zimmer mit 2 Zonen (Schlafzimmer + Bad) zeigen 2 Panels. Jedes
  Panel ist eigenstaendig (eigener Override-Setpoint, eigene
  Quelle-Auswahl, eigener „Aufheben"-Button).
- **Window-Pre-Check vor POST**: GET `/api/v1/rooms/{room_id}/window-state`
  (oder Reuse `engine-trace`-Endpoint) bevor Override-POST. Wenn
  Zone offen: Button disabled, Hinweis-Text „Fenster offen —
  Override nicht moeglich, bitte Fenster schliessen". Erspart 409-
  Response-Loops im Normalbetrieb.
- **Schema-Konsum `heating_zone_id`**: Response-Body zeigt
  `heating_zone_id` (int | null); UI rendert Zone-Scope vs.
  Room-Scope (Default) als Label-Variante.
- **422 / 409-differenzierte Fehler-Anzeige**: heute generischer
  „Fehler"-Toast. 409 `room_not_occupied` → „Override nur fuer
  belegte Zimmer moeglich". 409 `override_rejected_window_open`
  → siehe Window-Pre-Check. 404 `invalid_zone` → defensive Fallback.
- **room_blocked-Slot-Stub fuer Sprint 12c**: UI-Komponente fuer
  Sperr-Toggle vorbereiten (deaktiviert, mit „kommt in Sprint 12c"-
  Hinweis), Backend-Pfad bleibt 12c-Scope.

## Tasks (Skizze)

- Refactor `frontend/src/components/patterns/manual-override-panel.tsx`
  von `(roomId)` auf `(roomId, zoneId)`-Mode
- Neue Container-Komponente `manual-override-panel-list.tsx` rendert
  N Panels pro Zone des Raums + 1 Room-Scope-Fallback-Panel falls
  Bestandsdaten vorhanden
- Hook `useWindowStateForRoom(roomId)` + Pre-Check-Gating
- API-Schema-Konsum `heating_zone_id` in Response + Create-Body
- Playwright E2E: Zone-Override anlegen, Aufheben, Window-Pre-Check
  Disable-State, 422/409-Fehler-Toasts

## Out of Scope

- Backend-Aenderungen (alles in Sprint 12a fertig)
- `room.guest_override_blocked`-Toggle (Sprint 12c)

---

# SPRINT 12c — Uebersteuerungs-Sperre `room.guest_override_blocked` (ABGESCHLOSSEN 2026-05-20)

**Status:** ✅ Abgeschlossen 2026-05-20 (T1-T9, Branch `feat/sprint12c-room-override-blocked`)
**Tag nach Merge:** `v0.1.17c-room-override-blocked`
**Autonomiestufe:** 1 (DB-Migration produktiv + Engine/Adapter + neuer API-Mutator + Auto-Revoke mit Audit)

## Ergebnis

Uebersteuerungs-Sperre als Mitarbeiter-Toggle (`PATCH /rooms/{id}/override-block-state`). Block-Gate liegt im `override_service.create()` als Single-Source-of-Truth; Device-Adapter spiegelt das Gate als Pre-A vor OCCUPIED + Window-Check und schreibt off-pipeline `EventLogLayer.MANUAL_OVERRIDE_BLOCKED` mit neuem `CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED`. Toggle-On triggert `revoke_all_active_overrides(reason="room_override_blocked")` (source-agnostic), BusinessAudit-Action `ROOM_OVERRIDE_BLOCK_TOGGLED` mit `new_value.revoked_overrides_count`. Frontend: Toggle im Zimmer-Detail-Header (Lock-Symbol), Sperre-Banner im Override-Tab, Create-Form versteckt waehrend blocked. Engine bleibt unangetastet (kein neuer Layer).

**Diff-Stats:** Backend +1 Migration, +1 Test-Datei (`test_api_rooms.py`), 8 Source-Files. Frontend +1 Component (`RoomOverrideBlockToggle`), +1 E2E-Spec (4 Cases §5.54-konform), 7 Source-Files. Backend-Tests 426 passed; Frontend-E2E 51/51 gruen.

**Querverweise:** STATUS §2aq, AE-58 (Sprint-12c-Ergaenzung), §5.49 (Test-Fixture-Anpassung Raw-SQL), §5.51 (Domain-Invariante Block-Gate vor OCCUPIED-Gate), §5.52 (Off-Pipeline-Audit fuer Pre-A-Gate).

## Out of Scope (Backlog)

- B-12c-AuditGap: `auto_revoke_on_checkout` schreibt weiterhin kein Audit.
- B-12c-1: Vicki-Hardware-Child-Lock via Downlink 0x07 (separater Sprint).
- Zimmer-Liste-Indikator: ausgelagert in Sprint 12c.a (siehe unten).

---

# SPRINT 12c.a — Zimmer-Liste-Block-Indikator (ABGESCHLOSSEN 2026-05-20)

**Status:** ✅ Abgeschlossen 2026-05-20 (T1-T3, Branch `feat/sprint12ca-room-block-list-indicator`)
**Tag nach Merge:** `v0.1.17d-room-block-list-indicator`
**Autonomiestufe:** 3 (Frontend-only-Trivial-Sprint, kein Backend-Touch, kein Logik-Pfad)
**Voraussetzung:** Sprint 12c gemerged + Tag `v0.1.17c` gesetzt + Live-Verify erfolgreich

## Ergebnis

Schloss-Symbol-Spalte in `frontend/src/app/zimmer/page.tsx` (RoomTable) zwischen Status-Pill und Detail-Link. Symbol `lock` mit `aria-label="Übersteuerung gesperrt"` + gleichlautendem `title` wenn `r.guest_override_blocked === true`. Wording-Trennung zu `RoomStatus.BLOCKED` bleibt scharf (eigene Spalte, kein Merge in `STATUS_COLOR`-Map). Backend liefert das Feld bereits seit Sprint 12c (PR #166), keine API-Aenderung.

**Diff-Stats:** Frontend +1 E2E-Spec (`sprint12ca-room-block-list-indicator.spec.ts` mit 2 Cases), 1 Source-File geaendert (`app/zimmer/page.tsx`), 1 Doku-Block (STATUS §2ar + §1 + §9, SPRINT-PLAN). Playwright 53 passed (51 Bestand + 2 neu).

**Querverweise:** Sprint 12c (PR #166, AE-58, Tag `v0.1.17c`), STATUS §2ar, §5.20 (Wording-Trennung), §5.54 (RegExp-Routes).

## Out of Scope (Backlog)

- Tooltip-Komponente in `components/ui/` extrahieren (kein Bedarf ausserhalb dieser einen Zelle)
- Status-Pill-Komponente extrahieren (Sprint-8-Inline-Pattern, kein 12c.a-Anlass)
- Filter „Nur gesperrte zeigen"
- Lock-Symbol im Zimmer-Detail-Header (Doppelung mit 12c-Toggle-Button)

---

# SPRINT 13 — Pre-Pairing-Skript + Device-Tausch-Endpoint (Phase 1, Sprint-13-light-Cut 2026-05-21)

**Priorität:** 🟠 (Vorbedingung Phase 4b Pre-Pairing September)
**Geschätzte Dauer:** 13a ~4-6 h ✅ + 13b ~5-8 h (Sprint 13a abgeschlossen 2026-05-23)
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 12c.a abgeschlossen + Hygiene-Mini-Sprint
abgeschlossen (gemerged via PR #171). AE-57 verfuegbar.
**Tag fuer 13a:** `v0.1.18a-pre-pairing-skript` (T9.12, nach PR-Merge)
**Tag fuer 13b (geplant):** `v0.1.18-pairing-wizard` (Sprint-13-Gesamt-Tag)

## Sprint-13-Cut (verbindlich ab 2026-05-21)

Strategie-Chat-Entscheidung aus Phase-0-Bericht
`docs/features/2026-05-21-sprint13-phase0-quellcheck.md`: **keine**
dreistufige Wizard-UI im September-Workflow. Hotelier paired ~100 Vickis
einmalig am Office-Laptop ueber ein Python-CLI-Skript. ChirpStack-
Provisioning bleibt manuell via ChirpStack-UI-Bulk-Import (vorab durch
den Hotelier). heizung-DB-Eintraege kommen via CSV-Import-Subcommand
des Pre-Pairing-Skripts.

Alte Skizze (dreistufiger Pairing-Wizard, ChirpStack-gRPC-Bootstrap)
verworfen 2026-05-21. Begruendung: einmaliger Mass-Pairing-Vorgang
rechtfertigt keine Wizard-UI; CLI-Skript ist robuster + reproduzierbar
+ versionierbar (script lebt im Repo, Vendor-CSV im Office-Laptop-
Filesystem).

## Sprint 13a — Pre-Pairing-Skript (Phase 4b-Vorbereitung) ✅ ABGESCHLOSSEN 2026-05-23

**Tatsaechliche Dauer:** ~4-6 h reine Code-Arbeit (T2-T7), zzgl. T8
Live-Verify + T9 Doku am 2026-05-23.
**Tag (T9.12):** `v0.1.18a-pre-pairing-skript`
**Branch:** `feat/sprint13a-pre-pairing-skript` (8 Commits auf
develop @ `8f3554b`).

### Ergebnis (Abweichungen von Skizze)

- **Skript-Pfad:** `backend/src/heizung/scripts/pair_devices.py`
  (im neuen Sub-Package `heizung.scripts/`), nicht
  `backend/scripts/`. Aufruf via `python -m
  heizung.scripts.pair_devices …`. Bestehendes
  `backend/scripts/activate_open_window_detection.py` bleibt am
  alten Ort — Migration in Backlog B-Sprint13a-1.
- **Subcommands:** `validate`, `import` (mit `--dry-run`), `test`,
  `list-pool`. `retire-device` verworfen — gehoert thematisch zu
  Sprint 13b (Tausch-Endpoint), wo es als Service-Helper unter dem
  REST-Endpoint sitzt.
- **`PairingCsvRow`** liegt unter
  `heizung.scripts.pairing.csv_row`, nicht
  `heizung.services.pairing_csv` — Service-Layer haette suggeriert,
  das Modell sei auch fuer den Engine-Pfad relevant; das ist es
  nicht.
- **Reserve-Pool-Konzept** kam in 13a dazu (Phase-0-Befund Sprint
  12c.a Live-Test 2026-05-21): drei Lifecycle-Zustaende
  (`pool`/`paired`/`retired`) abgeleitet aus `heating_zone_id` +
  `retired_at` (Sprint 13b). Pool-Rows in CSV mit leeren ersten
  vier Spalten.
- **Eingangstest:** auf 6 Schritte erweitert (RUNBOOK §10h.1, incl.
  non-blocking Schritt 0 als OW-Re-Send), nicht 4 wie Skizze.

### Tasks Ist (Commits siehe STATUS §2at)

- T1 — Master-Inventar-Format-Doku `docs/inventar/README.md` (XLSX
  selbst NICHT im Repo, S4/S5).
- T2 — `PairingCsvRow` Pydantic-Modell + Pool-Konsistenz-Validator.
- T3 — CSV-Parser + `validate_against_db` + DevEUI-Duplikat-Check.
- T4 — Pairing-Service mit Gate-Stack + Savepoint-Isolation +
  `DEVICE_PAIRED`-Audit.
- T5 — Eingangstest-Modul (RUNBOOK §10h.1, 6 Schritte).
- T6 — CLI-Entrypoint mit 4 Subcommands + Auto-Detect.
- T7 — RUNBOOK §10h.2 Pre-Pairing-Skript-Anwendung.
- T8 — Live-Verify auf lokaler heizung-test-DB (Pool-Smoke).
- T9 — STATUS + SPRINT-PLAN + Backlog + PR + Tag.

### Out of Scope 13a (in 13b)

- Migration 0018 (kommt in 13b)
- Frontend-Dialog (kommt in 13b)
- Engine-Read-Stellen-Umbau (kommt in 13b)
- `retire-device`-Subcommand (verworfen, kommt als
  POST-Endpoint in 13b)

## Sprint 13b — Tausch-Endpoint + Frontend-Dialog + Migration 0018

**Cut 2026-05-23 (Strategie-Chat):** Aufgespalten in 13b.1 (Backend,
abgeschlossen 2026-05-23 — siehe STATUS §2au) und 13b.2 (Frontend,
geplant).

### Sprint 13b.1 ✅ Backend abgeschlossen 2026-05-23

**Status:** Code-Phase fertig, Live-Verify auf heizung-test pending
(T7 nach Merge). PR-Erstellung in T8b.
**Tatsaechliche Dauer:** ~6 h Code + ~1 h Doku.
**Branch:** `feature/sprint-13b1-device-lifecycle` (7 Commits).
**Tag (geplant):** `v0.1.18b1-device-replacement-backend`.

Geliefert:

- Migration 0018 (`retired_at`, `retired_reason`,
  `replaced_by_device_id`, Partial-Unique-Index,
  `is_active`-Drop). Minimal — **KEIN** `pairing_status`-Feld
  (Strategie-Entscheidung 2026-05-23, B-Sprint13a-5 verworfen).
- `services/device_service.py`: `get_active_devices_for_zone`,
  `get_pool_devices`, `replace_device` (race-safe via UPDATE-
  WHERE-rowcount-Check), `retire_device`. Drei Exceptions
  (`DeviceNotFound`/`DeviceStateError`/`PoolDeviceUnavailable`).
- 6 §L-Stellen umgestellt (T4.1-T4.6, 6 dedizierte Tests).
- 3 API-Endpoints (`GET /devices/pool`,
  `POST /{id}/replace/from-pool`, `POST /{id}/retire`) +
  Listen-Default-Filter `retired_at IS NULL` mit
  `?include_retired=true`-Opt-In.
- `BusinessAudit DEVICE_REPLACED` (eine Row pro Tausch, AE-57
  Entscheidung 6) + `DEVICE_RETIRED` (Stilllegung ohne Ersatz).
- 40 neue Tests (3 Migration + 6 Helper + 6 §L + 13 Service +
  12 API). Voll-Suite 518 passed, 1 xfailed.

Out of Scope 13b.1 → 13b.2:

- Frontend-Dialog "Vicki ersetzen" auf `/zimmer/[id]`
- shadcn `badge`-Komponente falls Reserve-Tag visuell
- Playwright-E2E Tausch-Flow
- B-Sprint13a-8 CLI-Summary-Wording / B-Sprint13a-9 Dry-Run-Msg

### Sprint 13b.2 ✅ Frontend abgeschlossen 2026-05-24

**Status:** Code + Tests + Doku fertig auf
`feature/sprint-13b2-device-replacement-frontend` (13 Commits auf
develop @ `72a6e16`). PR-Erstellung in T9 nach Strategie-Chat-
Freigabe, Tag in Stop 6.
**Tatsaechliche Dauer:** ~4 h Code + ~1 h Doku (statt 3-5 h Brief-
Schaetzung — Brief-Plus-Adds aus Drift-Resolutionen).
**Branch:** `feature/sprint-13b2-device-replacement-frontend`.
**Tag (geplant nach Merge):** `v0.1.18b2-device-replacement-frontend`.

Geliefert (Brief-T1-T8 + 4 Brief-Plus-Adds):

- T1.c `frontend/src/lib/api/devices.ts`: 3 typisierte Client-
  Funktionen `getPool`, `replaceFromPool`, `retireDevice` plus 2
  Request-Types in `types.ts`.
- T1.b `frontend/src/lib/api/hooks-devices-lifecycle.ts` (neu):
  `useDevicePool` (staleTime 10s, Race-relevant), `useReplaceFromPool`
  + `useRetireDevice` (Mutations mit optional `roomId`-Param fuer
  zone-spezifische Invalidation).
- T2 `frontend/src/components/ui/badge.tsx` (neu): shadcn-Standard,
  4 Varianten, Token-Konvention konsistent zu dialog.tsx + select.tsx.
- T3 DevicesInRoom-Erweiterung (`/zimmer/[id]/page.tsx`): 2 Action-
  Buttons (`swap_horiz Tauschen`, `power_off Stilllegen`) pro Device-
  Row + State-Anker `openReplaceDialog` / `openRetireDialog`.
- T4 `components/patterns/replace-device-dialog.tsx`: Pool-Dropdown
  via Select, Empty-State, 409-Subtype-String-Match (RE_POOL +
  RE_DEVICE_STATE), Toast-Wiring.
- T5 `components/patterns/retire-device-dialog.tsx`: Reason-Dropdown
  (4 feste Optionen Defekt/Batterie leer/Verlust/Wartung),
  Last-Active-Warning bei 1-Vicki-Zone, destructive Confirm-Button.
- T6 Reserve-Badge in `/devices`-Liste (`LabelCell`) bei
  `heating_zone_id === null && retired_at === null`.
- T7 + T7-prep `scripts/pair_devices.py`: B-Sprint13a-8 +
  B-Sprint13a-9 CLI-Wording-Fixes Cross-Sprint-Touch. Plus Fixture-
  Suffix-Patch in `test_pair_devices_cli.py` analog §5.18 (Pre-
  existing Test-Hygiene-Bug).
- T8 `frontend/tests/e2e/sprint13b2-device-replacement.spec.ts`:
  5 Playwright-Cases (Replace Happy/Pool-leer/Pool-Race-409/Retire
  Happy/Last-Active-Warning).
- T9 Doku: STATUS §2av + SPRINT-PLAN + AE-57-Status + RUNBOOK
  §10j.6 + CLAUDE.md §5.63 + Backlog-Updates (dieser Commit).

Brief-Plus-Adds (Drift-Resolutionen Strategie-Chat 2026-05-23):

- T1.d `components/ui/form-dialog.tsx` (neu): FormDialog-Primitive
  mit children-Body-Slot (Drift-4 — ConfirmDialog Confirm-only-
  Pattern reicht nicht fuer Pool/Reason-Dropdown).
- T1.c-prep `types.ts` + 3 Konsumenten + 3 e2e-Mocks: Lifecycle-
  Type-Drift gegen Backend post-13b.1 (Live-UX-Bug-Fix:
  Devices zeigten "Eingerichtet: nein" weil `is_active` weg —
  Brief-Luecken-Klasse analog §5.30/§5.43, neue Lesson §5.63).
- T0.6 sonner Toast-Library + `lib/toast.ts`-Wrapper (Drift-5 —
  Toast-Lib war im Repo nicht vorhanden, Brief verlangte sie).
- T7-prep Fixture-Suffix in `test_pair_devices_cli.py` (§5.18-
  Konformitaet).

**Tests:** Frontend type-check + lint + Playwright **58 passed
(43.5s)**, davon 5 neu in T8. Backend ruff format/check + mypy
strict + pytest **240 passed / 279 skipped / 0 failed** post-T7-
prep (Skip-Vorbehalt: ohne `TEST_DATABASE_URL`; CI deckt die 279
DB-Tests).

**Diff-Summe (T1-T9):** 20 Files, +1283 Insertions / −17 Deletions
in 14 Commits (13 Feature/Fix/Test + 1 Doku).

**Live-Verify:** Cowork-Auftrag formuliert nach Merge separat
(Strategie-Chat), Befund spaeter in STATUS §2av nachgepflegt.

### Out of Scope 13b (gesamt)

- gRPC-ChirpStack-Bootstrap (verworfen 2026-05-21)
- Pairing-Wizard-UI (verworfen 2026-05-21)
- Pilot-Zimmer-Auswahl (Backlog B-11prep-4)
- DEV_EUI-Wiederverwendung nach Retire im CSV (B-13b-1, eigener
  Sprint)

---

# SPRINT 14 — Cross-Sicht-UI + Health-Badges + Mail-Platzhalter (Phase 1)

**Priorität:** 🟠 (Phase-1-Abschluss vor 14b)
**Geschätzte Dauer:** 1-2 Wochen
**Autonomiestufe:** 2
**Voraussetzung:** Sprint 13 abgeschlossen (+ Hygiene-Mini-Sprint `v0.1.18c`)
**Tag nach Abschluss:** `v0.1.19-cross-sicht-ui` (Sammel; Sub-Sprints mit
eigenen Tags `v0.1.19a/b/c`)

## Sub-Sprint-Split (Strategie-Chat 2026-05-25, D1)

Sprint 14 wird in drei Sub-Sprints umgesetzt, jeder mit eigenem Phase-0
+ Live-Verify:

- **14a — Geräte-Liste + Detail + Hardware-Nummer:** ✅ abgeschlossen
  2026-05-26 (STATUS §2ay; AE-61; Migration `0020`; enriched DeviceRead;
  3-Spalten-Liste; Detail-Karten + 7 Kacheln; ZoneHealthBadge).
  Tag `v0.1.19a-cross-sicht-devices`.
- **14a.1 — Spalten-Split „Status" → „Gerät" + „Zone" (Hotfix):** ✅
  abgeschlossen 2026-05-27 (STATUS §2az; PR #187; `1f6c132`; §5.66).
  Tag `v0.1.19a.1-cross-sicht-hotfix`. **Live-Verify pending** (Cowork
  lokal OK; heizung-test Deploy-Stall, §5.67).
- **14b — Zimmer-Detail-Restruktur (Zone-Karten, additiv Variante B/B'):**
  ✅ abgeschlossen 2026-05-27 (STATUS §2ba; PR #191; `a59b7aa`; AE-62;
  §5.69). Tag `v0.1.19b-cross-sicht-zimmer-detail`. Live-Verify auf
  heizung-test bestätigt (Block-A war Phantom, §5.68). Link-out-Variante
  (Override-Steuerung bleibt im Übersteuerung-Tab).
- **14c — Dashboard (KPI-Kacheln + Mail-Platzhalter Alarm-Stufe 2/3):**
  ✅ abgeschlossen 2026-05-28 (STATUS §2bb; Tag v0.1.19c-cross-sicht-dashboard;
  6 KPI-Kacheln; GET /api/v1/dashboard/kpi; Logger-Payload 4→10 Felder additiv).
  Phase-3-Cross-Sicht-UI komplett (3/3 Sub-Sprints durch).
- **14d — Override-Sichtbarkeit (Block A + FU-4-Eval + FU-6-Wording):**
  ✅ abgeschlossen 2026-05-30 (STATUS §2bc; Tag v0.1.19d-override-sichtbarkeit
  pending — nach Merge + Cowork-Begehung). Zimmer-Liste zeigt „Aktiv"-
  Indikator (R-A/R-B drei exklusive Zustände, Single-Zelle); RoomRead.
  `has_active_override` via 1-Batch-Query (R-D, kein N+1); HeatingZoneRead.
  `active_override` ersetzt useZoneOverride-Roundtrip (FU-5); SOURCE_LABEL
  zeigt Quelle Gast/Mitarbeiter (FU-6 Option A); FU-4-Doku-Eval Status Quo
  (kein UI-Refactor, B-14b-FU-4 bleibt Backlog).

**Phase-3-Cross-Sicht-UI-Stand:** ✅ 3/3 Sub-Sprints durch (14a + 14b + 14c),
plus 14d Override-Sichtbarkeits-Hygiene.

> Hinweis: „SPRINT 14b — arc42-Konsolidierung" weiter unten ist ein
> separater Doku-Sprint, NICHT der Cross-Sicht-Sub-Sprint 14b.

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

> **⚠️ SUPERSEDED (2026-06-09, Sprint 15g, AE-67).** Dieser Sprint (klassische
> heizung-main-Daten-Migration: 9.8a-Stand → develop, Migrationen 0005–0015,
> Auth-Cutover, Migrations-Trockenlauf, DR-Drill) wird **nicht mehr
> ausgeführt**. Ersetzt durch den **Prod-Domain-Promote** (Sprint 15g):
> heizung-test ist datenführend und wurde zur Prod-Domain promotet — kein
> main-Strang, keine Daten-Migration (Begründung: AE-67). Die Aufgabe
> „Backup-Cron + Off-Site-Replikation" ist via Block A (Sprint 15g) erledigt.
> Text unten nur noch historisch.

> **Hinweis (Hotelier-Entscheidung 2026-06-07):** Nummer und Termin
> bewusst offen. Die hier genutzte „15" ist historisch (STATUS §2bg,
> getrennter Track) und nicht bindend; der Cutover kommt nach der
> letzten Feature-Funktion.

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
- Migrationen 0005-0015 anwenden (inkl. 0015_health_state aus Sprint 11)
- Auth-Bootstrap mit echten Hotel-User-Daten
- `AUTH_ENABLED=true`-Cutover analog Sprint 9.17a/b
- Backup-Cron (OP-1) + Off-Site-Replikation
- Disaster-Recovery-Drill bestanden
- Migrations-Trockenlauf gegen heizung-test-Datenstand

---

# SPRINT 16 — Test→Main-Sync + Last-Test + Bug-Fixing (Phase 4)

> **⚠️ SUPERSEDED (2026-06-09, Sprint 15g, AE-67).** Setzt den main-Strang aus
> Sprint 15 voraus, den es nicht mehr gibt (Single-Server-Prod, kein
> main-Strang). Der Last-Test-/Bug-Fixing-Anteil (synthetische Readings für
> ~100 Vickis, Engine-Performance unter Last) bleibt als Kandidat relevant
> und wird bei Bedarf neu als eigener Sprint geschnitten — ohne Test→Main-Sync.

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
| `v0.1.17-multivicki-fenster` | Sprint 12: Mehrfach-Vicki Schreiben + Fenster belegungs-abhängig + Override-Reject 409 (AE-51 P3 / AE-52 / AE-55 / AE-56) |
| `v0.1.17a-override-zone-scope` | Sprint 12a (Folge): Override-Zone-Scope + Frontend-Hinweis (Fenster-offen-Vorpruefung, R4-Erledigung) |
| `v0.1.18-pairing-wizard` | Sprint 13: Pairing-Wizard + Mass-Pairing-CSV + Eingangstest |
| `v0.1.19-cross-sicht-ui` | Sprint 14: Cross-Sicht-UI + Health-Badges + Mail-Platzhalter |
| `v0.1.20-arc42-konsolidierung` | Sprint 14b: arc42-Doku-Konsolidierung (Phase-1-Abschluss) |
| `v0.2.0-main-cutover` | **SUPERSEDED** (AE-67 / Sprint 15g) → ersetzt durch **`v0.2.0-prod-domain`** (Prod-Domain-Promote statt main-Migration). Finale Tag-Vergabe offen (Strategie/Hotelier nach C1), hier nur Doku-Name vereinheitlicht. |
| `v0.2.1-test-main-sync` | **SUPERSEDED** (AE-67) — Test→Main-Sync entfällt mit dem main-Strang; Last-Test/Bug-Fixing-Anteil ggf. als eigener Sprint. |
| `v0.2.2-pms-fias` | Sprint 16a (conditional): PMS-Casablanca-Integration (Phase 5) |
| `v0.2.3-pre-pairing` | Pre-Pairing (Phase 4b) |
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
- B-14c-FU-1 🟢 3 PMS-/Wetter-Kacheln (Check-in, Außentemperatur, Energiestatus)
  reaktivieren nach Sprint 16a (Casablanca-PMS) + Wetter-Service-Sprint
- B-14c-FU-2 🟢 Component-Test-Runner (vitest) evaluieren, falls patterns/-Komponenten
  wachsen (heute nur Playwright + tsc)
- B-14c-FU-3 🟢 User.display_name-Feld backend-seitig (Migration + Schema +
  Benutzer-UI), Dashboard-Greeting nutzt Klarname statt E-Mail

## Was nach Go-Live kommt (außerhalb dieses Plans)

- Klimaanlagen-Domain (Phase 2)
- KI-Layer (Layer 6+) auf Wetter+Sensor+Event-Log-Basis
- Reporting-Modul mit Energie-Verbrauchs-Auswertung
- Multi-Hotel-Rollout (Tenant 2, 3, ...)
- iOS/Android-Apps für Hotelier-Mobile-Use
