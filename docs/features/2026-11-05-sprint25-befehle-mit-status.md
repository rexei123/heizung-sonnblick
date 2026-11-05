# Sprint 25 — Befehle mit Status: offen → zugestellt → bestätigt

**Stand:** 2026-11-05 · **Befund aus der Analyse zu Zimmer 306**, am Code
und an der Datenbank belegt · **Bau ab Montag 09.11.2026** (Freigabe des
Betreibers 05.11.) · **Autonomie-Stufe 1** — Steuerlogik mit
Concurrency und Hardware-Befehlspfad

---

## 0. Die Befunde

Alle Zahlen sind gelesen, nicht geschätzt; Stand 05.11.2026, Zeitraum ab
01.10.2026.

### Befund A — widersprüchliche Sollwerte in der Warteschlange

**125 Fälle auf 42 Geräten:** zwei **verschiedene** Sollwerte an dasselbe
Gerät innerhalb von 10 Minuten, also innerhalb der Zustellzeit eines
Class-A-Geräts. Beide liegen damit gleichzeitig in der ChirpStack-Queue.
Mittlerer Abstand **117 Sekunden**, die engsten:

| Gerät | erster Befehl | Abstand | Sollwerte |
|---|---|---|---|
| 67 | 22.10. 21:21:21 | **7 s** | 22,00 → 25,00 |
| 55 | 05.10. 11:39:41 | **7 s** | 25,00 → 21,00 |
| 55 | 05.10. 11:39:48 | **7 s** | 21,00 → 25,00 |
| 85 | 19.10. 04:35:51 | **7 s** | 19,00 → 25,00 |

Gerät 55 bekam am 05.10. in **14 Sekunden** 25 → 21 → 25.

§0 S4 sagt wörtlich: *„Keine widersprüchlichen Setpoints in der
ChirpStack-Queue."*

**Was dabei sichtbar wird und was nicht.** Der Endzustand ist richtig —
das Gerät landet auf dem letzten zugestellten Wert. Der Preis ist eine
**überflüssige Ventilbewegung je Doppelbefehl** (Motor, Batterie) und ein
Trace, der wie ein Widerspruch aussieht. Am 22.10. um 06:39 trug Gerät 85
innerhalb von 15 Sekunden drei Sollwerte (30 → 20 → 25) — die drei
Uplinks haben `fcnt` 3261, 3262, 3263, es war die Queue beim Abfließen.
Wer das ohne diesen Zusammenhang liest, sucht eine Engine-Schwingung, die
es nicht gibt: **in den Befehlen** gibt es hausweit **0** Fälle von drei
verschiedenen Sollwerten in 60 Sekunden.

### Befund B — kein Befehl wird bestätigt

**`acknowledged_at` ist bei 0 von 14.020 Befehlen gesetzt**, 14.010 sind
als gesendet markiert. §0 S4: *„Keine Befehle ohne
Bestätigungs-Strategie."* Das Feld existiert und wird nie gefüllt.

### Befund C — die Trace-Lücke (S3)

Die Spur der 30-°C-Entscheidung vom 16.10. (`evaluation_id 8e8cdb67…`):

```
base_target        21.0 -> 21.0   occupied_setpoint   status=occupied
manual_override    21.0 -> 21.0   occupied_setpoint   "no active override"
hard_clamp         21.0 -> 21.0   occupied_setpoint   within [10,30]
```

Alle Schichten auf **21,0**, „keine aktive Übersteuerung" — und derselbe
`evaluation_id` trägt im `control_command` den Wert **30,00**. Die
Übersteuerung hängt an der **Zone** (`heating_zone_id=274`), die
Schichtspur rechnet auf **Zimmer**-Ebene, und der Zonenwert greift erst
im Versand je Gerät.

**Wer den Trace liest, sieht 21 und das Gerät bekommt 30.** Das ist die
Auditierbarkeit aus §0 S3, blind an genau der Stelle, an der der Gast die
Steuerung übernimmt.

---

## 1. Die Gewichtung — und wo ich widerspreche

**Einschätzung des Betreibers:** *„Bestätigung gibt es heute schon
indirekt über den Abgleich. Die Lücke ist pro Befehl, nicht
grundsätzlich."*

