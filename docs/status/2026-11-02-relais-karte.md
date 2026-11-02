## Die Relais-Karte sagt, was sie zählt — und was der Wächter tut (2026-11-02)

**Keine Migration.** Ein Feld in einer Leseantwort, zwei Zeilen auf der
Karte, ein Handbuch-Abschnitt. Baut auf dem Wächter-Backoff auf.

### Zwei Stellen, die mehr behaupteten als sie wussten

**„Schaltzyklen 0" trotz mehrfachem Schalten.** Befund des Betreibers
vom 01.11.2026 an Relais 109, nach dem T3.0-Lauf. Der Zähler war
**richtig**: `switch_cycles` wächst nur, wenn ein Befehl bestätigt wird,
den der **Orchestrator** gesendet hat — und T3.0 lief von Hand über
`python -c` am Wächter vorbei. Das Etikett versprach mehr, als es zählt.
Es heißt jetzt **„Schaltzyklen der Steuerung"**; der Zähler bleibt
unverändert.

**Ein unbestätigter Schaltbefehl war unsichtbar.**
`pending_target_on`, `pending_since` und `pending_attempts` hatten keinen
Leser außer dem Orchestrator. Ein Relais, das seit Stunden keine
Bestätigung liefert, stand als Alarm im Log und sonst nirgends — und das
Log liest niemand ohne Anlass (§5.76).

**Seit dem Wächter-Backoff ist das schwerer zu tragen**: der Alarm
löscht den offenen Stand nicht mehr (AE-78 §14), der Zustand lebt also
beliebig lange. Ohne Anzeige wäre er damit ein dauerhaft unsichtbarer
Zustand — genau die Klasse, die §5.79 beschreibt.

### Was jetzt zu sehen ist

Eine Zeile **„Unbestätigter Befehl"**, und nur dann, wenn einer offen
ist:

| Was dort steht | Was es heißt |
|---|---|
| „EIN, ein Versuch seit 10:42" | normal, die Bestätigung ist unterwegs |
| „AUS, 3 Versuche seit 10:20" | der Funk trägt schlecht, die Fristen wachsen |
| „… — gemeldet, wird nur noch gedrosselt wiederholt" | der Alarm ist heraus, es geht nur noch alle halbe Stunde einer hinaus |

### `gemeldet` kommt aus dem Backend

Die Schwelle steht in `relay_max_versuche` (Vorgabe 3). Sie im Frontend
ein zweites Mal zu kennen wäre beim ersten Nachjustieren falsch —
dieselbe Entscheidung wie bei den Batterie-Stufen (§5.73), wo die
Oberfläche die Stufe bekommt und nicht die Grenze.

Die Grenze ist in **beide** Richtungen festgehalten: bei **genau**
`max_versuche` ist `gemeldet` noch `false`, weil der Alarm in diesem
Durchlauf erst hinausgeht. Ohne diese Zeile wäre `>=` statt `>` nicht zu
unterscheiden — und die Mutationsprobe belegt es.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| `>=` statt `>` bei `gemeldet` | der Grenzen-Test |
| Label zurück auf „Schaltzyklen" | Playwright |
| „gedrosselt"-Zusatz immer anzeigen | Playwright (der Fall ohne Alarm) |
