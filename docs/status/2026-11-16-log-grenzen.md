---
datum: 2026-11-16
thema: Zwei Protokolle wuchsen ohne Grenze — Deckel gebaut, Ausrollen offen
pr: offen
---

# 79 MB am Tag für 163 KB Nutzinhalt

**Keine Migration. Keine Server-Änderung.** Der Server ist nach diesem PR
unverändert; gebaut sind zwei Konfigurationsdateien, ein Install-Skript, die
Rechnung dahinter und die Laufliste §10be. Ausgerollt wird nichts ohne
Freigabe des Betreibers.

## Gefunden am 16.11.2026, bei den lesenden Prüfschritten nach PR #412

| Protokoll | Stand | Beginn | Rate | Regel |
|---|---|---|---|---|
| `/var/log/heizung-deploy.log` | 94,7 MB | 20.04.2026 | 0,45 MB/Tag | **keine** |
| `deploy-chirpstack-1` | 71,7 MB | 15.11.2026 07:59 | **79,3 MB/Tag** | **keine** (`map[]`) |
| die anderen zehn Container | 75 MB | bis 15.05.2026 | 3,1 MB/Tag | keine |

**ChirpStack ist 96 % des Problems.** 79,3 MB/Tag sind 29 GB im Jahr; frei
sind 25 GB. Ohne Grenze ist die Platte in rund **320 Tagen** voll, und was
bei 100 % passiert, steht seit dem 14.11. in §10az: Postgres nimmt keine
Schreibvorgänge mehr an.

Dringend ist es nicht (66 % belegt), und genau deshalb ist es jetzt zu
machen — der Vorfall vom 13.11. begann bei 94 %.

## Der Vorschlag aus dem Auftrag war fünffach zu knapp

Zur Prüfung vorgeschlagen war `max-size 50m, max-file 5` für chirpstack. Die
Rechnung an der gemessenen Rate:

```
garantiertes Fenster = (max-file − 1) × max-size / Rate
(5 − 1) × 50 MiB = 209,7 MB  →  209,7 / 79,3 = 2,6 Tage
```

Verlangt sind **14** Tage, weil §10av Schritt 6a `tx_power_index` je Gerät
aus dem letzten `LinkADRReq acknowledged` liest — der Wert steht in keiner
Datenbank von uns, und ADR protokolliert nur, wenn es etwas ändert. Eine zu
knappe Grenze hätte Schritt 6a **lautlos** halbiert: der Befehl läuft weiter
durch und meldet nur weniger Geräte.

Wie lautlos, zeigt der Ist-Stand. In 21,8 Stunden Protokoll stehen 183 Acks
von **55 verschiedenen Geräten**; Schritt 6a erwartet rund 90. Knapp einen
Tag Fenster deckt also etwa 60 % der Geräte ab.

**Gewählt: `max-size 100m`, `max-file 16`, `compress`.**

```
(16 − 1) × 100 MiB = 1572,9 MB  →  19,8 Tage bei 79,3 MB/Tag
```

Das Fenster bleibt bei mindestens 14 Tagen, solange die Rate unter
112,4 MB/Tag bleibt — **41 % Luft** auf den gemessenen Wert. Die höchste
Einzelstunde (4,12 MB), dauerhaft gehalten, ergäbe 15,9 Tage. Beide Zahlen
stehen als Test in `backend/tests/test_log_limits.py`, nicht als Kommentar:
wer die Grenze kleiner setzt, bekommt einen roten Test mit der Anzahl Tage,
die dann noch übrig wäre.

## Was es kostet

`compress` wurde am echten Protokoll gemessen: **Faktor 21,6**. Erwartet
sind damit 169 MiB für chirpstack (100 MiB laufend + 15 × 4,6 MiB gepackt),
harte Obergrenze 1,68 GB. Für `heizung-deploy.log`: 3,8 MB statt 160 MB im
Jahr.

Dass `docker logs` die komprimierten Generationen mitliest, ist **geprüft,
nicht angenommen** — lokal mit `max-size=10k, max-file=4, compress=true`:
277 Zeilen aus einer laufenden Datei und drei `.gz`-Dateien. Hätte das nicht
gestimmt, wäre `max-file` für Schritt 6a wertlos gewesen. Preis: Schritt 6a
liest dann bis zu 1,5 GB entpackt und braucht rund 30 s statt 1,2 s.

## Kein `logging:`-Block in der Compose-Datei

Vorgabe des Betreibers vom 16.11.: `mosquitto`,
`chirpstack-gateway-bridge` und `chirpstack` bekommen **keinen** Eintrag in
der Compose-Datei, weil jede Änderung an der Definition den Container beim
nächsten Deploy neu erstellt — und das ist bei diesen drei das Risiko selbst
(§10ay: Mosquitto-Neustart am 04.11.; §10bb: chirpstack in Schleife am
15.11.). Dass der Eintrag dort fehlt, ist ein Test, keine Absicht.

Die Vorgabe kommt deshalb aus `/etc/docker/daemon.json` und gilt je
Container **ab seiner nächsten Neuerstellung**. Daraus folgt die
Reihenfolge in §10be:

* `api`, `web`, `celery_worker`, `celery_beat` — beim **nächsten Merge** von
  selbst (H-6: jeder Merge erstellt sie neu, am 16.11. zweimal in zehn
  Minuten).
* `chirpstack`, `mosquitto`, `chirpstack-gateway-bridge`, `caddy`, `db`,
  `redis`, `chirpstack-postgres` — erst bei einer **gewollten**
  Neuerstellung im Wartungsfenster. Ein Neustart, auch der des Servers,
  genügt nicht: ein neu gestarteter Container behält seine alte Vorgabe.
* die logrotate-Regel — sofort mit dem nächsten `logrotate.timer`, ohne
  Docker.

**Der erste Deploy nach dem Merge erstellt genau die vier Dienste neu, die
jeder Merge neu erstellt** (`api`, `web`, `celery_worker`, `celery_beat`).
Kein zusätzlicher Dienst, weil die Compose-Datei unberührt bleibt.

## Die Falle, die in der Laufliste steht

Eine Neuerstellung von chirpstack legt ein **leeres** Protokoll an — mit und
ohne Grenze. Sie nimmt Schritt 6a also die Vorgeschichte, und zwar
unabhängig von dieser Änderung. §10be Schritt 4 sichert deshalb die Acks
vorher weg:

```bash
docker logs deploy-chirpstack-1 2>&1 | grep "LinkADRReq acknowledged" \
  > /var/log/heizung-adr-acks-$(date +%F).log
```

Das Fenster ist immer das Minimum aus zwei Zahlen: der Grenze **und** dem
Alter des Containers. Heute ist das Alter die kleinere (21,8 Stunden, seit
der Notreparatur vom 15.11.).

## Offen

**`tx_power_index` gehört in unsere Datenbank.** 1572 MB Rohprotokoll für
163 KB Nutzinhalt am Tag (0,19 %) sind der Preis dafür, dass der Wert nur im
Container-Protokoll steht. Solange das so ist, hängt jede Antwort auf
§10av Schritt 6a am Alter eines Containers. Das Sieben der Ack-Zeilen in
eine eigene Datei wäre sparsamer, aber ein neues bewegliches Teil, das
stillstehen kann, ohne dass es auffällt — und es verschiebt die Quelle für
Schritt 6a. Beides ist als eigene Aufgabe vermerkt, nicht in diesem PR
(S6: ein Thema je PR, und die einfache Variante liegt im Budget).
