## Zimmerliste: „Temperatur" und „Details" mit schwarzer Schrift (2026-11-03)

**Keine Migration.** Eine Klassen-Konstante, zwei Aufrufe, vier
Playwright-Tests. Kein Backend.

### Die Vorgabe

Betreiber, 31.10.2026: **„Schrift schwarz"**. Schrift **und Symbol** der
beiden Zeilen-Knöpfe tragen das Text-Token des Design-Systems
(`--color-text-primary`, `#14171c`), **nicht** die Primärfarbe. Beim
Überfahren wird der Hintergrund hell rosé wie bisher, gesperrt bleibt
grau.

| Zustand | vorher | jetzt |
|---|---|---|
| Ruhe | `text-primary` (Brand-Rosé `#dd3c71`) | **`text-text-primary`** (`#14171c`) |
| Überfahren | Hintergrund `primary-soft` **und Schrift rot** (`hover:text-error`) | Hintergrund `primary-soft`, **Schrift bleibt schwarz** |
| Gesperrt | `disabled:opacity-50` auf Rosé → blasses Rosé | `disabled:opacity-50` auf Schwarz → **wirklich grau** |

**Die dritte Zeile ist ein Nebeneffekt, und zwar der gewünschte.** Die
Vorgabe lautete „grau wie bisher"; gesperrt war bisher aber kein Grau,
sondern blasses Rosé — die halbe Deckkraft lag auf der Primärfarbe. Mit
schwarzer Schrift wird daraus Grau, ohne dass an der Sperre etwas
geändert wurde.

### Eine Auslegung, die der Betreiber umdrehen kann

Die Vorgabe nennt für das Überfahren **nur den Hintergrund**. Das
frühere `hover:text-error` färbte zusätzlich die **Schrift** rot — und
damit genau in dem Moment, in dem man hinsieht, wieder nicht schwarz. Ich
habe es deshalb entfernt. **Wenn die Schrift beim Überfahren rot werden
soll, ist das eine Zeile zurück** (`hover:text-error` in
`ZEILEN_KNOPF_KLASSEN`) plus eine Zeile im Test.

### Warum eine Konstante und nicht zweimal derselbe String

Die beiden Knöpfe stehen nebeneinander in derselben Zeile und müssen
gleich aussehen. Zwei Fassungen desselben Klassen-Strings laufen beim
nächsten Griff auseinander, und ein Knopf, der um eine Nuance anders
aussieht als sein Nachbar, fällt niemandem auf (§5.53).

### Eine Abweichung vom Design-System, und sie ist markiert

`ghost` heißt im Design-System „Transparent + Primary-Text" (§6.1). Die
Zimmerliste hebt den zweiten Teil auf. Damit niemand den Aufruf dort für
einen Fehler hält und ihn „zurückfixt", steht der Hinweis an **beiden**
Enden: im Kopfkommentar von `components/ui/button.tsx` bei `ghost`, und
ausführlich an `ZEILEN_KNOPF_KLASSEN`. Ein Kommentar nur am Aufruf hätte
die Stelle nicht erreicht, an der jemand nachsieht, was `ghost` tut.

### Tests, und warum nicht auf die Klasse geprüft wird

Vier Playwright-Tests in `zimmerliste-knopffarbe.spec.ts`. Geprüft wird
die **gerechnete Farbe**, nicht der Klassen-Name:

| Test | prüft |
|---|---|
| beide Knöpfe | `color` == Text-Token, und Text-Token != Primärfarbe |
| das Symbol | das Material-Symbol erbt dieselbe Farbe |
| Überfahren | Hintergrund == `primary-soft` **und** Schrift weiter schwarz |
| Gesperrt | `disabled`, `opacity` 0.5, Farbe weiter Text-Token |

**Eine Klassen-Prüfung hätte hier nichts geprüft.** `text-text-primary`
muss sich gegen das `text-primary` der Variante durchsetzen, und das tut
`tailwind-merge` in `cn()`. Ob die Klasse **dasteht**, sagt nichts
darüber, ob sie **greift** — und genau diese Auflösung ist das Fragile an
der Lösung.

**Die Sollwerte liest der Test aus `globals.css`**
(`--color-text-primary`, `--color-primary`, `--color-primary-soft`), statt
Hex-Werte zu tragen. Eine Zahl im Test wäre eine zweite Wahrheit und beim
ersten Nachjustieren am Token falsch — dieselbe Überlegung wie Goldene
Regel 13 für Zahlen im Handbuch. Der erste Test prüft zusätzlich, dass
Text-Token und Primärfarbe sich überhaupt unterscheiden; wären sie
gleich, bestünde er, ohne etwas auszusagen.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| `text-text-primary` entfernt (zurück auf `ghost`) | **alle vier** |
| `hover:text-error` wieder dazu | der Überfahren-Test |
| `hover:bg-transparent` (Hintergrund weg) | der Überfahren-Test |
| `disabled={!knopf.erlaubt}` entfernt | der Gesperrt-Test |

Die erste ist die wichtigste: sie ist der Rückfall auf den Stand von
vorher und bringt die ganze Datei zu Fall, nicht ein Detail.

### Nicht geändert, und das ist eine Frage an den Betreiber

Auf der **Zimmerseite** (`zimmer/[id]`) gibt es zwei kleine Textlinks mit
`text-text-secondary hover:text-error` — dieselbe Familie, andere Stelle,
nicht die beiden Knöpfe der Liste. Der Auftrag nannte die Zimmerliste;
diese zwei stehen unverändert. Ob die Regel „Schrift schwarz" auch dort
gelten soll, entscheidet der Betreiber.

**Querverweise:** `frontend/src/app/zimmer/page.tsx`
(`ZEILEN_KNOPF_KLASSEN`), `frontend/src/components/ui/button.tsx`
(`ghost`), `frontend/tests/e2e/zimmerliste-knopffarbe.spec.ts`,
`docs/status/2026-11-02-boost.md` (der Knopf „Temperatur" selbst).
