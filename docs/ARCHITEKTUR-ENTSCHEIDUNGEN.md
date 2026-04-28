# Hotel Sonnblick – Heizungssteuerung

## Architektur-Entscheidungen

**Version 1.1 · April 2026**
**Status:** Freigegeben
**Bezug:** Addendum zu STRATEGIE.md v1.0 (Strategiepapier Heizung)

---

## Zweck dieses Dokuments

Dieses Addendum ergänzt das Strategiepapier um die Architektur-Entscheidungen, die beim Review vor Entwicklungsstart getroffen wurden. Es schließt Lücken, die im Strategiepapier offen geblieben sind, und dokumentiert die Auflösung zweier Widersprüche. Jede Entscheidung folgt dem Muster: Kontext – Entscheidung – Begründung.

Bei Widersprüchen zwischen STRATEGIE.md v1.0 und diesem Dokument gilt dieses Dokument.

---

## AE-01 · Icons ausschließlich Material Symbols

**Kontext.** Die Design Strategie 2.0 enthält einen internen Widerspruch: Kapitel 7 und 15 schreiben Material Symbols als einziges Icon-Set fest, Kapitel 10.3 listet aber `lucide-react` als verbindliche NPM-Basis-Dependency.

**Entscheidung.** Es gilt ausschließlich Material Symbols Outlined, eingebunden über den Google-Fonts-CDN-Link. `lucide-react` wird aus Kapitel 10.3 der Design Strategie gestrichen. Ein Patch-Update der Design Strategie auf Version 2.0.1 erfolgt in Sprint 1.

**Begründung.** Zwei Icon-Sets erhöhen Wartungs- und Konsistenzaufwand ohne Nutzen. Material Symbols decken den Bedarf vollständig.

---

## AE-02 · Belegung als Schreibquelle, nicht als Connector

**Kontext.** STRATEGIE.md 4.3 bezeichnet die manuelle Belegungseingabe als „ersten Connector" hinter der PMS-Abstraktion. Das ist eine Fehlabstraktion: Ein Connector adaptiert ein externes System. Die manuelle Eingabe ist jedoch ein interner UI-Input.

**Entscheidung.** Der `OccupancyService` liest ausschließlich aus einer einzigen internen Tabelle `occupancy`. Schreibquellen sind gleichberechtigt: das Admin-UI schreibt direkt; jeder PMS-Connector schreibt ebenfalls direkt in dieselbe Tabelle und markiert seine Einträge über das Feld `source`. Ein PMS-Connector ist damit ein reiner Import-Adapter.

**Begründung.** Saubere Trennung: Die Kernlogik liest aus einer Quelle. Ausfall eines PMS-Connectors macht andere Schreibquellen nicht betroffen. Die „Abstraktion ist immer da"-Garantie gilt ohne Scheinkonstrukt.

---

## AE-03 · Keine Gastdaten in der Heizungsdatenbank

**Kontext.** STRATEGIE.md 7.1 listet `reservations.gast_name (verschlüsselt)`. Für die Heizsteuerung ist der Name nicht nötig – ausreichend sind Zimmer, Anreise- und Abreise-Zeitpunkt.

**Entscheidung.** `reservations` enthält nur: `room_id, arrival_datetime, departure_datetime, status, source, last_synced_at`. Kein Gastname, keine Kontaktdaten, keine Gast-ID aus dem PMS. PMS-Connectoren verwerfen personenbezogene Felder bereits beim Import.

**Begründung.** DSGVO-Risiko (R7) entfällt weitgehend. Keine Schlüsselverwaltung, kein Löschkonzept, kein Auftragsverarbeitungsvertrag für Gastdaten nötig. Das System wird aus Datenschutzsicht ein reines Gebäudeautomations-System.

---

## AE-04 · Fenster-Erkennung als Treiber-Feature

**Kontext.** STRATEGIE.md 6.2, Regel 5: Temperatursturz > 2 °C in 5 Min soll das Ventil schließen. Bei LoRaWAN Class A (Vicki) liegen zwischen zwei Uplinks typisch 15–30 Min – die geforderte 5-Min-Reaktion ist über den Cloud-Pfad nicht einhaltbar.

