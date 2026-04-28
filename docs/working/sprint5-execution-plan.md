# Sprint 5 — Execution Plan (LoRaWAN-Foundation)

**Erstellt:** 2026-04-27. **Lese-Reihenfolge:** zuerst `docs/features/2026-04-27-sprint5-lorawan-foundation.md`, dann diese Datei. Diese Datei ist Claude's Operationsplan, nicht die User-facing Doku.

---

## 0. Verbindliche Architektur-Entscheidungen (NICHT erneut diskutieren)

| Entscheidung | Wahl | User-Bestätigung |
|---|---|---|
| A — ChirpStack-Hosting | Eigener Container, NICHT UG65-LNS | 2026-04-27 |
| B — ChirpStack-DB | Separater Postgres-Container | 2026-04-27 |
| C — MQTT-Broker | Mosquitto v2, ACL via passwd-File | 2026-04-27 |
| D — Bridge | aiomqtt im FastAPI-Lifespan | 2026-04-27 |
| E — Vicki-Codec | JS in ChirpStack-DeviceProfile | 2026-04-27 |
| F — Dev-First | Lokal auf work02, Test-Server in Sprint 6 | 2026-04-27 |

**Hardware:** Geräte da, Gateway noch nicht im LAN — daher Sprint 5 zwingend hardware-unabhängig mit chirpstack-simulator.

---

## 1. Reihenfolge (10 Sub-Sprints)

### 5.1 — Feature-Brief ✅ (erledigt 2026-04-27)
Datei: `docs/features/2026-04-27-sprint5-lorawan-foundation.md`. User-Gate 1+2 abwartet.

### 5.2 — ADR ChirpStack-Architektur
**Datei:** `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` ergänzen.
**Inhalt:** Entscheidungen A–F oben mit Begründungen. Format: bestehender ADR-Stil im File übernehmen (ADR-Nummer hochzählen, Status: Accepted, Datum, Context, Decision, Consequences).
**Dauer:** 15 Min.

### 5.3 — Lokales Compose-Setup ChirpStack + Mosquitto
**Wichtig:** Wir haben `docker-compose.prod.yml` (Server) — für lokale Dev brauchen wir `docker-compose.yml` (oder `docker-compose.dev.yml`). Aktuell unklar, ob ein Dev-Compose existiert. **Erst checken, dann entscheiden:** wenn keiner existiert, neuen `docker-compose.yml` für Dev anlegen, der die Services aus prod.yml referenziert + die LoRaWAN-Services ergänzt.

**Neue Services:**
- `mosquitto` (eclipse-mosquitto:2)
- `chirpstack-postgres` (postgres:16-alpine, eigenes Volume `chirpstack_db`)
- `chirpstack` (chirpstack/chirpstack:4)

**Konfig-Files (neu anlegen):**
- `infra/chirpstack/chirpstack.toml` — Hauptkonfig (Postgres-DSN, MQTT-URL, gRPC-Port)
- `infra/chirpstack/region_eu868.toml` — EU-Frequenzplan
- `infra/mosquitto/mosquitto.conf` — `listener 1883`, `allow_anonymous false`, `password_file /mosquitto/config/passwd`
- `infra/mosquitto/passwd` — User `chirpstack` und `heizung-api` (mosquitto_passwd-erzeugt; In .gitignore? Ja, secrets ausnehmen, dafür `passwd.example` einchecken)

**Ports lokal:**
- ChirpStack-UI: `8080` → `8080`
- ChirpStack-gRPC: `8090` → `8090` (für Bootstrap-Skript)
- Mosquitto: `1883` → `1883`
- Existing Caddy: `80`/`443` (kollidiert evtl. — für Dev evtl. abschalten oder umlegen)

**Verifikation:** `docker compose up -d`, dann Browser auf `http://localhost:8080`, Login `admin/admin`.

**Dauer:** 1–1.5 h. **In_progress markieren beim Start.**

