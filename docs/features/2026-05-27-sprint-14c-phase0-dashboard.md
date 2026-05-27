# Sprint 14c — Phase-0-Audit: Dashboard `/` (6 KPI-Kacheln + Mail-Payload-Verifikation)

**Datum:** 2026-05-27
**Branch:** `feature/sprint-14c-phase0-dashboard`
**Basis:** develop @ `9366602`
**Stufe:** 3 (read-only Audit, kein Code-Touch)
**Vorgänger-Tag:** `v0.1.19b-cross-sicht-zimmer-detail` (#192)
**Tag-Ziel nach Implementation-Sprint:** `v0.1.19c-cross-sicht-dashboard`
**Drift-Resolution §3 (a)–(f) (Übergabe-Brief 2026-05-27):** verbindlich, T1 freigegeben.

---

## 1. Zusammenfassung

Die Startseite `/` ist heute ein reiner **`redirect("/devices")`** (13 Zeilen,
kein UI). Es gibt **keine** `KpiCard`/`StatCard`-Komponente und **kein**
`/api/v1/dashboard/*`-Endpoint — beides ist **Greenfield**. Die Daten für alle
6 KPIs sind im Bestand vorhanden, aber **kein einziger Aggregat-Helper auf
Hotel-Ebene** existiert; 4 von 6 KPIs sind triviale `COUNT()`-Queries (XS), 2
brauchen Helper-Integration (S). Der Health-Alarm-Logger (`emit_health_alert`)
loggt heute 4 der 10 Soll-Felder für späteren SMTP-Versand; die fehlenden 6 sind
am Aufruf-Pfad **bereits in Scope** und additiv ergänzbar (kein Breaking Change).

**Zwei Brief-Annahmen korrigiert (CLAUDE §5.43):**
- KPI 5 „Fenster offen" hängt **nicht** an `heating_zone.is_window_open` (Feld
  existiert nicht) — Fensterzustand lebt in `sensor_reading.open_window`.
- KPI 6 „Letzter Engine-Lauf": `engine_tick`/`room_eval` existieren **nicht** als
  Layer; Empfehlung `HARD_CLAMP` (verifiziert: läuft auch im Sommer-Fast-Path).

Freigabe-Empfehlung: **freigeben für 14c-Stufe-2-Brief** (Implementation
~5–8 h + 1 h Cowork).

---

## 2. Paket A — Bestand Dashboard-Page `/`

### A.1 Rohes Listing `frontend/src/app/page.tsx` (13 Z.)

```tsx
/**
 * Startseite des Admin-UI.
 *
 * Aktuell: Redirect auf /devices (Geraeteliste). Sobald Sprint 8 die
 * Heizungs-Steuer-Logik bringt, wird hier eine echte Uebersicht (KPIs
 * pro Zone, Anzahl aktiver Devices, letzte Anomalien) entstehen.
 */
import { redirect } from "next/navigation";

export default function Home(): never {
  redirect("/devices");
}
```

**Befund:** Die Page rendert **nichts** — sie leitet serverseitig auf `/devices`
um. Der Kommentar (`:4-6`) antizipiert bereits die KPI-Übersicht.

### A.2 Heute gerenderte Komponenten

Keine. Weder Stub, Empty-State, Begrüßung, Card-Skelett — nur `redirect`.

### A.3 Begrüßung „Hallo, [Name]"?

**Nein, existiert nirgends.** Globaler Frontend-Grep auf „Hallo" + Namens-
Begrüßung leer. Die einzige User-Anzeige steht im **AppShell-Sidebar-Footer**
(`components/patterns/app-shell.tsx:166-203`, `SidebarFooter`): zeigt
`user.email` + Rolle („Administrator"/„Mitarbeiter"), **keine** namentliche
Begrüßung. Quelle: `useAuth()` (`contexts/auth-context.tsx:95-101`) →
`authApi.me()` → `GET /api/v1/auth/me` beim Mount (`auth-context.tsx:46-64`).
Der `User`-Type trägt `email` + `role`, **kein** `display_name`.

