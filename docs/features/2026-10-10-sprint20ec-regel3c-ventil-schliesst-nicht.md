# Sprint 20e-c — Regel 3c „Ventil schließt nicht"

**Stand:** 2026-10-10 · **Vorschlag des Hoteliers**, hier bewertet und mit
Aufwand versehen · **zur Freigabe, keine Umsetzung vor Entscheidung**

---

## 0. Der Anlass: AK 1b ist halb erfüllt

Kesseltest am 10.10.2026 (Kessel an ab ca. 10:10, Prüfung 13:36):

| Gerät | Raum | Soll | Befund |
|---|---|---|---|
| **027/110** | 26,1 °C | 18 | **gemeldet** — „7,2 K über Soll und 3,7 K über vergleichbaren Zimmern (Median 21,5 °C)", steht in `/devices` ganz oben |
| **100/405** | 24,6 °C | 18 | **nicht gemeldet** — ca. 3,1 K über dem Median, die Schwelle liegt bei 3,5 |

Beide klemmen offen. Einer wird gefunden, einer nicht.

**Die Ursache ist nicht die Schwelle, sondern die Jahreszeit.** Im Herbst
hebt die Eigenwärme der heizenden Zimmer den Median auf ~21,5 °C; der
Abstand eines defekten Zimmers dazu schrumpft entsprechend. Im Winter läge
der Median näher am Sollwert (~18 °C), und 100/405 wäre mit ~6 K klar
darüber. 100/405 liegt zusätzlich im 4. OG und flacht ab — der Heizkörper
wird weniger heiß als bei 027.

**Regel 3b erkennt also im Herbst nur die stark heizenden Defekte.** Das ist
kein Fehler der Regel — sie tut genau, was sie soll, und die
Saisonabhängigkeit war der Preis dafür, die 14 Fehlalarme loszuwerden. Aber
es ist eine Lücke, und sie ist jetzt gemessen statt vermutet.

**Die Schwelle zu senken ist nicht der Ausweg.** 3,5 K steht dort, weil der
knappste bekannte Fehlalarm bei genau 3,0 lag (T0 vom 08.10.). Senken holt
die Fehlalarme zurück und verliert, was 20e-b gewonnen hat.

---

## 1. Der Vorschlag

> **Regel 3c:** Gerät meldet `valve_position >= 80 %` **und**
> `temperature >= setpoint + 2 K`, `bool_and` über dasselbe 2-h-Fenster,
> Mindest-Stichprobe wie 3/3b.

**Die Physik dahinter ist stark, und das ist der entscheidende Punkt.** Ein
funktionierendes Vicki, dessen Zimmer über dem eigenen Sollwert liegt,
**schließt**. Meldet es stattdessen über zwei Stunden durchgehend ein weit
offenes Ventil, dann arbeitet seine Regelung nicht — Funk und Sensor sind in
Ordnung, der Stellantrieb nicht.

**Und: das Kriterium braucht keine Referenz.** Es vergleicht das Gerät mit
**sich selbst** (seiner eigenen Zielvorgabe und seiner eigenen gemeldeten
Stellung), nicht mit dem Haus. Wetter, Jahreszeit und Belegung fallen damit
heraus — kein Median, keine Rückfallkette, keine Mindestzahl an
Referenzzimmern.

Das ist eine andere Klasse von Melder als 3b, nicht eine bessere Variante
davon. CLAUDE.md §5.84 sagt, ein Melder gegen eine Umwelt brauche ein
relatives Kriterium; 3c steht **nicht** gegen die Umwelt, sondern gegen eine
Zusicherung des Geräts. Deshalb darf es absolut sein.

---

## 2. Was die Daten hergeben — und was nicht

### `valve_position` ist da, und was es bedeutet

Der Codec rechnet `valveOpenness = round((1 - motorPosition / motorRange) * 100)`
(`mclimate-vicki.js:148`), mit Clamp gegen Positionen über dem Bereich.
Persistiert als `sensor_reading.valve_position` (`SmallInteger`, 0..100).

**Der Wert ist die Motorstellung, nicht die Ventilstellung.** Das schneidet
den Geltungsbereich von 3c zu, und zwar genau dort, wo der Hotelier die
Abgrenzung schon gezogen hat:

