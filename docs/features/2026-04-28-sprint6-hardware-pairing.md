> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprint 6 — Hardware-Pairing + Test-Server-LoRaWAN-Deploy

**Typ:** Hardware / Infrastruktur / Operations
**Ziel:** Milesight UG65 Gateway im Hotel-LAN, ChirpStack-Stack auf `heizung-test` deployed, erstes echtes MClimate-Vicki-Pairing mit dekodierten Werten in der TimescaleDB.
**Branch:** `feat/sprint6-hardware-pairing`
**Geschaetzte Dauer:** 6–10 h, davon ~3 h Repo-Arbeit, ~3 h Hardware/Pairing, ~30 Min Doku/PR.

---

## Feature-Brief (Phase 1)

### Ausgangslage
- Sprint 5 hat ChirpStack v4 + Mosquitto + FastAPI-MQTT-Subscriber lokal lauffaehig gemacht. Pipeline mit Mock-Uplink validiert.
- Hardware (Milesight UG65, mindestens ein MClimate Vicki) ist physisch verfuegbar, Gateway noch NICHT im Hotel-LAN.
- Test-Server `heizung-test.hoteltec.at` lauft produktiv, hat aber die LoRaWAN-Komponenten noch nicht ausgerollt.

### Ziel — End-State Sprint 6

```
[MClimate Vicki, real]
        |  LoRaWAN (EU868)
        v
[Milesight UG65, Hotel-LAN, statische IP]
        |  Basic Station (TLS-WebSocket)
        v
[Caddy auf heizung-test, cs-test.hoteltec.at, Basic-Auth + LE]
        |  reverse_proxy chirpstack:8080
        v
[ChirpStack v4]
        |  MQTT (intern, ACL-protected)
        v
[Mosquitto] -- subscribed by --> [FastAPI MQTT-Subscriber]
                                        |
                                        v
                                [TimescaleDB sensor_reading]
                                        |
                                        v
                       [GET /api/v1/devices/{id}/sensor-readings]
```

### Architektur-Entscheidungen (verbindlich)

**Entscheidung G — Gateway-Network:**
UG65 per Ethernet im Hotel-LAN, statische IP per DHCP-Reservation oder direkter Konfiguration. KEIN LTE, KEIN WLAN. Begruendung: Stabilitaet, keine Mobilfunkkosten, reproduzierbares Setup.

**Entscheidung H — Gateway-Protokoll:**
Basic Station (LNS-Protokoll, TLS-WebSocket auf Port 443). KEIN klassisches Semtech UDP Packet-Forwarder. Begruendung: ChirpStack-v4-Standard, verschluesselte Verbindung, kein UDP-Port-Forwarding noetig, Gateway-Authentifizierung ueber Zertifikate.

**Entscheidung I — ChirpStack-UI-Zugriff:**
Eigene Subdomain `cs-test.hoteltec.at`, Caddy-Reverse-Proxy mit Basic-Auth-Schutz. KEIN public ohne Auth. KEIN Tailscale-only (Service vom Hotel aus muss komfortabel moeglich sein). Begruendung: erreichbar via Browser von ueberall, sicher genug fuer Test-Stage, Production-Hardening (mTLS, IP-Allowlist) erst wenn relevant.

**Entscheidung J — MQTT-Auth auf Test-Server:**
Mosquitto mit `passwd` + `acl`-Datei aktiv. Linux-Bind-Mount hat keine Permission-Probleme (Sprint-5-Lokal-Workaround mit `allow_anonymous` war Windows-spezifisch). Zwei Users: `chirpstack` (publish auf `application/#`), `heizung-api` (subscribe auf `event/up`).

### Akzeptanzkriterien

