---
datum: 2026-11-16
thema: Fremde Images auf Tag plus Digest festgenagelt
pr: offen
---

# Fremde Images festgenagelt

**Keine Migration. Keine Server-Änderung in diesem PR.** Geändert sind
neun `image:`-Zeilen in `infra/deploy/docker-compose.prod.yml`, der
Dateikopf, RUNBOOK §10bg, Lehre §5.91 und ein Testmodul. Das Ausrollen
ist ein eigener Handgriff und gehört in einen Wartungstermin — die
Begründung steht unten unter „Warum nicht ins Merge-Fenster".

## Was geändert ist

Acht fremde Images (neun Zeilen, `alpine:3.20` steht zweimal) hängen
jetzt an **Tag plus Digest**:

| Dienst | Zeile heute | läuft |
|---|---|---|
| `db` | `timescale/timescaledb:latest-pg16@sha256:95a79974…` | PostgreSQL 16.13, timescaledb 2.26.3 |
| `redis` | `redis:7-alpine@sha256:7aec734b…` | Redis 7.4.8 |
| `mosquitto` | `eclipse-mosquitto:2@sha256:a908c65c…` | Mosquitto 2.1.2 |
| `chirpstack-postgres` | `postgres:16-alpine@sha256:4e6e670b…` | PostgreSQL 16.13 |
| die zwei Init-Behälter | `alpine:3.20@sha256:d9e853e8…` | Alpine 3.20.10 |
| `chirpstack-gateway-bridge` | `chirpstack/chirpstack-gateway-bridge:4@sha256:14a1b367…` | Gateway Bridge 4.1.1 |
| `chirpstack` | `chirpstack/chirpstack:4@sha256:72cabb11…` | ChirpStack 4.17.0 |
| `caddy` | `caddy:2-alpine@sha256:83446812…` | Caddy v2.11.2 |

**Unsere eigenen Images bleiben ohne Digest.** `api`, `web` und die
zwei celery-Dienste hängen an `${IMAGE_TAG}`, und `deploy-pull.sh` setzt
den je Commit (H-6). Ein fester Digest daneben würde genau den
Mechanismus aushebeln, der den Rückfallpunkt schafft. Ein Test sichert
das ab.

## Wofür das gut ist — und wofür nicht

**Richtigstellung zur ursprünglichen Begründung.** Der Neustart am
Mi 18.11. kann **keine** neue Version laden. `pull_policy: always` steht
nur bei `api`, `web` und den zwei celery-Diensten; für die Infrastruktur
gilt die Compose-Vorgabe `missing`, und alle acht Images liegen lokal.
`deploy-pull.sh` zieht ohnehin nur `api web`. Dieser PR ist also **kein**
Schutz vor dem Mittwoch.

**Die echte Gefahr** ist das fehlende Image. Sobald eines lokal nicht
mehr liegt, holt die nächste Neuerstellung, was gerade unter `:4`, `:2`
oder `latest-pg16` liegt. Am 14.11. wurden 108 Images entfernt; aktuell
liegen wieder 117 Images, 29,9 GB, davon 31,3 GB reklamierbar. Am 15.11.
wurde `chirpstack` **mitten im Störfall** neu erstellt — wäre das Image
vorher weggeräumt gewesen, hätte derselbe Befehl **4.18** gezogen statt
4.17.0, und zwar in der Minute, in der niemand eine zweite Baustelle
braucht. Festnageln ist **Wiederherstellbarkeit**, nicht Prävention.

## Der Befund, der die Zahlen beinahe gekippt hätte

Die Digests kamen aus der Übergabe der zweiten Sitzung. Beim Nachlesen
stand bei **allen acht** derselbe Wert zweimal:

```
redis:7-alpine
  RepoDigests: ["redis@sha256:7aec734b2bb2…"]
  Id:          sha256:7aec734b2bb2…
```

Normalerweise ist `.Id` der **Config**-Digest und `.RepoDigests[0]` der
**Manifest**-Digest, und die beiden sind verschieden. Hinter
`image: name@sha256:…` gehört der Manifest-Digest; ein Config-Digest
lässt sich nicht ziehen.

**Die Erklärung ist der Image-Store, nicht ein Fehler.** Der Server läuft
mit Docker 29.4.0 und containerd (`docker info` → `Storage Driver:
overlayfs`, `driver-type: io.containerd.snapshotter.v1`). Dort liefert
`.Id` den Manifest-Digest. Bestätigt am `Descriptor`:

```
{"mediaType":"application/vnd.oci.image.index.v1+json","digest":"sha256:7aec734b…"}
```

Das ist der Digest des **Multi-Arch-Index** — genau der ziehbare Wert,
und der richtige zum Festnageln: er löst weiter je Architektur auf.

**Warum der Umweg nötig war.** Hätte ich die Gleichheit als Tippfehler
abgetan und „den anderen" Wert genommen, wäre nichts aufgefallen: das
Image liegt lokal, Compose zieht `missing`, kein Neustart hätte es
gemerkt. Der falsche Digest hätte erst in dem Moment aufgeschlagen, für
den der ganze PR gebaut ist — wenn das Image **fehlt**. Ein Fehler, der
genau dann zuschlägt, wenn die Absicherung greifen soll, ist schlimmer
als keine Absicherung. Daraus Lehre **§5.91**.