**Zustimmung, und zwar stärker als formuliert.** Der Abgleich vergleicht
den **gemeldeten** Sollwert des Geräts mit dem der Engine und erzwingt
bei Abweichung einen Downlink. Er bestätigt damit den **Zustand**, nicht
den Befehl — und das ist nach §5.76 die richtige Sache zum Überwachen:
**Wirkung statt Mechanik.** Ein Befehl-für-Befehl-Ack ist Mechanik.

**Deshalb wird in diesem Sprint kein Tor gebaut, das an einer
Befehlsbestätigung hängt.** Das wäre S6-pflichtig und würde die
Steuerung komplizierter machen, um eine Frage zu beantworten, die der
Abgleich schon beantwortet.

**Ein Punkt, an dem ich widerspreche.** Der Abgleich hat ein Loch, und es
ist nicht „pro Befehl":

> Er gibt nach drei Versuchen auf, und das einzige Signal ist eine
> Audit-Zeile. **Gerät 7** (Etikett 001, Zimmer 52, Schlafzimmer L) zeigt,
> was dann passiert: Erschöpfung am 01.11. bei „Engine 15, Gerät 18" — und
> am 04.11. hat die **Engine ihren Wunsch auf 18 geändert**
> (`vacant_setpoint`). Seitdem stimmt es wieder, aber **nicht weil das
> Gerät gehorcht hat, sondern weil das Ziel zu ihm gewandert ist.**

Ein Melder, dessen Befund durch eine Zieländerung gelöscht wird,
überwacht nichts. Das ist §5.79 im Steuerpfad und gehört behoben —
unabhängig von A und B. Es ist **T3**.

---

## 2. Die technische Lage, die die Varianten vorentscheidet

**Wir haben keinen Zugriff auf die Warteschlange.** Im ganzen Backend
gibt es kein `FlushQueue`, kein `GetDeviceQueue`, nichts — Downlinks sind
MQTT-Publishes, und AE-48 hat den gRPC-Pfad für Gerätebefehle bewusst
nicht geöffnet (§5.28).

**Damit fällt jede Flush-Variante aus, und zwar aus zwei Gründen.** Der
erste ist der Betreiber-Vorbehalt und er trifft genau zu: ein Flush
löscht auch **Konfigurationsbefehle** — `0x07` Kindersicherung, `0x08`
Grenzen (Byte-Nummern geprüft in `downlink_adapter.py`). Der zweite ist,
dass ein Flush erst den gRPC-Pfad bräuchte.

**Wir können also nur eines ändern: was wir senden.** Das genügt.

### Verworfen: Zurückhalten („offener Befehl sperrt den nächsten")

Marker je Gerät, ein widersprechender zweiter Wert wird unterdrückt.
**Ausschlussgrund:** der erste Wert liegt schon in der Queue und **kommt
trotzdem an**. Beim Fall 20 → 25 landet das Gerät auf 20 und bleibt dort
bis zur nächsten Auswertung — also zehn Minuten auf dem falschen Wert
statt einer überflüssigen Bewegung. **Gleich viele Bewegungen, längerer
Fehlzustand.** Das macht es schlechter.

---

## 3. Die Aufgaben

### T1 — Entprellen vor dem Senden (**der Kern**)

Nicht sofort publizieren. Je Gerät ein Fenster von **60–120 s** sammeln
und nur den **letzten** Wert senden. Aus 20 → 25 in 100 Sekunden wird
**ein** Publish mit 25.

| Dafür | Dagegen |
|---|---|
| Die überflüssige Bewegung entsteht nie | Jede Sollwertänderung verzögert sich um das Fenster |
| Kein Queue-Zugriff, kein Flush, kein 0x07/0x08-Risiko | Ein Zustand mehr in Redis |
| Der Abgleich bleibt unberührt und räumt weniger auf | Fenstergröße ist eine Abwägung, keine Herleitung |
| Wirkt auf **alle** 125 Fälle | |

