# 27.11.2026 — Zimmer mit Verlaufsdaten löschen: 409

**Stand:** PR offen, nichts gemergt. Keine Migration.

**Die Entscheidung** ist vom Betreiber, zweiter Sammelauftrag vom
27.11.2026: ein Zimmer mit Verlaufsdaten wird nicht gelöscht, sondern mit
**409** und `ROOM_HAS_HISTORY` abgewiesen. Die Audit-Zeile `ROOM_DELETED`
bleibt.

## Der Punkt, den es schließt

`event_log.room_id` hängt mit `ON DELETE CASCADE` an `room.id`. Ein
gelöschtes Zimmer nimmt seinen gesamten Engine-Trace mit — für alle
vergangenen Tage, lautlos. Danach ist die Frage „warum war das Zimmer
kalt" nicht mehr beantwortbar. §0 S3 verlangt, dass jede
Sollwert-Entscheidung im Trace steht und dass es keine schnellen Pfade
daran vorbei gibt; eine Löschung, die den Trace entfernt, ist genau
dieser Pfad.

PR #439 hat das **belegt** und eine Audit-Zeile mit Zahlen hinzugefügt.
Dieser PR schließt es.

## Warum im Endpunkt und nicht `ON DELETE RESTRICT`

`RESTRICT` im Schema wäre die härtere Variante — sie würde auch `psql`
und jede Datenmigration treffen. Sie ist trotzdem **nicht** gebaut:

* Eine Migration, die einen Fremdschlüssel verengt, ist **nicht additiv**
  (AE-77, Goldene Regel 10). Ein Rückfall per `PIN_SHA` (§10u) ist nur
  über additive Migrationen zulässig — wer unter Druck zurückrollt, hätte
  dann ein Schema, das die alte Fassung nicht mehr bedienen kann.
* Die Meldung wäre ein `ForeignKeyViolation` aus der Datenbank. Der
  Administrator bekäme „violates foreign key constraint
  `event_log_room_id_fkey`" statt „14 212 Verlaufszeilen der Steuerung".
* Der Handgriff aus RUNBOOK §10bk wäre damit auch gesperrt, und es gäbe
  für ein versehentlich angelegtes Zimmer keinen Weg mehr.

**Der Preis der weicheren Variante:** `psql` und Datenmigrationen gehen
weiter durch. Das ist bewusst — sie sind der dokumentierte Weg (§10bk),
und wer dort arbeitet, hat vorher gesichert.

## Verlauf gegen Einrichtung

Von den sieben Tabellen am Cascade lösen **drei** die Sperre aus:

| Tabelle | Was sie ist | sperrt |
|---|---|---|
| `event_log` | der Engine-Trace, jede Entscheidung mit Schicht und Grund | **ja** |
| `occupancy` | wer wann im Zimmer war — Abrechnungsgrundlage | **ja** |
| `manual_override` | jeder Eingriff am Drehrad und aus der Oberfläche | **ja** |
| `heating_zone` | wie das Zimmer eingerichtet ist | nein |
| `rule_config` | Regelsätze | nein |
| `scenario_assignment` | Zuordnungen | nein |
| `tagesplan_fenster` | Zeitfenster | nein |

**Die Trennung ist der ganze Punkt.** Die Einrichtung darf mit dem Zimmer
verschwinden: sie ist wiederherstellbar, und jedes Zimmer hat davon etwas
— eine Sperre darauf wäre eine Sperre auf alles. Ein Test hält die
Gegenprobe fest: ein Zimmer mit Zone und Tagesplan-Fenster, aber ohne
Verlauf, **lässt sich löschen**. Ohne ihn wäre `CASCADE_TABELLEN` an
dieser Stelle eine grüne Mutation, die jedes Zimmer des Hauses
unlöschbar macht.

**Auch eine abgelaufene Belegung ist Verlauf.** Die ältere Schranke prüft
`is_active` — sie fragt „wohnt da gerade jemand". Diese fragt „hat da
jemand gewohnt". Eigener Test, damit der Unterschied nicht bei einer
späteren Vereinfachung stillschweigend einkassiert wird.

## Die Meldung nennt Zahlen

