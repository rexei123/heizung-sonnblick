# `docker exec -it` verschluckt Folgezeilen genauso, aber nicht überall zu Unrecht

**Stand:** 04.11.2026

Nachtrag zu Befund 3 der Rotation vom 04.11.
(`2026-11-04-rotation-teil2.md`). Dort ging es um `docker compose`, das
eingefügte Folgezeilen aus derselben Einfügung verschluckt. `docker exec
-it` hat dieselbe Eigenschaft aus derselben Ursache — `-t` belegt ein
Terminal, `-i` hängt stdin an den Container — und im RUNBOOK standen vier
solche Aufrufe.

## Die vier Stellen haben zwei verschiedene Antworten

| Stelle | Befehl | Antwort |
|---|---|---|
| 803 | `psql … -c "SELECT …"` | `-it` **weg** — der Befehl ist nicht interaktiv |
| 943 | `python -c "…"` | `-it` **weg** |
| 947 | `python -c "…"` | `-it` **weg** |
| 978 | `redis-cli` **ohne Argument** | `-it` **bleibt** |

Bei den ersten drei war das Flag schlicht überflüssig: ein `-c`-Aufruf
liest nichts von stdin und braucht kein Terminal. Es stand da, weil
`docker exec -it` die Form ist, die man sich merkt — und hat als
Nebenwirkung die nächste eingefügte Zeile gefressen.

**978 ist der interessante Fall.** `redis-cli` ohne Argument **ist** eine
Sitzung; die `>`-Zeilen darunter werden darin getippt. Hier das Flag zu
entfernen würde den Handgriff zerstören. Die richtige Antwort ist deshalb
nicht „Flag weg", sondern ein Vermerk daneben: dieser Aufruf ist
absichtlich interaktiv und gehört an das **Ende** einer Einfügung.

**Das ist der Grund, warum eine Suche-und-Ersetze-Runde hier falsch
gewesen wäre.** Drei von vier Treffern sind Versehen, einer ist Absicht,
und die Unterscheidung steht nicht im Flag, sondern im Befehl dahinter.

## Was unangetastet bleibt

Die vier Aufrufe mit **`-i` allein** (1445, 2803, 2812, 7683) speisen
einen Heredoc. Dort ist `-i` nicht nur erlaubt, sondern notwendig, und
der Heredoc begrenzt sich selbst durch seinen Schlussmarker — er kann
nicht mehr verschlucken, als zu ihm gehört.

## Was das nicht ist

Kein Beweis, dass es im RUNBOOK keine weitere Stelle dieser Art gibt.
Geprüft ist genau das Muster `docker exec -` über die ganze Datei; ein
Aufruf, der stdin auf anderem Weg belegt — ein Werkzeug, das selbst
nachfragt, etwa — fällt durch diese Suche. §5.79: die Prüfung gilt für
das Muster, das sie gesucht hat.
