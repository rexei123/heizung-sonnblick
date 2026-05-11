# Session-Start — Pflicht-Pre-Read für jede KI-Session

**Status:** Verbindlich ab 2026-05-07
**Gültig für:** Strategie-Chat (Claude.ai), Claude Code, Cowork
**Bezug:** ARCHITEKTUR-REFRESH-2026-05-07.md

## Trigger-Phrase

Bei jedem neuen Chat / jeder neuen Task / jedem neuen Auftrag sagt der
User als ersten Satz:

> **„Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."**

Die KI antwortet mit:

1. Welche Dokumente sie gelesen hat (Liste)
2. Welche Rolle sie einnimmt (Strategie / Code / Cowork)
3. Welcher Sprint aktuell ist (aus STATUS.md §2 jüngster Eintrag)
4. Welche Backlog-Punkte aktuell offen sind (Top 3 nach Priorität)
5. Bestätigt, dass historische Sprint-Briefe in `docs/features/` mit
   Datum vor 2026-05-07 nicht für neue Pläne herangezogen werden

Wenn die Antwort unvollständig ist: User antwortet **„Stop, lies nochmal
SESSION-START.md."**

## Pflicht-Lese-Liste pro Rolle

### Strategie-Chat (Claude.ai-Web/App, plant + reviewt)

In dieser Reihenfolge lesen:

0. **Projekt-Anweisung im Strategie-Chat-Frontend** (steht im
   Projekt-Frontend von claude.ai, NICHT im Repo) — definiert Rolle,
   Stil, Domänen-Wissen, Stabilitäts-Verhalten, Format für Antworten.
   Wird beim Chat-Start automatisch geladen, MUSS aber bewusst gelesen
   und befolgt werden, nicht überflogen.
1. `docs/SESSION-START.md` (dieses Dokument)
2. `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` (Master)
3. `docs/SPRINT-PLAN.md` (aktueller + nächster Sprint)
4. `STATUS.md` §1 (Aktueller Stand) + §2 letzter Eintrag
5. `CLAUDE.md` §0 (Stabilitätsregeln) + §0.1 (Autonomie-Default)
6. **Kritische Hardware-Befunde** (siehe Sektion unten in diesem Dokument)
7. `docs/AI-ROLES.md` (eigene Rolle)

**Was die Strategie-Chat-Rolle tut:**
- Sprint-Briefe schreiben
- Tasks in Claude-Code-Aufträge zerlegen
- Architektur-Entscheidungen mitentwickeln
- Reviews + Befunde auswerten
- Dokumentation aktualisieren

**Was sie NICHT tut:**
- Code schreiben (außer Snippets <20 Zeilen für Diskussion)
- Direkt deployen
- Eigenmächtig Sprint-Plan ändern

### Claude Code (CLI im Repo, programmiert)

In dieser Reihenfolge lesen:

1. `docs/SESSION-START.md`
2. **Kritische Hardware-Befunde** (siehe Sektion unten in diesem Dokument)
3. `CLAUDE.md` (komplett — alle Lessons §5.x)
4. `docs/SPRINT-PLAN.md` (nur den aktuellen Sprint-Eintrag)
5. `STATUS.md` §1
6. Ggf. `RUNBOOK.md` für SSH/Deploy-Kontext
7. Den vom Strategie-Chat gelieferten Brief (im User-Prompt)

**Was Claude Code tut:**
- Code schreiben nach Brief 1:1
- Tests schreiben + ausführen
- Lokal builden, ruff + mypy + pytest grün halten
- Branches anlegen, committen, pushen
- PRs erstellen, mergen nach Freigabe
- Tags vergeben nach Freigabe

**Was Claude Code NICHT tut:**
- Eigenmächtig vom Brief abweichen
- Architektur ändern ohne Strategie-Chat-Freigabe
- SSH auf heizung-test (User macht das, Claude Code formuliert nur die
  Befehle)
- Sprint-Plan oder STATUS.md überschreiben außer im definierten Sprint-Doku-Task

### Cowork (Browser-Agent, testet visuell)

In dieser Reihenfolge lesen:

1. `docs/SESSION-START.md` (dieses Dokument)
2. Den vom User gelieferten Test-Brief (im Auftrag selbst)
3. `Design-Strategie-2_0_1.docx` (UI-Konventionen, falls relevant)

**Was Cowork tut:**
- Visuelles Klicken nach Auftrag
- Screenshots, JSON-Dokumentation
- Smoke-Tests von neuen UI-Strecken
- Inventarisierung externer Systeme

**Was Cowork NICHT tut:**
- Daten ändern (Speichern, Senden, Anwenden, Löschen, Reset)
- Eigenmächtige Vergleiche oder Bewertungen
- Sprint-Plan oder Architektur-Vorschläge

## Kritische Hardware-Befunde (Pflicht-Wissen vor jeder Code-Session)

