---
datum: 2026-11-21
thema: Tagesplan für Allgemeinbereiche — mehrere Zeitfenster am Tag
pr: offen
---

# Eine Zeit war zu wenig

**Migration additiv (0042, eine neue Tabelle). Kein Funkbefehl, keine
Server-Änderung.** Ohne Zeile in dieser Tabelle verhält sich die
Steuerung wie vorher.

## Der Wunsch

Der Betreiber, aus dem Brief in #421 (Punkt 12) und wörtlich wiederholt
am 21.11.2026: ein Allgemeinbereich soll **mehrere** Zeitfenster am Tag
haben, je Fenster eine eigene Solltemperatur. Beispiel aus dem Wunsch:
06:00–08:00 auf 25 °C, 08:00–21:00 auf 22 °C, sonst Absenkung.

## Was es schon gab, und warum es nicht reicht

Die Steuerung hat seit Sprint 9.8 **ein** Zeitfenster je Zimmer:
`rule_config.night_start` / `night_end` mit `t_night`. Seit Sprint 24d
tritt es bei einem Allgemeinbereich als **Betriebszeit** auf — dieselbe
Rechnung mit anderen Worten (`services/betriebszeit`: „außerhalb der
Betriebszeit ist bei einem Bereich genau das, was bei einem Gästezimmer
die Nacht ist").

Ein Bereich, der morgens wärmer sein soll als mittags, lässt sich damit
nicht beschreiben. Man müsste `t_night` als Tagwert missbrauchen und das
Fenster invertieren — ein Feld mit zwei Bedeutungen (§5.51) und der
Grund, es **nicht** so zu bauen.

> **Berichtigung einer Annahme des Betreibers.** Der Auftrag sagte, ohne
> Tagesplan solle sich alles „exakt wie heute" verhalten, nämlich wie
> „Raumtyp Betrieb/Absenkung". Der heutige Stand ist mehr als das: die
> Bereiche haben eine **Betriebszeit am Zimmer**, und die ist der Teil,
> mit dem der Plan sich vertragen muss. Ohne diese Korrektur wäre der
> Plan neben einem zweiten Zeitplan gelandet, von dem niemand gesprochen
> hat.

## Die Entscheidungen, und was sie gekostet haben

### Der Plan verdrängt die Betriebszeit, er ergänzt sie nicht

Beide gleichzeitig wirksam zu lassen hieße, zwei Zeitpläne übereinander
zu legen. Welcher bei einer Überschneidung gewinnt, wäre eine Regel, die
niemand sehen kann. Also: **steht ein Fenster, liest Schicht 2 das
Nachtfenster nicht mehr.**

Der Preis ist ein Formular, dessen Zahlen gerade nicht wirken — genau
§5.77. Bezahlt wird er mit einem Satz: solange ein Plan steht, sagt das
Betriebszeit-Formular, dass es ruht und wann es wieder gilt. Dasselbe im
Verlauf: `night_window` fällt weg, das Band kommt aus den **Lücken** des
Plans, und die Unterschrift sagt „Absenkung nach Tagesplan".

### Minuten seit Mitternacht statt `time`

„bis 24:00" ist bei der Betriebszeit ausdrücklich erlaubt. `time` kennt
diesen Wert nicht — als `00:00` gespeichert wäre das **Ende** kleiner als
der Anfang, und ein Fenster „15:00 bis 24:00" hätte keine Dauer. Mit
`0 … 1440` ist die Spanne halboffen `[von, bis)` und die
`EXCLUDE`-Bedingung ein `int4range`.

Die Schreibweise `HH:MM` steht seither **einmal** im Repo
(`heizung.uhrzeit`); `betriebszeit.parse_uhrzeit` ruft sie und bildet
weiter auf `time` ab. Dass dieser Auszug verhaltensneutral war (§5.47),
hält eine eigene Testgruppe fest — einschließlich der Abbildung
`24:00 → 00:00`, die die Betriebszeit braucht.

### Kein Fenster über Mitternacht

Abgewiesen, nicht zerlegt. Zwei Gründe: ein umschlagender Bereich ist mit
`int4range` nicht prüfbar, und „Lücke = Absenkung" wäre nicht mehr
eindeutig. Eine automatische Zerlegung in zwei Zeilen wäre freundlich und
falsch — danach stünden im Formular Zeilen, die niemand eingegeben hat.

### Eine Tabelle, nicht zwei — und keine Erbkette

Abweichend vom Brief, der einen `tagesplan` mit Namen und
Aktiv-Schalter plus drei Erbebenen vorschlug:

| Brief | Gebaut | Grund |
|---|---|---|
| Plan-Tabelle + Fenster-Tabelle | **eine** Tabelle | Ein Bereich hat einen Plan; „kein Plan" ist keine Zeile, nicht ein Schalter auf `false` (S6) |
| `name`, `aktiv` | keine | Die Bar hat schon einen Namen; beides additiv nachrüstbar |
| hausweit / Raumtyp / Zimmer | nur am Zimmer | Entscheidung der Betriebszeit vom 24.10.: „die Zeit gehört zum Ort, nicht zur Art". Ein hausweiter Plan wirkte auf 47 Gästezimmer, sobald ihn jemand anlegt |
| Oberfläche auf `/profile` | am Zimmer | Vorgabe des Betreibers. Die Betriebszeit steht einen Abschnitt darüber; zwei Orte für eine Frage wären der Zustand, in dem man künftig an beiden sucht |

`/profile` bleibt leer **und nennt den Weg**. Eine Seite, die „Tag-,
Nacht- und Wochenend-Heizprofile" verspricht, während es sie woanders
gibt, ist dasselbe wie ein Schalter ohne Wirkung.

### `PUT` mit der ganzen Liste

Drei Gründe, der dritte ist der harte: Idempotenz (§0 S2); die Prüfung
braucht den vollständigen Satz; und **zwei Fenster zu tauschen verletzt
bei jedem Einzelschritt die `EXCLUDE`-Bedingung**, ganz gleich mit
welchem man anfängt. Ein vollständiger Austausch in einer Transaktion hat
das Problem nicht.

### Die Überschneidungsprüfung dreimal

Keine Verdopplung, sondern drei verschiedene Fragen:

| Stelle | Frage | Reichweite |
|---|---|---|
| Zod (`lib/api/tagesplan`) | „ist das, was ich tippe, sinnvoll" | sofort, ohne Netz |
| Pydantic (`schemas/tagesplan`) | „ist das, was ankommt, sinnvoll" | jede Anfrage, auch `curl` |
| `EXCLUDE USING gist` | „gilt es auch bei zwei Admins gleichzeitig" | nur die Datenbank kann das (§5.60) |

Gemeinsam ist allen drei die Grenzauslegung: Fenster **stoßen aneinander
an**, 08:00 gehört dem Fenster, das dort beginnt.

### Kein neuer `CommandReason`

§5.45: der Enum trägt einen DB-CHECK auf zwei Tabellen. Ein Treffer
meldet `vacant_setpoint` („Betrieb-Sollwert" bei einem Bereich) mit
`sollwert_quelle = tagesplan` und der Fenster-Kennung im `detail`; eine
Lücke meldet `night_setback` mit `tagesplan_luecke`. Die Oberfläche nennt
die Herkunft „Tagesplan" — ohne eigene Marke stünde dort „Zimmer",
richtig in der Ebene und irreführend im Ort.

## Was gebaut wurde

| Datei | Inhalt |
|---|---|
| `alembic/versions/0042_tagesplan_fenster.py` | Tabelle, zwei `CHECK`, `EXCLUDE` mit `btree_gist` |
| `models/tagesplan.py` | `TagesplanFenster` |
| `uhrzeit.py` | `HH:MM` mit `24:00`, als Minuten — einmal im Repo |
| `rules/tagesplan.py` | Lesen, `fenster_bei`, `luecken` (Engine **und** Verlauf, §5.46) |
| `services/tagesplan.py` | `ersetze`, Audit-Form |
| `schemas/tagesplan.py` | Eingabeprüfung mit den Sätzen, die der Betreiber liest |
| `rules/engine.py` | Schicht 2 um den Plan erweitert, `_absenk_schritt` ausgezogen |
| `services/room_history.py` | `tagesplan_baender` aus den Lücken |
| `api/v1/rooms.py` | `GET`/`PUT /rooms/{id}/tagesplan`, 422 für Gästezimmer |
| `components/patterns/tagesplan-form.tsx` | Tabelle, Tagesleiste, Zod |
| `lib/api/tagesplan.ts` | Spiegel, Prüfung, Hook |

## Mutationsproben

Zehn, jede einzeln gesetzt und zurückgenommen:

| # | Mutation | Rot |
|---|---|---|
| 1 | Schicht 2 liest den Plan nicht | **18** Tests |
| 2 | Grenze beidseitig geschlossen (`<=`) | 4 |
| 3 | Lücke nach dem letzten Fenster fällt weg | 5 |
| 4 | Lücke senkt nicht ab, Grundwert bleibt stehen | 5 |
| 5 | Vergleich in UTC statt Ortszeit | 6 |
| 6 | Aneinander stoßende Fenster gelten als Überschneidung | 6 |
| 7 | `EXCLUDE` mit beidseitig geschlossenem Bereich | 3 |
| 8 | Der Verlauf zeichnet weiter die Betriebszeit | 4 |
| 9 | Die Schranke gegen Gästezimmer entfernt | 1 |
| 10 | Die Zod-Prüfung im Formular abgeschaltet | 3 (Playwright) |

**Probe 8 hat einen schwachen Test gefunden.** Beim ersten Lauf blieb
`test_ein_plan_hindert_den_verlauf_am_band` grün: das Zimmer hatte keine
Betriebszeit, also fand der Verlauf auch ohne den Plan kein Nachtfenster
und zeichnete so oder so nichts. Eine leere Erwartung, die aus zwei
Gründen erfüllt sein kann, prüft den falschen (§5.55). Der Test setzt
jetzt ausdrücklich eine Betriebszeit, die ein Band erzeugen **würde** —
danach ist er rot.

## Zahlen

* **2320 Tests** lokal grün (vorher 2201), 60 übersprungen.
* **438 Playwright-Tests** grün, davon 15 neu.
* `ruff check`, `ruff format --check`, `mypy src` ohne Befund.
* Migration lokal gegen `timescale/timescaledb:latest-pg16` gefahren —
  dasselbe Image wie in CI. `btree_gist` ist dort vorhanden (1.7),
  `int4range(smallint, smallint)` löst über den impliziten Cast auf
  `integer` auf; beides geprüft und nicht angenommen.

## Was nicht gebaut wurde

* **Wochentag- und Wochenend-Pläne.** #421 hat davon in der ersten Stufe
  abgeraten, der Betreiber hat sie nicht verlangt. Additiv nachrüstbar
  (eine zweite Dimension am Fenster), sobald sichtbar ist, wie die erste
  Stufe benutzt wird (§0 S6).
* **Ein Plan je Saison.** `rule_config` hat `season_id`; eine dritte
  Dimension in einer Oberfläche, die noch keine erste hat.
* **Kein Backfill.** Aus den heutigen Betriebszeiten einen Plan zu
  erzeugen wäre eine Übersetzung, die niemand bestellt hat — und sie
  würde die Bereiche von der einen Logik auf die andere schieben, ohne
  dass sich ihr Verhalten ändern soll.

## Offen

* Der Plan steht **nur** am Zimmer. Wer ihn für zwei Bereiche gleich
  haben will, tippt ihn zweimal. Das ist bei zwei Bereichen richtig und
  bei zehn nicht mehr — dann ist die Erbkette aus #421 die Antwort.
* Die Tagesleiste ist **lesend**. Fenster mit der Maus zu ziehen wäre
  bequemer und ist eine eigene Entscheidung.
* Aus dem vorigen PR offen und unverändert: Max/Mittel der
  Gehäusetemperatur im Tages-Verlauf, der Stundengrenzen-Fix für die
  193 Wh (`services/relais_verlauf._ANTEIL_SQL`) und die Doku-Lücke der
  Alarmtabelle (Zonen-Melder, Platten-Wächter).
