---
datum: 2026-11-14
thema: Der gemeldete Schaltzustand bekommt ein Haltbarkeitsdatum
pr: offen
---

# Ein Panel, das heizt, und ein Wächter, der „bereits aus" meldet

Punkt 2c des Auftrags vom 13.11.2026: *„Veralteter Relais-Zustand (> 2,5 ×
Meldeintervall) im Wächter = ‚unbekannt': kein `bereits_aus`, sondern
Zustandsabfrage `0xB1`."* **Steuerpfad**, Merge Montag 16.11.

**Dieser Zweig setzt auf #405 auf** und trägt deshalb vorläufig dessen
Branch als Basis — 2c rechnet mit `relay_meldeintervall_s`, und diese
Einstellung entsteht erst dort. Nach dem Merge von #405 zeigt der PR von
selbst auf `develop`.

## Der Fehler, in einem Satz

Der Wächter hat dem letzten gemeldeten Schaltzustand **ohne Verfallsdatum**
geglaubt. Eine Meldung von vor drei Stunden galt wie eine von vor drei
Minuten.

Das ist in beide Richtungen offen:

| letzte Meldung | Regler will | bisher | in Wahrheit möglich |
|---|---|---|---|
| **AUS**, vor 3 h | AUS | `bereits_aus`, nichts | das Panel **heizt** — die Bestätigung eines späteren EIN ging verloren |
| **EIN**, vor 3 h | EIN | `laeuft_ab_von_selbst`, nichts | der Timer ist längst abgelaufen, das Zimmer **kühlt aus** |

Die erste Zeile ist die teure. Ein 1600-W-Panel, das unbemerkt heizt, ist
genau der Fall, gegen den dieser Wächter gebaut wurde — und er entstand
hier **aus seinem eigenen Urteil**. Und er blieb: es gab keinen Durchlauf
mehr, der daran etwas ändert, weil nichts mehr gefragt wurde.

**Dass das real möglich ist, steht gemessen im Repo.** Am Relais 109 lagen
**16 % Paketverlust bei eingeschaltetem Panel** (0 % bei ausgeschaltetem,
Befund vom 13.11.). Eine verlorene Bestätigung ist dort kein Sonderfall.

## Was gebaut ist

**1. Der Zustand hat jetzt zwei Zeiten.** `relay_state.RelaisZustand`
trägt neben `seit` (Beginn des Zustands, daran rechnet der
Zweipunktregler seine Mindestlaufzeit) ein neues `gemeldet`: den
Zeitpunkt der **jüngsten** Zeile, die den Zustand führt.

Die Verwechslung der beiden ist teuer, und sie ist nicht
rekonstruierbar: „EIN seit zwei Stunden, zuletzt gehört vor zehn Minuten"
und „EIN gemeldet vor zwei Stunden, seither still" haben **dieselbe**
`seit`. Wer die Frische daran misst, hält ein laufendes Panel für stumm
und ein stummes für laufend.

**2. Der Wächter prüft das Alter vor allem anderen.** Ist die Meldung
älter als das Fenster, gilt der Zustand als **unbekannt** — und zwar als
Schritt 0, vor der Bestätigungsprüfung. Das schließt einen zweiten
Fehler, der vorher gar nicht aufgefallen war: eine Meldung von vor zwei
Stunden konnte einen Befehl von vor zwei Minuten „bestätigen". Der
offene Stand verschwand, ein Einschaltzyklus wurde gezählt, und geprüft
hatte niemand etwas.

**3. Bei unbekanntem Zustand wird gefragt, egal was gewünscht ist.** Die
Abfrage steht jetzt **vor** dem AUS-Zweig. Damit endet „ich weiß es
nicht" nicht mehr in `bereits_aus`. `bereits_aus` gibt es weiterhin — aber
nur noch für eine Meldung, der wir glauben.

Der Wächter sagt das mit einer eigenen Handlung (`FRAGE_ZUSTAND`) statt
über einen Grund-Text, den der Aufrufer vergleicht. Zwei Gründe
unterscheiden die Fälle im Protokoll: `zustand_unbekannt` („noch nie
gemeldet", ein Montagefall) und `zustand_veraltet` („seit 25 min stumm",
ein Funkfall).

**4. Das Fenster ist das Zweieinhalbfache des Meldeintervalls**, mit den
Vorgaben **25 Minuten**. Dieselbe Zahl (`VERALTUNGS_FAKTOR`) und dieselbe
Begründung wie beim Fühler der Zone: eine verlorene Meldung soll nichts
ändern, zwei in Folge schon. Bei genau zwei verlorenen Meldungen ist die
dritte um 30 Minuten fällig — die Schwelle greift also davor und nicht
danach.

