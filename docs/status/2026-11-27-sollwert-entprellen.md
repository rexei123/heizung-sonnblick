# Entprellen der Sollwert-Befehle (Sprint 25 T1, gebaut 27.11.2026)

Der Kern des Sprint-25-Briefs vom 05.11.2026, und der letzte offene Punkt
daraus. T2 bis T5 sind seit dem 08.11. gebaut.

## Der Fall

Ändert die Steuerung ihren Wunsch zweimal kurz hintereinander — erst 20,
dann 25 innerhalb von hundert Sekunden —, gehen **zwei** Downlinks hinaus
und das Ventil führt **zwei** Bewegungen aus. Die erste war überflüssig.
**125 solche Fälle** lagen dem Brief zugrunde.

Seit diesem PR wird die erste Änderung je Gerät **gesammelt** und erst
beim nächsten Tick nach Ablauf des Fensters geschickt — dann aber mit dem
Wert, der **dann** gilt:

| Verlauf | vorher | jetzt |
|---|---|---|
| 20 → 25 | zwei Downlinks | **einer**, mit 25 |
| 20 → 25 → 20 | zwei Downlinks | **keiner** |
| ein einzelner Wechsel | ein Downlink | einer, 60–120 s später |

## Der Tick ist die Uhr

Die naheliegende Form wäre ein Celery-Auftrag mit `countdown`, der nach
sechzig Sekunden den gemerkten Wert schickt. Dagegen sprechen zwei Dinge,
und beide sind der Grund für die gewählte Form:

1. **Der gemerkte Wert wäre der alte.** Der Auftrag müsste senden, was vor
   einer Minute gewollt war. Der Tick rechnet den Wunsch neu und schickt
   den **jetzt** gültigen — und das ist der Punkt des Entprellens.
2. **Ein zweiter Schreibpfad an die Hardware.** Heute geht jeder Sollwert
   durch genau eine Stelle (`engine_tasks._dispatch_downlinks_per_zone`).
   Ein Auftrag, der daneben publiziert, wäre der zweite — und zwei Pfade
   zur selben Geräte-Warteschlange sind der Fall, den §0 S4 verbietet.

Die Engine läuft im Minutentakt. Mit `SOLLWERT_ENTPRELL_S=60` geht ein
Wert beim nächsten Tick hinaus, der mindestens eine Minute nach der ersten
Änderung liegt: **60 bis 120 Sekunden**, genau die Spanne aus dem Brief.
Die Wartezeit ist damit eine Folge des Takts und keine zweite Uhr, die man
synchron halten müsste.

**60 und nicht 120**, obwohl der Brief die Spanne nennt: mit 120 wäre die
tatsächliche Wartezeit 120 bis 180 Sekunden. Eine Nachtabsenkung drei
Minuten später ist nichts, eine Korrektur nach einer Drehrad-Verstellung
schon.

## Drei Wege gehen daran vorbei

| Weg | Grund |
|---|---|
| **Boost** | Die eine Sollwertänderung, die der Gast sofort spüren soll. Eine Minute Wartezeit wäre genau dort teuer, wo jemand auf Wirkung wartet und sonst noch einmal drückt |
| **Re-Sync nach Neustart** | Das Gerät steht nach einem Stromausfall auf einem gedrifteten Wert (§5.71). Eine Minute auf dem falschen Wert ist genau das, was der Re-Sync verhindern soll |
| **Abgleich** | Er ist selbst auf eine Nachsendung je 30 Minuten gedrosselt. Zwei Bremsen hintereinander verschieben nur, sie bremsen nichts |

**Der Boost löscht den Merker**, statt ihn zu ignorieren — sonst folgte
dem sofortigen Boost eine Minute später der gesammelte alte Wert und nähme
ihn zurück. Dieser Punkt stand ausdrücklich im Brief und hat einen eigenen
Test.

**Erkannt wird der Boost an der Quelle der Übersteuerung**, nicht am Wert.
Ein Vergleich „ist das ein Boost-Sollwert" wäre eine Vermutung über die
Absicht; die Quelle ist der Befund. Dafür trägt `RuleResult` ein neues
Feld `uebersteuerung_quelle` — gefüllt aus derselben Variablen, die auch
`raumweit_eingegriffen` liest, nicht aus einer zweiten Ableitung (§5.53).

## Nur Sollwerte

`0x07` (Kindersicherung), `0x08` (Grenzen) und `0x45`/`0x46`
(Fenstererkennung) laufen über `downlink_adapter` und berühren dieses
Modul nicht. Vorgabe des Betreibers, und sie ist die bessere Reihenfolge:
Class A stellt in Einreihungsfolge zu, Konfigurationsbefehle kommen also
**vor** einem entprellten Sollwert an — Grenzen zuerst, dann der Wert, der
sie einhalten muss.

## Bei Redis-Ausfall wird gesendet

Pflicht aus §0 S5. Ein Puffer, der bei Störung Befehle verschluckt, ist
schlimmer als der Zustand ohne ihn: fällt Redis aus, fällt das Entprellen
**zum Senden hin** aus, mit einer Zeile im Protokoll.