**Entscheidung.** Die Fenster-Erkennung läuft lokal im Vicki-Thermostat (eingebaute Open-Window-Detection). Der Vicki-Treiber in der Geräte-Abstraktion aktiviert und konfiguriert dieses Feature; die Cloud empfängt nur den Status „Fenster-offen erkannt" und loggt ihn. Andere Treiber (z. B. Milesight WT102 oder zukünftige Hersteller) implementieren das gleiche Treiber-Interface `supports_window_detection()` entweder hardwareseitig oder – wenn nicht vorhanden – deaktivieren diese Regel für das betroffene Gerät.

**Begründung.** Reaktionsgeschwindigkeit und Batterielebensdauer bleiben erhalten. Die Herstellerabhängigkeit wird durch ein klares Feature-Flag im Treiber-Interface gekapselt – der Kern bleibt herstellerneutral.

---

## AE-05 · Edge-Autonomie ohne Regel-Duplizierung

**Kontext.** STRATEGIE.md 4.6 fordert, dass das System bei Cloud-Ausfall „autonom weiterarbeitet". Wird die Regel-Engine auf der Edge (Node-RED) dupliziert, entsteht Wartungshölle mit zwei Implementierungen.

**Entscheidung.** Die Regel-Engine läuft ausschließlich in der Cloud. Node-RED auf der UG65 erhält von der Cloud einen minimalen Fallback-State pro Raum: aktueller Sollwert und Frostschutz-Grenze. Bei Cloud-Ausfall friert das System auf diesem Zustand ein; Thermostate halten ihren Sollwert, Frostschutz ist aktiv. Nach Wiederherstellung läuft eine Resynchronisation.

**Begründung.** Zimmer im Hotel Sonnblick sind sehr gut isoliert – ein Cloud-Ausfall von einigen Stunden bleibt komfortneutral. Der Gewinn aus doppelter Regel-Ausführung steht in keinem Verhältnis zum Aufwand. Die einzige kritische Garantie (Frostschutz) wird edge-seitig gehalten.

---

## AE-06 · Regel-Engine als fünfschichtige Pipeline

**Kontext.** STRATEGIE.md 6.2 listet acht Regeln ohne Priorisierung. Bei Konflikten (z. B. Nachtabsenkung aktiv vs. Vorheizen für 05:30-Anreise) muss entschieden werden, welche Regel gewinnt.

**Entscheidung.** Die acht Regeln werden in fünf Schichten organisiert, die in fester Reihenfolge angewendet werden:

| Schicht | Zweck | Regeln |
|---|---|---|
| 1 · Base Target | Grundsollwert aus Belegung | R1, R7 |
| 2 · Temporal Override | Zeitabhängige Übersteuerung | R2, R3, R4 |
| 3 · Guest Override | Manueller Gast-Eingriff | R6 |
| 4 · Window Safety | Fenster-offen-Reaktion | R5 |
| 5 · Hard Clamp | Absolute Grenzen | R8 + Gäste-Grenzen |

**Begründung.** Keine Regel-Priorisierung nötig – die Reihenfolge ist die Architektur. Jede Schicht ist eine eigene reine Funktion, einzeln testbar. Neue Regeln lassen sich klar zuordnen. Schicht 5 garantiert Frostschutz und Gäste-Grenzen absolut.

**Konfliktauflösung Beispiel.** Gast-Anreise 05:30, Nachtabsenkung bis 06:00: Schicht 1 liefert `T_belegt`, Schicht 2 priorisiert die explizite Intent-Regel „Vorheizen" über die Hintergrundregel „Nachtabsenkung" – Vorheizen beginnt 04:00.

---

## AE-07 · Trigger hybrid: Events + 60-s-Scheduler

**Kontext.** Eine reine Periodik (z. B. jede Minute alle Räume auswerten) ist verschwenderisch. Eine rein eventbasierte Architektur verpasst zeitliche Regeln (Vorheiz-Start, Nachtabsenkung).

**Entscheidung.** Zwei Trigger-Quellen:

- **Events (sofort):** Belegungsänderung, Thermostat-Uplink, Gast-Override, Settings-Änderung rufen `evaluate_room(room_id)` auf.
- **Scheduler (Celery-Beat, 60 s):** Prüft ausschließlich Räume mit `next_transition_at <= now`. Zeitliche Regeln tragen beim Evaluieren ihren nächsten Umschaltzeitpunkt in dieses Feld ein.

