---
datum: 2026-11-15
thema: Relais-Timer nachsetzen — die Strategie refresh wird betriebsfähig
pr: offen
---

# Jede EIN-Phase war 30 Minuten lang. Keine einzige länger.

## Der Befund

Der Betreiber meldete am 15.11., die Relais schalten aus, obwohl das Soll
nicht erreicht ist. Bestätigt, mit drei Belegen:

**Aus dem Worker-Log**, Zone 299 (Rezeption), neun Durchläufe
hintereinander:

```
'soll': '23.0', 'ist': '19.9', 'regler': 'ein', 'regler_grund': 'unter_ein_schwelle', 'gesendet': 0
```

Der Regler sagt jede Minute EIN, das Relais ist aus, es geht nichts
heraus.

**Aus den Phasendauern**, 41 Phasen am 14./15.11.:

| Relais | Phase | Anzahl | kürzeste | mittlere | längste |
|---|---|---|---|---|---|
| 108 | EIN | 24 | 29,8 min | 30,8 min | 40,1 min |
| 109 Panel | EIN | 17 | 20,0 min | 28,5 min | 30,2 min |

`relay_timer_expire_s` ist **1800**. Keine EIN-Phase ist länger als 30
Minuten — wäre es der Regler, müsste die Dauer mit dem Wärmebedarf
schwanken. An der Rezeption war der Raum dabei durchgehend 2 bis 3 K zu
kalt (Ist 20,4–21,3 bei Soll 23,0).

**Aus einem vollständigen Zyklus**, 108, auf die Sekunde:

| Ortszeit | Ereignis | Quelle |
|---|---|---|
| 06:58:13 | `0x57` abgesetzt, ChirpStack sendet in **einer Sekunde** über RX2 | ChirpStack-Log, `tx_ack` |
| 07:07:24 | Relais meldet EIN, 1568 W — 9 min später, nächster Keepalive | `relay_reading`, fcnt 427 |
| 07:28:13 | Timer läuft ab, Relais geht aus | gerechnet, 1800 s |
| 07:37:18 | Relais meldet AUS, 0 W — 9 min später | `relay_reading`, fcnt 430 |
| 07:48:16 | nächstes `0x57` — 11 min später | Worker-Log |

**20 Minuten aus, keine Minute davon vom Regler gewollt.** Davon neun aus
dem Meldeverzug (das Relais meldet alle zehn Minuten) und zehn aus der
Mindestpause, gerechnet ab dem **gemeldeten** AUS — also ab einem
Zeitpunkt, der schon neun Minuten alt war.

Einschaltanteil, zeitgewichtet: **60–67 %** an der Rezeption, 50–55 % an
der Bar. Ein 1,5-kW-Panel liefert damit effektiv 0,9 kW.

**Die Lieferung ist nicht das Problem:** Class C ist aktiv
(`enabled_class = C` an beiden Relais), und der Downlink geht in einer
Sekunde auf Luft. Das hatte ich zwischendurch anders vermutet — die
ChirpStack-Zeitstempel sind UTC, die Datenbankabfragen Ortszeit, und die
Stunde Unterschied sah wie Verzug aus. Sie ist keiner.

## Was dieser PR tut

`REFRESH` war seit Sprint 24 gebaut, je Gerät wählbar und
standardmäßig aus. Dieser PR macht sie **betriebsfähig** — er schaltet
sie nicht ein.

### Die Spalte, ohne die REFRESH einen Downlink alle zwei Minuten schickt

Der Orchestrator reichte `device.pending_since` als „letzter EIN-Befehl"
durch. Der wird gelöscht, sobald das Gerät den Zustand meldet
(`_loesche_offen` beim Grund `bestaetigt`). Danach sah der Wächter „kein
Vorbefehl" und setzte sofort nach.

**Gemessen, nicht geschätzt:** ein Lauf gegen die Datenbank vor der
Korrektur ergab **drei `0x57` in fünf Minuten** — eines alle zwei
Minuten statt alle fünf, also 30 je Stunde statt 12.

Neu ist `device.relais_ein_gesendet_at` (Migration 0040, additiv). Sie
trägt „wann wurde zuletzt eingeschaltet" und bleibt, wenn der offene
Stand mit der Bestätigung verschwindet. `pending_since` dafür
weiterzuverwenden hieße, einem Feld zwei Bedeutungen zu geben (§5.51) —
und die eine überschreibt die andere beim ersten Bestätigungs-Uplink.

### Der Weg zum Umschalten

`PATCH /api/v1/devices/{id}/relay/watchdog-strategy`, nur Admin, mit
`business_audit` (`RELAY_WATCHDOG_STRATEGY_SET`). Kein Downlink im
Aufruf: die Umschaltung wirkt beim nächsten Durchlauf, innerhalb einer
Minute.

