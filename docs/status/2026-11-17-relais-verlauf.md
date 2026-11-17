---
datum: 2026-11-17
thema: Relais-Verlauf — dieselbe Rechnung, jetzt auch als Ansicht
pr: offen
---

# Relais-Verlauf

**Keine Migration.** Keine Server-Änderung, kein Funkbefehl. Alles in
diesem PR ist Lesen: zwei `GET`-Wege, eine Ansicht, ein Handbuch-Abschnitt.

## Der Auftrag und die Falle darin

Auftrag des Betreibers vom 16.11.2026: *„Relais-Verlauf (Ein/Aus mit
Ist/Soll, Heizdauer, kWh mit Rücksprung, Einschaltungen, Tabelle je Tag,
CSV, 24 h / 7 Tage / 30 Tage)."*

Die Zahlen, die dafür gebraucht werden, **gab es schon**: seit dem
15.11. rechnet `scripts/relais_auswertung` den Einschaltanteil je Stunde,
zeitgewichtet, mit Deckel gegen Meldungslücken und mit dem Sollwert aus
derselben `hard_clamp`-Zeile, aus der auch der Regler ihn liest. Fünfzehn
Tests halten das fest.

**Die Falle wäre gewesen, das zweimal zu rechnen.** Ein Endpunkt mit
eigener SQL hätte beim ersten Nachziehen eine zweite Wahrheit ergeben
(§5.53) — und zwar die schlechtere Art davon: zwei Zahlen, die *fast*
gleich sind, streiten länger als zwei, die sich offen widersprechen.

## Was geändert ist

| Stelle | Änderung |
|---|---|
| `services/relais_verlauf.py` | **neu.** Die Rechnung, aus dem Werkzeug herausgelöst — Namen, Signaturen und SQL unverändert |
| `scripts/relais_auswertung.py` | rechnet nicht mehr selbst; gibt die Namen weiter und druckt |
| `api/v1/relays.py` | `GET /devices/{id}/relay/history` und `…/history.csv` |
| `models/relay_reading.py` | Kopf: „Energiereports sind nicht im Umfang" stimmt nicht mehr |
| `lib/api/relais-verlauf.ts` | Zod-Spiegel, CSV-Pfad |
| `patterns/relay-history.tsx` | **neu.** Kennzahlen, Diagramm, Tageszeilen, CSV |
| `devices/[device_id]/page.tsx` | der Verlauf für Relais; die leeren Kacheln sind weg |
| `handbuch/seite-thermostate.md` | Abschnitt „Der Verlauf der Heizzone" |
| RUNBOOK §10bd | Hinweiskasten: die Ansicht ist der Alltagsweg, das Werkzeug bleibt |

### Die Verlagerung ist verhaltensneutral — und der Beleg sind die alten Tests

`test_relais_auswertung.py` ist **nicht angefasst**. Es ruft weiter
`werkzeug._bericht`, `werkzeug.Stunde`, `werkzeug._zonen_mit_relais` und
`werkzeug._soll_der_stunde`; das Werkzeug gibt diese Namen jetzt
ausdrücklich weiter. Fünfzehn Tests grün ohne eine geänderte Zeile — das
ist der Beleg, den §5.46/§5.47 verlangt, und er wäre weg, wenn ich die
Tests „nur schnell auf den neuen Pfad gezogen" hätte.

### Neu gerechnet wird nur, was es vorher nicht gab

**Heizdauer in Minuten.** Stand vorher nur in Prozent da. Die Minuten
kommen aus `ein_s` und **nicht** aus `ein_prozent × erfasste_minuten`:
der Prozentwert ist schon gerundet, und zwei Rundungen übereinander
ergeben bei kurzen Randstunden Minuten, die es nicht gab.

**Tageszeilen in Ortszeit.** Gebündelt wird über `zoneinfo`, nicht über
`date_trunc('day', …)`: in UTC beginnt der Tag des Hotels um 23:00 bzw.
22:00, und eine Tageszeile, die um 01:00 Ortszeit anfängt, beantwortet
keine Frage, die jemand gestellt hat (§5.65). Zwei Tests halten beide
Jahreshälften fest.

