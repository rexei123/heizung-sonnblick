## Paketverlust aus Lücken im Frame-Zähler (2026-11-02)

**Keine Migration.** Ein Lese-Endpunkt, eine Kachel, ein Werkzeug,
RUNBOOK §10au.

### Warum

Relais 109 hatte am 01.11.2026 vor einem Neustart `fCnt` 8 und danach
`fCnt` 13 — **vier Frames fehlten, rund 30 %**, während das Gateway die
Vickis im selben Zeitraum normal hörte (552 `data_up`-Zeilen in zehn
Minuten). Diese Rechnung stand in keiner Oberfläche; sie wurde von Hand
aus den ChirpStack-Ereignissen gelesen.

**Es ist eine Messung, keine Schätzung.** Der LoRaWAN-Zähler läuft
lückenlos hoch, auch über die Frames, die niemand gehört hat. Wer die
Spanne kennt und die Zeilen zählt, kennt den Verlust.

### Was es jetzt gibt

| | |
|---|---|
| `GET /devices/{id}/paketverlust?stunden=24` | für Relais **und** Vickis, die Tabelle wählt das Backend nach der Geräteart |
| Kachel „Paketverlust" | auf der Geräteseite, neben „Signal" |
| `scripts.funkqualitaet` | Tabelle über ein Fenster, `--seit` in **Ortszeit**, liest nur |
| RUNBOOK §10au | die Auswertung am Endplatz, mit Entscheidungstabelle |

**Drei Unterscheidungen tragen die Anzeige:**

**„—" ist nicht 0 %.** Unter zwei Frames im Fenster gibt es keine Lücke,
die man sehen könnte. Eine Null wäre eine Behauptung über einen Funk,
der nicht gemessen wurde — dieselbe Unterscheidung wie bei der Batterie,
wo unter drei Messwerten „unbekannt" steht und nicht „in Ordnung"
(§5.73).

**Eine Rücksetzung des Zählers ist kein Verlust.** Nach einem Neustart
beginnt die Folge von vorn (§5.71); die Reihe wird dort geteilt und
beide Teile werden getrennt gerechnet. Ohne die Teilung wäre die Spanne
`4000 → 0` eine Lücke von viertausend Frames.

**Mehrfachempfang ist kein Verlust.** Zwei Gateways, ein Frame: derselbe
Zähler zählt einmal.

### Die Schwelle aus §5.71 gilt hier bewusst nicht

`is_reboot_frame` verlangt zusätzlich, dass der neue Zähler **klein**
ist. Das ist dort richtig — es geht um die Übernahme eines
Drehring-Werts, und die soll vorsichtig sein. Hier wird nur gerechnet:
**jedes** Sinken ist eine Rücksetzung, denn ein Zähler, der hochzählt,
kann nicht sinken. Mit der Schwelle wäre ein Neustart mit hohem
Anfangswert eine Lücke von Millionen Frames.

### Was die Zahl nicht sagt — und was wir dafür nicht speichern

**Die Richtung.** Ein verlorener Uplink kann am Funkweg, am Gateway oder
am Netz dahinter liegen.

**RSSI und SNR gibt es nur für Vickis, die Datenrate für niemanden.**
`sensor_reading` führt `rssi_dbm` und `snr_db`, `relay_reading` nicht;
die Datenrate speichern wir gar nicht. Für ein Relais stehen im Werkzeug
deshalb Striche — und der Weg zu den Zahlen steht daneben: **ChirpStack →
Device 109 → Metriken** führt RSSI, SNR und die Verteilung der
Datenraten je Stunde.

**Die Spalten nachzuziehen wäre eine additive Migration und ein eigener
PR.** Sie sammelt erst ab dem Einbau Daten und kommt für die Messung am
Endplatz zu spät — deshalb jetzt nicht, und deshalb hier benannt statt
verschwiegen.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| „—" durch `?? 0` ersetzt (ein Strich wird zu 0 %) | Playwright |
| Rücksetzung nicht als Teilung behandelt | Einheiten-Test (Lücke von 4000) |
| Doppelte als Empfang gezählt | Einheiten-Test |
| `--seit` als UTC gelesen | Einheiten-Test (eine Stunde Versatz) |

### Was CI gefunden hat und der lokale Lauf nicht

**Eine neue Anfrage auf einer geteilten Seite bringt jede Spec-Datei
dieser Seite zu Fall.** Die Kachel fragt auf **jeder** Geräteseite
`GET /devices/{id}/paketverlust`, und der Rückhalt in
`tests/e2e/fixtures.ts` lässt keine ungemockte API-Anfrage durch — mit
Absicht, denn ungemockt ginge sie über den Rewrite an heizung-test. Die
eigene Spec hatte ihren Mock, die neun anderen nicht: **23 Fehlschläge
in vier Dateien**, und lokal unsichtbar, weil ich nur die neue Datei
laufen ließ.

Behoben mit einem **Standard** in der Hülle, wie bei `/auth/me`: eine
Liste, die jede künftige Spec mitpflegen muss, läuft lautlos
auseinander. Die Grenze steht daneben und ist eng — einen Standard
bekommt nur, was **lesend** ist, auf **jeder** Seite einer Art vorkommt
und keinen Zustand trägt. Alles, was etwas ändert, bekommt keinen: ein
Test, der eine Mutation nicht mockt, soll umfallen.

**Die Lehre für mich ist die Reihenfolge**: nach einer Änderung an einer
geteilten Seite ist der **ganze** e2e-Lauf die Prüfung, nicht die neue
Datei. 312 Tests, 2,7 Minuten.

### Nebenbei nachgezogen

Der Handbuch-Artikel „Thermostate" behauptete, der Relais-Pfad sei
„vorbereitet, aber nicht in Betrieb" und die Messung T3.0 stehe aus.
Beides stimmte seit dem 01.11.2026 nicht mehr — §5.77 in der Oberfläche,
also an der Stelle, wo es der Betreiber liest. Der Absatz nennt jetzt
den geprüften Stand von 109 und das Ergebnis von T3.0.