**5. Die Abfrage wird gedrosselt** — eine Abfrage je Gerät und Fenster,
über eine Redis-Marke mit Ablauf (`services/relais_abfrage.py`).

## Warum die Drosselung zum Auftrag gehört

**Ohne sie wäre die Änderung schädlich.** Bisher wurde nur bei
gewünschtem EIN gefragt, und das heilte sich nach einem Durchlauf selbst.
Jetzt wird auch bei gewünschtem AUS gefragt — also auch bei einem Relais,
das **dauerhaft** schweigt. Der Orchestrator läuft jede Minute:

| | ohne Bremse | mit Bremse |
|---|---|---|
| Lese-Downlinks je Tag, ein stummes Relais | **1440** | **57** |
| Sendezeit dafür bei DR1 (~0,66 s) | **rund 16 min** | rund 38 s |

16 Minuten am Tag sind mehr als ein Prozent — jenseits dessen, was das
Gateway auf den meisten Bändern einhalten muss. Es wäre derselbe Fehler
wie die feste Frist von 60 Sekunden, die am 01.11. sieben Downlinks in
sieben Minuten erzeugt hat, nur mit einem Lese- statt einem
Schaltbefehl.

**Der Abstand ist das Veraltungs-Fenster selbst**, aus einer Funktion für
beide Verbraucher (`zustand_veraltungs_fenster`). Eine zweite Zahl hätte
dieselbe Herleitung und wäre eine zweite Wahrheit (§5.53).

**Bei Redis-Ausfall wird nicht gefragt** — die Gegenrichtung zu
`provision_lauf`, mit Begründung: eine unterbliebene Abfrage hält ein
Relais aus (kalter Raum), eine ungedrosselte verbrennt die Funkzeit des
ganzen Hauses. Praktisch ist das eher Form als Wirkung, weil Redis der
Broker dieses Tasks ist — ohne Redis läuft der Durchlauf gar nicht.

## Die Gegenvariante, und warum sie es nicht ist

Naheliegend wäre, bei unbekanntem Zustand und gewünschtem AUS sofort
`0xC1 00` zu schicken: ein Downlink statt zwei, und AUS ist die sichere
Richtung. Dagegen sprechen zwei Dinge, und das zweite ist das stärkere:

1. Es schreibt einen **Schaltbefehl auf eine Vermutung**.
2. Es nimmt dem nächsten Durchlauf die Grundlage. Nach einem AUS ins
   Blaue ist der Zustand **genauso unbekannt** wie vorher — nur steht
   jetzt ein unbestätigter Befehl offen, dessen Bestätigung dieselbe
   Funkstrecke nehmen muss, die gerade nicht liefert.

Der Auftrag sagt `0xB1`, und das ist auch die richtige Reihenfolge: erst
fragen, dann schalten.

## Was die Änderung kostet

**Eine Minute.** Ein veralteter Zustand führt zur Abfrage, und erst der
Durchlauf danach schaltet. Vorher: nichts, dauerhaft.

**Die Mindestlaufzeit läuft ab der Auskunft, nicht ab dem Einschalten.**
Eine Zustandsabfrage sagt, *was* gilt, nicht *seit wann*. Wird ein Panel
als EIN entdeckt, gilt die Mindestlaufzeit ab dieser Entdeckung — das
Panel heizt also noch zehn Minuten, wenn der Raum lediglich warm ist.
Bei fehlendem oder veraltetem **Istwert** greift unverändert der
Zwangs-AUS, der die Mindestlaufzeit bricht (S5). Ein eigener Test hält
beides fest.

**Der Regler bleibt unberührt.** `_zonen_schaltzustand` liest den Zustand
weiterhin ohne Haltbarkeitsdatum, und das ist Absicht: der Regler sendet
nichts. Zweifeln muss der, der sendet. Sichtbar wird das im
Ende-zu-Ende-Test, in dem der Regler `bereits_aus` sagt und der Wächter
trotzdem fragt.

## Was im Testaufbau geändert werden musste (§5.51)

Der Ende-zu-Ende-Aufbau legte **eine** Relais-Zeile von vor 30 Minuten
an. Diese eine Zeile trug zwei Aussagen auf einmal — „aus seit 30
Minuten" (Mindestpause vorbei) und „zuletzt gehört vor 30 Minuten". Mit
dem Haltbarkeitsdatum sind das zwei verschiedene Dinge, und fünf
Bestandstests wollten ein `0x57` und bekamen eine Abfrage.

