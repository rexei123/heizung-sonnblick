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

Ab 01.11.2026 zusätzlich das Merge-Fenster: werktags 10-12 Uhr, Doku-PRs
gebündelt (CLAUDE.md §0.3, RUNBOOK §10v). Jeder Merge startet den Stack neu.
Hotfix ist die Ausnahme — dann hier den Grund nennen.
-->

**Handbuch:** angepasst / nicht nötig, weil …
<!--
Pflichtzeile seit Paket 1 (CLAUDE.md §3.13). Das Handbuch liegt als Markdown
in `frontend/content/handbuch` und wandert durch denselben PR wie die
Änderung, die es beschreibt — ein Handbuch, das man getrennt pflegen muss,
ist nach drei Sprints falsch.

- **angepasst** — der PR ändert Verhalten oder Oberfläche, und der betroffene
  Artikel samt `stand`-Datum ist mit drin.
- **nicht nötig, weil …** — mit Grund. „Reiner Umbau ohne sichtbare
  Änderung" ist ein Grund, „habe ich vergessen" nicht.

Was CI prüft, ist nur die Vollständigkeit der Zuordnung
(`backend/tests/test_handbuch_spiegel.py`: jede Seite der Seitenleiste hat
einen Artikel, jeder Artikel ein Datum). Ob der Text noch stimmt, prüft diese
Zeile — und nur sie.
-->

---

## Was und warum
