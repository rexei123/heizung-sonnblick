# Sprint 13 Phase-0 — Quellcheck

**Datum:** 2026-05-21
**Rolle:** Claude Code (Read-Only-Quellcheck, kein Code-Edit, kein PR)
**Brief:** Strategie-Chat 2026-05-21 — Pre-Pairing-Skript + Device-Tausch-Endpoint
**Branch:** `chore/sprint13-phase0` (nur WIP-Commit dieses Berichts)
**Autonomiestufe:** 2

## SESSION-START bestätigt — 2026-05-07

- **Rolle:** Code (Phase-0-Quellcheck, Read-Only)
- **Gelesen:** `docs/SESSION-START.md`, `CLAUDE.md` (komplett, §0..§7 + §5.1..§5.57), `docs/STRATEGIE-REFRESH-2026-05-15.md`, `docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md`, `docs/SPRINT-PLAN.md` (Sprint 12c, 12c.a, 13), `STATUS.md` §1 + §2aq + §2ar, `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` AE-43/AE-48/AE-51/AE-58 (+ AE-47/AE-52/AE-53/AE-54), `docs/RUNBOOK.md` §10h, Sprint-13-Brief.
- **Aktueller Sprint laut STATUS.md §2:** Sprint 12c.a abgeschlossen (Tag `v0.1.17d-room-block-list-indicator`, Live-Verify 2026-05-21). Nächster Sprint: 13 (Pairing-Wizard + Mass-Pairing-CSV + Vicki-Eingangstest).
- **Top-3-Backlog:** B-12c-AuditGap (`auto_revoke_on_checkout` ohne Audit), B-12c-1 (Vicki-Hardware-Child-Lock via `0x07`), AE-57-Lücken-Klärung (Doku-Hygiene).
- **Kritische Hardware-Befunde gelesen:** §5.27 (Vicki-Window-Default disabled, FW-abhängig, Sommer nicht testbar), AE-45 (Auto-Override-Mechanik — abgelöst durch AE-58), AE-47 (Hardware-First-Window mit drei Trigger-Quellen), `docs/vendor/mclimate-vicki/` (FW-Tabelle + Command-Cheat-Sheet).
- **Historische Sprint-Briefe vor 2026-05-07:** nicht für Pläne, nur für Lessons.

Bereit für Auftrag.

---

## Zusammenfassung (5 Bullets)

- **Schema-Lücke für Lifecycle:** `device.is_active` (Boolean) + `device.heating_zone_id` (FK nullable, SET NULL) existieren. Es gibt **kein** `retired_at`-Feld. `is_active` mischt heute „temporär deaktiviert" und „permanent retired" — empfohlen ist explizites `retired_at: TIMESTAMP NULL` in Migration 0018 (Pattern §5.49).
- **Sprint 9.13-Detach reicht für Tausch-Use-Case nur eingeschränkt:** `DELETE /devices/{id}/heating-zone` setzt nur `heating_zone_id=NULL`, lässt `is_active=True`. Sensor-Readings + Device-Row bleiben (gut für Historie). Aber kein Audit-Marker „wann retired", kein BusinessAudit, keine Cross-Reference auf neuen Vicki.
- **`set_open_window_detection` ist seit Sprint 9.11x.b vorhanden** (AE-48, `downlink_adapter.py:207`), `send_setpoint` ist robust und Roundtrip-tauglich. Pre-Pairing-Eingangstest braucht **keine** neuen Downlink-Helper — nur ein Skript-Wrapper.
- **CSV-Konvention existiert nicht im Repo** (kein `csv.*`-Import, kein pandas). Empfehlung: pure-stdlib `csv.DictReader` + Pydantic-Row-Modell mit Decimal-Setpoints und Hex-Pattern-Validierung. CLI-Skripte folgen `argparse`-Pattern aus `backend/scripts/activate_open_window_detection.py`.
- **Engine-Query-Audit (12 Stellen identifiziert)**: S4-Hauptrisiko liegt im Downlink-Dispatch (`engine_tasks.py:349-355`); dort schützt `is_active.is_(True)`. Layer-4-Detached + Window-Helper haben **keinen** `is_active`-Filter — nach Sprint-13-Schema-Migration ist `retired_at IS NULL`-Filter an 5 Stellen Pflicht (Liste in §L).

---

## A. Device-Schema

**File:** `backend/src/heizung/models/device.py`

### Befund — alle Columns

| Spalte | Typ | NOT NULL | Default | Bemerkung |
|---|---|---|---|---|
| `id` | int | ✓ | PK autoincrement | |
| `dev_eui` | VARCHAR(16) | ✓ | — | unique, LoRaWAN |
| `app_eui` | VARCHAR(16) | — | — | |
| `kind` | Enum (`DeviceKind`, length=20, `native_enum=False`) | ✓ | — | |
| `vendor` | Enum (`DeviceVendor`, length=20, `native_enum=False`) | ✓ | — | |
| `model` | VARCHAR(50) | ✓ | — | |
| `heating_zone_id` | FK `heating_zone.id`, ON DELETE SET NULL | — | — | NULL = Provisioning oder Detach |
| `label` | VARCHAR(200) | — | — | |
| `firmware_version` | VARCHAR(8) | — | — | Sprint 9.11x.b, MQTT-Subscriber pflegt |
| `health_state` | VARCHAR(16) | ✓ | DB `'silent'` | AE-53, CHECK-Constraint |
| `is_active` | Boolean | ✓ | Python `True` | seit jeher vorhanden |
| `last_seen_at` | TIMESTAMP TZ | — | — | |
| `created_at` | TIMESTAMP TZ | ✓ | `now()` | |
| `updated_at` | TIMESTAMP TZ | ✓ | `now()` + `onupdate` | |

### Befund — Lifecycle-Felder

- **Vorhanden:** `is_active: bool`, `heating_zone_id: int | None` (FK SET NULL), `last_seen_at`, `updated_at`.
- **Fehlt:** explizites `retired_at`, `retired_reason`, `replaced_by_device_id`.
- Sprint 9.13-Doku zeigt: `is_active` wird heute **nirgends** im Code auf `False` gesetzt (kein Endpoint, kein Service). Es ist ein „toter Hebel" mit semantischem Default.

### Empfehlung — Migration 0018

`backend/alembic/versions/0018_device_retired_at.py`, basiert auf §5.49-Pattern (nullable Spalten ohne Backfill-Drift):

```python
def upgrade() -> None:
    op.add_column("device", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("device", sa.Column("retired_reason", sa.String(64), nullable=True))
    op.add_column(
        "device",
        sa.Column(
            "replaced_by_device_id",
            sa.Integer(),
            sa.ForeignKey("device.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Voll-Unique-Constraint aus Migration 0001 entfernen und durch
    # Partial-Unique-Index ersetzen, damit retired Rows mit derselben
    # DevEUI nebeneinander existieren koennen (DevEUI-Wiederverwendung
    # nach Werksreset). Eindeutigkeit nur unter aktiven Rows.
    op.drop_constraint("uq_device_dev_eui", "device", type_="unique")
    op.create_index(
        "ix_device_dev_eui_active",
        "device",
        ["dev_eui"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )
    # is_active-Spalte wird durch retired_at abgeloest (siehe Anhang
    # is_active-Befund + AE-57 Entscheidung 2 Uebergangs-Klausel).
    op.drop_column("device", "is_active")
```

