# Sprint 9.10b — Stabilitätsregeln + Autonomie-Default verankern

**Datum:** 2026-05-07
**Branch:** `chore/sprint9.10b-stability-rules`
**PR:** TBD
**Tag:** keiner — Governance-Sprint, kein Feature.

## Ziel
Stabilität als oberste Systemregel und Autonomie-Default für Claude Code formal im Repo festschreiben. Reine Markdown-Doku, kein Code, keine Tests. Autonomie-Stufe 3.

## Anlass
Sprint 9.10 (Window-Detection) legte eine seit Sprint 9.6 latent dokumentierte, aber nie implementierte Race-Condition-Mitigation (`celery_app.py:60-61`) durch den Reading-Trigger aktiv frei. Folge-Diskussion: Stabilitätsprinzipien dürfen nicht implizit auf Sprint-Ebene ausgehandelt werden; Sprint-Reviews dürfen sich nicht in Yes-Klicks auf Routine verlieren.

## Tasks

| Task | Beschreibung | Status |
|---|---|---|
| T1 | CLAUDE.md §0 — Stabilitätsregeln S1-S6 + Eskalations-Regel + Nicht-Ziele | erledigt |
| T2 | CLAUDE.md §0.1 — Autonomie-Default Stufe 2 (Pflicht-Stops 1-9, Auto-Continue, Berichts-Format, Sprint-Stufen 1/2/3) | erledigt |
| T3 | CLAUDE.md §2 — Pflicht-Lektüre um Punkt 0 erweitert | erledigt |
| T4 | ADR AE-41 in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` (konsistent zu AE-40) | erledigt |
| T5 | README.md — Abschnitt „Stabilitätsregeln" als Verweis (Single Source of Truth bleibt CLAUDE.md §0) | erledigt |
| T6 | STATUS.md §2q + dieser Sprint-Brief | erledigt |

## Designentscheidungen

- **Single Source of Truth:** CLAUDE.md §0 ist verbindlich. README enthält nur Verweis. Kein Doppel-Abdruck → kein Drift-Risiko zwischen zwei Quellen.
- **§-Nummerierung:** §0 + §0.1 bewusst als Vor-Block. Bestehende §1-§7 bleiben unverändert, alle externen Verweise (PRs, Skripte, frühere Sprints) bleiben gültig.
- **Pflicht-Lektüre Punkt 0** statt 1-Verschiebung — selber Grund: Stabilität externer Verweise.
- **Autonomie-Stufen 1/2/3 statt Pro-Task-Flag:** Aufmerksamkeits-Fokus auf Sprint-Granularität, nicht Einzel-Edit. Stufe 2 als Default bedeutet weniger Yes-Klicks bei Routine, mehr Sorgfalt bei substantiellen Entscheidungen.
- **AE-41 als Architektur-ADR:** Stabilität ist eine Querschnitts-Architektur-Entscheidung, nicht eine Feature-Konvention. Daher in der ADR-Reihe, nicht nur im SPEC-FRAMEWORK.

## Verwandte ADRs / Lessons

- **AE-41** (dieser Sprint) — formaler ADR-Eintrag.
- **AE-40** (Sprint 9.10) — Engine-Task-Lock; Anlass-Fall für S1.
- **CLAUDE.md §5.20** — Aspirative Code-Kommentare als Doku-Drift; konkreter Vorgang, der die Race-Condition aus AE-40 freigelegt hat.

## Pre-Push

Reine Doku — `git diff --stat` zeigt nur `*.md`-Files. Kein ruff/mypy/pytest-Lauf, kein Frontend-Build.

## Nicht in Scope

- Anpassung des SPEC-FRAMEWORK an die neuen Regeln (eigener Sprint, falls nötig).
- Tooling/Hook-Automation für S1-S6-Verstoß-Detektion (Backlog).
- Nachträgliche Stabilitäts-Audits älterer Sprints (Backlog).
