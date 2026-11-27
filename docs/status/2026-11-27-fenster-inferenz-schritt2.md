# Fenster-Erkennung Schritt 2: das Ventil entscheidet (27.11.2026)

Passiv, wie vorgegeben. Kein Sollwert, kein Downlink, keine Schicht in der
Pipeline — nur eine Zeile im `event_log` und ein Werkzeug, das sie gegen
die Vergangenheit hält.

## Der Anlass, und die Zahl, um die es geht

Am 05.11.2026 meldete der Betreiber Zimmer 306: ein Gast, der sichtbar oft
lüftet, Einbrüche um 3 bis 4 Grad — und in 30 Tagen bei **13.179
Meldungen 0× `open_window = true`**. Die Analyse bestätigte die Einbrüche:
**49 Stück ab 1,5 Grad, davon 37 mit öffnendem Ventil.**

Diese 37 sind der Unterschied, um den es hier geht. Ein Temperaturfall
allein sagt nichts: ein Raum, dessen Sollwert gerade abgesenkt wurde,
kühlt genauso. Ein Fall, bei dem das **Ventil aufgeht**, sagt etwas — das
Gerät versucht gegenzuheizen und kommt nicht nach. Das ist Wärmeverlust,
und die häufigste Ursache dafür ist ein offenes Fenster.

## Was sich geändert hat

| | vorher (Sprint 9.11y) | jetzt |
|---|---|---|
| Lookback | 10 min | **25 min** |
| Δ-T-Schwelle | 0,5 °C | **1,5 °C** |
| Unterscheider | keiner | **Ventilstellung** |
| Wirkung | passiv | passiv (unverändert) |

**25 statt 10 Minuten** — Vorgabe des Betreibers. Zehn Minuten sind bei
einer Meldung alle paar Minuten zwei bis drei Messwerte; ein Fall über 1,5
Grad ist darin selten, und ein geöffnetes Fenster wirkt langsamer als zehn
Minuten.

**1,5 statt 0,5 Grad** — nicht vorgegeben, sondern Folge: der Prüfsatz
sind die 49 Einbrüche **ab 1,5 Grad**; mit 0,5 wäre der Detektor nicht
gegen ihn vergleichbar. Dazu die Mechanik: über 25 Minuten ist ein halbes
Grad normale Abkühlung, und ein Melder, der die meldet, meldet den ganzen
Tag.

## Der Unterscheider

Als „Ventil geht auf" gilt:

* ein Anstieg um mindestens **5 Prozentpunkte** zwischen der ältesten und
  der jüngsten Meldung des Fensters,
* **oder** eine jüngste Stellung von mindestens **90 %**.

**Der zweite Zweig ist nicht Beiwerk.** Ein Ventil, das schon ganz offen
steht, kann nicht weiter aufgehen; ohne ihn wäre genau der deutlichste
Wärmeverlust unsichtbar — das Gerät heizt mit allem, was es hat, und der
Detektor sieht „kein Anstieg". Eine Mutationsprobe entfernt den Zweig; der
Test geht rot.

**Die 5 Prozentpunkte gegen Rauschen.** Ein Ventil wackelt um ein bis zwei
Punkte; mit 0 wäre daraus ein Ereignis geworden.

**Ohne zwei Ventilmeldungen gibt es keinen Treffer.** Nicht, weil nichts
passiert wäre, sondern weil wir es nicht unterscheiden können — und ein
Melder, der meldet, wenn er nichts unterscheiden kann, ist genau der Lärm,
den dieser Schritt vermeiden soll.

**Fall und Ventil müssen zum selben Gerät gehören.** Ein Fall an Gerät A
und ein offenes Ventil an Gerät B sind zwei Beobachtungen und kein Befund;
über die Geräte zu mischen wäre die Sorte Korrelation, aus der Fehlalarme
werden. Ein Test hält es fest, eine Probe nimmt es weg.

## Der Prüfsatz ist jetzt ausführbar

**Die 49 Ereignisse liegen in der Datenbank des Servers, nicht hier.** Sie
als Datei ins Repo zu kopieren wäre eine Kopie, die beim ersten Nachziehen
nicht mehr zum Original passt — und die Frage „findet der Detektor sie
wieder" wäre damit nicht beantwortet, sondern nachgestellt.

Stattdessen gibt es `scripts/fensterinferenz.py`: es lässt **denselben**
Detektor über einen vergangenen Zeitraum laufen und bündelt die Treffer zu
Episoden.

