> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprint 7 — Frontend-Dashboard (Geraeteliste + Detail-View)

**Typ:** Frontend / UX
**Ziel:** Hotelier sieht auf einen Blick, welche LoRaWAN-Geraete aktiv sind, mit aktuellen Reading-Werten und 24h-Verlauf pro Geraet. Sichtbarkeit der bisher nur API-/DB-zugaenglichen Daten.
**Branch:** `feat/sprint7-frontend-dashboard` (von `main` nach Sprint-6-Tag)
**Geschaetzte Dauer:** 2 Sessions, ~6–8 h.

---

## Feature-Brief (Phase 1)

### Ausgangslage
- Backend liefert seit Sprint 5: `GET /api/v1/devices`, `GET /api/v1/devices/{id}`, `GET /api/v1/devices/{id}/sensor-readings`. Sprint 6.10: `POST/PATCH /api/v1/devices`.
- Frontend ist Grundgeruest aus Sprint 0 (Next.js 14 App Router, Tailwind, Roboto, Material Symbols Outlined, AppShell mit 200 px Sidebar).
- Keine Datenanzeige bisher. Daten kann man nur per `curl` oder `psql` einsehen.
- `shadcn/ui` ist bisher NICHT installiert (Notiz in STATUS.md, Sprint 0).

### Architektur-Entscheidungen (verbindlich)

**AE-21 — UI-Komponenten-Bibliothek: shadcn/ui**
Source-basierte Komponenten via `npx shadcn@latest add <component>`. Keine NPM-Dependency-Lock-In, Code wird ins Repo kopiert und ist editierbar. Kompatibel mit Tailwind + Roboto + Material Symbols. Anfangs-Set: Button, Table, Card, Skeleton, Sonner (Toasts), Sheet (Mobile-Sidebar). Weitere Komponenten on-demand pro Feature.

**AE-22 — Data-Fetching: TanStack Query (React Query) v5**
Server-State-Management. Stale-while-revalidate, Refetch-on-Focus, Cache-Invalidierung beim PATCH. `refetchInterval: 30000` fuer Reading-Listen (Live-Aktualisierung ohne WebSocket). Keine globalen Stores fuer Server-Daten — nur fuer UI-State (z.B. Filter).

**AE-23 — Charts: Recharts**
Tailwind-kompatibel, in shadcn/ui-Examples nutzbar, Standard-Library fuer React-Charts in TypeScript-Projekten. Fuer Sprint 7 nur LineChart fuer Temperatur+Setpoint-Verlauf. Komplexere Charts spaeter.

**AE-24 — Routing: Next.js App Router (bestehend)**
- `/devices` — Geraeteliste
- `/devices/[id]` — Detail-View
Kein Server-Rendering der API-Daten (kein `cache: 'no-store'`-Pattern). Daten werden client-side via TanStack Query geladen — ChirpStack-Status soll near-realtime sichtbar sein.

**AE-25 — API-Client-Pfad: relativer Fetch zu `/api/v1/...`**
Konsistent mit Sprint 4 (`NEXT_PUBLIC_API_BASE_URL` ist nicht im Build-Bundle eingebrannt). Caddy proxiet `/api/v1/...` an FastAPI.

### Akzeptanzkriterien

