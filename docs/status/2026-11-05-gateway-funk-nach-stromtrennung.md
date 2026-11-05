# Das Gateway kam schlechter zurück — 4 dB, hausweit, seit dem 04.11.

**Stand:** 05.11.2026

## Der Befund

Am 04.11. hat die Stromtrennung am UG65 das Gateway nach 36 Minuten
zurückgebracht (§10ay). **Es kam nicht in denselben Zustand zurück.**

| Zeitraum (Ortszeit) | SNR | RSSI | Uplinks/h | Geräte |
|---|---|---|---|---|
| bis 04.11. **06:00** | 8,6–9,0 | **−96** | ~605 | 103–104 |
| 04.11. **07:00** (Ausfallstunde) | 7,8 | −97 | 227 | 103 |
| ab 04.11. **08:00** bis 05.11. 09:00 | **6,0–6,9** | **−99/−100** | ~580 | 99–103 |

Rund **4 dB schlechter im RSSI, 2,3 dB im SNR**. Der Sprung liegt in
genau der Stunde, in der jemand am Gerät war, und er hält seit 25
Stunden an. Der Vergleich Stunde-gegen-Vortagsstunde zeigt **−2,0 bis
−2,4 dB** für jede Stunde, in der der Vortag noch gesund war.

**38 von 103 Geräten** haben über 3 dB verloren, verteilt über alle
Etagen: Zimmer 54, 102, 104, 105, 107, 204, 205, 208, 303, 307. Das sind
nicht hundert Geräte gleichzeitig, **das ist der Empfänger.**

Die Uplink-Menge ist dabei fast unverändert (605 → 580 je Stunde). Die
Verbindung steht also — sie hat nur 4 dB weniger Reserve.

## Wer dadurch ausgefallen ist

Die Geräte mit der geringsten Reserve sind unter den Rauschboden
gerutscht:

| Gerät | Ort | bis 03.11. | jetzt |
|---|---|---|---|
| **021** | 107 Kinderzimmer | 144 Uplinks/Tag, SNR **+6,3**, RSSI −105 | **6 Uplinks/Tag**, SNR **−9,7**, RSSI **−114** |
| **026** | 109 Bad | 142, −1,7, −113 | 40, **−7,0**, −113 |
| **028** | 110 Bad | 142, **+2,5**, −110 | 25, **−6,6**, −113 |

**Gerät 021 war vorher gesund.** Es ist kein Standort- und kein
Gerätefall, sondern der Teilnehmer mit dem längsten Weg, dem 9 dB
genommen wurden. −114 dBm ist der schlechteste Wert im ganzen Haus und
zugleich der Rauschboden.

Bei Class A heißt wenig senden auch wenig empfangen: ein Gerät mit 6
Uplinks am Tag öffnet das Downlink-Fenster 24-mal seltener als ein
gesundes. Es nimmt also auch keine Sollwerte mehr an.

## Wie es gefunden wurde, und warum das das Eigentliche ist

**Zufällig.** Der Betreiber hatte drei Geräte mit wenigen Uplinks
gemeldet — Zimmer 107, 109, 110, alle bei −113 dBm — und die Hypothese
„Funkloch in diesem Bereich" aufgestellt. Die Prüfung sollte sie
bestätigen oder verwerfen.

**Sie war falsch, und die Widerlegung führte zum richtigen Befund.** Die
Zimmernachbarn derselben Räume sind in Ordnung: 107 Bad mit 143 Uplinks
bei SNR +5,9, 109 Schlafzimmer mit 143 bei +3,1. Innerhalb eines Zimmers
liegen 9–14 dB Unterschied — ein Bereichsproblem erklärt das nicht. Erst
der Blick auf **14 Tage statt 24 Stunden** zeigte, dass alle drei bis
zum 03.11. normal waren.

**Mein eigener Fehler steht am Anfang davon:** die erste Auswertung lief
über 24 Stunden und mischte damit den gesunden und den gestörten
Zeitraum. Daraus sahen die drei Geräte wie dauerhaft schwache Standorte
aus. Ein Mittelwert über ein Fenster, in dem sich die Sache **ändert**,
verbirgt die Änderung — dieselbe Klasse wie §5.59, nur in der Auswertung
statt im Test.

**Niemand hätte es gemeldet.** Kein Alarm überwacht die Funkqualität. Die
Geräte waren `health_state = healthy`, weil sie ja noch melden; die
Batterie ist in Ordnung; die Uplinks liefen weiter. Das ist §5.76
wörtlich: der Mechanismus war grün, und die Wirkung war es nicht.

## Was offen ist

**Warum.** Die Korrelation ist eng, der Mechanismus unbelegt. Kandidaten,
in dieser Reihenfolge: **Antennenstecker nicht ganz fest**, Antenne
verdreht oder verbogen, oder das Gateway kam mit anderer
Funk-Konfiguration zurück. Wetter ist es nicht — ein 4-dB-Sprung
innerhalb einer Stunde und danach 25 Stunden flach sieht nicht so aus.

**Was nicht geprüft werden konnte:** die Datenrate bzw. der Spreizfaktor.
Wir speichern `rssi_dbm` und `snr_db`; der Spreizfaktor steckt in
ChirpStacks `txInfo` und wird nicht persistiert. Ob das Gateway nach dem
Neustart auf einem anderen SF empfängt, ist aus unseren Daten **nicht**
zu beantworten.

## Was daraus folgt

1. **§10ay Schritt 6** — nach jeder Stromtrennung am UG65 wird die
   Funkqualität geprüft, mit Befehl und Schwellwert. Dieser PR.
2. **Nie den Antennenstecker unter Strom lösen** — ebenfalls in §10ay.
   Ein Sender, der in einen offenen Stecker sendet, bekommt seine
   Leistung reflektiert zurück.
3. **Ein Wächter ist geplant** (Entscheidung des Betreibers, 05.11.):
   hausweiter SNR-Mittelwert der letzten Stunde gegen eine Grundlinie,
   Warnung bei mehr als 2 dB. Er hätte am 04.11. um 09:00 gemeldet statt
   heute zufällig. Der Plan gehört in den Sprint-Brief, nicht hierher —
   mit einem Fallstrick, der beim Entwerfen der Abfrage aufgefallen ist:
   **eine gleitende Mehrtages-Grundlinie verdünnt sich selbst.** Die
   Urteilsabfrage gegen das 7-Tage-Mittel sagt heute „im Rahmen" bei
   −1,8 dB, weil die 25 Stunden Störung im Mittel schon drinstecken. Ein
   Melder, der nach zwei Tagen von selbst verstummt, überwacht nichts.
4. **Der Antennenblick kommt vor dem Gerätetausch.** Ein neues Gerät in
   Zimmer 107 bringt nichts, wenn der Empfänger 4 dB verloren hat.

## Was nicht behauptet wird

Dass die Stromtrennung die Ursache **ist**. Sie ist der Zeitpunkt. Dass
das Gateway auch ohne Eingriff 4 dB verloren haben könnte, ist nicht
ausgeschlossen — nur unwahrscheinlich, weil der Sprung genau in die eine
Stunde fällt, in der jemand daran war.

Und dass §10ay deshalb falsch wäre: die Stromtrennung **ist** die
Behebung, das steht. Sie hat nur einen Preis, und der gehört
aufgeschrieben, bevor ihn das nächste Mal wieder niemand misst.
