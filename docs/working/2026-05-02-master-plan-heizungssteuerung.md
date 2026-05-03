# Master-Plan Heizungssteuerung — UX-Konzept und Architektur

**Datum:** 2026-05-02
**Autor:** Claude (Sparringspartner)
**Status:** Entwurf zur User-Bestätigung
**Bezug:** STRATEGIE.md v1.0, ARCHITEKTUR-ENTSCHEIDUNGEN.md v1.2 (AE-01 bis AE-25), QA-Audit 2026-04-29, Betterspace-Screenshots vom 2026-05-02
**Ersetzt:** ADR-Skizze AE-26 bis AE-32 aus dem vorherigen Sprint-8-Vorgespraech

---

## 0. Executive Summary (TL;DR)

Die Heizungssteuerung ist der Kern. Wir haben heute: **stabiles Datenmodell**, **vier gepairte Vicki-TRVs**, **Live-Telemetrie-Pipeline** (LoRaWAN -> ChirpStack -> MQTT -> TimescaleDB -> Frontend), **leeres Regel-Engine-Verzeichnis**. Die Strategie und das Datenmodell sind ueberraschend gut vorbereitet: `rule_config` mit Scope-Hierarchie (global/room_type/room) ist bereits da, `room`/`room_type`/`heating_zone`/`occupancy`/`device`/`control_command` ebenso.

**Was fehlt fachlich:** Saison-Zeitraeume, Sommermodus-Schalter, Szenarien-Stammdaten als orthogonale Aktivierungs-Schicht, einmalige manuelle Temperatur-Setzung, Belegungs-UI, Heatmap/Floorplan-View. Plus: die Regel-Engine selbst.

**Was fehlt UX:** Eine vollstaendige Information-Architecture, die nicht nur "Devices listen" zeigt (Sprint 7) sondern dem Hotelier in 3 Klicks zu "Welche Raeume verbrauchen heute Energie und warum?" fuehrt.

**Empfehlung:** Sechs-Sprint-Bogen `Sprint 8` bis `Sprint 13` (rund 4-6 Wochen Arbeitsblock). Sprint 8 = Datenmodell-Erweiterung + Belegung. Sprint 9 = Regel-Engine + Downlink. Sprint 10 = Saison/Szenarien/Sommermodus. Sprint 11 = Dashboard + Heatmap-View. Sprint 12 = Mobile-Tuning + Profile. Sprint 13 = Pilotbetrieb-Reife (Monitoring, Alerts, KPI-Reports).

Das Bauteil "echte Regel-Engine + Downlink" ist der **groesste Wertschritt**. Alles davor ist Vorbereitung, alles danach Komfort.

---

## 1. Stand heute (2026-05-02)

### 1.1 Was laeuft

| Schicht | Status |
|---|---|
| Hardware | 4x MClimate Vicki TRV + 1x Milesight UG65 Gateway live in Hotel-LAN |
| Edge | UG65 sendet via MQTT ans Mosquitto auf `heizung-test` |
| Datenpipeline | ChirpStack v4 dekodiert (Codec `mclimate-vicki.js`), MQTT-Subscriber persistiert in TimescaleDB |
| API | FastAPI mit Devices-CRUD + Sensor-Readings-Endpoint + Health |
| Auth | Caddy-Basic-Auth site-wide (Sprint 8a, K-1 interim) |
| Frontend | Next.js 14 App Router, `/devices` Liste + `/devices/[id]` Detail mit Recharts-24h-Verlauf |
| Datenmodell | `room_type`, `room`, `heating_zone`, `device`, `occupancy`, `rule_config`, `control_command`, `sensor_reading` (Hypertable) |
| Regel-Engine | `backend/src/heizung/rules/__init__.py` ist leer. Nur `constants.py` mit `FROST_PROTECTION_C=10.0`. |
| Belegung | Datenmodell vorhanden, KEIN UI, KEINE Schreibwege |
| Downlink | KEIN Code, keine Mosquitto-Publish-Logik fuer Setpoints |
| Saison/Szenarien/Sommermodus | KEIN Code, KEINE Tabellen |
| Mobile-Optimierung | Layout responsive, aber keine echte Mobile-First-UX |

### 1.2 Tags

`v0.1.7-frontend-dashboard` (2026-05-01) ist aktueller Stand. K-1 Auth ist als Sprint 8a auf beiden Servern deployt.

### 1.3 Was nicht funktioniert

- Es heizt kein einziger Setpoint-Befehl bisher. Alle Vicki-Werte sind direkt am Geraet manuell eingestellt.
- Kein Hotelier kann heute eine Belegung im UI eintragen.
- Kein Hotelier sieht im UI, was die Engine "denkt" - es gibt keine Engine.

---

## 2. Markt-Recherche: Was machen die anderen?

### 2.1 Betterspace (Ist-Zustand des Hoteliers, abloesendes System)

Quelle: betterspace360.com + Hotel-Tech-Report + die geposteten Screenshots.

**Top-Level-Aktionen im Heizungs-Modul:**
- Szenarien (Aktivierung/Deaktivierung pro Raumtyp)
- Temperatur setzen (einmalige Aktion)
- Sommermodus (deaktiviert Szenarien-Set)
- Saison (Zeitraeume mit Sondereinstellungen)
- Raumtypen (Stammdaten + Default-Temperaturen)

**Globale Einstellungen (Zeiten):**
Geraetebenachrichtigungen-Cron, Check-in-Default-Zeit (14:00), Check-out-Default-Zeit (11:00), Tagabsenkung-Fenster (09:00-15:00), Nachtabsenkung-Fenster (00:00-06:00), Lichtaktivierung-Zeit (15:00).

**Globale Temperaturen:**
Realtime-Check-in-Offset, Tagabsenkung-Temp + Offset, Nachtabsenkung-Temp + Offset, Fensteroffset, Check-out-vorzeitig-Temp, Vorheizen-Offset.

**Klimaanlagen-Sektion** (fuer das Hotel Sonnblick out-of-scope, da nur Heizkoerper).

**22+ Szenarien** (im Screenshot sichtbar): Automatischer Temperatur Reset, Belegungsplan, Bewegungssteuerung, Elektroheizung, Fenstererkennung, Frueher Check-In/Check-Out, Gute Nacht, Heizprofil, Klimaanlage, Licht (3 Szenarien), Nachtabsenkung mit Offset, Realtime Check-in, Realtime Check-out, Standard Wunschtemperatur, Strom An/Aus Belegungsplan, Tagabsenkung mit Offset, Temperaturgrenzen, Unbelegt Temperatur erzwingen, Unsicheres Vorheizen, Verzoegerter Check-In.

**Raumtypen** (Beispiel): Schlafzimmer (ID 4), Studio (ID 6), Tagungsraum (ID 3) - jeweils Obere/Untere Grenze + besetzt/frei + drei Flags ("Gasttemperatur speichern", "Raumtemperatur aus Raumtyp berechnen", "Wunschtemperatur auf Raumtyp beziehen").

**Schwaechen die wir nicht uebernehmen:**
- Konfusionspunkte zwischen "Tagabsenkung Temperatur" und "Tagabsenkung Offset" (zwei Eingaben, eine wirkt - intransparent).
- Drei Flags pro Raumtyp die schwer erklaerbar sind.
- Lange flache Szenarien-Liste ohne Gruppierung/Suche.
- Kein klares Diff-View "alter Wert vs. neuer Wert" beim Ueberschreiben pro Zimmer.

