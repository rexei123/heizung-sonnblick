# Sprint 20e — Montage-Status vereinfacht (AE-74)

**Typ:** Backend (Engine-Schicht + Health) + Frontend + eine Migration
**Ziel:** Ein zugeordnetes Gerät, das einmal nachweislich montiert war, gilt
dauerhaft als montiert. Der Backplate-Taster steuert danach weder Anzeige
noch Steuerung. Statt seiner melden zwei Wirkungs-Kriterien: Funkstille und
ein Ventil, das nicht reagiert.
**Branch:** `feat/sprint20e-montage-status` (von `develop`)
**Autonomie-Stufe:** **1** — Engine-Schicht mit Hardware-Schutz-Bezug (Layer 4
Detached). Volle Stop-Points.
**Geschätzte Dauer:** 8–11 h.
**Status:** Brief, Phase 1. **Nicht gebaut.** Das Gate kommt vor der Umsetzung.

---

## 0. Die Abwägung, die vor allem anderen steht

Regel 1 schaltet für zugeordnete Geräte den **Detached-Frostschutz** ab —
Engine Layer 4, zweiter Trigger, gebaut in Sprint 9.11x nach AE-47. Dessen
Zweck war: wird das Thermostat vom Heizkörper genommen, regelt niemand mehr,
und der Raum geht auf Frostschutz, statt ungebremst zu heizen oder
auszukühlen.

**Was nach Regel 1 unsichtbar wird:** ein Gerät, das abgenommen wurde,
**weiter sendet** und dessen Ventil sich in der Luft frei bewegt. Es meldet
sich (Regel 2 greift nicht), sein Ventil reagiert auf Sollwerte (Regel 3
greift nicht), und der Backplate-Taster wird nicht mehr gelesen. Dieser Fall
hat nach dem Sprint **keinen** Melder mehr.

Dagegen steht der gemeldete Befund: der Taster meldet bei nachweislich
montierten Geräten zeitweise `false` (013 in 102, 051 in 207 Bad). Ein
Melder, der am montierten Gerät Fehlalarm gibt, kostet jedes Mal eine
Fehlersuche — und §5.79 sagt, dass ein Melder, dem niemand mehr glaubt,
nichts überwacht. Dass der Taster bei beiden Geräten wackelt, ist zudem kein
Software-, sondern ein Hardware-Befund.

**Das ist eine bewusste Entscheidung und sie gehört ins ADR, nicht in einen
Task.** Der Brief setzt sie um wie beauftragt; AE-74 schreibt beides auf: was
der Wechsel bringt und welchen Fall er aufgibt.

**Eine Abmilderung, die nichts kostet** (Vorschlag, nicht beauftragt): der
Rohwert bleibt in der Geräte-Detailseite sichtbar — als Diagnose-Kachel mit
Zeitstempel, nicht als Status. Wer einem Gerät nachgeht, sieht dann weiter,
was der Taster sagt; nur steuert es nichts mehr.

---

## 1. Wo `attached_backplate` heute ausgewertet wird

Sechs Stellen, vollständig (`grep -rn "attached_backplate\|attachedBackplate"`
über `backend/src`, `frontend/src`, `infra`).