| Lage | Gerät meldet | Wer findet es |
|---|---|---|
| Motor fährt nicht zu (Antrieb defekt, Stift greift nicht) | **offen** | **3c** |
| Kopf abgenommen, letzte Stellung war offen | offen (veraltet) | 3c, zufällig |
| Kopf abgenommen, letzte Stellung war zu | **zu** | nur 3b |
| Ventil klemmt mechanisch, Motor meldet erfolgreich zu | **zu** | nur 3b |

**3c und 3b ergänzen sich also tatsächlich**, und keines ersetzt das andere.
Das gehört in die Doku, damit niemand 3b nach ein paar ruhigen Wochen für
überflüssig hält.

### `calibration_failed` ist da — und sollte 3c ausnehmen

`sensor_reading.calibration_failed` wird seit Sprint 20f persistiert. Ein
Gerät, dessen Kalibrierung gescheitert ist, hat **keinen gültigen
`motorRange`** — `valve_position` ist dann eine Zahl ohne Bedeutung, und
„80 % offen" sagt nichts.

**Vorschlag: `calibration_failed` im Fenster schließt 3c aus.** Nicht weil
der Fall harmlos wäre, sondern weil er einen **anderen** Handgriff hat
(rekalibrieren, §10e) und weil ein Hinweis, der auf einem bedeutungslosen
Messwert steht, der Anfang der nächsten Alarmmüdigkeit ist.

Offene Frage für T0: **wie viele Geräte melden das überhaupt?** Wenn es
viele sind, ist der Ausschluss teuer und wir brauchen stattdessen einen
eigenen Hinweis dafür.

### `lowMotorConsumption` ist **nicht** da

Der Hotelier nennt den Flag als Bild der beiden Fälle, und der Codec
dekodiert ihn (`mclimate-vicki.js:175`, `status7 & 0x02`). **Im Backend
existiert er nicht:** keine Spalte in `sensor_reading`, kein Leser, keine
Anzeige. Die einzige Fundstelle im Code ist ein Kommentar in
`battery_health.py`.

Der Flag, der an 027 und 100 beobachtet wurde, stand also in der
ChirpStack-Oberfläche (Events-Tab) — **nicht in unseren Daten.** Wer 3c auf
ihn stellen will, braucht vorher eine Migration.

**Empfehlung: nicht als Bedingung, sondern als Diagnose-Information** —
und als eigene, kleine Aufgabe (T7, optional). Zwei Gründe:

1. **Zwei Beobachtungen sind keine Grundlage für eine Bedingung.** Die
   Bedeutung des Bits ist herstellerdefiniert, und §5.21 ist genau diese
   Lesson: Hardware-Annahmen defensiv interpretieren. Als Bedingung würde
   ein Melder von einem Bit abhängen, dessen Verhalten wir an zwei Geräten
   kennen.
2. **Im Hinweistext ist er dagegen wertvoll und harmlos.** „Motor läuft ohne
   Widerstand" ist für den Hausmeister eine andere Auskunft als „Ventil
   meldet offen" — es sagt ihm, dass er den Stift prüfen soll und nicht das
   Gerät.

---

## 3. Abgrenzung zu Regel 3 und 3b

### Gegen Regel 3: schließen sich aus

Regel 3 verlangt `setpoint >= temperature + 3` **und** Ventil zu; 3c
verlangt `temperature >= setpoint + 2` **und** Ventil weit offen. Beide
Richtungen sind unvereinbar, solange beide Deltas positiv sind — dasselbe
Argument wie bei 3 gegen 3b, und ein Test hält es fest.

### Gegen Regel 3b: **überschneiden sich, und das braucht eine Vorrangregel**

Ein Zimmer, das 6 K über dem Sollwert und 4 K über dem Median liegt und
dessen Gerät 90 % offen meldet, erfüllt **beide**. Heute braucht
`valve_verdicts` keine Vorrangregel, und der Modul-Docstring sagt das
ausdrücklich. **Mit 3c ändert sich das**, und damit wird aus der Reihenfolge
der `elif`-Zweige eine stille Entscheidung — genau das, was §5.23 und der
bestehende Test `beide Regeln koennen nicht zugleich zutreffen` verhindern
sollen.

**Vorschlag: 3c gewinnt.** Begründung: es ist die **spezifischere** Aussage.
3b sagt „dieses Zimmer ist zu warm, vermutlich ist der Kopf ab"; 3c sagt
„dieses Gerät meldet offen, während es schließen müsste". Der zweite Satz
nennt den Mechanismus und erspart dem Hausmeister einen Diagnoseschritt.

Die Vorrangregel gehört **ausgesprochen** in den Modul-Docstring und in
einen Test, der sie an einem Gerät prüft, das beide Bedingungen erfüllt.