### 2.2 Honeywell INNCOM (Marktfuehrer Mid-Market Hotels)

- Energieeinsparung 25-40% pro Zimmer
- PMS-Integration zentral, "controlled loads" werden bei unverkauften Zimmern ganz abgeschaltet
- INNCOM Direct (2024): vereinfachte Variante fuer Mid-Market
- **UX-Stark:** Single-Pane-of-Glass Dashboard mit Floorplan-View

### 2.3 Telkonet EcoSmart (PIR-getrieben)

- "EcoSmart Recovery Time" - das Zimmer wird von "frei"-Setpoint zurueck zu "besetzt"-Setpoint **bevor der Gast den Unterschied bemerkt** (predictive)
- PIR-Sensoren erkennen tatsaechliche Anwesenheit (besser als reine PMS-Signale)
- Reports nach Raum/Stockwerk/Property sortierbar
- **UX-Stark:** Mobile-Geolocation-Pre-Arrival fuer Apartments (fuer Hotel weniger relevant)

### 2.4 Loxone (Smart-Building, kein reiner Hotel-Player)

- Eigene Loxone-Hardware, prop. Bus
- 70% Heiz/Kuehl-Ersparnis im Test-Campus
- Sehr starke UI-Skalierbarkeit
- **Nachteil:** komplett vendor-locked, nicht fuer LoRaWAN-Open-Stack

### 2.5 Best-Practice-Synthese fuer unser System

| Pattern | Quelle | Uebernahme |
|---|---|---|
| 5-Schichten-Regel-Pipeline | AE-06 (eigen) + INNCOM | JA - bereits ADR |
| PIR-getriebene Realtime-Belegung | Telkonet | LATER - braucht Hardware (Sprint 14+) |
| Predictive Recovery vor Belegung | Telkonet | JA - das ist unser "Vorheizen" (R2) |
| Floorplan-View Dashboard | INNCOM | JA - Sprint 11 |
| Mobile-First fuer den Hotelier | Mews/Telkonet | JA - Sprint 12 |
| Energie-KPI-Reports | INNCOM/EcoCentral | JA - Sprint 13 |
| Single-Pane-of-Glass | INNCOM | JA - Dashboard-Redesign Sprint 11 |
| Open-LoRaWAN statt Vendor-Hardware | (eigen) | JA - bereits umgesetzt |
| Audit-Log "Warum hat die Engine was gemacht" | (eigen, AE-08) | JA - bereits in `control_command.rule_context` |
| **Diff-View beim Ueberschreiben** (Raumtyp -> Raum) | (Mehrere Sources erwaehnen "transparency") | JA - eigener UX-Punkt, fehlt allen Konkurrenten |
| **Was-wuerde-passieren-Simulator** (vor Speichern zeigen, wie sich Settings auf 24h auswirken) | (kein Konkurrent kann das) | NICE-TO-HAVE - Sprint 14+ |

---

## 3. Funktions-Vollkatalog (kondensiert)

Master-Liste aller ueberhaupt sinnvollen Funktionen. Klassifikation: **MVP** (Sprint 8-13), **Backlog** (Sprint 14+), **Nicht uebernehmen** (out-of-scope fuer Hotel Sonnblick).

### 3.1 Heiz-Regeln (die "8 Kernregeln" plus Erweiterungen)

| # | Regel | Status | Klassifikation |
|---|---|---|---|
| R1 | Belegungsabhaengige Standard-Temperatur (T_belegt / T_frei) | Strategie + Datenmodell vorhanden, Engine fehlt | MVP Sprint 9 |
| R2 | Vorheizen 90 Min vor Check-in (Predictive Recovery) | Strategie vorhanden | MVP Sprint 9 |
| R3 | Check-out-Absenkung 30 Min nach Auszug | Strategie vorhanden | MVP Sprint 9 |
| R4 | Nachtabsenkung 00:00-06:00 (konfigurierbar) | Strategie vorhanden | MVP Sprint 9 |
| R5 | Fenster-offen-Erkennung (Vicki-onboard, AE-04) | Codec-Feld vorhanden, Reaktion fehlt | MVP Sprint 9 |
| R6 | Gast-Override mit Capping + Schaltpunkt-Ende (AE-10) | Vicki sendet manual_setpoint, Reaktion fehlt | MVP Sprint 9 |
| R7 | Unbelegt-Langzeit-Absenkung (>24h frei -> 15 Grad) | Strategie vorhanden | MVP Sprint 9 |
| R8 | Frostschutz 10 Grad (Systemkonstante) | `constants.py` vorhanden, Engine wendet nicht an | MVP Sprint 9 |
| R9 (neu) | Tagabsenkung 09:00-15:00 (aus Betterspace-Screenshot) | Datenmodell-Erweiterung noetig | MVP Sprint 10 |
| R10 (neu) | Sommermodus (Heizung komplett aus, nur Frostschutz) | Datenmodell + UI noetig | MVP Sprint 10 |
| R11 (neu) | Saison-Override (z.B. Skisaison anders als Sommer) | Datenmodell + UI noetig | MVP Sprint 10 |
| R12 (neu) | Verzoegerter Check-In (geplante Reservierung haelt erst spaeter Vorheizung) | Konflikt mit R2, klaeren | Backlog Sprint 14+ |
| R13 (neu) | Realtime-Bewegungs-Check-in (PIR triggert "ist da") | Hardware fehlt | Backlog Sprint 14+ |
| R14 (neu) | Heizprofil pro Wochentag (Mo-Fr anders als Sa-So) | Spezialfall | Backlog Sprint 14+ |
| R15 (neu) | Anomalie-Detection (Vicki dauer-offen, Batterie schwach, Kein-Uplink-2h) | KPIs fuer Monitoring | MVP Sprint 13 |

### 3.2 Stammdaten-Verwaltung

| # | Feature | Klassifikation |
|---|---|---|
| S1 | Raumtypen-CRUD (Schlafzimmer, Studio, Tagungsraum, ...) | MVP Sprint 8 |
| S2 | Zimmer-CRUD (Nummer, Etage, Orientation, Notes) | MVP Sprint 8 |
| S3 | Heizzone-CRUD (Schlafzimmer, Bad, Handtuchtrockner) | MVP Sprint 8 |
| S4 | Geraet-CRUD (vorhanden) + Geraet-zu-Zone-Zuordnung-UI | MVP Sprint 8 |
| S5 | Saison-CRUD (Zeitraeume mit Override-Settings) | MVP Sprint 10 |
| S6 | Szenario-CRUD (Stammdaten + Aktivierung pro Scope) | MVP Sprint 10 |
| S7 | Sommermodus-Schalter (global, mit Datum-from/to) | MVP Sprint 10 |
| S8 | User-Verwaltung (echte Auth, RBAC) | Sprint 14+ (K-1 Interim ist ausreichend bis dahin) |

### 3.3 Belegung

| # | Feature | Klassifikation |
|---|---|---|
| B1 | Belegung manuell anlegen (room_id, check_in, check_out, guest_count) | MVP Sprint 8 |
| B2 | Belegung-Liste mit Filtern (heute, naechste 7 Tage, nach Zimmer) | MVP Sprint 8 |
| B3 | Belegung im Kalender-View | MVP Sprint 11 |
| B4 | Belegung stornieren (soft delete, Audit) | MVP Sprint 8 |
| B5 | Belegung importieren via CSV (vor PMS-Connector) | Backlog Sprint 14+ |
| B6 | PMS-Connector (Casablanca, Apaleo, Mews) | Backlog Sprint 14+ |
| B7 | Realtime-Update via WebHook vom PMS | Backlog Sprint 14+ |