> Zimmer 204 hat Verlaufsdaten und wird deshalb nicht gelöscht: 12
> Verlaufszeilen der Steuerung, 1 Uebersteuerungen. Diese Daten hängen am
> Zimmer und würden mit ihm verschwinden.

Ein „Löschen nicht möglich" ohne Zahlen lässt offen, ob es um eine Zeile
oder um vierzehntausend geht — und das ist die Information, die der
Administrator braucht, um zu entscheiden, ob er den Weg aus §10bk geht.
Die Tabellennamen stehen **nicht** in der Meldung; `VERLAUF_KLARTEXT`
übersetzt sie, und ein Test verlangt für jede gesperrte Tabelle einen
Eintrag dort.

Der Diskriminator ist `error_code` neben `detail` (§5.64), nicht der Text.
Die Oberfläche zeigt `detail` direkt an — am Löschknopf der
Zimmer-Detailseite ist dafür keine Änderung nötig.

## Die Zahlen werden einmal geholt

`_was_mitgeht` läuft **einmal** und speist beides: die Sperre und, falls
sie nicht greift, die Audit-Zeile. Zweimal zu zählen wäre nicht nur
teurer, sondern eine zweite Wahrheit — zwischen den Abfragen könnte eine
Zeile dazukommen, und dann sperrte die eine, während die andere etwas
anderes protokolliert (§5.53).

## Was sich an den Tests ändert

**Der Cascade-Beleg geht jetzt an der Datenbank vorbei am Endpunkt.**
`test_der_cascade_nimmt_den_trace_mit` löschte über die Schnittstelle —
die weist das jetzt ab. Gelöscht wird dort direkt per SQL. Die
Schema-Eigenschaft bleibt wichtig: sie ist der Grund für die Sperre, und
sie gilt für **jeden** anderen Weg zum `DELETE`.

**Die Audit-Zeile wird am Zimmer ohne Verlauf geprüft**, mit einer neuen
Fixture. Sie nennt dort die Einrichtung und drei Nullen für die Tabellen
der Sperre — das belegt mit, warum die Löschung durchging.

**Der Modul-Docstring trug den Satz „Diese Datei belegt das Verhalten —
sie ändert es nicht" und „ob ein Zimmer mit Trace löschbar bleiben soll,
ist eine Entscheidung des Betreibers".** Beides ist seit diesem PR falsch
und ist ersetzt (§5.77). Derselbe Fall im `main.py`-Handler: dort stand
„Scope: Lifecycle-Pfade (replace, retire)" als Aufzählung, die beim
ersten neuen Pfad falsch wird — sie nennt jetzt das Kriterium.

## Mutationsproben: sechs, alle rot

| Probe | was rot wird |
|---|---|
| Sperre entfernt | die beiden 409-Tests |
| `VERLAUF_TABELLEN` = `CASCADE_TABELLEN` | 4 Tests, darunter die Gegenprobe |
| Meldung ohne Zahlen | die beiden 409-Tests |
| `occupancy` nicht als Verlauf | der Test zur abgelaufenen Belegung |
| `RoomHasHistory` erbt nicht von `LifecycleError` | die beiden 409-Tests (500 statt 409) |
| anderer `error_code` | die beiden 409-Tests |

## Was offen bleibt

**Die Oberfläche warnt nicht vorab.** Der Löschknopf ist aktiv und die
Absage kommt beim Klick. Ihn abhängig von den Verlaufszahlen zu
deaktivieren wäre eine zweite Stelle, die dieselbe Regel kennt — und die
erste, die beim Nachjustieren auseinanderläuft. Wenn es störend ist, ist
der richtige Weg ein Feld in der Zimmer-Antwort, nicht eine Regel im
Frontend.

**Querverweise:** RUNBOOK §10bk (der Weg für ein versehentlich angelegtes
Zimmer), `docs/status/2026-11-27-event-log-verdichten.md` (der Beleg aus
PR #439), §5.64 (`error_code` statt String-Vergleich), §5.77 (die zwei
überholten Vermerke), §5.53 (eine Wahrheit), AE-77 (additive
Migrationen), §0 S3.
