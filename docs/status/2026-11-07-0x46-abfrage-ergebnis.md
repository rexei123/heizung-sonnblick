# Die Fenstererkennung ist aus — jetzt belegt, nicht erschlossen

**Stand:** 07.11.2026 · Folgedoku zu #386 (`0038_fenstererkennung_stand`)

## Die Frage

Der Befund vom 05.11. war eine **Schlussfolgerung**: in 30 Tagen bei
13.179 Meldungen aus Zimmer 306 **null** `open_window = true`, hausweit
604.694 Zeilen `false` und keine einzige `true` — also ist die Erkennung
wohl nie eingeschaltet worden. „Wohl" ist dabei das entscheidende Wort
gewesen. Es gab im ganzen System **keine Stelle**, die den Zustand der
Gerätekonfiguration führte; `open_window` ist der *Zustand*, nicht die
*Einstellung*, und lauter `false` liest sich wie „es wurde nie gelüftet".

#386 hat den Lesepfad gebaut (die Antwort auf `0x46` landet in
`sensor_reading`). Diese Abfrage hat ihn benutzt.

## Was gesendet wurde

Nach Freigabe des Betreibers, Probelauf zuerst:

```
docker exec deploy-api-1 python -m heizung.scripts.fenstererkennung status \
    --nur 70b3d52dd3033389 --nur 70b3d52dd3033409 --nur 70b3d52dd30333cf
```

Drei `0x46`-Downlinks um **10:00:33Z**, je einzeln im Protokoll bestätigt.
Alle drei Geräte FW **4.4** (`0x45`/`0x46` greifen ab 4.2), alle
`health_state = healthy`.

## Das Ergebnis

| Gerät | Label | Zimmer | Antwort (UTC) | `enabled` | Delta | Dauer |
|---|---|---|---|---|---|---|
| 87 | 081 | 306 Bad | 10:09:39 | **false** | 1,0 °C | 10 min |
| 24 | 018 | 105 Schlafzimmer | 10:14:19 | **false** | 1,0 °C | 10 min |
| 85 | 079 | 306 Schlafzimmer | — | *keine Antwort* | | |

**Die Erkennung ist aus.** Nicht „unkonfiguriert und daher unbekannt",
sondern abgeschaltet, mit den Werksvorgaben 1,0 °C / 10 min im Gerät. Die
Schlussfolgerung vom 05.11. ist damit bestätigt — und sie ist jetzt eine
Messung.

**Zwei von drei Antworten reichen für diese Aussage.** Zwei Geräte in zwei
verschiedenen Zimmern, beide mit identischen Werksvorgaben, bei hausweit
null `true`-Meldungen. Ein drittes Gerät mit demselben Ergebnis hätte
nichts hinzugefügt.

## Warum 85 nicht geantwortet hat — und warum das kein Rätsel ist

Nicht „das Gerät ist stumm": es funkt im 10-Minuten-Takt weiter. Es fehlt
**ein einzelner Frame**.

```
fcnt 5703  09:56:03   setpoint 21,00
fcnt 5704  10:06:05   setpoint 21,00   <- hier wurde der Downlink abgeholt
     5705  ——         fehlt
fcnt 5706  10:16:15   setpoint 21,00
fcnt 5707  10:26:18   setpoint 21,00
```

Die Frame-Nummer **5705** fehlt, und der 10-Minuten-Takt ist dabei
ununterbrochen. Class A heißt: der Downlink wird im Empfangsfenster
**nach** einem Uplink zugestellt, die Antwort kommt als **eigener** Frame
danach. Genau dieser Frame ist verloren gegangen.

**Und bei diesem Gerät ist das der Normalfall.** Paketverlust über 24 h,
aus der `fcnt`-Spanne gegen die angekommenen Zeilen:

| Gerät | Zimmer | angekommen / erwartet | Verlust | RSSI | SNR |
|---|---|---|---|---|---|
| **85** (079) | **306 Schlafzimmer** | 131 / 147 | **10,9 %** | **-110 dBm** | **1,1 dB** |
| 87 (081) | 306 Bad | 142 / 146 | 2,7 % | -106 dBm | 5,2 dB |
| 86 (080) | 306 Kinderzimmer | 143 / 147 | 2,7 % | -106 dBm | 6,1 dB |
| 24 (018) | 105 Schlafzimmer | 143 / 147 | 2,7 % | -101 dBm | 9,1 dB |

**Gerät 85 verliert jeden zehnten Frame**, viermal so viel wie seine
beiden Nachbarn im selben Zimmer. Die Einzelmessungen von heute Morgen
lagen bei **-112 dBm** mit **negativem** SNR (0,2 / -0,5 / -1,0 / -1,5 dB)
— am Rand dessen, was sich noch demodulieren lässt.

Eine fehlende Antwort ist bei 10,9 % Verlust das **erwartete** Ergebnis,
kein Befund über die Fenstererkennung. Wer hier eine Gerätestörung
vermutet, sucht an der falschen Stelle.

## Die Folge für den Testplan (Sprint 23 T2)

**Gerät 85 ist der schlechteste Funkweg in Zimmer 306 — und 306 ist das
Testzimmer.** Der Grund für die Wahl war gut (ein Gast lüftet dort
sichtbar oft, 49 belegte Temperatureinbrüche in 30 Tagen). Der Funkweg war
nicht Teil der Wahl.

Bei 10,9 % Verlust mischt ein Erkennungstest auf 85 zwei Aussagen, die
sich nicht trennen lassen:

* die Erkennung hat **nicht ausgelöst**, oder
* sie hat ausgelöst und die **Meldung ist verloren**.

Zimmer 110 ist aus demselben Grund schon aus dem Testplan genommen worden
(Entscheidung vom 05.11., schlechter Funk). Dieselbe Begründung trifft auf
**85** zu, nicht auf das Zimmer: **86** (Kinderzimmer) und **87** (Bad)
liegen bei 2,7 % und sind brauchbar.

**Vorschlag, nicht entschieden:** der Test läuft auf **86**, nicht auf 85.
Das Kinderzimmer ist dem Schlafzimmer in Lage und Nutzung näher als das
Bad, und das Bad hat ohnehin das Fehlalarm-Problem (Dusche). Entscheidung
des Betreibers.

## Was diese Abfrage nicht beantwortet

* **Ob die Erkennung taugt.** Sie sagt, dass sie aus ist. Ob sie
  eingeschaltet im Hotelbetrieb brauchbar meldet, ist die Frage, für die
  der Testplan existiert (AE-47: Vicki-Erkennung und Server-Erkennung nie
  gleichzeitig scharf auf demselben Gerät).
* **Den Stand der übrigen ~100 Geräte.** Drei wurden gefragt. Hausweit
  null `true` bei 604.694 Zeilen `false` ist ein starkes Indiz, aber kein
  Beleg je Gerät. Ein Durchlauf über alle Geräte wäre ~100 Downlinks und
  gehört in eine eigene Freigabe.

## Querverweise

* `docs/status/2026-11-05-fenstererkennung-stand-lesbar.md` — #386, der
  Lesepfad
* AE-47 — der Grundsatz zur Koexistenz der beiden Erkennungen
* CLAUDE.md §5.27 — die Hardware-Realität: Erkennung ab Werk aus, und der
  Sensor sitzt am Heizkörper
* CLAUDE.md §5.68 — der Unterschied zwischen Schlussfolgerung und Messung,
  um den es in diesem Eintrag geht