- [ ] DNS A-Record `cs-test.hoteltec.at` -> `157.90.17.150` in Hetzner konsoleH
- [ ] `docker-compose.prod.yml` um `mosquitto`, `chirpstack-postgres`, `chirpstack` erweitert; auf heizung-test deployed
- [ ] Caddy-Konfig (`Caddyfile.test`) routet `cs-test.hoteltec.at` mit Basic-Auth auf `chirpstack:8080`, LE-Zertifikat gezogen
- [ ] Mosquitto auf Test-Server mit `passwd` + `acl` aktiv (kein anonymous, MQTT-Port nur intern im Docker-Network)
- [ ] ChirpStack auf Test-Server initialisiert: Tenant „Hotel Sonnblick", Application „heizung", DeviceProfile „MClimate Vicki", Gateway `simulator-gw-1` umbenannt zu echtem UG65
- [ ] UG65 mit statischer IP im Hotel-LAN, Basic Station-Endpoint `wss://cs-test.hoteltec.at:443/api/gateway/`, Status in ChirpStack-UI „Online, last seen vor X Sek"
- [ ] Erstes physisches Vicki via OTAA gepairt; OTAA-Join in ChirpStack-UI sichtbar
- [ ] Erster echter Vicki-Uplink: dekodierte Werte (Battery, Temp, Setpoint) im ChirpStack-UI sichtbar UND in `sensor_reading`-Tabelle persistiert
- [ ] `GET /api/v1/devices/{id}/sensor-readings` (auf Test-Server, intern via Tailscale getestet) liefert das echte Reading
- [ ] Hersteller-Codec abgeglichen — falls unser vereinfachter Codec daneben liegt, der MClimate-Codec nachgezogen
- [ ] STATUS.md Abschnitt 2h, RUNBOOK §10 erweitert um Production-Setup + Gateway-Konfiguration
- [ ] Tag `v0.1.6-hardware-pairing` gesetzt

### Abgrenzung — NICHT Teil von Sprint 6

- Kein Roll-out auf alle 45 Zimmer (das ist Sprint 8+, nach Komfort-Setup-Workflow)
- Keine Rollout-Automatisierung (Bulk-Provisioning-Skript) — Sprint 7+
- Keine Regel-Engine (8 Kernregeln) — Sprint 7
- Kein Frontend-Dashboard fuer Readings — Sprint 8
- Kein Downlink-Pfad (Set Target Temperature) — Sprint 7 mit Regel-Engine
- Kein Main-Server-Deploy — kommt nach erfolgreichem Test-Server-Pilot
- Keine Multi-Gateway-Strategie — fuer 45 Zimmer reicht ein UG65 in den meisten Hotels, Reichweite wird mit dem ersten Pilot-Vicki getestet

### Risiken

1. **UG65-Firmware zu alt:** Basic Station setzt Firmware 60.0.0.30+ voraus. Bei aelterer Firmware: erst lokales Firmware-Update via Web-UI (~30 Min, Reboot).
2. **Hotel-Switchport / Strom:** Gateway braucht entweder PoE+ (802.3at, 30 W) oder externes 12 V DC-Netzteil. Vorab pruefen, sonst Mehraufwand vor Ort.
3. **LoRaWAN-Reichweite im Stahlbeton:** Hotel-Hauswaende daempfen 868 MHz. Erste Vicki sollte nicht weiter als ein Stockwerk vom Gateway entfernt sein. Reichweite-Optimierung (Antennenposition, ggf. 2. Gateway) ist Folge-Sprint.
4. **Vicki Deep-Sleep:** Manche Vicki kommen aus dem Karton in Deep-Sleep, Magnet oder Tasterdruck noetig zum Aktivieren. MClimate-Anleitung mitnehmen.
5. **Codec-Mismatch:** Unser vereinfachter Codec (Sprint 5) basiert auf der gaengigen Vicki-Status-Frame-Struktur. Echte Firmware kann zusaetzliche Felder oder andere Bit-Layouts liefern. Plan: bei Mismatch den offiziellen MClimate-JS-Codec aus dem Developer-Hub ziehen und ersetzen.
6. **Basic-Station-Zertifikat:** TLS-WebSocket verlangt Server-Zertifikat (LE bringt Caddy automatisch) PLUS optional Client-Zertifikat. Wir starten ohne Client-Zert (ChirpStack akzeptiert Gateway via DevEUI-Identifikation), spaeter ggf. mTLS.
7. **Mosquitto-passwd auf Linux:** sollte sauber funktionieren (Sprint-5-Problem war Windows-Bind-Mount-spezifisch). Bei Permission-Issues: `chmod 0640` + `chown 1883:1883` auf der passwd-Datei.
8. **Caddy-Basic-Auth-Hash:** bcrypt-Hash via `caddy hash-password` lokal generieren, nicht das Passwort selbst ins Caddyfile eintragen.

