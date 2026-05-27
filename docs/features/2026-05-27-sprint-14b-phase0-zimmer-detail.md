# Sprint 14b — Phase-0-Audit: Zimmer-Detail Zone-scoped Restruktur

**Datum:** 2026-05-27
**Branch:** `chore/sprint-14b-phase0-audit`
**Basis:** develop @ `cb5f364`
**Stufe:** 3 (read-only Audit, kein Code-Touch)
**Vor-Entscheidungen (Strategie-Chat 2026-05-27, nicht erneut diskutiert):**
Variante B additiv (DevicesInRoom bleibt, neuer `ZonesInRoom`-Wrapper),
Card-per-Zone, Setpoint/Override pro Zone (AE-51), Bubble-Variante B detailliert,
`/zimmer`-Übersicht unverändert, Sprint-13b.2-Selektoren erhalten.

---

## A — Aktueller `/zimmer/[id]`-Aufbau

**Befund:** `frontend/src/app/zimmer/[id]/page.tsx` (456 Z.). Die Seite ist
**tab-basiert** (`Tab`-Type `:32`), Tab-Leiste `:163-186`:

```tsx
(["stammdaten", "zonen", "geraete", "engine", "override"] as const)
// Labels: Stammdaten · Heizzonen · Geräte · Engine · Übersteuerung
```

Tab-Render `:188-211`: `override` → `<ManualOverridePanelList roomId={id} />`;
sonst `stammdaten`→`RoomForm`, `zonen`→`HeatingZoneList`, `geraete`→
`DevicesInRoom`, `engine`→`EngineDecisionPanel`.

- **Hooks (Page-Level):** `useRoom`, `useUpdateRoom`, `useDeleteRoom`,
  `useRoomOverrides`, `useDevices`, `useHeatingZones` (`:22-29,38-60`).
- **Dialog-State am Page-Root** (`openReplaceDialog`/`openRetireDialog`,
  `:53-56`, B-Sprint13b2-5) — Dialoge `:226-244` außerhalb von DevicesInRoom.
- **Keine Zonen-Gruppierung heute:** der „Geräte"-Tab rendert eine **flache**
  Geräteliste (siehe B).

