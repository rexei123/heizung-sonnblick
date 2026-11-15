---
datum: 2026-11-15
thema: Verdichtung von event_log — Vorprüfung mit Messungen
pr: —
---

# event_log ist die Datenbank

## Gemessen am Server, 15.11.2026 (lesend)

| | |
|---|---|
| `event_log` | **11 GB**, **21 317 194 Zeilen**, 29 Chunks |
| `sensor_reading` | 187 MB, 200 Chunks |
| `relay_reading` | 488 kB, 3 Chunks |
| **Datenbank gesamt** | **11 GB** |
| Älteste Zeile | 2026-06-05 |
| Verdichtung | **auf keinem Hypertable aktiv** |

`event_log` ist nicht ein Teil der Datenbank, es **ist** sie: 99 % der
11 GB. `sensor_reading` mit 102 Geräten im Zehn-Minuten-Takt ist dagegen
187 MB.

**Zuwachs, je Tag:**

| Tag | Zeilen |
|---|---|
| 12.11. | 186 424 |
| 13.11. | 314 501 |
| 14.11. | 316 452 |

Also rund **315 000 Zeilen am Tag**, gleichmäßig über sieben Schichten:

```
window_safety 45080 · device_detached 45080 · hard_clamp 45080
base_target 45080 · manual_override 45080 · summer_mode_fast_path 45080
temporal_override 45080 · inferred_window_observation 6
```

45 080 Auswertungen am Tag auf 47 Zimmer — eine je Zimmer und 90 Sekunden.
Bei ~550 Byte je Zeile sind das **170 MB am Tag**, **5 GB im Monat**. Die
Platte hat nach dem Aufräumen 27–31 GB frei; ohne Maßnahme ist sie in
etwa einem halben Jahr wieder voll.

**Primärschlüssel und Indizes:**

```
event_log_pkey           PRIMARY KEY (time, room_id, evaluation_id, layer)
event_log_time_idx       (time DESC)
ix_event_log_room_time   (room_id, time DESC)
ix_event_log_evaluation  (evaluation_id)
fk_event_log_room        room_id -> room(id) ON DELETE CASCADE
fk_event_log_device      device_id -> device(id) ON DELETE SET NULL
```

## Die Probe: dieselbe Version, dieselbe Form, nicht die Produktion

Der Server wird heute nicht angefasst. Gemessen habe ich stattdessen in
einer **Wegwerf-Datenbank im lokalen Timescale-Container** — und der hat
**genau dieselbe Version wie die Produktion: 2.26.3**. Nachgebaut sind
Tabelle, Primärschlüssel, beide Indizes, `chunk_time_interval` von sieben
Tagen und ein `details`-JSONB in der Form, die der Engine-Trace wirklich
schreibt (`downlink_zone_status` mit einem Zonen-Eintrag, `hysteresis`).

**1 419 120 Zeilen → 827 MB.** Das sind 583 Byte je Zeile gegen 550 in
der Produktion: die Probe ist realistisch.

### Was die Messung ergibt

```sql
ALTER TABLE event_log SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'room_id',
    timescaledb.compress_orderby = 'time DESC'
);
```

| Frage | Messung |
|---|---|
| **Blockiert der Primärschlüssel das Einschalten?** | **Nein.** `ALTER TABLE` in 14 ms, mit zwei Warnungen: `evaluation_id` und `layer` „should be used for segmenting or ordering" |
| **Größe nach dem Verdichten** | 827 MB → **14 MB**, Faktor **59** |
| **Laufzeit** | **9,8 s** für 1,42 Mio Zeilen (2 Chunks) |
| **INSERT in einen verdichteten Chunk** | **funktioniert**, 12 ms |
| **Greift der Primärschlüssel dort noch?** | **Ja** — der doppelte INSERT wurde abgewiesen: `duplicate key value violates unique constraint "1_1_event_log_pkey"` |
| **UPDATE auf einem verdichteten Chunk** | **funktioniert**, 280 Zeilen in 34 ms |
| **DELETE aller Zeilen eines Zimmers** | **funktioniert**, 28 080 Zeilen in **5,5 ms** |

### Die drei Leser, vorher und nachher

| Abfrage | unverdichtet | verdichtet |
|---|---|---|
| (A) Engine-Panel: jüngste `hard_clamp`-Zeile, 3 Zimmer | 12,5 ms | 19,1 ms |
| (B) Zimmerverlauf: ein Zimmer, ein Tag, alle Schichten | 1,7 ms | 2,0 ms |
| (C) Relais-Regler: Zonen-Soll aus der jüngsten Zeile | 1,0 ms | 1,4 ms |

Alle drei werden **langsamer, und zwar unerheblich** — im schlechtesten
Fall 7 ms absolut. `segmentby = room_id` ist dafür der Grund: alle drei
Leser filtern auf `room_id` und greifen damit genau ein Segment.

## Antworten auf die Fragen aus dem Auftrag