**Zur Verzögerung:** beim Drehrad hat das Gerät den Gastwunsch **lokal
schon angewendet**; unser Downlink ist die Korrektur, und eine Korrektur
60 s später ist harmlos. Bei Nachtabsenkung ist eine Minute nichts.

**Pflicht (S5):** bei nicht erreichbarem Redis fällt das Entprellen
**zum Senden hin** aus, nicht zum Schweigen. Ein Puffer, der bei Störung
Befehle verschluckt, ist schlimmer als der Zustand heute. Vorlage:
`services/resync_flag.py` (`mark_pending` / atomares `consume` via
`GETDEL`) und `engine_abgleich.darf_senden`, das bei Redis-Ausfall
protokolliert und fortfährt.

**Offen, Pflicht-Stop:** **der Boost.** `services/boost.py` legt eine
Übersteuerung an, die Engine versendet sie — also läuft er heute durch
denselben Pfad und würde entprellt. Ein Boost ist aber die eine
Sollwertänderung, die der Gast **sofort spüren soll**. Entweder er
umgeht das Entprellen, oder er bekommt das untere Ende des Fensters.
**Das ist eine Produktentscheidung, keine technische** — sie gehört in
den Stop vor T1.

### T2 — `acknowledged_at` füllen, als reine Buchführung

Aus dem passenden Uplink setzen: der `0x81`-Sollwert bzw. die
`0x52`-Antwort stimmt mit dem gesendeten Wert überein.

**Keine Logik hängt daran.** Kein Tor, keine Wiederholung, keine
Alarmschwelle. Begründung oben: der Zustand ist das Richtige zum
Überwachen, nicht der Befehl. Der Nutzen ist Diagnose — und Ehrlichkeit:
solange das Feld leer ist, sieht jeder Befehl aus wie „nie angekommen".

**Abgrenzung, die im Test festgehalten wird:** ein Uplink bestätigt den
**jüngsten offenen** Befehl mit diesem Wert, nicht jeden. Sonst quittiert
ein zufällig passender Periodenbericht einen Befehl, der nie zugestellt
wurde.

### T3 — Abgleich-Erschöpfung bleibt stehen

Eine erschöpfte Lage bleibt bestehen, bis das Gerät **einmal** bestätigt
hat. Sie darf **nicht** dadurch verschwinden, dass die Engine ihren
Wunsch verschiebt (Gerät 7, 04.11.).

Heute ist der Zustand ein Redis-Zähler plus eine Audit-Zeile. Nach T3
gehört dazu ein Merker, der erst durch eine Übernahme fällt — und eine
Sicht, die ihn zeigt. **Welche Sicht**, ist offen und gehört in den Stop:
Geräteseite, Dashboard-Kachel oder Mail. Mein Vorschlag ist die
**Geräteseite**, weil der Befund geräte-eigen ist und dort schon die
Batterie- und Funk-Achsen stehen.

### T4 — der Trace zeigt den gesendeten Wert je Gerät

`downlink_per_device` im `hard_clamp`-Eintrag trägt bereits `dev_eui`,
`zone_id`, `device_id`, `status` und `hysteresis_reason` — **es fehlt
genau der gesendete Sollwert.** Ein Feld mehr im JSONB, additiv, **keine
Migration** (AE-55 / §5.44).

Dazu: die Schicht `manual_override` soll nicht „no active override"
melden, wenn für **eine Zone** des Zimmers eine Übersteuerung steht,
sondern das benennen.

**Warum im selben Sprint wie T1:** T1 ändert, *was* gesendet wird. Ein
Trace, der das nicht zeigt, macht die Abnahme von T1 unmöglich — man
könnte nicht unterscheiden, ob das Entprellen gewirkt hat oder ob ein
Befehl verloren ging. Eine Prüfung für beides.

### T5 — Konfigurationsbefehle gehen sofort, und die Reihenfolge wird geprüft

**Vorgabe des Betreibers:** Entprellen gilt **nur für Sollwerte**
(`0x51`). `0x07` (Kindersicherung), `0x08` (Grenzen) und `0x45`/`0x46`
(Fenstererkennung) gehen unverändert sofort raus.

