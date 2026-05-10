# Sprint 2 — Web-Container-Healthcheck reparieren

**Typ:** Operations-Hygiene
**Ziel:** `docker compose ps` meldet `web` als `healthy` auf beiden Servern. Grundlage für spätere automatische Monitoring-Alerts.
**Branch:** `fix/sprint2-web-healthcheck` (von `main`)
**Geschätzte Dauer:** ca. 45 Min

---

## Feature-Brief (Phase 1)

### Ausgangslage
- `web`-Container zeigt `(unhealthy)` auf Test und Main, obwohl die Anwendung sichtbar funktioniert.
- Aktueller Healthcheck im Dockerfile (`wget --spider http://localhost:3000/`) prüft die SSR-Root-Page, nicht einen dedizierten Endpoint.
- Kein `/api/health` vorhanden — `frontend/src/app/api/` existiert nicht.
- `wget --spider` ist kein robuster Health-Probe-Mechanismus (HEAD vs. GET, Spider-Semantik).

### Ziel
Leichtgewichtiger, stabiler Healthcheck-Endpoint + Dockerfile-HEALTHCHECK, der keine externen Binaries verlangt und unabhängig von Backend-Verfügbarkeit funktioniert (Web-Container prüft sich selbst, nicht die API).

### Akzeptanzkriterien
- [ ] Neue Next.js-Route `src/app/api/health/route.ts` liefert auf GET ein JSON `{ok:true, service:"web", ts:<iso>}` mit HTTP 200
- [ ] Route ist edge-kompatibel, ohne DB- oder API-Zugriff
- [ ] Dockerfile-HEALTHCHECK nutzt `node -e`-Einzeiler (nicht wget), prüft `/api/health`
- [ ] `docker compose ps` auf Test zeigt `web` als `(healthy)` nach Deploy
- [ ] `docker compose ps` auf Main zeigt `web` als `(healthy)` nach Deploy
- [ ] Playwright-Smoke-Test für `/api/health` (Statuscode 200, JSON-Schema)
- [ ] CI grün, PR durch Branch-Protection gemergt

### Abgrenzung — NICHT Teil von Sprint 2
- Kein zusätzlicher Backend-Healthcheck (API hat bereits Check, ist nicht betroffen)
- Keine Live-Metriken, kein Readiness vs. Liveness-Split (später im Monitoring-Sprint)
- Keine Healthcheck-Definition in `docker-compose.prod.yml` (Dockerfile ist die Single Source of Truth; compose-override nur falls nötig)

### Risiken
1. **`node -e` Inline-Script zu komplex für HEALTHCHECK-Zeile** → Test im Image mit `docker run --rm image sh -c '<cmd>'`. Bei Fehlschlag Alternative: kleines `healthcheck.js` in das Image kopieren und per `CMD ["node","healthcheck.js"]` aufrufen.
2. **Alpine-Base hat kein wget-Fallback nötig** → `node:20-alpine` hat bereits Node, also reicht `node -e`.
3. **Route liefert nicht bei Runtime-Startup** → Next.js-Standalone-Output startet in ~1-2 s; `start-period=30s` im HEALTHCHECK deckt das ab.

---

## Sprintplan (Phase 2)

### Sprint 2.1 — Feature-Brief & Plan
- Dieser Brief.
- Phase-1+2-Gate: User liest, gibt frei.

### Sprint 2.2 — `/api/health`-Route anlegen
- **Dateien:** neu `frontend/src/app/api/health/route.ts`
- **Vorgehen:**
  ```ts
  import { NextResponse } from 'next/server'
  export const dynamic = 'force-static'
  export const revalidate = false
  export async function GET() {
    return NextResponse.json({
      ok: true,
      service: 'web',
      ts: new Date().toISOString(),
    })
  }
  ```
- **Test lokal:** `cd frontend && npm run dev`, dann `curl http://localhost:3000/api/health` → JSON
- **Dauer:** 5 Min

### Sprint 2.3 — Dockerfile-HEALTHCHECK anpassen
- **Datei:** `frontend/Dockerfile`
- **Neu:**
  ```
  HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
      CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
  ```
- **Begründung:** Node 20 hat native `fetch`. Kein wget, kein curl, keine zusätzliche Dependency. 10 s schneller start-period, da Next.js-Standalone schnell startet.
- **Test lokal:** `docker build -t heizung-web:local frontend && docker run --rm -d --name hw heizung-web:local && sleep 20 && docker inspect --format='{{.State.Health.Status}}' hw`
- **Dauer:** 10 Min

### Sprint 2.4 — Playwright-Smoke für /api/health
- **Datei:** `frontend/tests/e2e/smoke.spec.ts` erweitern (oder neu `health.spec.ts`)
- **Vorgehen:**
  ```ts
  test('GET /api/health returns 200 JSON', async ({ request }) => {
    const res = await request.get('/api/health')
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toMatchObject({ ok: true, service: 'web' })
    expect(typeof body.ts).toBe('string')
  })
  ```
- **Test:** `npm run test:e2e` grün
- **Dauer:** 10 Min

### Sprint 2.5 — PR, CI, Deploy-Verifikation, Merge
- Feature-Branch pushen, PR gegen `main` öffnen
- CI grün abwarten (diesmal triggert der **echte** frontend-ci, da `frontend/**` geändert wird — nicht der Skip-Workflow)
- Nach Merge: 5-Min-Deploy-Timer wartet, dann auf beiden Servern prüfen:
  ```bash
  ssh root@100.82.226.57 "cd /opt/heizung-sonnblick/infra/deploy && docker compose ps"
  ssh root@100.82.254.20 "cd /opt/heizung-sonnblick/infra/deploy && docker compose ps"
  ```
  Erwartung: `web` bei beiden mit `healthy`.
- **Dauer:** 15 Min (Merge + Deploy-Wartezeit)

---

## Offene Fragen / Annahmen

- **[Annahme]** Node 20's natives `fetch` ist im Alpine-Image enthalten. Verifikation in 2.3 per lokalem Build.
- **[Annahme]** Die Route kann statisch gerendert werden (`force-static`) weil sie keine Request-Daten braucht. Das ist der schnellste Healthcheck. Wenn jemand einen dynamischen Timestamp bevorzugt, kann `dynamic = 'force-dynamic'` gesetzt werden — Performance-Unterschied vernachlässigbar.
- **[Annahme]** Die bestehende Smoke-Test-Datei heißt `smoke.spec.ts`. Falls anders, passen wir in 2.4 an.

---

## Phase-Gates

- **Gate 1+2 (jetzt):** User liest Feature-Brief + Sprintplan, gibt frei oder ändert.
- **Gate 4 (nach 2.4):** User reviewed PR vor Merge (wie Sprint 1.7).
- **Gate 5 (nach 2.5):** User prüft `docker compose ps` auf beiden Servern.