Das ist die **andere** Richtung als bei `engine_abgleich.darf_senden`, und
der Unterschied ist Absicht: dort verhindert die Sperre eine Nachsendung,
die Batterie kostet und nichts bewirkt — ohne Sperre lieber nicht senden.
Hier verzögert der Merker einen Befehl, den die Steuerung **will** — ohne
Merker lieber senden. Beide Richtungen stehen im Modulkopf nebeneinander,
damit die nächste Redis-Entscheidung nicht nach Gefühl fällt.

## Was im Trace steht

Ein gesammelter Wert bekommt den Status **`entprellt`** — nicht
`skipped_hysteresis`. Die Hysterese sagt „der Wert steht schon", das
Entprellen sagt „der Wert kommt noch". Wer beides als dieselbe Zeile
liest, hält eine Verzögerung für eine Nicht-Änderung und sucht den Fehler
bei der Hysterese (§5.53).

**Kein `ControlCommand` für einen gesammelten Wert.** Eine Zeile ohne
Downlink sähe aus wie ein Versuch; dieselbe Haltung wie bei der Hysterese.

## Die acht Testdateien, und der Preis dafür

Nach der Verdrahtung waren **22 Tests in acht Dateien** rot — alle mit
derselben Ursache: sie erwarten einen Downlink im **ersten** Tick, und das
stimmt nicht mehr.

Die Entscheidung: `conftest.py` setzt `SOLLWERT_ENTPRELL_S=0` für die
ganze Suite. Die betroffenen Tests prüfen, **was** gesendet wird — Wert,
Zone, Hysterese, Fenster, Übersteuerung —, nicht **wann**. Sie in je zwei
Ticks umzuschreiben hätte ihr Thema verschoben, und ein neuer Test, der
irgendwann einen Downlink erwartet, wäre ohne diese Zeile aus einem Grund
rot, der nichts mit ihm zu tun hat.

**Der Preis ist benannt und nicht versteckt:** damit prüft die Suite das
Zusammenspiel von Entprellen und allem anderen nicht (§5.55). Dagegen
steht `tests/test_sprint25_entprellen.py` — dort ist das Fenster **an**,
und die Tests laufen durch **denselben** Dispatch wie der Betrieb,
inklusive zweier Ticks, Boost, Re-Sync-Umgehung und der Gegenprobe, dass
`0` wirklich abschaltet. Ohne diese letzte Zeile liefen die 2300 anderen
Tests auf einer Annahme.

## Mutationsproben

Acht, jede einzeln gesetzt und zurückgenommen:

| # | Mutation | Rot |
|---|---|---|
| 1 | `fenster_s <= 0` wirkt nicht mehr (immer entprellen) | 2 |
| 2 | `_merke` setzt den Fensteranfang neu | 1 |
| 3 | `>` statt `>=` an der Fenstergrenze | 1 |
| 4 | Bei Redis-Ausfall **nicht** senden | 1 |
| 5 | Der Boost umgeht das Fenster nicht | 1 |
| 6 | Der Skip-Zweig löscht den Merker nicht | 1 |
| 7 | Der Boost umgeht, löscht den Merker aber nicht | 1 |
| 8 | **Jede** Übersteuerung umgeht das Fenster | 1 |

**Probe 2 blieb beim ersten Lauf grün.** Der Test rief zweimal
hintereinander auf, beide Aufrufe innerhalb derselben Sekunde — `seit` und
`jetzt` waren dieselbe Zahl, und „setze den Anfang neu" änderte nichts
Sichtbares. Der Test prüfte also nicht, was er behauptet (§5.55, derselbe
Befund wie bei Probe 3 im Relais-PR und Probe 8 beim Tagesplan). Er setzt
jetzt dreißig Sekunden zwischen die Aufrufe; danach ist die Probe rot.

Die Falle, die Probe 2 beschreibt, ist dabei keine erfundene: wer bei jeder
Änderung den Fensteranfang neu setzt, baut ein Fenster, das **nie**
abläuft — ein Gerät mit wechselndem Wunsch bekäme dann überhaupt keinen
Befehl mehr. Dieselbe Falle wie bei der TTL in
`engine_abgleich.versuch_gezaehlt`.

## Zahlen

* **2340 Tests** grün (vorher 2324), 60 übersprungen, 1 xfailed.
* `ruff check`, `ruff format --check`, `mypy src` ohne Befund.
* Keine Migration. Kein Frontend berührt.
* Neuer Settings-Wert `SOLLWERT_ENTPRELL_S` (Vorgabe 60), dokumentiert in
  `.env.example`.

## Offen

* **Die Wirkung ist noch nicht gemessen.** Ob aus 125 überflüssigen
  Bewegungen nachher eine Handvoll wird, sagt erst eine Woche Betrieb. Die
  Zahl steht im Trace: Einträge mit Status `entprellt` sind die
  gesammelten, und ein Vergleich der Downlinks je Tag vor und nach dem
  Deploy ist eine Abfrage auf `control_command`.
* **Das Fenster ist eine Abwägung, keine Herleitung** — so stand es schon
  im Brief. 60 Sekunden sind der Kompromiss zwischen gesparter Bewegung
  und Reaktionszeit; wer sie verschiebt, verschiebt beides.
* Ein neunter Testfall, der am Entprellen hängt, gehört in
  `test_sprint25_entprellen.py` und nicht in die `conftest`-Ausnahme.
