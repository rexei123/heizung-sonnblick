# Status-Einträge, ab 02.11.2026 eine Datei je Eintrag

Jeder PR, der einen Status-Eintrag braucht, legt hier **eine neue Datei**
an statt an `STATUS.md` anzuhängen:

```
docs/status/YYYY-MM-DD-<slug>.md
```

Zwei Einträge am selben Tag unterscheiden sich im Slug, nicht in einer
Nummer. Die Datei beginnt mit einer `##`-Überschrift in derselben Form
wie bisher — Thema, Datum, und in der ersten Zeile, ob eine Migration
dabei ist.

## Warum

`STATUS.md` hat 8300 Zeilen, und jeder PR hat am **Dateiende** angehängt.
Drei PRs hintereinander (#361) sind dort kollidiert, obwohl sie
inhaltlich nichts miteinander zu tun hatten: git sieht nur zwei
Änderungen an derselben letzten Zeile. Eine neue Datei je Eintrag kann
nicht kollidieren, weil zwei Branches nie dieselbe Datei anlegen.

Beim dritten Mal ist dabei fast ein Eintrag verloren gegangen:
`git checkout --theirs -- STATUS.md` nimmt die **ganze** Datei der
anderen Seite, nicht den strittigen Abschnitt. Der Eintrag §2cs war weg
und wurde nur bemerkt, weil die Abschnitte nachgezählt wurden. Das ist
der eigentliche Grund für diese Umstellung — nicht die Minuten für das
Auflösen, sondern dass die Auflösung selbst Inhalt verlieren kann.

## Was *nicht* umgestellt wird

- **Der Altbestand bleibt.** Die Abschnitte §2a bis §2cv stehen weiter in
  `STATUS.md`. Querverweise auf „§2cu" bleiben gültig; sie werden nicht
  umgeschrieben.
- **Es gibt keinen Index.** Ein Verzeichnis, das jeder PR ergänzen muss,
  wäre dieselbe Kollision an einer anderen Stelle. Wer sucht, nimmt
  `ls docs/status/` oder `grep -r`.
- **Die Kopfzeile von `STATUS.md` bleibt dort und darf kollidieren.** Sie
  ist der Stand, nicht ein Eintrag — §5.26 verlangt, dass der PR, der
  etwas abschließt, sie im selben PR nachzieht, und das soll so bleiben.
  Zwei PRs, die beide die Kopfzeile anfassen, müssen das von Hand klären;
  anders als beim Dateiende ist das auch richtig so, weil dann wirklich
  zwei Aussagen über denselben Stand im Streit sind.

## Verweise aus anderen Dokumenten

Auf einen neuen Eintrag wird mit dem Dateinamen verwiesen
(`docs/status/2026-11-02-waechter-backoff.md`), nicht mit einer
Abschnittsnummer. Die Nummern waren ohnehin nur in `STATUS.md` eindeutig
und mussten beim Anhängen fortgezählt werden — noch eine Stelle, an der
zwei parallele PRs dieselbe Zahl gewählt hätten.