### 3.4 Aktionen (manuelle Eingriffe)

| # | Feature | Klassifikation |
|---|---|---|
| A1 | "Temperatur jetzt setzen" (one-off, fuer Raumtyp/Raum, 1-24 h) | MVP Sprint 10 |
| A2 | "Bevorzugen" (Raum als VIP markieren, Override aller Setbacks) | Backlog Sprint 14+ |
| A3 | "Wartungsmodus" pro Raum (kein Setpoint, manuelle Steuerung am Vicki) | MVP Sprint 8 (Status BLOCKED reicht) |
| A4 | Manueller Downlink-Test (Diagnose im UI) | MVP Sprint 9 |
| A5 | Bulk-Aktion auf alle Zimmer eines Raumtyps | MVP Sprint 10 |

### 3.5 Visualisierung & Dashboard

| # | Feature | Klassifikation |
|---|---|---|
| V1 | Dashboard mit 6 KPI-Cards (vorhandene Strategie 8.4) | MVP Sprint 11 |
| V2 | Floorplan-View (Hotelplan mit eingefaerbten Raeumen, klickbar) | MVP Sprint 11 |
| V3 | Pro-Zimmer-Live-Status (Ist/Soll/Status/Letzter Befehl) | MVP Sprint 11 |
| V4 | 24h-Recharts-Verlauf pro Geraet (vorhanden Sprint 7) | MVP - schon da |
| V5 | Wochen/Monat-Verlauf pro Zimmer | MVP Sprint 13 |
| V6 | Heatmap "Welche Zimmer sind heute am meisten gelaufen?" | MVP Sprint 13 |
| V7 | Belegungs-Auslastungs-Chart | MVP Sprint 13 |
| V8 | Energie-KPIs (Heizgrad-Stunden, Differenz vs. Vormonat, vs. Vorjahr) | Backlog (braucht Verbrauchszaehler) |
| V9 | Audit-Log-View (Was hat die Engine gemacht und warum) | MVP Sprint 11 |

### 3.6 Mobile / Touch

| # | Feature | Klassifikation |
|---|---|---|
| M1 | Mobile-First-Layout fuer Sidebar (Bottom-Tab oder Drawer) | MVP Sprint 12 |
| M2 | Touch-Targets >= 44x44 (Strategie A28) | MVP Sprint 12 |
| M3 | "Heute"-Quick-View fuer Hotelier am Smartphone | MVP Sprint 12 |
| M4 | Push-Notifications (PWA) | Backlog Sprint 14+ |
| M5 | Offline-First-Anzeige (zeigt letzten Stand wenn keine Connection) | Backlog Sprint 14+ |

### 3.7 Monitoring & Ops

| # | Feature | Klassifikation |
|---|---|---|
| O1 | Geraet-Health (Battery, RSSI, Last-Seen) - vorhanden | MVP - schon da |
| O2 | Email-Alert "Vicki seit 2h offline" | MVP Sprint 13 |
| O3 | Email-Alert "Batterie < 20%" | MVP Sprint 13 |
| O4 | Email-Alert "Engine Downlink failed" | MVP Sprint 13 |
| O5 | Backup-Strategie (`pg_dump` + Off-Site, H-8) | MVP Sprint 13 |
| O6 | Echte User-Auth + Audit-Log (NextAuth, K-1 Replacement) | Sprint 14+ |
| O7 | Lasttest mit 130 simulierten Geraeten | Backlog vor Vollausbau |

### 3.8 Out-of-Scope (bewusst NICHT bauen)

- Klimaanlage-Steuerung (Strategie A6: spaeter)
- Lichtsteuerung (Betterspace-Szenario, fuer Hotel Sonnblick nicht aktuell)
- Strom-/Steckdosen-Steuerung
- Gute-Nacht-Szenario (Licht + Vorhang + Heizung kombiniert)
- Bewegungsmelder-Steuerung
- Elektroheizung (Backup, nicht primaer)
- Multi-Hotel-Mandantenfaehigkeit (Strategie A3 langfristig, aber nicht jetzt)

---

## 4. Datenmodell-Erweiterungen (Migration 0003)

### 4.1 Was bereits da ist (NICHT neu erfinden)

`room_type`, `room`, `heating_zone`, `device`, `occupancy`, `rule_config` (mit Scope-Hierarchie), `control_command`, `sensor_reading`. Das Modell traegt heute schon **R1 bis R8 plus Drei-Ebenen-Konfiguration**.

### 4.2 Was neu kommt (Migration 0003)

**Tabelle `season`** (Zeitraum-Override fuer rule_config-Werte)

```
season
  id PK
  name TEXT (z.B. "Winter 2026/27", "Sommerpause", "Skisaison")
  starts_on DATE (inklusiv)
  ends_on DATE (inklusiv)
  is_active BOOL (kann auf inaktiv gestellt werden ohne loeschen)
  notes TEXT
  created_at, updated_at
```

Die in `rule_config` referenzierte Settings koennen via `season_rule_config` ueberschreiben. Vorschlag: Erweitere `rule_config` um optionale `season_id` FK. Wenn `season_id IS NOT NULL`, gilt der Eintrag NUR im Saison-Zeitraum. Resolution-Reihenfolge dann:

```
1. Saison-spezifisch ROOM
2. Saison-spezifisch ROOM_TYPE
3. Saison-spezifisch GLOBAL
4. Permanent ROOM
5. Permanent ROOM_TYPE
6. Permanent GLOBAL
7. Hardcoded Default
```

**Tabelle `scenario`** (Stammdaten der Szenarien)

```
scenario
  id PK
  code TEXT UNIQUE (z.B. "day_setback", "night_setback", "checkin_realtime")
  name TEXT (z.B. "Tagabsenkung", "Nachtabsenkung")
  description TEXT
  is_system BOOL (TRUE fuer mitgelieferte Standard-Szenarien, FALSE fuer Custom)
  default_active BOOL (Default-Aktivierung global)
  parameter_schema JSONB (Zod-aequivalentes Schema, dokumentiert welche Parameter erlaubt sind)
  created_at, updated_at
```

**Tabelle `scenario_assignment`** (Aktivierung pro Scope, mit ueberschreibenden Parametern)

```
scenario_assignment
  id PK
  scenario_id FK
  scope ENUM (global, room_type, room)
  room_type_id FK NULL
  room_id FK NULL
  is_active BOOL
  parameters JSONB (Override der Defaults aus scenario.parameter_schema)
  season_id FK NULL (optional saisonal limitiert)
  created_at, updated_at
  CHECK: scope-Konsistenz (gleicher Pattern wie rule_config)
  UNIQUE: (scenario_id, scope, room_type_id, room_id, season_id)
```

**Singleton-Tabelle `global_config`** (oder als spezieller `rule_config` global)

Diskussion: braucht es eine separate Tabelle? Die Strategie-Werte (Check-in/Check-out-Default-Zeit, Sommermodus-Flag, Email-Adressen fuer Alerts) sind nicht "Regel-Parameter" im engeren Sinne. Empfehlung:

