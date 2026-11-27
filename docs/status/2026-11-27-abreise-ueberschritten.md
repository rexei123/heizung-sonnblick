# Abreise überschritten — ein Hinweis, der von selbst verschwindet (27.11.2026)

## Der Fall stand schon im Handbuch, nur zu spät

Der Artikel „Abreise verschiebt sich" sagt es seit dem 25.10.2026:

> Ohne diesen Schritt setzt die Steuerung das Zimmer am ursprünglichen
> Abreisetag auf „frei" — der Gast kommt abends in ein kühles Zimmer
> zurück, obwohl niemand etwas falsch gemacht hat.

Der Artikel sagt, **was** zu tun ist. Er sagt nicht, **wann** — und genau
da fällt der Fall durch: wer das Datum vergisst, liest den Artikel nicht.
Der Hinweis steht deshalb dort, wo die Rezeption ohnehin hinsieht.

## Was er zeigt

Die Zimmer, deren **Abreise in den letzten 24 Stunden verstrichen** ist
und für die **keine** neue Belegung läuft. An einem normalen Tag sind das
die Abreisen des Vormittags — eine Handvoll; nach dem Mittag meist
nichts. Steht nichts da, erscheint der Hinweis gar nicht.

## Die Auslegung, und wo ich eine Annahme getroffen habe

Der Auftrag lautet: *Warnung „Abreise überschritten, noch belegt"
(Dashboard-Hinweis, kein Mail-Spam)*. „Noch belegt" lässt zwei Lesarten
zu, und sie führen zu verschiedenen Listen:

| Lesart | Liste | Problem |
|---|---|---|
| **A** — die Abreise ist vorbei, es steht keine neue Belegung | die Abreisen des Tages | zeigt auch Zimmer, die wirklich leer sind |
| **B** — zusätzlich gibt es ein Zeichen, dass noch jemand da ist | nur belegte Verdachtsfälle | verschweigt die stillen Fälle — und das sind die teuren |

**Gebaut ist A, mit dem Zeichen aus B als Zusatz je Zeile.** Begründung:
die Anlage kann „noch belegt" nicht wissen — das weiß nur die Rezeption.
Was sie hat, sind Spuren, und die meisten Gäste hinterlassen keine. Eine
Liste, die auf B verkürzt, wäre genau dann leer, wenn ein stiller Gast
abends im kühlen Zimmer sitzt (§5.55). Umgekehrt ist A ohne Zusatz eine
Liste, in der alles gleich aussieht.

**Falls der Betreiber B gemeint hat**, ist das ein Einzeiler: der Filter
steht am Ende von `lies_abreisen`, und die Mutationsprobe 5 setzt ihn
genau dort — sechs Tests gehen dabei rot, also ist die Entscheidung
belegt und nicht versteckt.

## Die zwei Spuren

| Zeichen | Woher | Was es heißt |
|---|---|---|
| **jemand hat am Thermostat gedreht** | `event_log`, Schicht `manual_override_blocked` | Nach der Abreise hat jemand im Zimmer verstellt, und das OCCUPIED-Tor (AE-58) hat die Verstellung verworfen. Der stärkste Hinweis, den die Anlage auf einen anwesenden Gast hat |
| **Wunschtemperatur gesetzt** | laufende `manual_override`, angelegt nach der Abreise | Die Rezeption weiß es schon — falsch steht die **Belegung** |
| *kein Zusatz* | — | Nichts beobachtet. **Nicht** „leer" |

Die `manual_override_blocked`-Zeilen gibt es seit Sprint 12a (§5.52). Sie
waren bis heute ein reiner Diagnosepfad — „verworfene Drehring-Aktionen",
wie die Lesson sie nennt. Sie zu lesen kostet eine Abfrage und ist die
einzige Stelle im System, an der ein **Mensch** in einem leer geführten
Zimmer sichtbar wird.

**Die Spur muss nach der Abreise liegen.** Ohne diesen Vergleich trüge
jedes Zimmer mit Drehrad-Historie ein Zeichen; ein Test hält es fest, und
Probe 4 nimmt den Vergleich weg.

**Das Drehrad schlägt die Übersteuerung**, wenn beides vorliegt: „jemand
hat gedreht" ist die Spur des Gastes, „Wunschtemperatur gesetzt" die der
Rezeption. Die erste stellt die Belegung in Frage, die zweite bestätigt
nur, dass jemand schon reagiert hat.

## Was er nicht tut

* **Keine Mail.** Vorgabe des Betreibers, und sie ist richtig: eine
  Abreise ist ein Alltagsereignis. Eine Mail je Abreise wäre nach drei
  Tagen ein Filter im Postfach — und dann ist auch der Alarm weg, der
  etwas bedeutet (§5.79).
