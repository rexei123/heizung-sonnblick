# Sprint 20e-b — Regel 3b misst das Wetter, nicht das Ventil

**Datum:** 2026-10-08
**Typ:** Backend (read-time Bewertung) + Oberfläche (Hinweistext)
**Autonomie-Stufe:** 2
**Status:** **Brief zur Freigabe.** Nichts umgesetzt.

---

## 0. Der Befund

**Live, 07.10.2026 14:58, Kessel aus, Herbst.** Dashboard-Kachel „Zimmer zu
warm" = **14**. Erwartet waren **2** (Gerät 027 in Zimmer 110, Gerät 100 in
Zimmer 405).

Ursache: leere Zimmer standen bei 22–24 °C, Sollwert 18 °C, Ventile zu. Also
`Ist ≥ Soll + 5 K` über das ganze Fenster — die Bedingung von Regel 3b, Wort
für Wort erfüllt.

**Die Schwelle ist nicht das Problem, das Kriterium ist es.** Ein absoluter
Abstand zwischen Ist und Soll kann einen klemmenden Kopf nicht von einem
warmen Herbsttag unterscheiden, weil beide dasselbe Messbild erzeugen: Raum
deutlich über Sollwert, Ventil zu. Wer die Schwelle auf 7 K hebt, verschiebt
die Grenze und verliert dabei die echten Fälle — 027 und 100 lagen heute bei
Werten, die ein strengeres Delta mit aussortiert hätte.

Und ein Hinweis, der an 14 von 104 Geräten steht, von denen 12 falsch sind,
ist nach einer Woche kein Hinweis mehr (§5.79). Das wäre besonders bitter,
weil Regel 3b seit 20e **der einzige automatische Melder für ein
abgefallenes Gerät** ist (AE-74): Layer 4 erkennt es bei einem Gerät mit
Montage-Nachweis nicht mehr.

---

## 1. Der Gedanke dahinter — und warum er trägt

**Wetter wirkt auf alle Zimmer, ein klemmendes Ventil auf eines.**

Das ist der Unterschied, den ein absolutes Kriterium nicht sehen kann und ein
relatives sehr wohl: Ein Zimmer, das **gegenüber vergleichbaren Zimmern**
auffällig warm ist, hat ein Problem im Zimmer. Ein Zimmer, das zusammen mit
allen anderen warm ist, hat Wetter.

**Vorschlag des Hoteliers (07.10.):** Regel 3b verlangt zusätzlich

    Raum ≥ Median aller nicht belegten Zimmer + 3 K

im selben 2-h-Fenster, mit `bool_and` wie die bestehende Bedingung. Die
absolute Bedingung bleibt daneben stehen, verknüpft mit **UND**.

Das ist die richtige Richtung. Die absolute Bedingung behalten ist wichtig:
ohne sie würde in einem gleichmäßig kalten Haus das wärmste Zimmer
auffallen, obwohl es nur das wärmste und nicht zu warm ist.

---

## 2. Grenzfälle

Die beiden aus dem Auftrag, plus drei, die mir beim Durchrechnen aufgefallen
sind. Der dritte ist der, der die Umsetzung bestimmt.