```
global_config (Singleton, immer 1 Row mit id=1)
  id PK = 1 (CHECK constraint)
  default_checkin_time TIME (Default 14:00)
  default_checkout_time TIME (Default 11:00)
  summer_mode_active BOOL (Default FALSE)
  summer_mode_starts_on DATE NULL
  summer_mode_ends_on DATE NULL
  alert_email TEXT
  hotel_name TEXT
  timezone TEXT (Default "Europe/Vienna")
  created_at, updated_at
```

**Tabelle `manual_setpoint_event`** (One-Off-Aktion "Temperatur jetzt setzen")

```
manual_setpoint_event
  id PK
  created_by_user_id (NULL solange keine echte Auth)
  scope ENUM (room_type, room)
  room_type_id FK NULL
  room_id FK NULL
  target_setpoint_celsius NUMERIC(4,1)
  starts_at TIMESTAMPTZ (Default NOW)
  ends_at TIMESTAMPTZ (NOT NULL)
  reason TEXT (Optional, "Wartung Fenster", "Spezialgast")
  is_active BOOL (kann manuell beendet werden vor ends_at)
  created_at
  CHECK: scope-Konsistenz
```

Die Engine prueft beim Evaluieren: gibt es ein aktives `manual_setpoint_event` mit jetzt zwischen starts_at und ends_at? Wenn ja, ueberschreibt es R1-R7 (R8 Frostschutz nicht).

### 4.3 Erweiterung `room_type` (kleine Felder)

Aus Betterspace-Screenshot: drei Flags pro Raumtyp. Wir nehmen davon zwei realistische uebernehmen:

```
room_type
  ... vorhandene Felder ...
  + max_temp_celsius NUMERIC(4,1) NULL (Obere Grenze, ueberschreibt rule_config-Default)
  + min_temp_celsius NUMERIC(4,1) NULL (Untere Grenze, ueberschreibt rule_config-Default)
  + treat_unoccupied_as_vacant_after_hours INT NULL (Override fuer R7)
```

Das dritte Flag aus Betterspace ("Wunschtemperatur des Zimmers auf Raumtypen beziehen") ist Implementations-Detail, nicht Datenmodell.

### 4.4 Was wir NICHT machen

- **Keine separate Tabelle pro Szenario.** Das skaliert nicht. Eine `scenario` + `scenario_assignment` mit JSONB-Parametern reicht und ist zukunftsoffen.
- **Keine EAV-Settings-Tabelle.** Wuerde alle Validierung kaputt machen.
- **Keine zweite "config_history"-Tabelle.** Audit-Log via `event_log` (kommt mit Sprint 9), nicht eigene Versionierung pro Tabelle.
- **Keine `holiday`-Tabelle.** Saison loest das via Zeitraeume, das ist ausreichend.

### 4.5 ADRs neu

| ADR | Inhalt | Empfehlung |
|---|---|---|
| AE-26 | 5-Schichten-Resolution erweitert um Saison als oberste Schicht | JA |
| AE-27 | `scenario` + `scenario_assignment` als orthogonale Aktivierungsschicht | JA |
| AE-28 | `global_config` als Singleton-Tabelle statt EAV | JA |
| AE-29 | `manual_setpoint_event` als zeitlich begrenzter Override | JA |
| AE-30 | Saison-Override gilt nur fuer rule_config, NICHT fuer Stammdaten (room_type-Defaults) | JA |
| AE-31 | Engine als reine Funktion (`evaluate(ctx) -> RuleResult`) gemaess AE-08, jetzt mit Saison-Layer | JA |
| AE-32 | Downlink-Hysterese 0.5 Grad (gemaess AE-09) im Code zentralisieren als Konstante | JA |
| AE-33 | Bei Konflikt zwischen mehreren Saisons: spaeteres `starts_on` gewinnt | JA |
| AE-34 | Sommermodus deaktiviert R1-R7, R8 Frostschutz bleibt aktiv. Ist NICHT die "Heizung aus", sondern "minimaler Energieverbrauch fuer Frostschutz" | JA |
| AE-35 | UI-Navigation folgt 6-Bereiche-Struktur statt der bestehenden Sprint-7-Sidebar (siehe §6) | JA |

---

## 5. Regel-Engine: 5-Schichten-Pipeline (gemaess AE-06, erweitert)

Bisherige Spec (AE-06) war 5 Schichten. Wir erweitern um die Saison als Modulator und Sommermodus als Kill-Switch:

```
        Eingang: room_id, jetzt
                 |
                 v
   [0] Fast-Path: Sommermodus aktiv?
       JA -> setpoint = MAX(FROST_PROTECTION_C, season_override or 10)
             reason = "summer_mode"
             return
                 |
                 v
   [1] Base Target (R1, R7)
       Aus rule_config-Hierarchie (Saison > Permanent, Room > Type > Global)
       resultiert T_belegt oder T_frei oder T_long_vacant
                 |
                 v
   [2] Temporal Override (R2 Vorheizen, R3 Check-out, R4 Nacht, R9 Tag)
       Aktive Zeitfenster wenden Offsets/Absoluttemp an
                 |
                 v
   [3] Manual Override
       3a) `manual_setpoint_event` aktiv?  -> ersetzt Setpoint
       3b) Gast-Override am Vicki erkannt? -> Cap auf [min_guest, max_guest]
                 |
                 v
   [4] Window Safety (R5)
       Vicki meldet Fenster offen -> Setpoint = FROST_PROTECTION_C
                 |
                 v
   [5] Hard Clamp (R8)
       Setpoint = MAX(FROST_PROTECTION_C, MIN(MAX_HOTEL_C, setpoint))
       MAX_HOTEL_C = 28 (Systemkonstante)
                 |
                 v
        Ergebnis: target_setpoint_celsius + reason + rule_context
```

### 5.1 Trigger (gemaess AE-07: hybrid)

- **Event:** Belegungsaenderung (POST/PATCH `/api/v1/occupancies`), Vicki-Uplink mit Setpoint-Aenderung, Settings-Aenderung (rule_config / scenario_assignment / global_config / season), Fenster-offen-Meldung -> sofortige `evaluate_room(room_id)` Aufgabe in Celery.
- **Scheduler:** Celery-Beat alle 60 s prueft Raeume mit `next_transition_at <= now`. Zeitliche Regeln tragen ihren naechsten Schaltpunkt in dieses Feld ein.

### 5.2 Downlink-Logik (gemaess AE-09)

Nur senden wenn:
- `|new_setpoint - last_acknowledged_setpoint| >= 0.5`
- ODER: kein Downlink in den letzten 6 h (Heartbeat)
- ODER: Reason ist `frost_protection` oder `window_open` (Safety)

Priority-Queue:
1. Frostschutz/Window-open (immer, unabhaengig von Duty-Cycle-Budget)
2. Manual-Override
3. Temporal-Transitions (Vorheizen, Nachtabsenkung)
4. Routine

### 5.3 Audit (gemaess AE-08)

Jede Evaluation schreibt in `event_log` (neu, Migration 0003):

```
event_log (TimescaleDB Hypertable)
  time TIMESTAMPTZ NOT NULL
  room_id FK
  device_id FK NULL
  evaluation_id UUID (gleicher Wert fuer alle Eintraege einer Evaluation)
  layer ENUM (base, temporal, manual, window, clamp)
  setpoint_in NUMERIC(4,1)
  setpoint_out NUMERIC(4,1)
  reason ENUM (CommandReason)
  details JSONB (vollstaendiger Kontext-Snapshot)
  PRIMARY KEY (time, room_id, evaluation_id, layer)
```

