---
datum: 2026-11-14
thema: Platten-Warnung bei 85 % und automatisches Aufräumen beim Deploy
pr: offen
---

# Damit es nicht wieder passiert

Punkt **3** des Auftrags vom 14.11.2026: *„Platten-Warnung (> 85 %,
Kachel + Mail je Episode) + automatisches Aufräumen in deploy-pull.sh
(heizung-api/web älter als 7 Tage; laufender Tag + PIN_SHA-Ziel immer
behalten)."*

**Kein Steuerpfad** im Backend. Der Deploy-Teil ist ein Eingriff auf dem
Server, aber nur löschend auf Images, nach dem erfolgreichen Deploy und
ohne Einfluss auf den Lauf.

## Der Anlass

Am 13.11. war die Platte zu **94 %** belegt — 4,5 GB frei von 75 GB, am
nächsten Morgen 4,1 GB. **Gefunden wurde es beim Nachsehen nach etwas
anderem.** Gewarnt hat nichts.

Bei 100 % nimmt Postgres keine Schreibvorgänge mehr an: keine Messwerte,
keine Engine-Auswertung, keine Relais-Bestätigungen. Der Weg dorthin ist
nicht dramatisch, sondern gleichmäßig — jeder Merge erzeugt ein
Image-Paar von rund 400 MB (§5.4), und `event_log` wächst um etwa 4,8 GB
im Monat. Mit 4,1 GB frei waren das noch rund **zehn Merges**.

## Teil 1: die Warnung

**Gemessen wird die Wirkung, nicht die Mechanik** (§5.76). Nicht „läuft
das Aufräumen", nicht „wie viele Images liegen da", sondern **wie viel
Platz frei ist**. Das greift unabhängig davon, welche Ursache gerade
zunimmt — auch bei einer, an die heute niemand denkt.

### Die Rechenart ist der Kern, nicht ein Detail

`df` rechnet den Belegungsgrad **ohne** die für root reservierten Blöcke
(bei ext4 rund 5 %) und rundet auf. Gemessen am 14.11. auf dem Server:

| | |
|---|---|
| `df` sagt | **64 %** |
| `belegt / gesamt` | 60,6 % |
| `belegt / (belegt + frei)` | 63,2 % → **64 %** |

Drei Prozentpunkte klingen harmlos und sind es nicht: mit der falschen
Rechnung schlüge eine 85-Prozent-Warnung erst an, wenn `df` **88 %**
zeigt. Dann steht in der Mail eine andere Zahl als auf dem Server, und
die erste Frage ist nicht „was räumen wir auf", sondern „welche Zahl
stimmt" (§5.53). Zwei Tests halten den Unterschied als Zahl fest.

### Warum das im Container ohne Bind-Mount geht

`shutil.disk_usage("/")` im api-Container fragt den overlay2-Aufbau, und
dessen `statfs` liefert die Werte des darunterliegenden Dateisystems.
Nachgemessen, Host und beide Container auf Byte-Ebene identisch:

```
/dev/sda1  total=80307429376  used=48690868224  free=28293947392
```

Das ist eine Eigenschaft **dieses Aufbaus**, keine Zusicherung von
Docker: läge `/var/lib/docker` eines Tages auf einer eigenen Platte,
mäße der Code jene und nicht die der Datenbank. Der Prüfbefehl steht im
Kopf von `services/plattenplatz.py`.

### Kachel, Mail, Episode

* **Kachel „Plattenplatz"** (die vierzehnte), Prozent als Wert, freie
  Gigabyte als Zusatzzeile. `tone` kommt aus dem Backend
  (`platte_warnt`) — die Grenze im Frontend zu wiederholen wäre eine
  zweite Schwelle, die beim ersten Nachjustieren driftet (§5.53).
* **Eine Mail je Vorfall**, Entwarnung danach. Zustand in
  `business_audit` (`PLATTE_FAST_VOLL` / `_ENDE`, `target_type =
  "server"`), damit er den Neustart überlebt — Redis lässt bei Ausfall
  alles durch, und dann käme die Mail stündlich.
* **Wiederholung nach 24 Stunden**, nicht nach sechs wie beim
  Zonen-Melder: eine volle Platte erledigt sich nicht von selbst, und
  niemand räumt nachts um drei auf.
* **Der Audit-Eintrag hängt nicht an der Mail-Adresse.** Er *ist* der
  Zustand der Episode; hinge er an der Adresse, begänne die Episode bei
  jedem Lauf von vorn.

## Teil 2: das Aufräumen

Phase 4 in `deploy-pull.sh`, nach dem erfolgreichen Deploy.

**Warum dort und nicht als eigener Timer.** Images entstehen beim
Deploy, also ist der Deploy der Moment, sie wegzuräumen. Ein zweiter
Timer wäre ein zweiter Mechanismus mit eigener Überwachung — und einer,
der genau dann nichts tut, wenn nicht deployt wird, also wenn auch
nichts entsteht.

**Was immer bleibt**, in dieser Reihenfolge der Sicherungen:

1. **Alles, was ein Container benutzt** (`docker ps`). Ist diese Liste
   nicht zu bekommen, wird **nichts** gelöscht — die Sicherheitsprobe
   aus RUNBOOK §10az, als Code.
2. **Der Tag dieses Laufs.** Bei gesetztem `PIN_SHA` ist das der
   Pin-Tag, also das Rückfallziel.
3. **Alles, was jünger ist als sieben Tage** (`DEPLOY_CLEANUP_DAYS`).