**Der Anteil der Tageszeile ist zeitgewichtet**, mit derselben
Begründung wie `anteil_gesamt`: am Rand des Fensters ist die erste Stunde
immer kurz, und ein schlichter Mittelwert über Stundenwerte wäre an
**jedem** Tag falsch. 100 % in sechs Minuten neben 60 % in sechzig sind
64 und nicht 80.

### Energie: ein Zähler, kein Messwert

`relay_reading.energy_wh` ist der Stand des Zählers im Gerät. Er läuft
bei 0xFFFFFFFF über, der Befehl `0x26` setzt ihn auf 0, ein Gerätetausch
beginnt bei 0. Gerechnet wird deshalb die Summe der **positiven**
Sprünge; ein negativer wird **gezählt und nicht addiert** und steht als
`ruecksprunge` in der Antwort und als Satz neben der kWh-Zahl.

Dasselbe Muster wie `services/paketverlust`, das Geräte-Neustarts neben
dem Verlust ausweist statt sie darin zu verstecken: **eine Zahl, die
kleiner ist als erwartet, muss erklärbar sein.**

**Der Fall ist in diesem Haus noch nie eingetreten.** Gemessen am
17.11.2026, beide Relais, ganze Historie: kein einziger Rücksprung. Der
Zähler hat sogar den Stromstoß beim Rejoin von 108 unverändert überlebt —
41683 Wh bei `fcnt` 582 der alten Sitzung, 41683 bei `fcnt` 1 danach,
41937 bei `fcnt` 3 (+254 Wh in rund zehn Minuten bei 1560 W, passt).

Trotzdem behandelt, weil das Gegenteil **still** falsch wäre: ein
Rücksprung ohne Behandlung macht aus einem Tagesverbrauch eine negative
Zahl oder — bei `sum` über gemischte Vorzeichen — eine zu kleine, und
niemand sieht, warum. Der DB-Test fährt den Fall mit einem Zähler, der
mitten im Fenster bei 0 neu anfängt.

**Wo die Energie innerhalb einer Meldungslücke liegt, wissen wir nicht.**
Der Sprung wird der Stunde der **früheren** Meldung zugerechnet, dieselbe
Richtung wie der Einschaltanteil. Über das Fenster ist die Summe richtig;
innerhalb einer Lücke ist die Verteilung eine Annahme — und die Lücke
steht in derselben Zeile (`erfasste_minuten`).

### Die Eimer sind immer Stunden

Auch im 24-Stunden-Fenster. Das Relais meldet alle zehn Minuten; ein
Zehn-Minuten-Eimer wäre damit **ein Zustand und keine Dauer**, und 144
davon sind keine Ansicht. Gezeichnet werden Stunden bei 24 h und 7 Tagen,
Tage bei 30 Tagen (720 Balken auf 600 Pixeln sind kein Bild mehr); die
Stundenzeilen bleiben in der CSV für alle drei Fenster erhalten.

### Die CSV ist für Excel gebaut

Semikolon, Dezimalkomma, CRLF, BOM. Jedes davon ist eine Entscheidung:
ohne Semikolon steht in deutschem Excel alles in Spalte A, mit Punkt wird
`20.00` zu Text, ohne BOM liest Excel die Datei als Windows-1252. Die
Seed-Liste im Repo (`Zimmerliste_seed.csv`) nutzt Komma und Punkt — sie
wird von einem Programm gelesen, nicht von einem Menschen geöffnet. Zwei
Formen, zwei Leser.

Jede Zeile trägt die Stunde **in Ortszeit mit Zonennamen und daneben in
UTC**. Die UTC-Spalte ist keine Vollständigkeit um ihrer selbst willen:
genau deren Fehlen hat am 16. und 17.11. zweimal eine falsche Meldung
erzeugt (§5.92).

## Die leeren Kacheln beim Relais

