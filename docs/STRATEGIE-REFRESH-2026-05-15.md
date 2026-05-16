# Strategie-Refresh 2026-05-15

**Status:** Verbindlich ab 2026-05-15
**Vorgänger:** `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` (bleibt als
Architektur-Master gültig, nur §7 Sprint-Plan-Adaption ist überholt)
**Gilt für:** Alle Arbeiten ab Sprint 10
**Auslöser:** Strategie-Chat-Entscheidung 2026-05-15 nach erfolgreichem
Auth-Cutover auf heizung-test (Tag `v0.1.14-auth`)

## 1. Anlass

Nach vier Wochen Bauphase (April-Mai 2026) sind Engine + Hardware +
Auth + Stammdaten + UI komplett. Auth-Cutover auf heizung-test ist
am 2026-05-15 erfolgreich abgeschlossen (`AUTH_ENABLED=true` seit
10:18 UTC stabil). Hotelier-Statement nach Cutover-Verifikation:

> „System extrem stabil laufen bevor weitere Features dazu kommen.
> Casablanca im Extremfall umgehbar, weil Belegung auch manuell
> pflegbar."

Konsequenz: Strategie-Re-Priorisierung. Stabilisierung schlägt
Feature-Tempo (analog CLAUDE.md §0 S1-S6). Fünf Monate bis
Heizperiode-Start lassen Raum für saubere Phasen-Logik mit Puffer.

## 2. Was sich ändert

Architektur-Refresh 2026-05-07 hatte die Feature-Reihenfolge
9.18 Dashboard → 9.19 Analytics → 9.20 API-Keys → 9.21 Gateway-UI →
10 Hygiene → 11 PMS → 12 Backup → 13 Wetter → 14 Go-Live vorgesehen.

**Neue Reihenfolge:** Phase 1 Stabilisierung → Phase 2
Live-Beobachtung → Phase 3 Frostschutz → Phase 4
heizung-main-Migration → Phase 5 PMS-Casablanca → Phase 6 Go-Live →
Phase 7 Features.

Die alten Feature-Sprints 9.18 bis 9.21 sind nicht gestrichen,
sondern in Phase 7 (nach Go-Live) verschoben. Reihenfolge in
Phase 7 nach realem Hotelier-Bedarf, nicht nach Plan-Erinnerungen.

## 3. Phasen-Definition mit Abschluss-Kriterien

### Phase 1 — Stabilisierung + Zuordnungs-Architektur (Mai-Juli 2026)

Phase 1 konkretisiert sich in Sprint 10 + 10a/b/c (CI-Hygiene und
Hardware-Diagnose) und in Sprint 11-14 + 14b (Brainstorming-
Inhalte aus Strategie-Chat 2026-05-15 plus arc42-Doku-
Konsolidierung). Details siehe `docs/SPRINT-PLAN.md`.

**Abschluss-Kriterium:**
- pytest auf grün ohne psycopg2-Ignores
- mypy-Fehler in `tests/` unter 20
- alle vier Vickis entweder produktiv eingebucht ODER formal
  dokumentiert als „nicht-pairing-fähig" mit Hardware-Begründung
- AE-51..AE-54 implementiert (Aggregat-Lesen + Schreiben,
  Fenster belegungs-abhängig, Health-State-Modell, Engine-Zone-
  Isolation)
- Doku-Skelett auf arc42 (12 Kapitel) gemappt; Source-of-Truth-
  Hierarchie ergibt sich strukturell aus arc42
- Backlog konsolidiert (Duplikate aufgelöst)

### Phase 2 — Live-Beobachtung heizung-test (parallel zu Phase 1)

Kein eigener Sprint. Hotelier klickt produktiv durch, meldet
Befunde. Strategie-Chat triagiert. Sprint-Aufwand minimal — nur
Befund-Sprints falls scharfe Mängel.

**Abschluss-Kriterium:** Zwei Wochen ohne neue 🔴/🟠-Befunde im
Strategie-Chat-Log.

### Phase 3 — Frostschutz-Reaktivierung (zurückgestellt)

AE-42 bleibt im zurückgestellten Zustand (siehe STATUS §2aa,
STRATEGIE-THERMOSTAT-ZUORDNUNG.md §10: Frostschutz 10 °C bleibt
als Code-Konstante unangetastet). Keine eigene Sprint-Zuordnung
vor Heizperiode. Reaktivierungs-Pfad in Phase 7, falls aus der
Heizperiode 2026/27 konkreter Bedarf entsteht.