- **`retired_at: datetime | None`** — NULL = aktiv, gesetzt = retired (unwiderruflich, Audit-Anker).
- **`retired_reason: VARCHAR(64) | None`** — z. B. `'hardware_swap'`, `'battery_dead'`, `'pre_pairing_failed'`. Optional, aber Free-Text bleibt aus dem `event_log` heraus. Länge auf 64 angeglichen an `BusinessAudit.action` (CLAUDE.md §5.45-Disziplin).
- **`replaced_by_device_id: FK device.id NULL`** — Cross-Reference Alt → Neu (Brief K. DEVICE_REPLACED).
- **Partial-Unique-Index `ix_device_dev_eui_active`** — erlaubt mehrere retired Rows mit gleicher `dev_eui` (Hardware-Drift-Forensik + Re-Pair nach Werksreset), garantiert Eindeutigkeit nur unter aktiven Rows. Ersetzt die Voll-Unique-Constraint `uq_device_dev_eui` aus Migration 0001 (`backend/alembic/versions/0001_initial_domain_model.py:162`).
- **`DROP COLUMN is_active`** — Bundle mit `ADD retired_at` (AE-57 Entscheidung 2 Übergangs-Klausel). Zwei Read-Stellen umstellen: `engine_tasks.py:352` + `api/v1/devices.py:137`.
- **Kein Backfill nötig** (Spalten nullable, kein `server_default`), §5.56-Roundtrip-Anpassung **nicht** erforderlich.

---

## B. Sprint 9.13 Detach-Logik

**File:** `backend/src/heizung/api/v1/devices.py` (kein separater Service-Layer, Logik inline)

### Befund

- `DELETE /api/v1/devices/{id}/heating-zone` (`detach_device_from_zone`, Zeile 246–296, `require_admin`):
  - Setzt `device.heating_zone_id = None`.
  - Logged `device_zone_detached` (struct).
  - Triggert `evaluate_room.delay(old_zone.room_id)` (Engine-Tick auf altes Zimmer, Layer-4-Detached-Aggregation aktualisiert sich).
  - **Setzt KEIN** `is_active=False`, **kein** `last_seen_at`-Touch, **kein** BusinessAudit-Eintrag.
- `PUT /api/v1/devices/{id}/heating-zone` (`assign_device_to_zone`, Zeile 188–243): Re-Attach an Zone, idempotent, triggert Engine-Tick auf neues Zimmer.
- `PATCH /api/v1/devices/{id}` (Zeile 158–180): generischer Partial-Update — könnte über `payload.is_active=False` indirekt einen Retire-Pfad bieten, aber kein dedizierter Endpoint, kein Audit.

Sensor-Readings + Device-Row bleiben **unangetastet**. `sensor_reading.device_id` zeigt weiter auf alte Row (Historie OK).

### Reicht es für Hardware-Tausch mit Historien-Erhalt?

Eingeschränkt. **Funktional ja** (Detach kappt Zone, Re-Attach legt neuen Vicki auf gleiche Zone, Engine ignoriert alten Vicki über `Device.heating_zone_id == zone_id`-Filter im Downlink-Dispatch). **Audit nein**:

- Kein BusinessAudit-Eintrag → Hotelier kann später nicht nachvollziehen, **wann** ein Vicki ersetzt wurde.
- Kein expliziter Timestamp → `updated_at` ist mehrdeutig (Label-Edit, Detach, Health-Update setzen es alle).
- Keine Cross-Reference Alt → Neu → bei Mehrfach-Tausch (z. B. zwei Vickis in einer Zone, einer kaputt) nicht ohne SQL-Forensik klärbar.
- Alter Vicki bleibt `is_active=True` mit `heating_zone_id=NULL` — semantisch zweideutig: „warten auf Re-Pairing" vs. „retired".

**Empfehlung Sprint 13:** Neuer Endpoint `POST /api/v1/devices/{id}/retire` (siehe A für Schema), der atomar setzt: `retired_at=now()`, `is_active=False`, `heating_zone_id=NULL`, `replaced_by_device_id=<neuer_id|None>`, plus BusinessAudit `DEVICE_RETIRED` in derselben Transaktion + `evaluate_room.delay(old_room_id)`. Detach-Endpoint bleibt für „temporäre Abnahme" (Wartung, Umzug) erhalten.

---

## C. Device-Queries Lifecycle-Filter-Audit

Repo-Grep `select(Device)` / `Device.<col>` / `from heizung.models.device`. 12 Fundstellen, gruppiert nach Risiko-Klasse.