Auch wenn Setpoint unveraendert: Eintrag in `event_log` (KI-Vorbereitung).

### 5.4 Was wir NICHT machen (Anti-Patterns vermeiden)

- **Keine implizite Konflikt-Aufloesung in Regeln.** Die Reihenfolge der Schichten IST die Architektur (AE-06).
- **Keine Iteration "auf Konvergenz".** Eine Evaluation ist eine Pipeline, keine Schleife.
- **Keine Datenbank-Trigger fuer Engine-Logik.** Alles in Python, testbar, debugbar.
- **Kein Caching von Settings.** TanStack-Query Frontend reicht. Backend liest bei jeder Evaluation frisch (rule_config ist klein, < 100 Rows).

---

## 6. UI/UX-Konzept (High-End Hotelier-Frontend)

### 6.1 Information-Architecture (neue Sidebar)

Die Strategie-Sidebar (8.3) ist gut, aber zu detailliert. Hotelier denkt in 6 Hauptbereichen:

```
HEUTE                       (icon: today)
  Dashboard                 (icon: dashboard)
  Live-Status               (icon: thermostat)

ZIMMER                      (icon: meeting_room)
  Liste                     (Standard-Tabelle)
  Floorplan                 (Karte mit eingefaerbten Zimmern)
  Belegungen                (Kalender-View)

REGELN                      (icon: tune)
  Globale Einstellungen     (Zeiten + Temperaturen)
  Raumtypen                 (Schlafzimmer, Studio, Tagungsraum, ...)
  Szenarien                 (Aktivierung + Konfiguration)
  Saisons                   (Zeitraeume mit Override)
  Sommermodus               (Switch + Datum)

GERAETE                     (icon: device_thermostat)
  Geraete-Liste             (vorhanden Sprint 7)
  Gateway                   (Status + Konfiguration)
  Pairing                   (Wizard fuer neue Geraete)

ANALYSE                     (icon: insights)
  Heizverlauf               (Charts pro Raum/Geraet)
  Audit-Log                 (Was hat die Engine gemacht)
  Reports                   (Energie-KPIs, Belegungs-Auslastung)

EINSTELLUNGEN               (icon: settings)
  Hotel-Stammdaten          (Name, TZ, Email-Alerts)
  Benutzer                  (kommt mit echter Auth)
  API-Keys                  (kommt mit echter Auth)
  System-Status             (Backup-Status, Migrations-Stand)
```

**Mobile:** Die Top-Level-6-Bereiche werden zur Bottom-Tab-Bar (Heute / Zimmer / Regeln / Geraete / Analyse / mehr...). Die zweite Ebene wird als Drawer von oben.

### 6.2 Hauptscreens

**6.2.1 Dashboard (Hauptseite "Heute")**

Kein Chart, KPI-First (gemaess Strategie 8.4 + Annahme A26):

```
+---------------------------------------------+
|  Guten Morgen, Hotel Sonnblick.             |
|  Heute ist Samstag, 02.05.2026.             |
+---------------------------------------------+
| KPI |  KPI  |  KPI  |  KPI  |  KPI  |  KPI  |
+---------------------------------------------+
| 38/45 | 20.4 | 127/130 | OK   | 14:00  | -3°|
| Beleg | DurT | Online  | Mode | NextIn | Au |
+---------------------------------------------+

| Quick-Actions:                              |
| [+ Belegung] [Temperatur jetzt setzen]      |
| [Sommermodus aktivieren] [Zur Liste]        |
+---------------------------------------------+

| Aktive Hinweise:                            |
| - 2 Geraete nicht erreichbar (>2h)          |
| - 3 Vorheizungen laufen (Zimmer 102, 215, 308) |
| - Sommermodus inaktiv                       |
+---------------------------------------------+
```

Quick-Actions oeffnen sich als Drawer (gemaess A27).

**6.2.2 Floorplan-View (NEU, Sprint 11)**

Vereinfachte Hotel-Karte (per Etage), Zimmer als Rechtecke eingefaerbt nach Status:

- Gruen = belegt, im Soll
- Gelb = belegt, vorheizen aktiv
- Blau = frei, abgesenkt
- Rot = Geraet offline / Anomalie
- Grau = blocked / Wartung

Klick aufs Zimmer -> Drawer mit Detail.

**6.2.3 Zimmer-Detail (Drawer)**

```
+----------------------------------+
| Zimmer 215 (Schlafzimmer)        |
| Etage 2, Sued                    |
+----------------------------------+
| Aktuell:                         |
|  Ist 21.4 Grad / Soll 21.0 Grad  |
|  Belegt seit gestern 16:30       |
|  Auszug morgen 11:00             |
+----------------------------------+
| Geraete:                         |
|  - Vicki-001 (Schlafzimmer)      |
|    Battery 95%, RSSI -75 dBm     |
|    Letzter Uplink: vor 3 Min     |
|  - Vicki-007 (Bad)               |
|    Battery 88%, RSSI -82 dBm     |
+----------------------------------+
| Engine-Entscheidung:             |
|  R1 Base belegt -> 21.0          |
|  R4 Nachtabsenkung NICHT aktiv   |
|  R5 Fenster geschlossen          |
|  Resultat: 21.0 Grad             |
+----------------------------------+
| [Temperatur jetzt setzen]        |
| [Belegung bearbeiten]            |
| [Wartungsmodus]                  |
+----------------------------------+
```

Das **Engine-Entscheidung-Panel** ist der UX-Killer-Feature: Hotelier versteht JEDE Sekunde, warum die Engine einen bestimmten Setpoint gewaehlt hat. Kein anderes System macht das so transparent.

**6.2.4 Globale Einstellungen**

Form mit gruppierten Cards (Settings-Layout):

```
Card: Standardzeiten
  Default Check-in    [14:00]
  Default Check-out   [11:00]
  Tagabsenkung von    [09:00] bis [15:00]
  Nachtabsenkung von  [00:00] bis [06:00]
  Vorheizen-Lead      [90 Min]

Card: Standardtemperaturen
  T_belegt Default       [20.0 Grad]
  T_frei Default         [17.0 Grad]
  T_nacht Default        [19.0 Grad]
  T_long_vacant Default  [15.0 Grad]
  Gast Override Min/Max  [19] [24] Grad
  Gast Override Dauer    [240 Min]

Card: Sicherheit
  Frostschutz [10.0 Grad] (Systemkonstante, nicht aenderbar)
  Hard Max    [28.0 Grad] (Systemkonstante, nicht aenderbar)
  Fenster offen Drop  [2.0 Grad in 5 Min]

Card: Alerts
  Email an [hotelsonnblick@gmail.com]
  Geraet offline nach [120 Min]
  Batterie warnen unter [20 Prozent]
```

[Speichern] zeigt Diff-Modal: "Sie aendern X von Y auf Z. Das betrifft 12 Raeume."

**6.2.5 Raumtypen-CRUD**

Liste links, Detail rechts (Master-Detail-Layout):

