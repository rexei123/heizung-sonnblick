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

## Nachtrag vom selben Tag, 10:15 — zwei Kandidaten sind weg

Der Betreiber hat nachgesehen, und die beiden naheliegenden Erklärungen
fallen damit aus:

| Geprüft | Ergebnis |
|---|---|
| **ChirpStack-Dashboard, 31 Tage** | Kanäle **unverändert** (868,1 / 868,3 / 868,5), Empfang stabil bei rund **14.600 Meldungen am Tag**, keine Kollisionen |
| **Datenraten** | seit dem 04.11. **mehr DR2–4** — die Geräte weichen auf robustere Stufen aus |
| **Antenne vor Ort** | **Sitz und Position unverändert** |

**Geänderte Funk-Einstellung und Antenne sind damit ausgeschlossen.**

Der DR-Befund passt zum Bild und ist ein unabhängiger Beleg: ADR
reagiert auf ein schlechteres Link-Budget, indem es auf eine robustere
Stufe geht. Die Geräte haben also selbst gemerkt, dass weniger Reserve da
ist — und dass die Meldungsmenge trotzdem stabil blieb, ist genau die
Folge: sie haben es ausgeglichen, auf Kosten von Sendezeit und Batterie.
Nur die Geräte ohne Reserve konnten es nicht ausgleichen.

**Die Hypothese ist jetzt eine andere:** eine **schlechte Kalibrierung
des Funkmoduls beim harten Neustart** — oder ein **Hardware-Schaden** im
Gerät. Beides kann dieses System nicht unterscheiden; die Antwort kommt
aus einem geplanten Neustart (§10ay Schritt 7) und, wenn der nichts
bringt, von Milesight.

## Nachtrag 06.11.2026 — behoben, und eine Lehre über das Messen

**Ein geplanter Neustart mit 30 Sekunden stromlos hat es behoben.**
Gemessen in Zehn-Minuten-Fenstern:

| Fenster (Ortszeit) | SNR | RSSI |
|---|---|---|
| 07:00–07:59 | 6,0–6,7 | −100 / −101 |
| **08:00** | **8,7** | **−96** |
| 08:10–08:50 | 9,4 · 9,1 · 9,2 · 9,2 · 8,9 | **−95** |
| 09:00–13:00 (Stundenmittel) | 9,0–9,2 | −95 |

Der Stand vor dem Vorfall war 8,6–9,0 bei −96 — **vollständig erholt**.
Und die drei ausgefallenen Geräte senden wieder im Takt: **021** (Zimmer
107 Kinderzimmer) hatte **6 Meldungen am Tag**, jetzt wieder 18 in drei
Stunden, also 144 am Tag wie vorher. Auch 026 und 028 sind zurück, beide
sogar leicht über ihrem Stand von Ende Oktober.

### Es war ein Sprung, keine Kurve — und das ist eine Korrektur

Die ersten Stichproben nach dem Neustart sahen nach einer **langsamen**
Erholung aus: 6,2 → 6,7 → 6,9 → 7,1 (08:13) → 9,1 (13:46). Daraus wäre
die Regel „Bewertung erst nach vier bis sechs Stunden" gefolgt.

**Die Zehn-Minuten-Fenster zeigen etwas anderes:** zwischen 07:50 und
08:10 ist der volle Wert da, und von 09:00 bis 13:00 liegen die
Stundenmittel **flach** bei 9,1. Es gab keine Erholung über Stunden.

Die scheinbare Kurve war ein **gleitendes Fenster, das sich leerte**. Um
08:13 deckte „letzte 30 Minuten" den Zeitraum 07:43–08:13 ab — also
überwiegend den alten, schlechten Zustand. Mit jeder Stichprobe rutschte
mehr davon heraus, und der Mittelwert stieg. **Nicht das Gateway hat sich
langsam erholt, sondern die Messung hat sich langsam gereinigt.**

**Das ist dieselbe Falle zum zweiten Mal in diesem Vorgang.** Am 05.11.
hat mein eigenes 24-Stunden-Fenster den gesunden mit dem gestörten
Zeitraum gemischt und drei Geräte wie dauerhaft schwache Standorte
aussehen lassen. Jetzt hat ein 30-Minuten-Fenster die Erholung wie eine
Kurve aussehen lassen. **Ein Mittelwert über ein Fenster, in dem sich die
Sache ändert, verbirgt die Änderung** — und zwar in beide Richtungen.

Die Regel, die daraus in §10ay Schritt 4 steht, ist deshalb nicht „länger
warten", sondern: **das Fenster muss vollständig nach der Rückkehr
liegen.** Dreißig Minuten genügen; sie beginnen erst, wenn wieder
Meldungen kommen.

### Der Mechanismus bleibt ungeklärt

Dass dreißig Sekunden stromlos den Verlust behoben haben, den eine
Stromtrennung zwei Tage vorher **verursacht** hat, ist **beobachtet und
nicht erklärt**. „Kalibrierung des Funkmoduls" ist eine plausible
Geschichte und kein Befund; sie steht in §10ay als Vermutung und nicht
als Ursache. Wer sie belegen will, braucht Milesight oder einen zweiten
Fall.

**Was für den nächsten Vorfall gilt:** nach einem harten Stromverlust die
Funkqualität prüfen, und bei einem Befund **einen geplanten Neustart
versuchen, bevor man das Gerät für defekt hält.** Beim ersten Mal hat es
geholfen.

## Was offen bleibt

**Nicht mehr der Funk.** Offen ist die ältere Frage, und sie ist die
teurere: **warum verbindet sich das UG65 nach einem Neustart des LNS
nicht von selbst wieder?** Am 04.11. kam es 36 Minuten nicht zurück,
obwohl Bridge und ChirpStack ab 07:39:59 frisch liefen. Das ist die eine
Frage, die an Milesight geht — eng gestellt, nicht als „was könnte es
sein".

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
