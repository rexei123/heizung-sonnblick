---
datum: 2026-11-14
thema: Die Engine schickt keinem Relais einen Sollwert
pr: offen
---

# 51 Befehle an zwei Geräte, die sie nicht kennen

Punkt **2d** des Auftrags vom 13.11.2026: *„Engine schickt keine
Sollwertbefehle (0x51) an Geräte vom Typ Relais. Relais bleibt in der
Zone."* **Steuerpfad**, Merge frühestens Montag nach dem Merge-Block.

## Der Befund, gemessen

Die Auswahl der angesteuerten Geräte (`engine_tasks._get_zone_devices`)
filterte `retired_at`, `health_state` und `measure_only`. Nach der
**Geräteart** fragte niemand — also bekam ein Relais in einer Zone
Sollwert-Downlinks wie ein Thermostat.

Produktion, Stand 14.11.2026 (`control_command` gegen `device`):

| Gerät | Zone | Befehle | an das Gateway | bestätigt | Sollwerte | erster | letzter |
|---|---|---|---|---|---|---|---|
| Relais **108** (Rezeption) | 299 | **16** | 16 | **0** | 17–23 °C | 12.11. 08:02 | 14.11. 06:03 |
| Relais **109 Panel** (Bar) | 302 | **35** | 35 | **0** | 15–23 °C | 01.11. 10:22 | 14.11. 06:55 |

**51 Befehle, 51 abgesetzte Downlinks, keine einzige Bestätigung.** Davon
**15 in den letzten 24 Stunden**. Nach Grund: 32 × `vacant_setpoint`,
19 × `night_setback`.

Ein 16ASPM ist ein Schalter. Er hat kein Sollwert-Register, kennt `0x51`
nicht und verwirft den Befehl. Jeder dieser Downlinks war Sendezeit, ein
Eintrag in der ChirpStack-Warteschlange und eine Zeile in
`control_command` — ohne jede Wirkung am Gerät.

## Was den Schaden begrenzt hat, und zwar zufällig

Der Abgleich (Sprint 20f) vergleicht den **gemeldeten** Sollwert des
Geräts mit dem gesendeten und sendet bei Abweichung nach. Ein Relais
meldet keinen Sollwert, also ist `ist_wert` immer `None`, und die
Nachsende-Schleife konnte nicht anlaufen. Ohne diese Eigenschaft hätte
jedes Relais zusätzlich die Abgleich-Wiederholungen bekommen — und nach
`MAX_VERSUCHE` eine Mail „Abgleich erschöpft" für ein Gerät, das nichts
falsch macht.

Das ist keine Entschärfung, auf die man sich verlassen sollte: sie hängt
an einem `None`, nicht an einer Prüfung.

## Was gebaut ist

**Eine Zeile, an der Stelle, die diese Frage schon stellt.**
`_get_zone_devices` filtert jetzt zusätzlich `kind != RELAY` — dieselbe
Zeile, die `measure_only` filtert, und aus demselben Grund: „welche
Geräte gehören zur Zone" und „welche Geräte bekommen einen Sollwert" sind
zwei Fragen. Die erste beantwortet `get_active_devices_for_zone` und
bleibt unverändert.

**Das Relais bleibt in der Zone** (Vorgabe des Betreibers). Es gehört
dorthin: die Zone ist der Ort, an dem Soll, Ist und Schaltzustand
zusammenkommen. Der Orchestrator findet es dort, der Melder aus #403
ebenso, und die Anzeige zeigt das Zimmer mit seiner Heizung. Nur
**angesteuert** wird es nicht.

**Der Grund im Trace nennt jetzt das Relais.** Eine Zone, in der
ausschließlich Relais hängen, liefert eine leere Geräteliste — und dafür
stand im Trace `no_healthy_active_devices`. Das behauptet einen Ausfall,
während ein gesundes, in Betrieb genommenes Relais darin hängt und jede
Minute geregelt wird. Wer das im Engine-Panel der Rezeption liest, sucht
einen Fehler, den es nicht gibt (§5.79). Jetzt steht dort
`nur_relais_in_der_zone`.

Die Unterscheidung kostet **eine** zusätzliche Abfrage, und nur in dem
Zweig, in dem die Geräteliste leer ist — im Haus betrifft das die zwei
Relais-Zonen.

## Was ausdrücklich nicht geändert wurde

**Die 51 bestehenden Zeilen bleiben stehen** (Vorgabe des Betreibers).
Sie sind der Beleg für den Befund; gelöscht wäre nicht mehr
nachvollziehbar, was zwischen dem 01. und dem 14.11. gesendet wurde.