### A.4 Auth-/Session-Wrapper um die Page

- **Kein `middleware.ts`** (Next.js App-Router-Konvention) im Frontend-Root.
  Auth ist **rein Context + HttpOnly-Cookie**, kein Per-Page-`requireAuth`.
- `frontend/src/app/layout.tsx:36-49`: Root-Layout wrapped **alle** Pages in
  `<Providers><AppShell>{children}</AppShell></Providers>` + `<Toaster>`.
  `Providers` stellt QueryClient + `AuthProvider`. Pre-Login-Routen (`/login`,
  `/auth/*`) rendern via AppShell-Pathname-Check ohne Sidebar.

### A.5 Platzierung der KPI-Card-Reihe

**Befund:** Da `/` heute nur ein Redirect ist, gibt es **keinen** bestehenden
Header-/Begrüßungs-Block, der dupliziert werden könnte. Die natürliche Lösung:
`page.tsx` von `redirect("/devices")` auf eine **echte Client-Page** umstellen
(`"use client"`), die im AppShell-`children`-Slot rendert:

```
<h1>Hallo, {user.email} (bzw. display_name, siehe Offene Frage 1)</h1>  ← neu, via useAuth()
<div className="grid …">  ← KPI-Card-Reihe (Paket G)
```

**Klassifikation:** 🟢 unproblematisch — Greenfield, kein Duplikat-Risiko, kein
AppShell-Touch (§5.8: KEIN zweiter AppShell-Wrapper in der Page).
**Hinweis:** Der `redirect("/devices")`-Wegfall bedeutet, dass `/` künftig die
Default-Landing ist — Sidebar-Default-Highlight ggf. anpassen (kosmetisch).

---

## 3. Paket B — Bestand KPI-/Stat-Card-Komponente

### B.1 Suchergebnis

`grep -ri "kpi|stat-card|metric-card"` über `components/`: **kein Treffer.**
Es existiert **keine** `KpiCard`/`StatCard`/`MetricCard`. Bestand sind nur
Komposit-Primitive:

| Pfad | Eignung als KPI-Basis |
|---|---|
| `components/ui/card.tsx` | ✅ Basis-Wrapper (`Card`/`CardHeader`/`CardTitle`/`CardDescription`/`CardContent`/`CardFooter`) — Token-Klassen `rounded-lg border border-border bg-surface shadow-sm`. Kein Icon-Slot, kein Label+Zahl-Layout. |
| `components/patterns/zone-health-badge.tsx` | Tone-Referenz (siehe B.4) |
| `components/patterns/hardware-status-badge.tsx` | Tone-Referenz (siehe B.4) |
| `components/scenario-card.tsx` | Komposit-Card (Card + Switch + Confirm) — nicht als KPI-Card wiederverwendbar |

### B.2 Existiert eine KpiCard? — Nein

Entfällt. Es gibt nichts zu prüfen; siehe B.3 Greenfield.

### B.3 Greenfield-Vorschlag `components/patterns/kpi-card.tsx`

Props-Skizze (Implementation in Stufe 2, **hier nur Vorschlag**):

```tsx
interface KpiCardProps {
  label: string;                                  // "Belegte Zimmer"
  value: string | number;                         // 12
  subValue?: string;                              // "von 30" / "Ø 21,4 °C"
  icon: string;                                   // Material-Symbol-Name, z.B. "hotel"
  tone?: "success" | "warning" | "danger" | "neutral";
  loading?: boolean;                              // Skeleton
  error?: boolean;                                // Fehler-Tone + Hinweis
}
```

**Design-Strategie-Konformitäts-Pflicht** (analog Bestand-Badges):
- Material-Symbol-Icon-Slot via `<span className="material-symbols-outlined" style={{ fontSize: N }}>` (einzig erlaubter Inline-Style im Repo — nur `fontSize`).
- Token-basierte Farben (`bg-success-soft text-success` etc.), **kein** Inline-Hex.
- Tones identisch zur Badge-Familie (B.4) für visuelle Konsistenz.

### B.4 Querverweis — Tone-Referenz (Geräte online / Warnfarben)