| # | Stelle | Was sie heute tut | Änderung in 20e |
|---|---|---|---|
| 1 | **Engine Layer 4 Detached** — [`rules/engine.py:593-749`](backend/src/heizung/rules/engine.py:593) | AND über **alle** Geräte der Zonen eines Raums: die letzten **zwei** frischen Frames mit `attached_backplate IS NOT NULL` müssen beide `False` sein, dann Frostschutz (`MIN_SETPOINT_C`, Reason `DEVICE_DETACHED`). Frischefenster 30 min ([`constants.py:40`](backend/src/heizung/rules/constants.py:40)) | **Trigger entfällt für Geräte mit gesetztem Montage-Nachweis.** Die Schicht bleibt in der Pipeline und schreibt ihren `LayerStep` weiter (§5.23 — jede Schicht schreibt immer), mit neuem `detail`-Token `sticky_mounted`. Nur Geräte **ohne** Nachweis werden noch geprüft |
| 2 | **`GET /devices/{id}/hardware-status`** — [`api/v1/devices.py:520-560`](backend/src/heizung/api/v1/devices.py:520) | `status="active"`, wenn im 30-min-Fenster **ein** Frame `attached_backplate=True` trägt; zählt Frames mit `IS NOT NULL` | Für zugeordnete Geräte mit Nachweis: `status` kommt aus dem Nachweis, nicht aus dem Fenster. `frames_in_window` und `last_seen` bleiben — sie sind die Diagnose |
| 3 | **`HardwareStatusBadge`** — [`hardware-status-badge.tsx`](frontend/src/components/patterns/hardware-status-badge.tsx:7) | Vier Zustände, darunter `im_lager` für Pool-Geräte (Sprint 20) | Neuer Pfad „montiert (bestätigt)". Pool-Pfad **unverändert** |
| 4 | **Geräte-Detailseite** — [`devices/[device_id]/page.tsx:531-538`](frontend/src/app/devices/[device_id]/page.tsx:531) | Kachel aus `latest_reading.attached_backplate` (true/false/unbekannt) | Bleibt — aber **als Diagnose gekennzeichnet**, mit Zeitstempel, nicht als Status. Siehe §0 |
| 5 | **`assign` Nachprüfung** — [`pairing/assign.py:228-271`](backend/src/heizung/scripts/pairing/assign.py:228) | Nach dem Schreiben: `attached_backplate is True` im jüngsten frischen Reading = in Ordnung, sonst Warnung → Exit 2, kein Rollback | **Unverändert.** Das ist der Montage-Moment selbst: hier ist der Taster die Messung, nicht der Dauerzustand |
| 6 | **Eingangstest Vor-Check** — [`pairing/batch_inbound_test.py:467-475`](backend/src/heizung/scripts/pairing/batch_inbound_test.py:467) | Ohne Backplate kein Sollwert-Test; ohne `--require-motor` „OHNE MOTOR", mit `--require-motor` **FAIL** | **Unverändert.** Pool-Gerät, und der Lauf ist genau die Prüfung, die den Nachweis erzeugt |

Dazu zwei Nennungen ohne Auswertung: [`rules/inferred_window.py:6`](backend/src/heizung/rules/inferred_window.py:6)
beschreibt den Taster als einen der zwei Hardware-Trigger (Doku, nachzuziehen),
und [`mqtt_subscriber.py:236`](backend/src/heizung/services/mqtt_subscriber.py:236)
schreibt den Rohwert — der bleibt, unverändert.

**Health und Alarme werten den Taster heute NICHT aus.** `health_tasks.py`
kennt ihn nicht; es rechnet ausschließlich mit dem Alter des jüngsten
Readings und einem Redis-Zähler für implausible Werte. Das ist der Grund,
warum Regel 2 an eine bestehende Mechanik anknüpfen kann.

---

## 2. Regel 1 braucht `motorRange` — und das ist nicht gespeichert

**Der Befund, der den Zuschnitt bestimmt.** Der Codec berechnet und emittiert
`motor_range` ([`mclimate-vicki.js:144`](infra/chirpstack/codecs/mclimate-vicki.js:144)),
aber der Subscriber bildet nur `valve_openness` auf `valve_position` ab
([`mqtt_subscriber.py:208-221`](backend/src/heizung/services/mqtt_subscriber.py:208)) —
**es gibt keine Spalte `motor_range`** in `sensor_reading`
([`models/sensor_reading.py:35-97`](backend/src/heizung/models/sensor_reading.py:35)).
Die Bedingung „motorRange > 0" ist aus den vorhandenen Daten **nicht**
beantwortbar.

