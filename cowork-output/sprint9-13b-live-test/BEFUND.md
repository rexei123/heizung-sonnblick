# Live-Test Sprint 9.13 Bündel B — BEFUND

Test-Datum: 2026-05-12
Zielsystem: https://heizung-test.hoteltec.at
Build-SHA: 47701f5 (visuell verifiziert über neue Sidebar mit 14 Einträgen
in 5 Gruppen; `/api/v1/_meta`-Endpoint noch im Backlog B-9.13a-hf2-1)
Tester: Cowork

## Schritte

### 1. Desktop-Sidebar

Status: ✅ Erfolg

Sidebar mit 14 Einträgen in 5 Gruppen-Headern (UEBERSICHT, STEUERUNG,
GERAETE, ANALYSE, EINSTELLUNGEN) sichtbar nach Hard-Reload zur
Cache-Umgehung. Material Symbols geladen, Rose-Highlight am aktiven
Eintrag.

### 2. Stub-Pages

Status: ✅ Erfolg (3/3)

- `/profile` — EmptyState mit Title „Profile", Symbol, Badge „Sprint 9.15"
- `/einstellungen/saison` — EmptyState mit Title „Saison", Symbol
  `wb_sunny`, Badge „Sprint 9.16"
- `/einstellungen/gateway` — EmptyState mit Title „Gateway", Symbol
  `router`, Badge „Sprint 9.21"

Active-Route-Highlight greift exakt auf den angeklickten Eintrag, keine
Prefix-Vererbung auf Hotel/Benutzer/API.

### 3. Bestehende Pages

Status: ✅ Erfolg, keine Regression

- `/raumtypen` lädt normal
- `/devices`: Pairing-CTA-Button vorhanden, Inline-Label-Edit
  funktioniert (Bündel A)
- `/zimmer` zeigt 45 Zimmer
- `/zimmer/1` hat 5 Tabs, funktional

### 4. Mobile-Sheet

Status: ✅ Erfolg

Viewport 375×812. Hamburger-Button sichtbar oben links. Klick öffnet
Sheet von links mit voller NavList. Sheet schließt automatisch nach
Navigation auf `/zimmer`. A11y-Fix (`sr-only` Title + Description aus
PR #137-Nachzug) wirksam: KEINE Radix-DialogTitle-Warnings mehr in
DevTools-Konsole.

### 5. Konsole-Errors

Status: ✅ Erfolg

Keine App-spezifischen Errors. 11× Chrome-Extension-Spam („listener
indicated an asynchronous response"), per Brief explizit als nicht-fatal
eingestuft.

## Zusätzlicher UX-Befund

Hotelier sieht alte Sidebar bis Hard-Reload nach Deploys — Kandidat für
Cache-Busting-Sprint, nicht produktionskritisch. Backlog-Item:
B-9.13b-1.

## Empfehlung

Live-verifiziert, kein Hotfix nötig. Sprint 9.13 Bündel B kann als
geschlossen markiert werden.
