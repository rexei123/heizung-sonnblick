# Grenzen fuer die beiden Protokolle, die unbegrenzt wuchsen

Zwei Dateien liegen hier, beide werden **nicht** vom Deploy ausgerollt:

| Datei | Ziel am Server | wirkt |
|---|---|---|
| `daemon.json` | `/etc/docker/daemon.json` | je Container **erst bei dessen naechster Neuerstellung** |
| `../logrotate/heizung-deploy` | `/etc/logrotate.d/heizung-deploy` | sofort, mit dem naechsten `logrotate.timer` (taeglich 00:00) |

Eingerichtet wird beides mit `infra/deploy/install-log-limits.sh`. Das Skript
kopiert, prueft und erklaert — es startet **nichts** neu. Die Laufliste fuer den
Betreiber steht in `docs/RUNBOOK.md` §10be.

## Der Befund (gemessen am 16.11.2026, 05:45 UTC)

| Protokoll | Stand | Beginn | Rate |
|---|---|---|---|
| `/var/log/heizung-deploy.log` | 94,7 MB | 20.04.2026 (210 Tage) | **0,45 MB/Tag** |
| `deploy-chirpstack-1` (json-file) | 71,7 MB | 15.11.2026 07:59 UTC | **79,3 MB/Tag** |
| alle anderen zehn Container zusammen | 75 MB | bis zurueck zum 15.05.2026 | **3,1 MB/Tag** |

Fuer keines von beiden gab es eine Grenze: `grep -rl heizung-deploy
/etc/logrotate.d/` fand nichts, und `docker inspect deploy-chirpstack-1
--format '{{.HostConfig.LogConfig.Config}}'` gab `map[]` — kein `max-size`,
kein `max-file`, weder in der Compose-Datei noch in einer `daemon.json`
(die gab es am Server gar nicht).

**ChirpStack ist 96 % des Problems.** 79,3 MB/Tag sind 29 GB/Jahr; die Platte
hat 25 GB frei. Ohne Grenze ist sie in rund **320 Tagen** voll — mit der
Folge aus §10az: Postgres nimmt keine Schreibvorgaenge mehr an, also keine
Messwerte, keine Engine-Auswertung, keine Relais-Bestaetigungen.

Die 79,3 MB/Tag sind der Mittelwert ueber 21 volle Stunden (15.11. 08:00 bis
16.11. 04:59 UTC): 69 373 349 B, also 3 303 493 B/h. Die Stundenwerte liegen
zwischen 3,07 MB und 4,12 MB — der Strom ist gleichmaessig, nicht stossweise.

## Warum die Grenze fuer chirpstack so gross sein muss

RUNBOOK §10av Schritt 6a liest `tx_power_index` je Geraet aus dem jeweils
**letzten** `LinkADRReq acknowledged` in `docker logs deploy-chirpstack-1`.
Dieser Wert steht in **keiner** Datenbank von uns; ChirpStack haelt ihn in
`device.device_session` (Postgres, binaer). Das Container-Protokoll ist die
einzige lesbare Quelle.

Und ADR protokolliert **nur, wenn es etwas aendert**. Ist die Leistung eines
Geraets eingeschwungen, kommt tagelang keine neue Zeile — der letzte Ack
dieses Geraets wird also beliebig alt, waehrend er weiter die gueltige Antwort
ist. Eine zu knappe Grenze wirft ihn weg, und zwar **lautlos**: der Befehl
laeuft weiter durch und meldet nur weniger Geraete.

Wie lautlos, zeigt der Ist-Stand. Das Protokoll laeuft seit der Notreparatur
(§10bb) und ist 21,8 Stunden alt. Darin:

* 131 135 Zeilen, davon **183** `LinkADRReq acknowledged` (813 B je Zeile) —
  **0,19 %** des Volumens;
* Acks von **55 verschiedenen Geraeten**. Schritt 6a erwartet "rund 90
  Geraete auf `tx_power_index=7`".

Knapp 22 Stunden decken also **etwa 60 % der Geraete** ab. Das ist der Grund,
warum die Grenze nicht an der Ack-Rate haengt, sondern an der Rohdatenrate:
um 90 Geraete zu sehen, muss weit mehr als ein Tag im Protokoll stehen.

### Die Rechnung

Der json-file-Treiber haelt die laufende Datei (0 bis `max-size`) **plus**
`max-file − 1` gefuellte Dateien. Garantiert vorhanden ist damit die
**untere** Grenze — unmittelbar nach einer Rotation ist die laufende Datei
leer:

```
garantiertes Fenster = (max-file − 1) × max-size / Schreibrate
```

Mit `max-size 100m`, `max-file 16` (`m` ist bei Docker MiB):

```
(16 − 1) × 100 MiB = 1500 MiB = 1572,9 MB
1572,9 MB / 79,3 MB/Tag = 19,8 Tage
```

**19,8 Tage garantiert, verlangt sind 14.** Der Abstand ist die Reserve, und
sie ist in der Einheit angegeben, in der sie aufgebraucht wird: das Fenster
bleibt bei mindestens 14 Tagen, solange die Rate unter

```
1572,9 MB / 14 Tage = 112,4 MB/Tag
```

bleibt — **41 % ueber dem heute gemessenen Wert**. Zum Vergleich: die
hoechste gemessene Einzelstunde (4,12 MB) ergaebe, dauerhaft gehalten,
98,8 MB/Tag und damit **15,9 Tage**. Auch der Spitzenwert reicht.

### Der Vorschlag aus dem Auftrag reicht nicht

`max-size 50m, max-file 5` waere:

```
(5 − 1) × 50 MiB = 200 MiB = 209,7 MB
209,7 MB / 79,3 MB/Tag = 2,6 Tage   (bei Spitzenrate 2,1 Tage)
```

**2,6 statt 14 Tage** — ein Faktor 5 zu knapp. Schritt 6a wuerde damit noch
laufen, aber nur die Geraete melden, deren ADR in den letzten zweieinhalb
Tagen etwas geaendert hat. Mit `max-file 1` waere das Fenster 0 bis 1,3 Tage,
also gar keine Zusicherung. Genau diese Falle stand im Auftrag — die Rechnung
bestaetigt sie.

### Was die Grenze auf der Platte kostet

`compress` macht aus den rotierten Dateien `.gz`. Gemessen an den letzten
20 MB des echten Protokolls: **Faktor 21,6** (20 000 000 B zu 926 450 B; die
ANSI-Sequenzen und der wiederkehrende Zeilenaufbau komprimieren gut).

| | chirpstack |
|---|---|
| erwartet | 100 MiB + 15 × 4,6 MiB = **169 MiB** (rund 178 MB) |
| harte Obergrenze (unkomprimierbarer Strom) | 16 × 100 MiB = **1,68 GB** |

Die erwarteten 178 MB sind **mehr als heute** (71,7 MB), aber heute ist das
Protokoll 22 Stunden alt. Gegen die Fortschreibung ohne Grenze — 29 GB/Jahr —
ist es ein Deckel.

Die zehn anderen Container schreiben zusammen 3,1 MB/Tag. Fuer sie ist
dieselbe Vorgabe grosszuegig, aber nicht teuer: die Grenze ist eine
Obergrenze, kein belegter Platz. Mosquitto, der zweitgroesste Schreiber,
braucht bei 1,74 MB/Tag **drei Jahre** bis zur ersten Rotation.

### Was *nicht* geht

* **Das Log-Level von ChirpStack anheben.** `chirpstack.toml` steht auf
  `level = "info"`; die Ack-Zeilen sind selbst INFO. `warn` wuerde die 99,8 %
  Rauschen entfernen — und die 0,19 %, auf die es ankommt, mit.
* **Die Ack-Zeilen sieben und separat aufheben** (ein Timer, der
  `docker logs` filtert) waere sparsamer: 163 KB/Tag statt 169 MiB. Es ist
  auch ein neues bewegliches Teil, das stillstehen kann, ohne dass es
  auffaellt, und es verschiebt die Quelle fuer Schritt 6a. S6 ist nicht
  erfuellt, solange die einfache Variante im Budget liegt. **Der richtige
  Platz fuer diesen Wert ist unsere Datenbank** — als eigene Aufgabe
  vermerkt, nicht hier.

### Ein Deckel ersetzt die zweite Grenze nicht

Das Fenster ist das Minimum aus zwei Zahlen: der Grenze hier **und** der Zeit
seit der letzten Neuerstellung des Containers. Heute ist die zweite die
kleinere (21,8 Stunden, Notreparatur vom 15.11.), und sie faellt bei jeder
Neuerstellung auf null zurueck — eine Neuerstellung legt ein leeres Protokoll
an, mit oder ohne Grenze. Wer chirpstack neu erstellt, nimmt Schritt 6a also
die Vorgeschichte. Deshalb steht in §10be vor der Neuerstellung ein Schritt,
der die Acks wegsichert.

## Dass `docker logs` die komprimierten Dateien mitliest, ist geprueft

