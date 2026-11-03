## Rotation Teil 2: Laufliste für Mittwoch, und drei Korrekturen (2026-11-02)

**Keine Migration.** Nur Doku — RUNBOOK §10aw (neu) und drei Stellen in
§10ab Teil 2.

### Was geliefert ist

**§10aw** ist die Laufliste für den **04.11.2026**: Reihenfolge,
Zeitfenster, Dauer je Block, die vier Regeln, die in jedem Schritt
gelten, und die Abbruchpunkte. Die Blöcke selbst stehen weiter in §10ab
Teil 2 — **sie sind nicht wiederholt.** Zwei Fassungen desselben Befehls
sind eine Fehlerquelle und keine Hilfe (§5.53).

| | Block | Fenster |
|---|---|---|
| 0 | Teil 1 Schritt 0.0–0.6 plus 0.3 aus Teil 2 | vorher |
| C1 | SMTP-Passwort | jederzeit |
| **C2** | `OCCUPANCY_IMPORT_TOKEN` | **nach 08:30, fertig vor 15:30** |
| C3 | `HOTEL_BASIC_AUTH_HASH` | jederzeit |
| C4 | `gateway-ug65` entfernen | jederzeit |
| C5 | ChirpStack-Admin (C5.1 zuerst) | jederzeit |
| C6 | apt-Updates und Neustart | **zuletzt** |
| **C7** | alte Backups löschen | **nach** grüner Prüfliste |

### Die Prüfung, die falsch war — und das ist der Fund des Tages

**C1 prüfte mit einem Befehl, der nicht laufen konnte.** Dort stand ein
Python-Schnipsel mit `send_mail(recipient=None, …)` und `r.ok`. Drei
Fehler in vier Zeilen:

- `MailResult` hat `sent`, `reason` und `detail` und **kein** `ok` — der
  Aufruf wäre mit `AttributeError` abgebrochen.
- `recipient=None` heißt in `mailer.send_mail` ausdrücklich „kein
  Empfänger eingetragen" und löst **keine** Auflösung der Alarm-Adresse
  aus. Es wäre nie eine Mail hinausgegangen.
- Das Werkzeug für genau diesen Handgriff gab es schon:
  `python -m heizung.scripts.send_test_mail`.

**Nichts davon wäre am Mittwoch als Doku-Fehler erkannt worden.** Der
Befehl hätte einen Fehler geworfen, und der sieht aus wie ein
SMTP-Problem — also hätte der Block als „SMTP kaputt" gegolten, mit einem
Rückweg, den niemand gebraucht hätte. §5.79 in Reinform: **eine
Prüfanweisung ist eine Aussage über den Code, den sie aufruft, und sie
verfällt mit ihm.**

C1 ruft jetzt das Werkzeug. Es zeigt die wirksame SMTP-Einstellung ohne
das Passwort, schreibt die drei Versandfelder auf `global_config` und
berührt keine Wiederholungsbremse.

### Zwei weitere Korrekturen

**Zeilennummern.** Die Verweise in §10ab zeigten auf `:338/:339/:340` in
`docker-compose.prod.yml`; richtig sind 330 (ChirpStack-Hash), 333
(Hotel-Hash), 334 (der `$$`-Kommentar) und 338 (Caddyfile). Nachgezogen,
jeweils mit „Stand 02.11.2026" daneben — eine Zeilennummer ohne Datum
ist die nächste Drift.

**C7 ist neu.** „Danach alte Backups löschen" war als Auftrag da und in
§10ab nirgends. Jetzt steht er dort, mit drei Festlegungen: die
**jüngste** Sicherung bleibt (Rückweg für die Tage danach, etwa wenn ein
Alarm erst später ausbleibt), gelöscht wird mit **`shred -u`** und nicht
`rm` (in den Dateien stehen die alten Geheimnisse im Klartext — bei einem
Wert, der wegen Sichtbarkeit rotiert wurde, ist `rm` der falsche
Abschluss), und die DB-Backups aus §10q sind **nicht** berührt.

### Nachgeprüft gegen `develop`, nicht übernommen

Ein Audit gilt für den Stand, den es gesehen hat (§5.79). Geprüft wurde
jede Aussage von §10ab Teil 2, die auf Code oder Konfiguration zeigt:
die `SMTP_*`-Namen, `OCCUPANCY_IMPORT_TOKEN`, `HOTEL_BASIC_AUTH_HASH`,
`STAGE`, der Mosquitto-User `gateway-ug65` (**weiter vorhanden**, C4
bleibt nötig) und die Zahl der `basicauth`-Regeln in `Caddyfile.test`
(**genau eine**, der ChirpStack-Host hat keine — C5 ist der einzige
Schutz davor).

**B-22-4 ist nicht erledigt:** `CHIRPSTACK_BASIC_AUTH_HASH` steht weiter
in Compose und `.env.example`, und der irreführende Kommentar in
`Caddyfile.test:5` behauptet weiter eine Basic-Auth, die es nicht gibt.
Das ist §5.77 in der sicherheitsrelevanten Richtung und bleibt
ausdrücklich **außerhalb** dieser Rotation — eigener kleiner PR.

### Die vier Regeln, die in jedem Schritt gelten

`ENV_NEU` vor jedem `docker compose` (auch in den Rückwegen, dazu
`--no-deps`) · je Schritt eine Prüfung **und** ein Rückweg · **keine
Werte auf dem Bildschirm** (die Prüfungen zeigen Eigenschaften, nicht
Inhalte — Anlass ist der Screenshot vom 19.09.2026) · **kein
`do-release-upgrade`**, und auch kein `full-upgrade`: das darf Pakete
entfernen, um Abhängigkeiten aufzulösen, und was es entfernt, sieht man
erst danach.
