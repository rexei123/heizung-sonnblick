# B-10-4 Phase-0 — DST-Verhalten Oktober 2026

**Stand:** 2026-05-25
**Zweck:** Read-Only-Audit aller zeit-gesteuerten Engine-Pfade vor dem
ersten produktiven DST-Wechsel am **2026-10-25** (Sommerzeit →
Winterzeit, lokal 03:00 → 02:00, die Stunde 02:00–03:00 wiederholt
sich). Heizperiode-Start typisch Mitte Oktober — drei Wochen
Heiz-Betrieb vor DST-Wechsel.
**Rolle:** Code (Read-Only, Autonomie-Stufe 3)
**Branch:** `docs/b-10-4-dst-phase0-audit`
**Bezug:** STATUS §6 B-10-4-Eintrag, CLAUDE.md §5.59 (FlakyTime-Pattern
als verwandte Time-Logic-Klasse), AE-58 (Override-Domain),
`engine.py:295-297` (dokumentierter Sprint-9.8-Vereinfachungs-Hinweis).

---

## 1. datetime-Verwendung Backend

`backend/src/heizung/**/*.py` — alle Treffer von `datetime.now`,
`datetime.utcnow`, `date.today`:

| Datei : Zeile | Aufruf | TZ-Status |
|---|---|---|
| `auth/jwt.py:30` | `datetime.now(UTC)` | TZ-aware ✓ |
| `tasks/health_tasks.py:169` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `tasks/engine_tasks.py:142` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `tasks/engine_tasks.py:248` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `tasks/engine_tasks.py:476` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `rules/engine.py:798` | `now or datetime.now(tz=UTC)` | TZ-aware ✓ |
| `rules/engine.py:849` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `rules/engine.py:982` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `services/override_service.py:195` (`_now()`) | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `services/device_service.py:156` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `services/device_service.py:233` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `services/mqtt_subscriber.py:116/236/390` | `uplink.time or datetime.now(tz=UTC)` | TZ-aware ✓ |
| `services/occupancy_service.py:27` (`_now()`) | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `api/v1/overrides.py:168` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `api/v1/devices.py:403` | `datetime.now(UTC)` | TZ-aware ✓ |
| `api/v1/occupancies.py:190` | `datetime.now(tz=UTC)` | TZ-aware ✓ |
| `api/v1/auth.py:95` | `datetime.now(UTC)` | TZ-aware ✓ |
| `scripts/pairing/inbound_test.py:331` | `datetime.now(tz=UTC)` | TZ-aware ✓ |

`engine.py:468` ist ein Docstring-Erwähnung (kein Code-Aufruf).

**Befund:** 0 Treffer für `datetime.now()` ohne `tz`. 0 Treffer für
`datetime.utcnow()` (deprecated + naive). 0 Treffer für
`date.today()`. **Alle 19 Aufrufe sind TZ-aware mit explizitem
UTC-Bezug.**

---

## 2. Time-Comparison-Stellen

`night_start | night_end | preheat | check_in | check_out | expires_at`
in `services/`, `rules/`, `tasks/`:

### 2.1 Override `expires_at` — DateTime-Vergleich, TZ-aware

- `override_service.get_active()` filtert `expires_at > now` mit
  beidseits TZ-aware datetime (Column `DateTime(timezone=True)` +
  `_now()`). **🟢 OK** — DST-sicher durch Monotonie der UTC-Linie.
- `override_cleanup_tasks` läuft cron-basiert in UTC (siehe §4).

### 2.2 Occupancy `check_in` / `check_out` — DateTime-Vergleich, TZ-aware

- `occupancy_service.derive_room_status()` und `next_active_checkout()`
  vergleichen `Occupancy.check_in / check_out` (TIMESTAMPTZ) gegen
  `_now()` (UTC). **🟢 OK**.

### 2.3 `preheat_minutes_before_checkin` — TZ-aware Subtraction