### 5.4 — ChirpStack initialisieren (Bootstrap-Skript)
**Datei:** `infra/chirpstack/bootstrap.py`.
**Stack:** Python + `grpcio` + `chirpstack-api` (PyPI: `chirpstack-api`). Oder einfacher: REST API über `requests`.
**Idempotenz-Pattern:**
```python
# Pseudo-Code
tenant = find_or_create_tenant(name="Hotel Sonnblick")
app = find_or_create_application(tenant_id=tenant.id, name="heizung")
codec = read_file("infra/chirpstack/codecs/mclimate-vicki.js")
profile = find_or_create_device_profile(
    tenant_id=tenant.id,
    name="MClimate Vicki",
    region="EU868",
    mac_version="LORAWAN_1_0_3",
    codec_runtime="JS",
    codec_script=codec,
)
```

**Codec-File:** `infra/chirpstack/codecs/mclimate-vicki.js`. Quelle: https://github.com/MClimateOpenSource (oder aktueller Hersteller-Repo). Header mit Source-URL + Commit-SHA.

**Auth:** ChirpStack-API verlangt API-Key. Default-Admin (`admin/admin`) loggt sich ein, generiert API-Key, der wird in `.env.dev` als `CHIRPSTACK_API_KEY` abgelegt (gitignored).

**Aufruf:** `docker compose exec api python -m infra.chirpstack.bootstrap` oder einmalig `docker run --rm` mit gemountetem Skript.

**Dauer:** 1.5–2 h.

### 5.5 — chirpstack-simulator: erster Uplink
**Tool:** `chirpstack-simulator` (offizielles ChirpStack-Tool, separates Image).
**Ablauf:**
1. Virtual Gateway in ChirpStack-UI anlegen (oder via Bootstrap)
2. Device in ChirpStack registrieren (DevEUI z. B. `0011223344556677`, AppKey 16-Byte zufällig)
3. Simulator konfigurieren (`simulator.toml`): Gateway-EUI, Device-DevEUI, AppKey, Uplink-Interval
4. `docker run --rm chirpstack/chirpstack-simulator simulator.toml` startet Simulator, der OTAA-Join + periodische Uplinks generiert
5. Custom-Hex-Payload: aus MClimate-Datenblatt, z. B. typischer Vicki-Status-Frame `01 0a 18 64` (Battery, RSSI, Temp, Position — Bytes je nach Codec)

**Verifikation Gate 3:**
- ChirpStack-UI → Device → Live-Frames zeigt Join + Uplink mit decoded `object`
- `mosquitto_sub -h localhost -p 1883 -u heizung-api -P <pw> -t "application/+/device/+/event/up" -v` zeigt JSON-Frame

**Dauer:** 1 h.

### 5.6 — FastAPI MQTT-Subscriber
**Dependency:** `aiomqtt` (oder `asyncio-mqtt`). In `backend/pyproject.toml` ergänzen.
**Datei:** `backend/app/services/mqtt_subscriber.py`.

**Pattern:**
```python
from contextlib import asynccontextmanager
import aiomqtt
from app.core.config import settings
from app.db.session import async_session_factory
from app.models.uplink import Uplink

async def mqtt_consumer():
    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.MQTT_HOST,
                port=settings.MQTT_PORT,
                username=settings.MQTT_USER,
                password=settings.MQTT_PASSWORD,
                client_id="heizung-api-subscriber",
                clean_session=False,
                keepalive=30,
            ) as client:
                await client.subscribe("application/+/device/+/event/up", qos=1)
                async for msg in client.messages:
                    await persist_uplink(msg.payload)
        except aiomqtt.MqttError as e:
            logger.warning("MQTT-Reconnect in 5s", error=str(e))
            await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(mqtt_consumer())
    yield
    task.cancel()
```

**Pydantic-Schema** `UplinkEvent` validiert ChirpStack-JSON (Felder: `deviceInfo.devEui`, `fCnt`, `fPort`, `data` (base64), `object` (decoded), `rxInfo[].rssi`, `rxInfo[].snr`, `txInfo.frequency`).

