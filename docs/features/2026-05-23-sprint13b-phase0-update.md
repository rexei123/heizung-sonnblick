# Sprint 13b Phase-0-Update gegen develop @ 4c1dcc5

**Stand:** 2026-05-23
**Vorgaenger:** `docs/features/2026-05-21-sprint13-phase0-quellcheck.md` (gilt als Basis)
**Zweck:** Schema-Drift-Check + Frontend-Audit vor Sprint-13b.1-Implementierung. Pruefen, ob `§L`-Liste (5 Pflicht-Filter-Stellen) noch vollstaendig ist und ob Frontend-Annahmen fuer 13b.2 (Tausch-Button auf Zimmer-Detail, Pool-Dropdown via shadcn Dialog) zum aktuellen develop-Stand passen.
**Rolle:** Code (Read-Only-Audit, Autonomiestufe 3)
**Branch:** `docs/sprint13b-phase0-update` (ein Doku-Commit, kein Code-Touch)
**Verbindliche Strategie-Entscheidungen 2026-05-23 (aus Brief-Header):**

- Sub-Split 13b.1 Backend / 13b.2 Frontend Pflicht
- Migration 0018 minimal (KEIN `pairing_status`-Feld)
- Workflow A entfaellt komplett (CLI deckt Pool-Refill)
- Workflow B als Confirm-Dialog mit Pool-Dropdown (shadcn Dialog, KEIN Drawer)
- Tausch-Button auf Zimmer-Detail-Seite, nicht auf Geraete-Detail

Phase-0-Update prueft NUR Vertraeglichkeit gegen aktuellen develop-Stand und schlaegt KEINE Architektur-Aenderungen vor.

---

## 1. Audit 1 — is_active-Lese-Stellen heute

`git grep -n "is_active" backend/src/heizung/` liefert Treffer ueber mehrere Tabellen. Hier nur die `Device.is_active`-relevanten Stellen (out-of-scope-Tabellen `user`, `occupancy`, `season`, `scenario_assignment` ignoriert, weil sie eigene Domaenen sind und nicht von AE-57 beruehrt werden).