Vorgabe des Betreibers vom 16.11.2026. Betroffen sind **Temperatur,
Sollwert, Batterie, Signal, Ventilstellung, Fenster + Backplate,
Gerätegrenzen und Override** — bei einem Relais alle acht weg.

Der Grund ist nicht Platz. Fünf davon lesen `sensor_reading`, und ein
16ASPM hat in dieser Tabelle **keine einzige Zeile**: die Kacheln standen
dauerhaft auf `—`, und ein Strich liest sich wie „gerade kein Wert" und
nicht wie „diese Frage gibt es hier nicht". Batterie: das Relais hängt am
Netz. Gerätegrenzen: eine Vicki-Rücklesung (`0x15`). Override: ein
Drehring, den ein Relais nicht hat.

**Signal ist kein Verlust, sondern ein Umzug.** RSSI und SNR des Relais
stehen seit dem 16.11. in der Relais-Karte, aus `relay_reading` (#428).
Dieselbe Kachel hier hätte aus der falschen Tabelle gelesen.

**Der Paketverlust bleibt.** Er zählt Lücken im Frame-Zähler und gilt für
beide Gerätearten.

Dazu weggefallen: der Abschnitt „Verlauf der letzten 24 Stunden" und die
Tabelle „Letzte Einzelmessungen" — beide aus `sensor_reading`, beide bei
einem Relais leer, und beide hätten neben dem neuen Verlauf die Frage
aufgemacht, welcher der richtige ist.

## Mutationsproben

| Mutation | Erwartet rot | Ergebnis |
|---|---|---|
| Kalendertag per UTC statt `zoneinfo` | zwei Tests (Winter, Sommer) | rot |
| Tagesanteil als schlichter Mittelwert | `der_tagesanteil_wiegt_nach_erfasster_zeit` | rot |
| Lücke als 0 % mitzählen | zwei Tests | rot |
| Energie als schlichte Differenz (Rücksprung mitgerechnet) | DB-Test | rot |
| `energie_wh_gesamt` 0 statt `None` | `ohne_zaehlerstand_gibt_es_keine_energie` | rot |
| Heizdauer in Sekunden statt Minuten | zwei Tests | rot |
| CSV ohne Dezimalkomma | `die_csv_ist_fuer_excel_gebaut` | rot |
| Energie `null` als „0.0 kWh" anzeigen | e2e „leerer Zeitraum" | rot |
| Heizdauer ohne Stunden-Umrechnung | e2e „vier Kennzahlen" | rot |
| Rücksprung-Hinweis entfernt | e2e „mit Rücksprung die Warnung" | rot |
| CSV-Pfad ohne Zeitraum | e2e „Umschalter" | rot |
| Kacheln doch angezeigt | e2e „Kacheln … sind weg" | rot |

## Ein fremder Test, der nachgezogen werden musste

`sprint-17-hardware-status-drei-zustaende.spec.ts` prüft an einem Relais,
dass die Montage **nicht** abgefragt wird. Die Hülle aus `fixtures.ts`
lässt jeden Test umfallen, der eine ungemockte API-Anfrage auslöst — und
die Geräteseite holt für ein Relais jetzt zusätzlich den Verlauf. Eine
Route mehr im Mock, mit Begründung an derselben Stelle, an der schon die
Relais-Karte eine gebraucht hat.

**Das ist kein Rauschen, sondern der Zweck der Hülle:** ohne sie wäre die
Anfrage über den Next-Rewrite nach draußen gegangen — in die Produktion
dieses Hauses.

## Querverweise

§5.46/§5.47 (verhaltensneutrale Verlagerung), §5.53 (eine Wahrheit),
§5.65 (Ortszeit gegen UTC), §5.63 (Zod-Spiegel), §5.77 (veralteter
Hinweis), §5.92 (UTC neben der Ortszeit), §5.39 (Testleckage), RUNBOOK
§10bd (das Werkzeug), §10bc (Timer nachsetzen),
`docs/status/2026-11-15-relais-auswertung.md`,
`docs/status/2026-11-16-relais-signal.md`.
