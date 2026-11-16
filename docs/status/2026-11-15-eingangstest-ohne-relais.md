---
datum: 2026-11-15
thema: Der Eingangstest prüft keine Relais
pr: offen
---

# Ein latenter Fehler, als solcher gefunden

## Der Befund

`_cmd_inbound_test` läuft über `get_pool_devices()`. Dieser Helfer
filtert nach Zone (`heating_zone_id IS NULL`) und Lebenszyklus
(`retired_at IS NULL`) — **nicht nach Geräteart**.

Der Eingangstest setzt Sollwerte (`0x51`) und beurteilt das Gerät daran,
ob es sie meldet und ob sich das Ventil bewegt. Ein Relais hat **kein
Sollwert-Register und kein Ventil**: der Befehl geht ins Leere, die
Bestätigung bleibt aus, und das Gerät fällt durch eine Prüfung, die es
nicht betrifft.

**Heute tritt der Fehler nicht auf.** Im Pool liegt kein Relais; die
beiden im Haus sind zugeordnet und in Betrieb. Beim nächsten
Reserve-Relais wäre er einer — und zwar derselbe, den #410 im Engine-Pfad
beseitigt hat: 51 sinnlose `0x51` an Geräte ohne Sollwert.

## Wo gefiltert wird, und warum nicht in der Leseschicht

**Im Lauf, nicht in `get_pool_devices`.** Die Pool-Liste soll das Relais
**zeigen**: wer ein Reserve-Relais einlagert, will es dort sehen. Ein
Filter in der Leseschicht würde es unsichtbar machen und damit ein
zweites Problem schaffen, um das erste zu lösen.

Die Mutationsprobe M3 setzt genau diesen falschen Filter und macht zwei
Tests rot — der Unterschied ist also geprüft und nicht nur behauptet.

**Nach der `--devices`-Auswahl, nicht davor.** Wer ein Relais in
`--devices` nennt, soll hören, dass es übersprungen wird — nicht „nicht
im Pool gefunden". Das Relais *ist* im Pool; es ist nur nicht
eingangsprüfbar, und eine Meldung, die etwas anderes behauptet, schickt
jemanden auf die falsche Suche.

## Zwei Wege, zwei Antworten

| Weg | Verhalten |
|---|---|
| `inbound-test --all-pool` | Relais werden **übersprungen**, mit Namen und Grund genannt |
| `test <device>` auf ein Relais | **Abbruch** mit Exit 1 |

Beim Einzeltest ist das Gerät ausdrücklich genannt. Ein Lauf, der es
still übergeht und 0 zurückgibt, sähe wie ein bestandener Test aus
(§5.55). Der Rückgabewert ist hier die Aussage, nicht die Meldung.

Dazu zeigt `list-pool` jetzt die **Art** des Geräts. Wer aus der Liste
nicht sieht, dass dort ein Relais liegt, sucht den Grund für das
Überspringen im Lauf statt im Gerät.

## Tests

5 neu. Die tragenden prüfen die **Liste, die der Lauf bekommt** — nicht
eine Ausgabe, denn eine Zeile im Protokoll beweist nicht, dass kein
Befehl hinausging. Dazu die Gegenprobe (ein Vicki läuft weiter), der
Abbruch beim Einzeltest, und dass `get_pool_devices` das Relais weiter
liefert.

Die Tests patchen `pair_devices.SessionLocal` auf die Test-Session — das
Muster aus `test_pair_devices_cli`. Der erste Versuch ließ den Befehl
seine eigene Session öffnen, und zwei gleichzeitige Operationen auf einer
Verbindung endeten in „another operation is in progress": derselbe
Nachbarschaftsschaden wie §5.14, nur über den Pool statt über den Loop.

| Probe | Ergebnis |
|---|---|
| M1 kein Relais-Filter im Batch (der Zustand vorher) | **2 rot** |
| M2 Einzeltest bricht nicht ab | **1 rot** |
| M3 Filter in `get_pool_devices` (das falsche Mittel) | **2 rot** |

## Läufe

* `ruff`, `mypy` (161 Dateien) grün.
* Backend-Suite **2008 passed, 45 skipped, 1 xfailed** — nach dem
  Aufräumen der lokalen Test-Datenbank, siehe unten.

## Nebenbefund: das Leck in der Test-Datenbank hat eine Adresse

`test_funkempfang::test_lies_funkempfang_zaehlt_nur_das_fenster` war im
Gesamtlauf rot (6 Meldungen statt 4). Ursache sind **Geräte 48 und 49**,
die seit einem früheren Lauf ohne Label und ohne Zone in der lokalen
Test-Datenbank liegen und frische Messwerte bekommen.

Die Adresse dazu, neu: `tests/test_api_rooms.py`, Fixture
`zimmer_mit_thermostat`. Sie committet ein `Device` und räumt am Ende
`room` und `room_type` weg — **das Gerät nicht**. Da
`device.heating_zone_id` nullable ist, löscht die CASCADE vom Zimmer die
Zone und setzt das Gerät nur auf `NULL`: jeder Lauf hinterlässt ein
Thermostat im Pool. Dieselbe Mechanik, die der Kommentar in
`test_relais_orchestrator_e2e` beschreibt (§5.39).

**In CI ist das unsichtbar** (frische Datenbank je Lauf), lokal kippt es
einen fremden Test. Gehört in den Hygiene-PR, nicht hierher — ein Thema,
ein PR (§5.1).