### Rollback

- ChirpStack-Subdomain DNS-Record loeschen, Caddy revertieren auf vorherige Caddyfile-Version, Stack ohne LoRaWAN-Services neu starten
- `docker compose -f docker-compose.prod.yml up -d --remove-orphans` mit dem alten Compose-Stand entfernt die LoRaWAN-Container sauber
- Persistente Volumes (`chirpstack_db`, `mosquitto_data`) bleiben erhalten, Re-Activierung jederzeit ohne Datenverlust moeglich

---

## Sprintplan (Phase 2)

### 6.1 — Feature-Brief (dieses Dokument)
User-Gate.

### 6.2 — DNS + Hotel-LAN-Vorbereitung
**User-Aktion (manuell):**
- A-Record `cs-test.hoteltec.at` -> `157.90.17.150` in Hetzner konsoleH (TTL 300)
- Hotel-LAN: Switchport am Heizungsrack/IT-Schrank suchen, statische IP reservieren (z. B. `192.168.x.50`), PoE-Versorgung (Switch oder PoE-Injector) oder 12 V Netzteil bereitlegen
- DNS-Propagation per `nslookup cs-test.hoteltec.at` verifizieren

**Dauer:** 15 Min DNS, plus Hotel-Begehung.

### 6.3 — docker-compose.prod.yml LoRaWAN-Erweiterung
- Services `mosquitto`, `chirpstack-postgres`, `chirpstack` analog zur Dev-Compose, aber:
  - Mosquitto-Ports nicht public (kein `ports:`-Eintrag, nur internes Docker-Network)
  - Mosquitto mit `passwd` + `acl` (NICHT anonymous)
  - ChirpStack-Port 8080 nicht public, Caddy-Reverse-Proxy davor
- `passwd`-Datei via `mosquitto_passwd`-Container erzeugen, `chmod 0640`, ins Volume mounten

**Dauer:** 1 h.

### 6.4 — Caddy: cs-test.hoteltec.at + Basic-Auth
- `infra/caddy/Caddyfile.test` um zweite Site erweitern:
  ```caddyfile
  cs-test.hoteltec.at {
      basicauth {
          admin <bcrypt-hash>
      }
      reverse_proxy chirpstack:8080
      header Strict-Transport-Security "max-age=31536000"
  }
  ```
- Basic-Auth-Hash lokal mit `docker run --rm caddy:2 caddy hash-password` generieren

**Dauer:** 30 Min.

### 6.5 — Test-Server-Deploy + ChirpStack-Init
- Auf `heizung-test`: `git pull`, `docker compose -f docker-compose.prod.yml up -d`
- ChirpStack-DB auto-initialisiert (pg_trgm via Init-Skript)
- ChirpStack-UI auf `https://cs-test.hoteltec.at` (Basic-Auth)
- Tenant + Application + DeviceProfile + Codec wie lokal anlegen (oder spaeter via Bootstrap-Skript)

**Dauer:** 1 h, davon ~5 Min Caddy-Cert-Acquire.

