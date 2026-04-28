# Sprint 5 — LoRaWAN-Foundation (Software-Phase)

**Typ:** Backend / Infrastruktur
**Ziel:** Komplette LoRaWAN-Datenpipeline lokal auf `work02` lauffähig — ChirpStack v4 + Mosquitto + chirpstack-simulator + FastAPI-MQTT-Subscriber + TimescaleDB-Hypertable. Hardware-unabhängig, simulierte Uplinks.
**Branch:** `feat/sprint5-lorawan-foundation` (von `main`)
**Geschätzte Dauer:** 6–10 h, aufgeteilt auf 2–3 Sessions.
**Hardware-Sprint folgt:** Sprint 6 — Gateway ins Hotel-LAN, ChirpStack auf `heizung-test` deployen, erstes echtes Pairing.

---

## Feature-Brief (Phase 1)

### Ausgangslage
- MClimate Vicki Heizkörperthermostate physisch da, Milesight UG65 Gateway physisch da, aber **noch nicht im Hotel-LAN** konfiguriert.
- FastAPI-Backend + TimescaleDB laufen produktiv auf beiden Servern (Sprint 0–4).
- Bisher keine LoRaWAN-Pipeline, keine MQTT-Infrastruktur, keine Sensor-Daten in der DB.
- Frontend ist Grundgerüst — Sprint 5 wird Backend-only.

### Architektur-Entscheidungen (verbindlich)

**Entscheidung A — ChirpStack-Hosting:**
Separater Docker-Container in unserer Compose-Stack (NICHT eingebauter LNS im UG65). Begründung: einheitliche Dev-Umgebung, Versionskontrolle, Backup-Strategie, Migration auf zweites Gateway später trivial.

**Entscheidung B — ChirpStack-Datenbank:**
Eigener Postgres-Container (`chirpstack-postgres`), getrennt vom heizung-DB. Begründung: ChirpStack-Schema ist vendor-controlled, eigene Update-Pfade, separate Backup-Strategie. Zusatz-RAM ~150 MB akzeptabel.

**Entscheidung C — MQTT-Broker:**
Eigenständiger Mosquitto v2-Container. ChirpStack publisht Uplinks auf `application/<id>/device/<dev-eui>/event/up`. FastAPI subscribt asynchron. Anonymous-Login deaktiviert; ACL via Passwort-Datei mit getrennten Usern für `chirpstack` (publish) und `heizung-api` (subscribe).

**Entscheidung D — Bridge-Pattern:**
Asyncio-MQTT-Subscriber als Background-Task im FastAPI-Lifespan-Manager (`asgi-mqtt` oder `aiomqtt`). KEIN HTTP-Webhook. Subscribe-Reconnect kostenlos, replay-fähig (QoS 1), mehrere Subscriber Future-proof.

**Entscheidung E — Vicki-Payload:**
Decoder als JS-Codec in ChirpStack-DeviceProfile eingespielt (Hersteller-Codec von MClimate). FastAPI verlässt sich auf das **decodierte JSON** (`object` im Uplink-Event), parst nicht selbst Binary. Reduziert Codec-Logik-Duplikation.

**Entscheidung F — Dev-First, Server später:**
Sprint 5 läuft komplett lokal auf `work02`. Test-Server-Deployment ist Sprint 6 zusammen mit Hotel-LAN-Setup. Begründung: schnelle Iteration ohne GHCR-Build-Pull-Zyklus.

### Ziel — End-State Sprint 5

```
[chirpstack-simulator]         (lokal, Mock-Gateway + Mock-Device)
        │
        ▼ LoRaWAN-Frames simulieren
[chirpstack v4]                (lokal Container)
        │
        ▼ Uplink-Event als JSON
[mosquitto]                    (lokal Container)
        │
        ▼ Topic application/.../event/up
[fastapi-mqtt-subscriber]      (Background-Task)
        │
        ▼ Pydantic-Validierung
[timescaledb hypertable uplinks]
        │
        ▼
[GET /api/v1/devices/{id}/uplinks?from=&to=&limit=]
```

### Akzeptanzkriterien

- [ ] `docker compose up` lokal startet alle 8 Services (api, web, db, redis, caddy, chirpstack, chirpstack-postgres, mosquitto) sauber
- [ ] ChirpStack-Web-UI auf `http://localhost:8080` erreichbar, Tenant + Application + DeviceProfile angelegt (idempotent via Bootstrap-Skript)
- [ ] `chirpstack-simulator` generiert mindestens einen Vicki-formatigen Uplink, sichtbar in ChirpStack-UI mit decodiertem JSON-Object
- [ ] MQTT-Topic mit `mosquitto_sub` lauschbar — Uplink-JSON sichtbar
- [ ] FastAPI MQTT-Subscriber empfängt Uplink, validiert, persistiert in `uplinks`-Hypertable
- [ ] `GET /api/v1/devices/{dev_eui}/uplinks?limit=10` liefert JSON-Array mit den letzten 10 Uplinks
- [ ] Alembic-Migration `0002_lorawan` clean nach upgrade/downgrade-Zyklus
- [ ] Unit-Tests grün, Integrationstest mit testcontainers grün
- [ ] CI grün (lint-and-build + e2e)
- [ ] STATUS.md + neue RUNBOOK-Section §10 (LoRaWAN-Pipeline) committed
- [ ] Tag `v0.1.5-lorawan-foundation` gesetzt