**Begründung.** Reaktionszeit auf Events im Sekundenbereich. Keine CPU-Verschwendung für ruhige Räume. Skaliert linear mit Anzahl anstehender Transitions, nicht mit Zimmeranzahl.

---

## AE-08 · Reine Funktion plus vollständiges Event-Log

**Kontext.** Testbarkeit und KI-Vorbereitung (STRATEGIE.md 6.4) fordern Reproduzierbarkeit und lückenlose Kontext-Historie.

**Entscheidung.** Die Engine ist eine reine Funktion `evaluate(ctx: RuleContext) -> RuleResult` ohne Seiteneffekte. Alle benötigten Daten werden vorher geladen, das Ergebnis wird nachher persistiert. Jede Evaluation schreibt einen Eintrag in `event_log` – auch dann, wenn der Sollwert unverändert bleibt. Der Eintrag enthält Sollwert, Grund, ausgelöste Schichten und vollständigen Kontext-Snapshot (Belegung, Wetter, Innen-/Außentemperatur, vorheriger Sollwert).

**Begründung.** Tests laufen ohne Datenbank. KI-Training in Phase 2 braucht vollständige Historie inklusive „Nicht-Änderungen". Speicherbedarf ca. 10 MB pro Raum pro Jahr, von TimescaleDB automatisch komprimiert.

---

## AE-09 · Downlink nur bei Änderung, mit Duty-Cycle-Budget

**Kontext.** EU-LoRaWAN-Regulierung erlaubt nur 1 % Duty Cycle. Unnötige Downlinks gefährden die Verfügbarkeit für kritische Befehle (Frostschutz).

**Entscheidung.** Nach jeder Evaluation wird ein Downlink nur dann erzeugt, wenn der neue Sollwert vom letzten gesendeten Wert abweicht (Hysterese 0,5 °C). Downlinks laufen in eine Priority-Queue: Frostschutz > Fenster-Reaktion > Normalbetrieb. Die Queue respektiert das Duty-Cycle-Budget pro Kanal.

**Begründung.** Bei 130 Thermostaten und 1 % Duty-Cycle wäre ein naives „immer senden" nicht haltbar. Priorisierung stellt sicher, dass sicherheitsrelevante Befehle nicht durch Routine-Updates blockiert werden.

---

## AE-10 · Gast-Override endet am nächsten Schaltpunkt

**Kontext.** STRATEGIE.md 6.2, Regel 6: Override gilt „bis zum nächsten Profil-Schaltpunkt oder maximal 4 Stunden". „Schaltpunkt" war nicht definiert.

**Entscheidung.** Ein Schaltpunkt ist jeder Zeitpunkt, an dem eine zeitliche Regel umschaltet: Vorheiz-Start, Check-out, Nachtabsenkung-Start, Nachtabsenkung-Ende, Langzeit-Absenkungs-Schwelle. Der Gast-Override endet beim erstem dieser Ereignisse – oder nach 4 h, falls keines früher eintritt.

**Beispiel.** Gast stellt 22:00 auf 24 °C. Nachtabsenkung startet 00:00. Override endet um 00:00, nicht 02:00.

**Begründung.** Nachtabsenkung und Check-out sind primäre Energiespar- und Komfortmaßnahmen und werden nicht durch spätabendliche Gasteingaben verschoben. Die 4-h-Obergrenze schützt bei seltenen Räumen ohne Schaltpunkte.

---

## AE-11 · Vorheizen statisch 90 Min im MVP

**Kontext.** STRATEGIE.md Regel 2 setzt 90 Min Vorheizzeit. Wetterabhängige Heuristik wäre technisch möglich.

**Entscheidung.** MVP bleibt bei fixen 90 Min. Wetterabhängige Dynamik wird frühestens in Phase 2 eingeführt, zusammen mit der KI-Ebene.

**Begründung.** Zimmer sind sehr gut isoliert, Auskühlung zwischen Check-outs begrenzt. 90 Min sind ein sicherer Mittelwert ohne Komfortrisiko. Early Optimization vermeiden.