### 6.6 — UG65 Gateway-Konfiguration
- Strom + Ethernet anschliessen, UG65 Web-UI ueber statische IP erreichen (Default `192.168.1.1` oder per DHCP-Lease)
- Login `admin` / `password` (Default, sofort aendern)
- Statische IP setzen, NTP-Server konfigurieren
- Firmware-Version pruefen, ggf. updaten
- Packet-Forwarder-Modus auf **Basic Station** stellen
- LNS-Endpoint `wss://cs-test.hoteltec.at:443/api/gateway/`
- Gateway-EUI in ChirpStack registrieren (UI: Tenant -> Gateways -> Add)
- Test: Gateway in ChirpStack-UI „Online, last seen wenige Sek"

**Dauer:** 1.5 h, davon evtl. 30 Min Firmware-Update.

### 6.7 — Vicki-Pairing
- Vicki Reset/Aktivieren (Magnet oder Reset-Knopf laut MClimate-Anleitung)
- DevEUI + AppKey aus dem Vicki-Aufkleber oder MClimate-Lieferantenliste
- In ChirpStack: Application „heizung" -> Devices -> Add (DevEUI, Profile = Vicki, AppKey)
- Auf OTAA-Join warten (typisch < 30 Sek nach Aktivierung)
- Erster Uplink (typisch < 5 Min nach Join, je nach Vicki-Default-Reporting-Interval)

**Dauer:** 30 Min plus iteriert je nach Hardware-Verhalten.

### 6.8 — Codec-Validierung gegen Realdaten
- ChirpStack-UI: Live-Frames -> dekodierte JSON-Felder checken
- Vergleich gegen unseren Codec (`infra/chirpstack/codecs/mclimate-vicki.js`)
- Bei Abweichung: offiziellen MClimate-Codec ziehen, ersetzen, DeviceProfile updaten
- TimescaleDB-Side: `SELECT * FROM sensor_reading WHERE device_id = ... ORDER BY time DESC LIMIT 5`

**Dauer:** 30–60 Min, je nach Codec-Drift.

### 6.9 — Doku + PR + Tag
- STATUS.md Abschnitt 2h
- RUNBOOK §10 erweitert um Production-Setup-Schritte + Gateway-Konfiguration
- ADR AE-19 (Basic Station als Protokoll), AE-20 (Caddy-Subdomain mit Basic-Auth)
- PR `feat/sprint6-hardware-pairing -> main`, CI grün, Squash-Merge, Tag `v0.1.6-hardware-pairing`

**Dauer:** 30 Min.

---

## Phase-Gates

- **Gate 1+2 (jetzt):** Feature-Brief + Sprintplan freigegeben
- **Gate 3 (nach 6.5):** ChirpStack-UI auf `cs-test.hoteltec.at` per Browser erreichbar, Login durch
- **Gate 4 (nach 6.6):** Gateway in ChirpStack als „Online" sichtbar
- **Gate 5 (nach 6.7+6.8):** Echtes Vicki-Reading in `sensor_reading`-Tabelle
- **Gate 6 (nach 6.9):** Tag gesetzt, Test-Server stabil, Doku synchron

---

## Offene Fragen / Annahmen

- **[Annahme]** UG65-Default-Login `admin` / `password` ist noch aktiv. Falls geaendert: Reset-Taster druecken (15 Sek halten) oder neu beschaffen.
- **[Annahme]** Hotel-Switch unterstuetzt PoE+ ODER es gibt einen 12V-Netzteilanschluss am UG65-Aufstellort.
- **[Annahme]** Vicki-Lieferung enthaelt DevEUI/AppKey-Liste oder einen QR-Code zum Auslesen. Falls nicht: MClimate-Support kontaktieren.
- **[Annahme]** Hotel-LAN hat keinen restriktiven Egress-Firewall — Outbound TCP/443 von `heizung-test`-IP-Range ist erreichbar. Wenn Hotel-IT eine Whitelist verlangt: IP/Hostname `cs-test.hoteltec.at` (157.90.17.150:443) freischalten lassen.
- **[Annahme]** Vicki-Codec aus Sprint 5 trifft das echte Frame-Format. Falls nicht, passen wir in 6.8 an. Worst-Case: 1 h Codec-Aufwand.