**Und die naheliegende Abkürzung trägt nicht.** `valve_position IS NOT NULL`
ist **kein** Ersatz: bei `motorRange == 0` setzt der Codec `valveOpenness = 0`
und nicht `null` ([`mclimate-vicki.js:131-136`](infra/chirpstack/codecs/mclimate-vicki.js:131)).
`valve_position = 0` heißt also entweder „Ventil zu" oder „nicht kalibriert" —
dieselbe Zahl für zwei Zustände.

**Was trägt:** `valve_position > 0`. Eine Öffnung über 0 % kann nur aus dem
Zweig `if (motorRange > 0)` kommen; außerhalb bleibt der Wert auf 0. Also gilt

> `valve_position > 0` ⟹ `motorRange > 0`

und das ist aus dem Codec beweisbar, nicht angenommen. Die Umkehrung gilt
nicht (ein kalibriertes, geschlossenes Ventil meldet 0 %) — für einen
**Nachweis** reicht die eine Richtung: wir brauchen einmal einen Beleg, nicht
einen Dauerzustand.

**Und der Nachweis fällt im Montage-Ablauf ohnehin an:** der Eingangstest
fährt auf 28 °C und erwartet dort eine Öffnung um 80 % (§10h.4). Jedes Gerät,
das `PASS` hat, hatte `valve_position > 0`.

### Zwei Wege, Empfehlung

| Weg | Dafür | Dagegen |
|---|---|---|
| **A: `valve_position > 0` als Kriterium** | keine Migration, aus dem Codec belegbar, im Montage-Ablauf immer erfüllt | nicht die wörtliche Bedingung des Auftrags; ein kalibriertes Gerät, dessen Ventil nie geöffnet wurde, bekommt keinen Nachweis |
| **B: Spalte `sensor_reading.motor_range`** | die wörtliche Bedingung, und der Rohwert hilft später bei Ventil-Diagnosen | Migration, und sie wirkt **nur nach vorn** — für die heute montierten 12 Geräte steht der Wert nirgends, der Nachweis müsste aus `valve_position > 0` kommen oder auf den nächsten Uplink warten |

**Empfehlung: A**, und B als eigener Backlog-Eintrag für den Rohwert. Grund:
B löst das Problem für die Pilotgeräte nicht — es gibt keine historischen
`motor_range`-Werte —, und A ist für den Zweck „einmal belegt" exakt.

---

## 3. Wo der Nachweis liegt: eine Spalte auf `device`

**Vorschlag:** `device.mounted_confirmed_at` (`TIMESTAMPTZ NULL`), analog zu
`retired_at` (AE-57) — eine Lebenszyklus-Tatsache des Geräts.

Geschrieben wird sie vom Subscriber, auf dem Frame, der beide Bedingungen
zuerst erfüllt, mit `WHERE mounted_confirmed_at IS NULL` als Wächter: ein
Schreibvorgang je Gerät, je Lebenszeit, idempotent und race-frei (§5.60 —
die Bedingung gehört in die `UPDATE`-`WHERE`, nicht in einen Python-Vorab-Check).

### Warum nicht read-time abgeleitet (§5.73)

Die Regel sagt: ableitbare Werte read-time ableiten, nicht persistieren. Hier
gilt sie **nicht**, und zwar aus zwei Gründen:

1. **Das Prädikat ist monoton über die ganze Historie.** Read-time wäre es ein
   `EXISTS` ohne Zeitgrenze. Das ist billig, solange es **wahr** ist (erster
   Treffer, Index `ix_sensor_reading_device_time`), und teuer, wenn es
   **falsch** ist — dann liest es die ganze Historie des Geräts. Falsch ist es
   genau bei den interessanten Geräten: Pool und defekt.
2. **`sensor_reading` ist eine Hypertable, und Retention ist vorgesehen.**
   Heute gibt es **keine** Retention-Policy (geprüft: kein
   `add_retention_policy`/`drop_chunks` in `backend/alembic/versions/`), aber
   B-17-2 schlägt sie für `event_log` vor und nennt `sensor_reading` im
   Vergleich. Ein Nachweis, der aus Daten abgeleitet wird, die gelöscht werden
   dürfen, ist kein Nachweis. Das ist der Unterschied zur Batterie-Stufe
   (AE-72): die darf vergessen, dieser Wert nicht.