**Der Sollwert der Zone landet weiter im Trace.** Das ist die wichtigere
Hälfte dieser Änderung, und sie hat ihren eigenen Test: der Orchestrator
liest den Sollwert nicht aus `control_command`, sondern aus dem
`HARD_CLAMP`-Trace (`latest_hard_clamp_setpoint_per_room`). Stünde dort
nichts, sagte er `kein_engine_soll` und schaltete gar nicht — aus einem
Panel, das einen Befehl zu viel bekam, wäre eines geworden, das keinen
mehr bekommt.

## Ein Fund daneben, nicht in diesem PR

`services/device_service.get_pool_devices` filtert `heating_zone_id IS
NULL` und `retired_at IS NULL` — **nicht** die Geräteart. Der
Batch-Eingangstest (`pair_devices inbound-test --all-pool`) nimmt diese
Liste und schickt jedem Gerät zwei Sollwerte und eine Firmware-Abfrage.
**Läge ein Relais im Pool, bekäme es dabei `0x51`** und fiele mit
`timeout` durch, weil es keinen Sollwert melden kann.

**Heute ist das nicht scharf:** beide Relais hängen in Zonen, der Pool
enthält keines (geprüft am 14.11., Abfrage unten). Der Fund gehört
trotzdem notiert, weil die nächste Lieferung Relais in den Pool legt.

Nicht hier mitgefixt, weil es eine andere Stelle und ein anderes Thema
ist (§5.1): `get_pool_devices` beliefert auch die Pool-Liste in der
Oberfläche, und dort sollen Relais **erscheinen**. Der Filter gehört
also in die Geräteauswahl des Eingangstests, nicht in den Helfer.

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT id, label, kind, heating_zone_id FROM device WHERE kind = 'relay' ORDER BY id;"
```

## Handbuch: ein überholter Vermerk, vier Zeilen lang (§5.77)

Im Artikel „Heizlogik" stand bis heute:

> Für die Infrarot-Heizkörper ist ein Relais-Pfad **vorbereitet, aber
> nicht in Betrieb** […] es ist kein Relais montiert, und es wird keines
> geschaltet.

Und in der Liste der Versandregeln: *„Ein Relais hätte einen eigenen Weg
— siehe oben, es ist keines in Betrieb."*

Beides war seit dem 01.11.2026 falsch. Das ist genau die Klasse aus
§5.77: ein Vermerk, der einmal richtig war, von einem späteren Sprint
überholt wurde und seither wie ein Befund gelesen wird — hier in der
**Oberfläche**, also dort, wo der Betreiber hinsieht.

Der Abschnitt ist neu geschrieben: ein Relais ist ein Schalter, es
bekommt keinen Sollwert, eingeschaltet wird immer mit Zeitbegrenzung, bei
fehlendem oder altem Istwert wird abgeschaltet, und bei ausbleibender
Zustandsmeldung wird gefragt statt geraten. **Ohne Zahlen** (Regel 13:
Schwellen sind pro Haus verstellbar), mit `stand: 2026-11-14`.

Der letzte Punkt beschreibt das Verhalten aus #409 — deshalb darf dieser
PR erst **nach** #409 gemergt werden, sonst steht im Handbuch eine
Zusicherung, die das Programm noch nicht gibt.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 Relais-Filter entfernt | **5 Tests rot** |
| M2 statt Relais werden Thermostate gefiltert | **23 Tests rot** |
| M3 Grund im Trace unverändert (`no_healthy_active_devices`) | **1 Test rot** |
| M4 leere Zone gilt als Relais-Zone (`all()` auf leerer Liste) | **2 Tests rot** |
| M5 gemischte Zone gilt als Relais-Zone (`any` statt `all`) | **1 Test rot** |
| M6 Zonen-Sollwert nicht mehr im Trace | **1 Test rot** |

Sechs Proben, sechs rot. M6 ist die Gegenprobe zur Gefahr dieser
Änderung: ohne den Sollwert im Trace schaltet das Relais nicht mehr.

## Läufe

* Backend **1925 passed, 45 skipped, 1 xfailed**.
* `ruff check`, `ruff format --check` (339 Dateien), `mypy` (160 Dateien) grün.
* Handbuch-Spiegel (`test_handbuch_spiegel.py`) grün.
* Kein Frontend-Code berührt (nur ein Handbuch-Artikel).

## Was offen bleibt

**Die Gerätekarte des Relais zeigt weiter einen alten Sollwert-Befehl.**
Es kommen keine neuen Zeilen mehr, also bleibt die letzte vom 14.11.
06:55 stehen — und sieht aus wie der aktuelle Stand. Gehört in den
Anzeige-PR (Punkt 4), zusammen mit „Relais-Zustand unbekannt — letzte
Meldung HH:MM".

**Der Filter des Eingangstests** (Fund oben), als eigener kleiner PR.
