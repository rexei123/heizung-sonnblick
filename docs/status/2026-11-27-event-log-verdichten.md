# event_log verdichten — und der S3-Punkt, der zuerst zu klären war (27.11.2026)

## Teil 1: der S3-Punkt, geklärt und belegt

**Die Frage.** `event_log.room_id` hängt mit `ON DELETE CASCADE` an
`room.id`. Was passiert mit dem Engine-Trace, wenn ein Zimmer gelöscht
wird?

**Der Befund, gemessen und nicht vermutet.** Er wird mitgelöscht — jede
Zeile, für alle vergangenen Tage, und **lautlos**: die Datenbank führt
den Cascade aus, niemand schreibt etwas darüber. Danach ist die Frage
„warum war das Zimmer kalt" für dieses Zimmer nicht mehr beantwortbar.

`DELETE /api/v1/rooms/{id}` steht jedem Administrator offen; die einzige
Schranke ist eine aktive Belegung. Sieben Tabellen hängen am Cascade:

| Tabelle | was verloren geht |
|---|---|
| `event_log` | **der Engine-Trace** — das Protokoll jeder Sollwert-Entscheidung |
| `heating_zone` | die Zonen des Zimmers (die Geräte selbst bleiben, `device.heating_zone_id` ist `SET NULL`) |
| `manual_override` | laufende und vergangene Wunschtemperaturen |
| `occupancy` | die Belegungsgeschichte |
| `rule_config` | Nachtfenster und Betriebszeit |
| `scenario_assignment` | Szenarien am Zimmer |
| `tagesplan_fenster` | der Tagesplan (seit #436) |

**§0 S3 verlangt**, dass jede Sollwert-Entscheidung im Trace steht und
dass es keine schnellen Pfade daran vorbei gibt. Eine Löschung, die den
Trace entfernt, ohne sich selbst zu protokollieren, ist genau dieser
Pfad.

### Was dieser PR dagegen tut

Eine Audit-Zeile `ROOM_DELETED`, **vor** dem Löschen, in derselben
Transaktion, mit den Zeilenzahlen **je Tabelle**. Ohne die Zahlen stünde
dort „ein Zimmer wurde gelöscht" statt „zwölf Trace-Zeilen sind weg".

`business_audit` hängt ausdrücklich **nicht** an `room` — die Zeile
überlebt also das Zimmer, dessen Löschung sie beschreibt. Hätte sie einen
Cascade, würde sie im selben Zug verschwinden, in dem sie von ihrem
Verschwinden berichtet.

**Die Liste der Tabellen prüft ein Test gegen das Schema**, nicht gegen
eine Erinnerung: welche Fremdschlüssel auf `room.id` haben
`confdeltype = 'c'`? Genau die muss `CASCADE_TABELLEN` nennen. Kommt eine
Tabelle dazu, fällt der Test — eine unvollständige Liste zählt still zu
wenig. (Der Test hat sich dabei selbst korrigiert: die erste Fassung der
Abfrage zählte auch die **Chunks** der Hypertable mit, weil jeder Chunk
den Fremdschlüssel erbt.)

### Was dieser PR **nicht** tut, und warum

**Er sperrt nichts.** Ob ein Zimmer mit Trace überhaupt löschbar bleiben
soll, ist eine Entscheidung des Betreibers. Zwei Wege:

| Weg | Wirkung | Preis |
|---|---|---|
| **409 im Endpunkt**, wenn `event_log`-Zeilen existieren | ein Zimmer mit Geschichte ist nicht löschbar | ein Tippfehler bei der Zimmernummer bleibt für immer in der Liste; es braucht dann einen zweiten Weg (etwa „stilllegen") |
| **`ON DELETE RESTRICT`** in einer Migration | dieselbe Wirkung, eine Ebene tiefer, greift auch bei `psql` | **nicht additive** Migration (AE-77): eine verengte Beschränkung, also mit Zeile im Docstring und ohne Rückfallweg per `PIN_SHA` |

Mein Vorschlag ist der **Endpunkt-409 mit einem Stilllege-Weg daneben** —
die Datenbank-Variante schützt mehr, nimmt aber dem Betreiber die
Möglichkeit, ein falsch angelegtes Zimmer wieder loszuwerden, und das ist
ein Fall, der öfter vorkommt als eine versehentliche Löschung. Beides ist
eine Entscheidung und kein Bauauftrag; dieser PR macht den Verlust
sichtbar, bevor jemand sie trifft.

## Teil 2: die Verdichtung

**Der Anlass:** `event_log` wächst um rund **4,8 GB im Monat** (gemessen
14.11.2026). Am 13.11. war die Platte zu 94 % belegt, gefunden beim
Nachsehen nach etwas anderem. Bei 100 % nimmt Postgres keine
Schreibvorgänge mehr an.

**Verdichten, nicht löschen.** Alte Zeilen wegzuwerfen wäre der andere
Weg und derselbe S3-Verstoß wie oben, nur absichtlich. TimescaleDB legt
alte Chunks spaltenweise ab: keine Zeile geht verloren, Abfragen lesen
weiter.

### Die Vorprüfung, und was sie wert ist

Eigene Datenbank im Test-Container, dasselbe Image
(`timescale/timescaledb:latest-pg16`, TimescaleDB **2.26.3**), 6 Millionen
Zeilen in der Form des Betriebs (sechs Schichtzeilen je Auswertung, jede
mit dem üblichen JSONB-Kontext):

| | |
|---|---|
| je Chunk vorher | **148 MB** |
| je Chunk nachher | **2,6 MB** |
| Faktor | **57** |
| Lesen aus einem verdichteten Chunk | unverändert, 5088 Zeilen |
| Schreiben in den jungen Chunk | unverändert |
| `ON DELETE CASCADE` durch einen verdichteten Chunk | **läuft durch**, alle 12 000 Zeilen weg |

Der Faktor ist so hoch, weil der JSONB-Kontext sich wiederholt: nach der
Umstellung steht er einmal statt tausendmal.

**Das ist eine Messung an nachgebauten Daten, keine Zusage für die
Anlage** — und deshalb sagt der Trockenlauf des Werkzeugs „Faktor dieser
Datenbank: **unbekannt**", solange kein Chunk verdichtet ist. Erst nach
dem ersten echten Lauf nennt er eine Zahl, und dann ist es eine gemessene
(§5.68). Eine Mutationsprobe setzt dort die 57 ein; der Test geht rot.

**Zwei Formen geprüft, nicht eine geraten:** `segmentby = room_id` mit
`orderby = time DESC` ergibt Faktor 58,6, mit den übrigen
Primärschlüssel-Spalten im `orderby` 57,2. Gebaut ist die zweite — der
Unterschied ist kleiner als der Grund: ohne die Spalten warnt TimescaleDB,
und eine Eindeutigkeit, die die Datenbank nach der Verdichtung nicht mehr
prüfen kann, ist keine.

### Das Werkzeug

`scripts/event_log_verdichten.py`:

| Aufruf | Wirkung |
|---|---|
| ohne Schalter | **Trockenlauf**: zählt Chunks, Platz, Faktor. Ändert nichts |
| `--ausfuehren` | verdichtet die offenen Chunks, Chunk für Chunk, je einer eine eigene Transaktion |
| `--zuruecknehmen` | der **Rückweg**: packt wieder aus, mit Warnung über den Platz |
| `--aelter-als-tage` | Vorgabe 14. Unter 7 bricht es ab — darunter liegt der laufende Chunk |

**Es läuft nicht von selbst.** Kein Beat-Eintrag, keine
`add_compression_policy`, kein Aufruf aus einer Migration — ein Lauf nach
dem Merge war ausdrücklich nicht gewollt. Eine Migration hätte genau das
getan.

**Wiederholbar:** ein schon verdichteter Chunk bricht den Lauf nicht ab,
er wird übersprungen und gezählt. Im Wartungsfenster wird ein Befehl auch
zweimal getippt.

### RUNBOOK §10bh

Vier Schritte, jeder mit Prüfung: nachsehen (Trockenlauf) → sichern →
verdichten → Rückweg. Die Sicherung benutzt **denselben Befehl** wie
§10ab Schritt 0.2; zwei Formen derselben Sicherung wären zwei Wahrheiten
darüber, was „gesichert" heißt. Die Abnahme nach dem Lauf ist die
**Zeilenzahl** — sie muss dieselbe sein wie vorher.

## Mutationsproben

Sieben, jede einzeln gesetzt und zurückgenommen:

| # | Mutation | Rot |
|---|---|---|
| 1 | Der Trockenlauf verdichtet doch | 1 |
| 2 | `--ausfuehren --zuruecknehmen` zusammen erlaubt | 1 |
| 3 | Grenze unter 7 Tagen erlaubt | 1 |
| 4 | Audit-Zeile ohne Zahlen (`mit_geloescht = {}`) | 1 |
| 5 | Audit **nach** dem Löschen geschrieben (Zahlen 0) | 1 |
| 6 | Eine Tabelle fehlt in `CASCADE_TABELLEN` | 2 |
| 7 | Faktor 57 aus der Vorprüfung statt „unbekannt" | 1 |

## Zahlen

* **2337 Tests** grün (vorher 2324), 60 übersprungen, 1 xfailed.
* `ruff check`, `ruff format --check`, `mypy src` ohne Befund.
* Keine Migration. Die Verdichtungs-Eigenschaft setzt das **Werkzeug**,
  nicht Alembic — in einer Migration wäre sie ein automatischer Lauf nach
  dem Merge.
* Kein Frontend berührt.

## Offen

* **Die Entscheidung aus Teil 1** (409 oder `RESTRICT` oder so lassen).
* **Eine Policy statt Handgriff.** Nach dem Lauf wächst `event_log`
  weiter; in einigen Wochen stehen neue Chunks jenseits der Grenze.
  `add_compression_policy` wäre die dauerhafte Antwort und ein eigener
  PR — sie tut automatisch, was heute ausdrücklich von Hand geschieht.
* **Der echte Lauf auf dem Server** steht in der Laufliste
  (Wartungsfenster), nicht in diesem PR.