- [ ] `npx shadcn@latest init` durchgelaufen, `components.json`, `lib/utils.ts`, `tailwind.config.ts` erweitert
- [ ] Anfangs-Komponenten installiert: Button, Table, Card, Skeleton, Sonner
- [ ] `frontend/src/lib/api/` mit `devices.ts`, `sensor-readings.ts` (Typen + Fetch-Funktionen)
- [ ] TanStack Query in `app/layout.tsx` mit QueryClientProvider eingerichtet
- [ ] Custom Hooks: `useDevices()`, `useDevice(id)`, `useSensorReadings(deviceId, opts)`
- [ ] `/devices`-Seite: shadcn-Table mit `dev_eui`, `label`, `vendor`, `model`, `letzter Reading-Wert`, `last_seen_at`. Loading-Skeleton, Empty-State, Refresh-Button.
- [ ] `/devices/[id]`-Seite: Metadaten-Card oben, KPI-Karten (Temperatur, Setpoint, Battery, RSSI), Recharts-LineChart 24h-Verlauf
- [ ] Refetch alle 30 Sek auf beiden Seiten
- [ ] Material Symbols Outlined fuer Icons (kein Lucide aus AE-01)
- [ ] Design-Strategie 2.0.1: Rose-Akzent `#DD3C71` als Primary, Roboto, 200 px Sidebar bleibt
- [ ] Playwright-Smoke fuer beide Seiten (HTTP 200, kein React-Crash)
- [ ] STATUS.md Abschnitt 2i, ADRs AE-21..25
- [ ] Tag `v0.1.7-frontend-dashboard`

### Abgrenzung — NICHT Teil von Sprint 7

- Keine Zimmer-Uebersicht (kommt mit Sprint 10 Belegungs-Workflow)
- Keine Heizzonen-Anzeige (gleicher Sprint)
- Keine Edit-Forms im UI (PATCH gibt es per API, UI-Forms fuer Verwaltung kommen mit dem Admin-Workflow-Sprint)
- Keine Login/Auth (oeffentlich auf heizung-test, intern via Tailscale)
- Keine WebSocket-Live-Updates (Polling 30 Sek reicht; LoRaWAN-Uplink-Intervall ist 15 Min)
- Keine Mobile-First-Optimierung (Mobile kommt in Folge-Sprint)
- Keine Internationalisierung (nur Deutsch, Sie-Form)
- Kein dunkles Farbschema

### Risiken

1. **shadcn-Init kollidiert mit existierenden Tailwind-Configs:** Sprint-0-Setup hat `tailwind.config.ts` fertig. shadcn ueberschreibt ggf. Custom-Farben.
   **Gegenmassnahme:** vor `shadcn init` das aktuelle `tailwind.config.ts` sichern; nach Init die Rose-Farbe + Roboto wieder einsetzen.

2. **Recharts + SSR:** Recharts hat manchmal Hydration-Issues mit Next.js Server-Components.
   **Gegenmassnahme:** Chart-Komponente als `"use client"` markieren, Lazy-Load mit Loading-Skeleton.

3. **CORS:** Frontend laeuft auf `localhost:3000`, API auf `:8000`. Im Docker-Compose-Stack laeuft Caddy davor — Frontend → Caddy → API; relative Pfade funktionieren. Lokal ohne Caddy = CORS-Header in FastAPI noetig.
   **Gegenmassnahme:** falls notwendig, FastAPI `CORSMiddleware` mit `localhost:3000`-Origin allowen.

4. **Decimal-Werte aus API:** API liefert `temperature` etc. als Float (nach `field_serializer`). Im Frontend einfach als Number behandeln, ggf. `toFixed(1)` fuer Anzeige.

5. **Empty-State:** Wenn keine Devices da sind (Test-Server nach Cleanup), darf UI nicht crashen. Empty-State-Komponente mit „Noch keine Geraete gepairt"-Hinweis.

### Rollback

Nicht-mergen / `git revert`. Frontend-Anpassungen sind isoliert, kein Backend-Touch.

---

## Sprintplan (Phase 2)

### 7.1 — Feature-Brief (dieses Dokument)
User-Gate.

### 7.2 — shadcn/ui initialisieren
- `npx shadcn@latest init` im `frontend/`
- Style: New York
- Base Color: Rose (matcht unser Design-Strategie-Akzent)
- CSS-Variables: ja
- Komponenten installieren: button, table, card, skeleton, sonner, sheet
- `tailwind.config.ts` Rose-Farbe als `primary` mappen, Roboto bleibt globale Schrift
- Smoke: `npm run build` + `npm run dev` ohne Errors

**Dauer:** 30 Min.