Nicht angenommen, sondern ausgefuehrt (lokal, Docker 29.8.2; am Server laeuft
29.4.0):

```bash
docker run -d --name logprobe \
  --log-driver json-file --log-opt max-size=10k --log-opt max-file=4 \
  --log-opt compress=true \
  alpine sh -c 'for i in $(seq 1 3000); do echo "ZEILE-$i ---"; done; sleep 2'
docker logs logprobe | wc -l    # 277
docker logs logprobe | head -1  # ZEILE-2724
```

Im Verzeichnis lagen dabei eine laufende Datei (9853 B) und **drei
`.gz`-Dateien**; `docker logs` liefert 20 775 B — also deutlich mehr als die
laufende Datei allein. Die rotierten, komprimierten Generationen werden
gelesen. Haette das nicht gestimmt, waere `max-file` fuer Schritt 6a wertlos
gewesen.

**Preis:** Schritt 6a liest dann bis zu 1,5 GB entpackt statt 72 MB. Heute
braucht der Befehl 1,2 s; zu erwarten sind daher rund **30 s**.

## Die logrotate-Regel

```
weekly            0,45 MB/Tag = 3,2 MB je Generation
rotate 8          acht Wochen Vorgeschichte (rund 56 Tage)
maxsize 50M       Bremse fuer den Fehlerfall: schlaegt ein Lauf in Schleife,
                  wird nicht erst in einer Woche rotiert
compress          Faktor 37 gemessen (94,7 MB zu 2,5 MB)
delaycompress     die erste Generation bleibt unkomprimiert. deploy-pull.sh
                  schreibt mit `tee -a` und `>>`, also je Aufruf neu
                  geoeffnet; ein Lauf, der genau in die Rotation faellt,
                  schreibt den Rest in die umbenannte Datei. Unkomprimiert
                  bleibt dieser Rest lesbar statt in einer Datei zu landen,
                  die gerade gepackt wird.
notifempty        kein Rotieren, wenn nichts geschrieben wurde
missingok         kein Fehler, wenn die Datei (noch) nicht existiert
create 0644 root root   wie bisher (gemessen: 644 root:root)
```

Erwarteter Platzbedarf: 3,2 MB laufend + 7 × 0,09 MB gepackt, also rund
**3,8 MB** statt 160 MB im Jahr.

**Einmaliger Effekt:** die erste Rotation nimmt die heutigen 94,7 MB als
Generation 1 mit. Sie bleibt acht Wochen liegen (ab der zweiten Rotation
gepackt, rund 2,5 MB) und faellt dann heraus. Wer den Platz sofort will,
loescht sie nach der ersten Rotation von Hand — notwendig ist es nicht.

## Warum keine `logging:`-Blöcke in der Compose-Datei

Jede Aenderung an der Compose-Definition eines Dienstes erzeugt den
Container beim naechsten Deploy neu. Fuer `mosquitto`,
`chirpstack-gateway-bridge` und `chirpstack` ist das keine Nebenwirkung,
sondern das Risiko selbst (§10ay: ein Mosquitto-Neustart hat am 04.11. das
Gateway haengen lassen; §10bb: chirpstack lief am 15.11. in Schleife). Diese
drei bleiben deshalb unberuehrt — Vorgabe des Betreibers vom 16.11.2026.

Fuer `api`, `web`, `celery_worker` und `celery_beat` braucht es ebenfalls
keinen Eintrag: H-6 gibt jedem Commit einen eigenen Image-Tag, **jeder Merge
erstellt diese vier neu** (CLAUDE.md, Merge-Fenster ab 18.10.) — am
16.11.2026 zweimal zwischen 05:40 und 05:50. Ihr Protokoll beginnt damit
ohnehin alle paar Tage von vorne, und die Vorgabe aus der `daemon.json`
greift bei ihnen **beim naechsten Merge von selbst**.

Bleiben `caddy`, `db`, `redis` und `chirpstack-postgres`: zusammen 1,4 MB/Tag,
und ihre Compose-Definition zu aendern wuerde sie ohne Not neu erstellen. Sie
bekommen die Vorgabe deshalb ebenfalls aus der `daemon.json`, wenn sie das
naechste Mal aus einem anderen Grund neu erstellt werden.

**Eine `daemon.json` kann den Docker-Dienst am Starten hindern**, wenn sie
fehlerhaft ist. Deshalb prueft das Install-Skript die Datei, bevor es sie
kopiert, und §10be laesst vor dem Neustart des Dienstes
`dockerd --validate --config-file=/etc/docker/daemon.json` laufen.
