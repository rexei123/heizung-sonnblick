# Hotel Sonnblick – Heizungssteuerung

## Vollständiges Strategiepapier

**Version: 1.1 · Stand: 2026-05-07 (Architektur-Refresh)**
**Domain:** heizung.hotel-sonnblick.at
**Status:** Freigegeben für Entwicklungsstart

> **Hinweis (2026-05-07):** Dieses Dokument wurde überarbeitet. Korrekturen
> in §6.2 R8 (Frostschutz) und §9.3 (Phasen-Modell). Die maßgebliche
> Quelle für aktuelle Pläne ist `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
> sowie `docs/SPRINT-PLAN.md`.

---

## 1. Über dieses Dokument

Dieses Dokument ist die verbindliche Referenz für das gesamte Heizungssteuerungsprojekt des Hotel Sonnblick Kaprun. Es fasst alle Entscheidungen, Architekturprinzipien, Regeln und den Entwicklungsplan zusammen.

**Zwei Versionen existieren:**
- **Google Drive** (Word-Dokument) – für den Hotelier als Referenz und Nachschlagewerk
- **GitHub** (diese Datei als `STRATEGIE.md`) – für die Entwicklung als technische Referenz

Bei Widersprüchen gilt die neuere Version. Änderungen werden in beiden Dokumenten synchron eingepflegt.

---

## 2. Projektziel und Vision

### Ziel
Aufbau einer **eigenständigen, cloud-basierten Heizungssteuerung**, die Betterspace im Hotel Sonnblick Kaprun vollständig ersetzt. Das System steuert LoRaWAN-Thermostate in 45 Zimmern belegungsabhängig und spart Energie, ohne Gästekomfort einzuschränken.

### Vision
Das Heizsystem ist das **erste von mehreren hauseigenen Tools**, die langfristig in einem zentralen Dashboard zusammenlaufen. Jedes Tool wird mit Claude Code im Cowork-Modell gebaut, folgt der gleichen Design Strategie 2.0, und kommuniziert über offene API-Schnittstellen.

### Kernprinzipien

1. **Autonomer Kern:** Das System funktioniert vollständig ohne externe Anbindungen. PMS ist optional.
2. **Regeln dominieren KI:** Heizregeln sind unantastbar. KI optimiert nur innerhalb der Regelgrenzen.
3. **Doppelte Herstellerunabhängigkeit:** Thermostat-Hersteller und PMS-Anbieter sind jederzeit austauschbar.
4. **API-First:** Alle Funktionen sind über eine offene REST-API erreichbar – auch für zukünftige Tools.
5. **Datensammlung von Tag 1:** Wetter, Raummetadaten und Entscheidungskontext werden für spätere KI gespeichert.
6. **Design-Konsistenz:** Jedes Tool folgt der Design Strategie 2.0 des Hotel Sonnblick.

---

## 3. Annahmen

Die folgenden 28 Annahmen bilden das Fundament aller Architektur- und Designentscheidungen.

### Architektur und Hardware

| Nr. | Annahme | Status |
|-----|---------|--------|
| A1 | System funktioniert autonom ohne PMS. Belegungsdaten werden manuell erfasst. PMS-Anbindung ist optional und jederzeit nachrüstbar. | Bestätigt |
| A2 | Stabile Internetverbindung vorhanden. LTE-SIM als Fallback im Gateway. | Bestätigt |
| A3 | Skalierbar: Mandantenfähig, Multi-Hotel-ready, 130+ Thermostate im Vollausbau, nach oben offen. | Bestätigt |
| A4 | Ein UG65-Gateway reicht für Hotel Sonnblick (2.000+ Geräte, 500 m Reichweite). | Bestätigt |
| A5 | Aktuell reine Warmwasser-Heizkörperheizung. Andere Systeme (Klimaanlage, FBH) werden architektonisch vorbereitet und sind später erweiterbar. | Bestätigt |
| A6 | Klimaanlagen-Steuerung wird architektonisch vorbereitet, aber im MVP nicht gebaut. Nachrüstung in 1–2 Jahren geplant. | Bestätigt |
| A7 | Gäste können Soll-Temperatur im Bereich 19–24 °C ändern. Grenzen sind konfigurierbar auf drei Ebenen (global, Raumtyp, Zimmer). | Bestätigt |

### Heizlogik und KI

| Nr. | Annahme | Status |
|-----|---------|--------|
| A8 | Nur Admin-Rolle im MVP. Mehrbenutzersystem kommt in Phase 2. | Bestätigt |
| A9 | Hybrid-System: Regeln garantieren Sicherheit und Komfort. KI optimiert innerhalb der Regelgrenzen. KI kann Regeln niemals überstimmen. | Bestätigt |
| A10 | Wetterdaten (Außentemperatur, Sonneneinstrahlung, Bewölkung, Wind) werden ab Tag 1 stündlich erfasst. | Bestätigt |
| A11 | Zimmer-Metadaten (Himmelsrichtung, Stockwerk, Raumgröße) sind Pflichtfelder im Datenmodell. | Bestätigt |
| A12 | Jede Regel-Entscheidung wird mit Begründung und Kontextdaten (Wetter, Belegung, Uhrzeit) protokolliert. | Bestätigt |
| A13 | Leere KI-Ebene von Tag 1 im Code. Shadow-Mode mindestens 3 Monate vor Scharfschaltung. | Bestätigt |

### Abstraktion und API

| Nr. | Annahme | Status |
|-----|---------|--------|
| A14 | Zwei Abstraktionsschichten: Geräte-Abstraktion (Thermostat-Hersteller) und Belegungs-Abstraktion (PMS-Anbieter). | Bestätigt |
| A15 | OpenAPI 3.1 Dokumentation, automatisch aus dem Code generiert. | Bestätigt |
| A16 | API-Keys mit Berechtigungs-Scopes (lesen / schreiben / admin). | Bestätigt |
| A17 | Webhooks für externe Tools und zentrales Dashboard. | Bestätigt |
| A18 | Einheitliche Datenformate: ISO 8601 UTC für Zeit, Dezimalzahl in °C für Temperaturen. | Bestätigt |

### Workflow und Infrastruktur

| Nr. | Annahme | Status |
|-----|---------|--------|
| A19 | Zwei-System-Architektur: Testsystem (test.heizung.hotel-sonnblick.at) und Main-System (heizung.hotel-sonnblick.at) auf getrennten Servern. | Bestätigt |
| A20 | Feature-Branch-Workflow in GitHub. Kein Code erreicht Main ohne automatische Tests und manuelle Freigabe. | Bestätigt |
| A21 | CI/CD via GitHub Actions, vollautomatisch. | Bestätigt |
| A22 | Dokumentation in Google Drive (für den Hotelier) und im Code (automatisch generiert). | Bestätigt |
| A23 | Monitoring mit E-Mail-Alerts auf zwei Stufen (Warnung / Kritisch). | Bestätigt |

### Design und UI

| Nr. | Annahme | Status |
|-----|---------|--------|
| A24 | Frontend exakt nach Design Strategie 2.0: Rosé #DD3C71, Roboto, Material Symbols Outlined, Tailwind + CSS-Variablen, shadcn/ui, AppShell mit 200 px Sidebar. Die Design Strategie ist eine visuelle Guideline – Verbesserungen und Änderungen werden nach Freigabe eingearbeitet. | Bestätigt |
| A25 | Backend weicht bewusst von der Design Strategie ab: Python/FastAPI statt Next.js API-Routes. Begründung: KI/ML-Vorbereitung, TimescaleDB-Kompatibilität, Claude-Code-Eignung. | Bestätigt |
| A26 | Dashboard zeigt initial KPI-Cards ohne Charts (gemäß Design Strategie 5.2). Charts gehören in Analytics/Expertenmodus. Änderungen nach Freigabe möglich. | Bestätigt |
| A27 | Drawer statt Modal für Edit-Flows. Modal nur für kurze Bestätigungen (z. B. „Wirklich löschen?", „Sommermodus aktivieren?"). | Bestätigt |
| A28 | Deutsche UI, Sie-Form, gastgeberische Tonalität. WCAG 2.2 AA. Mobile-first. Touch-Targets ≥ 44×44 px. | Bestätigt |

---

## 4. Architektur

### 4.1 Gesamtübersicht

Das System besteht aus drei Schichten:

**Cloud (Hetzner, Deutschland):**
- API-Server (Python/FastAPI)
- Datenbank (PostgreSQL + TimescaleDB)
- Regel-Engine (Hintergrundprozess)
- Frontend (Next.js + React + Tailwind)
- Wetterdaten-Service

**Edge (im Hotel, Milesight UG65):**
- LoRaWAN-Gateway (ChirpStack)
- Node-RED (PMS-Connector, lokale Logik)
- Lokaler Puffer bei Internetausfall

**Feld (in den Zimmern):**
- MClimate Vicki LoRaWAN TRV (Heizkörperthermostate)
- Milesight WT102 (Vergleichstest, 1 Stück)

### 4.2 Autonomer Kern

Das System funktioniert vollständig ohne externe Anbindungen. Die Belegungsverwaltung ist ein eigener Baustein im Kern – manuelle Eingabe über das Admin-UI ist der erste und immer verfügbare „Connector".

Wenn später ein PMS angebunden wird, übernimmt der PMS-Connector die Belegungseingabe automatisch. Die manuelle Eingabe bleibt als Fallback immer aktiv – auch bei PMS-Ausfall.

### 4.3 Abstraktionsschichten

**Geräte-Abstraktion (Thermostat-Hersteller):**
Einheitliche Schnittstelle für alle Thermostate. Die Heizlogik sagt nur: „Setze Zimmer 107/Schlafzimmer auf 20 °C." Die Abstraktionsschicht übersetzt das in das herstellerspezifische Protokoll.

Verfügbare Treiber im MVP: MClimate Vicki, Milesight WT102, Mock-Thermostat (für Tests).

Neuen Hersteller hinzufügen = nur einen neuen Treiber schreiben. Heizlogik bleibt unberührt.

**Belegungs-Abstraktion (PMS-Anbieter):**
Einheitliche Schnittstelle für Belegungsdaten. Die Heizlogik fragt nur: „Ist Zimmer 107 belegt?" Die Abstraktionsschicht beantwortet das – egal ob die Information manuell eingegeben oder von einem PMS geliefert wurde.

Verfügbare Connectoren im MVP: Manuelle Eingabe (Admin-UI).
Geplant für Phase 2: Casablanca Hotelsoftware.
Architektonisch vorbereitet für: Protel, ASA Hotel, beliebige weitere PMS.

Neues PMS anbinden = nur einen neuen Connector schreiben. Kern bleibt unberührt.

### 4.4 API-First-Architektur

Alle Funktionen des Systems sind über eine REST-API erreichbar. Das eigene Admin-UI ist nur einer von vielen möglichen Clients. Jedes zukünftige Tool (Housekeeping, Reporting, zentrales Dashboard) kann die gleiche API nutzen.

**API-Spezifikation:** OpenAPI 3.1, automatisch aus dem Code generiert.
**Authentifizierung:** API-Keys mit Scopes (lesen / schreiben / admin).
**Webhooks:** Events werden aktiv an registrierte Endpunkte gesendet.
**Dokumentation:** Automatisch erreichbar unter /docs (Swagger-UI) und /redoc.

### 4.5 Kommunikationswege

Thermostat → Cloud:
Thermostat → LoRaWAN 868 MHz → UG65 Gateway → MQTT → Cloud-Backend → Datenbank

Cloud → Thermostat:
Regel-Engine → Geräte-Abstraktion → LoRaWAN-Downlink → UG65 → Thermostat

PMS → Cloud (wenn angebunden):
PMS lokal → Node-RED auf UG65 → HTTPS → Cloud-Backend

Wetter → Cloud:
open-meteo.com → Stündlicher Abruf → Datenbank

### 4.6 Ausfallverhalten

| Ausfallszenario | Systemverhalten |
|-----------------|-----------------|
| Internet im Hotel fällt aus | Gateway arbeitet autonom mit letzten Regeln weiter. Thermostate halten letzte Soll-Temperatur. |
| Cloud-Server fällt aus | Gateway puffert Daten. Bei Wiederherstellung automatische Resynchronisation. |
| PMS nicht erreichbar | Kein Problem – System arbeitet mit lokaler Belegungskopie oder manueller Eingabe. |
| Thermostat offline | Alarm nach 2 h. System arbeitet für restliche Geräte normal weiter. |
| Gateway defekt | Thermostate halten letzte Soll-Temperatur. Ersatzgerät im Schrank. |

---

## 5. Hardware

### 5.1 Warum LoRaWAN

LoRaWAN (Long Range Wide Area Network) ist ein Spezial-Funkstandard für IoT-Geräte. Im Vergleich zu WiFi bietet LoRaWAN: Reichweite bis 500 m durch Gebäude, Batterielebensdauer bis 10 Jahre, Ende-zu-Ende-Verschlüsselung, keine Belastung des Hotel-WLANs, und nur ein einziges Gateway für das gesamte Hotel.

Betterspace setzt seit kurzem ebenfalls auf LoRaWAN. Es ist der Industriestandard in der Hotelbranche für Thermostatsteuerung.

### 5.2 Komponenten

**Thermostate – MClimate Vicki LoRaWAN (Hauptgerät):**
- LoRaWAN Class A, EU868
- M30×1,5 Ventilanschluss (99 % Kompatibilität)
- Batterielebensdauer bis 10 Jahre (2× AA Lithium)
- Integrierter Temperatur- und Feuchtigkeitssensor
- Open-Window-Detection (softwarebasiert)
- Manuelle Bedienung am Drehring (Gast-Override)
- Child-Lock und Anti-Tampering verfügbar
- Rugged Backplate für öffentliche Bereiche / Bäder

**Thermostat – Milesight WT102 (Vergleichstest, 1 Stück):**
- LoRaWAN Class B (schnellere Reaktion)
- Thermal Energy Harvesting (batterielos, lädt sich durch Heizkörperwärme)
- Metallgehäuse, robust
- Dient im MVP nur zum Vergleich mit Vicki

**Gateway – Milesight UG65:**
- 8-Kanal LoRaWAN-Gateway, SX1302 Chip
- Bis zu 2.000 Endgeräte
- Integrierter ChirpStack LoRaWAN-Netzwerkserver
- Integriertes Node-RED für lokale Logik und PMS-Connector
- Ethernet + WiFi + optional LTE
- IP65 Gehäuse
- Betriebstemperatur -40 °C bis +70 °C

### 5.3 Bestellliste MVP

| Pos. | Artikel | Menge | Stückpreis ca. | Summe |
|------|---------|-------|---------------|-------|
| 1 | Milesight UG65 LoRaWAN Gateway (EU868) | 1 | 450 € | 450 € |
| 2 | MClimate Vicki LoRaWAN TRV (EU868, inkl. Batterien) | 4 | 109 € | 436 € |
| 3 | Milesight WT102 (Thermal Harvesting, Class B) | 1 | 200 € | 200 € |
| 4 | MClimate Rugged Backplate | 2 | 25 € | 50 € |
| | **Gesamt MVP-Hardware** | | | **ca. 1.136 €** |

**Optional:** Ventil-Adapter (Danfoss RA/RAV/RAVL) je 5–10 €, externe LoRa-Antenne GA01 ca. 30 €, LTE-SIM ca. 5 €/Monat.

**Empfohlene Händler:** m2mgermany.de, shopiot.eu, iot-shop.de, mclimate.eu (Mengenrabatt ab 20 Stück).

**Wichtig vor Bestellung:** Ventiltyp am Heizkörper prüfen (Standard M30×1,5 oder Danfoss).

### 5.4 Vollausbau-Schätzung

45 Zimmer × ca. 2,5 Thermostate = 113 Thermostate + 10 % Reserve = ca. 125 Vicki.
125 × 109 € = ca. 13.625 € + 1 Gateway (bereits vorhanden) = ca. 14.000 € Vollausbau.

---

## 6. Heizlogik

### 6.1 Regelarchitektur: Hybrid-System

Das System arbeitet auf zwei Ebenen:

**Ebene 1 – Safety & Comfort Layer (Regeln, starr):**
Prüft: Wird ein Grenzwert verletzt? Ist Frostschutz aktiv? Überschreitet der Wert die Gäste-Grenzen? Wenn ja, wird der Wert korrigiert. Diese Ebene kann von keiner anderen Komponente überstimmt werden.

**Ebene 2 – Optimization Layer (KI, später):**
Darf innerhalb der Safety-Grenzen Vorschläge machen und umsetzen. Im MVP ist diese Ebene leer. Ab Phase 2 läuft hier das KI-Modell zunächst im Shadow-Mode (beobachtet und schlägt vor, steuert aber nicht). Nach mindestens 3 Monaten Shadow-Mode und nachgewiesener Verbesserung wird die KI schrittweise scharfgeschaltet.

### 6.2 Die 8 Kernregeln für das MVP

**Regel 1 – Belegungsabhängige Standard-Temperatur:**
Pro Raumtyp existieren zwei Soll-Werte: T_belegt und T_frei. Bei Check-in → T_belegt, bei Check-out → T_frei. Standard-Werte: Schlafzimmer belegt 20 °C / frei 17 °C, Bad belegt 22 °C / frei 17 °C.

**Regel 2 – Vorheizen bei Check-in (Pre-Arrival Heating):**
90 Minuten vor geplanter Anreise startet die Aufheizung auf T_belegt. Die Anreisezeit kommt aus der Reservierung oder der globalen Standard-Check-in-Zeit (z. B. 14:00 Uhr).

**Regel 3 – Check-out-Absenkung:**
30 Minuten nach bestätigtem Check-out wird auf T_frei abgesenkt. Verzögerung, damit das Zimmer nicht während des Abreiseprozesses auskühlt.

**Regel 4 – Nachtabsenkung (belegtes Zimmer):**
Zwischen 00:00 und 06:00 Uhr wird auf T_Nacht reduziert (Standard: 19 °C). Morgens rechtzeitig wieder auf T_belegt.

**Regel 5 – Fenster-offen-Erkennung (softwarebasiert):**
Temperatursturz > 2 °C innerhalb von 5 Minuten bei aktiver Heizung → Ventil schließen (Frostschutz 4,5 °C). Automatische Rückkehr nach Temperaturanstieg oder 30 Minuten. Schwellenwerte konfigurierbar pro Raumtyp.

**Regel 6 – Manueller Gast-Override:**
Gast ändert Soll-Temperatur am Thermostat. Wert wird gecapped auf konfigurierbare Grenzen (Standard: 19–24 °C). Dauer: bis zum nächsten Profil-Schaltpunkt oder maximal 4 Stunden. Danach Reset auf Algorithmus-Wert.

**Regel 7 – Unbelegt-Langzeitabsenkung:**
Zimmer > 24 h als „frei" markiert → Absenkung auf T_frei_langzeit (Standard: 15 °C). Spart Energie bei längeren Leerständen.

**R8 — Frostschutz (zweistufig, ab 2026-05-07, AE-42)**

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

### 6.3 Konfigurierbarkeit: Drei-Ebenen-System

Alle Temperaturwerte (außer Frostschutz) sind konfigurierbar auf drei Ebenen:

**Ebene 1 – Global (für das ganze Hotel):**
z. B. „Gäste dürfen zwischen 19 und 24 °C einstellen."

**Ebene 2 – Pro Raumtyp (überschreibt global):**
z. B. „Badezimmer dürfen bis 26 °C."

**Ebene 3 – Pro einzelnem Zimmer (überschreibt Raumtyp):**
z. B. „Zimmer 107 hat einen sensiblen Stammgast – Maximum 25 °C."

Änderungen werden sofort wirksam und im Änderungsverlauf protokolliert.

### 6.4 KI-Vorbereitung

**Datenerfassung von Tag 1:** Wetterdaten (Außentemperatur, Sonneneinstrahlung, Bewölkung, Wind), Zimmer-Metadaten (Ausrichtung, Stockwerk, Raumgröße), vollständige Event-Logs mit Kontext.

**KI-fähige Event-Struktur:** Jede Entscheidung wird mit Grund, Kontext und Ergebnis gespeichert. Die KI kann daraus lernen, wann bessere Entscheidungen möglich gewesen wären.

**Shadow-Mode:** KI beobachtet mindestens 3 Monate, schlägt vor, steuert nicht. Ihre Vorschläge werden mit den tatsächlichen Ergebnissen verglichen. Erst nach nachgewiesener Verbesserung wird scharfgeschaltet – schrittweise, Raum für Raum.

**Beispiel-Anwendungsfälle für spätere KI:**
- Süd-Zimmer im März bei Sonnenschein: Heizung 2 h früher abschalten
- Vorheizzeit dynamisch an Außentemperatur anpassen
- Anomalie-Erkennung: defekte Ventile, dauerhaft gekippte Fenster
- Stammgast-Personalisierung
- Wartungsprognose (Batterie, Ventilleistung)

---

## 7. Datenmodell

### 7.1 Kernentitäten

**hotels:** Mandantentabelle. Hotel Sonnblick = Mandant Nr. 1. Vorbereitet für Multi-Hotel.

**units (Zimmer/Einheiten):** Zimmernummer, Hotel-ID, PMS-Mapping-ID, Ausrichtung (N/S/O/W), Stockwerk, Raumkategorie. Jede Einheit gehört zu genau einem Hotel.

**rooms (Räume):** Jedes Zimmer hat 1–n Räume (Schlafzimmer, Bad, Kinderzimmer, Flur). Jeder Raum hat einen Raumtyp und Verweise auf zugehörige Thermostate.

**room_types:** Badezimmer, Schlafzimmer, Kinderzimmer, Flur. Pro Typ: Standard-Temperaturen (belegt, frei, Nacht, Langzeit-frei), Override-Grenzen (min/max).

**devices (Thermostate):** DevEUI, Hersteller, Modell, Treiber-Typ, zugeordneter Raum, letzter Status, Batteriestand, Signalqualität (RSSI/SNR), letzter Online-Zeitpunkt.

**reservations:** Zimmer-ID, Gastname (verschlüsselt), Anreisedatum/-zeit, Abreisedatum/-zeit, Status (reserviert/eingecheckt/ausgecheckt), Quelle (manuell/PMS), letzte Synchronisation.

**occupancy_state:** Aktueller Belegungsstatus pro Zimmer. Abgeleitet aus Reservierungen plus manuellen Overrides. Status: belegt, frei, reserviert, Reinigung, gesperrt.

### 7.2 Zeitreihen und Events

**temperature_readings (TimescaleDB Hypertable):** Zeitstempel, Geräte-ID, Ist-Temperatur, Soll-Temperatur, Ventilposition (%), Luftfeuchtigkeit, Batteriestand, RSSI.

**weather_data (TimescaleDB Hypertable):** Zeitstempel, Außentemperatur, Sonneneinstrahlung (W/m²), Bewölkung (%), Windgeschwindigkeit, Windrichtung.

**temperature_commands:** Zeitstempel, Geräte-ID, Befehl (Soll-Temperatur, Ventilposition), Ergebnis (gesendet/bestätigt/fehlgeschlagen), Quelle (Regel/Override/API/KI).

**event_log (Algorithmenverlauf):** Zeitstempel, Zimmer, Raum, Regel-Name, Aktion, Begründung, Kontextdaten (Wetter, Belegung, vorherige Temperatur). Zentrale Audit-Spur.

### 7.3 Konfiguration

**settings:** Hierarchische Einstellungen (global → Raumtyp → Zimmer). Check-in-Zeit, Check-out-Zeit, Nachtabsenkungsfenster, alle Temperatur-Schwellenwerte.

**settings_history:** Änderungsprotokoll. Wer hat wann was geändert.

**api_keys:** Schlüssel für externe Tools, mit Scope (read/write/admin) und Ablaufdatum.

**webhook_subscriptions:** Registrierte Endpunkte für Push-Events.

---

## 8. UI und Design

### 8.1 Design Strategie 2.0 – Integration

Das Frontend folgt der verbindlichen Design Strategie 2.0 des Hotel Sonnblick. Die vollständige Strategie liegt als separates Dokument vor und wird hier nicht wiederholt, sondern referenziert.

**Kernelemente für die Heizungssoftware:**
- Primärfarbe: Rosé #DD3C71
- Schrift: Roboto (Pflicht für alle Admin-Bereiche)
- Icons: Material Symbols Outlined (einziges Icon-Set, kein Lucide)
- Layout: AppShell mit 200 px Sidebar links, kollabierbar auf 56 px
- Komponenten: shadcn/ui als Basis, angepasst an Design-System-Tokens
- Sprache: Deutsch, Sie-Form, gastgeberische Tonalität
- Accessibility: WCAG 2.2 AA, Kontrast geprüft, Fokus-Styles, Touch-Targets ≥ 44×44 px

Die Design Strategie ist eine visuelle Guideline. Verbesserungen und Änderungen dürfen nach dem etablierten Freigabeprozess (Phase 5 im Workflow) eingearbeitet werden.

### 8.2 Heizungs-spezifische Domain-Farben

Ergänzung zur Design Strategie 2.0 für den Heizungsbereich:

| Bedeutung | Token | Farbe | Einsatz |
|-----------|-------|-------|---------|
| Heizung läuft | --color-domain-heating-on | #16A34A (Grün) | Statusanzeige „Heizung aktiv" |
| Heizung aus | --color-domain-heating-off | #E05252 (Rot) | Statusanzeige „Heizung inaktiv" |
| Vorheizen | --color-domain-preheat | #F59E0B (Amber) | Vorheiz-Phase vor Check-in |
| Frostschutz | --color-domain-frost | #7C3AED (Violett) | Frostschutz-Modus aktiv |

### 8.3 Seitenstruktur und Komponentenmapping

**Sidebar-Navigation:**

```
ÜBERSICHT
  Dashboard              (dashboard)
  Zimmerübersicht         (meeting_room)