### 7.3 — API-Client + Typen
- `frontend/src/lib/api/types.ts` mit `Device`, `SensorReading`, `DeviceCreate`-Typen
- `frontend/src/lib/api/devices.ts` mit `listDevices()`, `getDevice(id)`, `listSensorReadings(deviceId, opts)`
- `frontend/src/lib/api/client.ts` mit Fetch-Wrapper, Error-Handling, JSON-Parse
- Pfade relativ: `/api/v1/devices` etc.

**Dauer:** 45 Min.

### 7.4 — TanStack Query Setup
- `npm i @tanstack/react-query @tanstack/react-query-devtools`
- `frontend/src/lib/query.ts` QueryClient-Singleton
- `frontend/src/components/providers.tsx` mit QueryClientProvider
- `app/layout.tsx` Provider einbinden
- Custom Hooks: `frontend/src/lib/api/hooks.ts` mit `useDevices`, `useDevice`, `useSensorReadings`

**Dauer:** 45 Min.

### 7.5 — Geraeteliste
- `app/devices/page.tsx`
- shadcn-Table mit Spalten: Label, DevEUI (kursiv klein), Vendor, Model, Letzte Temp, Letzter Setpoint, Battery, Last seen
- Klick auf Zeile -> `/devices/{id}` (next/link)
- Loading: 5 Skeleton-Rows
- Error: Alert-Banner
- Empty: „Noch keine Geraete gepairt — Pairing-Anleitung siehe RUNBOOK §10"

**Dauer:** 1.5 h.

### 7.6 — Detail-View + Chart
- `app/devices/[id]/page.tsx`
- Header-Card: Label, DevEUI, Vendor/Model, Status (aktiv/inaktiv), Last Seen
- KPI-Cards: Temp, Setpoint, Motor-Position, Battery
- Chart-Card: Recharts LineChart 24h, X-Achse Zeit, Y-Achse Temperatur
- Reading-Liste unten: Tabelle mit den letzten 50 Readings
- 404-Handling falls `id` nicht existiert

**Dauer:** 2 h.

### 7.7 — Playwright-Smoke
- `frontend/tests/e2e/devices.spec.ts`
- Test 1: GET `/devices` -> 200, Tabelle hat `<thead>`
- Test 2: GET `/devices/<bekannte-id>` mit gemockter API-Response -> Chart-Element rendert (data-testid)
- Test 3: Empty-State

**Dauer:** 45 Min.

### 7.8 — Doku + PR + Tag
- STATUS.md Abschnitt 2i mit Lessons Learned
- ADRs AE-21..25
- Frontend-README mit shadcn-Component-Liste
- PR `feat/sprint7-frontend-dashboard → main`, CI grün
- Tag `v0.1.7-frontend-dashboard`
- `main → develop`-Sync

**Dauer:** 30 Min.

---

## Phase-Gates

- **Gate 1+2 (jetzt):** Feature-Brief + Sprintplan freigegeben
- **Gate 3 (nach 7.4):** TanStack Query laeuft, ein erster Hook fetched gegen lokale API
- **Gate 4 (nach 7.5):** `/devices` lokal aufrufbar mit echten DB-Daten
- **Gate 5 (nach 7.6):** Detail-View + Chart sichtbar, Refresh alle 30 Sek
- **Gate 6 (nach 7.8):** Tag gesetzt

---

## Offene Fragen / Annahmen

- **[Annahme]** Recharts-LineChart kommt mit Decimals als number klar. Falls nicht, im API-Hook `Number(...)` casten.
- **[Annahme]** shadcn-Init erkennt das bestehende Tailwind-Setup und ueberschreibt nicht Critical Files. Falls doch — Backup vor Init aus Sprint 0 vorhanden.
- **[Annahme]** FastAPI-CORS ist im Stack-via-Caddy-Setup ueberfluessig. Lokal ohne Caddy ggf. CORS-Middleware temporaer aktivieren.
- **[Annahme]** Roboto wird via Google-Fonts-CDN geladen (Sprint 0), shadcn ueberschreibt das nicht.