---

## 4. Grenzfälle

| # | Fall | Wirkung | Antwort |
|---|---|---|---|
| **G1** | **Sollwert fällt gerade** (Nachtabsenkung, Abreise → 18 °C). Das Zimmer ist über dem neuen Sollwert, das Ventil noch offen | 3c würde kurz nach jeder Absenkung anschlagen | `bool_and` über 2 h trägt das: ein funktionierendes Vicki schließt innerhalb von Minuten, und ein einziger Messwert unter 80 % fällt das Urteil. **In T0 zu prüfen**, weil es die Hauptquelle für Fehlalarme wäre |
| **G2** | **Frostschutz / offenes Fenster.** Die Engine senkt den Sollwert stark, das Zimmer liegt weit darüber | Jedes Gerät, das offen meldet, erfüllt 3c | Fachlich richtig (ein Ventil, das bei Frostschutz offen bleibt, ist ein Defekt) — aber es überlagert sich mit Layer 4. **In T0 zählen**, und falls häufig: `open_window` im Fenster schließt 3c aus |
| **G3** | **Kalibrierung gescheitert** | `valve_position` ist bedeutungslos | Ausschluss, siehe §2 |
| **G4** | **Gerät im Pool, keiner Zone zugeordnet** | Kein Sollwert-Bezug? | Nein: `setpoint` kommt vom Gerät selbst, nicht aus der Engine. 3c funktioniert auch ohne Zuordnung — und soll es, denn ein defekter Antrieb fällt am Tisch genauso auf |
| **G5** | **`motorRange` falsch gemessen**, aber Kalibrierung formal erfolgreich | `valve_position` systematisch verschoben | Nicht abfangbar und nicht zu verwechseln mit G3. Bekannte Grenze; der Hinweistext nennt die Rekalibrierung als ersten Handgriff, und das deckt diesen Fall mit ab |

**Warum der Sollwert vom Gerät kommt und nicht aus der Engine.** Das ist eine
Entscheidung, nicht eine Bequemlichkeit: 3c prüft die Regelung **des
Geräts** gegen **dessen eigene** Zielvorgabe. Nähme man den
Engine-Sollwert, würde ein nicht angekommener Downlink wie ein defekter
Antrieb aussehen — zwei verschiedene Fehler unter einem Hinweis, und der
Handgriff wäre je nach Ursache ein anderer.

---

## 5. Eigene Kachel, eigenes Etikett — oder unter „Ventil prüfen"?

Die Frage des Hoteliers, und sie ist die, bei der man es falsch machen kann.

| Variante | Dafür | Dagegen |
|---|---|---|
| **A: unter „Ventil prüfen"** (zu `valve_stuck_count`) | Keine dritte Kachel, ein Etikett weniger zu lernen. Erster Handgriff ist bei beiden das Rekalibrieren | **Ein Etikett für zwei entgegengesetzte Symptome.** „Ventil prüfen" hängt heute an „Zimmer wird nicht warm"; 3c heißt „Zimmer wird zu warm". Der Hausmeister liest das Etikett und weiß nicht mehr, was er erwartet — damit sagt es nichts |
| **B: unter „Zimmer zu warm"** (zu `room_too_warm_count`) | Dieselbe Wirkung (Energie läuft gegen das Fenster), derselbe Handgriff aus §10t | Die Kachel zählte dann zwei **verschiedene Empfindlichkeiten** (5 K + relativ gegen 2 K + offen). Wer sie beobachtet, kann einen Anstieg nicht mehr deuten. Und „zu warm" ist bei 2 K über dem Sollwert eine Übertreibung |
| **C: eigener Zustand, eigenes Etikett, eigene Kachel** ✅ | Die Aussage ist spezifischer als beide: Funk arbeitet, Regelung nicht. Das ist nennbar und erspart einen Diagnoseschritt | Eine dritte Ventil-Kachel. §5.79 warnt vor zu vielen Meldern |

**Empfehlung: C**, mit zwei Bedingungen daran:

1. **Das Etikett nennt den Befund, nicht die Vermutung:**
   „**Ventil schließt nicht**", rot (die Wirkung ist Energieverlust, wie bei
   3b). Hinweistext: „Zimmer liegt X K über Soll, Gerät meldet trotzdem
   Y % offen. Ventil fährt nicht zu oder ist nicht kalibriert."
