---
datum: 2026-11-15
thema: Die Zonen-Übersteuerung wirkte nicht auf Relais-Zonen
pr: offen
---

# Zwei Zahlen in einer Zeile, und die Steuerung hatte die falsche

Befund des Betreibers vom 15.11.2026, am Live-Stand belegt.

## Der Fehler

Der Barbereich war am 14.11. zweimal auf **23 Grad** übersteuert
(`frontend_bereich`, 13:05–17:05 und 17:10–21:10, dazu am 13.11.
17:46–21:46; angelegt von `verwaltung@hotel-sonnblick.at`). Zonenkarte
und Verlauf zeigten 23. Das Panel regelte das Totband um **22** aus —
den Sollwert des Raumtyps.

Die `hard_clamp`-Zeile von 14.11. 17:11 trägt **beide** Zahlen:

```
setpoint_out                            = 22.0
details->downlink_zone_status[0].zone_id = 302
details->downlink_zone_status[0].setpoint_c = 23
```

Der Relais-Regler las `latest_hard_clamp_setpoint_per_room` — also die
**Spalte**. Die Anzeige liest seit dem 31.10.2026
`latest_hard_clamp_zone_setpoints` — also das **JSON-Feld**. Dieselbe
Zeile, zwei Zahlen, und die Steuerung hatte die falsche (§5.53).

**Messbare Folge an der Bar, 14.11. 12:50–21:00:** Ist pendelte zwischen
21,47 und 22,18 — das ist genau das Totband um 22 (Einschaltschwelle
`soll − 0,5`, Ausschaltschwelle `soll + 0,3`). Bei Soll 23 hätte das
Panel durchgehend geheizt.

## Warum es ausgerechnet an einem Relais auffiel

Bei einem Thermostat trägt der Dispatch den Zonenwert selbst zum Gerät;
die Übersteuerung wirkt dort, ohne dass jemand den Sollwert nachlesen
müsste. Ein Relais hat kein Sollwert-Register — es wird geschaltet, und
dafür muss der Regler den Sollwert **lesen**.

**Seit #410 ist das der einzige Lesepfad.** Vorher stand das Relais
zusätzlich in der Geräteliste des Dispatch (und bekam sinnlose
`0x51`-Befehle, 51 Stück). Seit #410 ist es dort heraus, und damit hängt
der Sollwert einer Relais-Zone ausschließlich an dieser einen Zeile im
Regler. #410 hat den Fehler nicht verursacht — er war vorher derselbe —,
aber es hat den Weg beseitigt, auf dem man ihn hätte sehen können.

## Die Rezeption: derselbe Fehler, unsichtbar

Die Rezeption war am 14.11. **zur gleichen Zeit** auf 23 übersteuert
(Zone 299, dieselben zwei Zeitfenster). Dort ist nichts aufgefallen, und
zwar aus einem Grund, der die Lage schlimmer macht statt besser: der
Zimmerwert der Rezeption **ist** 23 (`vacant_setpoint` des Raumtyps
„Raum mit Exit"). Der Regler nahm die falsche Zahl und sie war
zufällig die richtige.

**Eine Übersteuerung der Rezeption auf 25 wäre genauso wirkungslos
gewesen.** Der Fehler war dort latent, nicht abwesend — und ohne den
Befund an der Bar hätte ihn niemand gefunden.

## Was gebaut ist

Ein gemeinsamer Helfer in `services/event_log.py`:

```python
@dataclass(frozen=True)
class SollStand:
    je_zimmer: dict[int, Decimal | None]
    je_zone: dict[int, dict[int, int]]

    def fuer(self, room_id: int, zone_id: int | None) -> Decimal | None: ...


async def lies_soll_stand(session, room_ids) -> SollStand: ...
```

`fuer` enthält den Rückfall, den es vorher gab — nur stand er an **drei**
Stellen als eigene Zeile, und an der vierten fehlte er. Umgestellt sind
alle vier Aufrufer:

| Stelle | vorher | jetzt |
|---|---|---|
| `tasks/relay_tasks` (Regler) | Zimmerwert, **kein** Zonenwert | `stand.fuer(room_id, zone.id)` |
| `api/v1/rooms` (Zimmerliste) | zwei Abfragen + Rückfall inline | `stand.fuer(room.id, zone_id)` |
| `api/v1/heating_zones` (Zonenkarte) | zwei Abfragen + Rückfall inline | `stand.fuer(zone.room_id, zone.id)` |
| `api/v1/heating_zones` (Liste) | dito | dito |

Damit ist Punkt (d) des Auftrags erfüllt: Regler und Anzeige nehmen
denselben Helfer, nicht zwei gleich aussehende Zeilen.

**Der Umbau der Anzeige ist verhaltensneutral** — 61 Bestandstests in
`test_soll_je_zone`, `test_zimmerliste_ist_soll`,
`test_sprint14e_hygiene_rest`, `test_relais_orchestrator_e2e`,
`test_api_rooms` und `test_referenzzone` laufen **ohne eine Änderung**
weiter (§5.47).

## Tests

`test_relais_nimmt_das_zonen_soll.py`, 10 Tests. Fünf prüfen den Helfer
allein, fünf den Regler an der Bestückung, die es im Haus gibt: Relais in
Betrieb, Vicki auf „nur messen", nicht buchbarer Raumtyp.

Der tragende Test ist die Lage vom 14.11.: Zimmerwert 22, Zonenwert 23,
Ist **22,1**. Dieselbe Zahl, zwei Entscheidungen — im Totband um 22 liegt
sie drin, unter der Einschaltschwelle von 23 (22,5) liegt sie drunter.

Dazu die Gegenproben, ohne die „immer einschalten" genauso grün wäre:

* beide Werte 22 → Totband, **kein** Befehl;
* Zeile ohne `setpoint_c` → Rückfall auf den Zimmerwert, und der Regler
  bleibt **nicht** stehen (`kein_engine_soll` wäre hier falsch);
* Zonenwert einer **fremden** Zone → wirkt nicht;
* Regler und Anzeigehelfer liefern dieselbe Zahl.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 Regler nimmt wieder den Zimmerwert (der Fehler, der live war) | **3 Tests rot** |
| M2 der Helfer ignoriert die Zone | **5 rot** |
| M3 kein Rückfall auf den Zimmerwert | **9 rot** |
| M4 irgendeine Zone des Zimmers zählt | **2 rot** |
| M5 Zimmerliste wieder auf den Zimmerwert | **1 rot** |
| M6 Zonenkarte wieder auf den Zimmerwert | **1 rot** |

M1 stellt genau den Zustand her, der seit der Inbetriebnahme der Relais
live war.

## Läufe

* `ruff check`, `ruff format --check`, `mypy` (161 Dateien) grün.
* Backend-Suite: **2003 passed, 45 skipped, 1 xfailed**.
* Kein Frontend-Code berührt (die Anzeige liest dasselbe Feld wie
  vorher).

## Was danach offen bleibt

Die **Heizleistung** der Rezeption ist davon unberührt: dort war der
Sollwert die ganze Zeit 23 und das Panel kam trotzdem nur auf 20,4–21,3.
Das ist der 30-Minuten-Deckel des Relais-Timers (eigener PR, REFRESH) und
nicht dieser Fehler. An der **Bar** ändert dieser PR die Lage
unmittelbar: eine Übersteuerung auf 23 heizt jetzt auch auf 23.