```
Liste:                 Detail (Schlafzimmer):
Schlafzimmer (12)      Name [Schlafzimmer]
Studio (8)             Beschreibung [...]
Tagungsraum (2)        Buchbar [JA] (Checkbox)
Bad (15)               Default T_belegt [20.0]
Flur (6)               Default T_vacant [17.0]
[+ Raumtyp]            Default T_nacht [19.0]
                       Max-Grenze [25.0]
                       Min-Grenze [15.0]
                       Vacant nach [24 h] -> long_vacant
                       
                       [Speichern]
                       [Loeschen] (nur wenn 0 Raeume)
                       
                       Verwendet in 12 Raeumen:
                       - 101, 102, 103, ..., 215
```

**6.2.6 Szenarien-Liste**

Cards-Grid mit Aktivierungs-Switch:

```
+-------------------+  +-------------------+  +-------------------+
| Tagabsenkung      |  | Nachtabsenkung    |  | Realtime Check-in |
| Aktiv [X]         |  | Aktiv [X]         |  | Aktiv [ ] (off)   |
| 09:00-15:00       |  | 00:00-06:00       |  | Trigger: PIR      |
| Offset -2 Grad    |  | Absolut 19 Grad   |  | Bedingung: keine  |
|                   |  |                   |  | Hardware vorhand. |
| Aktiv in:         |  | Aktiv in:         |  |                   |
| Alle Raumtypen    |  | Alle Raumtypen    |  | [Konfigurieren]   |
| [Konfigurieren]   |  | [Konfigurieren]   |  |                   |
+-------------------+  +-------------------+  +-------------------+
```

[+ Custom Szenario] (fuer Phase 2) ausgegraut mit Hinweis "Custom Szenarien kommen in Phase 2".

**6.2.7 Saisons**

Liste mit Zeitraum-Visualisierung (Gantt-aehnlich):

```
2026                Q1            Q2            Q3            Q4
Skisaison        |==========|                              |======|
Sommerpause                              |======|
Winter aktiv                                            |==|

[+ Saison]
```

Klick auf eine Saison -> Detail mit Override-Settings (analog zu Globalen Einstellungen, aber als Override).

**6.2.8 Sommermodus**

Eine Seite, einfacher Switch:

```
Sommermodus

[ ] Aktiv

Wenn aktiviert, schaltet die Heizung in **Standby**:
- Frostschutz (10 Grad) bleibt aktiv
- Alle anderen Regeln werden pausiert
- Vicki-Geraete senden weiter Telemetrie
- KEIN Downlink (Setpoint bleibt auf Frostschutz)

Optional Zeitraum:
  Von [01.06.2026]
  Bis [31.08.2026]
  (Wenn gesetzt: automatisch aktivieren/deaktivieren)

[Speichern]
```

**6.2.9 Audit-Log-View (NEU)**

Tabelle mit Filter (Raum, Zeitraum, Reason). Pro Eintrag aufklappbar mit JSON-Kontext. Kann Hotelier nutzen um zu verstehen "warum war es gestern Abend in 215 zu kalt".

### 6.3 Visuelle Sprache

Bestaendig auf Design-Strategie 2.0.1 (Sprint 7 hat Tokens flach gemacht):

- Primaer-Farbe Rosé `#DD3C71`
- Heizungs-Domain-Farben (gemaess Strategie 8.2): Heating-On Gruen `#16A34A`, Heating-Off Rot `#E05252`, Vorheizen Amber `#F59E0B`, Frostschutz Violett `#7C3AED`
- **NEU:** Sommermodus Blau `#0EA5E9` (entspannte Off-Saison-Stimmung)
- Roboto + Material Symbols Outlined (AE-01)
- Tailwind Custom Tokens (`bg-surface`, `text-foreground`, ...)

### 6.4 Mobile-First

Sprint 7 ist responsive. Aber nicht "Mobile-First" im engeren Sinne. Sprint 12 macht:

- Sidebar -> Bottom-Tab-Bar fuer < 768 px
- Drawer-Animation fuer Detail-Views (statt Modal)
- Big-Touch-Buttons (>= 48 px)
- Reduced-Motion respektieren
- "Gestern Abend"-Quick-Filter im Audit-Log fuer Hotelier-Mobile-Nutzung
- PWA-Manifest + Install-Prompt

### 6.5 Komponenten-Inventur (was wir konkret brauchen)

| Komponente | Status | Sprint |
|---|---|---|
| AppShell mit Sidebar + Topbar | vorhanden Sprint 7 | Refactor Sprint 11 (6-Bereiche-Nav) |
| KPI-Card | vorhanden | erweitern Sprint 11 |
| Recharts-LineChart | vorhanden Sprint 7 | wiederverwenden |
| FloorplanView | NEU | Sprint 11 |
| RoomDetailDrawer | NEU | Sprint 11 |
| OccupancyCalendar | NEU | Sprint 11 |
| RuleConfigForm (Settings-Layout) | NEU | Sprint 8 |
| ScenarioCard | NEU | Sprint 10 |
| SeasonGantt | NEU | Sprint 10 |
| AuditLogTable | NEU | Sprint 11 |
| DiffModal "alter Wert -> neuer Wert + Auswirkungen" | NEU | Sprint 8 |
| MobileBottomNav | NEU | Sprint 12 |
| EngineDecisionPanel | NEU (Killer-Feature) | Sprint 11 |

shadcn/ui-Einfuehrung als eigener Refactor-Sprint **vor** Sprint 11 (Sprint 7.2 verschoben). Begruendet damit, dass Drawer/Dialog/DataTable/Calendar viel Boilerplate sparen.

---

## 7. Sprint-Plan Sprint 8 bis Sprint 13

### Sprint 8 — Stammdaten-CRUD + Belegung

**Ziel:** Hotelier kann im UI Raumtypen, Raeume, Heizzonen, Geraet-Zuordnungen und Belegungen anlegen und bearbeiten.

**Branch:** `feat/sprint8-stammdaten-belegung`
**Schaetzung:** ca. 8-12 h Arbeitsblock
**ADRs:** AE-26 bis AE-30 (Datenmodell-Erweiterung)

Sprint-Schnitt:
- 8.1 Migration 0003 Teil 1: `season`, `scenario`, `scenario_assignment`, `global_config`, `manual_setpoint_event`, `event_log`, plus `room_type.max_temp/min_temp/long_vacant_hours`. Nur Schema, kein Code.
- 8.2 Seed-Skript erweitern (Default-Szenarien + Default global_config + 3 Default-Raumtypen)
- 8.3 Backend-API: CRUD fuer `room_type`, `room`, `heating_zone`, `device-zone-assignment`
- 8.4 Backend-API: CRUD fuer `occupancy` (mit Storno-Pattern)
- 8.5 Frontend: `/raumtypen` Seite mit Master-Detail-Layout
- 8.6 Frontend: `/zimmer` Seite mit Tabelle + Drawer-Detail
- 8.7 Frontend: `/belegungen` Seite mit Liste + Anlege-Form
- 8.8 Pflichtprueflauf E2E: Anlegen, bearbeiten, loeschen, stornieren
- 8.9 Doku + PR + Tag `v0.1.8-stammdaten`

### Sprint 9 — Regel-Engine + Downlink

**Ziel:** Engine berechnet pro Raum den Setpoint, schreibt `event_log` + `control_command`, sendet Downlink an Vicki via ChirpStack-API.

**Branch:** `feat/sprint9-regel-engine`
**Schaetzung:** ca. 12-16 h Arbeitsblock
**ADRs:** AE-31, AE-32