**Klassifikation:** 🟢 unproblematisch
**Konsequenz:** ZonesInRoom fügt sich additiv ein (eigener Tab oder Erweiterung
des „Heizzonen"-Tabs). Tab-Gerüst + Page-Root-Dialoge bleiben unberührt.

---

## B — `DevicesInRoom`-Komponente

**Befund:** **Inline-Funktion** in `zimmer/[id]/page.tsx:249-…` (KEIN separates
File). Props `{ roomId, onReplaceClick, onRetireClick }` (`:249-256`).

- **Filter (`:267-270`):** holt `useHeatingZones(roomId)` + `useDevices()` (alle
  aktiven Devices) und filtert **client-seitig auf ALLE Zonen des Zimmers**
  (`zoneIds.has(d.heating_zone_id)`) — **nicht pro einzelner Zone**.
- **Render (`:308-349`):** flaches `<ul>`, ein `<li>` pro Device mit:
  `label ?? dev_eui` + `HardwareStatusBadge variant="compact"` + Zeile
  `{vendor} {model} · Zone {name}` + „Detail →"-Link + `ReplaceDeviceButton` +
  `RetireDeviceButton` + `DetachButton`.
- **Heute NICHT gezeigt:** Ist-Temp, Batterie, Sollwert, Signal (nur der
  Hardware-Badge). **Kein** Inline-Edit (Bezeichnung/Hardware-Nr leben auf
  `/devices/[id]`).
- **Mutations:** Detach via `useDetachDeviceZone`; Replace/Retire über die
  Page-Root-Dialoge (`onReplaceClick`/`onRetireClick`).

**Klassifikation:** 🟡 Anpassung im Brief vorsehen
**Konsequenz:** Zwei Spannungen zur Vor-Entscheidung:
1. DevicesInRoom filtert **room-weit**, nicht pro Zone → für „eine Bubble-Gruppe
   pro Zone-Karte" kann DevicesInRoom **nicht 1:1 pro Zone wiederverwendet**
   werden (es würde in jeder Karte alle Room-Devices rendern). Entweder
   `zoneId`-Filter-Prop ergänzen (kleine Änderung) **oder** ZonesInRoom rendert
   eigene Bubbles und DevicesInRoom bleibt nur im „Geräte"-Tab.
2. Bubble-Variante B (detailliert: + Ist-Temp + Batterie) ist **reicher** als
   das heutige DevicesInRoom-Rendering → die Bubbles sind faktisch **neues
   Rendering**, nicht DevicesInRoom verbatim. „DevicesInRoom bleibt erhalten"
   gilt für den unveränderten „Geräte"-Tab, nicht als Bubble-Quelle.

---

## C — Sprint-13b.2-Selektor-Hierarchie

**Befund:** `frontend/tests/e2e/sprint13b2-device-replacement.spec.ts` — **alle**
DevicesInRoom-Zugriffe sind **role-/text-basiert, keine `data-testid`**:

- Tab-Einstieg: `getByRole("button", { name: "Geräte", exact: true }).click()` (z. B. `:224`).
- Buttons: `"Thermostat tauschen"` (`:227`), `"Thermostat stilllegen"` (`:429`),
  Dialog-Confirm `"Tauschen"` (`:240`)/`"Stilllegen"` (`:446`).
- Toasts/Warnungen: `"Thermostat getauscht — …"` (`:244`), `"Letzter aktiver
  Thermostat dieser Zone."` (`:439`), `"Thermostat nicht gefunden…"` (`:624`).

**Klassifikation:** 🟢 unproblematisch — **wenn** Variante B additiv eingehalten
wird.
**Konsequenz:** Selektoren bleiben stabil, **solange der „Geräte"-Tab
DevicesInRoom unverändert rendert** (gleicher Tab-Name, gleiche Button-Labels).
ZonesInRoom als **separater** Tab/Abschnitt berührt diese Tests nicht. **Bedingung
für 🟢:** ZonesInRoom darf den „Geräte"-Tab nicht ersetzen. Falls der Brief
DevicesInRoom doch verändert (zoneId-Prop o. ä.) und dabei Tab/Labels touched →
**STOP-Empfehlung + Sprint-Stufe 1**. Aktuell kein Bruch absehbar.

---

## D — Heating-Zone-API: `health_state`?

**Befund:** `backend/src/heizung/api/v1/heating_zones.py:70-83`
(`GET /api/v1/rooms/{room_id}/heating-zones` → `list[HeatingZoneRead]`).
`schemas/heating_zone.py:29-41` `HeatingZoneRead`:

```python
id, room_id, kind, name, is_towel_warmer,
health_state: Literal["healthy", "degraded", "silent", "no_device"],
created_at, updated_at
```

**`health_state` wird bereits geliefert.** **Nicht** enthalten: Ist-Temp,
Soll-Temp, Devices-Liste.

**Klassifikation:** 🟢 (für ZoneHealthBadge) / 🟡 (für Bubble-Daten)
**Konsequenz:** ZoneHealthBadge kann `health_state` direkt aus
`useHeatingZones` konsumieren — **kein Backend-Touch** dafür. Aber Ist-/Soll-Temp
pro Zone fehlen (siehe E).

---

## E — Zone-Aggregat-Reads (AE-51) + Setpoint

**Befund:**
- **Kein Setpoint-Write-Endpoint vorhanden.** `grep` über `api/v1/` findet nur
  den heating-zones-CRUD-Router (`heating_zones.py:48`), **kein**
  `PUT /heating-zones/{id}/setpoint`. Setpoints berechnet die Engine; manuelle
  Eingabe läuft über **Overrides** (`manual_override`).
- **Zone-Aggregat-Ist-Temp** (AE-51 Mittelwert healthy Vickis) ist **nirgends als
  API-Feld exponiert** — weder in `HeatingZoneRead` noch sonst (engine-intern).
- **Override-Endpoint:** `rooms/{room_id}/overrides` (overrides.py) mit
  optionalem `heating_zone_id` (AE-58, zone-scoped). `DeviceRead.active_override`
  liefert den aktiven Override read-only (Sprint 14a).

**Klassifikation:** 🔴→🟡 (Klärungs-Blocker, kein Code-Blocker)
**Konsequenz:** „Setpoint-Steuerung pro Zone" hat **keinen** dedizierten
Endpoint — gemeint ist ein **zone-scoped Override** (`heating_zone_id` im
overrides-POST). Das existiert bereits (AE-58). Ein „rohen Sollwert setzen" gibt
es bewusst nicht (Engine-Hoheit). **Offene Frage 1** (siehe unten).

---

## F — Override-Status-Anzeige

**Befund:** Override-Verwaltung im **„Übersteuerung"-Tab** via
`<ManualOverridePanelList roomId={id} />` (`:188-189`). Daten: `useRoomOverrides`
(`hooks-overrides`, `:23,42`). Aktive-Anzahl wird für den Block-Toggle berechnet
(`:43-46`). Zusätzlich liefert die Sprint-14a `DeviceRead.active_override`
(Quelle, Sollwert, Ablauf) pro Device read-only.

**Klassifikation:** 🟢 (AE-61-konform)
**Konsequenz:** Override-**Aktionen** liegen bereits auf der Zimmer-Seite
(Übersteuerung-Tab) — AE-61 erfüllt. Die neuen Zone-Karten können den aktiven
Override **read-only** pro Zone anzeigen (aus `active_override` bzw.
`useRoomOverrides` mit `heating_zone_id`); für Aktionen auf die bestehende
Override-UI verlinken/wiederverwenden.

---

## G — `data-testid`-Vorschläge (neue Komponenten)

**Befund:** DevicesInRoom-Kinder haben **kein** `data-testid` (role/text).
Bestands-Konvention kebab-case (`device-zuordnung`, `zone-health-badge`,
`override-card`, …).

**Klassifikation:** 🟢
**Konsequenz:** Neue testids konfliktfrei: `zones-in-room`,
`zone-card-{zone_id}`, `zone-card-{zone_id}-header`,
`zone-card-{zone_id}-setpoint-button`, `zone-card-{zone_id}-override-button`,
`zone-card-{zone_id}-devices`. Bestands-Selektoren (Sprint 13b.2) bleiben
role/text-basiert und unberührt.

---

## H — Mobile-Layout-Risiko

**Befund:** Tab-Content in `bg-surface border rounded-md p-5` (`:191`); flache
Liste, keine Grid-/Breakpoint-Sonderregeln. Tabs als horizontale Flex-Leiste
(`:163`).

**Klassifikation:** 🟢
**Konsequenz:** Card-per-Zone stapelt vertikal → Mobile-tauglich. Bei 3 Zonen ×
(Header + Bubbles + Buttons) wächst die Page-Länge, aber kein horizontales
Overflow-Risiko. Tab-Leiste bei vielen Tabs ggf. scrollbar prüfen (heute 5 Tabs,
unkritisch).

---

## I — Override-Hierarchie (AE-58) Sichtbarkeit

**Befund:** `OverrideSource` unterscheidet `device` (Vicki-Drehknopf) vs.
`frontend_4h`/`frontend_midnight`/`frontend_checkout`. `DeviceRead.active_override`
(14a) trägt `source` + `setpoint_celsius` + `expires_at`. ManualOverridePanelList
zeigt die Overrides des Raums.

**Klassifikation:** 🟡
**Konsequenz:** Die Zone-Karte soll erkennbar machen: überstimmt ja/nein, Quelle
(Drehknopf vs. Rezeption), bis wann. Datenquelle vorhanden (`active_override` /
`useRoomOverrides` zone-gefiltert). Reine Anzeige, kein Backend-Touch — aber
Mapping Override→Zone klären (Override kann room-scoped `heating_zone_id=NULL`
sein → gilt für alle Zonen; oder zone-scoped).

---

## J — Datenmodell-Map Room → Zone → Device

**Befund:** Heute client-seitig in DevicesInRoom: `useHeatingZones(roomId)` +
`useDevices()` (alle aktiven), Filter `d.heating_zone_id ∈ zoneIds` (`:267-270`).
**Mehrere Hooks + Client-Merge**, kein enriched „Room-mit-Zonen-mit-Devices"-
Endpoint. §5.58: `useDevices()` ohne `include_retired` → Backend filtert
`retired_at IS NULL` → retired Devices erscheinen nicht. 🟢

**Klassifikation:** 🟢
**Konsequenz:** ZonesInRoom nutzt dasselbe Muster (Zonen aus `useHeatingZones`,
Devices client-seitig nach `heating_zone_id` **pro Zone** gruppieren). Kein neuer
Aggregat-Endpoint nötig für die Gruppierung — wohl aber für Bubble-Ist-Temp/
Batterie (siehe E + Offene Frage 2).

---

## Gesamt-Befund

- **Kein trivialer Reiner-Wrapper.** ZonesInRoom-Gruppierung + Zone-Karten sind
  Frontend-überschaubar, ABER zwei Daten-Lücken brauchen eine Brief-Entscheidung:
  1. **Setpoint pro Zone** = zone-scoped Override (kein Setpoint-Endpoint) — E.
  2. **Bubble Ist-Temp + Batterie** sind **nicht** in `DeviceRead.latest_reading`
     (nur `valve_position`/`open_window`/`attached_backplate`) und **nicht** in
     `HeatingZoneRead` → Backend-Erweiterung oder per-Device-Readings-Fetch nötig.
- **ZoneHealthBadge-Daten (`health_state`) sind da** — kein Backend-Touch dafür.
- **Sprint-13b.2-Selektoren stabil**, solange der „Geräte"-Tab DevicesInRoom
  unverändert behält (Variante B additiv).

## Geschätzter Implementation-Aufwand (~5–7 h)

| Teil | Aufwand |
|---|---|
| Backend (`DeviceLatestReadingRead` + `temperature` + `battery_percent`, falls Bubble-Variante B; health_state schon da) | 30–60 Min |
| Frontend `ZonesInRoom`-Wrapper + Zone-Karten + Thermostat-Bubbles | 2–3 h |
| Setpoint-/Override-pro-Zone-UI (zone-scoped Override über Bestands-Endpoint, read-only Status + Verlinkung auf Override-Tab) | 1–1,5 h |
| Playwright (neue ZonesInRoom-Tests + Verifikation Sprint-13b.2 stabil) | ~1 h |
| Cowork-Begehung + Doku (STATUS, ggf. AE) | 0,5–1 h |

## Offene Fragen für Strategie-Chat

1. **„Setpoint-Steuerung pro Zone":** Es gibt **keinen** Setpoint-Write-Endpoint.
   Gemeint ist ein zone-scoped **Override** (`rooms/{id}/overrides` mit
   `heating_zone_id`, AE-58, existiert)? Oder soll ein echter Sollwert-Endpoint
   neu gebaut werden (widerspräche Engine-Hoheit)? **Empfehlung:** zone-scoped
   Override wiederverwenden, „Setpoint-Button" = Override-Dialog vorbelegt.
2. **Bubble-Ist-Temp + Batterie:** nicht in `DeviceRead.latest_reading`. Variante
   (a) `DeviceLatestReadingRead` um `temperature` + `battery_percent` erweitern
   (sauber, ~30–60 Min, additiv) **oder** (b) per-Device
   `/devices/{id}/sensor-readings`-Fetch (N+1, kein Backend-Touch)? **Empfehlung:**
   (a) — Schema-Erweiterung, konsistent mit 14a-Pattern, ein Request pro Liste.
3. **Zone-Aggregat-Ist-Temp (AE-51):** nirgends als Endpoint. Zeigt die
   Zone-Karte pro-Device-Ist-Temp (Bubbles) **oder** das Zone-Aggregat (dann neuer
   Compute/Endpoint)? **Empfehlung:** pro-Device in Bubbles (vorhanden via #2),
   Zone-Aggregat-Endpoint später (eigener Backlog), nicht 14b.
4. **ZonesInRoom-Platzierung:** neuer Tab, oder Erweiterung des „Heizzonen"-Tabs
   (HeatingZoneList → ZonesInRoom)? **Pflicht:** der „Geräte"-Tab mit
   DevicesInRoom muss **unverändert bestehen bleiben** (Sprint-13b.2-Selektoren,
   C). **Empfehlung:** „Heizzonen"-Tab zu Zone-Karten ausbauen, „Geräte"-Tab
   unangetastet lassen.

---

**Stop-Point:** Audit abgeschlossen. Kein Code-Touch, kein Backend-Schema-Touch,
keine Test-Anpassung. Warte auf Implementation-Brief.
