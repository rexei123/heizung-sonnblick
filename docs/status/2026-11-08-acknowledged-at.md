---
datum: 2026-11-08
sprint: 25
thema: T2 — acknowledged_at füllen, reine Buchführung
pr: 400
---

# Sprint 25 T2 — die Spalte, die seit Sprint 9.2 immer leer war

## Der Befund

`control_command.acknowledged_at` existiert seit Sprint 9.2 und wurde
**nie gesetzt**. Jeder Befehl in der Datenbank sieht damit aus wie „nie
angekommen" — auch die, die angekommen sind. Eine Spalte, die immer leer
ist, ist keine fehlende Information, sie ist eine falsche.

## Was als Quittung gilt

Ein Uplink, der den **gesendeten** Wert meldet: der Sollwert im
Periodenbericht (`0x81`) oder die ausdrückliche Antwort (`0x52`). Beides
läuft durch dieselbe Funktion, weil es dieselbe Aussage ist — *das Gerät
steht auf dem Wert, den wir geschickt haben.*

Der `0x52`-Weg brauchte einen eigenen Aufruf: der Reply-Zweig überspringt
den Reading-Insert, die Quittung kommt dort also nicht von selbst mit.
Ohne ihn wäre genau der Frame unbeachtet, der am deutlichsten
„angekommen" sagt — und der Kommentar im Reply-Zweig sagt seit Sprint
20f-b, dass `0x52` nur noch „die Bestätigung des eigenen Downlinks" ist.

## Vier Bedingungen, und jede hat einen Grund

| Bedingung | Warum |
|---|---|
| `target_setpoint = gemeldet` | sonst quittiert jeder Uplink irgendeinen Befehl |
| `acknowledged_at IS NULL` | sonst wandert der Zeitstempel mit jedem Periodenbericht nach vorn, und die Dauer wäre immer zehn Minuten |
| `sent_to_gateway_at <= gemeldet_um` | ein Uplink kann keinen Befehl bestätigen, der nach ihm hinausging |
| `ORDER BY sent_to_gateway_at DESC LIMIT 1` | der **jüngste** offene Befehl, Festlegung des Betreibers |

**Die Folge der letzten Zeile ist gewollt:** stehen zwei Befehle mit
demselben Wert offen, bleibt der ältere offen. Er wurde vom jüngeren
überholt, und niemand hat ihn je einzeln bestätigt. Das als „auch
quittiert" zu schreiben wäre eine Annahme statt einer Beobachtung.

## Class A — deshalb dauert es

Ein Vicki holt den Downlink erst im Fenster nach einem eigenen Uplink ab;
die Bestätigung trägt dann die **übernächste** Meldung. Zwischen Befehl
und Quittung liegen damit regelmäßig zehn bis zwanzig Minuten. Ein
`acknowledged_at` eine Minute nach `sent_to_gateway_at` wäre der
verdächtige Fall, nicht der normale.

Der Test fährt genau diesen Ablauf: Befehl auf 21 um 11:00, nächster
Uplink 11:02 meldet noch **18** → keine Quittung, übernächster 11:12
meldet 21 → Quittung mit dessen Zeit.

## Kein Tor

Die Vorgabe lautet „kein Tor, keine Logik hängt daran". Das ist hier mehr
als eine Zusage: der Aufruf im Keepalive-Pfad steht in einem `try`, und
ein `SQLAlchemyError` kostet eine Protokollzeile statt des Messwerts, der
gerade geschrieben wird. Ein verlorener Eintrag in einer Diagnose-Spalte
kostet nichts; ein verlorener Messwert kostet die Regelung.

Der letzte Test der Datei hält genau das fest — Quittung absichtlich
kaputt, Messwert muss trotzdem in der Tabelle stehen.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Zeitgrenze entfernt | **1 Test rot** |
| ältester statt jüngster offener Befehl | **1 Test rot** |
| „offen"-Bedingung entfernt | **1 Test rot** |
| Wertgleichheit entfernt | **1 Test rot** |
| Fang um die Quittung entfernt (sie wird zum Tor) | **1 Test rot** |
| `sent_to_gateway_at IS NOT NULL` entfernt | **grün — Redundanz, siehe unten** |
| Aufruf im Reply-Zweig entfernt | **zuerst grün — echte Lücke, geschlossen** |

**Die sechste Probe ist Redundanz, keine Lücke.** `NULL <= gemeldet_um`
ist in SQL nicht wahr, ein nie gesendeter Befehl fällt also schon an der
Zeitgrenze heraus. Die Bedingung bleibt trotzdem stehen, weil sie die
Absicht **sagt** — wer die Abfrage liest, soll „nur gesendete Befehle"
nicht aus dem NULL-Verhalten eines Vergleichs erschließen müssen. Als
Kommentar am Code festgehalten.

**Die siebte war eine echte Lücke.** Mein Test rief
`_handle_setpoint_reply_quittung` direkt auf und sagte damit nichts
darüber, ob die Schleife ihn auch aufruft. Dieselbe Lücke haben die
beiden älteren Reply-Handler (`0x04`, `0x46`) — nur hat dort nie jemand
die Probe gemacht. Geschlossen mit einem Verdrahtungs-Test, der die
Quelle von `_consume_loop` liest. Er belegt die Reihenfolge nicht und
nicht, dass der Zweig erreicht wird; er fällt genau dann, wenn jemand den
Aufruf entfernt oder umbenennt. `_consume_loop` für einen besseren Test
zu zerlegen wäre ein Eingriff in den Eingangspfad und gehört nicht in
einen Buchführungs-PR (§5.1).

## Läufe

**1882 passed, 45 skipped** — `TEST_DATABASE_URL` gesetzt, die DB-Tests
sind gelaufen. Kein Frontend-Code berührt.

## Ein Test fiel, der nicht zu dieser Aufgabe gehört

`test_funkempfang::test_lies_funkempfang_zaehlt_nur_das_fenster` fiel mit
`6 == 4`. **Nicht durch diese Änderung** — der Test fällt auch, wenn man
nur ihn allein laufen lässt, ohne eine Zeile von mir im Lauf.

Ursache: `lies_funkempfang` zählt `sensor_reading` **hausweit**. Nach
jedem Suite-Lauf bleiben zwei Zeilen zurück, deren `time` eine Minute vor
ihrer Entstehung liegt; läuft der Funkempfang-Test innerhalb von zehn
Minuten erneut, zählt er sie mit. Die Geräte dazu haben kein Etikett,
keine Zone und eine nackte uuid4 als DevEUI.

Nach Löschen der zwei Zeilen: **1882 passed**. §0.1 Pflicht-Stop 4 — ein
fremdes Test-Leck wird gemeldet, nicht nebenbei behoben. Als eigene
Aufgabe notiert, samt der neun bereits ausgeschlossenen Dateien.

In der CI tritt es nicht auf: dort ist die Datenbank je Lauf frisch.
