## Zimmerseite: die Geräte-Aktionen mit schwarzer Schrift (2026-11-03)

**Keine Migration.** Eine Klassen-Konstante, drei Aufrufe, vier
Playwright-Tests. Nachtrag zu
`docs/status/2026-11-03-knopffarbe-zimmerliste.md`.

### Es waren drei, nicht zwei — und mein Bericht war daran schuld

Gemeldet hatte ich **zwei** Textlinks auf der Zimmerseite. Es sind
**drei**: „Tauschen", „Stilllegen" und „Trennen" stehen nebeneinander in
derselben Zeile am Gerät, mit demselben Klassen-Rumpf, und unterschieden
sich nur in **einer** Eigenschaft — der Farbe beim Überfahren.

| Aktion | vorher in Ruhe | vorher beim Überfahren |
|---|---|---|
| Tauschen | `text-text-secondary` | **`hover:text-primary`** — die Primärfarbe |
| Stilllegen | `text-text-secondary` | `hover:text-error` |
| Trennen | `text-text-secondary` | `hover:text-error` |

**Die fehlende war die schlimmste.** „Tauschen" wurde beim Überfahren
**zur Primärfarbe** — genau der Fall, den die Vorgabe ausschließt. Ich
habe sie nicht gefunden, weil ich nach `hover:text-error` gesucht hatte,
also nach dem Symptom der beiden anderen, statt nach der Familie. Ein
`grep` nach dem, was man schon gesehen hat, findet nichts Neues; §5.79
gilt auch für die eigene Suche von vor zehn Minuten.

### Was jetzt gilt

| Zustand | jetzt |
|---|---|
| Ruhe | `text-text-primary` (`#14171c`), alle drei gleich |
| Überfahren | **Farbe bleibt stehen**, dazu `hover:underline` |
| `transition-colors` | entfallen — es wechselt keine Farbe mehr |

**Der Hinweis „anklickbar" liegt jetzt auf der Unterstreichung.** Anders
als bei den Pillen in der Zimmerliste geht hier kein Hintergrund: die
drei sind randloser Text ohne Innenabstand, eine Fläche dahinter wäre
ein Kasten um zwei Wörter. `hover:underline` ist die Form, die das Repo
für textförmige Bedienelemente schon an 13 Stellen benutzt — unter
anderem an „Detail →" in derselben Zeile.

**Eine Beobachtung zum Gewicht.** Die Zurücknahme dieser drei Aktionen
kam bisher aus **zwei** Quellen: der kleinen Schrift (`text-xs`) **und**
dem Grau. Mit dem Text-Token trägt sie nur noch die Schriftgröße; die
drei stehen also etwas kräftiger da als vorher. Das ist die Vorgabe
(„ebenfalls schwarz") und kein Nebenbefund — hier genannt, weil es im
Haus auffallen wird und nicht an einem Fehler liegt.

### Was absichtlich nicht schwarz ist

**Die Links.** „Detail →" in derselben Zeile und „Zur Zimmerliste" am
Kopf der Seite stehen in der Link-Darstellung der ganzen Anwendung
(`text-primary hover:underline`, 13 Stellen). Sie hier allein umzufärben
macht die Zimmerseite zur Ausnahme; sie überall umzufärben ist eine
Entscheidung über das Design-System und nicht über diese Zeile.
**Entscheidung liegt beim Betreiber.**

Die Reiter der Seite (`hover:text-text-primary`) gehen beim Überfahren
ohnehin auf das Text-Token und bleiben, wie sie sind.

### Tests

Vier in `zimmerseite-knopffarbe.spec.ts`, und zwei Entscheidungen darin
sind das Eigentliche:

**Jede der drei wird einzeln geprüft**, nicht eine stellvertretend. Jede
hatte vorher ihre eigene Hover-Farbe; ein Test, der nur „Tauschen"
prüft, besteht auch dann, wenn zwei weiter umfärben. Genau das war der
Zustand, der zu diesem Nachtrag geführt hat.

**Der erste Test prüft, dass Text-Token, Primärfarbe und Rot drei
verschiedene Werte sind.** Wären zwei davon gleich, bestünde er, ohne
etwas auszusagen.

Dazu: die Unterstreichung ist **in Ruhe abwesend** und erscheint erst
beim Überfahren — fällt sie weg, ist der Knopf von gewöhnlichem Text
nicht zu unterscheiden. Und die Symbole erben die Farbe, für alle drei.

Die Sollwerte liest der Test zur Laufzeit aus `globals.css`. Der Helfer
dafür steht auch in `zimmerliste-knopffarbe.spec.ts`; bei einem dritten
Verbraucher gehört er nach `fixtures.ts` — zwei Kopien eines Test-Helfers
sind tragbar, weil jede Kopie ihre eigene Seite prüft und ein
Auseinanderlaufen keine Prüfung verliert.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| Konstante zurück auf den alten String | **alle vier** |
| `hover:text-error` wieder dazu | der Überfahren-Test |
| `hover:underline` entfernt | der Unterstreichungs-Test |
| **eine der drei vergessen** (nur „Stilllegen" auf alt) | **drei von vier** |

Die letzte ist die, für die diese Datei existiert: sie ist genau der
Fehler, der mir im Bericht passiert ist, und die Schleife über alle drei
fängt ihn.

### Lokal

360 e2e passed (frischer Port 3167, §5.55), `tsc --noEmit`, `next lint`
ohne Befund. Jede Mutationsprobe mit eigenem Build auf eigenem Port.

**Querverweise:** `docs/status/2026-11-03-knopffarbe-zimmerliste.md` (der
PR davor, #376), `frontend/src/app/zimmer/[id]/page.tsx`
(`GERAETE_AKTION_KLASSEN`), `frontend/src/app/zimmer/page.tsx`
(`ZEILEN_KNOPF_KLASSEN`), §5.79 (ein Audit gilt für den Stand, den es
gesehen hat — hier für die eigene Suche).