- `engine.py:309-310`:
  ```python
  preheat_window_start = occ.check_in - timedelta(minutes=int(preheat_min))
  if preheat_window_start <= now < occ.check_in:
  ```
  Beide Seiten sind TZ-aware (`now` aus `evaluate_room` ist
  `datetime.now(tz=UTC)`, `occ.check_in` ist TIMESTAMPTZ).
  `timedelta`-Arithmetik ist DST-sicher (Wall-Clock-unabhängig).
  **🟢 OK**.

### 2.4 `night_start` / `night_end` — **wall-clock comparison gegen UTC**

- `engine.py:330-331`:
  ```python
  now_t = now.time()  # now ist UTC
  if _is_in_night_window(now_t, night_start, night_end):
  ```
- `_resolve_field("night_start", ctx)` liefert `time` (SQL `Time`,
  ohne TZ) — der Hotelier gibt das in der UI als wall-clock-Zeit ein
  (UI-Feld `variant="time"` in
  `frontend/src/app/einstellungen/temperaturen-zeiten/page.tsx:163`).
- `now.time()` extrahiert die **UTC-Wallclock-Stunde**, **nicht** die
  lokale Wiener Wallclock-Stunde.
- Der Docstring `engine.py:295-297` weist das selbst als bewusste
  Sprint-9.8-Vereinfachung aus: „Time-Berechnung in lokaler
  Hotel-Zeitzone (default Europe/Vienna in global_config). Sprint 9.8
  vereinfacht: nutzt now (UTC) direkt — Hotelier kann Sprint 13+ via
  global_config.timezone konfigurieren."
- `global_config.timezone` (Spalte) existiert (`models/global_config.py:40`,
  Default `"Europe/Vienna"`), wird heute aber von keinem Engine-Pfad
  gelesen.

**🔴 KRITISCH** — Details in §7.

### 2.5 `setback_minutes_after_checkout` — int-Delta, kein Wall-Clock

- `Integer`-Spalte, wird als Minuten-Delta zu `check_out` (TIMESTAMPTZ)
  addiert. TZ-arithmetik via `timedelta`. **🟢 OK**.

---

## 3. DB-Schema TZ-Konvention

`backend/src/heizung/models/*.py` — alle Treffer `DateTime(`, `TIMESTAMP`:

| Modell | Spalte | Typ | Status |
|---|---|---|---|
| `business_audit` | `created_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `config_audit` | `created_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `control_command` | `issued_at` / `sent_to_gateway_at` / `acknowledged_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `device` | `retired_at` / `last_seen_at` / `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `event_log` | `time` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `global_config` | `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `heating_zone` | `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `manual_override` | `expires_at` / `created_at` / `revoked_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `occupancy` | `check_in` / `check_out` / `cancelled_at` / `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `room` | `last_evaluated_at` / `next_transition_at` / `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `room_type` | `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `rule_config` | `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `rule_config` | `night_start` / `night_end` | `Time` (kein TZ) | **wall-clock**, siehe §2.4 |
| `scenario` / `scenario_assignment` | `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `season` | `created_at` / `updated_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `sensor_reading` | `time` (PK) | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |
| `user` | `created_at` / `updated_at` / `last_login_at` | `DateTime(timezone=True)` | TIMESTAMPTZ ✓ |

**Befund:** Alle DateTime-Spalten (35 von 35) sind TIMESTAMPTZ. Die
einzigen wall-clock-Spalten sind `rule_config.night_start` /
`night_end` als `Time` — bewusst, weil sie wiederkehrende
Tagesschwellen repräsentieren. Die Frage ist NICHT die Spalten-Wahl,
sondern wo der Vergleich gegen „jetzt" stattfindet (siehe §2.4).

---

## 4. Celery + Cron Schedule-Konfiguration

`backend/src/heizung/celery_app.py`:

- `app.conf.timezone = "UTC"` (Z.51), `enable_utc = True` (Z.52).
- Beat-Schedule:
  - `evaluate-due-rooms-every-60s`: `schedule=60.0` — **Intervall**,
    DST-immun (Monotonie). **🟢 OK**.
  - `cleanup-expired-overrides-daily`: `crontab(hour=3, minute=0)` in
    UTC. Cron in UTC hat keinen DST-Sprung — feuert weltweit zur
    selben Wallclock-UTC. **🟢 OK**.
  - `compute-health-state-every-5min`: `schedule=300.0` — **Intervall**.
    **🟢 OK**.
- Task-Time-Limits (`task_soft_time_limit=20`, `task_time_limit=30`):
  Sekunden-basiert, DST-irrelevant.
- Engine-Lock-TTL (Sprint 9.10 T3.5 / AE-40): Sekunden-basiert in
  `services/engine_lock.py`. DST-irrelevant.

Hetzner-Cron-Jobs (`RUNBOOK.md` §10):
- `heizung-deploy-pull.timer` (systemd-Timer, Auto-Pull alle 5 Min) —
  Intervall, DST-immun.
- Backup-Cron (falls vorhanden, RUNBOOK §10 prüfen) — out of scope
  dieses Audits, betrifft Operations nicht Engine-Setpoint-Pfade.

**Befund:** Keine cron-basierten Schedule-Patterns in Local-Time.
Alle periodischen Tasks laufen in UTC oder als Intervall. **🟢 OK**.

---

## 5. Engine-Layer Time-Pfade

`backend/src/heizung/rules/engine.py` — Layer-Pipeline:

### Layer 0 — Sommermodus (`layer_summer_mode`)
- Liest `ctx.summer_mode_active` (Bool aus `scenario_assignment`, AE-49).
- Kein Zeit-Vergleich, kein DST-Pfad.
- **🟢 OK**.

### Layer 1 — Base / Occupancy (`layer_base_target`)
- Liest `ctx.room.status` (RoomStatus-Enum, vorab via
  `occupancy_service.sync_room_status` synchronisiert).
- `sync_room_status` ruft `derive_room_status(now)` mit TZ-aware UTC
  (siehe §2.2).
- **🟢 OK**.

### Layer 2 — Temporal: Vorheizen + Nachtabsenkung (`layer_temporal`)
- **Vorheizen** (`engine.py:301-323`): DateTime-Arithmetik mit
  `timedelta`-Subtraktion, beide Seiten TZ-aware. **🟢 OK**.
- **Nachtabsenkung** (`engine.py:325-342`): `now.time()` aus UTC-`now`
  gegen wall-clock-`time`-Spalten — Strukturfehler aus Sprint 9.8.
  **🔴 KRITISCH** — siehe §2.4 + §7.

### Layer 3 — Manual-Override (`layer_manual_override`)
- Ruft `override_service.get_active(session, room_id, ...)` →
  `expires_at > now` (TZ-aware vs. TZ-aware). **🟢 OK**.
- Auto-Revoke bei Check-out (`auto_revoke_on_checkout`) nutzt
  TZ-aware now. **🟢 OK**.

### Layer 4 — Window / Detach (`layer_window_open`,
  `layer_device_detached` aus `rules/window_state.py` und Engine-Layer)
- Window-Open-Check filtert SensorReading nach
  `time >= now - WINDOW_STALE_THRESHOLD_MIN` — beidseits TZ-aware.
  **🟢 OK**.
- Detach-Check vergleicht `device.last_seen_at` (TIMESTAMPTZ) gegen
  TZ-aware now mit `timedelta`-Schwelle. **🟢 OK**.

### Layer 5 — Clamp (`layer_clamp`)
- Numerische Bounds, kein Zeit-Vergleich. **🟢 OK**.

### Engine-Task-Driver (`tasks/engine_tasks.py`)
- `_evaluate_due_rooms_async`: filtert `Room.next_transition_at <= now`
  — beidseits TZ-aware. **🟢 OK**.
- `_evaluate_room_async` setzt `next_transition_at = now +
  timedelta(seconds=60)`. **🟢 OK**.
- Hysterese-Heartbeat (`engine.py:798`): `now - prev_issued_at`,
  `timedelta`-Vergleich. **🟢 OK**.

### MQTT-Subscriber (`services/mqtt_subscriber.py`)
- `uplink.time or datetime.now(tz=UTC)` (drei Stellen Z.116/236/390).
  ChirpStack liefert `uplink.time` als ISO-8601 mit TZ-Offset, Fallback
  ist UTC. **🟢 OK**.

---

## 6. Frontend Time-Display

`frontend/src/lib/format.ts`:
- `Intl.DateTimeFormat("de-AT", ...)` — JS-Standard: ohne explizite
  `timeZone`-Option wird die **Browser-lokale Zeitzone** verwendet.
  Für den Hotelier-Browser in Kaprun ist das Europe/Vienna mit
  automatischem DST-Handling. **🟢 OK**.
- `new Date(iso).getTime()` und `Date.now()` liefern Unix-Timestamps
  (ms seit Epoch). Subtraktionen wie in `overrides-display.ts:39`
  (`new Date(expiresAt).getTime() - now`) sind monoton und
  DST-immun. **🟢 OK**.

`frontend/src/lib/overrides-display.ts:31-51` (`useRemainingTime`):
- Reine Timestamp-Differenz, kein Wall-Clock-Vergleich. **🟢 OK**.

`frontend/src/app/einstellungen/temperaturen-zeiten/page.tsx`:
- `night_start` / `night_end` werden als `time`-Input editiert
  (Z.164-183) und als ISO-Strings übergeben. UI zeigt wall-clock —
  dieselbe Form wie der Hotelier sie eingibt. **🟢 OK** auf
  Display-Ebene.
- Hinweis: dass die UI-Anzeige (z.B. „Nachtabsenkung 22:00 – 06:00")
  und das tatsächliche Engine-Verhalten (heute 22:00 **UTC**, nicht
  CET/CEST) **auseinanderlaufen**, ist die Folge von §2.4. Das ist
  Backend-Bug, nicht Frontend-Bug.

`frontend/src/components/patterns/engine-decision-panel.tsx`,
`manual-override-panel.tsx`, `engine-window-indicator.tsx`,
`occupancy-form.tsx`, `belegungen/page.tsx`, `devices/.../page.tsx`,
`sensor-readings-chart.tsx`:
- Alle nutzen entweder `formatDateTime(iso)` (`Intl.DateTimeFormat` mit
  Browser-TZ) oder `new Date(iso)` für Subtraktionen. Keine
  manuellen Wall-Clock-Vergleiche oder TZ-Konversionen. **🟢 OK**.

---

## 7. Befund-Klassifikation

### 🔴 KRITISCH — 1 Stelle

**`backend/src/heizung/rules/engine.py:330` — Layer 2 Nachtabsenkung
vergleicht UTC-Wallclock gegen Hotelier-Local-Wallclock.**

```python
now_t = now.time()   # now = datetime.now(tz=UTC), ergibt UTC-time
if _is_in_night_window(now_t, night_start, night_end):
```

`night_start` / `night_end` werden vom Hotelier im UI als
lokale Wiener Zeit eingegeben (Beispiel: „22:00" als
Nachtabsenkungs-Start). Die Engine vergleicht aber gegen die
UTC-Stunde. Effektiver Offset:

- **Sommer (CEST, UTC+2):** Setback startet 2h später als gewollt
  (22:00 CEST ≠ 22:00 UTC).
- **Winter (CET, UTC+1):** Setback startet 1h später als gewollt
  (22:00 CET ≠ 22:00 UTC).
- **DST-Wechsel 2026-10-25 (CEST→CET):** Der effektive lokale
  Setback-Start verschiebt sich um 1h von „00:00 lokal" (vorher)
  auf „23:00 lokal" (nachher). Hotelier nimmt eine plötzliche
  Stunden-Verschiebung der Setback-Zeit wahr.

**Wichtig:** Es gibt **keine doppelte Tick-Ausführung** und **keinen
ein-Stunden-Aussetzer** beim DST-Wechsel — Engine läuft monoton in
UTC, der Beat-Scheduler ist intervall-basiert. Die im
B-10-4-Backlog-Eintrag formulierte Sorge („doppelte Stunde / Stunde
übersprungen") trifft auf den Beat-Pfad **nicht** zu (siehe §4).

Der Bug ist ein **konstanter Offset zwischen Hotelier-Intent und
Engine-Verhalten**, der bei DST-Wechsel um 1h springt — aber bereits
heute, das ganze Jahr, existiert. Sprint 9.8-Docstring dokumentiert
das explizit als Vereinfachung („kann Sprint 13+ via
global_config.timezone konfigurieren").

Skripte/Tasks/Sensoren sind alle DST-sicher; nur die
Nachtabsenkungs-Triggerschwelle ist betroffen. Layer-2-Vorheizen ist
DST-sicher (siehe §2.3).

### 🟠 RISIKO — 0 Stellen

Keine Stellen identifiziert, bei denen unklar ist, ob Engine-relevant.

### 🟢 OK — alles übrige

19 datetime-Aufrufe TZ-aware, 35 DateTime-Spalten TIMESTAMPTZ,
3 Beat-Schedules in UTC/Intervall, Frontend Browser-TZ-basiert,
Layer 0/1/3/4/5 + Layer-2-Vorheizen DST-sicher.

---

## 8. Empfehlungen für Implementierungs-Brief

**B-10-4 ist NICHT als „kein Fix nötig" abschließbar.** Ein konkreter,
seit Sprint 9.8 dokumentierter Bug existiert (Layer 2 Nachtabsenkung,
§7 🔴-Befund). DST-Wechsel macht den Bug nicht „neu" — aber er macht
ihn am 2026-10-25 für den Hotelier sichtbar als plötzliche
1h-Verschiebung der effektiven Setback-Zeit.

### 8.1 Scope-Vorschlag für Fix-Implementierungs-Brief

**Mini-Sprint B-10-4-Fix** (~1–2 h, Autonomie-Stufe 3):

1. **Engine-Pfad:** `engine.py:layer_temporal` liest in
   `_load_room_context` oder via Helper die Hotel-TZ aus
   `global_config.timezone` (Default `"Europe/Vienna"`), konvertiert
   `now` per `now.astimezone(ZoneInfo(tz_name))` vor dem
   `now.time()`-Extrahieren.
2. **`_RoomContext`-Erweiterung:** Optional `tz_name: str`-Feld, damit
   der Layer nicht direkt auf `global_config` zugreifen muss
   (Domain-Layer-Trennung).
3. **`_is_in_night_window`-Signatur:** bleibt unverändert, weil sie
   bereits wall-clock-zu-wall-clock vergleicht.
4. **Docstring-Update:** `engine.py:295-297` von „Sprint 9.8
   vereinfacht: nutzt now (UTC) direkt" auf „nutzt
   `global_config.timezone` (Default Europe/Vienna), `time`-Spalten
   sind lokale Wall-Clock-Zeiten".
5. **Tests:** zwei neue Layer-2-Tests:
   - **Test-Sommer:** `@freeze_time("2026-07-01T20:00:00Z")` (= 22:00
     CEST), Hotelier-Setting `night_start=22:00` → Setback aktiv.
   - **Test-Winter:** `@freeze_time("2026-12-01T21:00:00Z")` (= 22:00
     CET), Hotelier-Setting `night_start=22:00` → Setback aktiv.
   - Bestandstests in `tests/test_engine_layer2.py` (falls vorhanden)
     auf die neue Konvention prüfen — Test-Fixtures setzen
     wahrscheinlich UTC-Stunden, müssen ggf. auf lokale Stunden
     umgestellt werden.
6. **Migration:** **NICHT erforderlich** — `global_config.timezone`
   existiert bereits mit Default `"Europe/Vienna"`,
   `night_start`/`night_end` bleiben `Time` (lokale Wall-Clock-Intent
   ist bereits implizit).

### 8.2 Backward-Compat & Risiko-Bewertung Fix

- **Bestehende rule_config-Daten** (heute auf Seed-Defaults
  `night_start=22:00:00`, `night_end=06:00:00`): wurden eingegeben in
  der Annahme „lokale Zeit". Fix richtet das Verhalten am Hotelier-
  Intent aus — keine Daten-Migration nötig.
- **Aktuell laufende Tests** in `test_engine_layer2.py` oder
  `test_engine_skeleton.py` (falls vorhanden) müssen geprüft werden:
  wenn sie auf den UTC-Bug aufgebaut sind, müssen sie auf lokale
  Stunden umgestellt werden. **Phase-0-Aufwand: ~10 Min zur
  Identifikation.**
- **Engine-Trace im `event_log`**: trägt `time` weiterhin in UTC
  (TIMESTAMPTZ), Detail-String wird das `now_t` weiterhin als
  ISO-Time loggen — kein Format-Bruch.

### 8.3 Timing-Empfehlung

Fix sollte VOR Heizperiode-Start (Mitte Oktober 2026) gemerged sein.
Heute (2026-05-25) sind das **~5 Monate Lead-Time**. Empfehlung:
**Fix als separaten Mini-Sprint vor Sprint 11 einplanen**, mit
eigenem Brief und Tag (`v0.1.18d-dst-night-setback` oder ähnlich, je
nach Mini-Sprint-Bündelung). Kein Druck auf Hygiene-Mini-Sprint
v0.1.18c.

### 8.4 Was NICHT gefixt werden muss

Alle DST-spezifischen Risiken aus dem ursprünglichen
B-10-4-Backlog-Eintrag (doppelte Tick-Ausführung, Stunden-Aussetzer,
Trace-Zeitstempel-Inkonsistenz) sind im aktuellen Stand **nicht
real** — die Engine arbeitet konsequent in UTC, Beat-Schedule ist
DST-immun, Frontend nutzt Browser-TZ mit DST-Auto-Handling.

---

## 9. Offene Fragen für Strategie-Chat

1. **Fix-Scope (eigener Brief vs. in B-10-4-Branch):** Brief sagt
   Stop 2 trifft die Entscheidung. Empfehlung Phase-0:
   **eigener Implementierungs-Brief** für B-10-4-Fix, weil:
   - Code-Touch im `rules/engine`-Modul ist Engine-Logik (S1-relevant),
     verdient eigenen sauberen Sprint mit Phase-0-Quellcheck der
     Layer-2-Tests + Strategie-Setzung zur Behandlung der historischen
     UTC-Test-Fixtures.
   - Heute-Audit-PR liefert nur die Doku; Code-Add wäre Mischung von
     Read-Only-Audit und Engine-Refactor in einer PR — bricht
     Iterations-Regel §5.1 (EIN Thema → EIN PR).
2. **Kommunikation an Hotelier:** Wenn der Bug seit Sprint 9.8
   existiert (effektive Setback-Zeit liegt 1-2h **später** als
   eingestellt), ist die heutige Setback-Stunde im Sommer/Winter
   möglicherweise schon empirisch vom Hotelier angepasst worden
   (z.B. „22:00 eingegeben damit es um 24:00 lokal greift"). **Wird
   vor Fix-Implementierung benötigt:** Hotelier-Bestätigung, ob die
   heutigen Einstellungen den UTC-Bug bereits kompensieren oder ob
   sie als Lokal-Zeit gemeint sind. Sonst dreht der Fix das Verhalten
   um 1-2h falsch herum.

---

## 10. Bestätigung

Phase-0-Audit fertig. Kein Code-Touch, kein Schema-Touch, keine
Implementierung. Stop-2-Bedingung ausgelöst (§7 🔴 KRITISCH).

**Stop-2-Empfehlung:** eigener Implementierungs-Brief B-10-4-Fix
(siehe §8.3 + §9.1), Strategie-Chat klärt zusätzlich die
Hotelier-Bestätigungsfrage (§9.2) bevor der Brief verbindlich wird.

PR aus diesem Audit landet ohne Code-Änderungen auf
`docs/b-10-4-dst-phase0-audit`, MERGED durch Strategie-Chat nach
Review.