**`ZoneHealthBadge`** (`patterns/zone-health-badge.tsx:34-59`, Sprint 11):

| State | Icon | Token-Klasse |
|---|---|---|
| `healthy` | `health_and_safety` | `bg-success-soft text-success` |
| `degraded` | `warning` | `bg-warning-soft text-warning` |
| `silent` | `error` | `bg-danger-soft text-danger` |
| `no_device` | `help` | `bg-surface-alt text-text-tertiary` |

**`HardwareStatusBadge`** (`patterns/hardware-status-badge.tsx:51-59`, Sprint 14a):
`active` → `bg-success-soft text-success` (Icon `wifi`); `inactive` →
`bg-danger-soft text-danger` (Icon `wifi_off`).

**Ableitung KPI-Tones:** online/ok → `success-soft`; Achtung → `warning-soft`;
offline/Fehler → `danger-soft`; neutral → `surface-alt`.

**Klassifikation:** 🟡 — Greenfield-Komponente nötig, aber low-risk (reine
Komposition aus Bestand-Tokens + Card). §5.69-Sub-Audit: KpiCard bettet **keine**
Bestand-Komponente mit eigener Card-Chrome/State-Plumbing ein → kein
Link-out-Konflikt; sauberer Greenfield-Build.

---

## 4. Paket C — Backend Health-State-Logger + Payload-Gap-Analyse

### C.1 Rohes Listing `services/health_alerts.py` (67 Z.)

```python
"""Sprint 11 T6 — Health-Alarm-Stub (AE-53 Stufe-2 + Stufe-3).

Heute: strukturierter Logger-Aufruf, der in journalctl / Container-Log
landet und nach ``dev_eui`` / ``reason`` grep-bar ist. Kein SMTP-Versand
— das ist eigener Sprint nach Heizperiode.

Konsument: ``_compute_health_state_async`` (health_tasks.py) ruft
``emit_health_alert`` fuer jede silent-Transition auf
(Stufe-3-Trigger laut AE-53).

Heutige Bedeutung "Stufe":

- **Stufe 1:** Device degraded (2-24h offline). Heute KEIN Alarm —
  sichtbar nur im ``device.health_state``. UI-Anzeige in Sprint 14.
- **Stufe 2:** Device silent durch offline > 24h. Logger-Alarm mit
  ``reason="offline_24h"``.
- **Stufe 3:** Device silent durch >= 10 implausible Readings in 24h
  (AE-53 Stufe-3-Trigger). Logger-Alarm mit
  ``reason="implausible_readings_24h"``.

Idempotenz: ``silent_transitions``-Liste aus T5 enthaelt bauartbedingt
nur ``previous != "silent" AND new_state == "silent"``-Uebergaenge,
stabile silent-Devices sind nicht in der Liste — also kein Re-Mail-
Sturm beim 5-min-Beat-Tick. Bei spaeterem SMTP-Swap muss der Helper
ggf. zusaetzlich pro dev_eui dedupliziert werden (z.B. Redis-Key
``health_alert_sent:{dev_eui}`` mit TTL); heute out-of-scope.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def emit_health_alert(
    *,
    level: int,
    device_id: int,
    dev_eui: str,
    reason: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Emittiert einen strukturierten WARNING-Log-Event.

    Args:
        level: ``2`` (offline_24h) oder ``3`` (implausible_readings_24h).
        device_id: Device-Primary-Key fuer DB-Korrelation.
        dev_eui: Device-EUI fuer Container-Log-grep.
        reason: ``"offline_24h"`` oder ``"implausible_readings_24h"`` —
            die Strings sind verbindlich (kommen aus AE-53 + T5).
        context: Optionaler Zusatz-Kontext (z.B. counter-Wert,
            last_uplink-Timestamp). Heute optional, in T7-Sprint-
            Abschlussbericht ggf. erweitert.
    """
    logger.warning(
        "health_alert",
        extra={
            "level": level,
            "device_id": device_id,
            "dev_eui": dev_eui,
            "reason": reason,
            "context": context or {},
        },
    )
```

