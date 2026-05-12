# BEFUND — Live-Test Sprint 9.13 Bündel A auf heizung-test

**Datum/Uhrzeit:** 2026-05-11, ca. 16:35–17:05 (Europe/Vienna)
**Reviewer:** Cowork
**Zielsystem:** https://heizung-test.hoteltec.at (Branch `develop`, Commit `aa86c41` + Sprint-9.13a-Merge fae8d91)
**Testobjekt:** Vicki-002 (DevEUI `70b3d52dd3034de5`, device_id `3`)
**Result:** ❌ **DoD NICHT ERFÜLLT — zwei Bugs gefunden, mindestens einer kritisch (Engine-Hard-Clamp). Hotfix-PR empfohlen vor Bündel B.**

---

## 1. Verifikation Voraussetzungen

| # | Check | Status |
|---|---|---|
| 1.1 | Deploy-Stand fae8d91 live (CTA „Gerät hinzufügen" auf /devices sichtbar) | ✅ |
| 1.2 | Sidebar mit allen 6 Einträgen (Übersicht/Zimmer/Belegungen/Raumtypen/Geräte/Einstellungen) | ✅ |
| 1.3 | Vicki-002 vor Test zugeordnet zu Zimmer 102, Heizzone „Schlafbereich" | ✅ |

**Wording-Drift:** Brief spricht von Zone „Schlafzimmer", UI rendert sie als **„Schlafbereich"**. Semantisch identisch, nur Wording-Drift. Nicht-blockierend.

---

## 2. Schritt-für-Schritt

### Schritt 1 — Detach via `/zimmer/2` Geräte-Tab

| Sub-Schritt | Status | Beobachtung |
|---|---|---|
| Zimmer 102 Geräte-Tab öffnen | ✅ | Vicki-002 sichtbar mit Trennen-Button |
| „Trennen"-Button klicken | ✅ | ConfirmDialog erscheint |
| ConfirmDialog-Inhalt | ✅ | „Gerät von Heizzone trennen?" + „Gerät „Vicki-002" wird von Heizzone „Schlafbereich" getrennt. Das Gerät bleibt im System, ist aber keiner Heizzone mehr zugeordnet." |
| Bestätigen | ✅ | **`DELETE /api/v1/devices/3/heating-zone` → 200** |
| Liste OHNE Vicki-002 | ✅ | Zimmer 102 zeigt Empty-State „Noch keine Geräte den Zonen dieses Zimmers zugeordnet." |
| Vicki-002 in /devices ohne Zuordnung | ⚠️ | Keine separate „Zuordnung"-Spalte in der Tabelle vorhanden. Verifikation indirekt über Wizard-Hinweis „1 Gerät(e) noch keiner Heizzone zugeordnet" und über Engine-Trace (siehe §3). |

**Schritt 1: PASS.** Backend-API sauber, UI-Feedback klar.

---

### Schritt 2 — Re-Attach via Wizard

| Sub-Schritt | Status | Beobachtung |
|---|---|---|
| CTA „Gerät hinzufügen" → `/devices/pair` | ✅ | Wizard öffnet, Step 1 zeigt „1 Gerät(e) noch keiner Heizzone zugeordnet" |
| Step 1 Dropdown — Vicki-002 wählbar | ✅ | Eintrag „Vicki-002 · mclimate/MC-LW-V02-BI-RUGGED" |
| Step 2 — Zimmer 102 wählen | ✅ | Dropdown zeigt Zimmer 101–115 + 201–202 |
| Step 3 — Heizzone „Schlafbereich" wählen | ✅ | 2 Zonen verfügbar (Schlafbereich · bedroom, Bad · bathroom) |
| Step 4 — Übersicht: Vicki-002 / 102 · Zimmer 102 / Schlafbereich / Label unverändert | ✅ | Korrekt |
| Bestätigen | ✅ | **`PUT /api/v1/devices/3/heating-zone` → 200** |
| Redirect zu `/zimmer/2?paired=70b3d52dd3034de5` | ✅ | URL-Parameter mit DevEUI |
| Vicki-002 im Geräte-Tab Zimmer 102 | ✅ | Karte mit „Vicki-002 · mclimate MC-LW-V02-BI-RUGGED · Zone Schlafbereich" + Trennen-Button |

**Schritt 2: PASS aus UI-Sicht.** Backend-API sauber. ABER: Engine-Effekt siehe §3 — Engine-Layer 4 hat den Re-Attach **NICHT** erkannt → kritischer Folge-Defekt.

---

### Schritt 3 — Inline-Label-Edit

| Sub-Schritt | Status | Beobachtung |
|---|---|---|
| `/devices` öffnen, Edit-Pencil bei Vicki-002 klicken | ✅ | Input erscheint, leer (Backlog B-9.13a-2 bestätigt) |
| Test-Label `Vicki-002-Live-Test-2026-05-11` eingeben + Enter | ✅ | **`PATCH /api/v1/devices/3` → 200** |
| **UI rendert nach Save:** `Vicki-002Vicki-002-Live-Test-2026-05-11` | ❌ | **BUG B-LT-1 (KRITISCH UX):** Verkettung von altem und neuem Label in der Tabelle |
| Hard-Reload (F5) — Persistierung prüfen | ❌ | Tabelle zeigt weiterhin verkettet `Vicki-002Vicki-002-Live-Test-2026-05-11` |
| Edit-Pencil erneut klicken — Input-Wert | ⚠️ | Input zeigt nur `Vicki-002-Live-Test-2026-05-11` (ohne Prefix). DB-Stand: `label = Vicki-002-Live-Test-2026-05-11`. Frontend-Render-Bug, nicht DB-Append. |
| Rollback-Versuch 1: Input leeren + Enter | ⚠️ | UI rendert jetzt `Device 3` (Fallback bei `label = NULL` oder leer-String). Originaler Vicki-Name-Wert ist offenbar nicht aus `device.name`, sondern war direkt das `label`-Feld. |
| Rollback-Versuch 2: `Vicki-002` eingeben + Enter | ✅ | UI rendert wieder `Vicki-002` (ohne Verdoppelung — vermutlich Dedup-Logik). End-Zustand stabil. |

**Schritt 3: PASS für Persistierung, FAIL für Render-Logik.** Siehe §6 Bugs für Detail.

**Konsolen-Network-Tab:** zwei `503`-Responses auf `https://heizung-test.hoteltec.at/devices/3?_rsc=...` (Next.js RSC-Stream). Sind die Frontend-Page-Streams, nicht die API. Vermutlich Race-Condition zwischen PATCH und Page-Re-Fetch. Nicht-blockierend, aber dokumentationswürdig.

---

## 3. Engine-Trace-Stabilität nach Re-Attach (KRITISCH)

**🚨 PFLICHT-STOP-TRIGGER laut Brief ausgelöst.**

Nach Re-Attach + Inline-Label-Rollback (Zustand: Vicki-002 wieder zugeordnet zu Zimmer 102 Zone Schlafbereich, Label „Vicki-002"):

- Navigiert zu `/zimmer/2` Engine-Tab
- Layer-Trace zeigt:

| Schicht | Setpoint | Grund | Detail |
|---|---|---|---|
| Sommermodus | — | Sommermodus | `summer_mode_inactive` |
| Basis (Belegung) | 18°C | Frei-Sollwert | `status=vacant` |
| Zeitsteuerung | 18°C | Frei-Sollwert | `temporal_inactive` |
| Manueller Override | 18°C | Manuell | Drehknopf, läuft ab 5T 15h · 17.5.2026, 07:55:33 |
| Fenster-Sicherheit | 18°C | Manuell | `no_open_window` |
| **Gerät-Sicherheit** | **10°C** | **Gerät abgenommen** | **`detached_devices=['70b3d52dd3034de5']`** |
| Sicherheits-Limit | 10°C | Gerät abgenommen | `within [10,30]` |

**Aktueller Sollwert: 10°C, Grund: Frei-Sollwert** (UI-Header zeigt allerdings „Frei-Sollwert" als finalen reason, was inkonsistent zu Layer-Detail „Gerät abgenommen" ist — Sub-Bug).

Letzte Evaluation: vor 17s. Hysterese-Alter: 2:54:08 (also der Setpoint klemmt seit ~3h auf 10°C).

**Wartet + Reload (70 Sek Pause)** — **keine Änderung.** Engine sieht Vicki-002 weiterhin als detached.

**Brief-Zitat:**
> „Falls Engine-Trace unerwartet 'device_detached' zeigt OBWOHL Re-Attach erfolgt war: stoppen, melden. Das waere Bug-Verdacht."

---

## 4. End-Zustand Vicki-002 nach Test

| Aspekt | Soll | Ist | Status |
|---|---|---|---|
| `device.heating_zone_id` | gesetzt auf Schlafbereich-Zone von Zimmer 102 | gesetzt | ✅ |
| Label | `Vicki-002` | `Vicki-002` | ✅ |
| Geräte-Tab im Zimmer 102 | Vicki-002 sichtbar mit Trennen-Button | sichtbar | ✅ |
| **Engine-Trace** | **Layer 4/5 ohne `device_detached`-Reason** | **Layer 4/5 zeigt `detached_devices=['70b3d52dd3034de5']`** | **❌** |

**Datenbankseitig ist Vicki-002 wieder im Ursprungs-Setup.** Aber: Engine-Pipeline hat den Re-Attach noch nicht durchgereicht, Zimmer 102 ist auf Hard-Clamp 10°C gefangen. Im Hotel-Live-Betrieb würde das einen kalten Raum bedeuten, bis der Engine-Cache invalidiert.

---

## 5. Backend-API-Verhalten

Alle direkten API-Calls antworten erwartungsgemäß:

```
DELETE /api/v1/devices/3/heating-zone   → 200
PUT    /api/v1/devices/3/heating-zone   → 200
PATCH  /api/v1/devices/3                → 200
GET    /api/v1/devices/3                → 200
GET    /api/v1/devices/3/sensor-readings → 200
GET    /api/v1/rooms/2/heating-zones    → 200
```

**Auffälligkeit:** Mehrere `503`-Responses auf `https://heizung-test.hoteltec.at/devices/3?_rsc=...` (Next.js React-Server-Components-Stream). Race-Condition zwischen PATCH und Page-Re-Fetch — vermutlich harmlos, aber im Log dokumentiert.

---

## 6. Bugs

### B-LT-1: Inline-Label-Edit — Render-Verkettung (UX-kritisch)

**Symptom:** Nach Label-Update zeigt die Geräte-Tabelle den alten Anzeigenamen + den neuen Label-Wert konkateniert (z.B. `Vicki-002Vicki-002-Live-Test-2026-05-11`).

**Reproduktion:**
1. `/devices` → Edit-Pencil bei einem Gerät mit bestehendem Label
2. Neuen Label eingeben → Enter
3. Tabelle rendert konkateniert; F5-Reload bestätigt persistente Anzeige.

**DB-Stand-Verifikation:** Edit-Pencil erneut öffnen zeigt nur den neuen String im Input. Backend hat korrekt gespeichert. Bug liegt im Frontend-Render.

**Hypothese:** Die Render-Komponente verwendet `${device.name}${device.label}` statt `${device.label ?? device.name}`. Empty-Reset führt zu `Device {id}`-Fallback, was die Hypothese stützt (Frontend fällt nur dann auf `name` zurück, wenn `label` truthy ist, sonst wird `Device {id}` gerendert — beide Pfade umgehen `device.name`).

**Schweregrad:** Hoch — Hotelier-Anwender wird Label-Edit als nicht-funktional wahrnehmen. Daten-Verschmutzung möglich (User korrigiert mehrfach, Strings werden lang und unleserlich).

**Empfehlung:** Hotfix-PR vor Bündel B. Render-Logik in der Geräteliste auf `${device.label || device.name || 'Gerät ' + device.id}` umstellen, mit klarer Bedingung.

### B-LT-2: Engine-Cache nach Re-Attach nicht invalidiert (KRITISCH)

**Symptom:** Nach `PUT /api/v1/devices/{id}/heating-zone` (Re-Attach) liefert die Engine weiterhin Layer-Trace mit `Gerät-Sicherheit: Gerät abgenommen / detached_devices=['<dev_eui>']`. Setpoint klemmt auf 10°C.

**Reproduktion:**
1. Vicki detachen → Engine zeigt Layer-4/5 detached-Reason
2. Vicki wieder attachen → API 200, UI zeigt Zuordnung korrekt
3. Engine-Tab refreshen
4. Layer-4/5 zeigt immer noch detached-Reason, Setpoint = 10°C

**Wartezeit:** Min. 70 Sek (≥2 Engine-Ticks) ohne Selbstheilung beobachtet.

**Hypothese:** Engine-Pipeline cached die Detach-Liste pro Zimmer und invalidiert nicht beim Re-Attach. Oder: Der `attached_backplate`-Flag aus AE-47 wird nicht zurückgesetzt, wenn das Gerät einer Zone wieder zugewiesen wird (nur wenn der Vicki selbst meldet, dass es wieder montiert ist). In dem Fall wäre das ein **Architektur-Konflikt zwischen Sprint 9.13a Pairing-Workflow und AE-47 Hardware-First-Window-Detection**.

**Schweregrad:** Kritisch — Hotel-Zimmer könnte nach Hardware-Tausch auf Frostschutz 10°C kleben bleiben, ohne UI-Indikator, ohne Self-Healing-Tick. Gast friert. Eskalations-pflichtig.

**Empfehlung:** **Hotfix-PR vor Bündel B sowie vor jeder weiteren Test-Hardware-Aktion**:

1. Backend-Service `device_zone_changed`-Event soll Engine-Cache pro betroffenem Zimmer invalidieren
2. Optional: UI-Warnbanner im Engine-Tab „Letzte Hardware-Änderung vor 30 s — Engine-Sync läuft" während des nächsten Ticks
3. ADR-Update für AE-47 mit Klarstellung: Manuelles Re-Attach in UI vs. automatisches `attachedBackplate=true` aus Vicki-Hardware

**Workaround bis Hotfix:** Nach jedem Re-Attach den Engine-Tick manuell triggern (falls API-Endpoint existiert) oder Backend neustarten. Aktuell beim Live-Test NICHT getestet, weil Brief-Pflicht-Stop ausgelöst wurde.

---

## 7. Browser-Konsole

App-spezifische Errors: keine.

Hintergrund-Rauschen (Chrome-Extension Adobe Acrobat, nicht App):

```
Error: A listener indicated an asynchronous response by returning true,
but the message channel closed before a response was received
```

---

## 8. Empfehlung

**DoD NICHT ERFÜLLT. Hotfix-PR vor Bündel B Pflicht.**

Zwei Hotfix-Tasks:

- **HF-9.13a-1 — Geräteliste-Render-Logik korrigieren (B-LT-1, UX-kritisch)**
  - Aufwand-Schätzung: 30 Min Code + Playwright-Test
  - Impact: Label-Edit funktioniert visuell wieder

- **HF-9.13a-2 — Engine-Cache-Invalidation bei device_zone_changed (B-LT-2, KRITISCH)**
  - Aufwand-Schätzung: 2–3 h (Service-Layer-Event + Engine-Hook + ADR-Update + Tests)
  - Impact: Verhindert Hard-Clamp-Falle nach Hardware-Tausch im Hotelbetrieb
  - Querverweis: AE-47 (Hardware-First-Window-Detection) — Klarstellung nötig, ob Re-Attach `attachedBackplate=true` setzen darf, oder ob dafür ein Vicki-Hardware-Signal abgewartet werden muss

**Sprint-Bündel-B-Freigabe:** **NEIN, nicht bevor HF-9.13a-2 durch ist.** B-LT-1 könnte parallel mitgemerged werden, ist aber im engeren Sinne nicht blockierend für Bündel B (Sidebar-Migration).

---

## 9. Pflicht-Stop-Verifikation

Brief-Anweisung getriggert: **„Engine-Trace nach Re-Attach instabil bleibt: NICHT erneut detach + re-attach versuchen. User informieren, Engine-Tick abwarten."**

Cowork hat:
- ✅ NICHT erneut detached + re-attached
- ✅ ~70 Sek Wartezeit für Engine-Tick eingebaut, dann F5-Reload
- ✅ Engine-Trace zeigt weiterhin denselben Defekt nach Tick
- ✅ Live-Test gestoppt, BEFUND geschrieben

**End-Zustand der Test-Daten:** Vicki-002 sauber zugeordnet, Label im Original-Zustand (`Vicki-002`). KEINE Test-Strings in der DB hinterlassen. Engine-Cache-Bug ist die einzige Verschmutzung — die hatte aber schon vor dem Test bestanden (Hysterese-Alter 2:54h zeigt, dass der Defekt nicht durch meinen Test entstanden ist, sondern eine bestehende Architekturschwäche ist, die durch das Test-Szenario sichtbar wurde).