Das ist nicht nur zulässig, es ist die bessere Reihenfolge: Class A
stellt in Einreihungsfolge zu, also kommen Konfigurationsbefehle **vor**
einem entprellten Sollwert an — Grenzen zuerst, dann der Wert, der sie
einhalten muss.

**Was dabei zu prüfen ist, und es ist der unangenehme Teil:**

> `hard_clamp` klammert auf die **Raumtyp**-Spanne (im Trace sichtbar als
> `within [10,30]`), **nicht** auf die Grenzen, die im Gerät stehen (seit
> 28.10. **15–25**, bei Bad-Zonen 18–25). Ein Sollwert von 30 passiert
> `hard_clamp` und wird vom Gerät abgewiesen oder geklammert — unser
> `control_command` sagt 30, das Gerät meldet 25, und der Abgleich
> kämpft, bis er erschöpft ist.

Das ist **kein** neues Risiko aus T1 — es besteht heute. T1 vergrößert
nur das Fenster, in dem ein `0x08` dazwischenkommen kann.

**Umfang in diesem Sprint: erkennen und melden, nicht beheben.** Eine
Prüfung, die beim Versand feststellt, wenn der Sollwert außerhalb der
**bestätigten** Gerätegrenzen liegt (`sensor_reading.temp_range_min` /
`_max`, Migration 0035), und das im Trace und als Audit-Zeile vermerkt.
Damit wird aus einem unsichtbaren Kampf ein Befund.

**Wer die Grenzen gewinnen soll — Raumtyp oder Gerät — ist eine eigene
Entscheidung** und gehört nicht in diesen Sprint. Sie zu treffen, bevor
der Befund vorliegt, wäre die falsche Reihenfolge.

---

## 4. Abnahme

| | Kriterium | Wie gemessen |
|---|---|---|
| A | Keine zwei verschiedenen Sollwerte je Gerät binnen 10 min | dieselbe Abfrage wie Befund A, über eine Woche nach dem Deploy; heute 125 Fälle / 42 Geräte |
| B | `acknowledged_at` ist bei der Mehrheit der Befehle gesetzt | Quote vorher **0 von 14.020** |
| C | Eine erschöpfte Abgleich-Lage überlebt eine Zieländerung | Test mit Gerätedoppel |
| D | Der Trace nennt je Gerät den gesendeten Wert | Spur eines Zimmers mit Zonen-Übersteuerung; heute zeigt sie 21 bei gesendeten 30 |
| E | Konfigurationsbefehle sind unverzögert | Test: `0x08` und ein Sollwert in derselben Auswertung |

**Mutationsproben** sind für jede Aufgabe Pflicht und werden im PR
benannt — nicht „Tests grün", sondern welcher Test bei welcher
Verfälschung fällt.

---

## 5. Nicht in diesem Sprint

* **Kein Queue-Zugriff, kein gRPC-Pfad für Gerätebefehle** (AE-48 bleibt).
* **Kein Flush** — Begründung oben, zweifach.
* **Kein Tor, das an `acknowledged_at` hängt.**
* **Keine Entscheidung, wessen Grenzen gewinnen** (T5 liefert den Befund).
* **Die Fenstererkennung** läuft getrennt weiter (Schritt 2, eigener PR).

## 6. Querverweise

* §0 S2 (Determinismus), S3 (Auditierbarkeit), S4 (Hardware-Schutz),
  S5 (defensiv bei externen Quellen), S6 (Komplexität trägt Beweislast)
* §5.76 (Wirkung statt Mechanik — die Begründung gegen den Lebenszyklus)
* §5.79 (ein Audit gilt nur für den Stand, den es gesehen hat — T3)
* §5.28 / AE-48 (Downlinks über MQTT, gRPC bewusst zu)
* AE-55 / §5.44 (JSONB-Sub-Trace statt PK-Migration — T4)
* AE-45 (Drehrad-Auto-Detect — die Quelle der 125 Fälle)
* AE-63 / `services/resync_flag.py` (Vorlage für Redis-Zustand mit
  atomarem Verbrauch)
* `docs/status/2026-11-05-fenstererkennung-stand-lesbar.md` (der
  Analyse-Tag, aus dem diese Befunde stammen)