### C.2 Heute geloggte Felder vs. Mindest-Soll (SMTP)

Aufruf: `tasks/health_tasks.py:274-281` in `_compute_health_state_async`, iteriert
`silent_transitions` (je Dict: `device_id`, `dev_eui`, `reason`):

```python
for transition in silent_transitions:
    level = 3 if transition["reason"] == "implausible_readings_24h" else 2
    emit_health_alert(
        level=level,
        device_id=transition["device_id"],
        dev_eui=transition["dev_eui"],
        reason=transition["reason"],
    )
```

| Soll-Feld | heute geloggt | Quelle am Aufruf-Pfad (in Scope!) |
|---|---|---|
| `level` | ✅ | abgeleitet aus reason |
| `device_id` | ✅ | transition-Dict |
| `dev_eui` | ✅ | transition-Dict |
| `reason` | ✅ | transition-Dict |
| `device_name` | ❌ | `device.label` (Device-Liste `:172`) |
| `room_name` | ❌ | JOIN zone→room: `room.number`/`display_name` |
| `zone_name` | ❌ | `zone.name` (Zonen-Liste `:173`) |
| `triggered_at` | ❌ | `now` (`:169`, UTC) |
| `last_uplink_at` | ❌ | `latest_reading[device_id][0]` (`:178-189`) |
| `implausible_count_24h` | ❌ | `counter_cache[dev_eui]` (`:216-223`) |

**6 von 10 fehlen** — alle 6 sind am Aufruf-Pfad bereits geladen.

### C.3 Empfehlung — additive Signatur-Erweiterung (kein Breaking Change)

`emit_health_alert(*, …)` ist keyword-only → neue **optionale** Parameter sind
nonbreaking. Vorschlag (Implementation Stufe 2):

```python
def emit_health_alert(
    *, level, device_id, dev_eui, reason,
    device_name: str | None = None,
    room_name: str | None = None,
    zone_name: str | None = None,
    triggered_at: datetime | None = None,
    last_uplink_at: datetime | None = None,
    implausible_count_24h: int | None = None,
    context: dict[str, Any] | None = None,
) -> None: ...
```

Namens-Auflösung am Aufruf via JOIN `device.heating_zone_id → heating_zone.id`,
`heating_zone.room_id → room.id`. Modell-FKs:
`Device.heating_zone_id` (`ForeignKey("heating_zone.id", ondelete="SET NULL")`,
nullable → Pool-Geräte) · `HeatingZone.room_id` (`ForeignKey("room.id")`, NOT
NULL) · `Room.number`/`Room.display_name`. Die `devices`/`zones`-Listen sind am
Call-Site (`:172-173`) bereits vorhanden → lokaler Dict-Lookup, **kein** extra
DB-Roundtrip.

### C.4 Verifikations-Snippet (Live-Tail health_alert-Logs, heizung-test)

RUNBOOK §10d.8 referenzieren. **SSH (heizung-test, root):**

```bash
# Container-Log nach health_alert grep-en (Celery-Worker emittiert)
docker logs deploy-celery_worker-1 --tail 200 2>&1 | grep -i "health_alert"
# Live-Tail
docker logs deploy-celery_worker-1 --since 10m -f 2>&1 | grep -i "health_alert"
```

> Hinweis §5.17: nach Container-Restart `--tail` statt `--since` (Time-Offset).

### C.5 Nicht-Ziel bestätigt

Re-Mail-Dedupe (`health_alert_sent:{dev_eui}`-Redis-Key) ist **nur im Docstring
dokumentiert, NICHT implementiert** (Grep bestätigt: kein Code-Treffer). Bleibt
**Backlog** — in Phase-0 und Stufe 2 **nicht** implementieren. Heutige Idempotenz
trägt über die `silent_transitions`-Konstruktion (nur Übergänge, keine stabilen
silent-Devices → kein Re-Sturm beim 5-min-Beat).

---

## 5. Paket D — KPI-Datenquellen-Matrix (6 Kacheln)