### Phase 4 — heizung-main-Migration (Sprint 15, Anfang August 2026)

Vorgezogen gegenüber Strategie-Refresh-Initialstand: heizung-main
wird Anfang August „leer" vom Sprint-9.8a-Stand auf aktuellen
develop-Stand gebracht, BEVOR im September Vickis pre-paired
werden (Phase 4b). Migrationen 0005-0014+ anwenden,
`safe.directory`-Fix (CLAUDE.md §5.7), Auth-Cutover-Sprint analog
9.17a/b, Backup-Cron plus Off-Site-Replikation, Migrations-
Trockenlauf. Vier bisherige Vickis bleiben in Phase 4 zunächst
auf heizung-test; Hardware-Umzug beginnt erst in Phase 4b und
Phase 6.

**Abschluss-Kriterium:**
- heizung-main läuft funktional identisch zu heizung-test
  (zunächst leer bzgl. Live-Devices)
- `AUTH_ENABLED=true`, Doku in arc42-Form (aus Sprint 14b),
  alle Sprint-14-Resultate (UI / Health-Badges) ausgerollt
- Backup-Cron läuft, ein Disaster-Recovery-Drill bestanden

### Phase 4b — Pre-Pairing September (Sprint 17, September 2026)

Sub-Phase von Phase 4. Massen-Pairing-Vorbereitung aller ~100
Vickis auf einem Tisch im Hotel-Office, ohne Montage. Pro Vicki
Eingangstest (Setpoint hoch → Ventil hörbar auf, Setpoint runter
→ Ventil hörbar zu). Mass-Pairing-CSV-Import bzw. Batch-Wizard
(B-11prep-2) erforderlich. Pilot-Zimmer-Auswahl finalisiert
(B-11prep-4). Schulung Hotelier abgeschlossen.

**Abschluss-Kriterium:**
- ~100 Vickis auf heizung-main eingebucht, Eingangstest pro Gerät
  bestanden
- Pilot-Zimmer-Auswahl steht (5 Zimmer maximaler Vielfalt)
- Hotelier kennt Rückbau-Pfad (5 Min pro Zimmer; Betterspace
  bleibt jederzeit als Fallback verfügbar)

### Phase 5 — PMS-Casablanca-Integration (Sprint 16a bedingt)

**Voraussetzung:** Casablanca-FIAS-Antwort (B-11prep-1) liegt
vor. Hotelier-Antwort steht aus (Stand 2026-05-15).

Falls vor Sprint-17-Start verfügbar: Anbindung mit Polling oder
Event-Stream je nach FIAS-Fähigkeit als **Sprint 16a** (additiv
zwischen Sprint 16 Test→Main-Sync und Sprint 17 Pre-Pairing).
Mapping PMS-Status → Heizlogik in Engine-Layer 1, Fallback bei
PMS-Ausfall letzter bekannter Stand mit Zeitstempel, Audit-Trail
über `business_audit`.

Falls FIAS-Antwort ausbleibt: Sprint 16a entfällt, PMS rutscht in
Phase 7, manuelle Belegungs-Pflege bleibt Fallback (§4).

**Abschluss-Kriterium (falls aktiviert):**
- PMS-getriebene Check-in/Check-out-Updates kommen automatisch
- Engine reagiert mit Vorheizen vor Anreise und Setback nach
  Abreise
- Fallback-Pfad bei PMS-Ausfall funktioniert (Stop-Smoke-Test)

### Phase 6 — Pilot-Go-Live (Oktober Woche 1, zeit-definiert)

Kein einzelner Sprint. 5 Pilot-Zimmer werden umgerüstet
(Betterspace-Thermostate ab, Vickis dran), Auswahl maximaler
Vielfalt (Standard / Suite / Mehrfach-Vicki / Funk-Rand /
häufiger Gästewechsel). Schrittweiser Rückbau ab Oktober Woche 1
abhängig von Lerngeschwindigkeit. Vollausbau erst nach
Heizperiode-Verlauf.

**Tag:** `v1.0.0-pilot` nach Inbetriebnahme der ersten 5 Pilot-
Zimmer. Tag `v1.0.0` (Vollausbau) erst nach abgeschlossener
Migration (Frühjahr 2027).

**Abschluss-Kriterium:**
- 5 Pilot-Zimmer produktiv auf Vicki, Betterspace dort entfernt
- Rest des Hotels weiter auf Betterspace als Fallback
- Strategie-Chat in Beobachtungs-Modus

### Phase 7 — Features + Vollausbau (Sprint 18+, Winter 2026 und danach)

