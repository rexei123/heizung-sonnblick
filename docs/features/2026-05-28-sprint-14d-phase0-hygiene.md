# Sprint 14d — Phase-0-Audit: RoomList-Override-Bug + Hygiene-Bündel

**Datum:** 2026-05-28
**Branch:** `chore/sprint-14d-phase0`
**Basis:** develop @ `f9a1dce`
**Stufe:** 3 (read-only Audit, kein Code-/Schema-/Migration-Touch)
**Festgelegt (nicht auditiert, nur geprüft):** F1 Indikator + Zähler-Badge, getrennter
Slot (R6) · F2 Single-Query-Aggregat + zwei Schema-Felder · F3 Bündel unter Reißleine.

---

## Zusammenfassung

Die `/zimmer`-Liste hat **die Spalte „Übersteuerung" bereits** (seit 12c.a) — sie
rendert aber **nur** das `lock`-Icon für `guest_override_blocked`, **nie** einen
aktiven-Override-Indikator. Ursache: **`RoomRead`/`Room` trägt kein Override-Feld**
(fehlendes Backend-Feld, **kein** Fehl-Mapping). Der List-Endpoint ist plain
`select(Room)` ohne Enrichment. Ein **Batch-Aggregat-Helper fehlt** im
`override_service` (F2 ist Greenfield). `HeatingZoneRead.active_override` (FU-5)
ist ebenfalls Greenfield. Block A (Bug + FU-5) liegt bei **~M** (oberer Rand). Zwei
Polish-Punkte sind **M** (FU-2 Engine-Setpoint, B-14c-FU-3 display_name) → **Splitt
nach 14e**. **Empfehlung:** Bündel 14d = Block A + XS-Polish (FU-4, FU-6); S/M-Polish → 14e.

---

## §A — RoomTable-Bestand (`frontend/src/app/zimmer/page.tsx`) 🔴

- **Spalte existiert:** Header „Übersteuerung" (`:193-195`, Sprint 12c.a). Zelle
  (`:218-229`) rendert **ausschließlich** das Block-Icon:
  ```tsx
  {r.guest_override_blocked ? (
    <span className="material-symbols-outlined text-text-secondary"
          aria-label="Übersteuerung gesperrt" title="Übersteuerung gesperrt"
          style={{ fontSize: 18 }}>lock</span>
  ) : null}
  ```
- **Datenquelle:** `useRooms()` (`:46`) → `Room[]` (`hooks-rooms.ts:51`, API
  `rooms.ts` `apiClient.get<Room[]>`, **kein Zod**). Der `Room`-Type trägt
  `guest_override_blocked`, **kein** `active_override*`.
- **Befund:** Spalte zeigt nur den 12c.a-Block-Lock; der Aktiv-Override-Indikator
  fehlt **wegen FEHLENDEM Backend-Feld** (`RoomRead` ohne Override), **nicht** wegen
  falschem Mapping. Die Spalten-Überschrift „Übersteuerung" verspricht mehr, als die
  Zelle liefert → der eigentliche Bug.
- **R6-Befund:** Lock + (künftiger) Zähler teilen sich **dieselbe Zelle**. F1 verlangt
  getrennten Slot → Layout-Entscheid nötig (Sub-Slots in einer Zelle vs. eigene Spalte;
  Tabelle hat heute 6 Spalten).

## §B — Backend `RoomRead` + Listen-Endpoint 🔴

- **`schemas/room.py` `RoomRead` (`:39-54`):** `id, number, display_name,
  room_type_id, floor, orientation, status, guest_override_blocked, notes,
  created_at, updated_at` — **kein** `active_override*`.
- **`api/v1/rooms.py` `list_rooms` (`:88-111`):** plain `select(Room)` + Filter
  (room_type/status/floor) + order/offset/limit. **Kein** Eager-Load, **kein**
  Override-Enrichment.