Alle Queries sind **Greenfield** (kein Hotel-Aggregat-Helper im Bestand). §5.58
(`retired_at IS NULL`) gilt für alle Device-Queries.

| # | KPI | Modell + Feld | Query-Skizze | Bestand-Helper | Gap (Aufwand) |
|---|---|---|---|---|---|
| 1 | Belegte Zimmer | `Room.status: RoomStatus` (`VACANT/OCCUPIED/RESERVED/CLEANING/BLOCKED`) | `COUNT(status=OCCUPIED)` + `COUNT(*)` | `occupancy_service.derive_room_status()`/`sync_room_status()` (pro Raum, **kein** Count) | Aggregat-Count **S** |
| 2 | Ø Raumtemperatur | `SensorReading.temperature: Numeric(5,2)` | letztes healthy Reading/Zone → Mittel über Zonen | `rules/aggregation.aggregate_zone_readings()` (Zone-Ebene, pure fn, ROUND_HALF_EVEN→0,1 °C) | Hotel-Aggregat **S** |
| 3 | Geräte online | `Device.health_state: str`, `Device.retired_at` | `COUNT(health_state IN ('healthy','degraded') AND retired_at IS NULL)` + `COUNT(retired_at IS NULL)` | nur `device_service.get_active_devices_for_zone()` (zonen-scoped) | Count-Query **XS** |
| 4 | Aktive Overrides | `ManualOverride.revoked_at`, `expires_at` | `COUNT(revoked_at IS NULL AND expires_at > now())` | `override_service.revoke_all_active_overrides()` liefert Count, aber **kein** active-Count | Count-Query **XS** |
| 5 | Fenster offen | **`SensorReading.open_window: bool\|None`** (NICHT `heating_zone.is_window_open`) | `COUNT(DISTINCT zone)` über `open_window=true` + Stale-Filter | `rules/window_state.detect_open_window_zones()` (pro Raum, Liste) | Zonen-Count-Aggregat **S** |
| 6 | Letzter Engine-Lauf | `EventLog.time`, `EventLog.layer` (`EventLogLayer`) | `MAX(time) WHERE layer='hard_clamp'` | keiner (Roh-Query) | Query **XS** |

### Korrektur-Befunde (§5.43 — Brief-Annahmen via Source belegt)

- **KPI 5:** `HeatingZone` hat **kein** `is_window_open`-Feld (Modell verifiziert).
  Fensterzustand lebt ausschließlich in `sensor_reading.open_window` (nullable;
  §5.27: Vicki-Open-Window per Default disabled, FW-abhängig). Stale-Filter
  `WINDOW_STALE_THRESHOLD_MIN` (`rules/constants.py`) wie in
  `detect_open_window_zones`. **Folge:** „Fenster offen" ist physisch nur belastbar,
  wenn Open-Window-Detection auf den Vickis aktiviert ist (Cowork-Frage, Paket H).
- **KPI 6:** Weder `engine_tick` noch `room_eval` existieren als `EventLogLayer`.
  Layer-Enum: `summer_mode_fast_path`, `base_target`, `temporal_override`,
  `manual_override`, `guest_override`, `window_safety`, `device_detached`,
  `hard_clamp`, `inferred_window_observation`, `manual_override_blocked`.
  **Empfehlung `HARD_CLAMP`** — verifiziert: läuft in **beiden** Pfaden, auch im
  Sommer-Fast-Path (`engine.py:997-1001` gibt `layers=(summer, clamp)` zurück),
  und schließt die Off-Pipeline-Inseln `MANUAL_OVERRIDE_BLOCKED` (synthetische
  `evaluation_id`, §5.52) aus. Alternativ `SUMMER_MODE_FAST_PATH` (Layer 0,
  always-on, ebenfalls in beiden Pfaden) — `HARD_CLAMP` ist aber das sauberere
  „Evaluation abgeschlossen"-Signal.

### Caveat KPI 1 (§5.53 Dual-Source)

