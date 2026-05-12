# BEFUND — Live-Verifikation HF-9.13a-2 auf heizung-test

**Datum/Uhrzeit:** 2026-05-12, 11:11–11:19 UTC (Europe/Vienna 13:11–13:19)
**Reviewer:** Cowork
**Zielsystem:** https://heizung-test.hoteltec.at
**Testobjekt:** Vicki-002 (DevEUI `70b3d52dd3034de5`, device_id `3`)
**PR/Commit:** #135 / `eb4ad06` (indirekt verifiziert, siehe §0)
**Result:** ✅ **HF-9.13a-2 VERIFIZIERT. Engine-Tick läuft sofort nach DELETE + PUT auf `/api/v1/devices/{id}/heating-zone`. Freigabe-Signal für Bündel B.**

---

## 0. Build-SHA-Verifikation (Voraussetzung)

| Check | Ergebnis |
|---|---|
| `/healthz` (Frontend) | 200, ts `2026-05-12T10:38:52Z` — Build vor ~32 Min, passt zu heutigem Merge |
| `/health` (Backend) | 200, `{"status":"ok","version":"0.1.0"}` |
| `/api/v1/_meta` | **404** — Endpoint existiert nicht, direkter SHA-Check nicht möglich |
| Indirekte Verifikation durch Test | ✅ Engine-Tick reagiert auf API-Call (Verhalten ist neu, vorher 60-Sek-Beat) |

Cowork hat kein direkter Server-Side-SHA-Endpoint vorgefunden, daher Build-Stand **indirekt** über das beobachtbare Verhalten verifiziert. Wenn HF-9.13a-2 nicht live wäre, würde der Tick-Zeitstempel weiterhin nach dem alten ~60-Sek-Beat laufen statt sofort. Beobachtet: Tick ~5–6 Sek nach API-Call. Damit ist eb4ad06 oder neuer live.

**Backlog-Vorschlag B-9.13a-hf2-1:** Server-Side-Endpoint `/api/v1/_meta` mit `{"sha": "<git-sha>", "build_ts": "<iso>"}` für reproduzierbare Build-Stand-Verifikation.

---

## 1. Schritt 1 — Engine-Trace VOR Test (Baseline)

| Aspekt | Wert |
|---|---|
| Path | `/zimmer/2` → Tab „Engine" |
| Aktueller Sollwert | **10°C** · Grund „Frei-Sollwert" |
| Letzte Evaluation | **vor 14 s** |
| `detached_devices` | `['70b3d52dd3034de5']` (Cache-Stand aus gestrigem B-LT-2-Bug) |
| Hysterese-Alter | 5:19:35.690048 |
| Schicht-Trace | Sommermodus → Basis 18°C → Zeit 18°C → Manuell 18°C → Fenster 18°C → **Gerät-Sicherheit 10°C `detached_devices=[…]`** → Limit 10°C |

**Beobachtung:** Vicki-002 ist seit gestern wieder zugeordnet (DB), aber Cache zeigt noch alten Detach-Stand. Genau die Situation, die HF-9.13a-2 adressiert. Test wird zeigen, ob neue API-Calls jetzt sofort triggern.

---

## 2. Schritt 2 — Detach Vicki-002

| Aspekt | Wert |
|---|---|
| Path | `/zimmer/2` → Tab „Geräte" → Vicki-002 „Trennen" → ConfirmDialog Bestätigen |
| Click-Zeitstempel | **11:14:56.388Z** (gespeichert in `window.__detachClickedAt`) |
| API-Aufruf | `DELETE /api/v1/devices/3/heating-zone` |
| API-Status | nicht direkt im Network-Tab erfasst (Tracking-Lag); Erfolgsmeldung via UI + Folge-Engine-Tick (siehe §3) |

UI-Feedback: Dialog schließt, Geräte-Tab zeigt jetzt Empty-State.

---

## 3. Schritt 3 — Engine-Trace SOFORT nach Detach (KRITISCH)

