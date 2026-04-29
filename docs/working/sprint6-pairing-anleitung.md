# Sprint 6 — Pairing-Anleitung fuer morgen (2026-04-29)

**Letzte Aktualisierung:** 2026-04-28 abend.
**Stand:** Server-Stack komplett vorbereitet, Pairing fehlt noch.

## Was schon fertig ist

- ChirpStack v4 + Mosquitto + Gateway-Bridge auf `heizung-test` produktiv
- `cs-test.hoteltec.at` mit TLS, ChirpStack-UI Login `admin/<starkes-pw>`
- Tenant „Hotel Sonnblick" (mit Can-have-gateways), Application „heizung", DeviceProfile „MClimate Vicki" mit JS-Codec
- Basic-Station-Endpoint via Caddy: `wss://cs-test.hoteltec.at:443/router-info`
- End-to-End-Mock-Pipeline auf Test-Server bewiesen
- Devices-CRUD-API: `POST /api/v1/devices` ist morgen die Methode der Wahl, statt SQL-INSERT

## Vor dem IT-Termin (User-Aktion)

- DevEUI + AppKey vom Vicki-Aufkleber notieren (oder MClimate-Liste haben)
- ChirpStack-UI offen lassen (`https://cs-test.hoteltec.at`)
- SSH-Terminal auf `heizung-test` offen halten

## 6.6 — UG65 Gateway konfigurieren (mit IT-Mitarbeiter)

### 6.6.1 IT bringt das Gerät online
- MAC-Adresse, statische IPv4, Stromart vom IT bekommen
- IT verbindet UG65 mit Hotel-LAN