STEUERUNG
  Temperaturen & Zeiten   (thermostat)
  Raumtypen              (category)
  Profile                (schedule)
  Szenarien              (tune)

GERÄTE
  Thermostate            (device_thermostat)
  Gateway                (router)

ANALYSE
  Temperaturverlauf      (show_chart)
  Algorithmenverlauf     (history)

EINSTELLUNGEN
  Allgemein              (settings)
  Saison                 (calendar_month)
  Benutzer               (person)
  API & Webhooks         (api)
```

**Layout-Zuordnung pro Seite:**

| Seite | Layout-Pattern | Begründung |
|-------|---------------|------------|
| Dashboard | Dashboard-Layout | KPI-Cards, Begrüßung, Quick-Actions |
| Zimmerübersicht | Master-Detail | Liste links, Zimmerdetail rechts |
| Temperaturen & Zeiten | Settings-Layout | Gruppen-Cards mit Einstellungen |
| Raumtypen | Settings-Layout | Konfiguration pro Typ |
| Profile | Settings-Layout + Tabs | Wochentag-Tabs, Zeitplan-Tabelle |
| Szenarien | Card-Grid | Szenario-Karten mit Konfiguration |
| Thermostate | Master-Detail | Geräteliste, Detail-Drawer |
| Gateway | Settings-Layout | Status und Konfiguration |
| Temperaturverlauf | Eigene Analytics-Seite | Charts erlaubt (nicht Dashboard) |
| Algorithmenverlauf | Master-Detail | Event-Log-Tabelle |
| Allgemein | Settings-Layout | Sub-Navigation, Forms |
| Saison | Card-Grid | Sommer/Winter Karten |
| Benutzer | Settings-Layout | Benutzer-Verwaltung |
| API & Webhooks | Settings-Layout | Key-Verwaltung, Webhook-Liste |

**Sidebar-Migration (Sprint 9.13):** Heute existieren 7 flache Einträge
in `frontend/src/components/sidebar.tsx`. Strategie-Konform sind 14
Einträge in 5 Gruppen (Übersicht / Steuerung / Geräte / Analyse /
Einstellungen). Migration in Sprint 9.13 zusammen mit Geräte-Pairing-UI.

Detaillierte Route-Liste in `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` §6.

### 8.4 Dashboard – Persönliche Begrüßung und KPI-Cards

Das Dashboard zeigt maximal 6 KPI-Cards (keine Charts, gemäß Design Strategie 5.2):

1. **Belegte Zimmer:** z. B. „38 von 45" mit Trend-Delta
2. **Ø Raumtemperatur:** z. B. „20,4 °C" aller belegten Zimmer
3. **Geräte online:** z. B. „127 von 130" mit Warnfarbe falls Offline
4. **Energiestatus:** z. B. „Normal" oder „Sommermodus"
5. **Nächster Check-in:** z. B. „14:00 Uhr · 3 Zimmer"
6. **Außentemperatur:** z. B. „-3 °C · bewölkt"

Begrüßung: „Guten Morgen, Benny! Hier ist die Übersicht für Ihre Heizung."

---

## 9. Entwicklungs-Workflow

### 9.1 Zwei-System-Architektur

| | Testsystem | Main-System |
|---|---|---|
| URL | test.heizung.hotel-sonnblick.at | heizung.hotel-sonnblick.at |
| Server | Hetzner CX22 (~6 €/Monat) | Hetzner CX32 (~11 €/Monat) |
| Datenbank | Eigene, mit Testdaten | Eigene, mit echten Daten |
| Thermostate | Simuliert oder Testgeräte | Echte Geräte |
| Fehler erlaubt | Ja – dafür ist es da | Nein – muss fehlerfrei laufen |

Beide Server laufen im selben Hetzner-Projekt (eine Rechnung).

### 9.2 Feature-Branch-Workflow

Jedes Feature wird auf einem eigenen Branch entwickelt. Der main-Branch enthält nur getesteten, freigegebenen Code. Kein Feature erreicht Produktion, das nicht vorher getestet und vom Hotelier freigegeben wurde.

### 9.3 5-Phasen-Workflow (verbindlich, siehe `docs/WORKFLOW.md`)

Pro Feature/Sprint werden fünf Phasen durchlaufen:

1. Brief & Plan (Strategie-Chat)
2. Implementierung (Claude Code)
3. Tests & lokale Validierung (Claude Code)
4. PR & Review (Claude Code formuliert, User gibt frei)
5. Merge & Tag (Claude Code nach Freigabe)

Eine frühere Fassung dieses Dokuments nannte 7 Phasen. Die maßgebliche
Quelle ist `docs/WORKFLOW.md` mit 5 Phasen.

### 9.4 Speicherstrategie

| Inhalt | Speicherort | Begründung |
|--------|------------|------------|
| Code (Backend, Frontend, Tests) | GitHub | Versionierung, CI/CD, Deployment |
| Konzepte, Planungsdokumente, Entscheidungslog | Google Drive | Für Nicht-Programmierer zugänglich |
| Feature-Abnahmen, Screenshots | Google Drive | Nachweisbar ohne GitHub |
| API-Dokumentation | Automatisch generiert (online) | Immer aktuell |
| Betriebshandbuch | Google Drive + Repository | An beiden Stellen auffindbar |
| Passwörter, API-Keys, Secrets | Hetzner Vault (verschlüsselt) | Niemals in Drive oder GitHub |

### 9.5 Google-Drive-Ordnerstruktur

```
Hotel Sonnblick Heizung/
├── 01_Konzept/
│   ├── Strategiepapier_v1.0.docx    ← dieses Dokument
│   └── Design-Strategie-2.0.docx
├── 02_Features/
│   ├── F001_Infrastruktur/
│   ├── F002_Belegungsverwaltung/
│   ├── F003_Nachtabsenkung/
│   └── ...
├── 03_API_Dokumentation/
├── 04_Betriebshandbuch/
└── 05_Entscheidungslog/
```

---

## 10. Roadmap – 12 Sprints in 6 Monaten

### Phase 1 – Fundament (Monat 1)

**Sprint 1 (Woche 1–2): Infrastruktur aufbauen**
- Hetzner-Server (Test + Main) aufsetzen
- Docker, GitHub-Repo, CI/CD-Pipeline
- SSL-Zertifikate, Domain-Setup
- Design-System als Code implementieren (Tokens, Basis-Komponenten)
- Datenbank-Grundstruktur mit Mandantenfähigkeit
- Ergebnis: Leere App läuft unter test.heizung.hotel-sonnblick.at

**Sprint 2 (Woche 3–4): Backend-Kern + Wetterdaten**
- API-Grundgerüst (FastAPI + OpenAPI 3.1)
- Datenmodell komplett implementieren
- Wetterdaten-Abruf starten (open-meteo.com, stündlich)
- Admin-Login
- Zimmer/Räume/Raumtypen-Verwaltung im UI
- Ergebnis: API läuft, Zimmerstruktur konfigurierbar, Wetterdaten fließen

### Phase 2 – Hardware und Geräte (Monat 2)

**Sprint 3 (Woche 5–6): Geräte-Abstraktion + Treiber**
- Universelle Thermostat-Schnittstelle (Interface-Definition)
- MClimate-Vicki-Treiber
- Milesight-WT102-Treiber
- Mock-Thermostat für Tests ohne Hardware
- Ergebnis: Software kann Thermostate lesen und steuern (simuliert)

**Sprint 4 (Woche 7–8): Gateway-Installation + erstes echtes Signal**
- UG65 im Hotel montieren
- ChirpStack konfigurieren
- Node-RED Grundflows
- Erste echte Vicki anmelden
- Ist-Temperatur lesen, Soll-Temperatur senden
- Geräte-Health-Monitoring
- Ergebnis: Erster echter Thermostat meldet live an die Cloud

### Phase 3 – Autonomer Betrieb (Monat 3)

**Sprint 5 (Woche 9–10): Manuelle Belegungsverwaltung + PMS-Abstraktion**
- Belegungs-UI: Zimmer belegen/freigeben per Klick
- Check-in/Check-out mit Datum und Uhrzeit
- Reservierungen manuell eintragen
- Zimmerstatus-Übersicht
- PMS-Abstraktionsschicht: einheitliche Schnittstelle, manuell als erster Connector
- Ergebnis: System funktioniert komplett autonom – kein PMS nötig

**Sprint 6 (Woche 11–12): Statusverarbeitung + Event-System**
- Event-Log (Algorithmenverlauf)
- Status-Historie pro Zimmer
- Zimmerwechsel-Logik
- Webhook-Grundgerüst
- Belegungsänderungen lösen Heizaktionen aus
- Ergebnis: Statuswechsel löst sofort Heizreaktion aus

### Phase 4 – Intelligenz (Monat 4)

**Sprint 7 (Woche 13–14): Regel-Engine Regeln 1–4**
- Belegungsabhängige Temperatur
- Vorheizen bei Check-in (90 Min)
- Check-out-Absenkung
- Nachtabsenkung
- Konfigurierbar auf drei Ebenen (global/Raumtyp/Zimmer)
- Leere KI-Ebene vorbereitet
- Ergebnis: System heizt automatisch nach Belegung und Tageszeit

**Sprint 8 (Woche 15–16): Regel-Engine Regeln 5–8 + Admin-UI komplett**
- Fenster-offen-Erkennung
- Gast-Override mit Grenzen
- Unbelegt-Langzeitabsenkung
- Frostschutz (absolut)
- Admin-UI: Zimmerübersicht, Gerätestatus, Einstellungen, Raumtypen, Temperatur-Setzen
- Ergebnis: Alle 8 MVP-Regeln aktiv. Admin-UI vollständig.

### Phase 5 – Pilot (Monat 5)

**Sprint 9 (Woche 17–18): Monitoring + Alarmierung + Temperaturverlauf**
- Health-Dashboard
- E-Mail-Alerts (zwei Stufen)
- Temperaturverlauf-Charts (Expertenmodus/Analytics)
- Event-Log-UI
- Geräte-Gesundheit, Batterie-Warnungen
- Sommermodus
- Ergebnis: System ist überwachbar und warnt bei Problemen

**Sprint 10 (Woche 19–20): 5-Zimmer-Pilot mit echten Gästen**
- 5 Zimmer komplett mit Vicki ausstatten
- Manuelle Belegung parallel zu Betterspace
- Tägliche Datenkontrolle
- Feinschliff Fenstererkennung anhand echter Daten
- Gast-Override testen
- Ergebnis: 5 Zimmer laufen produktiv – manuell gesteuert, ohne PMS

### Phase 6 – Skalierung und PMS (Monat 6)

**Sprint 11 (Woche 21–22): Offene API + Casablanca-Connector**
- OpenAPI 3.1 Dokumentation vollständig
- API-Key-Verwaltung mit Scopes
- Webhook-System für externe Tools
- Casablanca-Connector als erster PMS-Treiber (falls API-Doku vorhanden)
- Manuelle Eingabe bleibt als Fallback
- Ergebnis: Andere Tools und Casablanca können andocken

**Sprint 12 (Woche 23–24): Rollout + Betriebshandbuch**
- Weitere 10–15 Zimmer ausstatten
- Saison-Konfiguration (Sommer/Winter)
- Betriebshandbuch erstellen (Google Drive)
- Schulung für Hotelier und Hauspersonal
- Go-Live-Checkliste
- Performance-Optimierung
- Ergebnis: 10–20 Zimmer produktiv, System dokumentiert und übergabefähig

---

## 11. Risiken und Gegenmaßnahmen

| Nr. | Risiko | Wahrscheinlichkeit | Auswirkung | Gegenmaßnahme |
|-----|--------|-------------------|------------|----------------|
| R1 | Casablanca-API-Doku verzögert sich | Hoch | Gering (eliminiert durch autonomen Kern) | System funktioniert ohne PMS. Connector wird nachgerüstet. |
| R2 | 6-Monats-Timeline zu eng für Vollausbau | Mittel | Mittel | MVP = 5 Pilotzimmer. Vollausbau in Phase 2. |
| R3 | Fenster-Erkennung liefert Fehlalarme | Mittel | Gering | Schwellenwerte konfigurierbar. Echte Sensoren in Phase 2. |
| R4 | LoRaWAN-Funkschatten im Gebäude | Mittel | Mittel | Funkmessung vor Rollout. Zweites Gateway bei Bedarf. |
| R5 | Einziges Gateway fällt aus | Niedrig | Hoch | Ersatzgerät im Schrank. Konfiguration versioniert. |
| R6 | Scope Creep (Feature-Inflation) | Hoch | Hoch | Strenger Phasenplan. Freigabeprozess. |
| R7 | DSGVO-Bedenken (Gastdaten) | Niedrig | Mittel | EU-Hosting, Verschlüsselung, Löschfristen. |
| R8 | PMS-Wechsel in Zukunft | Mittel | Gering (eliminiert durch PMS-Abstraktion) | Nur neuer Connector nötig. |

---

## 12. Infrastruktur und laufende Kosten

### 12.1 Server

| Server | Hetzner-Modell | Spezifikation | Kosten/Monat |
|--------|---------------|---------------|-------------|
| Main-System | CX32 | 2 vCPU, 8 GB RAM, 80 GB SSD | 11 € |
| Test-System | CX22 | 2 vCPU, 4 GB RAM, 40 GB SSD | 6 € |
| | | **Gesamt Server** | **17 €/Monat** |

Beide Server im selben Hetzner-Projekt = eine Rechnung für die Buchhaltung.

### 12.2 Laufende Kosten gesamt

| Position | Kosten/Monat |
|----------|-------------|
| Hetzner Server (2×) | 17 € |
| Domain SSL (Let's Encrypt) | 0 € |
| Wetterdaten (open-meteo.com) | 0 € |
| GitHub (privates Repo, Free Tier) | 0 € |
| LTE-SIM Gateway (optional) | 5 € |
| **Gesamt laufend** | **ca. 17–22 €/Monat** |

### 12.3 Einmalige Kosten

| Position | Kosten |
|----------|--------|
| MVP-Hardware (Gateway + Thermostate) | ca. 1.250 € |
| Vollausbau-Hardware (125 Thermostate) | ca. 14.000 € |

---

## 13. Technischer Stack

### 13.1 Backend

| Bereich | Technologie | Begründung |
|---------|------------|------------|
| Sprache | Python 3.12+ | KI/ML-Ökosystem, Claude-Code-Eignung |
| Framework | FastAPI | Asynchron, automatische OpenAPI-Doku |
| Datenbank | PostgreSQL 16 + TimescaleDB | Relational + Zeitreihen in einer DB |
| ORM | SQLAlchemy 2.0 | Python-Standard, TimescaleDB-kompatibel |
| Task-Queue | Celery + Redis | Hintergrund-Jobs (Regel-Engine, Wetter) |
| Containerisierung | Docker + Docker Compose | Reproduzierbare Umgebung |

### 13.2 Frontend

| Bereich | Technologie | Begründung |
|---------|------------|------------|
| Framework | Next.js (App Router) | Design Strategie 2.0 Vorgabe |
| Sprache | TypeScript | Typensicherheit |
| Styling | Tailwind CSS + CSS-Variablen | Design-System-Tokens |
| Schrift | Roboto via next/font/google | Design Strategie 2.0 Pflicht |
| Komponenten | shadcn/ui | Anpassbar, eigener Code |
| Icons | Material Symbols Outlined | Design Strategie 2.0 Pflicht |
| Forms | React Hook Form + Zod | Validierung |
| State | Zustand / TanStack Query | Einfach lokal, stark für Server-State |

### 13.3 Edge (im Hotel)

| Bereich | Technologie | Begründung |
|---------|------------|------------|
| Gateway | Milesight UG65 | LoRaWAN + ChirpStack + Node-RED |
| LoRaWAN-Server | ChirpStack (integriert) | Geräte-Verwaltung, Payload-Decodierung |
| Lokale Logik | Node-RED | PMS-Polling, lokaler Puffer, Edge-Regeln |
| Protokoll | MQTT (Gateway → Cloud) | Leichtgewichtig, zuverlässig |

### 13.4 IoT-Protokoll

| Bereich | Technologie |
|---------|------------|
| Funk | LoRaWAN EU868, Class A (Vicki), Class B (WT102) |
| Frequenz | 868 MHz (lizenzfrei in EU) |
| Verschlüsselung | AES-128 Ende-zu-Ende |
| Aktivierung | OTAA (Over-The-Air Activation) |
| Duty Cycle | 1 % (EU-Regulierung) – softwareseitig beachtet |

---

## 14. Nächste Schritte

### Sofort (vor Cowork-Start)

1. **Ventiltyp prüfen:** Heizkörperthermostat abschrauben, Foto vom Gewinde machen.
2. **Hardware bestellen:** Bestellliste aus Kapitel 5.3 bei m2mgermany.de oder iot-shop.de.
3. **Casablanca kontaktieren:** API-Dokumentation für Ihr System anfordern. Kein Zeitdruck – System funktioniert ohne.
4. **DNS vorbereiten:** Subdomain-A-Record für heizung.hotel-sonnblick.at anlegen lassen.

### Cowork-Start (Sprint 1)

5. GitHub-Repository anlegen, Ordnerstruktur, dieses Strategiepapier als README.md.
6. Hetzner CX32 + CX22 im bestehenden Projekt aufsetzen.
7. Docker, CI/CD-Pipeline, SSL-Zertifikate.
8. Design-System aus Design Strategie 2.0 als Code implementieren.

---

## Änderungsprotokoll

| Version | Datum | Änderung |
|---------|-------|----------|
| 1.0 | April 2026 | Initiale Version, basierend auf Konzeptarbeit in Claude-Projekt |

---

*Ende des Dokuments*