**Gegenprobe zur Ehrlichkeit:** Punkt 2 ist ein Zukunftsrisiko, kein heutiger
Defekt. Wer ihn nicht gelten lässt, landet bei Punkt 1 — und der reicht.

---

## 4. Regel 2 — Funkstille, und die Schwelle steht heute auf 24 h

**Was es gibt.** [`health_tasks._basis_state_from_age`](backend/src/heizung/tasks/health_tasks.py:87):

| Alter des jüngsten Readings | `device.health_state` |
|---|---|
| ≤ `HEALTHY_MAX_AGE` = **2 h** | `healthy` |
| ≤ `DEGRADED_MAX_AGE` = **24 h** | `degraded` |
| darüber | `silent` |

Der Alarm hängt am **Übergang nach `silent`**
([`health_tasks.py:232-271`](backend/src/heizung/tasks/health_tasks.py:232) →
[`health_alerts.handle_silent_transitions`](backend/src/heizung/services/health_alerts.py:138)),
also heute bei **24 h**. Die beauftragten 3 h sind damit keine
Schwellen-Prüfung, sondern eine Verschiebung um den Faktor acht.

**Der einfachste Weg ist eine Zahl:** `DEGRADED_MAX_AGE` von 24 h auf 3 h.
Dann feuert der bestehende Alarm bei 3 h, ohne neuen Code, ohne neuen
Versandweg.

**Die Engine ändert sich dadurch nicht.** Sie filtert an drei Stellen auf
`health_state == "healthy"`
([`engine.py:571`](backend/src/heizung/rules/engine.py:571),
[`window_state.py:79`](backend/src/heizung/rules/window_state.py:79),
[`engine_tasks.py:392`](backend/src/heizung/tasks/engine_tasks.py:392)) — ein
Gerät über 2 h ist bereits als `degraded` ausgeschlossen. Ob die Grenze
dahinter bei 3 h oder 24 h liegt, ist für die Steuerung gleich.

**Zwei Nebenwirkungen, die eine Entscheidung brauchen:**

1. **Die Online-Kachel.** `count_devices_online` zählt `healthy` **und**
   `degraded` als online ([`dashboard_aggregates.py:39`](backend/src/heizung/services/dashboard_aggregates.py:39)).
   Ein Gerät fällt damit nach 3 h aus „online" statt nach 24 h. Das ist
   wahrscheinlich gewollt — aber es ist eine sichtbare Änderung an einer
   Kennzahl, die der Hotelier täglich liest.
2. **`degraded` wird zur Durchgangsstufe.** Zwischen 2 h und 3 h bleibt eine
   Stunde. Dann ist zu fragen, ob `HEALTHY_MAX_AGE` mit soll (etwa auf 1 h) —
   sonst hat die mittlere Stufe keine Aufgabe mehr. **Offene Frage für das
   Gate**, nicht im Brief entschieden.

Beide Schwellen gehören dabei in die Settings (Muster AE-73), nicht als
Konstanten in die Datei.

---

## 5. Regel 3 — Ventil reagiert nicht

**Aus `sensor_reading` allein auswertbar**, ohne neue Spalte:
`setpoint` (der vom Gerät gemeldete Sollwert, `Numeric(5,2)`), `temperature`
und `valve_position` ([`models/sensor_reading.py:49-51`](backend/src/heizung/models/sensor_reading.py:49)).

Bedingung: `setpoint >= temperature + Δ` **und** `valve_position = 0` über das
ganze Fenster. Schwellen als `Decimal` in den Settings, Muster AE-73:
`VALVE_STUCK_DELTA_K` (Vorgabe 3.0), `VALVE_STUCK_WINDOW_H` (2),
`VALVE_STUCK_OPENNESS_MAX` (0).