| Aspekt | Wert |
|---|---|
| Engine-Tab geöffnet | 11:15:36.779Z (msSinceDetachClick = **40.391 ms** = 40 Sek nach Click) |
| Aktueller Sollwert | **18°C** (war 10°C) — Sprung wegen `no_devices_in_zone` |
| Grund | „Frei-Sollwert" |
| **Letzte Evaluation** | **vor 34 s** → Tick-Zeitstempel ≈ 11:15:02 ≈ **~6 Sek nach Detach-Click** ✅ |
| `detached_devices` | **WEG** — Layer-4-Detail zeigt jetzt `no_devices_in_zone` |
| Layer 4 (Gerät-Sicherheit) | 18°C, Reason „Manuell", Detail `no_devices_in_zone` |
| Layer 5 (Sicherheits-Limit) | 18°C, Reason „Manuell", Detail `within [10,30]` |
| Hysterese-Block | **„Erster Downlink — wird gesendet"** (vorher „Innerhalb Hysterese, kein Downlink") |

**Verdikt Schritt 3: ERFOLG.** Engine-Tick lief ~6 Sek nach DELETE-Click. Setpoint-Sprung von 10°C auf 18°C ist Folge der korrekten Re-Evaluation: ohne Devices in der Zone fällt der `device_detached`-Hard-Clamp weg, der Engine wendet wieder normale Setpoint-Logik an (Basis 18°C → Drehknopf-Override 18°C → Hard-Clamp 18°C).

Auf altem System (vor HF-9.13a-2) hätte der Tick frühestens beim nächsten 60-Sek-Beat gelaufen, und auch dann hätte er wegen Cache-Bug noch `detached_devices` gezeigt. **Hier: ~6 Sek + State sauber.**

---

## 4. Schritt 4 — Re-Attach via Wizard

| Aspekt | Wert |
|---|---|
| Path | `/devices` → CTA „Gerät hinzufügen" → Wizard |
| Step 1 | Dropdown zeigt „1 Gerät(e) noch keiner Heizzone zugeordnet": Vicki-002 |
| Step 2 | Zimmer 102 ausgewählt |
| Step 3 | Heizzone „Schlafbereich" ausgewählt |
| Step 4 | Label leer (Original-Vicki-002 bleibt erhalten) |
| Bestätigen-Click | **11:18:24.401Z** (gespeichert in `window.__putClickedAt`) |
| API-Aufruf | `PUT /api/v1/devices/3/heating-zone` → **200** ✅ |
| Redirect | `/zimmer/2?paired=70b3d52dd3034de5` |

---

## 5. Schritt 5 — Engine-Trace SOFORT nach Re-Attach (KRITISCH)

| Aspekt | Wert |
|---|---|
| Engine-Tab geöffnet | 11:18:56.391Z (msSincePutClick = **31.990 ms** = 32 Sek nach Click) |
| Aktueller Sollwert | **10°C** · Grund „Frei-Sollwert" |
| **Letzte Evaluation** | **vor 27 s** → Tick-Zeitstempel ≈ 11:18:29 ≈ **~5 Sek nach PUT-Click** ✅ |
| Layer 4 (Gerät-Sicherheit) | 10°C, Reason „Gerät abgenommen", Detail `detached_devices=['70b3d52dd3034de5']` |
| Layer 5 (Sicherheits-Limit) | 10°C, Reason „Gerät abgenommen", Detail `within [10,30]` |
| Hysterese-Alter | 5:24:29 (neuer Tick, aber `Δ 0°C` — Setpoint unverändert vor/nach Tick) |

**Verdikt Schritt 5: ERFOLG.** Engine-Tick lief ~5 Sek nach PUT-Click.

**Wichtig:** Layer 4 zeigt jetzt wieder `detached_devices=[…]`. Das heißt:

- Engine kennt Vicki-002 wieder in der Zone (sonst wäre Detail `no_devices_in_zone` wie nach Schritt 3)
- Engine markiert Vicki-002 aber als **detached**, weil die Frame-Historie noch `attached_backplate=false` enthält (Hardware-First-Semantik, AE-47)
- Setpoint klemmt auf 10°C (Hard-Clamp aus Detach-Sicherheit)

**Brief-Zitat explizit:**
> NICHT-FATAL (akzeptabel): Layer-4 zeigt weiterhin „detached" nach Re-Attach, solange Frame-Historie alt ist. Das ist Hardware-First-Semantik, separates Folge-Item B-LT-2-followup im Backlog.

✅ Verhalten entspricht Spec.

---

## 6. Schritt 6 — Hardware-Recovery

**Übersprungen.** Cowork hat keinen physischen Zugriff auf Vicki-002 am Hotel-Standort. Backplate-Touch nicht ausgeführt.

