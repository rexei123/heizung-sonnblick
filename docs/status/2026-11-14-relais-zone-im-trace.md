---
datum: 2026-11-14
thema: Nachzug zu #410 — der Grund im Trace greift bei der echten Bestückung
pr: offen
---

# Ein Test, der eine Lage prüft, die es im Haus nicht gibt

Nachzug zu **#410**, gefunden **nach** dem Deploy am Live-Stand.

## Der Fehler

#410 hat dem Engine-Trace einen genaueren Grund gegeben: steht in einer
Zone kein ansteuerbares Gerät, weil dort ein **Relais** hängt, soll dort
nicht `no_healthy_active_devices` stehen — das liest sich wie ein
Ausfall und ist keiner.

**Im Trace stand nach dem Deploy weiter der alte Text:**

```
{"detail": "no_healthy_active_devices", "zone_id": 299, "count_skipped": 0, "setpoint_c": 23}
```

Die Bedingung fragte `all(d.kind == RELAY)` — „sind **alle** Geräte der
Zone Relais". In beiden Relais-Zonen des Hauses hängt aber auch der
Fühler: **056** in der Rezeption, **027** in der Bar, beide auf „nur
messen". Die Antwort war damit `False`.

**Der Test hat es nicht gefunden, weil er eine Zone mit ausschließlich
einem Relais prüfte — und die gibt es im Haus nicht.** Dieselbe Klasse
wie beim Aufräum-Skript am Vormittag: ein grüner Lauf, der eine Lage
prüft, die nicht vorkommt (§5.55).

## Wirkung: nur Lesbarkeit

Kein Steuerpfad, kein Downlink, keine veränderte Zahl. `count_skipped`
ist mit #410 korrekt von 1 auf 0 gefallen, `setpoint_c` steht weiter im
Trace — das Relais wird nicht mehr angesteuert und regelt weiter. Die
Oberfläche zeigt `detail` gar nicht an (geprüft: kein Treffer in
`frontend/src` und `frontend/content`); die Zeichenkette steht nur im
Trace, den man per SQL liest.

**Kein Rückfall nötig**, deshalb ein eigener kleiner PR statt eines
Hotfix-Wegs.

## Was gebaut ist

`_zone_hat_nur_relais` → **`_zone_hat_relais`**, `all` → `any`, und der
Grund heißt jetzt `relais_zone_ohne_sollwertgeraet` (die alte Marke
`nur_relais_in_der_zone` wäre bei einem Fühler daneben selbst falsch
gewesen).

**`any` ist auch die richtige Frage.** Gefragt ist nicht, woraus die Zone
besteht, sondern **warum** nichts angesteuert wird — und sobald ein
Relais darin hängt, ist das die Antwort. Dass der Fühler daneben
ebenfalls übergangen wird, ist ein zweiter, genauso normaler Grund
(`measure_only`).

**Was dabei verdeckt wird:** hängt in einer Relais-Zone zusätzlich ein
*krankes* Thermostat, nennt der Trace die Relais-Zone und nicht das
kranke Gerät. Dessen Zustand hat seinen eigenen Weg — die Health-Achse,
die Kachel „Geräte online", den Melder der Relais-Zone. Hier geht es nur
um die Frage, ob das leere Ergebnis erklärt ist.

## Tests

Zwei neue, und der erste ist der, der gefehlt hat:

* **Relais + Fühler auf „nur messen"** — die Bestückung, die es wirklich
  gibt: beide Geräte werden übergangen, der Grund nennt die Relais-Zone,
  der Sollwert steht weiter im Trace.
* **Zone nur mit Fühler** — kein Relais, also der alte Text. Ohne diese
  Gegenprobe wäre `return True` genauso grün.

Dazu hat der Test der gemischten Zone (gesundes Thermostat + Relais) eine
genauere Aussage bekommen: `_zone_hat_relais` sagt dort **ja**, und der
Grund kommt trotzdem nicht zum Tragen, weil der leere Zweig nie erreicht
wird.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 zurück auf `all()` (der Fehler, der live stand) | **2 Tests rot** |
| M2 jede leere Zone gilt als Relais-Zone | **3 Tests rot** |
| M3 keine Zone gilt als Relais-Zone (alter Text bleibt) | **3 Tests rot** |
| M4 Grund im Trace wieder der alte | **2 Tests rot** |
| M5 Zonen-Sollwert nicht mehr im Trace | **2 Tests rot** |
| M6 Relais-Filter in der Geräteauswahl entfernt | **6 Tests rot** |

Sechs Proben, sechs rot. **M1 ist die wichtigste**: sie stellt genau den
Zustand her, der heute vier Stunden live war, und wird jetzt rot.

## Läufe

* `ruff check`, `ruff format --check`, `mypy` (161 Dateien) grün.
* `test_kein_sollwert_an_relais` + `test_fuehler_rolle`: **18 passed**.
* Kein Frontend-Code berührt.

## Was daraus für die nächsten Tests folgt

Beide Fehler des Tages haben dieselbe Form: ein Testaufbau, der eine
**mögliche**, aber nicht die **vorhandene** Lage beschreibt. Beim
Aufräum-Skript war der „laufende" Tag jung (und damit schon vom Datum
geschützt), hier war die Relais-Zone ohne Fühler.

Die Frage, die beide gefunden hätte: **„Gibt es diese Bestückung im Haus
— und wenn nein, warum prüfe ich sie?"** Für die zwei Relais-Zonen ist
die Antwort nachlesbar: ein Relais, ein Vicki auf „nur messen", und das
steht seit #403 im Handbuch.