**Zwei Dinge, die man dazu wissen muss:**

1. **`temperature` ist der interne Vicki-Sensor, nicht die Raumtemperatur.**
   Er wird von der Heizkörperwärme mitgezogen — der Hersteller sagt das selbst
   (§5.27). Für diese Regel wirkt die Verzerrung **in die harmlose Richtung**:
   der gemessene Wert ist zu hoch, `setpoint >= temp + 3` trifft also seltener
   zu. Der Hinweis kommt damit eher zu selten als zu oft. Das ist vertretbar
   und muss aufgeschrieben werden, damit niemand später einen „fehlenden
   Hinweis" als Fehler jagt.
2. **`valve_position = 0` ist zweideutig** (§2): entweder zu oder nicht
   kalibriert. Für diese Regel ist das **kein** Problem — bei
   `setpoint >= temp + 3` soll das Ventil offen sein, und beide Ursachen
   verdienen denselben Satz „Ventil prüfen". Der Hinweistext nennt deshalb
   beide Möglichkeiten statt zu raten.

**Wo gerechnet wird: read-time, kein Beat-Task.** Dasselbe Muster wie die
Batterie-Stufe (AE-72 §3): eine Aggregat-Query über das 2-h-Fenster für
**alle** Geräte des Requests, vor der Schleife, Ergebnis als Pflicht-Argument
durchgereicht. Begründung wie dort: kein persistierter Zustand, der bei
Ausfall des Taktgebers plausibel einfriert (§5.76 — und B-20c-4 ist genau
dieser Fall, einen Tag alt).

---

## 6. Gibt es einen Benachrichtigungsweg zum Hausmeister?

**Einen — und er ist nicht nach Rolle getrennt.**

