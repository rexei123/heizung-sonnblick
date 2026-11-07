# Der Funk-Wächter: ein Melder auf die Wirkung, nicht auf die Mechanik

**Stand:** 05.11.2026 · Sprint 25 **T6**

## Warum es ihn gibt

Am 04.11. kam das Gateway nach der Stromtrennung **4 dB schlechter**
zurück, hausweit. Gefunden wurde das **einen Tag später und zufällig**,
bei der Prüfung einer anderen Vermutung.

**Jeder Mechanismus war grün.** Die Geräte standen auf
`health_state = healthy`, weil sie ja noch sendeten. Die Batterien waren
in Ordnung. Die Meldungsmenge fiel hausweit nur von 605 auf 580 je
Stunde — fünf Prozent, unauffällig. Und trotzdem ist ein Gerät von 144
Meldungen am Tag auf **6** gefallen, weil es die Reserve nicht hatte.

Das ist §5.76 wörtlich: wer die Mechanik prüft, findet solche Ketten
nie. Dieser Wächter prüft die **Wirkung** — wie gut das Haus empfangen
wird.

## Was gebaut ist

| | |
|---|---|
| Messfenster | letzte **2 Stunden** |
| Grundlinie | Mittel der **7 Tage**, die **24 Stunden vor jetzt enden** |
| Schwelle | mehr als **2,0 dB** darunter |
| Takt | **stündlich**, `crontab(minute=50)` |
| Ausgabe | `business_audit` (bedingungslos) **und** Mail (gebremst) |
| Eingriff in die Steuerung | **keiner**, rein lesend |

Dateien: `services/funk_waechter.py`, `tasks/funk_tasks.py`, sechs
Settings, eine neue Bremsen-Kennung in `alert_throttle`, RUNBOOK §10m.

## Die zwei Entscheidungen, auf die es ankommt

### Die Grundlinie läuft nach — sonst verdünnt sie sich selbst

Der naheliegende Entwurf vergleicht gegen ein gleitendes
Mehrtagesmittel. **Das funktioniert nicht**, und es ist beim Entwerfen
der Abfrage aufgefallen, nicht beim Nachdenken: gegen das 7-Tage-Mittel
gerechnet sagte der Befund vom 04.11. einen Tag später **„im Rahmen" bei
−1,8 dB**, weil die 25 Stunden Störung im Mittel steckten.

Ein Melder, der nach zwei Tagen von selbst verstummt, überwacht nichts
(§5.79). Die Grundlinie endet deshalb 24 Stunden vor jetzt.

**Die Grenze bleibt, und sie steht im RUNBOOK:** hält eine Störung
länger als sieben Tage an, wandert sie trotzdem hinein und der Alarm
verstummt — nicht weil es behoben ist, sondern weil der schlechte
Zustand zur Normalität geworden ist. Der Alarm meldet eine **Änderung**;
die Frage „wo stehen wir" beantwortet der Befehl aus §10ay Schritt 6.
Zwei Aufgaben, zwei Werkzeuge.

### Gerechnet wird über die Schnittmenge, und über Geräte-Mittel

**Schnittmenge:** nur Geräte, die in **beiden** Fenstern vorkommen. Sonst
wäre das Hausmittel durch den Bestand manipulierbar — kommen fünf Geräte
in gut versorgten Zimmern dazu, *steigt* das Mittel und verdeckt eine
Verschlechterung.

**Geräte-Mittel, nicht Zeilen-Mittel:** ein Gerät, das öfter sendet, soll
nicht schwerer zählen. Sonst verschiebt ein **stilles** Gerät — also
genau das Symptom — das Ergebnis in die falsche Richtung, weil das laute,
gut versorgte Gerät mehr Gewicht bekommt.

Beide Entscheidungen haben einen eigenen Test, und beide fallen in der
Mutationsprobe.

## Was er bewusst nicht tut

* **Keine Alarme je Gerät.** 107 einzelne Melder wären Lärm, und ein
  einzelnes schwaches Gerät ist kein Vorfall.
* **Kein Alarm bei zu wenigen Daten.** Unter 100 Meldungen von 40
  Geräten lautet das Urteil **„unbekannt"**, nicht „Warnung" — ein
  Melder, der beim Ausfall des Messwegs anschlägt, meldet seinen eigenen
  Ausfall (§5.79, dieselbe Haltung wie `BATTERY_MIN_SAMPLES`).
* **Keine Kachel im Dashboard.** Begründung unten.
* **Kein Eingriff in die Steuerung.**

## Warum keine Dashboard-Kachel in diesem PR

**Zuerst eine Korrektur an meiner eigenen Begründung.** Ich hatte
geschrieben, die Kachel sei zu teuer, weil sie eine Aggregation über
sieben Tage je Seitenaufruf bräuchte. **Dann habe ich es gemessen, und
das Argument hält nicht:**

```
EXPLAIN (ANALYZE, BUFFERS) … → actual time=45.763..49.214 ms
Chunks excluded during startup: 1
Parallel Index Scan using _hyper_1_208_chunk_sensor_reading_time_idx
Buffers: shared hit=12652 read=57
```

**49 ms auf der echten Anlage** (609.000 Zeilen, 103 Geräte in der
Schnittmenge). TimescaleDB schließt die nicht betroffenen Chunks aus —
nur **9 von 190** liegen im Zeitraum — und greift über den
**Zeit-Index jedes Chunks**, nicht über `ix_sensor_reading_device_time`.
Fast alles kommt aus dem Cache.

