---
datum: 2026-11-13
thema: Block 2b — die Bestätigungsfrist kommt aus dem Meldeintervall
pr: offen
---

# Eine Minute warten auf eine Antwort, die erst nach zehn kommen kann

Vorgabe des Betreibers vom 13.11.2026, Block 2b. **Steuerpfad** — Merge
Montag 16.11. früh.

## Der Befund

Relais 108 am 12.11.2026: **zehn Downlinks für vier Schaltungen**.

| Schaltung | gesendet | bestätigt |
|---|---|---|
| AUS | 09:26, 09:27 | 09:27:52 |
| EIN | 09:38, 09:39 | 09:47:51 |
| AUS | 09:58, 09:59, 10:01 | 10:07:56 |
| EIN | 10:31, 10:33, 10:36 | 10:37:43 |

Dazu um **10:06** ein Alarm im Protokoll:

```
ERROR relais ohne bestaetigung device_id=109 ziel_ein=False versuche=3
```

für ein Relais, das zu diesem Zeitpunkt **bereits aus war** — die Meldung
dazu kam um 10:07:56.

## Die Ursache war eine Zahl aus dem falschen Vorgang

Die Frist stand auf **60 Sekunden**, und die Begründung im Code lautete:
Class C, der Downlink ist sofort beim Gerät, eine Minute ist reichlich.

Das stimmt und beantwortet eine andere Frage. **Die Zustellung ist nicht
die Bestätigung.** Ein 16ASPM meldet seinen Zustand nur im eigenen Takt —
gemessen alle **600 Sekunden** (107 lückenlose Meldungen in der Nacht vom
12. auf den 13.11., Abstände 588 bis 612 s). Die Frist lag damit um den
Faktor zehn unter dem frühesten Zeitpunkt, an dem eine Bestätigung
überhaupt eintreffen kann.

Der Wächter hat also **planmäßig** wiederholt und **planmäßig** Alarm
geschlagen. Ein Melder, der bei jedem zweiten Vorgang Fehlalarm gibt,
wird nach einer Woche überlesen (§5.79).

## Was geändert ist

Zwei Einstellungen, ihre Verknüpfung ist Code:

| Einstellung | Vorgabe | Begründung |
|---|---|---|
| `relay_meldeintervall_s` | **600** | gemessen, nicht aus dem Geräteprofil — dort steht `uplink_interval = 3600`, und das ist ChirpStacks Offline-Erwartung |
| `relay_bestaetigungs_zuschlag_s` | **120** | 20 %, weit außerhalb der gemessenen Streuung von 588–612 s |

`relay_bestaetigungs_frist_s` ist **entfernt**. Die Frist wird in
`waechter_schwellen()` gerechnet. Damit kann niemand das Intervall
verstellen und die Frist vergessen (§5.53).

**Warum das Intervall eine eigene Einstellung ist und keine Konstante:**
Block 2c braucht dieselbe Zahl für „ab wann gilt ein gemeldeter
Schaltzustand als veraltet". Eine Zahl, zwei Verbraucher.

Ein Validator weist eine Kappung (`relay_backoff_max_s`) unterhalb der
ersten Frist ab — sonst wäre die Verdopplung wirkungslos **und** die
Frist zu kurz, also genau der alte Zustand, nur stumm hergestellt.

## Die unbequeme Folge: der Alarm kommt später

Die Leiter mit den neuen Vorgaben, gerechnet ab dem letzten **Senden**:

| Tick | Frist | was passiert |
|---|---|---|
| 0 | — | Versuch 1 |
| +12 min | 720 s | Versuch 2 |
| +24 min | 1440 s | Versuch 3 |
| +30 min | 1800 s (Kappung) | **Alarm**, kein Downlink |
| +30 min | 1800 s | Versuch 4, gedrosselt |

Der Alarm liegt damit bei **rund einer Stunde** statt bei sieben Minuten.

**Schneller ist nicht zu haben, ohne wieder zu raten.** Unter zwei
Meldeintervallen ist „keine Bestätigung" keine Aussage über das Gerät,
sondern eine über unsere Geduld. Wer den Alarm früher will, senkt
`relay_max_versuche` auf 2 — dann liegt er bei 36 Minuten, zum Preis
eines Versuchs weniger. Das ist eine Entscheidung des Betreibers und
steht im PR-Text zur Wahl.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Frist zurück auf feste 60 s | **8 Tests rot** |
| Zuschlag fällt weg (Frist genau das Intervall) | **4 Tests rot** |
| Meldeintervall-Vorgabe auf 60 s | **5 Tests rot** |
| Validator Kappung/Frist entfernt | **1 Test rot** |
| Validator Meldeintervall > 0 entfernt | **1 Test rot** |

Die zweite Probe ist die interessanteste: eine Frist von **genau** 600 s
wäre plausibel und falsch. Der gemessene Abstand geht bis 612 s, also
liefe sie bei etwa der Hälfte der Vorgänge wenige Sekunden zu früh ab —
und erzeugte eine Wiederholung, die nichts bewirkt. Der Test prüft gegen
den **gemessenen** Höchstabstand, nicht gegen den Mittelwert.

## Läufe

* Backend **1926 passed, 45 skipped** — `TEST_DATABASE_URL` gesetzt.
* **385 e2e-Tests grün** mit `--workers=1`.
* `ruff`, `ruff format`, `mypy`, `tsc`, `eslint` grün.
* Ein Bestandstest musste nachgezogen werden:
  `test_ohne_bestaetigung_nicht_jede_minute_ein_downlink` prüfte elf
  Minuten im Minutentakt und erwartete drei Versuche. Mit der längeren
  Frist ist es **einer** — und das ist der Zweck. Der Test prüft jetzt
  zwei Horizonte: elf Minuten (ein Versuch, kein Alarm) und neunzig
  Minuten (vier Versuche, genau ein Alarm), mit der Leiter als Tabelle
  im Docstring.

## Bekannter Fremdbefund

`test_funkempfang::test_lies_funkempfang_zaehlt_nur_das_fenster` fällt
lokal weiter mit `6 == 4`. **Nicht durch diese Änderung** — der Test
fällt auch allein, ohne eine Zeile von hier im Lauf. Es ist das in #400
gemeldete Test-Leck: `lies_funkempfang` zählt `sensor_reading`
hausweit, und nach jedem Suite-Lauf bleiben zwei Zeilen zurück. Nach dem
Löschen der zwei Zeilen: grün. In der CI tritt es nicht auf (frische DB
je Lauf). Als eigene Aufgabe notiert, §0.1 Pflicht-Stop 4.