| Datei : Zeile | Kontext | §L-Match | Lifecycle-Filter-Pflicht nach AE-57 |
|---|---|---|---|
| `models/device.py:83` | Modell-Definition `is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)` | §L-Schema | DROP in Migration 0018 (AE-57 Entscheidung 2) |
| `schemas/device.py:42` | Pydantic-Schema `DeviceCreate.is_active: bool = True` | §L-Schema | bleibt bis 13b.1-Schemata-Update (Default `True`, bei `retired_at IS NULL`-Mapping obsolet) |
| `schemas/device.py:67` | `DeviceUpdate.is_active: bool \| None = None` | §L-Schema | wie 42 |
| `schemas/device.py:88` | `DeviceRead.is_active: bool` | §L-Schema | wie 42 |
| `tasks/engine_tasks.py:341` | Docstring zu `_get_devices_for_zone` Filter-Konvention | §L #1 | Pflicht |
| `tasks/engine_tasks.py:352` | **FILTER** `select(Device).where(Device.is_active.is_(True))` im Downlink-Dispatch | **§L #1, S4-kritisch** | **Pflicht (Single-Source der Helper-Migration)** |
| `api/v1/devices.py:126` | Query-Param-Declaration `is_active: bool \| None = Query(...)` (Listen-View) | §L #13 | wird ersetzt durch `include_retired=False`-Default + `retired_at IS NULL`-Filter |
| `api/v1/devices.py:136` | If-Wrapper `if is_active is not None: ...` | §L #13 | wird ersetzt durch Default-Pflicht-Filter |
| `api/v1/devices.py:137` | **FILTER** `stmt = stmt.where(Device.is_active == is_active)` | §L #13 | siehe 136 |
| `rules/window_state.py:44` | Docstring-Note "impliziter Filter ueber Device-Records" | (in §L #6 erwaehnt, kein expliziter Filter heute) | Pflicht (S4-relevant per §L #6) |
| **`scripts/pair_devices.py:243`** | **NEU Sprint 13a** — Docstring zu `_cmd_list_pool` | **NICHT in §L** | Pflicht (Konsistenz mit Engine + UI) |
| **`scripts/pair_devices.py:245`** | **NEU Sprint 13a** — Docstring-Hinweis `"is_active=True ist AE-57-Uebergangs-Klausel (Sprint 13b ..."` | **NICHT in §L** | bereits AE-57-aware kommentiert; muss umgestellt werden |
| **`scripts/pair_devices.py:253`** | **NEU Sprint 13a** — **FILTER** `.where(Device.is_active.is_(True))` in `list-pool`-Subcommand | **NICHT in §L** | **Pflicht (CLI-Konsistenz, kein S4 aber UI-Wahrheit)** |
| **`scripts/pair_devices.py:325`** | **NEU Sprint 13a** — Help-String-Text "Reserve-Pool-Devices (heating_zone_id IS NULL AND is_active=True)" | **NICHT in §L** | Doku-Update (Help-Text muss `retired_at IS NULL`-Semantik widerspiegeln) |
| **`scripts/pairing/csv_parser.py:184`** | **NEU Sprint 13a** — Docstring-Note `"Filter NICHT auf is_active oder retired_at"` (DevEUI-Duplikat-Check ist global) | NICHT in §L | bewusst kein Filter (Voll-Unique heute, Partial-Unique 13b) — Doku-Update nach 13b.1 (zweite Klausel entfaellt) |

**Andere Tabellen** (out-of-scope, aber zur Vollstaendigkeit notiert): `user.is_active`, `occupancy.is_active`, `season.is_active`, `scenario_assignment.is_active` — alle haben eigene Domaenen-Semantik und sind nicht von AE-57 betroffen (siehe Phase-0-Bericht 2026-05-21 §Anhang).

**Befund:** Alte `§L`-Liste hatte 13 Stellen, davon 5 S4-Pflicht-Filter. Sprint 13a hat **4 neue Doku-/Filter-Stellen in `pair_devices.py` + 1 in `csv_parser.py`** dazugebracht, davon **eine** als echter Filter (`pair_devices.py:253`). Bestehende `§L`-Pflicht-Stellen sind alle unveraendert vorhanden.

---

## 2. Audit 2 — Neue device-Stellen aus Sprint 13a

Sub-Package `backend/src/heizung/scripts/pairing/` (Sprint 13a T2-T5):

| Datei | Device-Bezug | Filter heute | Lifecycle-Filter nach 13b.1? |
|---|---|---|---|
| `__init__.py` | Re-Exports der Sub-Module | — | — |
| `csv_row.py` | Pydantic-Modell `PairingCsvRow`, kein DB-Query | — | — |
| `exceptions.py` | Exception-Klassen, kein DB-Query | — | — |
| `csv_parser.py:205` | `select(Device.id, Device.dev_eui).where(Device.dev_eui.in_(dev_euis))` (`check_dev_eui_duplicates`) | **kein Filter** (Docstring: "DevEUI global einzigartig per Voll-Unique-Constraint, bis 13b auf Partial-Unique") | bleibt ohne Filter — Pflicht ist nur das Partial-Unique-Index-Update (Migration 0018, AE-57 Entscheidung 1) |
| `pairing_service.py:135` | `select(Device.id).where(Device.dev_eui == row.dev_eui)` (Gate 1 Existenz-Check) | **kein Filter** (intentional: Re-Pair-Schutz greift global, retired Devices duerfen nicht denselben aktiven DevEUI haben — wird durch Partial-Unique-Index erzwungen) | bleibt ohne Filter |
| `inbound_test.py` | Importiert `Device` nur als Typ-Annotation; kein DB-Query (Device-Instanz wird von Caller vorgeladen uebergeben) | — | — |

Plus CLI-Entrypoint `scripts/pair_devices.py`:

| Datei : Zeile | Device-Bezug | Filter heute | Lifecycle-Filter nach 13b.1? |
|---|---|---|---|
| `pair_devices.py:130` | `select(Device).where(Device.dev_eui == dev_eui)` in `_resolve_device` (Auto-Detect fuer `test`-Subcommand) | **kein Filter** (Auto-Detect-Lookup ueber den vom Mitarbeiter eingegebenen Identifier, retired ist nicht relevant — Mitarbeiter sucht spezifisches Geraet) | bleibt ohne Filter — UX-Entscheidung: User darf retired Devices auflisten/finden, nur nicht erneut paaren |
| `pair_devices.py:251-253` | `select(Device....).where(Device.heating_zone_id.is_(None)).where(Device.is_active.is_(True))` in `_cmd_list_pool` | **AE-57-Uebergangs-Klausel-Filter** auf `is_active` | **Pflicht-Umstellung 13b.1:** `is_active.is_(True)` → `retired_at.is_(None)`. Nicht S4-kritisch, aber UI-Wahrheit (Hotelier sieht sonst retired Devices als "Reserve"). |

**Befund Audit 2:** Sprint-13a-Code ist explizit AE-57-aware (Docstrings + Help-Text-Kommentare verweisen auf "Sprint 13b Drop"). Pflicht-Umstellungen sind **1 Filter (`pair_devices.py:253`) + 4 Doku-Stellen** (Pair_devices.py:243+245+325, csv_parser.py:184). `list-pool` ist semantisch INVERS — filtert auf `heating_zone_id IS NULL AND aktiv`. Wer `retired_at IS NULL` einbaut, MUSS die Bedingung als AND, nicht OR formulieren — sonst kippt die Semantik.

---

## 3. Audit 3 — Frontend /zimmer/[id]-Stand

**Datei:** `frontend/src/app/zimmer/[id]/page.tsx` (347 Zeilen, inkl. drei Inline-Komponenten)

### Vicki-Anzeige pro Zone

**Heute room-flat, nicht zone-scoped.** Geraete-Tab rendert `<DevicesInRoom roomId={id} />` (Z.167). Die Inline-Komponente `DevicesInRoom` (Z.187-289):

- Laedt **alle** Devices via `useDevices()` (Hook aus `@/lib/api/hooks`).
- Laedt `useHeatingZones(roomId)` separat.
- Filtert Devices im Frontend: `d.heating_zone_id !== null && zoneIds.has(d.heating_zone_id)` (Z.197-200).
- Rendert als **flache Liste** mit `<ul>`, ein `<li>` pro Device. Pro Device-Row: Label, `<HardwareStatusBadge variant="compact" />`, `vendor + model + Zone-Name`, `Detail →`-Link, `<DetachButton />`.
- Pro-Zone-Kartendarstellung mit Geraete drin existiert **nicht**.

Frontend-Filter `d.heating_zone_id !== null` schliesst Pool-Devices (heating_zone_id IS NULL) heute automatisch aus der Zimmer-Detail-Sicht aus — gut.

### Einhaengepunkte fuer "Tauschen"-Button

| Stelle | Pro | Contra |
|---|---|---|
| **Pro-Device-Row, neben DetachButton (Z.264-272)** | Per-Vicki-Kontext sofort klar (vor allem bei Mehrfach-Vicki-Zonen); konsistent zur `Trennen`-Aktion-Position; Hotelier sieht "Tauschen" wo er "Trennen" erwartet | Action-Spalte kann mit Trennen + Tauschen ueberfuellen; bei vier+ Vickis pro Zone wird die Liste breit |
| **Im `DevicesInRoom`-Header neben "Geraet zuordnen" (Z.213-225)** | Globale "Tauschen"-Action zentral, ein Klick fuer den ganzen Workflow | Pre-Click-Vicki-Auswahl noetig → erhoeht Klick-Schritt-Zahl; ungewohnt fuer User, die heute `Trennen` per-Row finden |
| **Per-Zone-Karten-Header (heute nicht vorhanden, wuerde Refactor brauchen)** | Inhaltlich strukturiertere Sicht bei Mehrfach-Vicki-Zonen | Verworfen — Brief sagt 13b.2 minimal, nicht Refactor; ausserdem keine Vorbild-Komponente im Repo |

**Empfehlung:** Stelle 1 (Pro-Device-Row neben Trennen). Bei UX-Konflikt mit Trennen kann die Aktions-Spalte spaeter ein Action-Menue ersetzen (Outlook fuer 14er).

### API-Endpoint fuer Vicki-Liste

`useDevices()` ruft heute `GET /api/v1/devices` (global, ohne Room-Filter). Frontend macht das Room-Mapping selbst. Heute filtert der Endpoint auf optional `is_active`-Query-Param (siehe Audit 1 #126). **Nach 13b.1:**

- `GET /api/v1/devices` braucht **Default-Filter `retired_at IS NULL`** (Engine-relevant: bei nicht-gefilterter Liste wuerden Sprint-13b-Frontends retired Devices sehen).
- Neuer Query-Param `include_retired: bool = False` (Default) — fuer Audit-UI in Sprint 14+.
- `useDevices()` braucht **keine** Aenderung, weil Default-Filter serverseitig greift.

Stelle ist **API-relevant fuer 13b.1**, nicht erst 13b.2 (Frontend sieht den Effekt sofort).

---

## 4. Audit 4 — Design-System-Komponenten

| Komponente | Existiert | Quelle | Tailwind-Tokens | Verwendung |
|---|---|---|---|---|
| `frontend/src/components/ui/dialog.tsx` | **ja** | shadcn-Standard mit `@radix-ui/react-dialog` + `lucide-X` | shadcn-Default-Farben (`bg-background`, `text-muted-foreground`, `bg-accent`, `border-input`, `bg-popover`); **nicht** heizung-Design-System-Tokens | indirekt via `frontend/src/components/ui/confirm-dialog.tsx` (existiert; nutzt Dialog als Basis); Zimmer-Detail nutzt `ConfirmDialog` (z.B. Z.174-182, Z.317-336 in `[id]/page.tsx`) |
| `frontend/src/components/ui/select.tsx` | **ja** | shadcn-Standard mit `@radix-ui/react-select` + `lucide-Check/ChevronDown/ChevronUp` | shadcn-Default-Tokens (`bg-background`, `bg-popover`, `text-popover-foreground`, `ring`) | (Stand 2026-05-23: kein direkter Aufruf im Sprint-12c.a-Stand bekannt; Komponente ist vorhanden, aber Nutzung niedrig — Strategie-Chat hat das bewusst akzeptiert, weil Sprint 13b.2 sie nutzt) |
| `frontend/src/components/ui/badge.tsx` | **NEIN** | — | — | — |

### Konsequenz

- **Dialog + Select sind nutzbar** fuer die 13b.2-Confirm-Dialog-mit-Pool-Dropdown-Konstruktion. shadcn-Default-Token-Konvention bedeutet: die Dialog-Optik weicht von der heizung-Design-System-Palette (`bg-surface`, `text-text-primary`, `border-border`) ab, die in `[id]/page.tsx` und `patterns/*` genutzt wird. Strategie-Chat-Entscheidung ob: (a) Dialog im 13b.2-Brief explizit auf heizung-Tokens umgepatcht (cn-Override moeglich); (b) Default-Token akzeptiert (gleicher Stand wie heutige confirm-dialog.tsx); (c) eigener Wrapper-Pattern wie `RoomConfirmDialog` mit heizung-Tokens. Keine Empfehlung hier — nur Befund.

- **Badge fehlt.** Brief erwaehnt "badge (fuer Reserve-Tag)" als optional. Falls 13b.2 visuelles Reserve-Tag braucht: shadcn-`badge` muss als eigene UI-Komponente angelegt werden (Standard shadcn-Variants: `default`, `secondary`, `destructive`, `outline`). Brief-Default war "NICHT bauen, nur melden" → ich baue keine.

### Verwendete Pattern-Komponenten im Zimmer-Detail (Stand heute)

`/zimmer/[id]/page.tsx` importiert aus `@/components/patterns/`: `EngineDecisionPanel`, `HardwareStatusBadge`, `HeatingZoneList`, `ManualOverridePanelList`, `RoomForm`, `RoomOverrideBlockToggle`. Aus `@/components/ui/`: `Button`, `ConfirmDialog`. Sprint-13b.2-Tausch-Dialog landet stilistisch entweder in `patterns/` (neuer Pattern `VickiSwapDialog` o.ae.) oder direkt inline in `[id]/page.tsx` (analog `DevicesInRoom`-Inline-Komponente).

---

## 5. Audit 5 — Migration-Pattern-Vorbild

### 0017_room_guest_override_blocked.py (ADD NOT-NULL Boolean mit Backfill)

```python
def upgrade() -> None:
    op.add_column("room", sa.Column("guest_override_blocked", sa.Boolean(),
        nullable=False, server_default=sa.text("false")))
    # Server-Default nach Backfill entfernen — Default lebt im ORM-Modell.
    op.alter_column("room", "guest_override_blocked", server_default=None)


def downgrade() -> None:
    op.drop_column("room", "guest_override_blocked")
```

**Pattern-Eigenschaften:**

- ADD NOT NULL mit `server_default=sa.text("false")` → atomarer Backfill aller existing Rows.
- Direkt nachfolgendes `alter_column server_default=None` → Default lebt danach im ORM (`default=False` im `mapped_column`).
- §5.49-Pattern (Raw-SQL-Test-Inserts muessen Spalte mit-setzen, weil DB-Default weg).
- §5.56-Pattern (Migration-Roundtrip-Tests revisionsabhaengig anpassen, weil pre-0017 die Spalte nicht hat).
- Downgrade einzeilig.

### 0019_drop_manual_setpoint_event.py (DROP Tabelle mit 1:1-Downgrade-Reproduktion)

```python
def upgrade() -> None:
    op.drop_index("ix_manual_setpoint_event_active_window", ...)
    op.drop_table("manual_setpoint_event")


def downgrade() -> None:
    # 1:1-Reproduktion aus 0003a:271-330 (create_table) + 326-330 (create_index).
    op.create_table("manual_setpoint_event", ..., sa.CheckConstraint(...), ...)
    op.create_index("ix_manual_setpoint_event_active_window", ...)
```

**Pattern-Eigenschaften:**

- DROP-Reihenfolge: Index zuerst, dann Table.
- Downgrade reproduziert das volle Schema aus 0003a (alle Spalten, Defaults, FK-Optionen, CHECK-Constraints, Indices).
- Kein Server-Default-Trick (Tabelle entweder ganz da oder ganz weg).
- §5.56-Pattern in Downgrade besonders wichtig (Roundtrip-Tests muessen vor 0019 das alte Schema sehen).

### Empfehlung Migration 0018

Migration 0018 ist **Pattern-Mix**:

- **ADD-Block** (3 nullable Spalten, KEIN Backfill, KEIN server_default — anders als 0017): `retired_at TIMESTAMP TZ NULL`, `retired_reason VARCHAR(64) NULL`, `replaced_by_device_id INT FK device.id NULL`. Da nullable, brauchen sie keinen Default-Trick. Vorbild ist eher Migration `0016_manual_override_zone_id` (nullable FK + Partial-Index) — alter Phase-0-Bericht §H referenziert 0016 als naeheres Vorbild.
- **DROP-Block** (Voll-Unique-Constraint `uq_device_dev_eui` aus 0001 + Spalte `is_active`): Pattern-Vorbild ist 0019 (DROP + 1:1-Downgrade-Reproduktion). Downgrade muss `uq_device_dev_eui` wieder anlegen (`op.create_unique_constraint("uq_device_dev_eui", "device", ["dev_eui"])`) UND `is_active`-Spalte mit `server_default=sa.text("true")` zurueckbringen (analog 0017-Pattern in Reverse).
- **ADD-Index**: Partial-Unique-Index `ix_device_dev_eui_active` per `postgresql_where=sa.text("retired_at IS NULL")`. Pattern-Vorbild ist Migration 0016 (Partial-Index-Syntax, vom Phase-0-Bericht §H Z.401 dokumentiert).

**Einsatz von 0017 als Vorbild:** nur fuer die `is_active`-Spalte im **Downgrade** (sie war NOT NULL Boolean mit DB-Default `true`).
**Einsatz von 0019 als Vorbild:** DROP-Reihenfolge (`drop_constraint`, dann `drop_column`) + 1:1-Downgrade-Reproduktion-Disziplin.

Die alte Migration-Skizze in Phase-0-Bericht §H ist verbindlich + ausfuehrlich; dieses Update bestaetigt nur die Vertraeglichkeit gegen den neuen develop-Stand. Sprint-13b.1-T1-Implementierung kann die Skizze direkt uebernehmen.

---

## 6. Audit 6 — Helper-Lokation `get_active_devices_for_zone`

### Heutige Ist-Lage

`backend/src/heizung/repositories/` **existiert nicht.** Glob auf `repositories/*` liefert keine Files. Es gibt **kein** Repository-Pattern im Repo.

`backend/src/heizung/services/` enthaelt:
- `business_audit_service.py` — Schreib-Helper
- `config_audit_service.py` — Schreib-Helper
- `device_adapter.py` — Override-Adapter fuer Vicki-Drehring (kein generischer Device-Query-Helper)
- `downlink_adapter.py` — MQTT-Pfad fuer ChirpStack-Downlinks
- `engine_lock.py` — Redis-Lock-Helper
- `event_log.py` — Schreib-Helper
- `health_alerts.py` — Schreib-Helper
- `mqtt_subscriber.py` — Uplink-Persister
- `occupancy_service.py` — Multi-Caller-Read-Helper fuer Occupancy (`get_active`, `derive_room_status` etc.)
- `override_pms_hook.py` — Hook fuer Auto-Revoke
- `override_service.py` — Multi-Caller-Read+Write-Helper fuer Manual-Override (Create/Get/Revoke/Cleanup)
- `redis_client.py` — Connection-Helper

`backend/src/heizung/rules/` enthaelt:
- `aggregation.py`, `constants.py`, `engine.py`, `inferred_window.py`, `scenarios.py`, `window_state.py`
- **`_helpers.py` existiert nicht.** Sprint 12 T4 hatte `window_state.py` als "neutrales Modul" extrahiert (CLAUDE.md §5.46), aber **kein** generisches `_helpers.py`-Pattern eingefuehrt.

### Konsistenz-Empfehlung

`services/device_service.py` (**neue Datei**, analog `occupancy_service.py` / `override_service.py`):

- Konsistent zum bestehenden Service-Layer-Pattern. `occupancy_service.py` hat exakt diese Rolle: Multi-Caller-Read-Helper fuer eine Domain (Occupancy) mit Methods wie `derive_room_status`, `get_active`, `get_next_active`. `device_service.py` als analoge Domain-Modul-Variante.
- Vermeidet zirkulaere Imports (CLAUDE.md §5.46): `rules/` darf von `services/` importieren (etablierte Richtung), nicht umgekehrt. Helper in `services/` ist sowohl fuer `tasks/engine_tasks.py` als auch fuer `rules/engine.py` und `rules/window_state.py` aufrufbar.
- Heute existiert kein anderer guter Ort: `device_adapter.py` ist Override-spezifisch, `engine_lock.py` ist Redis-spezifisch. Sprint 13b.1 kreiert die Datei.

**Helper-Signatur (Skizze, Strategie-Entscheidung):**

```python
async def get_active_devices_for_zone(session: AsyncSession, zone_id: int) -> list[Device]:
    """Liefert aktive Devices einer HeatingZone (retired_at IS NULL).
    Nutzer: engine_tasks (Downlink-Dispatch), rules.engine (Layer-4-Detached),
    rules.window_state (Open-Window-Source), device_adapter (Override-Anlage).
    """
    stmt = select(Device).where(
        Device.heating_zone_id == zone_id,
        Device.retired_at.is_(None),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

`health_state == 'healthy'`-Filter ist **nicht** Teil dieses Helpers — `_get_devices_for_zone` in `engine_tasks.py:352` filtert zusaetzlich auf `healthy`, das ist Engine-Tick-spezifische Semantik und gehoert NICHT in den generischen Lifecycle-Helper. Sprint-13b.1-Brief sollte explizit klaeren: Helper liefert lifecycle-aktive Devices, jeder Caller fuegt seine zusaetzlichen Filter (Health, RoomScope) selbst hinzu.

### Test-Lokation

`backend/tests/test_device_service.py` (neue Datei). Vorbild: `tests/test_occupancy_service.py` (existiert) und `tests/test_override_service.py` (existiert). DB-Tests skippen ohne `TEST_DATABASE_URL`-Pattern uebernehmen (`pytest.skip`-Marker analog).

---

## 7. Drifts gegen alten Phase-0-Bericht

Liste der Stellen, an denen der alte Bericht (2026-05-21) heute nicht mehr stimmt, plus konkrete Korrektur:

| Alte Stelle | Drift | Korrektur 13b.1 |
|---|---|---|
| §J "AE-57-Luecken-Status" — Slot nie vergeben | erledigt: AE-57 vergeben im Hygiene-Sprint, Commits `9e17455` + `4ace2a9` | §J ist obsolet, AE-57-ADR-Block in `ARCHITEKTUR-ENTSCHEIDUNGEN.md:1650-1810` ist Master |
| §I "Zimmer-Inventar Live-Check" — SSH-Befehle als Brief-Vorbereitung | heute durch Sprint-13a §2at-Stand + STATUS §1 obsolet (110 Vickis: 105 verbaut + 5 Reserve, dokumentiert in `docs/inventar/README.md`) | §I obsolet |
| §K "BusinessAudit-Actions Empfehlung" — `DEVICE_PAIRED`, `DEVICE_RETIRED`, `DEVICE_REPLACED`, `PAIRING_BATCH_IMPORTED` | `DEVICE_PAIRED` umgesetzt in Sprint 13a T4 (`scripts/pairing/pairing_service.py`); `PAIRING_BATCH_IMPORTED` wurde verworfen (Sprint 13a baut keinen Batch-Audit, nur per-Row); `DEVICE_REPLACED` Strategie-Entscheidung 2026-05-23: **EINE** Audit-Row (nicht zwei) — anders als Phase-0-§K-Empfehlung "beides" | Sprint 13b.1 implementiert `DEVICE_REPLACED` als einzelne Audit-Row, `DEVICE_RETIRED` separat fuer Stilllegung ohne Ersatz |
| §L #1-#13 Engine-Query-Audit | Sprint 13a hat **+1 neue Filter-Stelle** (`scripts/pair_devices.py:253` list-pool) und **+4 Doku-Stellen** ohne neue Filter — keine alte §L-Stelle entfernt oder semantisch veraendert | `§L` erweitern um Sprint-13a-Stellen aus Audit 1 + Audit 2; Pflicht-Filter-Liste (5 S4-Stellen) bleibt unveraendert |
| §H Migration 0018 Skizze | Strategie-Brief 2026-05-23: KEIN `pairing_status`-Feld in 0018 (war B-Sprint13a-5-Vorschlag) — Phase-0-Skizze hatte das nie drin, also keine Drift zur Skizze | bestaetigt: 0018 bleibt minimal (3 nullable Spalten + Drop is_active + Partial-Unique-Index-Swap) |
| §B "Endpoint `POST /api/v1/devices/{id}/retire`" | Strategie-Brief 2026-05-23: Tausch-Endpoint ist **POST mit Pool-Reassign-Payload** statt simples Retire (Workflow B als atomarer Tausch alt→neu). Phase-0-§B beschrieb noch Retire-only + separates Pair-New (Workflow A) | 13b.1-Brief muss Endpoint-Signatur klaeren: atomarer Tausch `POST /api/v1/devices/{id}/replace` (Body: `replaced_by_device_id`) ODER zwei Endpoints `retire` + `pair`. Workflow A (separates Pair-New) entfaellt per Strategie-Entscheidung 2026-05-23 |
| §G Skript-Subcommands `import-csv`, `test-device`, `retire-device` | Sprint 13a hat `validate`, `import` (mit `--dry-run`), `test`, `list-pool` gewaehlt. `retire-device` verworfen (Strategie-Chat: Tausch ist Frontend-Job, nicht CLI) | bestaetigt |
| §E "ChirpStack-Config Tenant-ID" + "Skript am Office-Laptop vs. docker exec" | Sprint 13a hat `docker exec`-Pfad gewaehlt (RUNBOOK §10h.2 dokumentiert) | bestaetigt |

**Frontend-Drift:** Alter Bericht erwaehnt Frontend nur am Rand. Audit 3 + Audit 4 sind neue Pflicht-Sektionen fuer 13b.2 — keine Drift zum alten Bericht.

---

## 8. Empfehlungen für Sprint-13b.1-Brief

Fuenf Punkte, je eine Zeile, was im 13b.1-Brief explizit adressiert werden muss:

1. **Helper-Lokation:** `services/device_service.py` (neue Datei) als Single Source fuer `get_active_devices_for_zone()` — konsistent zum `occupancy_service.py`/`override_service.py`-Pattern, vermeidet `rules → services`-Zyklus.
2. **§L-Erweiterung Sprint 13a:** `scripts/pair_devices.py:253` (list-pool) auf `Device.retired_at.is_(None)` umstellen — Pflicht fuer UI-Konsistenz; keine S4-Auswirkung, aber Hotelier-Wahrheit.
3. **API-Default `retired_at IS NULL`:** `GET /api/v1/devices` (Listen-Endpoint) muss Default-Filter haben — sonst sieht Frontend nach Migration retired Devices. Neuer Query-Param `include_retired: bool = False` (Default).
4. **Migration 0018 Pattern-Mix:** ADD 3 nullable Spalten (kein Backfill), DROP is_active (Pattern 0017-Reverse mit `server_default=sa.text("true")` in Downgrade) + uq_device_dev_eui-Constraint (Pattern 0019: 1:1-Reproduktion in Downgrade), ADD Partial-Unique-Index `ix_device_dev_eui_active`. Migration-Skizze aus Phase-0-Bericht §H und AE-57-ADR-Block uebernehmen.
5. **Tausch-Endpoint Semantik klaeren:** Strategie-Brief 2026-05-23 verlangt **atomaren Tausch** (alt-retire + neu-zuweisen in einer Transaktion), nicht "Retire dann separat pair-new". 13b.1-Brief muss Endpoint-Signatur fixieren — Vorschlag: `POST /api/v1/devices/{old_id}/replace` mit Body `{ replaced_by_device_id: int, reason: str }`, der DEVICE_REPLACED in einer Transaktion ausloest. Phase-0-§B-Vorschlag "POST /retire" allein deckt das nicht.

Sprint-13b.2 (Frontend) bekommt separate Empfehlungen sobald 13b.1 die API-Vertraege festlegt.

---

## 9. Offene Fragen für Strategie-Chat

1. **Bestaetigung Helper-Lokation:** `services/device_service.py` als neue Datei (Audit 6 Empfehlung), oder anderes Vorbild bevorzugt? (Alternative: Helper-Funktion direkt in `services/device_adapter.py` anhaengen — semantisch ungenauer, weil device_adapter Override-spezifisch ist.)
2. **list-pool in 13b.1-Scope:** Soll `scripts/pair_devices.py:253` Teil der 13b.1-Pflicht-Filter-Umstellung sein (Audit 1 + Audit 2 fuehren Sprint-13a-Stelle als "Pflicht" an, aber CLI ist nicht-Engine)? Falls ja: Test in `tests/test_pair_devices_cli.py` mit-anpassen.
3. **Badge-Komponente:** Brief erwaehnt `badge.tsx` fuer "Reserve-Tag" — Komponente existiert heute nicht. Falls 13b.2 visuelles Reserve-Tag braucht: shadcn-`badge` Komponente vorab in 13b.1 mit-anlegen (5-LoC-Pattern aus shadcn-Doku) oder in 13b.2-Brief separat einplanen?
4. **Dialog-Token-Stil:** shadcn `dialog.tsx` nutzt Default-Farben (`bg-background`, `text-muted-foreground` etc.), nicht heizung-Tokens (`bg-surface`, `text-text-primary`). Brief sagt "shadcn Dialog" — soll die Default-Token-Optik akzeptiert werden, oder im 13b.2-Brief ein Patch auf heizung-Tokens explizit verlangt?
5. **`DEVICE_REPLACED`-Audit-Granularitaet:** Strategie 2026-05-23 sagt EINE Audit-Row. AE-57 Entscheidung 6 (Z.1745-1751) sagt ebenfalls "EINE Audit-Row pro Tausch". Phase-0-§K (alt) hatte "beides" empfohlen. AE-57 ist Master — diese Frage ist eigentlich geklaert, hier nur als Bestaetigung gelistet.

---

## Bestaetigung

Phase-0-Update-Bericht fertig. Kein Code-Touch, keine Architektur-Vorschlaege ueber den Strategie-Brief 2026-05-23 hinaus. Sprint-13b.1-Implementierung pausiert bis Strategie-Chat-Freigabe nach Review.