**Persistenz:** `INSERT ... ON CONFLICT (device_id, fcnt) DO NOTHING` für Idempotenz.

**Dauer:** 2 h.

### 5.7 — Datenmodell + Migration
**Datei `backend/app/models/device.py`:** ergänzen
```python
dev_eui: Mapped[str | None] = mapped_column(String(16), unique=True, index=True)
join_eui: Mapped[str | None] = mapped_column(String(16))
app_key_ref: Mapped[str | None] = mapped_column(String(64))
```

**Datei `backend/app/models/uplink.py`:** neu (siehe Feature-Brief 5.7).

**Migration `backend/alembic/versions/0002_lorawan_uplinks.py`:**
```python
def upgrade():
    op.add_column("devices", sa.Column("dev_eui", sa.String(16), unique=True))
    op.add_column("devices", sa.Column("join_eui", sa.String(16)))
    op.add_column("devices", sa.Column("app_key_ref", sa.String(64)))
    op.create_table(
        "uplinks",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("device_id", sa.Integer, sa.ForeignKey("devices.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fcnt", sa.Integer, nullable=False),
        sa.Column("rssi", sa.Integer),
        sa.Column("snr", sa.Float),
        sa.Column("freq", sa.BigInteger),
        sa.Column("payload", postgresql.JSONB),
        sa.UniqueConstraint("device_id", "fcnt"),
    )
    op.execute(
        "SELECT create_hypertable('uplinks', 'ts', chunk_time_interval => INTERVAL '7 days')"
    )
    op.create_index("ix_uplinks_device_ts", "uplinks", ["device_id", sa.text("ts DESC")])
```

**Verifikation:** `alembic upgrade head` lokal + `alembic downgrade -1` clean.

**Dauer:** 1.5 h.

### 5.8 — API GET /devices/{id}/uplinks
**Datei:** `backend/app/api/v1/devices.py` (vermutlich existiert schon — prüfen, sonst neu).

**Route:**
```python
@router.get("/{device_id}/uplinks", response_model=list[UplinkRead])
async def list_uplinks(
    device_id: int,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    cursor: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[Uplink]:
    ...
```

**Pagination:** Cursor-basiert über `id` (jüngste zuerst). Vermeidet Offset-Pagination-Probleme bei häufigen Inserts.

**Smoke-Test:** Playwright HTTP-Test in `frontend/e2e/api-uplinks.spec.ts`.

**Dauer:** 45 Min.

### 5.9 — Tests
**Unit-Tests** (`backend/tests/test_mqtt_subscriber.py`):
- UplinkEvent-Pydantic-Validierung mit valid + invalid Inputs
- `persist_uplink` mit Mock-DB

**Integration-Test** (`backend/tests/test_lorawan_e2e.py`):
- testcontainers: Postgres + Mosquitto
- Skript publisht Mock-Uplink auf MQTT
- Test wartet 2 Sek, queryt DB, erwartet 1 Row
- `pytest-asyncio` für async-Tests

**Playwright-Smoke**: HTTP `/api/v1/devices/.../uplinks` mit gesetzten Seed-Daten

**Dauer:** 1.5 h.

### 5.10 — PR + Merge + Tag
- Branch `feat/sprint5-lorawan-foundation`
- Commits chronologisch sauber (kein force-push, mehrere Commits OK, am Ende squash-merge)
- STATUS.md Abschnitt 2g (Sprint 5) ergänzen — siehe Pattern in 2c–2f
- RUNBOOK §10 (LoRaWAN-Pipeline) neu: lokales Compose, Bootstrap-Skript ausführen, Troubleshooting MQTT-Reconnect, ChirpStack-API-Key-Rotation
- ADR-Eintrag um Sprint-5-Lessons ergänzen
- PR-Body: Summary + Verifikation + Rollback (siehe Sprint 4 PR als Vorlage)
- `gh pr checks 8 --watch` (PR-Nr ist erratisch, im Moment des Erstellens ablesen)
- `gh pr merge --squash --delete-branch`
- `git tag -a v0.1.5-lorawan-foundation -m "Sprint 5: LoRaWAN-Foundation lokal lauffähig"`
- `git push origin v0.1.5-lorawan-foundation`