* **Kein Eingriff in die Steuerung.** Das Zimmer bleibt auf dem
  Frei-Wert. Aus einer Vermutung weiterzuheizen heißt, leere Zimmer zu
  heizen (§0 S5).
* **Keine Änderung an der Belegung.** Das Datum zu verlängern hat Folgen
  für Abrechnung und nächste Anreise.
* **Nichts zum Wegklicken.** Der Hinweis verschwindet von selbst: eine
  verlängerte Belegung nimmt das Zimmer sofort heraus, eine Abreise
  verlässt das Fenster nach 24 Stunden. Ein Hinweis mit Schließknopf ist
  am dritten Tag geschlossen.

## Keine Kachel

Eine Kachel mit „3" wäre auf dieser Seite nicht handlungsfähig — die
Rezeption müsste danach 47 Belegungen durchsehen, um die drei zu finden.
Der Hinweis nennt die Zimmer und verlinkt beides: das Zimmer und die
Belegungsliste, in der es erledigt wird.

**Keine zweite Zahl daneben.** Sie wäre `len` der Liste und damit eine
zweite Wahrheit, die beim ersten Filter auseinanderläuft (§5.53).

## Das Fenster

24 Stunden, als Konstante im Dienst. Kürzer wäre ein Hinweis, der mittags
verschwindet, bevor der Gast abends im kühlen Zimmer steht; länger wäre
eine Liste, die mit den Tagen wächst und sich nicht abarbeiten lässt. Sie
steht **nicht** in den Settings, weil es keinen Fall gibt, in dem zwei
Häuser sie verschieden brauchen — kommt er, zieht sie um.

## Mutationsproben

Neun, jede einzeln gesetzt und zurückgenommen:

| # | Mutation | Rot |
|---|---|---|
| 1 | Fensterkante weg — alte Abreisen bleiben in der Liste | 1 |
| 2 | Laufende Belegung schließt das Zimmer nicht aus | 1 |
| 3 | `is_active` nicht geprüft — abgesagte Buchungen zählen | 1 |
| 4 | Spur ohne Zeitvergleich (auch von **vor** der Abreise) | 1 |
| 5 | Liste auf Zimmer **mit** Spur verkürzt (Lesart B) | **6** |
| 6 | Abgelaufene Übersteuerung zählt als Spur | 1 |
| 7 | Älteste statt jüngste Abreise je Zimmer | 1 |
| 8 | Sortierung weg — Zimmer mit Spur nicht oben | 1 (Playwright) |
| 9 | Hinweis erscheint auch ohne Fälle | 1 (Playwright) |

## Zahlen

* **2338 Tests** grün (vorher 2324), 60 übersprungen, 1 xfailed.
* **443 Playwright-Tests** grün (vorher 438).
* `ruff check`, `ruff format --check`, `mypy src`, `tsc --noEmit`,
  `eslint` ohne Befund.
* Keine Migration. Alle drei Quellen (`occupancy`, `event_log`,
  `manual_override`) bestehen.

## Ein Befund am Rande, nicht in diesem PR

`test_funkempfang.py::test_lies_funkempfang_zaehlt_nur_das_fenster` war
beim ersten Gesamtlauf **rot**, ohne dass dieser PR etwas Verwandtes
anfasst: erwartet 4 Meldungen im Zehn-Minuten-Fenster, gezählt 6. Die
Ursache sind zwei zurückgebliebene Geräte in der lokalen Test-Datenbank
(ohne Etikett, ohne Zone, angelegt während des Laufs) samt je einer
Messung — der Test fragt **hausweit** und filtert nicht auf seine eigenen
Geräte, was §5.39 für genau diese Art Test verlangt.

Nach dem Entfernen der beiden Zeilen ist er grün. **CI ist nicht
betroffen** (frische Datenbank je Lauf). Der Punkt gehört zum offenen
Thema „Reste in der lokalen Test-DB" und ist kein Teil dieses PR — wer
ihn anfasst, setzt den `own_ids`-Filter, statt die Datenbank zu putzen.
Welcher Test die beiden Geräte hinterlässt, habe ich **nicht** ermittelt;
das wäre eine Behauptung statt eines Befundes (§5.68).

## Offen

* Ob der Betreiber Lesart A oder B wollte (siehe oben). Bis zur Antwort
  steht A.
* Ein Zimmer ohne Spur bleibt unbeobachtet. Eine dritte Spur wäre
  denkbar — etwa ein Istwert, der über Stunden nicht fällt, obwohl der
  Frei-Wert gilt —, aber das ist Inferenz und gehört nicht in einen
  Hinweis, der eine Handlung auslösen soll.