`Room.status` (persistiert) wird per Cron aus aktiven Occupancies gesynct
(`sync_room_status`). Ein Count auf `Room.status` ist schnell, kann aber bis zum
nächsten Sync minimal nachhängen. Alternative: live über `derive_room_status` pro
Raum (teurer). **Empfehlung:** `Room.status`-Count (Sync-Latenz für eine
Belegt-Kachel akzeptabel) — in Stufe-2-Brief explizit entscheiden.

---

## 6. Paket E — Endpoint-Inventar `/api/v1/dashboard/*`

`grep -ri "dashboard" backend/src/api/`: **kein Treffer → Greenfield.** Bestand-
Router (`api/v1/`): `auth`, `devices`, `global_config`, `heating_zones`,
`occupancies`, `overrides`, `room_types`, `rooms`, `rule_configs`, `scenarios`,
`users`. Kein Dashboard-Router in `__init__.py`.

**Vorschlag-Schema (Pydantic-Skizze, kein Code):**

```python
class DashboardKpiRead(BaseModel):
    rooms_occupied: int
    rooms_total: int
    avg_temperature_celsius: Decimal | None      # None wenn keine healthy Zone
    devices_online: int
    devices_total: int                            # retired_at IS NULL
    active_overrides: int
    zones_window_open: int
    last_engine_tick: datetime | None             # UTC ISO-8601, Frontend lokalisiert (§5.65)
```

**Additive Erweiterbarkeit (B-14c-FU-1):** flaches Schema, neue KPI-Felder später
anhängbar ohne Bruch. Ein Endpoint `GET /api/v1/dashboard/kpis` (require_user)
liefert alle 6 in einem Request → ein TanStack-Query-Hook (Paket F).

---

## 7. Paket F — Refresh-Strategie

### F.1 Bestand-Intervalle

| Hook | Datei | `refetchInterval` | Page |
|---|---|---|---|
| `useDevice` | `lib/api/hooks.ts:55` | `30_000` | `/devices/[id]` |
| `useHardwareStatus` | `lib/api/hooks.ts:72` | `30_000` | Hardware-Badge |
| `useSensorReadings` | `lib/api/hooks.ts:86` | `30_000` | Sensor-Chart |
| `useEngineTrace` | `lib/api/hooks-rooms.ts:42` | `30_000` | Engine-Panel (`/zimmer/[id]`) |

QueryClient-Default (`lib/query.ts:13-24`): `staleTime: 30_000`,
`refetchOnWindowFocus: true`, `retry: 1`. Höchste Bestands-Frequenz = **30 s**.

### F.2 Empfehlung Dashboard: 60 s

**Eigene Stufe 60 s** (nicht 30 s), begründet: KPIs ändern sich nicht schneller
als der Engine-Beat (`evaluate-due-rooms-every-60s`, §5.32) — eine höhere
Frequenz als der 60-s-Tick liefert keine neuen Werte, kostet aber Last (1 Endpoint
aggregiert 6 Queries über alle Räume/Geräte). `staleTime` analog 60 s.

### F.3 Hintergrund-Tab

`refetchIntervalInBackground` ist **nirgends gesetzt** → TanStack-Default `false`
→ **pausiert** im Hintergrund-Tab. Korrektes Verhalten, kein Counter-Pattern nötig.
`refetchOnWindowFocus: true` holt beim Zurückwechseln sofort frische Werte.

---

## 8. Paket G — Grid-Layout-Empfehlung + §5.2-Konflikt

### G.1 Bestand-Card-Grids

- `/szenarien` (`szenarien/page.tsx:81,106`):
  `grid gap-4 sm:grid-cols-2 lg:grid-cols-3` (1→2→3 Spalten, Gap 16 px).
- `/raumtypen` (`raumtypen/page.tsx:92`):
  `grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6` — **Master-Detail**, kein
  Card-Grid; nicht als KPI-Referenz brauchbar. → `/szenarien` ist die Referenz.

### G.2 Empfehlung

**3×2 Desktop / 2×3 Tablet / 1×6 Mobile**, identisch zum bewährten Szenarien-Grid:

```
grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4
```