Diese Befunde MÜSSEN bewusst vor jeder Sprint-Planung oder Code-Aktion
gelesen werden, weil sie Architektur-Annahmen aus früheren Sprints
korrigieren. Drift im Inhalt zwischen den verlinkten Stellen ist ein
S1-Befund (CLAUDE.md §0). Diese Sektion enthält **nur Verweise**, keine
Inhalte — die Wahrheit steht in den verlinkten Dokumenten.

### Vicki-Thermostat-Verhalten

- **CLAUDE.md §5.27** — Open-Window-Detection im Default disabled,
  Algorithmus-Trägheit, Sommer-Test-Strategie
- **AE-45 in `ARCHITEKTUR-ENTSCHEIDUNGEN.md`** — Auto-Detect-Override
  bei Hand-Drehung am Vicki
- **AE-47 in `ARCHITEKTUR-ENTSCHEIDUNGEN.md`** — Hardware-First-Window-
  Detection mit drei Trigger-Quellen
- **`docs/vendor/mclimate-vicki/README.md`** — Hersteller-Doku-Stand
  2026-05-09 mit FW-Tabelle und Command-Cheat-Sheet

### Pflege dieser Sektion

Wenn ein Sprint einen neuen Hardware-Realitäts-Befund aufdeckt
(Discrepancy zwischen Annahme und Verhalten): neue Lesson §5.x in
CLAUDE.md anlegen UND hier verlinken. Inhalt nicht doppelt pflegen.

## Source-of-Truth-Hierarchie

Bei Konflikt zwischen Dokumenten gilt diese Reihenfolge (oben schlägt
unten):

1. `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
2. `docs/SPRINT-PLAN.md`
3. `STATUS.md` (für laufenden Stand)
4. `CLAUDE.md` (für Stabilitätsregeln + Lessons)
5. `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
6. `docs/STRATEGIE.md`
7. `docs/RUNBOOK.md`
8. `docs/WORKFLOW.md`
9. `Design-Strategie-2_0_1.docx`

Alles in `docs/features/` mit Datum vor 2026-05-07 ist **historisch** —
gilt nicht mehr für Pläne, gilt für Lessons, falls dort enthalten.

## Was als „nicht mehr gültig" markiert ist

Folgende Inhalte gelten ab 2026-05-07 als überholt:

- ~~**STRATEGIE.md §6.2 R8 (alte Fassung)**: „Frostschutz absolut, nicht
  konfigurierbar". → Gilt jetzt: zweistufig (siehe AE-42)~~
  **Update 2026-05-11:** Diese Markierung ist hinfällig. Der Schwenk auf
  zweistufigen Frostschutz wurde zurückgenommen. R8 gilt wieder als
  globale Konstante; AE-42 wurde auf „zurückgestellt" gesetzt. Eintrag
  bleibt als Historie stehen.
- **STRATEGIE.md §9.3 (7-Phasen-Modell)**: → Gilt jetzt: 5 Phasen aus
  WORKFLOW.md
- **Alle Sprint-Briefe in `docs/features/` mit Datum vor 2026-05-07**:
  → Gilt jetzt: SPRINT-PLAN.md
- **STATUS.md §6 (alter Backlog)**: → Gilt jetzt: STATUS.md §6 nach
  Refresh-Update mit BR-1 bis BR-15

## Wenn die KI alte Logik wiedergibt

Symptom: Eine KI sagt „nächster Sprint ist 9.11 mit allen Layern auf
einmal" oder „Sommer braucht volle 6-Layer-Pipeline".

Reaktion User: **„Stop. Lies ARCHITEKTUR-REFRESH-2026-05-07.md §2.1
[oder §3 / §7] und korrigiere."**

Das passiert in den ersten 2-3 Wochen häufig, weil ältere Embeddings
durchschlagen. Konsequente Korrektur durch Dokument-Verweis ist die
wirksamste Mitigation.

> **Historische Notiz 2026-05-11:** Bis 2026-05-11 stand hier zusätzlich
> das Beispiel „laut Strategie ist Frostschutz nicht konfigurierbar".
> Nach Rücknahme des Frostschutz-Schwenks (AE-42 zurückgestellt, R8 wieder
> globale Konstante) ist diese Aussage wieder korrekt — Beispiel entfernt,
> um falsche Korrektur-Reflexe zu vermeiden.

## Pflicht-Bestätigung am Ende

Nach Lesen der Pflicht-Liste antwortet die KI im Klartext:

```
SESSION-START bestätigt — 2026-05-07
Rolle: <Strategie / Code / Cowork>
Gelesen: <Dokumentenliste>
Aktueller Sprint laut STATUS.md §2: <Sprint-Nummer + Ziel>
Top-3-Backlog: <BR-x, BR-y, BR-z>
Kritische Hardware-Befunde gelesen: §5.27 (Vicki-Window-Default),
  AE-45 (Auto-Override), AE-47 (Window-Hybrid), docs/vendor/mclimate-vicki/
Historische Sprint-Briefe vor 2026-05-07: nicht für Pläne, nur Lessons
Bereit für Auftrag.
```

Erst nach dieser Bestätigung beginnt die eigentliche Arbeit.