### 6.6.2 UG65 Web-UI (vom Hotel-LAN aus oder via Tailscale-Bridge)
- Browser auf statische IP des Gateways
- Default-Login `admin/password`, sofort aendern auf starkes Passwort
- **Network**: statische IP konfigurieren (falls noch DHCP)
- **System → NTP**: `pool.ntp.org` oder `at.pool.ntp.org`
- **Firmware-Version pruefen**: muss >= 60.0.0.30 fuer Basic Station. Bei aelteren: ueber Web-UI updaten (~30 Min Reboot)
- **LoRaWAN → Gateway**:
  - Mode: **Basic Station**
  - Server URI: `wss://cs-test.hoteltec.at:443/router-info`
  - Trust-Store: System-CAs (Let's Encrypt) — das default funktioniert
  - Save & Apply
- **Gateway-EUI ablesen** (vom Aufkleber oder im Web-UI unter Status)

### 6.6.3 Gateway in ChirpStack registrieren
- ChirpStack-UI → Tenant „Hotel Sonnblick" → Gateways → **+ Add gateway**
- Name: `ug65-3og` (oder beschreibend)
- Description: `Milesight UG65, 3. Stock`
- Gateway ID (EUI64): vom UG65-Aufkleber
- Stats interval: 30
- Region: eu868
- Submit
- **Gate 4:** Gateway-Liste zeigt nach 30–60 Sek „Last seen: wenige Sek"

## 6.7 — Vicki pairen

### 6.7.1 Device anlegen in ChirpStack
- Tenant „Hotel Sonnblick" → Applications → `heizung` → Devices → **+ Add device**
- Name: `vicki-zimmer-301` (oder Test-Zimmer)
- Description: `MClimate Vicki, Erstpilot`
- Device EUI: vom Vicki-Aufkleber (16 hex)
- Join EUI: meist `0000000000000000` oder vom Aufkleber
- Device profile: `MClimate Vicki`
- Submit
- Tab **OTAA keys** → Application key (vom Aufkleber, 32 hex) → Submit

### 6.7.2 Vicki aktivieren
- Magnet kurz an die Markierung halten ODER Reset-Knopf drücken (siehe MClimate-Anleitung)
- Im ChirpStack-UI: Device → Tab **LoRaWAN frames** offen lassen
- Innerhalb von 30 Sek sollte ein **Join Request** + **Join Accept** erscheinen
- Wenig später (typisch < 5 Min): erster Uplink mit decoded `object`

### 6.7.3 Device in Heizung-DB anlegen
**SSH heizung-test:**
```bash
DEV_EUI="<vom-aufkleber-lowercase>"
APP_EUI="<vom-aufkleber-lowercase-oder-leer>"
curl -s -X POST https://heizung-test.hoteltec.at/api/v1/devices \
  -H "Content-Type: application/json" \
  -d "{\"dev_eui\":\"$DEV_EUI\",\"app_eui\":\"$APP_EUI\",\"kind\":\"thermostat\",\"vendor\":\"mclimate\",\"model\":\"Vicki\",\"label\":\"vicki-zimmer-301\"}"
```
Erwartung: 201 + JSON-Response mit `id`.

## 6.8 — Codec-Validierung

- ChirpStack-UI → Device → LoRaWAN frames → letzten Uplink anklicken
- `object`-JSON anschauen, mit unserem Codec (`infra/chirpstack/codecs/mclimate-vicki.js`) vergleichen
- Felder die wir erwarten: `command`, `battery_voltage`, `temperature`, `target_temperature`, `motor_position`, ...
- **Falls Felder fehlen / falsch dekodiert:**
  - Hersteller-Codec von MClimate-Dev-Hub ziehen (`https://github.com/MClimateBg/lorawan-codecs` oder MClimate-Support fragen)
  - In ChirpStack-UI im DeviceProfile Codec-Tab ersetzen → Submit
  - Naechsten Uplink (15 Min spaeter) verifizieren

**SSH heizung-test:**
```bash
DEV_ID=$(curl -s https://heizung-test.hoteltec.at/api/v1/devices | jq -r '.[] | select(.dev_eui=="<dev-eui>") | .id')
curl -s "https://heizung-test.hoteltec.at/api/v1/devices/$DEV_ID/sensor-readings" | jq .
```
Erwartung: Reading mit `temperature`, `setpoint`, `valve_position`, `battery_percent`, `rssi_dbm`, `snr_db`.

## 6.9 — Sprint 6 abschliessen

- STATUS.md Abschnitt 2h: Sprint-6-Bericht (Hardware, Lessons Learned, ggf. Codec-Anpassung)
- RUNBOOK §10 erweitern: Production-LoRaWAN-Pipeline-Operations
- ADR AE-19 (Basic Station als Gateway-Protokoll), AE-20 (Caddy reverse_proxy fuer WebSocket)
- PR `feat/sprint6-hardware-pairing → main`, CI grün, Squash-Merge
- Tag `v0.1.6-hardware-pairing`
- `main → develop`-Sync-PR

## Troubleshooting (wenn etwas nicht klappt)

| Symptom | Ursache | Fix |
|---|---|---|
| Gateway in ChirpStack-UI „never seen" | Outbound-Firewall blockt 443/wss | Hotel-IT: TCP/443 outbound zu cs-test.hoteltec.at erlauben |
| Gateway „never seen", aber Hotel-Egress offen | UG65-Server-URI falsch | Endpoint pruefen: `wss://cs-test.hoteltec.at:443/router-info`, kein /api-Prefix |
| Caddy-Logs zeigen keine `/router-info`-Requests | DNS auf Gateway falsch | UG65 Network-Settings: DNS-Server pruefen, oeffentlichen DNS einsetzen |
| Vicki-Join kommt nicht | DevEUI/AppKey falsch eingetippt | Aufkleber pruefen, ggf. via App scannen |
| Codec-Output leer / falsch | Vicki-Frame-Format weicht ab | Hersteller-Codec ersetzen (siehe 6.8) |
| Reading kommt in ChirpStack, aber nicht in DB | API-MQTT-Subscriber-Connect-Problem | `docker compose logs api \| grep -i mqtt` auf Server |