```
docker exec deploy-api-1 python -m heizung.scripts.fensterinferenz --tage 30 --zimmer 306
```

Es liest nur — auch keine `event_log`-Zeile. Ein Probelauf, der Zeilen
anlegt, hätte die Geschichte verändert, gegen die er prüft.

**Es ist langsam, und das ist der Preis für eine Rechnung.** Dreißig Tage
in Zehn-Minuten-Schritten sind 4320 Aufrufe je Zimmer. Die Alternative
wäre, die Regel ein zweites Mal hinzuschreiben — zwei Rechnungen für
denselben Befund, von denen die eine nach dem ersten Nachziehen falsch ist
(§5.53).

**Wie die Zahl zu lesen ist:** liegt sie nah an 37, trifft der
Unterscheider. Liegt sie bei 49, unterscheidet er nichts. Liegt sie bei 3,
ist die Schwelle zu hoch. Der Lauf nennt den Vergleich selbst, damit
niemand ihn aus dem Gedächtnis zieht.

## Zwei Bestandstests nachgezogen

`test_inferred_window_detects_falling_temp_steady_setpoint` und
`test_inferred_window_pre_window_baseline_triggers` liefen mit einem Fall
von 1,0 Grad und ohne Ventilangabe. Beides trägt nicht mehr.

**Das ist eine Anpassung an eine geänderte Domänen-Wahrheit, nicht an
einen Bug** (§5.51) — und sie ist der Beleg, dass dieser PR nicht
verhaltensneutral ist (§5.47), was er auch nicht sein soll. Die
Zusicherung des zweiten Tests (`setpoint_c` aus der Pre-Window-Baseline)
ist unverändert; sie ist sein Gegenstand.

## Mutationsproben

Neun, jede einzeln gesetzt und zurückgenommen:

| # | Mutation | Rot |
|---|---|---|
| 1 | Unterscheider weg — jeder Fall ist ein Treffer | **5** |
| 2 | „Weit offen"-Zweig weg | 1 |
| 3 | Rausch-Schwelle auf 0 Prozentpunkte | 3 |
| 4 | Lookback zurück auf 10 min | 5 |
| 5 | Schwelle zurück auf 0,5 Grad | 2 |
| 6 | `>` statt `>=` an der Schwelle | 1 |
| 7 | **Eine** Ventilstellung genügt | 1 |
| 8 | Ventilweg über **alle** Geräte statt je Gerät | 1 |
| 9 | Ventilzahlen nicht im `event_log` | 1 |

**Probe 7 blieb beim ersten Lauf grün** — zum dritten Mal in diesem
Durchgang dasselbe Muster (§5.55). Der Test hatte als einzige Stellung
80 %: das ist kein Anstieg und nicht „weit offen", also fiel er auch mit
der Mutation durch. Mit **95 %** greift der „weit offen"-Zweig, und wer
die Zwei-Stellungen-Bedingung aufweicht, bekommt einen Treffer. Danach ist
die Probe rot.

## Zahlen

* **2337 Tests** grün (vorher 2324), 60 übersprungen, 1 xfailed.
* `ruff check`, `ruff format --check`, `mypy src` ohne Befund.
* Keine Migration. `sensor_reading.valve_position` gibt es seit dem
  Anfang; dieser PR liest sie.
* Kein Frontend berührt.

## Offen

* **Ob die 37 wiedergefunden werden, sagt dieser PR nicht.** Er macht die
  Frage ausführbar. Der Lauf auf dem Server ist ein Handgriff und braucht
  eine Freigabe — er liest nur, aber er läuft im Container.
* **Schritt 3** (die Vicki-Erkennung auf den Testgeräten 86 und 24
  einschalten) ist unberührt. Erst wenn beide Wege Zahlen liefern, ist
  vergleichbar, was die Hardware findet und was der Server vermutet.
* **Aktive Wirkung bleibt aus** (BR-16, AE-47): „Inferenz darf beobachten,
  aber nicht steuern, bevor sie sich produktiv bewährt hat." Ob die
  Schwellen stimmen, entscheidet der Prüfsatz — nicht dieser PR.
* Die Schwellen stehen als **Modulkonstanten**, nicht in den Settings. Sie
  dorthin zu ziehen lohnt erst, wenn der Prüfsatz gelaufen ist und jemand
  sie nachjustieren will; ein Schalter für einen Wert, den niemand kennt,
  ist Gewicht (§0 S6).