| # | Datei : Zeile | Aktueller Filter | S4-Risiko nach Retire+Pair-New |
|---|---|---|---|
| 1 | `tasks/engine_tasks.py:349-355` (`_get_devices_for_zone`) | `heating_zone_id == zone_id AND is_active.is_(True) AND health_state == 'healthy'` | **hoch (Downlink-Dispatch)** — Filter schützt heute, aber nur weil Retire-Pfad fehlt. Bei `retired_at`-Migration als Pflicht-Filter ergänzen. |
| 2 | `rules/engine.py:617-622` (`layer_device_detached` Device-Load) | `HeatingZone.room_id == room_id` (kein Lifecycle-Filter) | mittel — falsche Detached-Detection bei retirtem Device mit „unklarem" Status (Trigger feuert nicht, aber Diagnose irreführend) |
| 3 | `rules/engine.py:647-657` (`layer_device_detached` Reading-Subquery) | analog zu #2 | mittel — gleicher Pfad |
| 4 | `rules/engine.py:540-553` (`layer_window_open` no-op-Diagnose) | `Device.health_state == 'healthy'` | niedrig — nur Diagnose-Text (`no_readings`/`stale_reading`/`no_open_window`) |
| 5 | `rules/engine.py:887-892` (`_last_command_for_room` deprecated) | kein Lifecycle | niedrig — deprecated, audit-only Pfad |
| 6 | `rules/window_state.py:73-80` (`detect_open_window_zones`) | `HeatingZone.room_id == room_id AND Device.health_state == 'healthy'` | **mittel (S4-relevant)** — falsches Window-Signal → Layer 4 → Frostschutz statt Heizung |
| 7 | `rules/inferred_window.py:97-115, 105-113, 141-145` | kein Lifecycle | niedrig — read-only Diagnose, kein Setpoint-Pfad |
| 8 | `services/device_adapter.py:107-114` (`_device_room_id`) | `Device.id == device_id` | mittel — Override-Insert bei Vicki-Drehring; retirter Vicki könnte Override triggern, wenn er noch funkt |
| 9 | `services/device_adapter.py:128` (`_device_zone_id`) | analog zu #8 | mittel — gleicher Pfad |
| 10 | `services/mqtt_subscriber.py:192,385` (DevEUI → device_id) | `Device.dev_eui == dev_eui` | niedrig — Reading-Persisting bewusst auch für retired (Historie). Aber #11 ist abhängig. |
| 11 | `services/mqtt_subscriber.py:262-265` (`evaluate_room`-Trigger über Zone-Lookup) | `Device.id == device_id`, JOIN über `heating_zone_id` | niedrig (durch #1 abgesichert, aber unnötige Engine-Last) |
| 12 | `tasks/health_tasks.py:172` (`select(Device)` Health-Compute) | keiner | niedrig — Compute für retired Devices nutzlos, kein Schaden |
| 13 | `api/v1/devices.py:135` (Listen-View) | optional `is_active`-Query-Param | niedrig (UI) — neuer Param `include_retired` empfohlen |

**Pflicht-Filter nach Migration 0018** (`retired_at IS NULL`):

- #1 `_get_devices_for_zone` — **S4-Pflicht**
- #2 + #3 `layer_device_detached` — Pflicht (Audit-Konsistenz)
- #6 `detect_open_window_zones` — Pflicht (Layer-4-Konsistenz)
- #8 + #9 `_device_room_id` / `_device_zone_id` — Pflicht (Override-Anlage)
- #11 mqtt_subscriber Trigger — empfohlen

Restliche Stellen entweder durch Retire-Endpoint-Semantik (`heating_zone_id=NULL` setzt) bereits robust ODER niedrige Konsequenz.

---

## D. `downlink_adapter.py` Inventar

**File:** `backend/src/heizung/services/downlink_adapter.py`

### Exportierte Funktionen

| Funktion | Signatur | Sprint | Verwendung |
|---|---|---|---|
| `build_downlink_message(setpoint_c: int, dev_eui: str) -> str` | sync | 9.2 (refactored 9.11x.b) | Test-Hook |
| `build_downlink_topic(dev_eui: str) -> str` | sync | 9.2 | Test-Hook, **public** (Pre-Pairing-Skript darf wiederverwenden) |
| `send_raw_downlink(dev_eui, payload_bytes, *, fport=1, confirmed=False) -> str` | **async** | 9.11x.b (AE-48) | Generic-Low-Level, alle Wrapper delegieren hierher |
| `send_setpoint(dev_eui: str, setpoint_c: int) -> str` | async | 9.2 (refactored 9.11x.b) | 0x51-Wrapper |
| `query_firmware_version(dev_eui: str) -> str` | async | 9.11x.b | 0x04 (FW-Get, asynchrone Antwort via Uplink) |
| `set_open_window_detection(dev_eui, enabled: bool, duration_min: int, delta_c: Decimal) -> str` | async | 9.11x.b (AE-48) | 0x45 (FW ≥ 4.2 mit 0.1 °C-Resolution) |
| `get_open_window_detection(dev_eui: str) -> str` | async | 9.11x.b | 0x46 |

Plus Konstanten `MIN_SETPOINT_C` (= FROST_PROTECTION_C = 10), `MAX_SETPOINT_C` (= 30), Exception `DownlinkError`.

### Befund — `set_open_window_detection` (AE-48)

**Vorhanden, vollständig.** Default-Parameter aus Vendor-Doku: `enabled=True, duration_min=10, delta_c=Decimal("1.5")`. Wiederverwendbar für Pre-Pairing-Skript ohne Anpassung. `Decimal`-Pflicht (CLAUDE.md §6, S2/S6-Begründung).

### Befund — `send_setpoint` Roundtrip-Tauglichkeit

**Roundtrip-tauglich** für Eingangstest „Setpoint 25 → hörbar auf, Setpoint 10 → hörbar zu":

- Async-API; Skript kann `await send_setpoint(dev_eui, 25)` → `asyncio.sleep(60)` → `await send_setpoint(dev_eui, 10)` sequentiell aufrufen.
- Keine Confirmation/ACK-Mechanik im Adapter (Vicki bestätigt asynchron via Uplink `0x52`, MQTT-Subscriber persistiert) — für RUNBOOK §10h.1-Eingangstest reicht „hörbar" + ChirpStack-Events-Tab (Mensch verifiziert).
- Kein Hysterese-Check im Adapter selbst (Hysterese liegt in `engine_tasks.py`, nicht im Adapter-Pfad).

**Lückenbericht:** keine. Pre-Pairing-Skript kann `set_open_window_detection` + `send_setpoint` + `query_firmware_version` direkt wiederverwenden.

Mögliche Zusatz-Wrapper für Sprint 13 (nicht zwingend):

- **`send_child_lock(dev_eui, enabled: bool)` (0x07)** — bekannter Backlog B-12c-1, separater Sprint, **NICHT** Sprint 13.
- **`set_reporting_interval(dev_eui, minutes: int)` (0x4D)** — fall im Pre-Pairing-Workflow die Default-Periodic-Cycle (~10 Min) für Verify zu lang ist; ist heute Vendor-Default, kann offen bleiben.

---

## E. ChirpStack-Config

**Files:** `backend/src/heizung/config.py`, `.env.example`

### Variablen (heute)

| Variable | Default in `config.py` | In `.env.example` | Verwendung |
|---|---|---|---|
| `chirpstack_app_id` | UUID `b7d74615-...000000000000` (Platzhalter) | **fehlt** | Topic-Build (`downlink_adapter.py:152`) |
| `downlink_topic_template` | `application/{app_id}/device/{dev_eui}/command/down` | — | ChirpStack-v4-Konvention |
| `mqtt_host` | `mosquitto` (Container-DNS) | — | Innerhalb Docker OK, lokal fehlt SSH-Tunnel |
| `mqtt_port` | `1883` | — | |
| `mqtt_user`, `mqtt_password` | — | `MQTT_HEIZUNG_PASSWORD=…` | |
| `mqtt_client_id` | `heizung-api-subscriber` | — | Pre-Pairing-Skript muss eigenen Client-ID setzen |
| `chirpstack_api_secret` | — | `CHIRPSTACK_API_SECRET=…` | nur Bootstrap-Anker, **nicht** für Device-Downlinks |
| `chirpstack_api_key` | — | `CHIRPSTACK_API_KEY=` (leer) | gRPC-Bootstrap (Codec-Deploy-Backlog), **nicht** für Device-Downlinks (CLAUDE.md §5.28) |

**Tenant-ID:** existiert nicht als Variable — wird über App-ID implizit aufgelöst.

### Lookup-Helper für App-ID?

**Nein.** App-ID ist hartkodiert in `Settings.chirpstack_app_id` (Default ist Test-Server-UUID). Kein dynamischer Lookup-Helper, kein gRPC-Aufruf. Skript am Office-Laptop muss App-ID per ENV-Override mitbringen.

### Office-Laptop → heizung-test über Tailscale

Mosquitto läuft im Docker-Compose-Netz auf `heizung-test`. Port `1883` ist Container-intern; vom Office-Laptop **nicht direkt** erreichbar (UFW-Regel `allow in on tailscale0` öffnet kein Mosquitto-Forwarding).

**Drei Optionen:**

1. **SSH-LocalForward** (empfohlen): `ssh -L 1883:127.0.0.1:1883 -i ~/.ssh/id_ed25519_heizung -N heizung-test`. Skript sieht `mqtt_host=localhost`, alles andere identisch. Saubere Lösung, kein UFW-Touch.
2. **Skript im API-Container ausführen**: `docker exec deploy-api-1 python scripts/pair_devices.py …`. Vorteil: alle Settings (DB + MQTT + App-ID) bereits korrekt. Pattern identisch zu `activate_open_window_detection.py` (siehe G). CSV via `docker cp <local.csv> deploy-api-1:/tmp/pair.csv`.
3. **Mosquitto-Listener auf Tailscale-IP** — UFW + Mosquitto-Listener-Config-Change, S5-Risiko, **abzulehnen**.

**Empfehlung:** Option 2 als Default (am einfachsten für Hotelier, kein lokaler venv nötig). Option 1 für Entwickler-Verify ohne SSH-Sprung.

**Backlog-Hinweis:** `.env.example` ergänzen um `CHIRPSTACK_APP_ID=…` (heute fehlt es — `chirpstack_app_id`-Default ist nicht-produktiv). Kleiner Hygiene-Punkt, Mini-PR.

---

## F. CSV-Parser-Patterns

**Repo-Grep** in `backend/`: `csv.reader`, `csv.DictReader`, `pandas.read_csv`, `pydantic_csv` — **alle null Treffer.** Keine CSV-Konvention vorhanden.

`backend/pyproject.toml` listet keine `pandas`/`csv*`-Abhängigkeit. **stdlib-`csv`** ist verfügbar (Python 3.12).

### Empfehlung Sprint 13

Pure-stdlib `csv.DictReader` + Pydantic-Row-Modell mit `Decimal`-Setpoints und Hex-Pattern-Validierung. Pattern (Skizze, nicht implementieren):

```python
import csv
from decimal import Decimal
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, ValidationError

class PairingCsvRow(BaseModel):
    """Eine CSV-Zeile aus dem Mass-Pairing-Import (RUNBOOK §10h.2 TBD)."""
    dev_eui: str = Field(min_length=16, max_length=16, pattern=r"^[0-9a-fA-F]{16}$")
    app_eui: str = Field(min_length=16, max_length=16, pattern=r"^[0-9a-fA-F]{16}$")
    app_key: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-fA-F]{32}$")
    label: str | None = Field(default=None, max_length=200)
    room_number: str = Field(min_length=1, max_length=20)
    zone_name: str = Field(min_length=1, max_length=100)

    @field_validator("dev_eui", "app_eui", "app_key")
    @classmethod
    def _lowercase(cls, v: str) -> str:
        return v.lower()


def parse_csv(path: Path) -> tuple[list[PairingCsvRow], list[tuple[int, str]]]:
    rows: list[PairingCsvRow] = []
    errors: list[tuple[int, str]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, raw in enumerate(reader, start=2):  # Zeile 1 = Header
            try:
                rows.append(PairingCsvRow.model_validate(raw))
            except ValidationError as e:
                errors.append((idx, str(e)))
    return rows, errors
```

**Konventionen:**

- Encoding `utf-8` (LF, kein BOM — CLAUDE.md §5.3 erinnert an PS5-Encoding-Probleme; CSV wird typisch von Hotelier in Excel/Numbers gepflegt — UTF-8 als Pflicht in Header-Doku).
- Lowercase-Normalisierung für Hex-Strings (ChirpStack erwartet lowercase, CLAUDE.md §5.13).
- `room_number` als String (nicht Int) — passt zu `Room.number VARCHAR(20)`.
- `zone_name` muss zu existierendem `heating_zone.name` (Unique pro Room) matchen — Lookup im Skript, nicht in der Row-Validation.
- Alle Errors sammeln, am Ende **vollständig** rauswerfen (User-Brief-Pattern „nicht nur erste Zeile melden"). Beim ersten Error nur abbrechen wenn Header-Mismatch.

**CSV-Format-Vorschlag (RUNBOOK §10h.2 ergänzen):**

```csv
dev_eui,app_eui,app_key,label,room_number,zone_name
70b3d52dd3034de4,0000000000000000,abcdef0123456789abcdef0123456789,Vicki-101a,101,Schlafzimmer
70b3d52dd3034de5,0000000000000000,abcdef0123456789abcdef0123456789,Vicki-101b,101,Bad
```

---

## G. CLI-Skript-Patterns

**Pfad existiert:** `backend/scripts/`

| Skript | Sprint | Pattern |
|---|---|---|
| `scripts/README.md` | — | Doku |
| `scripts/smoke_engine_lock.py` | 9.10 T3.5 | Manueller Smoke gegen Redis-SETNX-Lock |
| `scripts/activate_open_window_detection.py` | 9.11x.b T8 | argparse + asyncio.run, 3-Phasen-Pattern, Aufruf via `docker exec deploy-api-1 python scripts/<n>.py` |

**Keine** `[project.scripts]`-Entry-Points in `backend/pyproject.toml` — Skripte werden direkt mit `python scripts/<name>.py` aufgerufen, nicht installiert als CLI-Befehle.

### Etablierte Konvention (aus `activate_open_window_detection.py`)

```python
"""Modul-Docstring als argparse-description (--help-Text)."""

import argparse, asyncio, logging, os, sys
from decimal import Decimal

# Pre-Import: ENV-Defaults für lokalen Run
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://...")

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.services.downlink_adapter import (  # noqa: E402
    send_setpoint, set_open_window_detection, query_firmware_version,
)

logger = logging.getLogger("kurzname")


async def main_async(args) -> int:
    ...


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-secs", type=int, default=60, ...)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
```

### Empfehlung Sprint 13 — Skript-Layout `backend/scripts/pair_devices.py`

Mit argparse-**Subcommands** (deckt Brief-Forderung „CLI + Mini-Subcommand für Eingangstest pro Vicki" sauber ab):

```python
parser = argparse.ArgumentParser(description=__doc__)
sub = parser.add_subparsers(dest="command", required=True)

p_import = sub.add_parser("import-csv", help="Mass-Pairing-CSV importieren")
p_import.add_argument("path", type=Path)
p_import.add_argument("--dry-run", action="store_true",
                      help="Nur Validierung, keine DB-Inserts, keine Downlinks")
p_import.add_argument("--no-eingangstest", action="store_true",
                      help="Devices anlegen, aber 25/10-Eingangstest überspringen")

p_test = sub.add_parser("test-device", help="Vicki-Eingangstest auf bereits gepairtem Device")
p_test.add_argument("dev_eui")
p_test.add_argument("--sleep-secs", type=int, default=60)

p_retire = sub.add_parser("retire-device", help="Device retiren (Tausch-Pfad, lokal über DB)")
p_retire.add_argument("dev_eui")
p_retire.add_argument("--replaced-by", help="DevEUI des neuen Vickis (optional)")
p_retire.add_argument("--reason", default="hardware_swap")
```

**Aufruf-Pattern (Brief-konsistent, RUNBOOK §10h ergänzen):**

```
# Auf heizung-test, via SSH + Tailscale
docker cp pairing-batch.csv deploy-api-1:/tmp/pairing.csv
docker exec deploy-api-1 python scripts/pair_devices.py import-csv /tmp/pairing.csv --dry-run
docker exec deploy-api-1 python scripts/pair_devices.py import-csv /tmp/pairing.csv
docker exec deploy-api-1 python scripts/pair_devices.py test-device 70b3d52dd3034de4
```

`backend/scripts/README.md` um Eintrag für `pair_devices.py` erweitern.

---

## H. Migrations-Konvention

**Files:** `backend/alembic/versions/0015_health_state.py`, `0016_manual_override_zone_id.py`, `0017_room_guest_override_blocked.py`

### Etablierte Patterns

- **`0015_health_state`** — Enum-VARCHAR-Spalte (NOT NULL) mit permanentem `server_default='silent'` + CHECK-Constraint. Backfill atomar mit `add_column`. Downgrade dropt Constraint + Spalte in umgekehrter Reihenfolge.
- **`0016_manual_override_zone_id`** — nullable FK-Spalte (`ondelete="SET NULL"`) + Partial-Index mit `postgresql_where`. Nullable braucht keinen Backfill.
- **`0017_room_guest_override_blocked`** — Boolean NOT NULL mit `server_default=sa.text("false")` direkt gefolgt von `alter_column server_default=None`. Default lebt im ORM (`mapped_column(default=False)`). §5.49-Pattern (Raw-SQL-Test-Inserts müssen Spalte mit-setzen). §5.56-Pattern (Migration-Roundtrip-Tests revisionsabhängig anpassen).

### Empfehlung Migration 0018-Slot

Sprint-13-Schema-Erweiterung — Device-Lifecycle:

- **Revision-ID:** `0018_device_retired_at`
- **Down-Revision:** `0017_room_guest_override_blocked`
- **Felder:** `retired_at TIMESTAMP TZ NULL`, `retired_reason VARCHAR(50) NULL`, `replaced_by_device_id INT FK device.id NULL` (ON DELETE SET NULL — selbst-referenzielle Lazy-Migration ohne Cascade-Risiko).
- **Index:** Partial-Unique `ix_device_dev_eui_active ON device(dev_eui) WHERE retired_at IS NULL`. Vor `create_index()`: `op.drop_constraint("uq_device_dev_eui", "device", type_="unique")` aus Migration 0001 entfernen. Performance-Partial-Index auf `heating_zone_id` ist verworfen (S6 — Mikro-Optimierung ohne realen Nutzen bei ~100 Devices, FK-Index reicht).
- **§5.56-Roundtrip-Check:** Spalten sind nullable → Raw-SQL-Test-Inserts in `tests/test_migrations_roundtrip.py` + `tests/test_device_*.py` brauchen **keine** Anpassung. Modul-Docstring-§5.49-Hinweis nicht erforderlich. Hinweis: `DROP COLUMN is_active` + Constraint-Swap auf `dev_eui` **doch** roundtrip-relevant — Downgrade muss `uq_device_dev_eui` wiederherstellen und `is_active`-Spalte mit `server_default=true` zurückbringen.
- **§5.50-Lokal-DB-Verify (Pflicht):** vor Push gegen lokales `timescaledb:latest-pg16` migrieren + zurück (`alembic upgrade head` + `alembic downgrade 0017_room_guest_override_blocked` + `alembic upgrade head`), kein Schema-Drift, alle bestehenden DB-Tests grün.

```python
"""device.retired_at + lifecycle-Felder (Sprint 13, AE-57).

Erweitert ``device`` um den Lifecycle-Marker für Retire+Pair-New aus
STRATEGIE-THERMOSTAT-ZUORDNUNG §15 (Vicki-Tausch ohne Historien-Verlust).

Backward-Compat: alle bestehenden Rows bleiben ``retired_at=NULL``
(aktiv). Kein Backfill, kein Server-Default — Spalten sind nullable und
NULL bedeutet semantisch "Device ist aktiv".

Partial-Unique-Index ``ix_device_dev_eui_active`` ersetzt die Voll-
Unique-Constraint ``uq_device_dev_eui`` aus Migration 0001 und erlaubt
mehrere retired Rows mit gleicher DevEUI (Hardware-Drift-Forensik +
Re-Pair nach Werksreset), garantiert Eindeutigkeit nur unter aktiven
Rows.

Revision ID: 0018_device_retired_at
Revises: 0017_room_guest_override_blocked
Create Date: 2026-05-21
"""
```

---

## I. Zimmer-Inventar Live-Check

**Status:** SSH-Befehle formuliert, **nicht ausgeführt** (Brief: User pastet in SSH-Session).

`Room.number` ist VARCHAR(20) (CLAUDE.md §5.49 belegt), `heating_zone.name` ist VARCHAR(100). DB-Zugang heute über `docker exec deploy-db-1 psql` (RUNBOOK §10, OP-5 DB-Tunnel-Sektion fehlt im Backlog).

### SSH-Befehle (User-Aktion)

```bash
# SSH (heizung-test, root)
ssh -i ~/.ssh/id_ed25519_heizung heizung-test

# Zimmer-Inventar
docker exec deploy-db-1 psql -U heizung -d heizung -c "
SELECT COUNT(*) AS room_count,
       STRING_AGG(number, ',' ORDER BY number) AS room_numbers
FROM room;
"

# Zonen pro Zimmer (Mehrfach-Vicki-Verteilung sichtbar)
docker exec deploy-db-1 psql -U heizung -d heizung -c "
SELECT room_id,
       COUNT(*) AS zone_count,
       STRING_AGG(name, ',' ORDER BY name) AS zone_names
FROM heating_zone
GROUP BY room_id
ORDER BY room_id;
"

# Bonus: Devices-pro-Zone (sieht den aktuellen Mehrfach-Vicki-Stand)
docker exec deploy-db-1 psql -U heizung -d heizung -c "
SELECT z.room_id,
       z.id AS zone_id,
       z.name AS zone_name,
       COUNT(d.id) AS device_count,
       STRING_AGG(d.label, ',' ORDER BY d.label NULLS LAST) AS device_labels
FROM heating_zone z
LEFT JOIN device d ON d.heating_zone_id = z.id
GROUP BY z.room_id, z.id, z.name
ORDER BY z.room_id, z.id;
"
```

### Offene Frage (Strategie-Chat)

> **User-Input erbeten:** Ergebnis der drei psql-Queries aus heizung-test, damit Sprint 13a (Pre-Pairing-Skript) den realistischen Volume-Test (45 Zimmer, ~100 Vickis aus STRATEGIE-THERMOSTAT-ZUORDNUNG §14) gegen den aktuellen Stand kalibrieren kann.

---

## J. AE-57-Lücken-Status

### Befund

- **Globaler Repo-Grep** auf `AE-57`: Treffer nur in `STATUS.md:1911` („AE-57-Luecken-Klaerung (Doku-Hygiene-Backlog)") im Sprint-12c-Block. **Kein** Treffer in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`.
- **Git-Log:** `git log --all --grep="AE-57" -- docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` und `git log --all -S "AE-57" -- docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` liefern **beide leer**. Der Slot wurde nie vergeben — **nicht** vergeben und wieder rausgenommen, sondern schlicht übersprungen (zwischen AE-56 Window-State-Modul Sprint 12 und AE-58 Override-Modell Sprint 12a, beide am 2026-05-15..20 entstanden, ist die Slot-Nummer leer geblieben).

### Empfehlung

**AE-57 für Sprint 13 vergeben:** „Device-Lifecycle: Retire + Pair-New, Zone als stabiler Historie-Anker". Löst den Hygiene-Backlog-Punkt **und** dokumentiert die Sprint-13-Architektur (Schema-Erweiterung + Endpoint + Engine-Query-Filter).

ADR-Skizze (Detail-Ausarbeitung in Sprint-13-T1):

```
# AE-57 — Device-Lifecycle: Retire + Pair-New, Zone als stabiler Historie-Anker

**Datum:** 2026-05-21 (mit Sprint 13 Phase 0)
**Status:** Beschlossen
**Bezug:** AE-43 (Geräte-Lifecycle UI), AE-51 (Zone-Aggregat), AE-58
(Override-Modell), STRATEGIE-THERMOSTAT-ZUORDNUNG §15 (Migrations-Plan)

## Kontext
Im September 2026 paart der Hotelier ~100 Vickis am Office-Laptop ein.
Über die Heizperiode 2026/27 wird der eine oder andere Vicki ausfallen
(Batterie, Hardware, Funk) und durch einen neuen ersetzt werden. Die
Historie der sensor_readings + control_commands gehört zur Zone, nicht
zum spezifischen Hardware-Gerät — sonst gehen Trend-Analytics bei jedem
Tausch verloren.

## Entscheidung
1. `device.retired_at: TIMESTAMP TZ NULL` als Lifecycle-Marker.
   NULL = aktiv, gesetzt = retired (unwiderruflich).
2. Tausch-Endpoint `POST /api/v1/devices/{id}/retire` setzt atomar
   `retired_at=now`, `is_active=False`, `heating_zone_id=NULL`,
   optional `replaced_by_device_id=<neuer>`. BusinessAudit
   `DEVICE_RETIRED` in derselben Transaktion + Engine-Tick.
3. Pair-New = neuer Device-Row mit eigenem dev_eui, an gleiche Zone
   gemappt. sensor_reading.device_id zeigt weiter auf alte Row (Historie).
4. Engine-Queries filtern `Device.retired_at IS NULL` an den
   S4-kritischen Stellen (siehe Phase-0-Bericht §L).
5. BusinessAudit-Actions: DEVICE_PAIRED, DEVICE_RETIRED, DEVICE_REPLACED,
   PAIRING_BATCH_IMPORTED (siehe Phase-0-Bericht §K).
6. Bestehender Detach-Endpoint (Sprint 9.13) bleibt für "temporäre
   Abnahme" (Wartung, Umzug) erhalten — semantisch separiert von Retire.

## Konsequenzen
- Migration 0018 (`device.retired_at`, `retired_reason`,
  `replaced_by_device_id`, Partial-Index).
- Engine-Query-Filter-Anpassung an 5 Stellen
  (`engine_tasks._get_devices_for_zone`,
  `rules/engine.layer_device_detached`,
  `rules/window_state.detect_open_window_zones`,
  `services/device_adapter._device_room_id` + `_device_zone_id`).
- Frontend-Anpassung (Sprint 13 oder folgender): Geräte-Liste filtert
  `retired_at IS NULL` als Default, mit Toggle "Auch retirte zeigen".
- §5.49 / §5.56 nicht aktiv betroffen (nullable Spalten).
```

---

## K. BusinessAudit-Action-Pattern für Device-Events

**File:** `backend/src/heizung/models/business_audit.py`, Schreibhilfe in `services/business_audit_service.py`

### Befund

`BusinessAudit.action` ist `VARCHAR(64) NOT NULL`. Bestehende Werte (Grep auf `action=`):

| Action | Eingeführt in | target_type |
|---|---|---|
| `OCCUPANCY_CREATE` | Sprint 9.17 | `occupancy` |
| `OCCUPANCY_CANCEL` | Sprint 9.17 | `occupancy` |
| `MANUAL_OVERRIDE_SET` | Sprint 9.17 | `room` |
| `MANUAL_OVERRIDE_CLEAR` | Sprint 9.17 | `room` |
| `PASSWORD_CHANGE` | Sprint 9.17 | `user` |
| `PASSWORD_RESET_BY_ADMIN` | Sprint 9.17 | `user` |
| `ROOM_OVERRIDE_BLOCK_TOGGLED` | Sprint 12c (AE-58) | `room` |

Konvention: `OBJEKT_VERB`, UPPER_SNAKE_CASE, max 64 chars. Schreibung atomar in der Transaktion (`record_business_action` in `services/business_audit_service.py`, analog `config_audit_service` aus AE-46).

### Empfehlung Sprint 13 Actions

| Action | Länge | target_type | new_value JSONB (Skizze) |
|---|---|---|---|
| `DEVICE_PAIRED` | 13 | `device` | `{"dev_eui": "...", "label": "...", "zone_id": <int>, "source": "csv_import" \| "manual"}` |
| `DEVICE_RETIRED` | 14 | `device` | `{"retired_at": "<iso>", "reason": "hardware_swap", "replaced_by_device_id": <id_or_null>, "prev_zone_id": <int>}` plus `old_value={"is_active": true, "heating_zone_id": <prev>}` |
| `DEVICE_REPLACED` | 15 | `device` (= **neuer** device_id) | `{"replaces_device_id": <alter_id>, "heating_zone_id": <int>}` — Cross-Ref-Eintrag zusätzlich zu `DEVICE_RETIRED` |
| `PAIRING_BATCH_IMPORTED` | 22 | `device` (target_id=NULL — Batch-Operation) | `{"count": <int>, "source_file": "<basename>", "source_sha256": "<hex64>", "imported_device_ids": [<list>], "skipped_rows": [{"line": <int>, "reason": "..."}]}` |

Alle 4 Actions unter 64 chars, `OBJEKT_VERB`-Konvention respektiert.

### Offene Frage Strategie-Chat

> **Entscheidung gewünscht:** `DEVICE_REPLACED` als **eigener** Audit-Eintrag (Vorteil: Cross-Ref-Suche pro neuem Device, intuitive History-Sicht) ODER **nur** `DEVICE_RETIRED` mit `new_value.replaced_by_device_id` (Vorteil: weniger Rows, ein Tausch = ein Eintrag)?
>
> Empfehlung Phase 0: **beides** — `DEVICE_RETIRED` auf alter `target_id`, `DEVICE_REPLACED` auf neuer `target_id` (Doppelung okay; Doppelte Audit-Sicht ist hier sinnvoll, weil sowohl der alte als auch der neue Vicki im Audit-Trail eines Tausches finden müssen).

---

## L. Engine-Query-Audit für Retire+Pair-New-Sicherheit

**File:** `backend/src/heizung/rules/engine.py` (+ Helper in `rules/window_state.py`, `rules/inferred_window.py`).

### Befund — Device-Iterationen / Device-JOINs

`_load_room_context` (Zeile 809–861) lädt heute **keine** Devices — nur `Room` + `RoomType` + `RuleConfig` (über alle drei Scopes) + Sommermodus-Flag + nächste Belegung. Device-Lookup passiert in den Layer-Funktionen selbst (lazy).

Liste aller Engine-internen Device-Stellen, sortiert nach S4-Risiko:

| # | Stelle | Heute filtert auf | Nach Retire+Pair-New zwingend Filter `retired_at IS NULL`? |
|---|---|---|---|
| **L-1** | `tasks/engine_tasks.py:349-355` `_get_devices_for_zone` (Downlink-Dispatch zu jedem Vicki einer Zone) | `heating_zone_id == zone_id AND is_active.is_(True) AND health_state == 'healthy'` | **JA — S4-Pflicht.** Heute durch `is_active` indirekt geschützt, weil kein Code-Pfad `is_active=False` setzt. Sobald Retire-Endpoint kommt, muss `retired_at IS NULL` explizit. |
| **L-2** | `rules/engine.py:617-622` `layer_device_detached` Device-Load | `HeatingZone.room_id == room_id` (kein Lifecycle-Filter) | **JA.** Sonst Detached-AND-Trigger inkonsistent (retirter Vicki ohne Readings = „unklar", Trigger feuert nicht — aber Diagnose-Detail im event_log irreführend). |
| **L-3** | `rules/engine.py:644-657` `layer_device_detached` Reading-Subquery | analog L-2 | **JA.** Gleicher Pfad. |
| **L-4** | `rules/window_state.py:73-80` `detect_open_window_zones` (Layer-4-Source + Override-POST-Reject) | `HeatingZone.room_id == room_id AND Device.health_state == 'healthy'` | **JA.** S4-relevant: retirter Vicki mit gelegentlichem Uplink + altem Reading könnte Layer 4 fälschlich auf Frostschutz drücken. |
| **L-5** | `rules/engine.py:540-553` `layer_window_open` no-op-Diagnose | `Device.health_state == 'healthy'` | empfohlen — niedrig (nur Diagnose-Text). |
| **L-6** | `rules/engine.py:887-892` `_last_command_for_room` deprecated | kein Filter | niedrig — deprecated audit-only. |
| **L-7** | `rules/inferred_window.py:97-115, 105-113, 141-145` passive Diagnose | kein Filter | niedrig — read-only, kein Setpoint-Pfad. |
| **L-8** | `services/device_adapter.py:107-114` `_device_room_id` (Override-Insert beim Vicki-Drehring) | `Device.id == device_id` | **JA.** Sonst Override-Anlage durch retirten Vicki, falls dieser noch funkt. |
| **L-9** | `services/device_adapter.py:128` `_device_zone_id` | analog L-8 | **JA.** Gleicher Pfad. |
| **L-10** | `services/mqtt_subscriber.py:262-265` `evaluate_room.delay`-Trigger via Zone-Lookup | kein Filter | empfohlen — Engine-Tick auf retirten Uplink wäre unnötig. Durch L-1 ohnehin folgenlos für S4. |
| **L-11** | `tasks/health_tasks.py:172` `select(Device)` (Health-Compute über alle Devices) | kein Filter | optional — Health-Compute für retired ist nutzlos, aber kein Schaden. |
| **L-12** | `services/mqtt_subscriber.py:192,385` `select(Device.id).where(dev_eui == ...)` (Reading-Persisting + Override-Adapter-Aufruf) | `dev_eui == dev_eui` | **bewusst kein Filter** — Readings persistieren auch für retirte Devices (Historie). Override-Pfad ist durch L-8 + L-9 abgesichert. |
| **L-13** | `api/v1/devices.py:135` List-View | optional `is_active`-Query-Param | UI-Empfehlung: neuer Query-Param `include_retired=False` (Default). |

### Risiko-Tabelle (S4-Fokus)

| # | Was passiert ohne `retired_at IS NULL`-Filter | S4? |
|---|---|---|
| L-1 | **Doppelter Setpoint-Downlink an alten + neuen Vicki**, wenn beide kurz parallel `heating_zone_id == zone_id AND is_active=True AND health_state='healthy'` haben (Race-Window beim Tausch). S4-Verstoß. | **hoch** |
| L-2/L-3 | Inkonsistente Detached-Detection: alter Vicki ohne frische Readings → „unklar" → AND-Trigger feuert nicht. Diagnose-Detail (`extras.detached_devices`) zeigt retirten Vicki, irreführend. | niedrig (Trigger), mittel (Audit) |
| L-4 | Layer 4 sieht retirtes Device noch als „healthy mit Reading" und triggert fälschlich Window-Open → Setpoint auf Frostschutz/Setback. **S4-relevant**, weil Setpoint folgt. | mittel |
| L-8/L-9 | Vicki-Drehring eines retirten Devices triggert Override-Insert. Anti-Strategie (Retire war ja gewollt), Audit-Verschmutzung. | niedrig (Override-Audit) |

### Konsequenz für Sprint 13

Migration 0018 (Phase A) + Code-Anpassung an **L-1, L-2, L-3, L-4, L-8, L-9** als **zusammenhängende** Task. Defensiv-Filter an L-5, L-10, L-11 als „while-we-are-at-it"-Beigabe (geringer Aufwand, S5-Defensive). Tests in `tests/test_engine_retired_*.py` pro Layer mit explizitem Retired-Fixture.

§5.47-Pflicht: Helper-Anpassung verhaltensneutral für nicht-retirte Fälle — bestehende Test-Suite (insbesondere `test_engine_layer4.py`, `test_engine_multivicki_write.py`, `test_engine_aggregate.py`) bleibt ohne Anpassung grün.

---

## Offene Fragen an Strategie-Chat

1. **(I)** Zimmer-Inventar-Live-Check (45 Zimmer, ~100 Vickis Vollausbau-Ziel) — User pastet psql-Output aus heizung-test, damit Sprint-13a-Skript-Skizze gegen realistischen Volume kalibriert ist.
2. **(K)** `DEVICE_REPLACED` als eigener Audit-Eintrag (Cross-Ref auf neuem Device) ODER nur als `DEVICE_RETIRED.new_value.replaced_by_device_id`? Phase-0-Empfehlung: beides (Doppelter Audit-Eintrag, weil Tausch zwei Devices betrifft).
3. **(E)** Pre-Pairing-Skript läuft am **Office-Laptop** (SSH-Tunnel zu heizung-test) ODER **im API-Container** (`docker exec`)? Phase-0-Empfehlung: `docker exec` (einfacher für Hotelier, kein lokaler venv, Settings out-of-the-box).
4. **(J)** AE-57-Slot für Device-Lifecycle vergeben? Phase-0-Empfehlung: ja (löst Hygiene-Backlog + dokumentiert Sprint-13-Architektur).
5. **(A)** `is_active`-Spalte parallel zu `retired_at` behalten ODER mit Sprint 13 entfernen? Phase-0-Empfehlung: vorerst behalten (Backward-Compat, kein aktiver Schreibpfad → kein Drift-Risiko), Entfernung als eigener Cleanup-Sprint nach Sprint 14b (arc42-Konsolidierung).
6. **(F)** CSV-Encoding `utf-8`-Pflicht oder optional `utf-8-sig` (BOM-tolerant, weil Excel manchmal BOM schreibt)? Phase-0-Empfehlung: `utf-8-sig` zum Lesen (BOM-tolerant), `utf-8` ohne BOM für Template-Beispiele.

---

## Empfehlung Sprint-13-light-Cut

### Hygiene-Mini-Sprint vor Sprint 13a (empfohlen, ~2-4 h)

- **H1** AE-57-Slot vergeben: ADR-Eintrag in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` für „Device-Lifecycle: Retire + Pair-New, Zone als stabiler Historie-Anker" (Volltext siehe §J-Skizze).
- **H2** `.env.example` ergänzen: `CHIRPSTACK_APP_ID=` (heute fehlt es; `chirpstack_app_id`-Default ist nicht-produktiv).
- **H3** RUNBOOK §10h.2 (Mass-Pairing-CSV-Format) konkretisieren: CSV-Header-Definition + Beispiel-Datei `docs/examples/pairing-batch-example.csv` ablegen.
- **H4** AE-58-Verweise: `docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md` §15 um Pre-Pairing-CSV-Schritt erweitern (heute: nur Hands-on, kein CSV-Pfad).

### Sprint 13a — Pre-Pairing-Skript (~6–8 h)

- **T1** Migration `0018_device_retired_at.py` (Schema-Erweiterung, §H-Skizze).
- **T2** `backend/scripts/pair_devices.py` mit Subcommands `import-csv`, `test-device`, `retire-device` (§G-Skizze).
- **T3** Pydantic-Row-Modell `PairingCsvRow` + Parser-Helper in `backend/src/heizung/services/pairing_csv.py` (§F-Skizze).
- **T4** Service-Helper `pair_device_from_row` (idempotent, BusinessAudit `DEVICE_PAIRED`) + `retire_device` (BusinessAudit `DEVICE_RETIRED`).
- **T5** Eingangstest-Logik: `set_open_window_detection(enabled=True, 10, Decimal("1.5"))` → sleep 5 s → `send_setpoint(25)` → sleep 60 s → `send_setpoint(10)` → sleep 60 s. Audit `DEVICE_PAIRED.new_value.eingangstest_ok=True`.
- **T6** Tests: `tests/test_pairing_csv.py` (Validation, Hex-Pattern, Duplikate, ungültige Zone), `tests/test_pair_devices_script.py` (Smoke gegen Test-DB).
- **T7** Doku-Updates: STATUS §2as, SPRINT-PLAN, RUNBOOK §10h.2, CLAUDE.md ggf. neue Lesson.

### Sprint 13b — Tausch-Endpoint + Frontend-Dialog (~6–8 h)

- **T1** Endpoint `POST /api/v1/devices/{id}/retire` (`require_admin`, atomare Transaktion: `retired_at=now`, `is_active=False`, `heating_zone_id=NULL`, optional `replaced_by_device_id`, BusinessAudit `DEVICE_RETIRED`, optional `DEVICE_REPLACED` bei vorhandenem `replaced_by`).
- **T2** Engine-Query-Filter `retired_at IS NULL` an L-1, L-2, L-3, L-4, L-8, L-9 ergänzen. §5.47-Pflicht: bestehende Tests bleiben grün.
- **T3** Frontend-Dialog im Geräte-Detail: „Vicki ersetzen" → DevEUI-Eingabe für neuen Vicki (optional) + Begründung. Submit ruft `POST /retire` + zeigt Toast „Vicki retired, neuer Vicki kann jetzt gepairt werden".
- **T4** `api/v1/devices.py` List-View: Query-Param `include_retired=False` (Default), UI-Toggle „Auch retirte anzeigen".
- **T5** Tests: `tests/test_api_devices_retire.py`, Engine-Tests pro Lifecycle-Filter (L-1, L-4 prioritär).
- **T6** Playwright-E2E: Tausch-Flow (Retire → neuer Vicki anlegen → Zone-Re-Assign → Engine-Tick verifiziert).
- **T7** Doku-Updates analog 13a-T7.

### Tag-Plan

- Sprint 13a → `v0.1.18a-pre-pairing-script`
- Sprint 13b → `v0.1.18-pairing-wizard` (vereinheitlicht mit SPRINT-PLAN-Tag)

Phase 4b (September Pre-Pairing) ist 13a + 13b zusammen mit Pairing-Wizard-UI (Sprint 13 SPRINT-PLAN-Block, Wizard-Stufen ChirpStack/Zimmer/Zone/Label aus AE-43). 13a + 13b liefern die Backend-Voraussetzung; der Wizard im Frontend kann separat in 13c folgen.

---

## Stop-Point (Brief-konform)

Phase-0-Bericht abgelegt unter `docs/features/2026-05-21-sprint13-phase0-quellcheck.md`. Branch `chore/sprint13-phase0` mit WIP-Commit, **kein PR**. Strategie-Chat reviewt diesen Bericht und gibt Hygiene-Mini-Sprint-Brief + Sprint-13a-Brief frei.

---

## Anhang — `is_active`-Befund (Hygiene-Mini-Sprint 2026-05-21, Strategie-Chat-Pflicht-Check)

Der Hygiene-Mini-Sprint-Brief verlangte vor AE-57-Commit einen erneuten Grep zur Verifikation, dass die `is_active`-Spalte ausschliesslich auf `device` für AE-57 relevant ist und die übrigen Treffer **out of scope** bleiben.

### Grep-Ergebnis `is_active` in `backend/src/heizung/models/`

| Tabelle | Datei : Zeile | AE-57-Scope |
|---|---|---|
| `device` | `models/device.py:83` | **IN-SCOPE** (Sprint 13b Migration 0018 dropt, ersetzt durch `retired_at`) |
| `user` | `models/user.py:42` | out-of-scope (Auth, Sprint 9.17) |
| `season` | `models/season.py:44` | out-of-scope (Saison-Aktivierung, Sprint 8) |
| `manual_setpoint_event` | `models/manual_setpoint_event.py:73` | out-of-scope für AE-57 — **gesondert** als ganze Tabelle in Hygiene-Sprint T3 (B-12a-1, Migration 0019) gedropped |
| `occupancy` | `models/occupancy.py:59` | out-of-scope (Belegung, Sprint 8) |
| `scenario_assignment` | `models/scenario_assignment.py:72` | out-of-scope (Szenarien, Sprint 9.16) |

### Grep-Ergebnis `Device.is_active` als Code-Filter (`backend/src/heizung/`)

| Stelle | Zweck |
|---|---|
| `tasks/engine_tasks.py:352` (`_get_devices_for_zone`) | S4-Filter im Downlink-Dispatch |
| `api/v1/devices.py:137` | optionaler UI-Filter-Query-Param |

Nur Lese-Pfade. Kein aktiver Schreibpfad (kein Endpoint, kein Service setzt `device.is_active=False`). Default ist seit Migration 0001 `true`, alle Bestands-Rows haben `true`.

### Bestätigung

- AE-57 ändert ausschliesslich Semantik für `device`. Andere `is_active`-Vorkommen sind eigene Tabellen mit eigenen Domänen (User-Aktivierung, Saison-Aktivität, Belegungs-Aktivität, Szenario-Aktivierung) und bleiben unangetastet.
- Sprint 13b Migration 0018 ist gebündelt: `ADD COLUMN retired_at, retired_reason, replaced_by_device_id` (nullable) **plus** `DROP COLUMN device.is_active` **plus** Umstellung der zwei oben gelisteten Read-Stellen auf `retired_at IS NULL`.
- Bis 13b-Merge bleibt `device.is_active` der aktive S4-Filter (Brief-Übergangs-Klausel im AE-57-Block).

### Strategie-Chat-Auflösung Partial-Index-Variante (2026-05-21)

Zwei Varianten standen im ersten AE-57-Entwurf gegeneinander:

| Variante | Spalte | Zweck | Status |
|---|---|---|---|
| 1 | `dev_eui` `UNIQUE WHERE retired_at IS NULL` | Eindeutigkeit nur unter aktiven Rows; erlaubt DevEUI-Wiederverwendung nach Werksreset; Forensik-Anker für retired Rows | **verbindlich** |
| 2 | `heating_zone_id` `WHERE retired_at IS NULL` | Performance-Index für „aktive Devices einer Zone"-Queries | **verworfen** |

Begründung Variante 2 verworfen: Mikro-Optimierung ohne realen Nutzen bei ~100 Devices (S6 — Komplexität trägt Beweislast). Engine-Queries laufen über bestehenden FK-Index `device.heating_zone_id`. Aktive-Filter-Selektivität bei wenigen retireten Rows nicht relevant.

Konsequenz: Migration 0018 muss zusätzlich die Voll-Unique-Constraint `uq_device_dev_eui` (Migration 0001) per `op.drop_constraint()` entfernen, bevor der Partial-Unique-Index angelegt wird. Downgrade-Pfad stellt die Voll-Constraint wieder her.

AE-57-Block in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` enthält den verbindlichen Wortlaut + Implementierungs-Skizze (Commit `4ace2a9` auf `chore/sprint13-hygiene`).