---

## AE-12 · API-Key-Scopes und User-Rollen sind getrennte Dimensionen

**Kontext.** STRATEGIE.md A8 definiert nur eine Admin-Rolle im MVP. A16 fordert API-Key-Scopes `read/write/admin`. Das wirkt widersprüchlich.

**Entscheidung.** Zwei unabhängige Autorisierungs-Dimensionen:

- **User-Rollen** (für menschliche Admin-UI-Nutzer): MVP nur `admin`. Phase 2: weitere Rollen.
- **API-Key-Scopes** (für Maschinen-zu-Maschinen-Zugriff): bereits im MVP `read`, `write`, `admin`.

**Begründung.** Ein externes Monitoring-Tool braucht nur `read` – auch wenn es technisch keinen User gibt. Die Trennung erlaubt feingranulare Maschinen-Berechtigungen ohne User-Rollen-System.

---

## AE-13 · ChirpStack als eigenständiger Container

**Kontext.** Das Milesight UG65 Gateway bringt einen eingebauten ChirpStack-LNS mit. Alternativ ist ein externer Provider (TTN, Helium) möglich. Der Container-Weg bedeutet zusätzlichen Service-Footprint.

**Entscheidung.** ChirpStack v4 läuft als Docker-Container in unserer Compose-Stack — weder als Embedded-LNS auf dem Gateway noch als externer Provider. Das Gateway agiert nur als Packet-Forwarder und sendet Pakete via UDP/TCP an unseren ChirpStack.

**Begründung.** Vendor-unabhängige Versionskontrolle, einheitliche Backup-Strategie über DB-Volumes, Wechsel auf zweites Gateway später trivial, kein Cloud-Lock-in (DSGVO), Web-UI über Caddy-Reverse-Proxy zentral erreichbar. Der RAM-Mehraufwand (ca. 150 MB) ist auf CPX22 unkritisch.

---

## AE-14 · Eigene Postgres-Instanz für ChirpStack

**Kontext.** ChirpStack braucht Postgres als Backing Store. Die Heizung-Anwendung nutzt bereits TimescaleDB (Postgres-Derivat). Eine geteilte Instanz wäre denkbar.

**Entscheidung.** ChirpStack bekommt eine eigene Postgres-Instanz (`chirpstack-postgres`, postgres:16-alpine), getrennt von der Heizungs-DB.

**Begründung.** ChirpStack-Schema ist vendor-controlled und ändert sich bei Major-Updates. Eine geteilte DB würde Migration-Reihenfolgen koppeln und unsere Backup-Strategie verkomplizieren. Zwei Container sind sauberer trennbar bei Disaster-Recovery. Der Mehraufwand RAM/Disk ist marginal.

---

## AE-15 · Mosquitto v2 als MQTT-Broker mit ACL

**Kontext.** ChirpStack publisht Uplinks per MQTT. FastAPI muss konsumieren. Optionen: HTTP-Webhook (synchron), eingebauter ChirpStack-Broker (nicht vorgesehen), externer Broker (Mosquitto, EMQX, RabbitMQ).

**Entscheidung.** Eigenständiger Eclipse Mosquitto v2 Container. Anonymous-Login deaktiviert. Zwei User in der Passwort-Datei: `chirpstack` (Publish auf `application/#`) und `heizung-api` (Subscribe auf `application/+/device/+/event/up`). ACL via `acl_file` enforced.

**Begründung.** Mosquitto ist ChirpStack-Standard, leichtgewichtig (<50 MB RAM), stabil, kein Vendor-Lock. Webhook wäre primitiver, würde aber Replay-Fähigkeit, mehrere Subscriber (Future: WebSocket-Push ans Frontend) und FastAPI-Hochverfügbarkeit blockieren. ACL-Trennung verhindert, dass kompromittierte API-Credentials Uplinks fälschen können.

---

## AE-16 · Vicki-Decoder als JS-Codec in ChirpStack

**Kontext.** MClimate Vicki sendet binäre Payloads. Decoder kann (a) im FastAPI-Backend oder (b) als JS-Codec im ChirpStack-DeviceProfile laufen.