Sprint-Schnitt:
- 9.1 `heizung.rules.engine` mit `evaluate(ctx) -> RuleResult` (reine Funktion, alle 8 Kernregeln + R9 Tagabsenkung)
- 9.2 RuleContext-Loader (laedt rule_config-Hierarchie + occupancy + last sensor reading)
- 9.3 Pytest-Suite: 30+ Tests fuer alle Layer und Edge-Cases (Frostschutz, Konflikt R2 vs. R4, etc.)
- 9.4 Celery-Setup (Redis ist im Compose, ungenutzt — siehe N-13). Worker-Container.
- 9.5 Trigger-Logik: `evaluate_room.delay(room_id)` bei Belegungsaenderung + Settings-Aenderung
- 9.6 Scheduler: Celery-Beat alle 60 s findet Raeume mit `next_transition_at <= now`
- 9.7 ChirpStack-Downlink-Adapter (gRPC oder MQTT-Publish auf `application/.../device/.../command/down`)
- 9.8 Hysterese (0.5 Grad) + Duty-Cycle-Budget
- 9.9 Frontend: `/audit-log` Seite mit Filter
- 9.10 Doku + PR + Tag `v0.1.9-regel-engine`

### Sprint 10 — Saison + Szenarien + Sommermodus

**Ziel:** Hotelier kann Saisons anlegen, Szenarien aktivieren/deaktivieren, Sommermodus schalten. Engine respektiert beides.

**Branch:** `feat/sprint10-saison-szenarien`
**Schaetzung:** ca. 8-10 h Arbeitsblock
**ADRs:** AE-33, AE-34

Sprint-Schnitt:
- 10.1 Engine-Erweiterung: Layer 0 (Sommermodus), Saison-Resolution in Layer 1
- 10.2 Backend-API: `season` CRUD, `scenario_assignment` CRUD, `global_config` GET/PATCH (Singleton)
- 10.3 Backend-API: `manual_setpoint_event` CRUD + Engine-Beruecksichtigung in Layer 3a
- 10.4 Frontend: `/szenarien` Cards-Grid + Konfigurieren-Drawer
- 10.5 Frontend: `/saisons` Liste + Detail (Override-Settings analog zu Global)
- 10.6 Frontend: `/sommermodus` einfacher Switch + Datums-Felder
- 10.7 Frontend: "Temperatur jetzt setzen" Drawer (in Dashboard + Zimmer-Detail eingebunden)
- 10.8 E2E-Tests: Sommermodus-Szenario (alles aus, Frostschutz aktiv), Saison-Override
- 10.9 Doku + PR + Tag `v0.2.0-szenarien`

### Sprint 11 — Dashboard + Floorplan + Audit + shadcn

**Ziel:** Hotelier hat ein "Single-Pane-of-Glass"-Dashboard. Floorplan zeigt Live-Status. Audit-Log ist durchsuchbar. UI-Library shadcn/ui ist eingefuehrt (vorgezogen Sprint 7.2).

**Branch:** `feat/sprint11-dashboard-floorplan`
**Schaetzung:** ca. 12-16 h Arbeitsblock
**ADRs:** AE-35 (Sidebar-Restrukturierung)

Sprint-Schnitt:
- 11.1 shadcn/ui init + Theme-Merge mit Custom-Tokens (Sprint 7.2 nachholen)
- 11.2 Sidebar-Refactoring auf 6-Bereiche-Struktur
- 11.3 Dashboard-Redesign mit 6 KPI-Cards + Quick-Actions + Hinweise
- 11.4 FloorplanView Komponente (SVG-basiert, klickbare Zimmer)
- 11.5 RoomDetailDrawer mit EngineDecisionPanel
- 11.6 OccupancyCalendar (FullCalendar oder eigene Implementierung)
- 11.7 AuditLogTable mit Filter
- 11.8 Mobile-Layout vorbereiten (Sidebar -> Drawer fuer < 768 px)
- 11.9 Doku + PR + Tag `v0.2.1-dashboard`

### Sprint 12 — Mobile-Tuning + PWA

**Ziel:** Hotelier kann das System komplett auf dem Smartphone bedienen. PWA-Install-Prompt funktioniert.

**Branch:** `feat/sprint12-mobile-pwa`
**Schaetzung:** ca. 6-8 h

Sprint-Schnitt:
- 12.1 Bottom-Tab-Bar fuer Mobile (6 Hauptbereiche)
- 12.2 Drawer-Animation polish, Big-Touch-Targets
- 12.3 Mobile-spezifische Quick-Actions im Dashboard
- 12.4 PWA-Manifest + Service-Worker (offline read-only)
- 12.5 Lighthouse Mobile-Score >= 90
- 12.6 Playwright Mobile-Viewport-Tests
- 12.7 Doku + PR + Tag `v0.2.2-mobile`

### Sprint 13 — Pilotbetrieb-Reife (Monitoring, Alerts, Reports, Backup)

**Ziel:** System kann real einen Pilot-Wing (5-10 Zimmer) bedienen. Hotelier wird via Email gewarnt bei Problemen. Backup laeuft.

**Branch:** `feat/sprint13-pilot-readiness`
**Schaetzung:** ca. 10-12 h
**Audit-Bezug:** schliesst H-8, M-2, M-4, M-6, M-11

Sprint-Schnitt:
- 13.1 Email-Alert-Service (Vicki offline > 2 h, Battery < 20%, Engine-Failure)
- 13.2 Reports: Heizgrad-Stunden pro Raum, Belegungs-Auslastung Wochenuebersicht
- 13.3 Heatmap-View: Welche Raeume am meisten gelaufen heute/letzte Woche
- 13.4 Backup-Strategie: `pg_dump` Cron + Hetzner Storage Box Sync (RUNBOOK §11)
- 13.5 M-6 `last_seen_at` updaten im MQTT-Subscriber
- 13.6 Mosquitto Healthcheck ohne Passwort-Leak (M-14)
- 13.7 Multi-Stage Dockerfile (M-4)
- 13.8 Caddy-Header-Snippet extrahieren (M-2)
- 13.9 Doku + PR + Tag `v0.3.0-pilot-ready`

### Sprint 14+ Backlog (nicht im Master-Plan-Bogen)

- Echte Auth (NextAuth + RBAC + User-Tabelle, K-1 Replacement)
- PMS-Connector (Casablanca / Apaleo / Mews)
- PIR-Sensor-Integration (Hardware-Beschaffung erst)
- Custom-Szenarien (User definiert eigene Logik)
- KI-Shadow-Mode (Strategie A13)
- Verbrauchszaehler-Integration (M-Bus oder Modbus-RTU)
- Multi-Hotel-Mandantenfaehigkeit
- WT101-Treiber (eigener Codec, Hardware vorhanden)
- 130-Geraete-Vollausbau

---

## 8. Risiken & Trade-Offs