- **Muster enriched `DeviceRead` (14a, `devices.py:_build_device_read` `:100-145`):**
  `DeviceRead.model_validate(device)` → `model_copy(update={"active_override":…})`;
  `active_override` aus `override_service.get_active(room_id, heating_zone_id)`
  **pro Device** (N+1, im Docstring `:111-112` bewusst akzeptiert „< 200 Geräte").
  → Schema-**Form** als Vorlage gut; die **Listen-Aggregation darf das N+1 NICHT
  kopieren** (F2: ein Batch-Query, siehe §D + §I-RD).
- **§5.63-Konsumenten des `Room`-Type (Frontend):** `lib/api/hooks-rooms.ts`
  (`useRooms`), `lib/api/rooms.ts` (`get<Room[]>`), `app/zimmer/page.tsx` (RoomTable),
  `components/patterns/room-form.tsx` (`initial?: Room`),
  `components/patterns/room-override-block-toggle.tsx` (`room: Room`). Additives
  optionales Feld → **kein Bruch**; nur RoomTable konsumiert es aktiv.

## §C — `HeatingZoneRead` (FU-5-Ausgangslage) 🟢

- **`schemas/heating_zone.py` `HeatingZoneRead` (`:29-42`):** `id, room_id, kind,
  name, is_towel_warmer, health_state, created_at, updated_at` — **kein**
  `active_override`. Saubere Greenfield-Erweiterung.
- **`useZoneOverride`-Roundtrip:** definiert `hooks-overrides.ts:60`, aufgerufen in
  **`zone-card.tsx:58`** (Heizzonen-Tab auf `/zimmer/[id]`). ZoneCard holt heute den
  aktiven Zone-Override über einen **separaten Query pro Karte**. FU-5 würde
  `zone.active_override` direkt in `HeatingZoneRead` liefern → der Roundtrip entfällt
  (zone-card.tsx `:52-58` dokumentiert das als Backlog).

## §D — Override-Service: Single-Query-Aggregat-Machbarkeit (F2) 🟠

- **Kein Batch-Helper.** `override_service.get_active(session, room_id,
  heating_zone_id)` (`:366-416`) liefert **einen** Override für **ein** Zimmer/Zone.
  `revoke_all_active_overrides` (`:483-517`) + `cleanup_expired` arbeiten je Einzel-
  Raum. Es gibt **keine** „aktive Overrides je Zimmer/Zone in EINEM Query".
- **Aktiv-Filter belegt (konsistent):** `revoked_at IS NULL AND expires_at > now`
  (`get_active:391-392`, `revoke_all:507-508`, `cleanup` invers `:529`).
- **Skizze neuer Batch-Helper (KEIN Code):**
  `async def active_override_summary(session) -> dict[int, int]` —
  `SELECT room_id, COUNT(DISTINCT heating_zone_id) … WHERE revoked_at IS NULL
  AND expires_at > now() GROUP BY room_id`, im Code zu `{room_id: n_zonen}`
  gemappt. **Semantik-Frage (→ §I-RA):** Room-Scope-Override
  (`heating_zone_id IS NULL`) übersteuert das **ganze Zimmer** — zählt als „alle
  Zonen" oder als „1"? Muss vor Implementation entschieden werden.
- **Aufwand Query:** XS; **Semantik-Entscheid:** S.

## §E — 12c.a-Indikator-Pattern als Wiederverwendungs-Basis 🟢

- **Exakte Stelle (`page.tsx:218-229`):** 5. Spalte (nach „Status"), Header
  „Übersteuerung". Markup: `<span className="material-symbols-outlined
  text-text-secondary" aria-label="Übersteuerung gesperrt" title="…"
  style={{ fontSize: 18 }}>lock</span>`, konditional auf `r.guest_override_blocked`.
- **Befund:** Der neue Override-Zähler kann **denselben Render-Stil** nutzen
  (Material-Symbol-Span + Token-Klasse + `aria-label` + `fontSize: 18`, plus
  Zähler-Badge-Text „N Zonen übersteuert"). **R6-Bedingung:** getrennter Slot vom
  Lock — beide liegen heute in derselben Zelle (Layout-Entscheid §A/R6).

## §F — Polish-FUs (Bestand + Aufwandsklasse)

| FU | Bestand-Befund | Datei(en) | Klasse |
|----|----------------|-----------|--------|
| **B-14b-FU-1** Zone-Aggregat-Ist-Temp im ZoneCard-Header | Header (`zone-card.tsx:77-86`) zeigt nur Name + ZoneHealthBadge + Kind; Ist-Temp nur pro Gerät in ThermostatBubbles. `aggregate_zone_readings` (rules/aggregation.py) existiert, aber nicht in `HeatingZoneRead` exponiert. | `schemas/heating_zone.py`, `api/v1/heating_zones.py`, `zone-card.tsx` | **S** |
| **B-14b-FU-2** Engine-Setpoint im ZoneCard-Header | Kein per-Zone-Engine-Setpoint im Bestand (Engine schreibt per-Room `event_log` / per-Device `control_command`; STATUS-Notiz: „heute nicht im Heizzonen-Tab"). Exponierung pro Zone ist nicht-trivial. | Backend (neue Aggregation/Endpoint) + `zone-card.tsx` | **M** |
| **B-14b-FU-3** Inline-Edit Zone-Eigenschaften | Create-Form vorhanden; `HeatingZoneUpdate`-Schema + PATCH-Endpoint vorhanden; `inline-edit-cell.tsx`-Muster (Zod) vorhanden. | `heating-zone-list.tsx`, ggf. `zone-card.tsx` | **S** |
| **B-14b-FU-4** Übersteuerung-Tab evaluieren | Konzept-Frage (ADR-Backlog ARCHITEKTUR-ENTSCHEIDUNGEN §2335). Doku-Evaluation, kein Pflicht-Code. | Doku (+ ggf. Refactor-Brief) | **XS** (doc-only) |
| **B-14b-FU-6** SourceBadge-Wording | `SOURCE_LABEL` (`lib/overrides-display.ts:13-18`): device→„Drehknopf", frontend_4h→„Für 4 Stunden", … Reines Label-Map, genutzt in 2-3 Stellen. | `lib/overrides-display.ts` | **XS** |
| **B-14c-FU-3** User.display_name | `User`-Modell/-Schema ohne `display_name` (Migration + Schema + Users-API + Benutzer-UI + Dashboard-Greeting + §5.63-Type-Spiegel). Multi-Layer-Backend-Touch. | Migration 0021 + `models/user` + `schemas/user` + `api/v1/users` + Frontend-User-Form + `app/page.tsx` | **M** |

---

## §G — Aufwands-Tabelle

| Block | Inhalt | Klasse |
|-------|--------|--------|
| **Block A — Bug** | `RoomRead.active_override_summary` (F2) + Batch-Query (§D) + List-Endpoint-Enrichment + Frontend-Zähler-Slot (R6, §A/§E) + `Room`-Type + Tests | **S–M** |
| **Block A — FU-5** | `HeatingZoneRead.active_override` + Zone-Endpoint-Enrichment (per-Zone, kleines N) + ZoneCard auf `zone.active_override` umstellen (`useZoneOverride`-Roundtrip raus) + Tests | **S** |
| **Block A gesamt** | Bug + FU-5 (zwei Schema-Felder, ein Batch + ein per-Zone-Enrichment, 2 Frontend-Stellen) | **~M (oberer Rand)** |
| B-14b-FU-1 | Zone-Ist-Temp Header | **S** |
| B-14b-FU-2 | Engine-Setpoint Header | **M** |
| B-14b-FU-3 | Inline-Edit Zone | **S** |
| B-14b-FU-4 | Übersteuerung-Tab-Eval | **XS** (doc) |
| B-14b-FU-6 | SourceBadge-Wording | **XS** |
| B-14c-FU-3 | User.display_name | **M** |

## §H — Splitt-Empfehlung (Reißleine F3)

**Bündel 14d tragbar: bedingt JA** — als **Block A (Bug + FU-5) + die zwei XS-Polish
(FU-4 Doku-Eval, FU-6 Wording)**.

Begründung an der F3-Reißleine:
- **M-Punkte → 14e:** **B-14b-FU-2** (Engine-Setpoint, M — kein Backend-Feld, nicht-
  trivial) und **B-14c-FU-3** (display_name, M — Migration + 5 Layer) schlagen auf M+
  → Splitt-Kandidaten.
- **S-Punkte → 14e (empfohlen):** **B-14b-FU-1** und **B-14b-FU-3** (je S). Block A
  selbst liegt bereits bei **~M**; zwei zusätzliche S-Items würden 14d über S/M heben.
  Daher in 14d **nicht** mitnehmen.
- **In 14d behalten:** Block A + FU-4 (XS, Doku) + FU-6 (XS, Label) — zusammen
  weiterhin im M-Rahmen, ein kohärentes Thema (Override-Sichtbarkeit).

→ **14e-Vorschlag:** B-14b-FU-1, FU-2, FU-3, B-14c-FU-3 (Polish-/display_name-Bündel).

## §I — Offene Risiken / Drift-Funde

- **R-A (Semantik „N Zonen übersteuert"):** Room-Scope-Override
  (`heating_zone_id IS NULL`) gilt fürs ganze Zimmer. Zählung als „alle Zonen" oder
  „1 (ganzes Zimmer)"? **Entscheid vor Implementation** (Strategie-Chat). Beeinflusst
  Badge-Text + Batch-Query (`COUNT(DISTINCT zone_id)` vs. Sonderfall NULL).
- **R-B (R6-Layout):** Lock + Override-Zähler teilen heute die „Übersteuerung"-Zelle.
  F1 verlangt getrennten Slot → Entscheid Sub-Slots-in-einer-Zelle vs. eigene Spalte
  (Mobile: Tabelle hat 6 Spalten, Breiten-Druck prüfen).
- **R-C (§5.63):** `RoomRead` + `HeatingZoneRead`-Schema-Änderungen brauchen
  Frontend-Type-Spiegel (`Room`, `HeatingZone`). `rooms.ts`/`heating-zones` nutzen
  plain Cast (kein Zod) → additiv, kein Bruch, aber Type-Felder pflegen.
- **R-D (N+1-Drift, scharf):** `DeviceRead` nutzt bewusst per-Device-`get_active`
  (N+1, < 200 akzeptiert). Die neue `RoomRead`-Summary **darf das NICHT kopieren** —
  F2 mandatiert **ein** Batch-Query über alle aktiven Overrides. Implementierungs-
  Risiko, wenn jemand das Device-Muster naiv überträgt → im Implementation-Brief
  explizit als Pflicht markieren.
- **R-E (FU-2 Backend-Lücke):** Per-Zone-Engine-Setpoint hat heute kein Feld;
  Engine schreibt per-Room `event_log`. Exponierung = eigener Backend-Aufwand (M) →
  bestätigt Splitt nach 14e.
- **Keine S1-Drift:** keine aspirativen Kommentare / Race / TODO in Steuerlogik
  gefunden. Die einzige „Drift" ist die seit 12c.a semantisch unvollständige
  „Übersteuerung"-Spalte (nur Lock) — genau der Bug, den 14d schließt.

---

**Stop-Point:** Phase-0-Audit abgeschlossen. Kein Code-/Schema-/Migration-/Test-Touch.
Warte auf Strategie-Chat-Freigabe für 14d-Implementation-Brief (inkl. R-A/R6-Entscheid).
