---
datum: 2026-11-15
thema: Die Mindestpause entfällt nach einem langen Lauf
pr: offen
---

# Eine Regel ohne den Fall, für den sie gilt

## Der Anlass

Ein Relais wird nie dauerhaft EIN gesetzt — EIN läuft über einen Timer
(S1), und der lief am 14./15.11. nach 30 Minuten ab, während der Raum
zwei bis drei Grad zu kalt war und der Regler jede Minute `ein` meldete.

Danach hielt die **Mindestpause** das Panel weitere zehn Minuten aus, und
zwar gerechnet ab dem **gemeldeten** AUS — das selbst schon neun Minuten
alt war, weil das Relais nur alle zehn Minuten meldet. Im Log sichtbar
als `'regler_grund': 'min_pause_600s'`.

Von zwanzig Minuten Totzeit je Zyklus war das die Hälfte. **Keine Minute
davon hat der Regler gewollt.**

## Warum die Regel umgestellt wird und nicht der Fall ausgenommen

Die Pause schützt vor schnellem Takten: EIN, AUS, EIN innerhalb weniger
Minuten belastet Kontakte und Gerät. Nach einer Laufzeit von mindestens
`min_lauf` gibt es nichts zu schützen — ein Wechsel je halbe Stunde ist
kein Takten. Die Pause bremste hier nicht den Regler, sondern den
Wächter, und damit etwas, das niemand entschieden hat.

Das war kein Fehler im Code. Es war eine Regel, die den Fall nicht
kannte, für den sie gilt.

**Die naheliegende Alternative scheitert an den Daten.** Man könnte nach
der *Ursache* des AUS fragen — unser Befehl oder der Timer?
`relay_reading.change_reason` ist aber in **allen** Zeilen des Hauses
`NULL`: eine Zustandsmeldung bei der Änderung (`0x54`) kommt bei uns
nicht an. Die Dauer der vorigen Phase steht dagegen in den Meldungen, und
sie ist das, was die Pause eigentlich meint.

## Was gebaut ist

`RelaisZustand` und `Zonenzustand` tragen `vorige_dauer`. Der Regler
lässt die Pause entfallen, wenn `vorige_dauer >= min_lauf`. Marke im
Trace bleibt `min_pause_600s`, wenn sie greift — sie fehlt einfach, wenn
sie entfällt.

**Die Dauer ist eine untere Schranke, und das ist Absicht.** Gerechnet
wird von der ersten bis zur letzten Meldung der Phase. Physisch lief das
Panel länger (die Meldungen kommen alle zehn Minuten). Von den beiden
Lesarten nimmt der Helfer die kleinere: eine Phase zu kurz zu schätzen
heisst, die Pause einmal zu oft anzuwenden — ein paar Minuten später
heizen. Zu lang zu schätzen heisst, sie einmal zu wenig anzuwenden, und
das ist der Fall, gegen den sie gebaut ist (§0 S5).

Kosten: eine dritte Abfrage auf `relay_reading` je Relais und Durchlauf,
über denselben Index, und nur wenn es überhaupt einen Wechsel gab.

## Wirkung, allein und mit `refresh`

**Allein** ist dieser PR der Rückfall: die Totzeit sinkt von zwanzig auf
etwa zehn Minuten (der Meldeverzug bleibt), der Einschaltanteil steigt
von 60–67 auf rund 75 Prozent.

**Mit `refresh`** greift er fast nie, weil der Timer dann nicht mehr
abläuft. Er bleibt trotzdem richtig — für den Fall, dass drei
Nachsetzungen in Folge verloren gehen.

Beide Wege sind unabhängig: dieser PR fasst `relais_ein_gesendet_at`
nicht an, und der REFRESH-PR fasst die Pause nicht an.

## Tests

7 neu in `test_mindestpause_nach_langem_lauf.py`: fünf am Regler allein,
zwei an der Datenbank (die Dauer aus den Meldungen, und der Orchestrator
Ende zu Ende mit den echten Meldezeiten im Zehn-Minuten-Raster).

Die Gegenproben sind der Kern: **nach kurzem Lauf bleibt die Pause** —
ohne diesen Test wäre „Pause immer entfallen lassen" genauso grün, und
das wäre eine Verschlechterung, die niemand bemerkt, bis ein Kontakt
hinüber ist. Dazu die Grenze (genau zehn Minuten reichen, eine Sekunde
weniger nicht), `None` als „wir wissen es nicht", und dass die
**Mindestlaufzeit** unberührt bleibt.

Alle 24 Bestandstests in `test_zweipunkt` laufen **ohne Änderung** weiter:
sie bauen `Zonenzustand` ohne `vorige_dauer`, und `None` heisst „Pause
gilt".

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 Pause gilt wieder immer (der Zustand vorher) | **3 rot** |
| M2 Pause entfällt immer | **4 rot** |
| M3 Grenze exklusiv statt inklusiv | **1 rot** |
| M4 `relay_state` liefert nie eine Dauer | **2 rot** |
| M5 obere statt untere Schranke | **1 rot** |
| M6 Mindestlaufzeit mit entfernt | **3 rot** |

## Läufe

* `ruff check`, `ruff format --check`, `mypy` (161 Dateien) grün.
* Backend-Suite **2010 passed, 45 skipped, 1 xfailed**.
* Kein Frontend berührt.