AE-72 hat für die Batterie-Stufen **22 ms je Request akzeptiert**. 49 ms
sind in derselben Größenordnung, und die Zahl wächst **nicht** mit der
Aufbewahrungsdauer, weil das Zeitfenster fest bei acht Tagen liegt — nur
mit der Gerätezahl und dem Meldungstakt.

**Die Kachel wäre also bezahlbar.** Mein Kostenargument war zu stark
formuliert, und es gehört korrigiert statt stehen gelassen (§5.77 in
eigener Sache).

**Was bleibt, ist der Umfang.** Eine Kachel heißt: Feld im Dashboard-
Schema, Aggregat-Abfrage, Komponente im Frontend, Handbuch-Artikel
(Golden Rule 13). Das ist ein zweites Thema in einem PR, der schon eines
hat (§5.1) — und die **bessere** Form ist ohnehin nicht die
Live-Abfrage, sondern dass der stündliche Lauf sein Urteil ablegt und die
Kachel es liest: dann kostet sie **null** statt 49 ms, und die Zahl im
Dashboard ist dieselbe, die der Alarm gesehen hat. Zwei Anzeigen, die
dieselbe Frage verschieden beantworten, wären eine zweite Wahrheit.

Bis dahin ist die Spur der `business_audit`-Eintrag und die Mail —
dieselbe Form wie bei `OCCUPANCY_IMPORT_STALE` und
`ENGINE_ABGLEICH_ERSCHOEPFT`, die beide ebenfalls keine Kachel haben.
Die Aufgabe steht im Sprint-25-Brief.

## Antworten auf die Rückfragen vor dem Merge

**Startet `api` ohne einen einzigen neuen `.env`-Eintrag? Ja.** Alle
sechs Settings haben Code-Vorgaben; nachgewiesen mit einer
`Settings()`-Instanz in einer Umgebung, in der keine der sechs Variablen
gesetzt ist:

```
funk_warn_delta_db           = Decimal('2.0')
funk_grundlinie_tage         = 7
funk_fenster_stunden         = 2
funk_min_meldungen           = 100
funk_min_geraete             = 40
funk_mail_sperre_stunden     = 24
```

**Es ist also keine Zeile einzutragen.** Der Block in beiden
`.env.example` ist Dokumentation, keine Voraussetzung.

**Die Mail geht an `global_config.alert_email`** — dieselbe Adresse wie
die beiden bestehenden Alarme, in der Oberfläche unter *Einstellungen /
Hotel* als **E-Mail für Warnungen**. Kein neuer Empfänger, kein neues
Feld. Ist sie leer, entsteht der Audit-Eintrag trotzdem und nur die Mail
entfällt — mit einer Protokollzeile, die das sagt.

## Die Mail kommt einmal am Tag, nicht einmal je Episode

Vorgabe war „einmal pro Episode". Gebaut ist eine **Sperrzeit von 24
Stunden**, und die Abweichung ist Absicht:

Eine strikte Einmal-Regel braucht einen gespeicherten Episodenzustand.
Fällt ein Lauf aus — Worker weg, Redis weg —, bleibt der Zustand stehen
und die Meldung kommt **nie**. Eine Sperrzeit kann höchstens zu viel
melden, und das ist die bessere Richtung. Vorbild ist
`TTL_IMPORT_STALE_S`.

Wer wirklich nur eine Meldung je Vorgang will, setzt
`FUNK_MAIL_SPERRE_STUNDEN` hoch — dann ist sie faktisch einmalig, ohne
einen Zustand einzuführen, der stumm hängen bleiben kann.

## Prüfung

* **Gegenprobe gegen den 04.11., wie verlangt:**
  `test_gegenprobe_04_11_loest_um_09_uhr_aus` baut die gemessenen
  Verhältnisse nach — Grundlinie 8,7, Messfenster 6,3, 50 Geräte — und
  verlangt eine Warnung bei **−2,4 dB**. Dazu die reine Urteilsprobe mit
  denselben Zahlen.
* **Die Schwelle ist inklusiv**, mit eigenem Test: am 04.11. lagen
  Stundenwerte bei genau −2,0, und eine exklusive Schwelle hätte dort
  geschwiegen.
* Volle Backend-Suite gegen echtes Postgres: **1847 passed, 45 skipped,
  1 xfailed**. `ruff check`, `ruff format --check`, `mypy src` grün.
* **Mutationsproben, vier, alle beißen:**

| Mutation | Folge |
|---|---|
| Mindestmenge entfernt | **2** Tests fallen |
| Schwelle exklusiv (`<` statt `<=`) | 1 Test fällt |
| über Zeilen statt Geräte-Mittel gemittelt | 1 Test fällt |
| Grundlinie ohne Nachlauf (`GRUNDLINIE_ABSTAND_H = 0`) | **3** Tests fallen, darunter die Gegenprobe |

Die letzte ist die aussagekräftigste: ohne Nachlauf steckt die Störung
in ihrer eigenen Vergleichsgröße, und genau der Befund vom 04.11. geht
verloren.

## Was nicht geprüft ist

Ob die **Schwelle** im Betrieb die richtige ist. Sie ist an **einem**
Ereignis kalibriert — 2,0 dB trennt die beobachteten −2,0 bis −2,4 vom
normalen Schwanken unter 0,5. Eine Reihe von Ereignissen gibt es nicht,
und bis es sie gibt, ist die Zahl ein Anhalt und kein Gesetz. Sie steht
deshalb in den Settings und nicht im Code.

Und ob eine Mail tatsächlich ankommt: der Versandweg ist der
bestehende (§10m), geprüft ist hier nur, dass er aufgerufen und sein
Ergebnis festgehalten wird.