| # | Fall | Wirkung | Antwort |
|---|---|---|---|
| **G1** | **Wenige leere Zimmer** | Median über zwei oder drei Zimmern ist kein Median, sondern ein Einzelwert mit Zufallsanteil | Mindestzahl, analog `VALVE_MIN_SAMPLES`. Darunter **kein** relatives Urteil — und damit kein 3b-Hinweis, weil die Bedingungen mit UND verknüpft sind |
| **G2** | **Hochsaison, fast alles belegt** | Die Referenzmenge verschwindet | Rückfallkette, siehe §3. **Nicht** einfach „dann über alle Zimmer": belegte Zimmer sind eine andere Population (G5) |
| **G3** | **Himmelsrichtung und Geschoss** | Ein Südzimmer im Dachgeschoss ist im Oktober bei Sonne um mehr als 3 K wärmer als ein Nordzimmer im ersten Stock. Ein hausweiter Median markiert dann **jedes** Südzimmer | **Der kritische Punkt.** Drei Varianten in §4; ohne Antwort tauscht 20e-b nur eine Sorte Falsch-Alarm gegen eine andere |
| **G4** | **Der Median ist mit den gesuchten Geräten verunreinigt** | Nach einer Reinigungsrunde auf einem Stockwerk sitzen mehrere Köpfe ab, diese Zimmer sind heiß und heben den Median — er verdeckt genau den Fehler | Der Median trägt das bis zu 50 % Verunreinigung; darüber nicht. Mit 14 Verdachtsfällen heute ist das keine Theorie. Gehört als **ausgesprochene Annahme** in den Code, nicht als stiller Nebeneffekt |
| **G5** | **Belegte Zimmer sind thermisch etwas anderes** | Gäste stellen 22–24 °C ein. Ein Median über alle Zimmer liegt deshalb höher und macht 3b stumpf — er hebt die Hürde genau dann, wenn ohnehin niemand nachsieht | Deshalb ist „über alle Zimmer" die **zweite** Stufe der Kette und nicht die erste, und sie bekommt ein eigenes, größeres Delta |

---

## 3. Vorschlag: Referenz mit Rückfallkette

Statt einer festen Wahl der Referenzmenge eine Kette, die benennt, worauf sie
sich stützt:

| Stufe | Referenzmenge | Bedingung | Delta |
|---|---|---|---|
| 1 | Nicht belegte Zimmer | mindestens `REF_MIN_ROOMS` davon | `ROOM_REL_DELTA_K` (Vorgabe **3,0**) |
| 2 | **Alle** Zimmer | Stufe 1 nicht erreicht, mindestens `REF_MIN_ROOMS` Zimmer | `ROOM_REL_DELTA_ALL_K` (Vorgabe **4,0**) |
| 3 | — | auch Stufe 2 nicht erreicht | **kein relatives Urteil → kein 3b-Hinweis** |

`ValveVerdict` bekommt dazu ein Feld `referenz` (`unbelegt` / `alle` /
`keine`) plus den verwendeten Medianwert. Der Hinweistext nennt es dann:
„Ist liegt 6,2 K über Soll und 4,1 K über vergleichbaren Zimmern" — und bei
Stufe 2 „über allen Zimmern". Ohne diese Angabe müsste ein Hausmeister
raten, gegen was verglichen wurde.

**Warum Stufe 3 kein Hinweis ist und nicht der alte absolute Hinweis.** Die
Versuchung ist, bei fehlender Referenz auf das absolute Kriterium
zurückzufallen — „besser etwas als nichts". Genau das wäre der heutige
Zustand mit 14 Falsch-Alarmen, nur seltener und damit unberechenbar. Lieber
eine Lücke, die man kennt, als ein Melder, dessen Verlässlichkeit von der
Belegung abhängt.

---

## 4. Die Entscheidung, die das Gate braucht: Himmelsrichtung (G3)

`room.orientation` (`N`, `NE`, `E`, `SE`, `S`, `SW`, `W` — `Orientation` in
`models/enums.py`) und `room.floor` existieren im Schema, beide nullable. Der
Kommentar am Enum sagt ausdrücklich „für spätere KI-Optimierung (solare
Gewinne bei Südzimmern)" — die Information ist also da und bisher ungenutzt.