2. **Der Handgriff ist derselbe wie bei „Zimmer zu warm"** (RUNBOOK §10t)
   und wird dort gemeinsam geführt, nicht als dritter Abschnitt. Drei
   Etiketten sind vertretbar, drei Anleitungen für denselben Gang ins
   Zimmer nicht.

**Und der Ausweg, falls C sich als zu viel erweist:** zeigt T0 (oder der
Betrieb nach vier Wochen), dass 3c und 3b fast immer dieselben Geräte
treffen, werden sie zusammengelegt. Das ist dann eine Messung und keine
Geschmacksfrage — und der Weg dahin ist kürzer als zurück.

---

## 6. T0 zuerst: messen, bevor gebaut wird

**Das ist der wichtigste Punkt dieses Briefs.** 20e-b hat gezeigt, was eine
Messung vor dem Bauen wert ist: die Vorgabe 3,5 K statt 3,0 stammt daraus,
und ohne sie hätte die Schwelle auf einem bekannten Fall gelegen.

Dasselbe hier. Die Zahlen 80 % und 2 K sind plausibel und **nicht gemessen**.
Vor einer Zeile Code:

**SSH (heizung-test, root), bei laufendem Kessel:**

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml exec db psql -U heizung -d heizung -c "
WITH fenster AS (
  SELECT d.label AS geraet, r.number AS zimmer, r.status,
         sr.temperature, sr.setpoint, sr.valve_position,
         sr.calibration_failed, sr.open_window
  FROM sensor_reading sr
  JOIN device d        ON d.id = sr.device_id AND d.retired_at IS NULL
  JOIN heating_zone hz ON hz.id = d.heating_zone_id
  JOIN room r          ON r.id = hz.room_id
  WHERE sr.time >= now() - interval '2 hours'
    AND sr.temperature IS NOT NULL AND sr.setpoint IS NOT NULL
)
SELECT geraet, zimmer, status,
       count(*) AS n,
       round(min(temperature - setpoint), 1) AS ueber_soll,
       min(valve_position)                   AS ventil_min,
       max(valve_position)                   AS ventil_max,
       bool_or(calibration_failed)           AS kalib_fehler,
       bool_or(open_window)                  AS fenster_offen,
       bool_and(valve_position >= 80 AND temperature >= setpoint + 2.0) AS regel3c
FROM fenster
GROUP BY 1,2,3
HAVING count(*) >= 6
   AND bool_and(valve_position >= 80 AND temperature >= setpoint + 2.0)