Das Umschalten löscht `relais_ein_gesendet_at` — der Zeitpunkt gehört zur
alten Strategie, und der erste Durchlauf danach soll nachsetzen statt
gegen einen Zeitpunkt zu rechnen, den niemand mehr meint.

## Warum 24 bestehende Tests den Fehler nicht gefunden haben

`REFRESH` war ausschließlich in `test_relais_waechter` geprüft — als
**reine Funktion**, die den Zeitpunkt des letzten EIN-Befehls als
Argument bekommt. Die Funktion war die ganze Zeit richtig; falsch war,
was ihr übergeben wurde. Die Verdrahtung im Orchestrator hat kein Test je
gesehen.

Das ist die dritte Fundstelle derselben Klasse an diesem Wochenende
(§5.55): ein grüner Lauf, der eine Lage prüft, die so nicht vorkommt.
`test_relais_timer_nachsetzen.py` prüft deshalb **Abfolgen mit Zeit** —
fünf Durchläufe, sechzehn, sechzig —, nicht Einzelaufrufe.

## Tests

7 neue in `test_relais_timer_nachsetzen.py`, 5 neue in
`test_api_relays.py`.

* **Fünf Durchläufe, ein Downlink.** Der Test, der gefehlt hat.
* **Nach fünf Minuten das zweite** — ohne diese Gegenprobe wäre „nie
  wieder nachsetzen" genauso grün, und das wäre der schlimmere Fehler.
* **900 s, nicht 1800.** Der kürzere Timer ist der Sicherheitsgewinn
  dieser Strategie; dass nachgesetzt wird, darf die Rückfallzeit nicht
  verlängern.
* **Verlorene Nachsetzung** (die Frage des Betreibers): sechzehn
  Durchläufe, vier Nachsetzungen, davon drei innerhalb der Timer-Laufzeit
  — zwei dürfen verloren gehen.
* **Funklast als Test**: eine Stunde Beat, **12** Nachsetzungen. Ändert
  sich die Zahl, ist das eine Entscheidung und keine Nebenwirkung.
* **`expire_and_resend` bleibt unberührt**: dieselbe Lage, kein Befehl.
* **Ein Zwangs-AUS setzt den Zeitpunkt nicht** — sonst trüge die Spalte
  zwei Bedeutungen.

Die Simulation enthält die **Keepalives** des Relais. Ohne sie altert der
gemeldete Zustand im Lauf einer simulierten Stunde über das
Haltbarkeitsdatum (25 min), und der Wächter fragt `0xB1` statt
nachzusetzen — richtig, aber nicht das, was hier geprüft wird.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 wieder `pending_since` (der Fehler) | **3 rot** |
| M2 Zeitpunkt wird nicht gesetzt | **3 rot** |
| M3 auch das AUS setzt den Zeitpunkt | **1 rot** |
| M4 es wird nie nachgesetzt | **3 rot** |
| M5 REFRESH nimmt die lange Laufzeit | **4 rot** |
| M7 Umschalten löscht den Zeitpunkt nicht | **1 rot** |
| M8 Strategie als freier String | **1 rot** |

**M8 war beim ersten Versuch grün**, und das war ein Fund: neben dem
`Literal` im Schema steht seit Migration 0030 die Bedingung
`ck_device_watchdog_strategy` in der Datenbank, deren Verletzung der
zentrale Handler ebenfalls zu 422 macht. Ein Test, der nur den
Status-Code prüft, kann die beiden Schichten nicht unterscheiden und
belegt keine von beiden. Er prüft jetzt die **Schicht**.

## Funklast

Ein `0x57` sind 4 Byte Nutzlast, mit LoRaWAN-Rahmen 17 Byte auf Luft. Bei
RX2 (DR0, SF12, 125 kHz) sind das **1,32 s** — dieselbe Rechnung, die in
§10av mit 1319 ms steht. Zwölf je Stunde: **15,8 s** je Relais, **31,7 s**
für beide. Das Band um 869,525 MHz hat die höhere Erlaubnis; unter einem
Prozent liegt die Zahl in jedem Fall.

## Was dieser PR nicht tut

* **Er schaltet nichts um.** Die Vorgabe bleibt `expire_and_resend`; das
  Umschalten ist ein Handgriff mit Audit (§10bc).
* **Er fasst die Mindestpause nicht an.** Sie verdoppelt die Totzeit beim
  Timer-Ablauf, und das gehört in einen eigenen PR — der zugleich der
  Rückfall ist, falls `refresh` am Gerät Ärger macht.
* **Er beantwortet die Panel-Frage nicht.** Ob ein Panel die Rezeption
  auf 23 Grad hält, ist erst nach zwei bis drei Tagen mit durchlaufendem
  Panel messbar. Heute liefe die Messung gegen eine Steuerung, die ein
  Drittel der Zeit abschaltet.