| Variante | Dafür | Dagegen |
|---|---|---|
| **A: hausweiter Median, Delta höher (5 K statt 3 K)** | Einfach, eine Referenzmenge, keine Gruppierung | Ein Delta, das Südzimmer verschont, verzeiht einem klemmenden Nordzimmer fast alles. Die Empfindlichkeit wird dort am kleinsten, wo die Chance auf einen echten Fund am größten ist |
| **B: Median je Himmelsrichtungs-Gruppe** (N/NE/E zusammen, S/SE/SW zusammen, W eigen) | Trifft die physikalische Ursache. Gruppen statt acht Einzelrichtungen, damit die Stichprobe hält | Mehr Code, und die Mindestzahl muss **je Gruppe** erreicht werden — bei 45 Zimmern und Hochsaison fällt das öfter auf Stufe 2 |
| **C: hausweiter Median, aber Zimmer ohne `orientation` ausschließen und Südzimmer mit Zuschlag** | Mittelweg | Ein Zuschlag je Richtung ist eine Tabelle mit sieben Zahlen, die niemand belegen kann. Das ist Scheinpräzision |

**Empfehlung: B**, mit Rückfall auf A (hausweiter Median, größeres Delta),
wenn eine Gruppe die Mindestzahl nicht erreicht. Die Kette aus §3 bekommt
damit eine Stufe mehr:

1. Nicht belegte Zimmer **derselben Richtungsgruppe**
2. Nicht belegte Zimmer **hausweit**
3. **Alle** Zimmer hausweit
4. kein Urteil

Das klingt nach viel für einen Hinweis. Die Begründung ist, dass jede Stufe
genau einen Grenzfall erledigt und im Verdict benannt wird — ein Operator
kann also immer nachlesen, worauf das Urteil fußt. Die Alternative ist eine
einzige Zahl, die in halben Jahreszeiten falsch liegt.

**Falls das Gate es kleiner will:** Variante A mit 5 K ist in zwei Stunden
gebaut und schon deutlich besser als heute. Dann bleibt G3 ein offener
Mangel, und der muss im Code und im RUNBOOK als solcher stehen — nicht als
„berücksichtigt".

---

## 5. Vor dem Bauen messen

Die Zahl 14 ist belegt, die Wirkung des Vorschlags nicht. Beides lässt sich
**vor** einer Zeile Code gegen den heutigen Datenstand prüfen. Erwartung
nach §0: höchstens 110/405.

**SSH (heizung-test, root):**

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml exec db psql -U heizung -d heizung -c "
WITH fenster AS (
  SELECT sr.device_id, d.label AS geraet, r.number AS zimmer, r.status,
         r.orientation, r.floor, sr.temperature, sr.setpoint
  FROM sensor_reading sr
  JOIN device d        ON d.id = sr.device_id
  JOIN heating_zone hz ON hz.id = d.heating_zone_id
  JOIN room r          ON r.id = hz.room_id
  WHERE d.retired_at IS NULL
    AND sr.time >= now() - interval '2 hours'
    AND sr.temperature IS NOT NULL AND sr.setpoint IS NOT NULL
),
referenz AS (
  SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY temperature) AS median_unbelegt,
         count(DISTINCT zimmer) AS zimmer_unbelegt
  FROM fenster WHERE status <> 'occupied'
),
je_geraet AS (
  SELECT device_id, geraet, zimmer, orientation, floor,
         count(*) AS messwerte,
         bool_and(temperature >= setpoint + 5.0) AS absolut,
         bool_and(temperature >= (SELECT median_unbelegt FROM referenz) + 3.0) AS relativ,
         round(min(temperature - setpoint), 1) AS min_ueber_soll
  FROM fenster GROUP BY 1,2,3,4,5
)
SELECT (SELECT round(median_unbelegt,1) FROM referenz) AS median_unbelegt,
       (SELECT zimmer_unbelegt FROM referenz)          AS zimmer_unbelegt,
       count(*) FILTER (WHERE absolut)                 AS heute_gemeldet,
       count(*) FILTER (WHERE absolut AND relativ)     AS mit_relativ_uebrig