ORDER BY ueber_soll DESC;"
```

Die Abfrage rechnet die vorgeschlagenen Werte nach (80 % / 2,0 K / 6
Messwerte) und liest keine Einstellungen.

**Was die Ausgabe entscheidet:**

* **Zwei Zeilen, nämlich 027 und 100** → der Vorschlag trifft, Werte
  bleiben, Umsetzung wie unten.
* **Deutlich mehr Zeilen** → die Spalten `kalib_fehler` und `fenster_offen`
  sagen, ob G2/G3 die Ursache sind. Dann kommen die Ausschlüsse **vor** den
  Hinweis, nicht danach.
* **027 und 100 fehlen** → `ventil_min`/`ventil_max` zeigen, was sie
  wirklich melden. Liegt es unter 80, ist die Schwelle zu hoch gegriffen,
  und `ventil_min` sagt, wo sie läge.
* **Eine zweite Messung bei Sollwert-Absenkung** (abends nach 22:00, wenn
  die Nachtabsenkung greift) prüft G1 — die Hauptquelle für Fehlalarme.

**Ohne diese zwei Messungen keine Umsetzung.** Pflicht-Stop.

---

## 7. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T0** | Beide Messungen aus §6 (Kessel an; Nachtabsenkung), Schwellen und Ausschlüsse festlegen. **Pflicht-Stop** | 0,5 h |
| **T1** | `valve_health`: dritte Bedingung im **selben** `GROUP BY` (`bool_and` über Stellung und Abstand), neuer Zustand `ventil_schliesst_nicht`, Ausschlüsse nach T0 | 1,5 h |
| **T2** | Vorrangregel 3c vor 3b, im Docstring ausgesprochen und per Test an einem Gerät geprüft, das beide erfüllt. Dazu der Test „3 und 3c schließen sich aus" | 0,75 h |
| **T3** | Einstellungen `VALVE_OPEN_MIN_PCT` (80) und `VALVE_NOT_CLOSING_DELTA_K` (2.0), Muster AE-73, mit Start-Validator (Delta > 0, Prozent 0..100, und **Delta kleiner als `ROOM_TOO_WARM_DELTA_K`** — sonst wäre 3c nie die engere Aussage) | 0,75 h |
| **T4** | Schema (`valve_state` erweitern, Spiegel-Test greift automatisch), Frontend-Spiegel, Badge-Etikett und Hinweistext, Dashboard-Kachel, `statusScore`-Rang | 1,5 h |
| **T5** | Tests: beide Bedingungen einzeln und zusammen; G1 (Absenkung, ein Messwert unter der Schwelle fällt das Urteil); G2/G3 nach T0-Entscheidung; Vorrang; **der Datenstand vom 10.10. als Testwand** (027 gemeldet, 100 gemeldet, sonst keiner) | 2 h |
| **T6** | RUNBOOK §10t (gemeinsamer Handgriff, Abgrenzungs-Tabelle aus §2), AE-74 um 3c erweitern, STATUS | 1 h |
| **Summe** | | **8,0 h** |
| **T7** *(optional)* | `lowMotorConsumption` persistieren: Migration (additiv, nullable), Subscriber, im Hinweistext als „Motor läuft ohne Widerstand". **Nicht** als Bedingung | 1 h |

---

## 8. Akzeptanzkriterien

1. **027/110 und 100/405 werden gemeldet, sonst keiner** (Live-Abnahme des
   Hoteliers, bei laufendem Kessel).
2. Bei **Nachtabsenkung** entsteht kein Hinweis — ein Gerät, das nach dem
   Sollwert-Wechsel schließt, fällt aus dem Urteil.
3. Ein Gerät, das **beide** Bedingungen (3b und 3c) erfüllt, trägt den
   3c-Hinweis, und ein Test hält das fest.
4. Die bestehenden Tests zu Regel 3 und 3b bleiben **ohne Anpassung** grün
   (§5.47) — 3c ist additiv. Ausnahme: die Tests, die „es gibt keine
   Vorrangregel" behaupten; die werden zur Vorrangregel.
5. Der Hinweistext nennt den Abstand **und** die gemeldete Stellung.
6. Kein Mailversand (wie 3 und 3b, AE-74).

---

## 9. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| **Die 80 % sind geraten** und treffen die beiden Fälle nicht | T0 misst `ventil_min`/`ventil_max` der betroffenen Geräte, bevor die Zahl feststeht |
| **G1 (Absenkung) erzeugt eine Fehlalarm-Welle jeden Abend** — und zwar genau die Sorte, die 20e-b gerade beseitigt hat | Zweite T0-Messung zur Absenkung ist Pflicht-Stop. Fällt sie schlecht aus, wird das Fenster für 3c verlängert statt die Schwelle verschoben |
| **Drei Ventil-Kacheln**, und die dritte verwässert die zwei bestehenden | Erwartete Zahl ist 2. Nach vier Wochen gegen 3b halten; treffen beide dieselben Geräte, zusammenlegen |
| **3c macht 3b scheinbar überflüssig**, und jemand baut es ab | Die Abgrenzungs-Tabelle aus §2 gehört in Modul-Docstring und RUNBOOK: ein abgenommener Kopf, dessen letzte Stellung „zu" war, meldet **zu** — den findet nur 3b |
| **Vorrang falsch gewählt** | Als Test festgehalten, nicht als Reihenfolge von `elif`-Zweigen (§5.23) |

---

## 10. Was NICHT in 20e-c gehört

- **`lowMotorConsumption` als Bedingung.** Zwei Beobachtungen, Bedeutung
  herstellerdefiniert (§5.21). Als Diagnose-Text in T7, nicht als Torwächter.
- **Regel 3b senken oder abbauen.** Sie findet den Fall, den 3c nicht sehen
  kann, und ihre Schwelle ist gemessen.
- **Die Saisonabhängigkeit von 3b „beheben".** Sie ist der Preis dafür, dass
  die Kachel nicht lärmt. 3c umgeht sie, statt sie zu bekämpfen — das ist der
  ganze Gedanke dieses Sprints.
- **Mail bei 3c.** Gate-Entscheidung aus AE-74 gilt weiter: UI-Hinweis.
- **Engine-Reaktion auf 3c** (etwa Sollwert senken, um das Zimmer zu
  schützen). Ein Melder, der auch handelt, ist zwei Dinge in einem; und bei
  einem Ventil, das nicht schließt, hilft kein Sollwert.