Reihenfolge nach realem Hotelier-Bedarf, nicht nach Plan-
Erinnerungen. Kandidaten siehe `docs/SPRINT-PLAN.md` Phase-7-
Sektion: AE-42-Reaktivierung (falls Bedarf), Drift-Erkennung
statistisch, Backend-Plausi für Fenster (BR-16), schrittweiser
Rückbau bis Frühjahr 2027 mit anschließender Betterspace-
Kündigung (siehe STRATEGIE-THERMOSTAT-ZUORDNUNG.md §15).

## 4. Casablanca-Strategie

**Entscheidung:** PMS-Integration vor Go-Live, **nicht** danach.

**Fallback:** Hotelier kann manuelle Belegungs-Pflege als Fallback
nutzen, falls Casablanca-Anbindung scheitert oder sich verzögert.
Manuelle Pflege bedeutet geschätzt 10-15 Min pro Tag Aufwand für
Rezeption — nicht Geschäftsmodell, aber lebbar.

**Konsequenz:** PMS ist kein Go-Live-Blocker mehr, sondern
Go-Live-Verbesserer. Falls FIAS-Antwort bis Sprint-12-Ende nicht
da ist: Go-Live mit manueller Pflege, PMS rutscht in Phase 7
(post Go-Live).

## 5. Heizperiode-Termin und Migrations-Plan

**1. Oktober 2026**, Hotel Sonnblick Kaprun. Davor müssen
heizung-main produktiv laufen (Phase 4) und alle Vickis
pre-paired sein (Phase 4b), sonst kein schrittweiser Rückbau
zur Heizperiode möglich.

Zeit-Plan 2026-05-15 → 2026-10-01: ~4,5 Monate.

- **Mai-Juli:** Phase 1 (Stabilisierung + Zuordnungs-Architektur
  + arc42-Konsolidierung), Phase 2 parallel