FROM je_geraet WHERE messwerte >= 6;"
```

Und die Liste dazu, um zu sehen **welche** übrig bleiben:

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml exec db psql -U heizung -d heizung -c "
WITH fenster AS (
  SELECT sr.device_id, d.label AS geraet, r.number AS zimmer, r.status,
         r.orientation, sr.temperature, sr.setpoint
  FROM sensor_reading sr
  JOIN device d ON d.id = sr.device_id
  JOIN heating_zone hz ON hz.id = d.heating_zone_id
  JOIN room r ON r.id = hz.room_id
  WHERE d.retired_at IS NULL AND sr.time >= now() - interval '2 hours'
    AND sr.temperature IS NOT NULL AND sr.setpoint IS NOT NULL
),
ref AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY temperature) AS m
        FROM fenster WHERE status <> 'occupied')
SELECT geraet, zimmer, orientation, status, count(*) AS n,
       round(min(temperature - setpoint),1) AS ueber_soll,
       round(min(temperature - (SELECT m FROM ref)),1) AS ueber_median,
       bool_and(temperature >= setpoint + 5.0) AS absolut,
       bool_and(temperature >= (SELECT m FROM ref) + 3.0) AS relativ
FROM fenster GROUP BY 1,2,3,4
HAVING count(*) >= 6 AND bool_and(temperature >= setpoint + 5.0)
ORDER BY ueber_median DESC;"
```

**Was die Ausgabe entscheidet:**

- `mit_relativ_uebrig` = 2 und die Liste nennt 027/110 und 100/405 → der
  Vorschlag trifft, Variante A reicht womöglich schon.
- `mit_relativ_uebrig` deutlich über 2, und die Übrigen sind auffällig oft
  `S`/`SE`/`SW` → **G3 ist scharf**, Variante B wird gebraucht.
- `zimmer_unbelegt` klein (unter 5) → G1 ist heute schon aktiv, die
  Mindestzahl ist keine Vorsichtsmaßnahme für später.
- Die Spalte `ueber_median` sagt, wo ein sinnvolles Delta liegt. **Die
  Vorgabe 3,0 K ist bis dahin ein Vorschlag und keine Messung.**

Die Abfragen rechnen die Vorgabewerte (5,0 / 3,0 / 6 Messwerte) nach — sie
lesen die Einstellungen **nicht**. Wer die Schwellen vorher geändert hat,
passt sie hier mit an.

---

## 6. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T0** | Messung aus §5 auswerten, Delta und Variante festlegen. **Pflicht-Stop** — ohne Zahlen ist jedes Delta geraten | 0,5 h |
| **T1** | `valve_health`: Referenz-Median je Fenster, als CTE in derselben Abfrage. Ein zweiter Roundtrip wäre vermeidbar, und beide Teile lesen dasselbe Fenster | 2 h |
| **T2** | Rückfallkette (§3, mit §4 ggf. vierstufig), Ergebnis als `referenz` + `referenz_median_c` im `ValveVerdict`. Benannt, nicht impliziert | 1,5 h |
| **T3** | Einstellungen: `ROOM_REL_DELTA_K`, `ROOM_REL_DELTA_ALL_K`, `REF_MIN_ROOMS`. Muster AE-73, mit Start-Validator (beide Deltas > 0, `ALL` ≥ normal) | 1 h |
| **T4** | Hinweistext nennt beide Abstände und die Referenz. Frontend-Spiegel (§5.63) **und** `field_serializer` für das neue `Decimal`-Feld — der strukturelle Test aus dem Hotfix fängt ein Vergessen, aber erst nach dem Schreiben | 1 h |
| **T5** | Tests: beide Bedingungen einzeln und zusammen; G1 (zu wenige Zimmer → kein Urteil); G2 (Rückfall auf Stufe 2); G4 (Median mit drei von sieben heißen Zimmern hält, mit fünf von sieben nicht — die 50-%-Grenze als Test, damit sie eine Aussage ist); Referenz im Verdict korrekt benannt | 2,5 h |
| **T6** | **Der Test mit dem heutigen Datenstand** als Fixture: die Temperaturlage vom 07.10. nachgebaut, Erwartung höchstens 027/110 und 100/405. Der Befund als Testwand, wie bei 20f-b die Nachtabsenkung | 1 h |
| **T7** | RUNBOOK §10t ergänzen: was „über vergleichbaren Zimmern" heißt, und dass bei Hochsaison die Referenz wechselt. AE-74 um die Entscheidung erweitern | 1 h |
| **Summe** | | **10,5 h** |

