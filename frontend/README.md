# Frontend — Heizung Sonnblick

Next.js 14 (App Router) · TypeScript strict · Tailwind 3 · Design-Strategie 2.0.

## Lokale Entwicklung

```bash
npm install
npm run dev   # http://localhost:3000
```

## Build & Lint

```bash
npm run lint
npm run type-check
npm run build
```

## Wichtig

- Icons: **ausschließlich** Material Symbols Outlined (siehe AE-01 in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`).
- Schrift: Roboto via `next/font/google` — **nicht** als CDN-Link einbinden.
- Farben/Radien/Schatten: nur über CSS-Variablen aus `src/app/globals.css`. Keine Hard-Coded-Hex-Werte in Komponenten.
- shadcn/ui-Komponenten kommen in Sprint 2 nach `src/components/ui/`.
