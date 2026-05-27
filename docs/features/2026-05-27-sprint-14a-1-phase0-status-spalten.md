# Sprint 14a.1 — Phase-0-Audit: Status-Spalten /devices-Liste

**Datum:** 2026-05-27
**Branch:** `chore/sprint-14a-1-phase0-audit`
**Basis:** develop @ `897494c` (nach Sprint-14a-Merge, PR #186)
**Stufe:** 3 (read-only Audit, kein Code-Touch)
**Ziel:** Vorbereitung UI-Hotfix „Status"-Spalte → Split in „Gerät" + „Zone".

---

## A — Spalten-Grid `/devices`-Liste

**Befund:** Das Layout ist eine **native HTML-`<table>`** (kein CSS-Grid, kein
shadcn-`<Table>`-Wrapper, kein Flex-Row). `frontend/src/app/devices/page.tsx`:

```tsx
// :150-157
<div className="bg-surface rounded-lg border border-border overflow-hidden">
  <table className="w-full text-sm">
    <thead className="bg-surface-alt text-text-secondary">
      <tr>
        <th className="text-left px-4 py-3 font-medium">Bezeichnung</th>
        <th className="text-left px-4 py-3 font-medium">Zuordnung</th>
        <th className="text-left px-4 py-3 font-medium">Status</th>
```

- **Spalten-Breiten:** Keine expliziten Definitionen — weder `grid-template-columns`
  noch `<col>`/`width`. Breite ist rein auto (Tabellen-Layout); jede Zelle nur
  `px-4 py-3`. Tabelle `w-full`.
- **Header-Wording Status-Spalte:** `Status` (`page.tsx:156`).

**Klassifikation:** 🟢 unproblematisch
**Konsequenz für Hotfix:** Trivialer Spalten-Split — ein viertes `<th>` einfügen
und die Status-`<td>` in zwei Zellen aufteilen. Keine Grid-/shadcn-Hürde, keine
Breiten-Neuberechnung nötig (auto-Layout).

---

## B — Status-Cell-Aufbau

**Befund:** `page.tsx:178-185` (in `DeviceRow`):

```tsx
<td className="px-4 py-3">
  <div className="flex items-start gap-3">
    <HardwareStatusBadge deviceId={d.id} variant="detailed" />
    {d.heating_zone ? (
      <ZoneHealthBadge healthState={d.heating_zone.health_state} variant="compact" />
    ) : null}
  </div>
</td>
```

- **Nebeneinander:** `flex items-start gap-3`, Reihenfolge HardwareStatusBadge →
  ZoneHealthBadge.
- **Render-Variationen HardwareStatusBadge (`detailed`):** zweizeilig, Inhalt
  zustandsabhängig — `hardware-status-badge.tsx:56-59`: Label `Aktiv`/`Inaktiv`,
  Zeile 2 `Zuletzt: <relativ>` bzw. `noch nie`. **Breite ist inhaltsabhängig**
  (bestätigt: Pille + variabler Zeitstring).
- **ZoneHealthBadge** wird **nur gerendert, wenn `d.heating_zone` gesetzt** ist
  (Pool-Devices → keine Zone-Pille).

**Klassifikation:** 🟢 unproblematisch
**Konsequenz für Hotfix:** Split = HardwareStatusBadge in neue „Gerät"-`<td>`,
ZoneHealthBadge in neue „Zone"-`<td>` (mit `null`-Fallback für Pool-Devices,
z. B. `—`). Der `flex`-Wrapper entfällt; jede Badge bekommt eine eigene Zelle.

---

## C — ZoneHealthBadge-Komponente

**Befund:** `frontend/src/components/patterns/zone-health-badge.tsx`.

