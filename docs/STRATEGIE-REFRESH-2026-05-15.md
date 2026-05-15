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

### Phase 1 — Stabilisierung (Mai-Juni 2026)

**Sprint 10:** CI-Hygiene + Test-Coverage.
**Sprint 10a:** Hardware-Diagnose Vicki-Pairing + Batterie.
**Sprint 10b:** Vicki-Code-Fixes, falls Diagnose es verlangt.
**Sprint 10c:** Frontend-Polish-Reste.

**Abschluss-Kriterium:**
- pytest auf grün ohne psycopg2-Ignores
- mypy-Fehler in `tests/` unter 20
- alle vier Vickis entweder produktiv eingebucht ODER formal
  dokumentiert als „nicht-pairing-fähig" mit Hardware-Begründung
- Backlog konsolidiert (Duplikate aufgelöst)

### Phase 2 — Live-Beobachtung heizung-test (Juni-Juli 2026)

Kein eigener Sprint. Hotelier klickt produktiv durch, meldet
Befunde. Strategie-Chat triagiert. Sprint-Aufwand minimal — nur
Befund-Sprints falls scharfe Mängel.

**Abschluss-Kriterium:** Zwei Wochen ohne neue 🔴/🟠-Befunde im
Strategie-Chat-Log.

### Phase 3 — Frostschutz-Reaktivierung (Sprint 11, Juli 2026)

AE-42 aus dem zurückgestellten Zustand (siehe STATUS §2aa)
aktivieren. R8 pro Raumtyp konfigurierbar machen. Engine Layer 5
nutzt `min_temp_celsius` aus `room_type` statt globaler Konstante.

**Abschluss-Kriterium:**
- Frostschutz greift bei Sensor-Werten unter `min_temp_celsius`
  des Raumtyps
- Engine-Trace dokumentiert sauber (LayerStep mit reason
  `frostschutz_active`)
- Vicki-Setpoint-Untergrenze 10 °C wird respektiert
- Live-Test vor Heizperiode-Beginn auf heizung-test bestanden

### Phase 4 — heizung-main-Migration (Sprint 12, Juli-August 2026)

B-9.11x-2 abräumen. heizung-main vom Sprint-9.8a-Stand auf
aktuellen develop-Stand bringen. Migrationen 0005-0014 anwenden.
`safe.directory`-Fix (CLAUDE.md §5.7). Auth-Cutover-Sprint analog
9.17a/b. Backup-Cron + Off-Site-Replikation. Vier Vickis physisch
auf heizung-main montiert.

**Abschluss-Kriterium:**
- heizung-main läuft funktional identisch zu heizung-test
- `AUTH_ENABLED=true` und alle Vickis online
- Backup-Cron läuft, ein Disaster-Recovery-Drill bestanden

### Phase 5 — PMS-Casablanca-Integration (Sprint 13, August 2026)

**Voraussetzung:** Casablanca-FIAS-Antwort liegt vor (erwartet
Mai 2026 — Hotelier-Statement 2026-05-15).

Anbindung mit Polling oder Event-Stream je nach FIAS-Fähigkeit.
Mapping PMS-Status → Heizlogik in Engine-Layer 1 (Setpoint-
Schicht). Fallback bei PMS-Ausfall: letzter bekannter Stand mit
Zeitstempel. Audit-Trail über `business_audit`. Manuelle
Belegungs-Pflege bleibt als Fallback funktionsfähig.

**Abschluss-Kriterium:**
- PMS-getriebene Check-in/Check-out-Updates kommen automatisch im
  System an
- Engine reagiert mit Vorheizen vor Anreise und Setback nach
  Abreise
- Fallback-Pfad bei PMS-Ausfall funktioniert (Stop-Smoke-Test)

### Phase 6 — Go-Live (Sprint 14, September 2026)

**Tag:** `v1.0.0`. Hotelier nimmt produktiv in Betrieb. Strategie-
Chat wechselt in Beobachtungs-Modus.

**Abschluss-Kriterium:** Heizperiode-Start in Hotel Sonnblick
erfolgt mit produktiv laufender Heizungssteuerung.

### Phase 7 — Features (Sprint 15+, Winter 2026 und danach)

Reihenfolge nach realem Hotelier-Bedarf, nicht nach Plan-
Erinnerungen. Kandidaten siehe `docs/SPRINT-PLAN.md` Phase-7-
Sektion.

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

## 5. Heizperiode-Termin

**1. Oktober 2026**, Hotel Sonnblick Kaprun. Davor muss
heizung-main produktiv laufen, sonst keine Heizungssteuerung
in der Heizperiode.

Zeit-Puffer-Rechnung 2026-05-15 → 2026-10-01: ~4,5 Monate.
- Mai bis Juni: Phase 1 (Stabilisierung)
- Juni bis Juli: Phase 2 (Live-Beobachtung)
- Juli: Phase 3 (Frostschutz)
- Juli bis August: Phase 4 (heizung-main-Migration)
- August: Phase 5 (PMS) — oder Fallback manueller Betrieb
- September: Phase 6 (Go-Live)

Mit zwei Wochen Puffer pro Phase ist der Plan stabil.

## 6. Sprint-Renumerierung

Variante 2: Sprint-Nummern entsprechen Zeit-Reihenfolge. Damit
alte Doku-Verweise auflösbar bleiben, hier das Mapping:

| alte Nummer | alter Inhalt | neue Nummer | neuer Inhalt |
|---|---|---|---|
| 9.18 | Dashboard KPI-Cards | 15+ | Phase 7 Features (nicht renumeriert, kommt nach Go-Live) |
| 9.19 | Temperaturverlauf-Analytics | 15+ | Phase 7 Features |
| 9.20 | API-Keys + Webhooks | 15+ | Phase 7 Features |
| 9.21 | Gateway-Status-UI | 15+ | Phase 7 Features |
| 10 (alt) | Hygiene-Sprint | 10 | Phase 1 CI-Hygiene |
| 11 (alt) | PMS-Casablanca | 13 | Phase 5 PMS-Casablanca |
| 12 (alt) | Backup + Production-Migration | 12 | Phase 4 heizung-main-Migration (jetzt umfassender) |
| 13 (alt) | Wetterdaten | 15+ | Phase 7 Features |
| 14 (alt) | Final-Tag v1.0.0 + Go-Live | 14 | Phase 6 Go-Live |
| (neu) | — | 11 | Phase 3 Frostschutz-Reaktivierung |
| (neu) | — | 10a, 10b, 10c | Phase 1 Sub-Sprints (Vicki-Diagnose, Vicki-Fix, Polish) |

## 7. Was unberührt bleibt

- **CLAUDE.md §0 Stabilitätsregeln S1-S6:** verbindlich, keine
  Änderung.
- **CLAUDE.md §0.1 Autonomie-Default Stufe 2:** verbindlich.
- **AE-1 bis AE-50:** alle Architektur-Entscheidungen gelten
  unverändert. AE-42 (Frostschutz pro Raumtyp) wird in Phase 3
  aus dem zurückgestellten Zustand aktiviert.
- **Engine-Pipeline 6-Layer:** keine Refactors.
- **Datenbank-Schema:** keine Änderungen bis Phase 3 (Frostschutz
  braucht eventuell `min_temp_celsius`-Aktivierung pro Raumtyp;
  Spalte existiert bereits).
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
