---
datum: 2026-11-08
sprint: 25
thema: T4 — der Trace zeigt den gesendeten Wert und die Zonen-Übersteuerung
pr: 399
---

# Sprint 25 T4 — zwei Zeilen im Trace, und bei beiden war die Lage anders als angenommen

## 1. Der gesendete Wert je Gerät

**Die Vorgabe lautete:** `downlink_per_device` im `hard_clamp`-Eintrag
bekommt den tatsächlich gesendeten Sollwert je Gerät; im Brief steht „es
fehlt genau der gesendete Sollwert".

**Der Befund:** `setpoint_c` steht je Gerät **schon** im Trace, seit dem
31.10.2026 (`d576e68`, Sprint 23 T1a). Die Brief-Annahme ist vier Tage
jünger als ihre Erledigung — §5.77 in Reinform, und der Grund, warum eine
Vorgabe mit einem `grep` beginnt und nicht mit einer Zeile Code.

**Was wirklich fehlte**, ist die Unterscheidung zweier Fragen, die heute
dieselbe Zahl haben:

| Feld | Frage |
|---|---|
| `setpoint_c` | was war die **Absicht** dieser Zone in diesem Tick |
| `gesendet_c` | was ist **hinausgegangen** |

Heute sind sie für jede gesendete Zeile gleich. **Nach T1 (Entprellen)
nicht mehr** — dort entscheidet nicht mehr der Tick allein, was hinausgeht,
und dann ist `gesendet_c` die einzige Stelle, an der sich „entprellt" von
„verloren" unterscheiden lässt. Genau das ist der Grund, aus dem der Brief
T4 in denselben Sprint legt wie T1.

Bei den anderen beiden Zuständen unterscheiden sie sich **schon heute**:

* `skipped_hysteresis` → `gesendet_c: null`. Eine Zahl an dieser Stelle
  liest sich als gesendet.
* `failed` → `gesendet_c: null`. Der Publish hat geworfen, beim Gateway
  ist nichts angekommen.

**Dazu eine Quelle statt zweier.** Der Downlink nahm seinen Wert bisher
ein zweites Mal aus `zone_target_setpoint_c`, parallel zum
`ControlCommand`. Zwei Ableitungen desselben Wertes können auseinander­
laufen (§5.53); jetzt liest `send_setpoint` aus `cc.target_setpoint`.

## 2. „no active override" bei einer Zonen-Übersteuerung

**Die Vorgabe:** Die Schicht `manual_override` soll eine aktive
Zonen-Übersteuerung benennen statt „no active override" zu melden.

**Der Befund, und er halbiert die Aufgabe:** In der **Oberfläche** ist das
seit Sprint 12b T4 bereits richtig. Das Trace-Panel zeigt „kein
zimmerweiter Override — siehe **Pro-Zone-Setpoints**", sobald
`zone_overrides_trace` gefüllt ist, und darunter einen Block je Zone.

Falsch war allein die **gespeicherte** Zeile: `event_log.details.detail`
sagt wörtlich „no active override". Wer die Datenbank liest, liest „für
dieses Zimmer gilt keine Übersteuerung" — und das ist falsch, wenn das Bad
auf 23 steht. Behoben ist jetzt der Datensatz, nicht die Anzeige.

**Wo der Zweig sitzt, und warum nicht früher.** Nicht im Zonen-Loop,
sondern am Ende von `evaluate_room`: dort ist `zone_overrides`
endgültig. Layer 4 kann den Dict bei offenem Fenster **vollständig
verwerfen**, Layer 5 kappt die Werte. Eine Zeile, die eine verworfene
Übersteuerung nennt, wäre die nächste Falschaussage.

`extras["source"]` bleibt `None`. Daran hängt `raumweit_eingegriffen` und
damit die Bad-Vorlage — zimmerweit ist hier gerade **nicht** eingegriffen
worden.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| `gesendet_c` aus der Zonen-Variablen statt aus dem Befehl | **grün — unentschieden, siehe unten** |
| übersprungenes Gerät trägt einen gesendeten Wert | **1 Test rot** |
| fehlgeschlagener Downlink trägt einen gesendeten Wert | **1 Test rot** |
| Zonen-Zweig in der Schicht entfernt | **1 Test rot** |
| Zonen-Zweig greift immer, auch ohne Übersteuerung | **1 Test rot** |

**Die erste Probe ist ein Gleichstand, und das ist keine Testlücke.**
Heute ergeben beide Ausdrücke dieselbe Zahl; kein Test kann sie
unterscheiden, ohne Produktionscode zu verbiegen. Die eine Quelle ist
Vorbereitung auf T1, nicht eine Wirkung von heute. Was der Test
tatsächlich sichert, ist strenger als die Zuweisung: `gesendet_c` wird
gegen den Wert geprüft, den die **Downlink-Attrappe empfangen** hat, nicht
gegen die Zielvariable (§5.55).

## Läufe

* Backend **1877 passed, 45 skipped** — `TEST_DATABASE_URL` gesetzt, die
  DB-Tests sind gelaufen.
* Kein Frontend-Code berührt.

## Nebenbefund: `downlink_per_device` hat keinen Leser

`downlink_zone_status` wird an vier Stellen gelesen (`room_history`,
`event_log`, `heating_zones`-API). `downlink_per_device` **nirgends** —
nur geschrieben. Es ist damit reine Auditspur für S3, und für diesen Zweck
richtig; wer es anzeigen will, braucht einen Konsumenten. Nicht in diesem
PR (§5.1), aber vermerkt, damit es nicht als „die Kachel liest das schon"
missverstanden wird.