Die Klartext-Versionen sind alle am laufenden Dienst nachgeprüft, nicht
aus der Übergabe übernommen. Eine Ausnahme: **die Bridge nennt ihre
Version nicht** — sie protokolliert beim Start `version=` leer und kennt
kein `--version`. Die 4.1.1 steht nur im Image-Label
`org.opencontainers.image.version`. Das ist in §10bg vermerkt, damit beim
nächsten Nachziehen niemand danach sucht.

## Was die Tests zusichern — und was nicht

Neun Zusicherungen in
`backend/tests/test_infrastruktur_images_festgenagelt.py`, alle
**strukturell**: jedes fremde Image trägt einen Digest, jeder Digest hat
die richtige Form, der Tag bleibt davor lesbar, über jedem steht die
Klartext-Version, unsere eigenen Images tragen keinen Digest, der
Dateikopf nennt den Preis und verweist auf §10bg, und §10bg existiert mit
Terminen, zweitem Anlass und dem Verweis auf die Gateway-Prüfliste.

**Die Digest-Werte stehen absichtlich nicht im Test.** Eine Kopie wäre
eine zweite Wahrheit (§5.53): sie müsste bei jedem Nachziehen mitgepflegt
werden, und ein Vergessen sähe aus wie ein Befund, obwohl nur die Kopie
alt ist. Der Test kann deshalb einen *falschen* Digest nicht erkennen —
nur einen fehlenden oder formal kaputten. Was den falschen abfängt, ist
Schritt 1 des Rituals und der Ausroll-Nachweis in Schritt 4.

**13 Mutationsproben, alle rot.** Zwei blieben im ersten Durchgang grün
und haben eine echte Schwäche gezeigt: die Zusicherungen auf „CVE" und
„§10ay" prüften nur, ob das Wort *irgendwo* im Abschnitt steht, und beide
Wörter stehen dort zweimal. Jetzt sind sie an die Stelle gebunden, an die
die Aussage gehört — der Anlass-Block und der Ausroll-Schritt. Dieselbe
Familie wie §5.88: eine Prüfung auf die ganze Datei ist keine Prüfung auf
die Stelle.

## Warum nicht ins Merge-Fenster

Ein Merge dieser Datei ändert die Zeilen von `db`, `redis`,
**`mosquitto`**, `chirpstack-postgres`, `chirpstack`,
**`chirpstack-gateway-bridge`**, `caddy` und den zwei Init-Behältern.
Der Timer zieht `origin/develop` alle fünf Minuten und ruft
`docker compose up -d` — **jeder Dienst mit geänderter Zeile wird
innerhalb von fünf Minuten neu erstellt**. Mosquitto und die Bridge sind
dabei, und das ist der Weg, auf dem am 04.11. das Gateway abgerissen ist
(§10ay).

**Vorschlag: mit C6 am Mi 18.11. bündeln**, in dieser Folge:

1. `install-log-limits.sh` (§10be, aus #422) → `reboot` → C6-Prüfliste.
2. Erst wenn die **grün** ist: diesen PR mergen, Timer erstellt neu,
   dann §10ay.

**Der Nebeneffekt ist der Grund für die Bündelung:** weil der
Docker-Dienst die `daemon.json` beim Neustart gelesen hat, bekommen alle
neu erstellten Container in einem Zug auch die Log-Grenze — genau das,
was §10be Schritt 5 für `mosquitto`, die Bridge, `caddy`, `db`, `redis`
und `chirpstack-postgres` einzeln nicht riskieren wollte. Eine
Neuerstellung, zwei Wirkungen, **eine** Gateway-Prüfung statt zwei
Terminen.

**Der Preis:** zwei Änderungen gleichzeitig im Spiel. Dagegen steht die
Reihenfolge — der Merge kommt erst nach der grünen C6-Prüfliste, der
Neustart ist dann schon abgehakt.

## Was das Festnageln kostet

Sicherheitspatches für `postgres`, `caddy`, `redis` und `mosquitto`
kommen danach **nie mehr von selbst** mit. Dagegen hilft nur das Ritual
in **§10bg**: einmal je Quartal (Januar, April, Juli, Oktober) oder bei
einem CVE, der zählt, bewusst nachziehen — in einem eigenen PR mit einem
Termin für die Neuerstellung. Steht das Ritual nicht, ist der
eingefrorene Stand in einem Jahr kein Entschluss mehr, sondern ein
Versehen. Deshalb sichert ein Test die Existenz von §10bg ab, und nicht
nur die Digests.

**Querverweise:** RUNBOOK §10bg (das Ritual), §10ay (Prüfliste nach einer
Neuerstellung, 04.11.), §10bb (ChirpStack 4.17 und das Plugin — warum ein
Sprung auf 4.18 kein Nebenbei ist), §10be (die Log-Grenzen, #422), H-6
und `test_deploy_pull_pinning.py` (unsere eigenen Images, je Commit),
§5.91, §5.53, §5.68, `docs/status/2026-11-16-uebergabe-sitzung-2.md`.
