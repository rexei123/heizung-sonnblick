# Relais-Verlauf, Nachtrag: Gehäuse, Stundengrenze, Alarmtabelle (27.11.2026)

Drei Punkte, die seit dem 18.11.2026 auf der Liste standen, in einem PR —
sie hängen an derselben Ansicht und an derselben Tabelle.

## 1. Die Gehäusetemperatur steht jetzt in der Tageszeile

**Die offene Frage war:** steigt das Gehäuse von Relais 110 über die Tage?
Sie war bisher nur mit einer Abfrage auf `relay_reading` am Server zu
beantworten — der Melder sieht 75 Minuten, die Karte den letzten Wert, und
der Verlauf sagte dazu nichts.

Jede Tageszeile trägt seither vier Zahlen: Mittel und größten Wert über
**alle** Meldungen des Tages, und dieselben beiden nur über die mit
eingeschaltetem Relais. Der Abstand zwischen den Paaren ist die eigentliche
Auskunft — *warm vom Schalten* oder *warm ohnehin*. Im Prüfsatz liegt der
größte Wert des Tages (45) in einer Meldung, in der das Relais **aus**
war; genau dieser Fall wäre mit nur einer Spalte unsichtbar.

**Keine Einheit, und das ist Absicht.** `internal_temperature_raw` ist ein
Rohwert; der Hersteller-Dekoder liest ein Byte und nennt keine Einheit
(AE-78). Ein „°C" in der Spalte wäre eine Behauptung, die niemand geprüft
hat — und für die Frage „steigt sie" braucht man keine Einheit, sondern
zwei Tage. Eine Mutationsprobe setzt das „°C" ein; der Playwright-Test
geht dabei rot.

**Das Tagesmittel wiegt nach der Zahl der Meldungen**, anders als
`ist_mittel` in derselben Zeile, das gleichmäßig über die Stunden mittelt.
Der Unterschied ist kein Versehen: die Zahl der *eingeschalteten* Meldungen
schwankt je Stunde zwischen null und sechs, und ein ungewogenes Mittel
wäre der Mittelwert über „Stunden, in denen zufällig einmal geschaltet
war". Bei `ist_mittel` liegen die Messungen gleichmäßig, dort kostet die
Gewichtung nichts und bringt nichts. Die Begründung steht im Feld, nicht
nur hier.

**Eigene Abfrage, nicht in `_ANTEIL_SQL` eingehängt.** Eine
Gehäusetemperatur ist ein *Punkt*, eine Einschaltdauer eine *Spanne*. Die
Spannen werden seit diesem PR an Stundengrenzen geteilt und vervielfachen
dabei Zeilen; ein Mittelwert über diese Stücke würde dieselbe Meldung
zweimal wiegen.

**Wo die Zahlen stehen — und wo nicht.** Je Tag in der Tabelle und in der
Antwort des Endpunkts; je Stunde **nur in der CSV-Datei**. Wer die Kurve
zeichnen will, braucht die Stunden und tut es in der Tabellenkalkulation;
ein Feld in der JSON-Antwort, das die Oberfläche nicht liest, wäre das
Gewicht, das §0 S6 meint. Die Asymmetrie steht im Docstring des
CSV-Endpunkts, damit sie nicht als Lücke gelesen wird.

## 2. Der Stundengrenzen-Fix — der Fall 193 Wh

**Der Befund vom 18.11.2026:** eine Stundenzeile mit **0 Prozent
Einschaltanteil und 193 Wh**. Beides kam aus derselben Spanne, und beides
landete in derselben Stunde:

| | vorher | jetzt |
|---|---|---|
| Spanne 10:57 → 11:07, Stand AUS, Zähler +193 Wh | ganz in Stunde 10 | 3 min in Stunde 10, 7 min in Stunde 11 |
| Energie | 193 Wh in Stunde 10 | 58 Wh in Stunde 10, 135 Wh in Stunde 11 |
| Heizdauer | 0 min (Zustand am Spannenanfang) | 0 min in beiden Stücken |
| Einschaltung | im Stück mit dem Spannenanfang | unverändert — ein **Ereignis**, kein Zustand |