**Dauer:** 30 Min.

---

## 2. Phase-Gates (User-Bestätigung erforderlich)

- **Gate 1+2:** Feature-Brief + Sprintplan freigegeben → ✅ am 2026-04-27 implizit durch "los gehts"
- **Gate 3 nach 5.5:** Erster Vicki-formatiger Uplink in MQTT sichtbar → User-Bestätigung mit Screenshot/Log-Auszug
- **Gate 4 nach 5.7:** FastAPI hat ersten Uplink in TimescaleDB → User-Bestätigung mit `SELECT * FROM uplinks LIMIT 5`-Output
- **Gate 5 nach 5.10:** Tag gesetzt, lokale `docker compose up` ergibt sauberen Stand mit allen Tests grün → User-Bestätigung

---

## 3. Risiken & Gegenmaßnahmen (operativ)

| Risiko | Gegenmaßnahme |
|---|---|
| ChirpStack-Bootstrap nicht idempotent | Skript prüft erst `find_*` und ruft `create_*` nur bei NotFound |
| MClimate-Codec nicht verfügbar / ändert sich | Codec-Datei versioniert mit Source-URL + Commit-SHA-Header |
| Simulator-Output nicht Vicki-realistisch | Sample-Hex aus MClimate-Doku als Input — End-to-End-Validierung erst mit echter Hardware (Sprint 6) |
| MQTT-Reconnect verliert Messages | QoS 1, `clean_session=False`, fixierte Client-ID, idempotenter Insert via UNIQUE (device_id, fcnt) |
| TimescaleDB Hypertable nicht erstellt | Explicit `op.execute("SELECT create_hypertable(...)")` in Migration |
| Compose-RAM auf work02 zu hoch | 8 GB RAM lokal sollte reichen, ChirpStack ~150 MB, Mosquitto <50 MB, Postgres ~150 MB |
| Caddy-Port-Konflikt lokal | Caddy in Dev-Compose evtl. abschalten oder Ports umbiegen (8080/8443) — Caddy ist für Lokal-Dev nicht zwingend |

---

## 4. Was NICHT zu Sprint 5 gehört (Scope-Schutz)

- ❌ Echte Hardware (Gateway/Vicki) — **Sprint 6**
- ❌ ChirpStack-Deploy auf heizung-test/main — **Sprint 6**
- ❌ Hotel-LAN-Konfiguration — **Sprint 6**
- ❌ Regel-Engine (8 Kernregeln) — **Sprint 7**
- ❌ Frontend-Dashboard für Uplinks — **Sprint 8**
- ❌ Downlink-Pfad (target_temp setzen) — **Sprint 7**
- ❌ MQTT-TLS — **Sprint 6** (Test-Server) bzw. nicht nötig lokal
- ❌ Secrets-Vault für AppKeys — späterer Sprint, wenn produktiv mit echten Devices

Bei Scope-Anflug: kurz STOP und User fragen, NICHT silently expandieren.

---

## 5. Tooling-Verweise (extern)

- ChirpStack v4 Docs: https://www.chirpstack.io/docs/
- ChirpStack Docker Compose Quickstart: https://github.com/chirpstack/chirpstack-docker
- ChirpStack Simulator: https://github.com/chirpstack/chirpstack-simulator
- MClimate Vicki Datenblatt: https://mclimate.eu/products/mclimate-vicki/
- MClimate Codec-Repo: https://github.com/MClimateBg/lorawan-codecs (Stand zu prüfen)
- aiomqtt: https://sbtinstruments.github.io/aiomqtt/
- TimescaleDB Hypertables: https://docs.tigerdata.com/api/latest/hypertable/

---

## 6. Status-Tracking

Tasks #35–#44 in TaskList. Beim Start jedes Sub-Sprints `in_progress` setzen, am Ende `completed`. Bei Blockern: in_progress lassen, neuen Task für den Blocker anlegen.