**`segmentby = room_id`, `orderby = time DESC`: passend zu den Lesern?**
Ja, und die Messung zeigt es. Jeder der drei Leser hat `room_id` in der
`WHERE`-Klausel und sortiert nach `time DESC`. Die Warnungen zu
`evaluation_id` und `layer` sind zu lesen, aber nicht zu befolgen:
`evaluation_id` ist nahezu eindeutig, als `segmentby` ergäbe das ein
Segment je Zeile und **keine** Verdichtung. `layer` als zweites
`segmentby` wäre denkbar (acht Werte) — es würde die Segmente verkleinern
und damit den Faktor senken. Ohne Not nicht.

**Temporärer Platzbedarf bei der ersten Verdichtung — nicht 11 GB.**
TimescaleDB verdichtet **chunkweise**: der verdichtete Chunk wird
geschrieben, dann der alte verworfen. Der Spitzenbedarf ist also ein
Chunk plus seine verdichtete Form, nicht die ganze Tabelle. Bei 11 GB auf
29 Chunks sind das ~380 MB je Chunk, Spitze also **unter 500 MB** — bei
27 GB frei keine Frage. In der Probe lief es über zwei Chunks ohne
Auffälligkeit.

**Läuft sie chunkweise, ohne die Schreiblast zu blockieren?** Chunkweise
ja, das ist der Mechanismus. Zur **Schreiblast** habe ich keine Messung:
dafür müsste parallel geschrieben werden, und der Engine-Takt lässt sich
in einer Wegwerf-Datenbank nicht nachbilden. Was ich belegen kann: ein
`INSERT` **in einen verdichteten Chunk** geht (12 ms), und der laufende
Schreibpfad trifft ohnehin den jüngsten, **un**verdichteten Chunk. Die
offene Frage ist damit auf „sperrt `compress_chunk` einen Chunk, in den
gleichzeitig geschrieben wird" verengt — und für die Produktion gilt das
nur, wenn die Verdichtungsgrenze so knapp liegt, dass sie den aktiven
Chunk erfasst. **Bei einer Grenze von sieben Tagen passiert das nicht**,
der aktive Chunk ist jünger.

**UPDATE/DELETE auf `event_log`?** Beides geht, gemessen. Das deckt sich
mit der Timescale-Dokumentation: `UPDATE`/`DELETE` auf verdichteten
Chunks seit 2.11.0, Löschen ganzer Segmente ohne Entpacken seit 2.17.0.
Die 5,5 ms für 28 080 Zeilen eines Zimmers sind genau dieser Fall — mit
`segmentby = room_id` ist „ein Zimmer" ein ganzes Segment.

## Der unangenehme Nebenbefund

**Das macht `ON DELETE CASCADE` auf `event_log.room_id` schlimmer, nicht
besser.** Ein `DELETE FROM room WHERE id = …` löscht die Historie dieses
Zimmers, und nach der Verdichtung dauert das **fünf Millisekunden** statt
Sekunden. Eine Löschung, die schnell und lautlos ist, fällt niemandem
auf.

Der Backlog-Punkt (S3: `SET NULL` oder Zimmer nur stilllegen) steht schon
auf der Liste. Diese Messung ist ein Argument dafür, ihn **vor** die
Verdichtung zu setzen und nicht danach — die Verdichtung nimmt die
einzige natürliche Bremse weg.

## Vorschlag

**Weg A, ab 7 Tagen, kein Löschen** — wie besprochen:

```sql
ALTER TABLE event_log SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'room_id',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('event_log', INTERVAL '7 days');
```

Erwartung für die Produktion: **11 GB → unter 1 GB.** Den Faktor 59 aus
der Probe schreibe ich **nicht** fort — die Probe hat in jeder Zeile
dasselbe JSON, die Produktion variiert (Sollwerte, Gründe, Zonen-Ids).
Realistisch sind Faktor 10 bis 20, also 0,5 bis 1,1 GB. Selbst der
pessimistische Rand ist eine Zehntelung.

**Reihenfolge, die ich empfehle:**

1. Erst der `CASCADE`-Punkt (S3). Danach ist eine Löschung nicht mehr
   lautlos möglich.
2. Dann die Verdichtung, als eigener PR mit der Policy.
3. Die erste Verdichtung **im Merge-Fenster** anstoßen, nicht nachts: sie
   dauert bei 21 Mio Zeilen nach der Probe rund **zweieinhalb Minuten**
   CPU, und wer dabei zusieht, sieht auch, wenn etwas klemmt.
4. Nach der ersten Verdichtung die drei Leser messen — dieselben drei
   Abfragen wie oben, am Server. Die Probe sagt „unerheblich"; die
   Produktion hat andere Datenmengen je Zimmer.

**Was ich nicht vorschlage:** die Chunk-Grenze zu verkleinern, um früher
zu verdichten. Sieben Tage halten den aktiven Chunk außerhalb der
Verdichtung, und genau das macht die offene Frage zur Schreiblast
unerheblich.