Die Zeile sagte damit zwei Dinge, die sich widersprechen: *es lief nicht*
und *es hat verbraucht*. Richtig war das erste; der Strom floss in Stunde
11.

**Was der Fix nicht kann, und das steht im Modulkopf:** wo die Energie
*innerhalb* der Spanne liegt, wissen wir weiterhin nicht. Im Beispiel lief
das Panel wahrscheinlich erst ab 11:00, die 58 Wh in Stunde 10 sind also
noch zu viel. Die Aufteilung nach Zeit ist die Annahme mit der geringsten
Behauptung; alles der späteren Stunde zuzuschlagen wäre eine Aussage über
den Zeitpunkt des Schaltens, die die Zehn-Minuten-Auflösung nicht hergibt.
Über das Fenster ist die Summe in beiden Fällen dieselbe — im Prüfsatz
210 Wh, genau die Zählerdifferenz.

**Je Stunde wird gerundet**, und die angezeigte Summe ist die Summe der
angezeigten Zeilen. Bei geteilten Spannen kann sie damit um ein Wh von der
Zählerdifferenz abweichen. Der Preis ist bewusst gewählt: eine Summe, die
zu keiner Zeile passt, ist schlechter als ein Wh. `round` statt `int` —
abschneiden wäre bei 24 Stunden bis zu 24 Wh zu wenig, und immer in
dieselbe Richtung.

**Verhaltensneutral für die Bestandstests.** Alle fünfzehn Tests von
`test_relais_auswertung` und alle von `test_relais_verlauf` bleiben
**unverändert** grün: ihre Meldungen liegen auf Stundengrenzen, dort gibt
es nichts zu teilen. Das ist der Beleg, dass der Fix nur den Fall trifft,
um den es geht (§5.47).

## 3. Die Alarmtabelle war nicht um zwei Zeilen zu kurz, sondern um fünf

Notiert waren der **Zonen-Melder** und der **Platten-Wächter**. Beim
Nachtragen kamen drei weitere Alarmwege zum Vorschein, die niemand als
Lücke vermerkt hatte:

| Alarm | wo er versendet |
|---|---|
| **Gerät nimmt den Sollwert nicht an** | `tasks/engine_tasks` — nach drei Befehlen meldet das Gerät weiter einen anderen Wert |
| **Belegungsliste überfällig** | `services/occupancy_import_service` — eigener Text neben „keine Belegungsliste" |
| **Stand festgesetzt** | `services/pin_reminder` — der Server läuft seit sieben Tagen auf einem festgenagelten Abbild |

Sie sind einfach dazugekommen, und die Tabelle ist stehen geblieben. Der
Kasten vom 18.11., der die Tabelle als unvollständig auswies, ist damit
weg — nicht weil die Lücke egal wäre, sondern weil sie geschlossen ist.

**Dazu ein Stolperdraht**, `tests/test_runbook_alarmtabelle.py`: die Zahl
der Tabellenzeilen muss der Zahl der Stellen entsprechen, die
`mailer.send_mail` **benutzen**. Gezählt wird im Syntaxbaum und nicht im
Text — das trifft beide Versandformen des Repos (direkter Aufruf und
`asyncio.to_thread(mailer.send_mail, …)`) und keine der sechs Erwähnungen
in Docstrings. Wer einen Alarmweg baut, kommt an `send_mail` nicht vorbei;
eine Liste von Alarm-Namen im Test wäre dagegen eine zweite Tabelle, die
genauso altert wie die erste. Der Test prüft die **Anzahl**, nicht den
Inhalt, und sagt das in seinem Kopf.

Ein zweiter Test verbietet, dass wieder ein „unvollständig"-Vermerk in den
Abschnitt wandert. Ein solcher Hinweis ist ehrlich, solange jemand ihn
nachträgt; als Dauerzustand ist er ein Melder, dem man nicht glauben muss
(§5.79).