Gap `gap-4` = 16 px (entspricht der `--spacing-md`-Vorgabe). Hinweis: das Repo nutzt
**kein** Custom-Token `--spacing-md`, sondern die Tailwind-Skala `gap-4` — konsistent
mit `/szenarien`. (Ein echtes `--spacing-md`-Token müsste zuerst angelegt werden;
für 14c **nicht** nötig — `gap-4` reicht und ist Bestand-konform.)

### G.3 §5.2-Konflikt-Vermerk

Design-Strategie §5.2 sagt „4 Cards Desktop", STRATEGIE §8.4 listet 6 Cards. Die
Empfehlung (6 Cards, 3×2) folgt **§8.4 + Drift-Resolution §3(b)** bewusst. Abweichung
zu §5.2 geht als Anmerkung in den **T12-Doku-PR** des Implementation-Sprints oder als
§5.2-Update-Vorschlag — **Strategie-Chat entscheidet nach Phase-0-Review.** Kein
Code-Vorgriff hier.

---

## 9. Paket H — Cowork-Daten-Voraussetzungen heizung-test (Live-Verify pending)

> §5.68: operative Server-State-Werte sind erst nach Diagnose-Output Befund, nicht
> Behauptung. Nachfolgende Werte sind **vom User auszuführen** (SSH heizung-test);
> die Snapshot-Tabelle wird vor Tag-Setzung gefüllt.

**SSH (heizung-test, root) — Befehle:**

```bash
# 1. Zimmer 101 belegt + Belegung aktiv (check_out > now)?
docker exec deploy-db-1 psql -U heizung -d heizung -c \
"SELECT r.number, r.status, o.check_in, o.check_out, (o.check_out > now()) AS aktiv
 FROM room r LEFT JOIN occupancy o ON o.room_id = r.id
 WHERE r.number = '101' ORDER BY o.check_in DESC LIMIT 3;"

# 2. Health-Verteilung der aktiven Vickis (healthy/degraded/silent)
docker exec deploy-db-1 psql -U heizung -d heizung -c \
"SELECT health_state, COUNT(*) FROM device
 WHERE retired_at IS NULL GROUP BY health_state ORDER BY health_state;"

# 3. Aktive Overrides
docker exec deploy-db-1 psql -U heizung -d heizung -c \
"SELECT COUNT(*) AS aktive_overrides FROM manual_override
 WHERE revoked_at IS NULL AND expires_at > now();"

# 4. Letzter Engine-Tick (sollte < 10 min alt sein)
docker exec deploy-db-1 psql -U heizung -d heizung -c \
"SELECT MAX(time) AS letzter_hard_clamp, now() - MAX(time) AS alter
 FROM event_log WHERE layer = 'hard_clamp';"

# (Zusatz) Fenster offen — Bestätigung Open-Window-Detection aktiv?
docker exec deploy-db-1 psql -U heizung -d heizung -c \
"SELECT COUNT(*) FILTER (WHERE open_window IS TRUE) AS offen,
        COUNT(*) FILTER (WHERE open_window IS NOT NULL) AS mit_flag
 FROM sensor_reading WHERE time > now() - interval '12 minutes';"
```

**Snapshot-Tabelle (auszufüllen):**

| Kennzahl | Erwartung | Realwert (Live) |
|---|---|---|
| Zimmer 101 Status / Belegung aktiv | „Belegt" / aktiv (14b-Cowork) | _pending_ |
| Vickis healthy / degraded / silent | 4 healthy (Test-Vickis 001-004) | _pending_ |
| Aktive Overrides | ? | _pending_ |
| Letzter Engine-Tick (Alter) | < 10 min | _pending_ |
| Fenster offen (mit Flag) | ggf. 0 (Detection im Sommer/Default oft aus) | _pending_ |

---

## 10. Paket I — §8.4-Refactor-Vermerk (Vermerk-only)