**Entscheidung.** Decoder läuft als JS-Codec im DeviceProfile. FastAPI verlässt sich auf das vom ChirpStack decodierte `object`-Feld im Uplink-Event.

**Begründung.** Hersteller-Codec ist in JS verfügbar (MClimate Open-Source-Repo), keine Re-Implementation nötig. Vereinheitlichte Codec-Logik über alle Konsumenten (auch ChirpStack-UI zeigt decoded Werte). Backend bleibt Codec-agnostisch — bei neuen Geräte-Typen reicht ein neues DeviceProfile, keine Backend-Änderung. Codec-Datei wird versioniert in `infra/chirpstack/codecs/` mit Source-URL und Commit-SHA.

---

## AE-17 · Uplinks als TimescaleDB-Hypertable mit JSONB-Payload

**Kontext.** Sensor-Uplinks sind Zeitreihen (typisch 1× pro 15 Min × 130 Geräte = ~1 Mio Rows/Jahr). Schema-Optionen: normalisiert (Spalte pro Sensor-Wert), JSONB, oder Wide-Table.

**Entscheidung.** Eine `uplinks`-Hypertable mit Kernfeldern (`device_id`, `ts`, `fcnt`, `rssi`, `snr`, `freq`) und einem `payload`-JSONB-Feld für die decoded Vicki-Werte. Chunk-Intervall 7 Tage. Eindeutigkeit via `UNIQUE (device_id, fcnt)` für idempotente Inserts.

**Begründung.** JSONB hält uns offen für unterschiedliche Geräte-Typen ohne Migrations-Hölle. TimescaleDB komprimiert ältere Chunks automatisch (~10× Reduktion typisch). Kernfelder bleiben indizierbar/queryable. UNIQUE-Constraint via DevEUI+FrameCounter macht MQTT-Replays bei Reconnects unproblematisch.

**Konsequenz.** Frontend-Queries auf Sensor-Werte (z. B. `payload->>'temperature'`) sind etwas teurer als Spaltenzugriffe — bei 1 Mio Rows/Jahr mit Indices auf `(device_id, ts DESC)` aber unkritisch. Bei Performance-Engpässen später materialized views.

---

## AE-18 · MQTT-Subscriber als FastAPI-Lifespan-Background-Task

**Kontext.** Wer konsumiert MQTT? Optionen: separater Microservice (eigener Container), Celery-Worker, FastAPI-Background-Task, externes Tool wie Telegraf.

**Entscheidung.** `aiomqtt`-Subscriber läuft als asyncio-Task im FastAPI-Lifespan. Reconnect-Loop mit Exponential Backoff. Persistente Sessions (`clean_session=False`, fixierte Client-ID `heizung-api-subscriber`), QoS 1.

**Begründung.** Kein zusätzlicher Container, kein Celery-Overhead. FastAPI läuft sowieso 24/7. Async-Stack ist passend zu MQTT-IO. Bei Skalierung > 1 FastAPI-Instanz wird der Subscriber auf einen separaten Worker-Container ausgelagert (späterer Sprint, falls relevant) — bis dahin trägt die Persistent-Session-Semantik plus UNIQUE-Constraint.

---

## Nicht-Entscheidungen (bewusst offen gelassen)

Folgende Punkte werden erst bei Bedarf entschieden, nicht jetzt:

- **PMS-Mock für Testsystem:** Technische Ausgestaltung entsteht in Sprint 11.
- **`settings_history`-Detailstruktur:** Minimal-Schema (user_id, timestamp, path, old_value, new_value) wird in Sprint 2 implementiert, Erweiterungen bei Bedarf.
- **Thermostat-Hysterese-Werte:** Werden aus Pilotdaten in Sprint 10 empirisch bestimmt.
- **Downlink-Queue-Implementierung:** Wird in Sprint 3 (Geräte-Abstraktion) festgelegt.

---

## Änderungsprotokoll

| Version | Datum | Änderung |
|---|---|---|
| 1.0 | April 2026 | Initiale Version vor Entwicklungsstart |
| 1.1 | 2026-04-27 | AE-13 bis AE-18 ergänzt (Sprint 5: ChirpStack, Mosquitto, Vicki-Codec, Uplink-Hypertable, MQTT-Subscriber-Pattern) |

---

*Ende des Dokuments*