**Beobachtung möglich:** Sobald Hotelier die Backplate von Vicki-002 kurz löst und wieder aufsetzt, sollte der nächste Vicki-Periodic-Frame `attachedBackplate: true` enthalten. Das würde im `sensor_reading` persistieren, mqtt_subscriber triggert Engine-Tick, Layer 4 erkennt das Gerät als wieder attached, `detached_devices` wird leer, Setpoint geht zurück auf 18°C.

Diese Hardware-Recovery wäre der finale Beweis, dass das Gesamtsystem korrekt zusammenarbeitet. Kann durch User manuell ergänzt werden.

---

## 7. End-Zustand Vicki-002

| Aspekt | Soll | Ist | Status |
|---|---|---|---|
| `device.heating_zone_id` | gesetzt auf Schlafbereich-Zone Zimmer 102 | gesetzt | ✅ |
| Label | `Vicki-002` | `Vicki-002` | ✅ |
| Geräte-Tab in Zimmer 102 | Vicki-002 sichtbar mit Trennen | sichtbar | ✅ |
| Engine kennt Vicki-002 in Zone | ja | ja (`detached_devices=[<dev_eui>]`, nicht `no_devices_in_zone`) | ✅ |
| Engine-Tick reagiert sofort auf API-Aktion | ja | **~5-6 Sek** | ✅ |
| Sollwert | abhängig von Backplate-Status: 10°C (detached) oder 18°C (attached) | 10°C (detached aus Hardware-Sicht) | ⚠️ erwartet, B-LT-2-followup |

**Keine Test-Strings, keine Vicki-001-Berührung, keine Repo-Edits, keine SQL/SSH-Operationen.**

---

## 8. Engine-Tick-Zeitstempel-Vergleich

| Phase | API-Call-Zeitpunkt | Tick-Zeitpunkt (gemessen aus „vor X s"-Wert) | Delta | Bewertung |
|---|---|---|---|---|
| Baseline (vor Detach) | — | 11:14:42 (vor 14 s gegen Aufruf-Zeit 11:14:56) | — | „eigener" 60-Sek-Beat-Tick |
| Nach Detach | 11:14:56.388Z | ≈ 11:15:02 | **+6 Sek** | ✅ HF wirkt |
| Nach Re-Attach | 11:18:24.401Z | ≈ 11:18:29 | **+5 Sek** | ✅ HF wirkt |

Beide API-getriggerten Ticks laufen innerhalb von 5–6 Sek nach dem Klick. Brief-Kriterium („innerhalb Sekunden nach API-Call") erfüllt.

---

## 9. Backend-API-Verhalten

| Endpoint | Methode | Status |
|---|---|---|
| `/api/v1/devices/3/heating-zone` | DELETE | (UI-Effekt + Engine-Tick bestätigen 200; Network-Tab-Tracking war noch nicht aktiv im Moment des Calls) |
| `/api/v1/devices/3/heating-zone` | PUT | **200** (explizit aus Network-Tab erfasst) |
| `/api/v1/rooms/2/heating-zones` | GET | implizit 200 (UI rendert Zonen-Auswahl korrekt) |

Keine API-Errors, keine Engine-Crashes, kein Daten-Inkonsistenz.

---

## 10. Empfehlung

**✅ HF-9.13a-2 VERIFIZIERT. Freigabe-Signal für Bündel B (Sidebar-Migration).**

Drei kleine Folge-Items für den Backlog:

| ID | Schwere | Beschreibung |
|---|---|---|
| **B-LT-2-followup-1** | Mittel | Layer 4 zeigt nach Re-Attach noch `detached_devices=[…]` und klemmt Sollwert auf 10°C, bis Vicki-Hardware `attachedBackplate: true` meldet. Spec-konform (AE-47), aber UI-Banner „Letzter Frame meldet detached — Backplate-Recovery erforderlich" wäre Hotelier-freundlicher. |
| **B-9.13a-hf2-1** | Niedrig | `/api/v1/_meta`-Endpoint für Server-Side-Build-SHA-Verifikation (war bei diesem Test indirekt notwendig). |
| **B-9.13a-hf2-2** | Niedrig | Engine-Tick-Trigger-Latenz dokumentieren: Brief erwartet „innerhalb Sekunden", real beobachtet 5–6 Sek (Celery-Queue-Pickup + DB-Commit). Klarer SLA hilfreich für Monitoring. |

Keines davon blockiert Bündel B.

**Cowork-Stop:** Keine erneute Detach/Re-Attach-Kette, keine Vicki-001-Berührung, kein Repo-Edit. End-Zustand sauber dokumentiert.