**Die Antwort darauf ist der Aufbau, nicht die Regel.** Ein Relais im
Betrieb meldet alle zehn Minuten; „AUS seit 40 min, zuletzt gemeldet vor
5 min" ist der **normale** Zustand eines abgeschalteten Panels, und genau
den beschreiben die zwei Zeilen jetzt. Kein Assert wurde angepasst,
außer dort, wo die Änderung das Verhalten verändert.

In Szenario 3 (veralteter Fühler) wurde die EIN-Meldung von 20 auf 2
Minuten gezogen, damit sie die jüngste bleibt. Nebeneffekt: der Test
prüft jetzt mehr als vorher — bei zwei Minuten ist die Mindestlaufzeit
**nicht** abgelaufen, der Zwangs-AUS bricht sie also wie zugesagt.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 Veraltung gar nicht geprüft | **8 Tests rot** |
| M2 Abfrage wieder hinter den AUS-Zweig (`bereits_aus` gewinnt) | **7 Tests rot** |
| M3 Rand andersherum (genau auf der Schwelle gilt als alt) | **1 Test rot** |
| M4 Bestätigung weiter gegen die rohe Meldung | **1 Test rot** |
| M5 Schwelle fest im Code statt aus den Schwellen | **1 Test rot** |
| M6 `gemeldet` ist der Beginn des Zustands | **1 Test rot** |
| M7 eigene Zahl statt Meldeintervall mal Faktor | **3 Tests rot** |
| M8 Drosselung entfernt | **1 Test rot** |
| M9 Drosselung mit gemeinsamem Schlüssel | **2 Tests rot** |
| M10 Marke ohne Ablauf (Abfrage nur ein einziges Mal) | **2 Tests rot** |

Zehn Proben, zehn rot. M10 ist die Gegenprobe zur Bremse selbst: eine
Drosselung ohne Ablauf wäre eine Stilllegung — ein stummes Relais bliebe
nach der ersten Abfrage für immer unbefragt.

## Läufe

* Backend **1950 passed, 45 skipped, 1 xfailed**.
* `ruff check`, `ruff format --check` (342 Dateien), `mypy` (161 Dateien) grün.
* Kein Frontend-Code berührt.
* **Lokal rot, und nicht von hier:**
  `test_funkempfang::test_lies_funkempfang_zaehlt_nur_das_fenster` — die
  seit #400 gemeldeten Reste in der lokalen Testdatenbank, einzeln
  reproduzierbar, in CI grün (frische Datenbank). Eigene Aufgabe, nicht
  im Vorbeigehen gefixt (§0.1 Pflicht-Stop 4).
* §5.59-Probe: `BEZUG` in `test_relais_zustand_meldezeit` auf den
  29.03.2027 (Zeitumstellung) verschoben — grün, die Datei hängt nicht am
  Kalender.

## Was ablesbar ist, wenn es wirkt

Im Protokoll des Orchestrators:

```
relais-zustand zustand_veraltet, 0xB1 gesendet device_id=109 gemeldet=2026-11-14 07:12:03+00:00
```

Im Ergebnis je Zone: `gefragt` (eine Abfrage ging hinaus) und
`frage_gedrosselt` (es wäre eine fällig gewesen, die Bremse hielt). Ohne
die zweite Zahl wäre ein gedrosselter Durchlauf von einem
stillschweigenden nicht zu unterscheiden, und die Diagnose eines stummen
Relais begänne mit der falschen Frage (§5.76).

## Was dieser PR nicht tut

**Die Oberfläche sagt weiterhin nicht, wann die letzte Meldung kam.** Die
Gerätekarte zeigt den Zustand ohne Alter — ein Zustand, dem das Programm
inzwischen misstraut, sieht dort aus wie jeder andere. Das ist Punkt 7d
des Auftrags („Relais-Zustand ‚unbekannt — letzte Meldung HH:MM"), und
der gehört in einen Anzeige-PR.

**Es gibt keinen Melder für ein dauerhaft stummes Relais.** Nach 25
Minuten wird gefragt, nach Stunden wird weiter gefragt — und niemand
erfährt es, außer wer das Protokoll liest. Der Fühler einer Relais-Zone
hat seit #403 einen Melder; das Relais selbst hat keinen. Gehört als
eigenes Thema in die Liste (§5.76: die Wirkung überwachen, nicht die
Mechanik).