- **Anfang August:** Phase 4 (heizung-main-Migration, „leer")
- **August:** Phase 5 (PMS) — falls FIAS-Antwort, sonst Fallback
  manueller Betrieb
- **September:** Phase 4b (Pre-Pairing aller ~100 Vickis auf
  einem Tisch, ohne Montage)
- **Oktober Woche 1:** Phase 6 (Pilot-Go-Live mit 5 Pilot-Zimmern)
- **Oktober-Frühjahr 2027:** schrittweiser Rückbau, dann Phase 7

Mit zwei Wochen Puffer pro Phase ist der Plan stabil.

### Migrations-Plan kompakt (Vicki-Rollout)

Aus STRATEGIE-THERMOSTAT-ZUORDNUNG.md §15 verkürzt.
Hauptaktion und Hotel-Steuerung pro Zeitfenster:

| Zeitraum | Hauptaktion | Hotel-Steuerung |
|---|---|---|
| Mai-Juli | Stabilisierung + Zuordnungs-Architektur + arc42 auf heizung-test (Phase 1) | Betterspace |
| August | heizung-main-Migration leer (Phase 4, Sprint 15 + 16); optional PMS Sprint 16a (Phase 5) | Betterspace |
| September | Pre-Pairing aller ~100 Vickis ohne Montage (Phase 4b) | Betterspace |
| Oktober Woche 1 | 5 Pilot-Zimmer umgerüstet, Pilot-Go-Live (Phase 6), Tag `v1.0.0-pilot` | 5 Vicki + Rest Betterspace |
| Oktober-Frühjahr 2027 | Schrittweiser Rückbau pro Zimmer (Phase 7); danach Betterspace-Kündigung, Tag `v1.0.0` | gemischt → nur Vicki |

Details (Rückbau-Pfad ~5 Min pro Zimmer, Fallback-Strategie,
Pre-Pairing-Workflow): STRATEGIE-THERMOSTAT-ZUORDNUNG.md §15.

## 6. Sprint-Renumerierung

Sprint-Nummern entsprechen Zeit-Reihenfolge. Mapping nach
Strategie-Chat 2026-05-15, damit alte Doku-Verweise auflösbar
bleiben:

| alte Nummer | alter Inhalt | neue Nummer | neuer Inhalt |
|---|---|---|---|
| 9.18 | Dashboard KPI-Cards | 18+ | Phase 7 Features (nach Go-Live) |
| 9.19 | Temperaturverlauf-Analytics | 18+ | Phase 7 Features |
| 9.20 | API-Keys + Webhooks | 18+ | Phase 7 Features |
| 9.21 | Gateway-Status-UI | 18+ | Phase 7 Features |
| 10 (alt) | Hygiene-Sprint | 10 | Phase 1 CI-Hygiene |
| 11 (alt) | PMS-Casablanca | 16a (bedingt) | Phase 5 PMS-Casablanca, nur bei FIAS-Antwort |
| 12 (alt) | Backup + Production-Migration | 15 | Phase 4 heizung-main-Migration (umfassender, „leer") |
| 13 (alt) | Wetterdaten | 18+ | Phase 7 Features |
| 14 (alt) | Final-Tag v1.0.0 + Go-Live | — | Phase 6 zeit-definiert (Oktober Woche 1), Tag `v1.0.0-pilot`; voller `v1.0.0` erst Frühjahr 2027 |
| ehem. Phase 3 | Frostschutz-Reaktivierung Sprint 11 | — | zurückgestellt, AE-42; Reaktivierungs-Pfad in Phase 7 |
| (neu) | — | 10a, 10b, 10c | Phase 1 Sub-Sprints (Vicki-Diagnose, Vicki-Fix, Polish) |
| (neu) | — | 11-Prep | Phase 1: Doku-Konsolidierung Zuordnungs-Architektur (dieser Sprint) |
| (neu) | — | 11 | Phase 1: Health-State + Plausi + Zone-Isolation + Aggregat-Lesen (AE-51 Lese-Teil, AE-53, AE-54) |
| (neu) | — | 12 | Phase 1: Mehrfach-Vicki Schreiben (symmetrisch) + Fenster belegungs-abhängig (AE-51 Schreib-Teil, AE-52) |
| (neu) | — | 13 | Phase 1: Pairing-Wizard inkl. ChirpStack-Stufe + Vicki-Eingangstest + Mass-Pairing-CSV |
| (neu) | — | 14 | Phase 1: Cross-Sicht-UI + Health-Badges + Mail-Platzhalter |
| (neu) | — | 14b | Phase 1: arc42-Konsolidierung der Architektur-Doku |
| (neu) | — | 16 | Phase 4: Test→Main-Sync + Last-Test + Bug-Fixing |
| (neu) | — | 16a | Phase 5 (bedingt): PMS-Casablanca-Integration falls FIAS-Antwort vorliegt |
| (neu) | — | 17 | Phase 4b: Pre-Pairing September (Mass-Pairing aller Vickis ohne Montage) |

## 7. Was unberührt bleibt

- **CLAUDE.md §0 Stabilitätsregeln S1-S6:** verbindlich, keine
  Änderung.
- **CLAUDE.md §0.1 Autonomie-Default Stufe 2:** verbindlich.
- **AE-1 bis AE-54:** alle Architektur-Entscheidungen gelten
  unverändert. AE-42 (Frostschutz pro Raumtyp) bleibt
  zurückgestellt; Reaktivierungs-Pfad in Phase 7 falls Bedarf
  aus Heizperiode 2026/27 entsteht (siehe Phase 3).
- **Engine-Pipeline 6-Layer:** strukturell unverändert. Phase 1
  ergänzt nicht-strukturelle Erweiterungen: Layer-4-Signatur um
  `occupancy_state` (AE-52), Pro-Zone-Isolation via try/except in
  `evaluate_all_zones()` (AE-54). Keine neuen Layer, keine
  Pipeline-Refactors.
- **Datenbank-Schema:** Phase 1 fügt zwei Health-State-Spalten
  hinzu (`device.health_state`, `heating_zone.health_state` aus
  AE-53) und ggf. Aggregat-Hilfsfelder für Mehrfach-Vicki-Zonen
  (AE-51). Darüber hinaus keine Schema-Änderungen bis Phase 4
  (heizung-main-Migration). `min_temp_celsius` in `room_type`
  existiert bereits, bleibt ungenutzt bis Phase 7.
- **WORKFLOW.md 5-Phasen-Feature-Flow:** verbindlich für jeden
  Sprint.

## 8. Querverweise

- **Vorgänger:** `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` — bleibt
  Architektur-Master, §7 Sprint-Plan-Adaption ist überholt.
- **Operative Konkretisierung:** `docs/SPRINT-PLAN.md` — neu
  strukturiert nach Phasen-Logik.
- **Auth-Cutover-Wendepunkt:** `STATUS.md` §2af, §2ag, §2ah, §2ai.
- **Stabilitätsregeln:** `CLAUDE.md` §0.
- **Source-of-Truth-Hierarchie:** `CLAUDE.md` §0.2 (dieses
  Dokument an Position 1 einsortiert).