| Was | Wohin |
|---|---|
| Versandweg | [`services/mailer.py`](backend/src/heizung/services/mailer.py) (stdlib `smtplib`), Zugangsdaten aus der Umgebung |
| Empfänger | **eine** Adresse: `global_config.alert_email`, in der Oberfläche editierbar (Einstellungen → Hotel → „E-Mail für Warnungen") |
| Alarm 1 | Health-Übergänge nach `silent`, **aggregiert** in einer Sammelmail ([`health_alerts.py:197`](backend/src/heizung/services/health_alerts.py:197)) |
| Alarm 2 | Belegungsliste fehlt ([`occupancy_import_service.py:685`](backend/src/heizung/services/occupancy_import_service.py:685)) |

Kein zweiter Empfänger, keine Rollen-Verteilung, kein SMS- oder Push-Weg. Ein
Hausmeister bekommt heute Post nur, wenn seine Adresse **die** Alarm-Adresse
ist.

**Daraus eine Empfehlung, die über den Auftrag hinausgeht:** Regel 3 ist ein
**Hinweis**, kein Alarm. Ihn in denselben Posteingang zu schicken wie den
Engine-Alarm verdünnt diesen — ein „Ventil prüfen" aus einem Zimmer, in dem
gerade gelüftet wird, kommt häufiger als ein echter Ausfall, und nach zwei
Wochen liest niemand die Betreffzeile noch genau (§5.79). Vorschlag: Regel 3
in die Oberfläche (Badge am Gerät + Zähler auf dem Dashboard), **nicht** per
Mail. Wenn Mail gewünscht ist, dann an eine **zweite** Adresse.

Das ist eine Produktentscheidung und gehört ins Gate.

---

## 7. Unverändert — ausdrücklich

- **Pool-Geräte.** Die Sticky-Regel gilt **nur** für Geräte mit
  `heating_zone_id IS NOT NULL`. Ein Pool-Gerät hat keinen Montage-Nachweis
  und soll keinen haben: am Tisch ist `attached_backplate=false` der erwartete
  Zustand.
- **Eingangstest.** `--require-motor` und der Vor-Check lesen den Rohwert
  weiter. Der Lauf ist die Prüfung, die den Nachweis **erzeugt** — er darf
  sich nicht auf ihn stützen.
- **`assign`-Nachprüfung.** Bleibt die Warnung mit Exit 2. Im Montage-Moment
  ist der Taster die Messung.
- **Der Rohwert selbst.** Subscriber und Spalte bleiben, die Detailseite zeigt
  ihn weiter als Diagnose.

---

## 8. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T1** | Migration 0025: `device.mounted_confirmed_at TIMESTAMPTZ NULL`. Kein Backfill im Schema — siehe T2 | 0,5 h |
| **T2** | Einmal-Backfill als **Skript**, nicht in der Migration: setzt den Nachweis für Geräte, die in der Historie einen Frame mit `attached_backplate=true` **und** einen mit `valve_position > 0` haben. Getrennt von der Migration, weil er fachlich urteilt und wiederholbar sein muss (§5.61: committet selbst, mit Bericht) | 1 h |
| **T3** | Subscriber: Nachweis setzen, wenn beide Bedingungen im selben Frame erfüllt sind und `mounted_confirmed_at IS NULL`, Zuordnung vorhanden. Ein `UPDATE … WHERE` (§5.60) | 1 h |
| **T4** | Engine Layer 4 Detached: Geräte mit Nachweis aus der Detached-Prüfung nehmen, `detail="sticky_mounted"` im Pass-Through-Fall. **Alle bestehenden Layer-4-Tests müssen ohne Anpassung grün bleiben**, soweit sie Geräte ohne Nachweis prüfen (§5.47) | 1,5 h |
| **T5** | `/hardware-status` + `HardwareStatusBadge`: Status aus dem Nachweis für zugeordnete Geräte, Pool-Pfad unberührt. Detailseite-Kachel als Diagnose kennzeichnen | 1,5 h |
| **T6** | Regel 2: `HEALTHY_MAX_AGE` / `DEGRADED_MAX_AGE` in die Settings, Vorgabe nach Gate-Entscheidung (3 h für silent). Alarmtext auf „Gerät meldet sich nicht" | 1 h |
| **T7** | Regel 3: read-time Ventil-Urteil über ein 2-h-Fenster, eine Aggregat-Query für alle Geräte des Requests, neues Read-Feld + Badge + Dashboard-Zähler. Schwellen als `Decimal` in den Settings | 2 h |
| **T8** | Tests: Sticky (Flag kippt auf false → Status bleibt, Layer 4 feuert nicht), Backfill, Regel 2 an den Grenzen, Regel 3 an den Grenzen inkl. des Falls `valve_position = 0` bei `motorRange == 0`, Pool-Geräte unberührt, Eingangstest unberührt | 2 h |
| **T9** | AE-74, RUNBOOK (was der Hausmeister bei „Ventil prüfen" tut, und dass der Taster kein Status mehr ist), §5.27-Nachtrag, STATUS | 1 h |

**Summe 11,5 h** — über der ersten Schätzung von 8–11 h. Treiber sind T4
(Engine, Stufe 1) und T8. Wenn gekürzt werden soll: T7 (Regel 3) ist der
abtrennbare Teil und könnte ein eigener kleiner Sprint sein; Regeln 1 und 2
hängen zusammen, weil Regel 2 den Melder ersetzt, den Regel 1 abschaltet.

**Gegenprobe als Pflicht** (aus 20c): vor dem PR den alten Stand
wiederherstellen und belegen, dass die neuen Tests fallen.

---

## 9. Risiken

| Risiko | Einordnung |
|---|---|
| **Der abgenommene, weiter sendende Vicki hat keinen Melder mehr** | §0. Die eigentliche Abwägung des Sprints, keine Nebenwirkung. Gehört ins ADR und ins Gate |
| **Der Nachweis ist nicht widerrufbar** | Absicht („einmal montiert = montiert"). Folge: nach einem Geräte-Tausch an derselben Zone trägt das **neue** Gerät erst einen Nachweis, wenn es selbst beide Bedingungen erfüllt — das ist richtig. Aber ein Gerät, das zurück in den Pool geht und später neu montiert wird, trägt den alten Nachweis weiter. **Offene Frage:** soll `detach`/`retire` den Nachweis löschen? Ich würde ja sagen — der Nachweis gehört an die Montage, nicht an die Seriennummer |
| **Online-Kennzahl springt** | §4. Ein Gerät fällt nach 3 h statt 24 h aus „online". Sichtbar auf dem Dashboard am Tag des Deploys |
| **Regel 3 ist zu Heizperiodenbeginn laut** | Ein Zimmer, das gerade aufheizt, hat Sollwert über Ist und ein Ventil, das noch nicht offen ist. Das 2-h-Fenster deckt das ab (ein Ventil, das zwei Stunden bei Δ3 K nicht öffnet, ist ein Befund) — belegen lässt sich das aber erst im Betrieb. Deshalb Schwellen konfigurierbar |
| **Backfill urteilt über Altdaten** | T2 setzt den Nachweis aus der Historie. Für die 12 Pilotgeräte ist das genau richtig (Eingangstest hat geöffnet). Für Geräte mit lückenhafter Historie kann er ihn nicht setzen — dann kommt er beim nächsten Uplink mit offenem Ventil. Kein Schaden, nur Verzögerung |
| **Stufe-1-Sprint neben der Montage** | T4 fasst eine Engine-Schicht an, die Frostschutz auslöst. Der Merge gehört **nicht** in ein Montagefenster, und §0.3 ist hier nicht Formalie, sondern der Kern |

---

## 10. Offene Fragen für das Gate

1. **§0 bestätigen:** Der abgenommene, weiter sendende Vicki wird bewusst
   blind. Einverstanden?
2. **Weg A oder B** für `motorRange` (§2). Empfehlung A.
3. **`HEALTHY_MAX_AGE` mit verschieben?** Sonst ist `degraded` eine
   Ein-Stunden-Durchgangsstufe (§4).
4. **Regel 3 per Mail oder nur in der Oberfläche?** Empfehlung: Oberfläche,
   sonst verdünnt der Hinweis den Engine-Alarm (§6).
5. **Löscht `detach`/`retire` den Montage-Nachweis?** Empfehlung: ja (§9).
6. **T7 abtrennen?** Wenn der Sprint kleiner sein soll, ist Regel 3 der
   natürliche Schnitt.

---

## 11. Querverweise

- **AE-47** — Hardware-First bei der Fenstererkennung; derselbe Taster,
  andere Richtung.
- **AE-57** — `retired_at` als Lebenszyklus-Tatsache auf `device`; Vorbild für
  `mounted_confirmed_at` (§3).
- **AE-54** — Isolation pro Zone; Vorbild für B-20c-4 und für die Frage, was
  passiert, wenn eine Auswertung ausfällt.
- **AE-72 §3** — read-time abgeleitetes Urteil über ein Zeitfenster, eine
  Aggregat-Query je Request; Vorbild für Regel 3 (§5).
- **AE-73** — Schwellen als `Decimal` in den Settings; Muster für Regel 2
  und 3.
- **§5.27** — der Hersteller zum internen Sensor und zur Zuverlässigkeit der
  Vicki-Erkennungen; die Quelle für die Einordnung in §5.
- **§5.79** — ein Melder, dem niemand glaubt, überwacht nichts. Die
  Begründung des ganzen Sprints, und gleichzeitig das Argument gegen Regel 3
  per Mail.
- **§5.47** — Verhaltensneutralität belegen: die Layer-4-Tests für Geräte
  **ohne** Nachweis müssen ohne Anpassung grün bleiben.
- **B-20c-4** — fehlende Isolation im Health-Task; betrifft Regel 2, weil sie
  auf genau diesem Task aufsitzt. Sollte vor oder mit 20e erledigt werden.