§8.4 ist nach 14c-Implementation veraltet (3 von 6 alten Kacheln sind PMS-/Wetter-
abhängig und entfallen). Refactor erfolgt **chirurgisch im T12-Doku-PR** des
Implementation-Sprints zusammen mit STATUS §2bb + SPRINT-PLAN-Update. Neue 6er-Liste
= Drift-Resolution §3(b): Belegte Zimmer, Ø Raumtemp, Geräte online, Aktive Overrides,
Fenster offen, Letzter Engine-Lauf. Begründungs-Vermerk: B-14c-FU-1 reaktiviert
PMS-/Wetter-KPIs nach Sprint 16a + Wetter-Service. **Kein Diff-Vorschlag, kein
Wortlaut-Drafting in Phase-0.**

---

## 11. Risiken-Update gegen Übergabe-Brief §5

> Hinweis: Der Übergabe-Brief 2026-05-27 (Strategie-Chat-Artefakt) liegt **nicht im
> Repo**; R1/R6-Wortlaut konnte nicht verbatim verifiziert werden. Zuordnung daher
> per Inferenz — Strategie-Chat bestätigt/korrigiert beim Phase-0-Review.

- **R1 (aufgelöst):** vermutlich „Dashboard-/KPI-Card-Greenfield-Risiko". Bestätigt
  als Greenfield (Paket B + E), aber **low-risk**: reine Komposition aus Bestand-
  Tokens/Card, additives Endpoint-Schema. Kein Architektur-/Engine-Touch → aufgelöst.
- **R6 (zu verifizieren):** vermutlich „Cowork-Daten-Verfügbarkeit auf heizung-test".
  **Bleibt offen bis Paket-H-Live-Verify** — insbesondere: (a) ob KPI 5 „Fenster
  offen" überhaupt nicht-leere Werte liefert (Open-Window-Detection-Aktivierung,
  §5.27), (b) ob 4 Test-Vickis healthy senden, (c) Engine-Tick-Frische < 10 min
  (Block-A-Stall-Historie §5.68 — per Diagnose belegen, nicht annehmen).

---

## 12. Empfohlene T-Liste für Implementation-Sprint 14c (Stufe 2)

| T | Inhalt | Aufwand |
|---|---|---|
| **T1** | Backend `services/dashboard_service.py` — 6 Aggregat-Helper (4× COUNT, Ø-Temp via `aggregate_zone_readings`, last-tick `HARD_CLAMP`). §5.58-Filter Pflicht. | 1,5–2 h |
| **T2** | Backend `api/v1/dashboard.py` — `GET /kpis` → `DashboardKpiRead`, `require_user`, in `__init__.py` registrieren. + Backend-Tests (lokal DB §5.50). | 1–1,5 h |
| **T3** | Frontend `components/patterns/kpi-card.tsx` (Greenfield, B.3-Props, Token-Tones, loading/error). | 1–1,5 h |
| **T4** | Frontend `app/page.tsx` von Redirect → Client-Page: `useAuth`-Begrüßung + KPI-Grid (G.2) + `useDashboardKpis`-Hook (`refetchInterval: 60_000`). | 1,5–2 h |
| **T5** | Playwright: `/`-Smoke (6 Kacheln, Werte, Mobile-Stack), Regex-Mock für Query-String (§5.54). | ~1 h |
| **T6 (additiv, optional)** | `emit_health_alert`-Signatur um 6 Felder erweitern (C.3) + Call-Site-Lookup. **Kein** Re-Mail-Dedupe (C.5). | 30–60 min |
| **T12** | Doku-PR: STATUS §2bb, SPRINT-PLAN, STRATEGIE §8.4-Refactor (Paket I), §5.2-Konflikt-Anmerkung (G.3), Cowork-Snapshot (Paket H), Tag `v0.1.19c-cross-sicht-dashboard`. | 0,5–1 h |

**Summe:** ~5–8 h Implementation + 1 h Cowork.

---

**Stop-Point:** Phase-0-Audit abgeschlossen. Kein Code-Touch, keine Migration, keine
Tests, kein Logger-Touch, kein STATUS-/SPRINT-PLAN-/§8.4-Touch, kein Tag. Read-only.
Warte auf Freigabe für 14c-Stufe-2-Implementation-Brief.
