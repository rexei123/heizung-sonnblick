## Boost-Abnahme §10ax bestanden — und eine falsche Uhrzeit dabei (2026-11-03)

**Keine Migration.** Kein Code. RUNBOOK §10ax, ein Handbuch-Artikel.

### Bestanden, 07:1x bis 07:30, durch den Betreiber

| Geprüft | Befund |
|---|---|
| freies Zimmer 52, Boost gesetzt | Soll **23** |
| Thermostat 002 | meldet `targetTemperature` **23** um **07:19** |
| Engine-Schicht | **„Boost (Mitarbeiter)" bis 20:00** |
| Beenden | zurück auf **15** |
| Übersteuerung gesperrt | Knopf **grau** |
| Bar (Allgemeinbereich) | Boost **grau mit Grund** |
| Rolle Mitarbeiter | wie vorgesehen |

**Der Teil, der zählt, ist die zweite Zeile.** Nicht die Oberfläche hat
23 angezeigt, sondern das **Thermostat hat 23 gemeldet** — der Weg vom
Klick über Engine, Downlink und Gerät bis zur Rückmeldung ist damit an
echter Hardware belegt und nicht nur an Mocks. Ebenso die Gegenprobe:
„Beenden" führt auf 15 zurück, also auf den Frei-Sollwert, und nicht auf
irgendeinen Zwischenwert.

### Die falsche Uhrzeit, und wie sie sich verraten hat

Der Betreiber hat **„bis 20:00"** beobachtet. §10ax behauptete in Schritt
1 „der **Nachtbeginn** des Zimmers (**im Haus 22:00**)", das Handbuch
zeigte „Boost bis 22:00" an drei Stellen.

**20:00 ist richtig, 22:00 war Drift.** Fünf unabhängige Stellen im Repo
nennen das Fenster 20:00–06:00:

| Stelle | Wortlaut |
|---|---|
| `seite-temperaturen-zeiten.md` | „20:00 bis 06:00 ist das Fenster im Haus" |
| `ablauf-zimmer-zu-kalt.md` | „Es ist nach 20:00" |
| RUNBOOK §10an | „konfiguriert ist (20:00/06:00)" |
| RUNBOOK (Absenkungs-Kriterium) | „Für das Kriterium gilt die Absenkung ab 20:00" |
| die Abnahme selbst | Boost endet 20:00 |

Die 22:00 standen in einem Text, der am 02.11. von mir geschrieben wurde
— **genau die Klasse, die Goldene Regel 13 verbietet**: eine Zahl im
Text, die eine Aussage über den heutigen Stand ist und beim ersten
Nachjustieren verfällt. Hier war sie nicht einmal je richtig.

**Was geändert ist:**

| Stelle | vorher | jetzt |
|---|---|---|
| §10ax Schritt 1 | „der Nachtbeginn des Zimmers (im Haus 22:00)" | der Nachtbeginn des Zimmers, **mit dem Weg dorthin** und ohne Zahl |
| `seite-zimmeruebersicht` Boost-Absatz | „Boost bis 22:00" | „Boost bis 20:00", dazu der Satz, dass die Uhrzeit mit dem Nachtfenster wandert |
| derselbe Artikel, „kein Mindestmaß" | „ein Boost um 21:55 endet um 22:00" | „fünf Minuten vor dem Nachtbeginn endet nach fünf Minuten" — **ohne Uhrzeit**, die Aussage braucht keine |
| derselbe Artikel, Marken-Tabelle | „Boost bis 22:00" | „Boost bis 20:00", als Beispiel gekennzeichnet |

**Im RUNBOOK ist die Zahl ganz weg, im Handbuch nicht.** Das ist Absicht
und nicht Inkonsequenz: das RUNBOOK wird unter Druck gelesen, dort ist
der **Weg zur Einstellung** die nützlichere Angabe. Das Handbuch zeigt
dem Betreiber, **wie der Knopf aussieht** — ohne eine Uhrzeit wäre das
Beispiel keines. Eine Marke `{{werte}}` gibt es nur als eigenen Block,
nicht inline (`lib/handbuch/markdown.ts`); für eine Uhrzeit mitten im
Satz existiert sie also nicht.

### Was nicht geändert ist

**`docs/status/2026-11-02-boost.md` behält seine 22:00.** Dort begründet
die Zahl eine Entscheidung vom Vortag („bei Nachtbeginn 22:00 wäre das
ein Boost von 23 Stunden"). Status-Einträge sind Geschichte, und
Geschichte wird nicht nachträglich richtiggestellt — die Begründung
bleibt mit jeder Uhrzeit gültig, weil sie von der Länge handelt und nicht
von der Zahl. Hier benannt, damit das Stehenlassen eine Entscheidung ist
und kein Vergessen.

### Der Befund, der einen eigenen PR bekommt

Der **Kopf der Engine-Seite** nannte bei laufendem Boost „Grund:
Frei-Sollwert · Sollwert aus: hausweit". Der Wert daneben (23 °C) war
richtig, die Begründung gehörte zu einer anderen Zeile: der Kopf liest
seinen Grund aus der **Basis-Schicht**, der Wert kommt aus der
**letzten** Schicht. Eigener PR, weil es Code ist und dies hier Doku.

**Querverweise:** RUNBOOK §10ax (die Anleitung, jetzt mit Ergebnis),
`docs/status/2026-11-02-boost.md` (der Boost selbst),
`docs/status/2026-11-02-boost-einstellen.md` (der einstellbare Wert),
`frontend/content/handbuch/seite-zimmeruebersicht.md`, Goldene Regel 13
(Zahlen gehören nicht in den Text), §5.77 (eine Aussage über den
heutigen Stand, die wie eine Eigenschaft gelesen wird).
