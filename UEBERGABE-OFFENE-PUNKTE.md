# Uebergabe — offene technische Punkte

Stand: 2026-05-05, Sprint 9.8 abgeschlossen.

Dieses Dokument listet Punkte aus Teil 1.3 der Uebergabe-Direktive, die
**nicht lokal abschliessbar** waren. Sie blockieren den Live-Betrieb
NICHT — die Produktivumgebung laeuft sauber, weil der Linux-Build im
CI durchlaeuft.

---

## 1. Frontend `npm run build` schlaegt auf Windows fehl

**Datei:** `frontend/src/app/icon.tsx` (Next.js `app/icon`-Konvention,
Sprint 7 N-12 fuer Favicon)

**Fehler bei `npm run build` auf Windows 10/11 lokal:**

```
✓ Compiled successfully
✓ Linting and checking validity of types
✓ Collecting page data
Error occurred prerendering page "/icon".
TypeError: Invalid URL
    at new URL (node:internal/url:819:25)
    at fileURLToPath (node:internal/url:1604:12)
    at file:///C:/Users/User/dev/heizung-sonnblick/frontend/node_modules/next/dist/compiled/@vercel/og/index.node.js:18988:32
> Export encountered errors on following paths:
        /icon/route: /icon
EXITCODE: 1
```

**Was ueberprueft wurde:**

- Code in `icon.tsx` ist syntaktisch + typisch korrekt. Keine eigenen
  URL-Konstruktoren, nur `next/og`-Standard-Pattern.
- Linux-Build im CI (`build-images.yml` Job "Build Web Image") laeuft
  seit Sprint 7 zuverlaessig durch und produziert ein funktionierendes
  Image (siehe alle GHCR-Tags `develop` + alle gemergten Frontend-PRs).
- `@vercel/og` ist Bundle-Bestandteil von Next.js 14.2.15 selbst.

**Vermutete Ursache:** Windows-spezifischer Pfad-Parsing-Bug in
`@vercel/og` beim File-URL-Lookup waehrend Static-Prerendering. Linux
CI traegt das nicht.

**Wirkung:** Lokaler Windows-Build ist nicht moeglich. Production
nicht betroffen. Frontend-Entwicklung lokal nur via `npm run dev`
moeglich.

**Vorschlaege fuer spaetere Loesung (KEINE eigenmaechtige Aenderung):**

1. `app/icon.tsx` durch statisches `/public/icon.png`-Asset ersetzen
   (entfernt die `@vercel/og`-Abhaengigkeit komplett).
2. Generation-Mode auf `force-dynamic` setzen (verhindert
   Prerendering, Icon wird zur Laufzeit gerendert).
3. Next.js-Update auf 15.x oder Patch-Release abwarten.

---

## 2. Frontend-Lint hat 2 Warnings (KEINE Errors)

**Datei:** `frontend/src/app/layout.tsx:41`

```
Warning: Block is not recommended. See: https://nextjs.org/docs/messages/google-font-display
Warning: Custom fonts not added in `pages/_document.js` will only load for a single page.
```

**Wirkung:** Cosmetic, kein Funktionsfehler. Build-Pipeline akzeptiert
Warnings.

**Loesung spaeter:** Custom-Font-Setup gemaess Next.js-13-App-Router-
Konvention via `next/font/google` (steht teilweise schon — vermutlich
falsch importiert).

---

## 3. `frontend/tests/e2e/sprint8.spec.ts` bricht 2 von 12 Cases im CI

**Datei:** `frontend/tests/e2e/sprint8.spec.ts` (Sprint-8.13-Smoke,
seit Sprint 8.13 untracked auf Disk, NIE im Repo, NIE in CI gelaufen)

**Bricht bei `npm run test:e2e` im CI:**

- `/belegungen rendert Liste mit Range-Filter` wartet auf Button
  `Naechste 7 Tage`, der erst nach `GET /v1/occupancies` rendert.
  CI hat keinen `api`-Container -> `EAI_AGAIN api`.
- `/einstellungen/hotel rendert 3 Cards` wartet auf Heading
  `Allgemein`, das erst nach `GET /v1/global-config` rendert.
  Gleiches Problem.

10 von 12 Cases sind gruen (statische Routen ohne Daten-Dependency).

**Wirkung:** Beim Versuch, die Datei mit dem Uebergabe-Commit
einzuchecken, bricht die Frontend-CI -> Branch-Protection blockt
Merge. Datei wurde deshalb aus dem Uebergabe-Commit AUSGENOMMEN
und liegt weiter untracked im lokalen Repo-Tree.

**Vorschlaege fuer spaetere Loesung (KEINE eigenmaechtige Aenderung):**

1. Tests umbauen, dass sie auf API-Loading-State warten (z.B.
   `getByRole(...).waitFor({ state: 'visible', timeout: 30000 })`)
   oder API via Playwright `route.fulfill` mocken.
2. Im e2e-CI-Job einen api+db-Container ueber docker-compose
   hochfahren (ChirpStack/Mosquitto nicht noetig).
3. Tests komplett mit `test.describe.skip` markieren, bis das
   Lokal-Dev-Setup inkl. Backend dokumentiert ist.

---

## 3. Backend-Tests in lokaler Sandbox nicht ausfuehrbar

**Wirkung:** Test-Status verifiziert ueber den letzten CI-Run von PR
#81 (`9.8b` quantize-half-up), der **alle Tests gruen** durchlaufen
hat (siehe GitHub Actions Run 25358881847+).

**Grund:** Sandbox-Umgebung hat:
- Python 3.10 statt 3.12 (`from datetime import UTC` schlaegt fehl)
- Keine `ENVIRONMENT`/`DATABASE_URL`/`SECRET_KEY`-Vars gesetzt
- Kein `asyncpg`-fertiges PostgreSQL erreichbar

**Verifikation moeglich via:**

```bash
# SSH (heizung-test, root)
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml \
  exec api python -m pytest tests/ --tb=short
```