### Abgrenzung — NICHT Teil von Sprint 5
- Keine echte Hardware (Gateway/Vicki) — Sprint 6
- Kein Test-Server-Deploy von ChirpStack — Sprint 6
- Keine Hotel-LAN-Konfiguration — Sprint 6
- Keine Regel-Engine — Sprint 7
- Kein Frontend für Uplinks — Sprint 8 (Dashboard-Sprint)
- Kein Downlink-Pfad (target_temp setzen) — Sprint 7 mit Regel-Engine
- Keine TLS auf MQTT (lokal nicht nötig, Test-Server bekommt es in Sprint 6 über Tailscale-only)

### Risiken

1. **ChirpStack v4 Bootstrap-Komplexität:**
   ChirpStack-UI verlangt initialen Tenant + Admin + Application + DeviceProfile + JS-Codec. Bei jedem `docker compose down -v` muss alles neu rein.
   **Gegenmaßnahme:** Bootstrap-Skript (`infra/chirpstack/bootstrap.py` via gRPC API oder REST API) — idempotent, prüft erst ob Objekte existieren.

2. **MClimate Vicki Codec:**
   Hersteller stellt Codec als JS-File bereit (Quelle: MClimate Developer Hub). Format kann sich zwischen Firmware-Versionen ändern.
   **Gegenmaßnahme:** Codec-Datei versioniert in `infra/chirpstack/codecs/mclimate-vicki-v<x>.js` ablegen, Source-URL im Header dokumentieren.

3. **chirpstack-simulator-Output ≠ echter Vicki-Output:**
   Simulator generiert generische LoRaWAN-Frames. Vicki-spezifische Felder müssen wir simulieren via Custom-Payload-Hex.
   **Gegenmaßnahme:** Realer Sample-Hex-Payload aus MClimate-Doku als Simulator-Input. Volle End-to-End-Validierung erst mit echter Hardware in Sprint 6.

4. **MQTT-Reconnect bei FastAPI:**
   Wenn Mosquitto neustartet, muss Subscriber sauber reconnecten ohne Doppel-Inserts.
   **Gegenmaßnahme:** `aiomqtt.Client` mit Auto-Reconnect, persistente Sessions (`clean_session=False`, eindeutige Client-ID), QoS 1, idempotenter Insert via `(dev_eui, fcnt)`-UNIQUE.

5. **TimescaleDB-Hypertable:**
   `create_hypertable` muss bei Migration aufgerufen werden, nicht nur via `CREATE TABLE`.
   **Gegenmaßnahme:** In Alembic-Migration explizit `op.execute("SELECT create_hypertable(...)")` nach Tabellen-Anlage.

6. **Compose-RAM auf work02 / heizung-test:**
   Drei zusätzliche Container = ~400 MB RAM. CPX22 hat 8 GB, bisher ~2 GB belegt — passt.

### Rollback

Reverter Sprint 5 = Branch nicht mergen oder vor Tag mit `git revert <merge-sha>` zurückrollen. Lokal: `docker compose down -v` löscht alles, nichts produktiv.

---

## Sprintplan (Phase 2)

### 5.1 — Feature-Brief (dieses Dokument)
User-Gate: freigeben oder ändern.

### 5.2 — ADR ChirpStack-Architektur
Entscheidungen A–F als ADR-Eintrag in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`. **Dauer:** 15 Min.

### 5.3 — Lokales Compose-Setup
- `docker-compose.yml` (Dev-Variante) erweitern um:
  - `chirpstack-postgres` (postgres:16-alpine, eigener Volume `chirpstack_db`)
  - `chirpstack` (chirpstack/chirpstack:4, abhängig von postgres + mosquitto)
  - `mosquitto` (eclipse-mosquitto:2)
- Konfig-Dateien:
  - `infra/chirpstack/chirpstack.toml`
  - `infra/chirpstack/region_eu868.toml`
  - `infra/mosquitto/mosquitto.conf` + `passwd`
- Startup-Verifikation: `docker compose up`, ChirpStack-UI auf `http://localhost:8080` erreichbar (Default-Login `admin/admin`).

**Dauer:** 1–1.5 h.

### 5.4 — ChirpStack initialisieren
- Bootstrap-Skript `infra/chirpstack/bootstrap.py`:
  - Verbindet via ChirpStack-API (`localhost:8090` gRPC oder REST)
  - Idempotent: Tenant `Hotel Sonnblick`, Application `heizung`, DeviceProfile `MClimate Vicki` mit JS-Codec
  - JS-Codec aus `infra/chirpstack/codecs/mclimate-vicki.js`
- README-Eintrag wie das Skript laufen muss.

**Dauer:** 1.5–2 h.