**Kein `prune`, kein `-f`.** `docker image prune -a` nimmt `caddy`,
`redis`, `timescaledb` und die ChirpStack-Bilder mit; sie
wiederzuholen braucht Netz zu einem Zeitpunkt, den niemand wählt. Und
ohne `-f` verweigert `docker rmi` jedes Image, das ein Container
benutzt, auch ein gestoppter — die Sicherung hinter der Sicherung.

**Der Lauf scheitert daran nicht.** Jeder Pfad endet mit `return 0`, der
Aufruf trägt `|| true`. Ein Deploy, der wegen einer Aufräum-Panne rot
meldet, wäre ein Melder am falschen Ort (§5.79).

**Die Sicherheitsprobe ist ein Filter, keine Prüfung danach.** Von Hand
ist sie ein Vergleich, den man liest und dann entscheidet; hier ist sie
der `grep -v`, der die laufenden Tags aus der Liste nimmt. Eine Prüfung
*hinter* dem Filter könnte nie anschlagen, und das ist schlechter als
keine.

## Was die Proben gefunden haben

### Backend (neun Proben, alle rot)

| Probe | Ergebnis |
|---|---|
| M1 Nenner `gesamt_b` statt `belegt+frei` | **2 Tests rot** |
| M2 abgerundet statt aufgerundet | **4 Tests rot** |
| M3 Grenze exklusiv statt inklusiv | **1 Test rot** |
| M4 Grenze fest im Modul | **1 Test rot** |
| M5 keine Bremse: jede Stunde eine Mail | **1 Test rot** |
| M6 Entwarnung auch ohne vorherigen Alarm | **2 Tests rot** |
| M7 Audit-Zeile nur, wenn die Mail hinausging | **1 Test rot** |
| M8 das Audit hält die Zahlen nicht fest | **1 Test rot** |
| M9 die Kachel rechnet die Grenze selbst | **1 Test rot** |

**M7 und M9 waren zuerst grün.** Für M7 fehlte der Fall „keine
Alarmadresse eingetragen" — die Testdatenbank hat eine, also änderte die
Mutation nichts. Für M9 prüfte niemand, dass der Endpunkt die Grenze aus
den Einstellungen nimmt; der Vertragstest sah nur, dass das Feld
existiert. Drei Tests nachgezogen.

### Deploy-Skript (zwei Proben, beide rot — und eine dritte, die etwas lehrte)

Das Skript läuft im Test gegen Attrappen für `docker`, `git`, `curl`.
Die beiden Proben:

| Probe | Ergebnis |
|---|---|
| der Filter „was läuft, bleibt" entfernt | das **laufende** Image steht in der Löschliste |
| `docker ps` gar nicht gefragt | dasselbe |

**Die erste Fassung des Tests hätte beide nicht gefunden.** Der
„laufende" Tag im Testaufbau war der des Laufs — und der ist **jung**,
also schon durch die Datumsgrenze geschützt. Der Test prüfte die
Datumsgrenze und nicht die Sicherung (§5.55: ein grüner Lauf, der nichts
geprüft hat). Aufgefallen ist es erst, weil die Mutation das Ergebnis
**nicht** verändert hat.

Der Aufbau kennt jetzt ein laufendes Image jenseits der Grenze (ein
Container, den `up -d` seit Wochen nicht angefasst hat — realistisch,
weil nur bei Image- oder Config-Drift rekreiert wird) und einen alten
Tag, der weder läuft noch gepinnt ist. Erst damit zeigt jeder der beiden
Tests etwas.

## Läufe

* Backend **1937 passed, 52 skipped, 1 xfailed**.
* `ruff check`, `ruff format --check` (342 Dateien), `mypy` (162 Dateien) grün.
* `tsc --noEmit` grün; e2e `kacheln-gleiche-hoehe` + `sprint-14c-dashboard`
  **23 passed** (lokal, Port 3123).
* **Das Deploy-Skript von Hand belegt** (14.11.2026, Git Bash): fünf
  Fälle — normaler Lauf (drei Tags weg, laufender und junger bleiben),
  mit `PIN_SHA` (das alte Rückfallziel bleibt, der andere alte Tag geht),
  `rmi` scheitert (Deploy grün, Ping geht hinaus), `docker ps` nicht
  abfragbar (nichts gelöscht), `DEPLOY_CLEANUP_DAYS=0` (übersprungen).
  Der pytest-Test dazu läuft nur auf POSIX, also in CI.

## Was offen bleibt

**Der Hinweis in RUNBOOK §10az fehlt noch.** Dort steht die Checkliste
von Hand, und sie bekommt einen Satz „läuft seit 14.11. automatisch beim
Deploy". Der Abschnitt entsteht erst mit #407; ein Eingriff von hier
hätte garantiert einen Konflikt. Gehört in das nächste Doku-Bündel.

**Die Warnung nennt keine Ursache.** Ob die Images, `event_log` oder ein
Backup den Platz braucht, sagt der Befehl in der Mail. Eine Vermutung im
Melder wäre eine Behauptung (§5.68).

**`event_log` bleibt das größere Thema.** Die Verdichtung steht als
Vorprüfung im Auftrag (Punkt 7); 4,8 GB im Monat füllen die 27 GB in
etwa fünf Monaten, auch ohne einen einzigen Merge.

**Nach dem Aufräumen bleiben 23,88 GB „reclaimable"** (Stand 14.11.,
§10az): die verbliebenen Tags liegen auf 14 Image-IDs, von denen zwei
laufen. Eine engere Grenze als sieben Tage gäbe noch einmal ähnlich
viel frei — sieben Tage sind der Preis für den Rückfallweg.