### Noch ein Befund in derselben Tabelle

Unter der Tabelle stand, die **Batterie-Schwelle** unter *Einstellungen /
Hotel* färbe Anzeige und Kachel. **Diesen Schalter gibt es dort nicht
mehr:** mit Sprint 20 (AE-72) ist `alert_battery_warn_percent` aus Schema
und Oberfläche entfallen, die Spalte steht nur noch ungelesen in
`global_config`. Wer dem Satz folgte, suchte ein Feld, das es nicht gibt —
§5.77, und zwar an der Stelle, die der Betreiber im Alarmfall liest. Die
Korrektur steht im RUNBOOK als Kasten, mit dem Hinweis, dass B-15b-1
damit anders zu lesen ist: der offene Rest ist „Mail an der
Batterie-**Stufe**", nicht „Mail an der konfigurierten Prozent-Schwelle".

## Mutationsproben

Neun, jede einzeln gesetzt und zurückgenommen:

| # | Mutation | Rot |
|---|---|---|
| 1 | Keine Teilung — Spanne ganz der ersten Stunde | **4** |
| 2 | Energie ganz dem ersten Stück statt zeitproportional | 2 |
| 3 | Einschaltung in **jedem** Stück gezählt | 1 |
| 4 | `FILTER (WHERE relay_on)` weg — beide Gehäusespalten gleich | 3 |
| 5 | Tagesmittel ungewogen | 5 |
| 6 | `int` statt `round` bei der Energie | 1 |
| 7 | Eine Zeile aus der Alarmtabelle entfernt | 1 |
| 8 | Fehlender Gehäusewert als `0.0` statt Strich | 1 (Playwright) |
| 9 | „°C" an den Rohwert | 1 (Playwright) |

**Probe 3 blieb beim ersten Lauf grün** — und das ist der Befund dieses
PR in eigener Sache. Der Test hieß „ein Einschalten wird nur einmal
gezählt", prüfte das aber nicht: im Prüfsatz liegt das Einschalten um
11:07 in einer Spanne, die ganz in Stunde 11 steckt. Die Bedingung
`von = spanne_von` war dort folgenlos, ihre Entfernung änderte nichts, und
der Test war grün aus dem falschen Grund (§5.55 — dasselbe Muster wie
Probe 8 beim Tagesplan sechs Tage vorher).

Der zweite Prüfsatz `haus_einschalten` lässt Einschalten und Teilung
zusammenfallen: um 10:57 geht das Relais an, die Spanne reicht bis 11:07.
Danach ist die Probe rot. Derselbe Aufbau belegt zugleich, dass die
**Heizdauer** geteilt wird (3 und 7 Minuten) — vorher trug die erste
Stunde alle zehn, und die zweite, in der das Panel fast durchgehend lief,
keine einzige.

## Zahlen

* **2344 Tests** grün (vorher 2324), 60 übersprungen, 1 xfailed.
* **440 Playwright-Tests** grün (vorher 438).
* `ruff check`, `ruff format --check`, `mypy src`, `tsc --noEmit`,
  `eslint` ohne Befund.
* Keine Migration. Die Gehäusespalte gibt es seit Migration 0041; dieser
  PR liest sie.

## Offen

* **Ob 110 über die Tage steigt, sagt dieser PR nicht** — er stellt die
  Frage nur beantwortbar. Die Antwort braucht zwei bis drei Tage
  Beobachtung in der neuen Tabelle.
* Die Gehäusezahlen gelten für die **Zone**, wie alle anderen in dieser
  Ansicht. Hängen zwei Relais in einem Raum, ist der größte Wert der des
  wärmeren Gehäuses. Eine Zahl je Gerät wäre eine zweite Gliederung in
  derselben Zeile; sie wird erst nötig, wenn eine Zone zwei Relais hat,
  die sich unterschiedlich erwärmen.
* Die Einheit des Rohwerts ist weiter unbelegt (AE-78). Sie zu klären
  hieße, am Gerät zu messen.