Bei Variante A statt B: **−2,5 h** (T2 bleibt dreistufig, T5 ohne Gruppen).

---

## 7. Akzeptanzkriterien

1. Gegen den Datenstand vom 07.10. 14:58 meldet Regel 3b **höchstens** die
   Geräte 027 (Zimmer 110) und 100 (Zimmer 405).
2. Ein Gerät, dessen Zimmer gegenüber der Referenz auffällt, wird weiter
   gemeldet — auch wenn das ganze Haus warm ist. Belegt mit einem Test, der
   alle Zimmer um 5 K hebt und das eine zusätzlich.
3. Reicht die Referenzmenge nicht, gibt es **keinen** 3b-Hinweis, und das
   Verdict sagt, warum.
4. Der Hinweistext nennt beide Abstände und die verwendete Referenz.
5. Die bestehenden Regel-3-Tests (Ventil klemmt zu) bleiben **ohne
   Anpassung** grün (§5.47) — 20e-b berührt nur 3b.
6. Live nachgeprüft: Kachel „Zimmer zu warm" entspricht am Folgetag der
   Begehung.

---

## 8. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| **Das relative Kriterium verdeckt einen echten Fall** (G4): sind mehrere Köpfe ab, hebt sich der Median | Median trägt bis 50 %. Als Annahme im Code benannt und per Test festgehalten. Dazu: die **absolute** Kachel bleibt daneben als Diagnose-Zahl erhalten, auch wenn sie keinen Hinweis mehr erzeugt — wer 14 absolute und 2 relative sieht, erkennt die Wetterlage |
| **Zwei Schwellen statt einer**, also mehr Stellschrauben | Dafür eine, die mit der Jahreszeit mitgeht. Ohne sie müsste die absolute Schwelle zweimal im Jahr von Hand nachgezogen werden, und zwischendurch wäre sie falsch |
| **`room.status` ist read-time abgeleitet** und per Beat gesynct (§5.53) | Für eine **Referenzmenge** ist das genau genug: ein Zimmer, das vor einer Stunde ausgecheckt hat, verhält sich thermisch noch wie ein belegtes. Die persistierte Spalte ist hier die bessere Quelle, nicht die schlechtere — und das gehört als Begründung in den Code, sonst sieht es wie ein Fehler aus |
| **Eine Jahreszeit später passt es wieder nicht** | Die Deltas stehen in den Einstellungen. Nach zwei Wochen Heizperiode nachjustieren, wie bei Regel 3 |

---

## 9. Was NICHT in 20e-b gehört

- **Außentemperatur als Referenz.** Physikalisch das Richtige, aber wir haben
  keinen Außensensor. Eine Wetter-API wäre eine neue externe Abhängigkeit im
  Melder-Pfad (§0 S5) für eine Größe, die der Hausmedian ohnehin mit abbildet.
- **Regel 3 (Ventil klemmt zu) relativieren.** Dort wirkt die
  Sensor-Verzerrung in die harmlose Richtung (AE-74), die Fehlalarm-Lage gibt
  es nicht. Ein Umbau ohne Befund ist S6-widrig.
- **Die Kachel „Zimmer zu warm" aufteilen** in absolut und relativ. Zwei
  Zahlen für einen Hinweis, und der Hausmeister müsste den Unterschied
  lernen. Die absolute Zahl bleibt in der Diagnose-Abfrage (§5), nicht auf
  dem Dashboard.
- **Lernende Referenz** (gleitender Mittelwert je Zimmer über Wochen). Wäre
  genauer und hätte einen persistierten Zustand, der bei Ausfall des
  Taktgebers plausibel einfriert — genau das Fehlerbild aus §5.76, das AE-72
  und 20e vermieden haben.