| Risiko | Wahrscheinlichkeit | Impact | Mitigation |
|---|---|---|---|
| Sprint 9 Engine wird komplexer als geschaetzt | hoch | mittel | Aggressive Pytest-Coverage von Tag 1, jede Layer-Funktion einzeln entwickeln + testen, dann zusammenbauen |
| Downlink via ChirpStack-API funktioniert nicht out-of-the-box | mittel | hoch | Vor Sprint 9 Start ein Spike-Day: einen manuellen Downlink mit `mosquitto_pub` testen, Setpoint im Vicki verifizieren |
| Saison + Szenario-Resolution wird verwirrend zu debuggen | mittel | mittel | EngineDecisionPanel im UI macht jede Schicht-Entscheidung sichtbar - das ist Debug-Tool und User-Feature in einem |
| Floorplan-View braucht Hotel-Grundriss als Bild/SVG | hoch | mittel | Sprint 11 startet mit "Liste-View first, Floorplan als Optional". Wenn Grundriss nicht da, machen wir Etagen-Listen mit Status-Badges - sieht auch gut aus |
| Mobile-First-Sprint 12 ohne echte Mobile-Tests | mittel | mittel | Playwright-Mobile-Viewport-Tests + Hotelier soll selbst auf Smartphone testen am Test-Server |
| K-1 Caddy-Basic-Auth bleibt zu lange Interim | hoch | gering (intern) | Sprint 14 echte Auth, vorher reicht Single-User-Hotel |
| PMS-Connector wird gefordert vor Pilot | mittel | hoch | Manuelle Belegung in Sprint 8 macht das System komplett autonom (Strategie A1). Wenn der Hotelier gefordert ist, ist das ein paar Minuten pro Tag, akzeptabel fuer Pilot |
| Frostschutz-Konstante hardcoded — was wenn jemand will dass sie 12 statt 10 Grad ist | gering | gering | Diskutieren mit Hotelier. Vorlage: 10 Grad ist EU-Standard fuer Wasserrohrschutz. Bei Bedarf in `global_config` ueberschreibbar machen |

### Trade-Off: shadcn/ui jetzt vs. Plain Tailwind

**Pro shadcn:** Drawer, Dialog, DataTable, Calendar, Form-Components - alle in 1-2 Stunden installiert. Sparen 20+ Stunden Eigen-Implementierung ueber Sprint 8-13.

**Contra:** Theme-Merge mit Custom-Tokens braucht Sorgfalt. Sprint 7.2 wurde genau deshalb verschoben.

**Empfehlung:** Sprint 11 nimmt shadcn/ui rein. **Vorher** in Sprint 8/9/10 mit Plain Tailwind weiter wie Sprint 7. Begruendung: Sprint 8/9/10 sind **Backend-lastig**, Frontend-Komponenten dort sind einfache Forms + Tabellen. Erst Sprint 11 (Dashboard + Floorplan) braucht die komplexen Komponenten.

### Trade-Off: Celery jetzt vs. Async-Background-Task

Sprint 5 hat MQTT-Subscriber als FastAPI-Lifespan-Task gemacht (AE-18). Engine koennte gleich laufen.

**Pro Celery:** Persistente Job-Queue, Retry-Logik, Scheduler (Beat) fuer 60-s-Intervall, einzeln skalierbar.

**Contra:** Mehr Container, mehr Komplexitaet, Redis muss laufen.

**Empfehlung:** Celery rein. Redis ist eh im Compose (N-13 sagt "ungenutzt"). Engine ist Mission-Critical, sollte nicht im API-Container mitlaufen. Worker-Container ist 1 Service mehr - tragbar.

### Trade-Off: Eigene Floorplan-Komponente vs. Bibliothek

**Pro eigen (SVG):** Volle Kontrolle, klein, anpassbar an Hotel-spezifische Formen.

**Contra Bibliothek (z.B. react-zoom-pan-pinch + react-konva):** Bessere Touch-Gesten, fertige Pan/Zoom-Logik.

**Empfehlung:** Eigen-Implementierung mit SVG fuer Sprint 11. Hotel Sonnblick hat 45 Zimmer auf wenigen Etagen - eine 3-Etagen-Karte mit eingefaerbten Rechtecken reicht. Wenn Mobile-Pan/Zoom Bedarf wird (Sprint 12), kann eine Bibliothek nachgezogen werden.

---

## 9. Empfehlung & naechste Schritte

### 9.1 Was JETZT bestaetigen

Konkret 4 Entscheidungen, danach Schreiben des Sprint-8-Feature-Briefs:

1. **Datenmodell-Erweiterung gemaess §4.2** - JA / NEIN / Aenderung?
2. **5-Schichten-Engine-Pipeline gemaess §5** - JA / NEIN / Aenderung?
3. **6-Bereiche-Sidebar gemaess §6.1** - JA / NEIN / Aenderung?
4. **Sprint-Bogen 8-13 in dieser Reihenfolge** - JA / NEIN / Umsortierung?

### 9.2 Was NACH Bestaetigung passiert

- Ich schreibe die ADRs AE-26 bis AE-35 in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
- Ich schreibe `docs/features/2026-05-02-sprint8-stammdaten-belegung.md` (Feature-Brief)
- Ich schreibe den Sprint-8-Sprintplan
- Wenn beide freigegeben (Gate 1 + Gate 2 nach WORKFLOW.md): Branch `feat/sprint8-stammdaten-belegung` und Umsetzung

### 9.3 Was wir NICHT vergessen duerfen (Realitaetscheck)

- **Sprint 9 Downlink:** vorher Spike-Test machen, ob ChirpStack-API einen Setpoint zum Vicki bringt. Sonst stehen wir Sprint 9 mit komplettem Engine-Code da, ohne ein Geraet zu erreichen.
- **Vicki-Setpoint-Format:** Der Codec macht Periodic-Reporting v1/v2 (Read-Only). Fuer Downlink brauchen wir Command 0x02 (Setpoint setzen). Das ist im offiziellen MClimate-Doc - aber ungetestet bei uns.
- **Sprint 11 Mobile-Vorbereitung:** Sidebar muss schon ab Sprint 8 als responsive Komponente aufgesetzt sein, sonst Mehrarbeit in Sprint 11.
- **Echtes Auth (K-1) Replacement:** Sprint 14 ist nicht "irgendwann", sondern vor Pilot-Live-Betrieb mit echten Gaesten verbindlich. Caddy-Basic-Auth ist Interim, kein Endzustand.
- **Backup (H-8):** Sprint 13 ist spaet. Empfehle parallel zu Sprint 9 (sobald `event_log` und Engine-Daten persistieren) eine Mini-Backup-Loesung als Hotfix-Sprint.

---

## 10. Quellen (recherchiert 2026-05-02)

- Betterspace Feature-Catalog: betterspace360.com/en/better-energy/control/feature/
- Betterspace Heating Control Hardware: betterspace360.com/en/better-energy/hardware/heating/
- MClimate Hotel Case Study: mclimate.eu/pages/digitizing-the-heating-system-in-a-family-hotel-in-germany
- Honeywell INNCOM: buildings.honeywell.com/us/en/brands/our-brands/hospitality
- Honeywell INNCOM Direct (2024): honeywell.com/us/en/press/2024/08/honeywell-launches-inncom-direct
- Telkonet EcoSmart: telkonet.com/ecosystems/ecosmart/
- Verdant/Copeland Smart Thermostats Hotel Industry 2026: verdant.copeland.com/blog/how-smart-thermostats-are-changing-hotel-industry
- Mews Smart Hotel Technology Guide: mews.com/en/blog/smart-hotel-technology
- Hotel Tech Report Smart Hotels: hoteltechreport.com/news/smart-hotels

---

*Ende Master-Plan. Auf User-Bestaetigung warten (4 Entscheidungen in §9.1) bevor ADR + Feature-Brief geschrieben werden.*