- **Props-Signatur** (`:19-23`): `{ healthState: ZoneHealthState; variant?: "compact" | "detailed"; className?: string }`.
- **Vier Zustände** (`CONFIG`, `:36-60`): `healthy` („Zone OK", success),
  `degraded` („Zone Achtung", warning), `silent` („Zone Stumm", danger),
  `no_device` („Kein Gerät", neutral). Material-Symbol je Zustand.
- **Default-Breite:** content-abhängige Pille (`inline-flex … px-2 py-0.5`),
  `compact` mit `title`-Tooltip, `detailed` mit zusätzlicher Hint-Zeile.
- **Konsum-Stellen:**
  - `/devices`-Liste — `compact` (`page.tsx:182`).
  - `/devices/[id]`-Detail-Header — **`detailed`** (`[device_id]/page.tsx`, Header-Block).

**Klassifikation:** 🟢 unproblematisch
**Konsequenz für Hotfix:** Keine neue Komponente nötig — beide Badges existieren.
Die Detail-Seite nutzt ZoneHealthBadge im **gestapelten** Header-Flex (kein
Tabellen-Kontext) → **vom Listen-Split nicht betroffen** (bestätigt Übergabe-Brief-
Annahme). Hotfix bleibt rein auf `page.tsx` begrenzt.

---

## D — Mobile-Layout

**Befund:** `page.tsx`.

- Container `:95` `p-6 max-w-content mx-auto`; Tabellen-Wrapper `:150`
  `bg-surface rounded-lg border border-border overflow-hidden`; Tabelle `:151`
  `w-full text-sm`.
- **Keine** responsiven Breakpoints (`sm:`/`md:`/`lg:`) auf Tabelle oder Zellen.
  **Kein** `overflow-x-auto`, **kein** vertikales Stacking. Wrapper hat
  `overflow-hidden` → bei zu schmaler Viewport wird Inhalt **abgeschnitten,
  nicht horizontal scrollbar**.
- Keine Sonder-Layout-Regel für die Status-Cell auf schmalen Viewports.

**Klassifikation:** 🟡 Anpassung nötig
**Konsequenz für Hotfix:** Schon bei 3 Spalten ist die Tabelle auf Mobile eng;
eine **vierte** Spalte verschärft das. Der Implementation-Brief muss eine
Mobile-Strategie setzen: entweder `overflow-x-auto` am Wrapper (horizontaler
Scroll statt `overflow-hidden`-Clipping) **oder** vertikales Stacking ≤ 768px.
Das ist die einzige nicht-triviale Design-Entscheidung des Hotfixes.

---

## E — Playwright-Selectors

**Befund — brechende Selektoren beim Spalten-Split:**

| Datei:Zeile | Selektor | Bruch |
|---|---|---|
| `tests/e2e/devices.spec.ts:120` | `expect(page.locator("th")).toHaveText(["Bezeichnung", "Zuordnung", "Status"])` | 🔴 bricht — 4 statt 3 Header nach Split |
| `tests/e2e/hardware-status-badge.spec.ts:93` | `expect(page.locator("th").filter({ hasText: "Status" }))` | 🔴 bricht, falls Header „Status" in „Gerät"/„Zone" umbenannt wird |
| `tests/e2e/devices.spec.ts:144` | Test-Name „ZoneHealthBadge in **Status-Spalte**" | 🟡 nur Semantik/Name — Selektor `getByTestId("zone-health-badge")` bleibt |

**Befund — stabile Selektoren (testid-/text-basiert, unverändert):**

- `getByTestId("zone-health-badge")` + `[data-health="…"]` — `devices.spec.ts:156,209`,
  `zone-health-badge.spec.ts:87,91,113-114`.
- `getByTestId("device-zuordnung")` — `devices.spec.ts:139`.
- `getByText("Aktiv")` / `getByText(/Zuletzt:/)` (HardwareStatusBadge) —
  `hardware-status-badge.spec.ts:95-96,131-132,182`.
- Detail-Seite `getByText("Status", { exact: true })` — `hardware-status-badge.spec.ts:129`
  bleibt grün (Detail-Header, **kein** `<th>`).

**Klassifikation:** 🟡 Anpassung nötig
**Konsequenz für Hotfix:** Genau **zwei** Asserts anzupassen
(`devices.spec.ts:120` Header-Array auf 4 erweitern; `hardware-status-badge.spec.ts:93`
auf neuen Header-Text). Alle testid-Asserts überleben. Test-Migration klein.

---

## F — `data-testid`-Inventar Status-Cell

**Befund:**

- Status-`<td>` (`page.tsx:178`): **kein** `data-testid`.
- `HardwareStatusBadge` (`hardware-status-badge.tsx`): **kein** `data-testid`,
  nur `role="status"` (`:41,63,84`).
- `ZoneHealthBadge`: **hat** `data-testid="zone-health-badge"` + `data-health`
  (`zone-health-badge.tsx`).
- Bestands-Naming-Konvention (kebab-case): `device-zuordnung`,
  `hardware-number-row`, `kpi-ventilstellung`, `window-backplate-card`,
  `override-card`, `zone-health-badge`.

**Klassifikation:** 🟡 Anpassung empfohlen
**Konsequenz für Hotfix:** Für stabile Split-Tests neue testids vergeben —
Vorschlag konventionskonform: **`device-geraet-status`** (Wrapper um
HardwareStatusBadge in der neuen „Gerät"-Zelle) und **`device-zone-status`**
(neue „Zone"-Zelle). Alternativ die Brief-Vorschläge `device-status-cell` /
`device-zone-cell` — beide passen zur kebab-Konvention. Zusätzlich ein
`data-testid` am HardwareStatusBadge-Wrapper erleichtert die Unterscheidung
(heute nur über „nicht-zone-health-badge" abgrenzbar).

---

## Gesamt-Befund

- **Trivialer Spalten-Split möglich.** Native `<table>` ohne Grid-/shadcn-
  Komplexität; vierte Spalte + Zell-Aufteilung sind reines HTML.
- **Keine neue Komponente nötig** — HardwareStatusBadge + ZoneHealthBadge
  existieren und werden nur umplatziert. Detail-Seite nicht betroffen (stacked).
- **Zwei echte Entscheidungs-/Aufwandspunkte:** (1) Mobile-Overflow-Strategie
  (🟡 D), (2) Header-Wording der zwei neuen Spalten (offene Frage).
- **Test-Migration klein:** 2 brechende Asserts + optional neue testids.

## Geschätzter Implementation-Aufwand (~1,5 h)

| Teil | Aufwand |
|---|---|
| Frontend-Patch (`page.tsx`: 4. `<th>`, Status-`<td>` → „Gerät"+„Zone"-Zellen, Pool-`null`-Fallback, Mobile `overflow-x-auto`, 2 neue testids) | 30–45 Min |
| Test-Anpassung (`devices.spec.ts:120` Header-Array, `hardware-status-badge.spec.ts:93`, optional neue testid-Asserts) | ~30 Min |
| Cowork-Begehung (Desktop + Mobile ≤ 768px, Pool-Device-Zeile) | 15–20 Min |

## Offene Fragen für Strategie-Chat

1. **Header-Wording** der zwei neuen Spalten: „Gerät" + „Zone"? (§5.20: ggf.
   „Thermostat" statt „Gerät" — aber Liste enthält auch Sensoren, daher „Gerät"
   wahrscheinlich korrekt.)
2. **Mobile-Strategie** (🟡 D): `overflow-x-auto` (horizontaler Scroll) vs.
   vertikales Stacking ≤ 768px. Heute `overflow-hidden` → klippt; mit 4 Spalten
   zu klären.
3. **Zone-Spalte bei Pool-Devices** (keine `heating_zone`): leer, „—", oder
   eigener „Reserve"-Hinweis? Heute rendert ZoneHealthBadge dort gar nicht.
4. **ZoneHealthBadge-Variante in eigener Spalte:** `compact` beibehalten oder
   `detailed` (mit Hint-Zeile, breiter)? Beeinflusst Mobile-Breite.

---

**Stop-Point:** Audit abgeschlossen. Kein Code-Touch, keine Test-Anpassung,
keine neue Komponente. Warte auf Implementation-Brief vom Strategie-Chat.
