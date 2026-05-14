# Live-Verifikation Sprint 9.13c + Wording-Fix — BEFUND

Test-Datum: 2026-05-12
Zielsystem: https://heizung-test.hoteltec.at
Deploy-Verifikation: PR #140 ca. 8 Min vor Test gemerged,
Pull-Timer-Wartezeit 2 Min, Marker Spalten-Header-Wechsel auf
`/devices`
Tester: Cowork

## Pflicht-Prüfungen (5/5 bestanden)

1. `/devices`-Liste: Spalten „Eingerichtet" (`check_circle` + ja/nein)
   und „Status" (Hardware-Badge) ersetzen 9.13c-Initial-Stand sauber.
2. `/devices/2` Detail: Label „Status" mit detailed-Badge oben rechts,
   „Eingerichtet: ja" darunter — Reihenfolge wie spezifiziert.
3. `/zimmer/1` Geräte-Tab: Compact-Badge auf Vicki-001 ohne Subtext,
   keine Eingerichtet-Anzeige in dieser Stelle (Scope-konform).
4. Konsole: 0 App-Errors. 40× Chrome-Extension-Spam (nicht-fatal),
   3× Recharts-Width-Warning (bekannt, B-pre-9.13c-1).
5. Vicki-002-Edge-Case visuell präzise: „Status: Inaktiv, noch nie"
   + „Eingerichtet: ja", während KPI-Cards und 24h-Chart aktive
   Werte zeigen (145 Readings). Genau der Use-Case „Backplate ab,
   andere Uplinks laufen weiter".

## Folge-Beobachtungen (Backlog, keine Blocker)

- `cancel`-Icon für „Eingerichtet: nein" mangels Test-Daten nicht
  visuell demonstrierbar (Schema implementiert).
- Wording-Audit auf Pairing-Wizard und anderen Pages noch offen.
- Recharts-Width-Warning bleibt (bestehendes Backlog).

## Empfehlung

Sprint 9.13c live-verifiziert, kann geschlossen werden.
