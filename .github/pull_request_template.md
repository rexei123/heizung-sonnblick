<!--
Die beiden Pflichtzeilen unten stehen oben, weil sie beim Lesen eines alten
PRs gebraucht werden — nicht beim Schreiben. Alles andere ist Freitext.
-->

**Migration additiv:** ja / nein / keine Migration
<!--
Pflichtzeile seit Sprint 20g (AE-77 §8). Sie entscheidet, ob ein Rückfall
auf diesen Stand zulässig ist (RUNBOOK §10u, Schritt 0).

- **keine Migration** — der PR fasst `backend/alembic/versions/` nicht an.
- **ja** — nur hinzufügend: nullable Spalte oder neue Tabelle, ohne Backfill
  und ohne Beschränkung, die Bestandszeilen betrifft. Eine `CHECK`-Bedingung
  zu ERWEITERN ist additiv.
- **nein — bricht Rückfall** — `DROP COLUMN`, `RENAME`, nachträgliches
  `NOT NULL`, Enum-Wert entfernt, Typ verengt, `CHECK` verengt. Dann
  zusätzlich eine Zeile im Docstring der Migration: der PR-Text ist, was beim
  Suchen nach „seit wann" gelesen wird, der Docstring, was beim Lesen der
  Migration gelesen wird.

Warum das kein CI-Check ist: ein Linter müsste `op.drop_column` im
`downgrade` von einem im `upgrade` unterscheiden, und dort ist es normal und
richtig. Die Falsch-Positiven wären häufiger als die echten Fälle.
-->

**§0.3 geprüft:** läuft ein Montage- oder Eingangstest?
<!--
Ein Merge nach `develop` ist ein Deploy auf heizung-test (CLAUDE.md §0.3).
Die Deploy-Sperre fängt den Fall ab, wenn der Lauf über die CLI kam — sie hat
drei Lücken, deshalb bleibt die Frage Pflicht.
-->

---

## Was und warum