### 5.5 — chirpstack-simulator: erster Uplink
- chirpstack-simulator als zusätzlicher Compose-Service oder einmaliges `docker run`
- Virtual Gateway anlegen, Virtual Device mit DevEUI + AppKey, Sample-Vicki-Hex als Payload
- Verifikation:
  - ChirpStack-UI zeigt Uplink mit decodiertem JSON-Object
  - `mosquitto_sub -t "application/+/device/+/event/up" -u heizung-api -P <pw>` zeigt JSON

**Dauer:** 1 h.

### 5.6 — FastAPI MQTT-Subscriber
- Dependency `aiomqtt` zu `pyproject.toml`
- `app/services/mqtt_subscriber.py`:
  - Startet im Lifespan, läuft bis Shutdown
  - Subscribt `application/+/device/+/event/up`
  - Pydantic-Schema `UplinkEvent` validiert ChirpStack-Payload
  - Schreibt via `db.session` in `uplinks`-Tabelle
  - Reconnect-Logik mit Exponential Backoff
- Logging via `structlog` (bereits im Repo)

**Dauer:** 2 h.

### 5.7 — Datenmodell + Migration
- `app/models/device.py`: Felder `dev_eui` (String 16, unique), `join_eui` (String 16, nullable), `app_key_ref` (String, vault-pointer; nullable)
- `app/models/uplink.py` (neu):
  ```python
  class Uplink(Base):
      __tablename__ = "uplinks"
      id: Mapped[int] = mapped_column(primary_key=True)
      device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
      ts: Mapped[datetime] = mapped_column(index=True)
      fcnt: Mapped[int]
      rssi: Mapped[int | None]
      snr: Mapped[float | None]
      freq: Mapped[int | None]
      payload: Mapped[dict] = mapped_column(JSONB)
      __table_args__ = (UniqueConstraint("device_id", "fcnt"),)
  ```
- Alembic-Migration `0002_lorawan_uplinks.py`:
  - alter table devices add columns
  - create table uplinks
  - `SELECT create_hypertable('uplinks', 'ts', chunk_time_interval => INTERVAL '7 days')`
  - Index auf (device_id, ts DESC)

**Dauer:** 1.5 h.

### 5.8 — API GET /devices/{id}/uplinks
- Route in `app/api/v1/devices.py`
- Query-Params: `from`, `to`, `limit` (max 1000), `cursor` (für Pagination)
- Response: `UplinkRead`-Pydantic-Schema (id, ts, payload, rssi, snr)
- OpenAPI-Beschreibung mit Beispiel
- HTTP-Smoke per Playwright

**Dauer:** 45 Min.

### 5.9 — Tests
- Unit: `UplinkEvent`-Parser, Edge-Cases (fehlende Felder, falsche Typen)
- Integration mit `testcontainers-python`:
  - Postgres + Mosquitto starten
  - Mock-Uplink publishen
  - 2 Sek warten, dann DB-Insert verifizieren
- Playwright: HTTP-Smoke `/api/v1/devices/.../uplinks` mit Seed-Daten

**Dauer:** 1.5 h.

### 5.10 — PR + Merge + Tag
- STATUS.md neuer Abschnitt 2g (Sprint 5)
- RUNBOOK §10 (LoRaWAN-Pipeline: Lokales Compose, Bootstrap-Skript, Troubleshooting)
- ADR-Log um Sprint-5-Entscheidungen ergänzen
- PR `feat/sprint5-lorawan-foundation → main`, CI grün, Squash-Merge, Tag `v0.1.5-lorawan-foundation`

**Dauer:** 30 Min.

---

## Phase-Gates

- **Gate 1+2 (jetzt):** User liest Feature-Brief + Sprintplan, gibt frei.
- **Gate 3 (nach 5.5):** Erster simulierter Vicki-Uplink ist in MQTT sichtbar.
- **Gate 4 (nach 5.6+5.7):** FastAPI hat ersten Uplink in TimescaleDB.
- **Gate 5 (nach 5.10):** PR gemerged, Tag gesetzt, lokal `docker compose up` ergibt sauberen Stand mit allen Tests grün.

---

## Offene Fragen / Annahmen

- **[Annahme]** MClimate stellt einen offiziellen JS-Codec für Vicki bereit (verifiziert vor 5.4). Falls nicht: Codec selbst aus dem Datenblatt schreiben (~2 h Mehraufwand).
- **[Annahme]** chirpstack-simulator akzeptiert custom Hex-Payload pro Uplink (verifiziert vor 5.5). Falls nicht: minimale Dummy-Payload und Codec-Decode-Pfad als Stub.
- **[Annahme]** TimescaleDB-Image (`timescale/timescaledb:latest-pg16`) auf beiden Servern unterstützt `create_hypertable` ohne weitere Init-Hooks (war für Sprint 0 schon der Fall).
- **[Annahme]** AppKey-Storage: vorerst Plaintext in DB-Spalte `app_key_ref` (16 Bytes hex). Echtes Secret-Vault in späterem Sprint, wenn produktiv mit echten Devices gepairt wird. Aktuell nur Mock-Keys im Simulator.
