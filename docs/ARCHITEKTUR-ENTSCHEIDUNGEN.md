# Hotel Sonnblick – Heizungssteuerung

## Architektur-Entscheidungen

**Version 1.2 · April 2026**
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

## AE-19 · Basic Station als Gateway-Protokoll (Sprint 6)

**Kontext.** Das Milesight UG65 unterstuetzt zwei LoRaWAN-Gateway-Protokolle: klassisches Semtech-UDP-Packet-Forwarding (Port 1700, unverschluesselt) und Basic Station (TLS-WebSocket auf Port 443).

**Entscheidung.** UG65 spricht Basic Station gegen `wss://cs-test.hoteltec.at:443/router-info`. Caddy macht TLS-Termination (Let's Encrypt) und reverse-proxiet zum `chirpstack-gateway-bridge`-Container intern.

**Begruendung.** Verschluesselte Verbindung ohne UDP-Port-Forwarding; Hetzner-Cloud-Firewall + UFW koennen TCP/443 ohnehin zulassen; Basic Station ist ChirpStack-v4-Standard. Keine eingehenden Ports am Hotel-LAN noetig.

---

## AE-20 · ChirpStack-Konfig via envsubst-Sidecar

**Kontext.** ChirpStack v4 substituiert KEINE `${VAR}`-Platzhalter in den TOML-Konfigs. Auch das offiziell dokumentierte env-Override-Pattern `CHIRPSTACK__SECTION__FIELD` greift in unserer Konstellation nicht zuverlaessig (zumindest nicht fuer `[postgresql] dsn`).

**Entscheidung.** Ein `alpine`-Init-Sidecar laeuft vor dem ChirpStack-Container, liest die TOML-Templates aus dem Bind-Mount (`infra/chirpstack/configuration/`), expandiert `${VAR}`-Platzhalter mit `envsubst` und schreibt die fertige Konfig in ein Named Volume (`chirpstack_config_rendered`). ChirpStack mountet dieses Volume read-only.

Selbes Muster fuer den `chirpstack-gateway-bridge`-Container.

**Begruendung.** Robust und unabhaengig von ChirpStack-internen Substitutions-Mechanismen. Secrets bleiben in der `.env` und kommen ueber Compose-env in den Init-Container. ChirpStack sieht eine "fertig gerenderte" Konfig — keine Plaintext-Passwoerter im Image-Layer, keine Inline-Substitution-Fehler.

---

## AE-21 · shadcn/ui-Foundation aufgeschoben (Sprint 7)

**Kontext.** Sprint 7 brauchte eine schnelle Frontend-Foundation. shadcn/ui haette Standard-Komponenten gebracht, aber der `init`-Prozess kollidiert mit dem in Sprint 0 etablierten Custom-Theme (CSS-Variablen-basiertes Design-System, Rosé + Heating-Farben, Roboto, Material Symbols Outlined).

**Entscheidung.** Sprint 7 nutzt **Plain Tailwind** mit unseren Custom-Tokens. shadcn/ui-Einfuehrung wird als eigener Refactor-Sprint geplant, mit Backup-Strategie und manuellem Theme-Merge.

**Begruendung.** Pragmatik: Sichtbarer Mehrwert (Devices-Liste + Detail-View) wichtiger als UI-Lib-Best-Practice. Der eigentliche Gewinn von shadcn (Source-basierte Komponenten, kein Vendor-Lock) bleibt jederzeit nachholbar.

---

## AE-22 · TanStack Query v5 als Server-State-Management

**Kontext.** Frontend braucht Caching, Refetch-on-Focus, optimistic-Updates fuer die FastAPI-Aufrufe.

**Entscheidung.** `@tanstack/react-query` v5 mit Devtools. Defaults: `staleTime: 30 s`, `refetchOnWindowFocus: true`, `retry: 1`. Pro Hook `refetchInterval: 30 s` fuer near-realtime-Updates auf der Detail-Seite (Reading-Daten, Device-Status).

**Begruendung.** Industriestandard fuer React-Apps mit REST-Backend. Reduziert Boilerplate enorm gegenueber `useEffect+useState`. Mutations invalidieren nach Erfolg automatisch die Liste-Caches (z. B. POST `/devices` invalidiert `useDevices`).

---

## AE-23 · Recharts fuer Charts

**Kontext.** Sprint 7 zeigt einen 24-h-Temperatur-Verlauf pro Geraet.

**Entscheidung.** `recharts` als Chart-Library. Komponente `sensor-readings-chart.tsx` mit `"use client"`-Direktive (Recharts hat SSR-Hydration-Issues mit Next.js Server-Components).

**Begruendung.** Tailwind-/CSS-Variable-kompatibel, gute TypeScript-Typen, Standard fuer React-TS-Projekte. Plain SVG selbst zu schreiben war fuer den Aufwand nicht gerechtfertigt.

---

## AE-24 · Next.js-Rewrite fuer API-Proxying

**Kontext.** Frontend ruft `/api/v1/...` (relativ). In Production proxiet Caddy diese Pfade an FastAPI. Lokal lief bisher kein Caddy.

**Entscheidung.** Next.js-Rewrite-Regel in `next.config.mjs`: `/api/v1/:path*` → `${API_PROXY_TARGET}/api/v1/:path*`. Default `http://api:8000` fuer Container-internen Service-Namen. Ueber Env-Variable `API_PROXY_TARGET` ueberschreibbar (z. B. `http://localhost:8000` fuer reines `npm run dev` ohne Compose).

**Begruendung.** Frontend-Code bleibt identisch zwischen Lokal-Dev und Production (relative Pfade). Kein CORS-Setup im Backend noetig. Production-Caddy ueberschattet dieses Rewrite — schadet aber nicht.

---

## AE-25 · Design-Token-System mit flachem Mapping (Sprint 7)

**Kontext.** Sprint-0-Tailwind-Config hatte CSS-Variablen-basiertes Theme, aber mit nested-Mapping (`bg.surface`, `bg.surface-alt`). Klassen wie `bg-surface` griffen nicht — Tailwind erwartete `bg-bg-surface`. Folge: Hover-States in den Sprint-7-Komponenten waren tot.

**Entscheidung.** Tailwind-Token flach umgestellt: `surface`, `surface-alt`, `overlay`, `border`, `border-strong`, `border-focus` als Top-Level-Colors. Plus Schriftgroessen-Skala als CSS-Variablen (`--font-size-xs/sm/base/lg/xl/2xl/3xl`). Body nutzt `var(--font-size-base)`.

**Begruendung.** Saubere Klassen-Konvention (`bg-surface` macht was es sagt). Globale Schriftgroessen-Skalierung ueber eine Variable (z. B. fuer User-Settings „kompakt/normal/groß"). Theme-Wechsel (Light/Dark) bleibt trivial nachholbar via `[data-theme]`-Selector.

**Konsequenz.** AE-01 (Material Symbols als einziges Icon-Set) bleibt unveraendert. Roboto bleibt UI-Schrift. Dark-Mode ist nicht Teil von Sprint 7, aber das Design-System ist fundament-tauglich.

---

## Nicht-Entscheidungen (bewusst offen gelassen)

Folgende Punkte werden erst bei Bedarf entschieden, nicht jetzt:

- **PMS-Mock für Testsystem:** Technische Ausgestaltung entsteht in Sprint 11.
- **`settings_history`-Detailstruktur:** Minimal-Schema (user_id, timestamp, path, old_value, new_value) wird in Sprint 2 implementiert, Erweiterungen bei Bedarf.
- **Thermostat-Hysterese-Werte:** Werden aus Pilotdaten in Sprint 10 empirisch bestimmt.
- **Downlink-Queue-Implementierung:** Wird in Sprint 3 (Geräte-Abstraktion) festgelegt.

---

## AE-26 · Saison als oberste Resolution-Schicht in der Settings-Hierarchie

**Kontext.** AE-06 hat die Engine als 5-Schichten-Pipeline entworfen. Settings werden mit der 3-Ebenen-Hierarchie ROOM > ROOM_TYPE > GLOBAL aufgeloest. Saisonale Ueberschreibungen (Skisaison, Sommerpause) brauchen eine zusaetzliche Dimension, die alle 3 Ebenen ueberschreiben kann.

**Entscheidung.** `rule_config` bekommt eine optionale Spalte `season_id`. Wenn gesetzt, gilt der Eintrag NUR im Saison-Zeitraum. Resolution-Reihenfolge erweitert auf 7 Stufen:

1. Saison-spezifisch ROOM
2. Saison-spezifisch ROOM_TYPE
3. Saison-spezifisch GLOBAL
4. Permanent ROOM
5. Permanent ROOM_TYPE
6. Permanent GLOBAL
7. Hardcoded Default

**Begruendung.** Eine separate `season_rule_config`-Tabelle waere doppelte Schema-Pflege. Die NULL-able-Spalte mit derselben Validierung skaliert fuer 5-10 Saisons pro Hotel ohne Performance-Probleme.

---

## AE-27 · Szenarien als orthogonale Aktivierungsschicht (Stammdaten + Assignment)

**Kontext.** Aus den Betterspace-Screenshots ergeben sich 22+ Szenarien (Tagabsenkung, Nachtabsenkung, Realtime Check-in, ...). Die Strategie fasste das in den 8 Kernregeln zusammen, aber der Hotelier denkt in "Szenarien" als Konfigurations-Einheit. Die Engine-Architektur (AE-06) bleibt regel-basiert.

**Entscheidung.** Zwei neue Tabellen:

- `scenario`: Stammdaten (code, name, description, parameter_schema JSONB, default_active, is_system).
- `scenario_assignment`: Aktivierung pro Scope (global/room_type/room) mit Override-Parametern als JSONB. Optional `season_id` fuer saisonale Aktivierung.

Die Engine liest beim Evaluieren beide Tabellen und mapped Szenarien auf Regel-Layer (Tagabsenkung -> Layer 2 Temporal Override, etc.).

**Begruendung.** Trennung von Was (Regel-Logik in Code) und Ob/Wie (Szenario-Aktivierung in DB). Hotelier-mentales-Modell respektiert. Custom-Szenarien (Phase 2) brauchen nur einen neuen `code`-Eintrag plus parameter_schema. Keine Code-Aenderung fuer reine Konfig-Anpassung.

---

## AE-28 · `global_config` als Singleton-Tabelle statt EAV

**Kontext.** Hotel-globale Settings (Default-Check-in-Zeit, Sommermodus-Flag, Email-Adresse fuer Alerts, Hotel-Name, Timezone) sind keine Regel-Parameter, sondern System-Konfiguration. EAV (key-value) waere flexibel aber schwer validierbar.

**Entscheidung.** Tabelle `global_config` mit `id PK = 1` (CHECK constraint), benannten Spalten pro Setting, Singleton-Pattern. Bei neuen Settings: Migration mit neuer Spalte plus DEFAULT.

**Begruendung.** Typsicher (Pydantic-Mapping trivial), explizit (Migration zeigt jede neue Setting), versioniert. Pflegeaufwand bei 10-30 Settings akzeptabel. EAV waere bei < 50 Settings Over-Engineering.

---

## AE-29 · `manual_setpoint_event` als zeitlich begrenzter Override

**Kontext.** Hotelier braucht "Temperatur jetzt setzen" als One-Off-Aktion (Wartung Fenster, Spezialgast, Aufheizen vor Ankunft). Soll ueber alle Regeln gewinnen ausser Frostschutz, aber zeitlich begrenzt.

**Entscheidung.** Tabelle `manual_setpoint_event` mit `scope`, `room_type_id` ODER `room_id`, `target_setpoint_celsius`, `starts_at`, `ends_at`, `is_active`, `reason TEXT`. Engine prueft im Layer 3 (Manual Override): Gibt es ein aktives Event mit jetzt zwischen starts_at und ends_at? Ja -> Setpoint ersetzen.

**Begruendung.** Audit-faehig (Wer hat wann was warum gesetzt). Auto-Expire ohne Cron-Job (Engine prueft jedes Eval). Multi-Scope (Bulk-Action auf Raumtyp moeglich).

---

## AE-30 · Saison-Override gilt nur fuer rule_config, NICHT fuer Stammdaten

**Kontext.** Theoretisch koennten Raumtyp-Defaults oder Zimmer-Zuordnungen saisonal variieren ("Im Sommer ist Zimmer 215 Lager statt Schlafzimmer"). Soll die Saison auch Stammdaten ueberschreiben?

**Entscheidung.** Nein. Saison-Eintraege wirken NUR auf `rule_config`-Werte (Setpoints, Zeitfenster, Override-Grenzen). Stammdaten-Aenderungen (room_type, room.room_type_id, heating_zone) sind permanente CRUD-Operationen. Wenn ein Raum saisonal anders genutzt wird, muss die Belegung das abbilden (z.B. `BLOCKED`-Status).

**Begruendung.** Saubere Trennung: Saison ist Settings-Override, kein Stammdaten-Modifier. Sonst entsteht eine zweite Realitaet, die debuggen zur Hoelle macht.

---

## AE-31 · Engine als reine Funktion mit 6 Layern (Erweiterung von AE-06 + AE-08)

**Kontext.** AE-06 entwarf 5 Schichten. AE-08 forderte reine Funktion plus vollstaendiges Event-Log. AE-26 fuehrt Saison ein. AE-27 fuehrt Szenarien ein. AE-29 fuehrt manuelle Events ein. Wir brauchen eine konsolidierte Pipeline-Definition.

**Entscheidung.** `evaluate(ctx: RuleContext) -> RuleResult` mit 6 Layern:

| # | Layer | Quelle | Wirkung |
|---|---|---|---|
| 0 | Sommermodus-Fast-Path | `global_config.summer_mode_active` | Sofort Frostschutz, Return |
| 1 | Base Target | rule_config-Hierarchie (Saison > Permanent) | T_belegt / T_frei / T_long_vacant |
| 2 | Temporal Override | Aktive Szenarien (Tag/Nacht/Vorheizen/Auszug) | Offset oder Absoluttemp |
| 3a | Manual Setpoint Event | `manual_setpoint_event` aktiv | Ersetzt Setpoint |
| 3b | Gast-Override am Vicki | `sensor_reading.manual_setpoint` | Cap auf [min, max] gemaess AE-10 |
| 4 | Window Safety | `sensor_reading.window_open_detected` | Setpoint = FROST_PROTECTION_C |
| 5 | Hard Clamp | `MIN(MAX_HOTEL_C, MAX(FROST_PROTECTION_C, setpoint))` | Garantierte Grenzen |

Jeder Layer ist eine eigene reine Funktion `apply_layer_X(setpoint, ctx) -> (setpoint, reason)`. `event_log` bekommt einen Eintrag pro Layer pro Evaluation (Audit + KI-Vorbereitung).

**Begruendung.** Jeder Layer einzeln testbar. Reihenfolge ist die Architektur (keine Konflikt-Aufloesung in den Regeln selbst). Audit ist vollstaendig — auch "warum hat sich nichts geaendert" ist sichtbar.

---

## AE-32 · Downlink-Hysterese 0.5 Grad als Konstante

**Kontext.** AE-09 forderte "nur senden bei Aenderung mit Hysterese 0.5 Grad". Konstante muss zentral sein.

**Entscheidung.** `heizung.rules.constants.SETPOINT_HYSTERESIS_C = Decimal("0.5")`. Plus `SETPOINT_HEARTBEAT_HOURS = 6` (mindestens alle 6 h einen Heartbeat-Downlink, auch wenn Wert unveraendert).

**Begruendung.** Werte aenderbar nur via Code-Review (Migration kommt nicht in Frage fuer Konstante). Test-Coverage stellt sicher, dass Aenderung des Wertes Tests aktualisiert.

---

## AE-33 · Bei Saison-Konflikt gewinnt das spaetere `starts_on`

**Kontext.** Zwei Saisons koennen sich ueberschneiden (z.B. "Winter 2026/27" 01.10-30.04 und "Skisaison" 15.12-15.03). Engine muss eindeutig entscheiden welcher Override gilt.

**Entscheidung.** Bei mehreren aktiven Saisons fuer ein Datum gewinnt die Saison mit dem spaetesten `starts_on`. Bei gleichem `starts_on`: hoechste `id` (zuletzt angelegt). UI warnt beim Anlegen ueberlappender Saisons.

**Begruendung.** "Spezifischer schlaegt allgemein" — eine kuerzere, spaeter angelegte Saison ist typischerweise die spezifischere. Deterministisch ohne Rangfolge-Spalte. UI-Warnung verhindert ungewollte Konflikte.

---

## AE-34 · Sommermodus deaktiviert R1-R7, R8 Frostschutz bleibt aktiv

**Kontext.** Was bedeutet "Sommermodus" konkret? Heizung komplett aus? Frostschutz aktiv?

**Entscheidung.** Sommermodus = Layer-0-Fast-Path in der Engine. Setpoint pro Raum = MAX(`FROST_PROTECTION_C`, eventuell saison-spezifisch erhoehter Sommer-Frostschutz). KEINE Belegungs-, Vorheiz-, Tagabsenkung-, Nachtabsenkung-Regeln. Vicki-Geraete senden weiter Telemetrie und Downlinks. Sommermodus kann manuell oder via Datum (`summer_mode_starts_on`/`ends_on` in `global_config`) aktiviert werden.

**Begruendung.** "Heizung komplett aus" waere bei Sommertagen mit Kaltfront riskant (Wasserrohre). 10 Grad Frostschutz ist EU-Standard. Hotelier kann via Saison-Override hoeheren Sommer-Frostschutz definieren (z.B. 12 Grad fuer Wohnkomfort).

---

## AE-35 · UI-Navigation in 6 Hauptbereichen (ersetzt Sprint-7-Sidebar)

**Kontext.** Strategie 8.3 listet 12 Sidebar-Eintraege in 5 Gruppen. Sprint 7 hat eine vereinfachte Variante mit nur "Devices". Hotelier-Workflow zeigte: 6 mentale Bereiche reichen, mehr ist Reibung.

**Entscheidung.** Neue Sidebar-Struktur:

- HEUTE (Dashboard, Live-Status)
- ZIMMER (Liste, Floorplan, Belegungen)
- REGELN (Globale Einstellungen, Raumtypen, Szenarien, Saisons, Sommermodus)
- GERAETE (Liste, Gateway, Pairing)
- ANALYSE (Heizverlauf, Audit-Log, Reports)
- EINSTELLUNGEN (Hotel-Stammdaten, Benutzer, API-Keys, System-Status)

Mobile: Top-Level wird zur Bottom-Tab-Bar, zweite Ebene als Drawer von oben.

**Begruendung.** Hotelier-Mental-Model entspricht der natuerlichen Frequenz der Nutzung (Dashboard taeglich, Zimmer-CRUD selten, Regeln noch seltener). 6 Bereiche passen in jeden Bottom-Tab-Bar-Layout. Strategie-8.3-Eintraege bleiben erhalten als Unterpunkte, aber die Top-Hierarchie ist neu.

---

## AE-36 · Engine-Layer als Pure Functions + duenner DB-Wrapper (Sprint 9.3)

**Kontext.** Die 5-Schichten-Pipeline (AE-06, AE-31) braucht Tests fuer jede Schicht und Edge-Cases. Mit DB-Session in jedem Layer-Aufruf wuerde jeder Test eine Postgres-Test-DB benoetigen — Setup-Hoelle.

**Entscheidung.** Jede Schicht (`layer_base_target`, `layer_clamp`, `hysteresis_decision`, etc.) ist eine **pure Funktion** mit Input-Dataclass `_RoomContext` (room + room_type + rule_configs als bereits geladene SQLAlchemy-Objekte) und Output `LayerStep`. Der DB-Zugriff ist genau zwei Funktionen vorbehalten: `_load_room_context(session, room_id)` und `_last_command_for_room(session, room_id)`. Die Public-API `evaluate_room` orchestriert: laedt Context, schickt durch Layers, gibt `RuleResult` zurueck.

**Begruendung.** Pure-Function-Tests laufen mit `SimpleNamespace`-Dummies in Millisekunden ohne DB. 23 Layer-Tests in Sprint 9.3 nutzen das. Integration-Tests (Sprint 13) testen den DB-Wrapper separat. Erweiterungen (Layer 0/2/3/4 in 9.7-9.9) folgen demselben Pattern.

---

## AE-37 · Hard-Clamp-Reason wird durchgereicht statt hardcoded (Sprint 9.6b)

**Kontext.** Layer-5 Hard-Clamp setzte initial `reason = OCCUPIED_SETPOINT` als Fallback. Bei Vacant-/Reserved-/Cleaning-Status zeigte das Engine-Decision-Panel im Frontend "Belegt-Sollwert" obwohl korrekt "Frei-Sollwert".

**Entscheidung.** `layer_clamp` bekommt `prev_reason: CommandReason` als kwarg vom Caller. Reason wird durchgereicht, NUR ueberschrieben mit `FROST_PROTECTION` wenn der Clamp tatsaechlich den Wert auf `MIN_SETPOINT_C` zog (`prev_setpoint_c < MIN_SETPOINT_C`).

**Begruendung.** Audit-Log + UI brauchen die richtige Reason fuer Erklaerbarkeit. Der Layer 5 ist Sicherheits-Funktion, kein Reason-Setter. Die Reason gehoert zur urspruenglichen Setpoint-Entscheidung.

---

## AE-38 · Celery-Worker-Process-Isolation fuer asyncpg (Sprint 9.6b)

**Kontext.** asyncpg-Connections sind an einen Event-Loop gebunden. Celery prefork startet n Worker-Forks mit dem Pool des Master-Prozesses. `asyncio.run()` in einer Task baut einen NEUEN Loop auf — alte Connections crashen mit `RuntimeError: Future attached to a different loop`.

**Entscheidung.** Im `celery_app.py` registrieren wir einen `@worker_process_init.connect`-Handler, der nach jedem Fork: `engine.dispose()` ausfuehrt und eine FRISCHE Engine + SessionLocal in `heizung.db` injiziert. Plus `pool_pre_ping=False` damit der Pool nicht im falschen Loop pingt.

**Begruendung.** Standard-asyncpg + Celery-prefork ist ein bekanntes Anti-Pattern. SQLAlchemy-Doku empfiehlt Engine-Reset pro Fork. Der Handler ist 10 Zeilen Code und loest das Problem komplett.

---

## Aenderungsprotokoll

| Version | Datum | Aenderung |
|---|---|---|
| 1.0 | April 2026 | Initiale Version vor Entwicklungsstart |
| 1.1 | 2026-04-27 | AE-13 bis AE-18 ergaenzt (Sprint 5) |
| 1.2 | 2026-04-28 | AE-19 bis AE-25 ergaenzt (Sprint 6 + 7) |
| 1.3 | 2026-05-02 | AE-26 bis AE-35 ergaenzt (Master-Plan Sprint 8-13: Saison, Szenarien, Sommermodus, Engine-Pipeline, UI-Navigation) |
| 1.4 | 2026-05-04 | AE-36 bis AE-38 ergaenzt (Sprint 9.3-9.6b: Engine-Layer-Architektur, Reason-Durchreichung, Worker-Engine-Reset) |

---

*Ende des Dokuments*


## AE-39 · Manual-Override Adapter-Pattern (Sprint 9.9)

**Kontext:** Engine Layer 3 muss Setpoint-Übersteuerungen aus zwei
Quellen verarbeiten: Vicki-Drehknopf (LoRaWAN-Uplink) und Frontend-
Rezeption (REST). Künftiger PMS- oder Thermostat-Wechsel soll keine
Engine-Änderung erzwingen.

**Entscheidung:** Generische `manual_override`-Tabelle mit `source`-
Spalte (`device | frontend_4h | frontend_midnight | frontend_checkout`).
Adapter-Schicht (`device_adapter`, `override_pms_hook`, REST-API)
befüllt die Tabelle, Engine kennt nur generische Override-Records.
Diff-Strategie für Vicki (kein dediziertes user-Setpoint-Feld im
Codec) via `ControlCommand`-Vergleich mit Toleranz-Modi (`0.6 °C`
für `fPort 1`/`uint8`, `0.1 °C` für `fPort 2`/decimal) und
60s-Acknowledgment-Window.

**Konsequenzen:**
+ Engine-Code unabhängig von PMS- und Hardware-Wahl.
+ Neue Quelle (z.B. Mobile-App) = neuer `source`-Wert + Adapter,
  kein Engine-Touch.
+ `next_active_checkout` und `next_active_checkin` zentral in
  `services/occupancy_service`, von API + Engine + PMS-Hook geteilt.
- Diff-Strategie kann seltene Edge-Cases (gleichzeitiger
  Engine-Send und User-Drehung im 60s-Fenster) nicht zu 100% sauber
  unterscheiden — akzeptiert, weil Folge-Tick mit Hysterese korrigiert.
- `LayerStep.extras: dict | None` im Engine-Pipeline ist additive
  Erweiterung; andere Layer setzen es nicht.
---

## AE-40 · Engine-Task-Lock via Redis-SETNX (Sprint 9.10 T3.5)

**Kontext.** Ab Sprint 9.10 triggert der MQTT-Subscriber nach jedem
persistierten Reading ein ``evaluate_room.delay(room_id)``. Bei
mehreren Vickis im selben Raum oder schnellen Auf-/Zu-Sequenzen
kann derselbe Raum innerhalb von Sekunden mehrfach in der
Celery-Queue landen. Mit ``worker_concurrency=2`` laufen zwei
Evals fuer denselben Raum parallel — Folge: doppelte
``ControlCommand``-Rows, doppelte Downlinks, gegenseitige
Hysterese-Umgehung (jeder Task liest noch nicht-committed
Vorgaengerstand).

**Entscheidung.** ``evaluate_room`` akquiriert vor jeder Eval
einen Redis-SETNX-Lock auf dem Key ``engine:eval:lock:{room_id}``
mit TTL 30 s. Bei Erfolg laeuft die Eval; ``finally`` gibt den
Lock frei. Bei Misserfolg wird der Task ueber
``apply_async(countdown=5)`` erneut in die Queue gelegt. KEIN
Drop — ein verzoegerter Eval ist akzeptabel, ein verlorener nicht.

**Begruendung.**
+ Atomicity: Redis-SETNX serialisiert die Acquire-Versuche
  Cluster-weit — auch bei mehreren Worker-Containern auf
  verschiedenen Hosts.
+ Self-healing: Der TTL (30 s) ist >= ``task_time_limit``. Wird
  ein Worker im laufenden Eval gekillt, gibt der TTL den Lock
  spaetestens nach 30 s frei.
+ Re-Trigger statt Drop: ``countdown=5`` haelt den Burst-Trigger
  (Reading-Eval, PMS-Push) garantiert wirksam — der naechste
  Slot uebernimmt. Verlorene Edge-Reads sind im Sicherheits-
  kontext (Layer 4 Window-Detection) inakzeptabel.
- Nicht-Determinismus: Bei sehr hoher Frequenz kann ein Eval
  ueber mehrere Re-Trigger-Generationen hingeschoben werden,
  bis der Lock frei wird. Akzeptiert: Hotelbetrieb mit 45 Zimmern
  + maximal 2 Vickis je Raum erzeugt keine relevante Last.
- Lock-Schluessel global pro Raum: zwei Sub-Operationen am
  selben Raum (z.B. Reading-Trigger + Beat-Tick) blockieren
  sich auch dann gegenseitig, wenn sie semantisch unabhaengig
  waeren. Akzeptiert wegen einfacher Mechanik.

**Konsequenzen.** ``services/engine_lock.py`` (Singleton-Helper,
``try_acquire`` / ``release``); ``celery_app.py``-Kommentar
ersetzt den 9.6-Hinweis durch Verweis auf AE-40; Backlog-Eintrag
B-9.10-4 (vorab in T3-Bericht angedacht) entfaellt — ist gefixt.

**Worker-Crash-Recovery.** Wenn ein Worker zwischen Lock-Acquire
und ``try``/``finally``-Release crasht (OOM, Container-Kill,
SIGKILL, Power-Loss), raeumt Redis den Lock nach TTL=30 s
automatisch auf. Der naechste Trigger fuer denselben ``room_id``
laeuft dann durch. Damit ist der Lock selbstheilend, ohne
externes Cleanup-Skript oder Watchdog.

---

## AE-41 · Stabilitaet als oberste Systemregel + Autonomie-Default fuer Claude Code (Sprint 9.10b)

**Status.** Akzeptiert, 2026-05-07.

**Kontext.** Waehrend Sprint 9.10 (Window-Detection) wurde eine
bestehende, undokumentierte Race-Condition-Luecke
(``celery_app.py:60-61`` dokumentierte die Mitigation als
erforderlich, sie war aber nicht implementiert) durch T3
(Reading-Trigger) scharf. Die Diskussion zeigte, dass Stabilitaet
als Prinzip nicht explizit verankert war und dass Sprint-Reviews
durch zu viele Yes-Klicks auf Routine-Schritte verwaessert wurden,
statt sich auf substantielle Entscheidungen zu konzentrieren.

**Entscheidung.**
1. Stabilitaet wird als oberste Systemregel in CLAUDE.md §0
   festgeschrieben — sechs operative Regeln S1-S6 plus
   Eskalations-Regel.
2. Claude Code erhaelt in CLAUDE.md §0.1 einen Autonomie-Default
   (Stufe 2): Auto-Continue fuer Routine, Pflicht-Stops bei
   substantiellen Entscheidungen. Sprints koennen abweichende
   Stufen 1 (volle Stops) oder 3 (volle Autonomie) explizit
   setzen.
3. Strategie-Chat und Sprint-Plaene pruefen aktiv gegen S1-S6.

**Konsequenzen.**
+ Race-Conditions, Doku-Drifts, TODO-Kommentare in Steuerlogik
  werden gefixt, nicht verschoben (S1).
+ Idempotenz und Determinismus sind Pflicht, nicht Optimierung
  (S2).
+ Engine-Trace ist Single Source of Truth fuer Setpoint-
  Aenderungen (S3).
+ Hardware-Schutz vor doppelten/widerspruechlichen Befehlen ist
  verbindlich (S4).
+ Defensive bei externen Quellen (PMS, IoT) statt Annahmen (S5).
+ Feature-Komplexitaet traegt Beweislast — im Zweifel einfacher
  (S6).
- Sprints koennen sich verlaengern, wenn S1-S6 das verlangen.
- Yes-Klick-Frequenz im Claude-Code-Workflow sinkt durch Stufe-2-
  Default; Aufmerksamkeit konzentriert sich auf Substanz statt
  Routine.

**Querverweise.**
- CLAUDE.md §0 (Stabilitaetsregeln)
- CLAUDE.md §0.1 (Autonomie-Default)
- CLAUDE.md §5.20 (Aspirative Kommentare als Doku-Drift)
- AE-40 (Engine-Task-Lock — konkreter Anlass-Fall fuer S1)

---

## AE-42 — Frostschutz pro Raumtyp (zurückgestellt 2026-05-11)

**Entscheidung:** Frostschutz bleibt systemweit
`FROST_PROTECTION_C = Decimal("10.0")` in
`backend/src/heizung/rules/constants.py`. Engine-Layer 0, 4, 5 lesen
die Konstante direkt, ohne Helper.

Pro-Raumtyp-Override wurde 2026-05-07 entworfen (siehe Historie unten),
aber 2026-05-11 zurückgestellt: kein realer Frostschaden-Fall im Hotel
Sonnblick, kein Hotelier-Bedarf, S6 zieht. Wenn das Feature später
kommt, ist der Migrations-Pfad klein und additiv:

- Migration: `room_type.frost_protection_c NUMERIC(4,1) NULL`
- Helper: `_resolve_frost_protection(room_type)` in `engine.py`
- Layer 0, 4, 5 rufen Helper statt Konstante
- Pydantic-Field optional in `RoomTypeUpdate`-Schema
- UI-Feld in `/raumtypen/[id]`-Form

Bis dahin gilt: untere Grenze ist die Konstante, nicht konfigurierbar.

**Historie 2026-05-07 (zur Nachvollziehbarkeit der zurückgestellten
Variante):** Cowork-Inventarisierung Betterspace zeigte, dass untere
Temperaturgrenzen pro Raumtyp differenziert werden (Bad mit
Handtuchwärmer vs. Flur, Cowork S107 Use-Case 7). Entworfen war eine
zweistufige Modellierung — Hard-Cap im Code plus optionaler
Raumtyp-Override `room_type.frost_protection_c NUMERIC(4,1) NULL` mit
`MAX(HARD_CAP, room_type.frost_protection_c)` als effektivem Wert.
Strategie-Chat-Review 2026-05-11 hat die Option geprüft und bewusst
zurückgestellt — nicht vergessen, sondern aktivierbar bei konkretem
Bedarf.

**Status:** zurückgestellt 2026-05-11, später aktivierbar
**Bezug:** STRATEGIE.md §6.2 R8 (globale Konstante),
ARCHITEKTUR-REFRESH §2.1 (Update-Box 2026-05-11)

---

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

---

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

---

## AE-45 — Device-Auto-Detect-Override-Mechanismus (2026-05-09)

**Kontext:** Während Sprint 9.11 Live-Test #2 wurde beobachtet, dass die `manual_override`-Tabelle automatisch Einträge mit `source=device`, `reason="auto: detected user setpoint change"` und `expires_at=now+7days` erhält. Der Mechanismus war im Strategie-Chat-Kontext nicht dokumentiert. Bekannt waren nur die `frontend_*`-Override-Quellen aus Sprint 9.9.

**Beobachtetes Verhalten:**

1. Wenn Vicki einen Setpoint zurückmeldet, der nicht zur Engine-Erwartung passt (z. B. weil Gast am Drehrad gedreht hat), schreibt das System einen `manual_override` mit `source=device` und `expires_at` +7 Tage.
2. Beim Anlegen des Auto-Overrides werden bestehende `frontend_*`-Overrides auf demselben Raum auto-revoked.
3. Layer 3 (`manual_override`) behandelt Auto-Override und Frontend-Override identisch — beide werden als `reason=manual` durchgereicht.
4. Das Frontend-Engine-Decision-Panel zeigt source-Information im Detail-Text („Drehknopf, läuft ab in 6T 23h"), aber nicht im reason-Token.

**Entscheidung:** Der Mechanismus wird als gewollt akzeptiert und in diesem ADR verankert. Begründung:

- Wenn Gast am Vicki dreht, ist seine Absicht klar: Komfort-Wunsch.
- 7-Tage-Cap ist defensiv — länger als Frontend (4h), aber nicht unbegrenzt.
- Auto-Revoke alter Frontend-Overrides verhindert widersprüchliche Setpoints (S4 Hardware-Schutz).

**Konsequenzen:**

- Engine-Trace muss source-Differenzierung sichtbar machen, damit Hotelier zwischen API-Setting und Hardware-Eingriff unterscheiden kann. Backlog B-9.11-1 + B-9.11-3 (Trace-Reason-Sub-Tokens `manual_frontend` / `manual_device`).
- RUNBOOK §10d zukünftig (Sprint 9.13 Pairing-UI) erweitern um Hardware-Override-Verhalten.
- Sprint 9.17 (NextAuth) sollte Audit-Trail für Auto-Override-Erkennung berücksichtigen — wer/wann hat am Vicki gedreht?
- Bestehender Code-Pfad muss noch lokalisiert werden — Quellcheck als Pflicht-Vorgehen für Sprint 9.13 Pairing-UI (Trace-UI braucht source-Differenzierung).

**Status:** akzeptiert
**Verstärkt:** Sprint 9.9 manual_override (Sub-Reasons fehlen heute)

---

# AE-47 Window-Detection: Hardware-First mit passiver Backend-Diagnose

**Datum:** 2026-05-09
**Status:** Beschlossen
**Bezug:** Sprint 9.11 Live-Test #2, docs/vendor/mclimate-vicki/

## Problem

Sprint 9.11 Live-Test hat gezeigt, dass die MClimate-Vicki openWindow im Hotelbetrieb nicht zuverlässig sendet. Cowork-Diagnose eliminiert Codec und Backend; Hersteller-Doku-Recherche identifiziert zwei harte Fakten:

1. **Open-Window-Detection ist im Vicki-Default DISABLED.** Wir haben nie via Downlink aktiviert. Funktion lief seit Inbetriebnahme nicht.
2. **Selbst aktiviert ist Erkennung laut MClimate „not 100% reliable".** Interner Vicki-Sensor wird durch HK-Wärme dominiert; bei aktiver Heizung kompensiert das Ventil den Raumluft-Sturz schneller als der Algorithmus ihn erkennt.

A/B-Test 2026-05-09 mit Vicki-001 (am HK) und Vicki-003 (passiv neben HK gelegt, kein Ventil-Anschluss) bei Außentemp ~18 °C: beide Devices verharren auf 18 °C-Niveau, Vicki-Algorithmus triggert nicht. Im Sommer und in der Heizung-Aus-Periode ist der Hardware-Pfad physikalisch nicht testbar.

## Entscheidung

Hardware-First-Strategie mit drei Trigger-Quellen, davon zwei aktiv und eine passiv:

### Aktive Trigger (verändern Setpoint)

**1. Vicki openWindow-Flag**

- In Sprint 9.11x via Downlink `0x4501020F` aktiviert (FW >= 4.2)
- Parameter: enabled, 10 Min Ventil zu, 1.5 °C Delta in 1 Min
- Bei `openWindow=true` → Layer 4 setzt Frostschutz, reason `open_window`

**2. attached_backplate=false**

- Codec liefert das Feld seit Vicki-FW 4.1 verlässlich
- Sprint 9.11x persistiert in `sensor_reading.attached_backplate`
- Bei zwei aufeinanderfolgenden Frames mit `attached=false` → Layer 4 setzt Frostschutz, reason `device_detached`
- Hysterese (2 Frames) gegen Sensor-Schalter-Wackler

### Passiver Trigger (nur Diagnose, kein Setpoint-Effekt)

**3. inferred_window via Backend-Algorithmus**

- Helper berechnet Δ Raumluft >= 0.5 °C in 10 Min bei stehendem Heizungs-Setpoint
- **Schreibt nur ins `event_log`** als Wartungs-Event-Kandidat (Sprint 9.11y)
- Layer 4 reagiert NICHT auf diesen Trigger
- Wenn der Trigger wiederholt feuert (z. B. 3× in 30 Min im selben Raum) ohne dass Vicki-Trigger kam → Hinweis auf Hardware-Schwäche der Vicki, nicht auf Setpoint-Bedarf

## Begründung

S2 (Determinismus) und S6 (Komplexität trägt Beweislast) verbieten unklare Multi-Trigger-Logiken in der Steuerlogik. OR-Verknüpfung mehrerer Trigger erhöht Falsch-Positiv-Risiko (Setpoint springt auf Frostschutz wegen Lufthauch / vorübergehender Tür-Öffnung) und Komfort-Verlust beim Gast. Hardware-Trigger sind Fakten (Vicki-Algorithmus, Backplate-Schalter), Backend-Algorithmus ist Inferenz. Inferenz darf beobachten, aber nicht steuern, bevor sie sich produktiv bewährt hat.

## Verworfen

- **OR-Verknüpfung aller drei Trigger als Setpoint-Quelle:** S2/S6-Verstoß
- **Reine Vicki-Konfiguration ohne Backend-Inferenz:** verschwendet Daten, blockiert spätere Diagnose
- **Reine Backend-Inferenz ohne Vicki-Aktivierung:** Hardware-Pfad bliebe blind, schneller Trigger fehlt

## Konsequenzen

- Sprint 9.11x liefert die Hardware-Quick-Wins (Vicki-Aktivierung + Backplate-Bit-Persistenz)
- Sprint 9.11y liefert Backend-Synthetic-Test (deterministisch via pytest mit künstlichen `sensor_reading`-Inserts) plus passiven Backend-Logger
- BR-16 verschoben in Heizperiode: aktive Eigenlogik-Trigger erst nach 2 Wochen produktiver Beobachtung neu bewerten
- Hardware-Kältepack-Test als manuelles Verfahren in RUNBOOK §10e (Vicki im Tiefkühlfach 5 Min → Sturz 18 → 4 °C → Vicki triggert)

## Test-Strategie für Heizung-Aus-Perioden

Im Sommer / bei Außentemp >= 15 °C ist der Vicki-Hardware-Algorithmus physikalisch nicht testbar. Test-Pfade:

1. **Backend-Synthetic-Test (pytest):** SQL-Inserts in `sensor_reading` mit künstlichem Δ-T, Layer-4-Output asserted. Deterministisch, in CI lauffähig, jederzeit. — Sprint 9.11y T1.
2. **Hardware-Kältepack-Test:** Vicki im Tiefkühlfach 5 Min, dokumentiert im RUNBOOK §10e. Manuelles Akzeptanz-Verfahren, kein Sprint-Task.
3. Codec-Spoofing in ChirpStack: **verworfen** wegen Drift-Risiko (§5.21/§5.22).

## Referenzen

- `docs/vendor/mclimate-vicki/01-open-window-detection.md`
- `docs/vendor/mclimate-vicki/03-firmware-release-notes.md`
- `docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md`
- CLAUDE.md §5.27 (neue Lesson aus diesem Befund)
- Sprint 9.11x, 9.11y in SPRINT-PLAN.md

---

# AE-48 Vicki-Downlink-Helper-Architektur (Hybrid)

**Datum:** 2026-05-09
**Status:** Beschlossen
**Bezug:** Sprint 9.11x.b, `downlink_adapter.py`, AE-47

## Problem

Sprint 9.11x.b benötigt drei neue Vicki-Downlinks (FW-Get `0x04`, Open-Window-Set `0x4501020F`, Open-Window-Get `0x46`). Bisher existiert nur ein hartcodierter Setpoint-Sender (`0x51`) in `backend/src/heizung/services/downlink_adapter.py`. Die Frage: Wie erweitern, ohne den bestehenden Pfad zu zerstören und ohne pro Command eine eigene Architektur einzuführen.

Bestehende Repo-Realität:

- `send_setpoint(dev_eui, setpoint_c)` → MQTT-Publish auf `application/{app_id}/device/{dev_eui}/command/down`
- Payload: base64-encoded bytes, fPort=1, confirmed=False
- Aufrufer: `backend/src/heizung/tasks/engine_tasks.py`
- Kein gRPC-Client, `CHIRPSTACK_API_KEY` leer

## Entscheidung

**Hybrid-Helper:** ein generischer Low-Level-Helper plus drei dünne typisierte Wrapper.

### Low-Level (neu)

```python
async def send_raw_downlink(
    dev_eui: str,
    payload_bytes: bytes,
    fport: int = 1,
    confirmed: bool = False,
) -> str:
    """MQTT-Publish auf ChirpStack-Downlink-Topic. Return: published
    payload-id (für Trace)."""
```

Ziel: ein einziger Pfad zur ChirpStack-MQTT-Queue. Setpoint wird intern auf diesen Helper umgestellt (kein Verhalten-Change, nur Refactor).

### Wrapper (typsicher, Domain-Sprache)

```python
async def query_firmware_version(dev_eui: str) -> None:
    """Sendet 0x04. Antwort kommt asynchron als Uplink mit cmd 0x04 + 4
    Bytes (HW major/minor + FW major/minor)."""

async def set_open_window_detection(
    dev_eui: str,
    enabled: bool,
    duration_min: int = 10,
    delta_c: Decimal = Decimal("1.5"),
) -> None:
    """Sendet 0x45 {enabled} {duration_min/5} {round(delta_c*10)}.
    FW-Voraussetzung: >= 4.2 (0.1 °C-Resolution-Variante).
    delta_c MUSS Decimal sein (harte Regel: keine Floats für
    Temperaturen)."""

async def get_open_window_detection(dev_eui: str) -> None:
    """Sendet 0x46. Antwort kommt asynchron als Uplink mit cmd 0x46 + 3
    Bytes."""
```

### Konventionen

- **Byte-Konvertierung intern.** Aufrufer übergeben Domain-Werte (Decimal-Celsius, Minuten, Bool), Helper rechnet auf Hardware-Format.
- **Keine confirmed Downlinks** für diese drei Commands. Antwort kommt als Uplink, nicht als ACK. (Setpoint bleibt unverändert `confirmed=False` — bestehender Vertrag.)
- **fPort=1** für alle drei (MClimate-Konvention, im bestehenden Encoder bereits gesetzt).
- **Logging analog `send_setpoint`:** `logger.info` mit `dev_eui` + cmd-byte als extra für Trace-Korrelation.

### Codec-Erweiterung (parallel)

Damit ChirpStack-Application-Layer auch eigenständig sendet (z. B. via UI im Notfall), wird `encodeDownlink` im Codec `infra/chirpstack/codecs/mclimate-vicki.js` um drei Commands erweitert:

- `input.data.query_firmware_version === true` → `[0x04]`
- `input.data.set_open_window_detection: {enabled, duration_min, delta_c}`
- `input.data.get_open_window_detection === true` → `[0x46]`

Codec-Encoder ist Spiegel des Backend-Helpers, NICHT die primäre Quelle. Zwei Implementierungen sind eine Drift-Quelle (siehe Lesson §5.22). Mitigation: Codec wird in Sprint 9.11x.b mitaktualisiert UND der Backend-Helper bekommt einen pytest, der gegen die identischen Erwartungs-Bytes asserted. Falls die zwei jemals divergieren, fällt der Test um.

## Begründung

S6 (Komplexität trägt Beweislast):

- Generic-Helper allein → Aufrufstellen kryptisch (raw bytes + magic numbers)
- Drei spezifische Helper allein → Boilerplate, kein gemeinsamer Test-Pfad für MQTT-Publish-Mechanik
- Hybrid → Aufrufstellen lesbar, MQTT-Mechanik einmal getestet, Wrapper-Tests nur Byte-Encoding

S2 (Determinismus + Idempotenz):

- Wrapper sind reine Funktionen mit Decimal-Input → identische Bytes bei gleichem Input, getestbar via pytest mit Decimal-Edge-Cases
- `Decimal("1.55")` wird zu `round(15.5) = 16` → 1.6 °C-Schwelle. Test deckt das explizit ab (Backlog-Item B-9.11x.b-1: Doku in RUNBOOK §10e zur Rundungs-Charakteristik).

S4 (Hardware-Schutz):

- Keine confirmed Downlinks für Get/Set-Konfig — Antwort kommt asynchron, kein Doppelversand
- Bulk-Aktivierung der 4 Vickis als One-Shot-Skript, nicht in Engine-Loop

## Verworfen

- **gRPC-Client einführen:** Aufwand >> Nutzen. ChirpStack-MQTT-Pfad läuft, gRPC würde neue Auth (`CHIRPSTACK_API_KEY`-Bootstrap) und neue Bibliothek erfordern. Kein operativer Vorteil für Downlinks.
- **Drei spezifische Helper ohne Generic-Layer:** Boilerplate + duplizierte MQTT-Mechanik. Nicht S6-konform.
- **Generic-Helper ohne Wrapper:** Aufrufer müssten Hex-Bytes bauen, Tests pro Aufrufer wiederholt — nicht S2-/S6-konform.

## Konsequenzen

- Sprint 9.11x.b implementiert AE-48 vollständig
- Bestehender `send_setpoint` wird auf `send_raw_downlink` umgestellt (Refactor ohne Verhalten-Change, mit Test-Schutz)
- CLAUDE.md neue Lesson: Downlink-Pfad ist MQTT-basiert via `downlink_adapter.py`, NICHT gRPC
- Backlog B-9.11x.b-1: Decimal-Rundungs-Charakteristik in RUNBOOK §10e dokumentieren

## Referenzen

- `backend/src/heizung/services/downlink_adapter.py` (bestehender 0x51-Pfad)
- `backend/src/heizung/services/mqtt_subscriber.py` (Uplink-Subscriber für FW-Antwort-Parsing in Sprint 9.11x.b T6)
- `infra/chirpstack/codecs/mclimate-vicki.js` (Encoder-Spiegel)
- `docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md` (Hex-Definitionen)
- AE-47 (Window-Detection-Hybrid, der diese Helper braucht)
