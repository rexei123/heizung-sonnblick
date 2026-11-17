---
datum: 2026-11-16
thema: Großer Durchgang — ein Merge-Lauf, ein Wartungsblock, dann das Plugin
pr: offen
---

# Großer Durchgang Mo 16.11.2026

Vier Phasen, in dieser Reihenfolge. **Das Haus ist leer bis Do 19.11.** —
das ist der Grund, warum alles an einem Tag geht, und es ist auch die
Frist: ab Donnerstag gilt wieder das Fenster.

## Grundregeln für diesen Tag

**1. Ab Phase 2 ist der Betreiber beim Gateway.** Nicht in Reichweite,
sondern dort. Das Gateway verbindet sich nach einer serverseitigen
Unterbrechung **nicht von selbst neu** (§10ay, 04.11.: 36 Minuten ohne
Messwerte), und die Behebung ist eine Stromtrennung am UG65.

**2. STOPP heißt: nichts weiter.** Nicht „nochmal versuchen", nicht „den
nächsten Schritt trotzdem". Ausgabe an mich, dann warten.

**3. Keine Befehle, die Geheimnisse zeigen können.** Kein `sed -n 'a,bp'`,
kein `cat`, kein `head`/`tail` auf `chirpstack.toml` oder `.env`. Gezielt
greppen, und zwar auf Nutzzeilen (§5.89, §5.88). Die gerenderte Fassung im
Volume ist die gefährlichere: dort sind die Platzhalter **aufgelöst**.

**4. Zeitstempel.** Die Container protokollieren in **UTC**, die
Serveruhr läuft in **CET**. Eine Logzeile „07:52" ist 08:52 Ortszeit. Wer
eine Störung vermutet, prüft sie an **Daten**, nicht an Logzeilen
(§5.92 — mir heute zweimal passiert). Der Datenbeweis:

```bash
ssh -i $HOME\.ssh\id_ed25519_heizung root@157.90.17.150 "docker exec deploy-db-1 psql -U heizung -d heizung -tAc \"SELECT count(*) FROM event_log WHERE time > now() - interval '5 minutes';\""
```

*Erwartet:* vierstellig (16.11., 08:53: **1078**). Nahe null heißt: der
Regler läuft wirklich nicht.

**5. Die Pflicht-Frage vor dem ersten Merge (§0.3):** Läuft gerade ein
Montage- oder Eingangstest? Ein Deploy erstellt den api-Container mitten
im Lauf neu, und das Gerät, das dabei in der Bestätigungs-Kette hängt,
bekommt die Downlinks beim Resume **erneut**.

---

# Phase 1 — Merge-Lauf

**Nicht dabei:** #424 (Pinning — der erstellt neun Infrastruktur-Dienste
neu, Phase 2d) und #425 (Plugin — Phase 3). Alles andere geht in **einer**
`merge-paket`-Zeile.

### 1.1 Die Merge-Zeile

*wo:* PowerShell (lokal)

```powershell
.\merge-paket.ps1 427,426,428,429
```

> **Komma, nicht Leerzeichen.** Das Skript nimmt `[int[]]$Prs` und
> danach `[int]$DeployTimeoutMin`. Mit Leerzeichen bindet PowerShell die
> zweite Zahl als Zeitgrenze und bricht bei der dritten ab. Hier stand bis
> zum 16.11. die Leerzeichen-Form — mein Fehler, vom Betreiber beim
> Aufruf richtig gemacht.

| PR | Thema | besonders |
|---|---|---|
| [#427](https://github.com/rexei123/heizung-sonnblick/pull/427) | **diese Laufliste** | reine Doku |
| [#426](https://github.com/rexei123/heizung-sonnblick/pull/426) | Drei Korrekturen, Lehre §5.92 | reine Doku + zwei Tests |
| [#428](https://github.com/rexei123/heizung-sonnblick/pull/428) | Relais-Signal (RSSI/SNR) | **Migration 0041**, additiv |
| [#429](https://github.com/rexei123/heizung-sonnblick/pull/429) | Anzeige-PR | nur Oberfläche und Fehlertexte |

**Warum diese Reihenfolge.** Die zwei Doku-PRs zuerst, damit bei einem
Abbruch der Rest noch nicht angefasst ist. #428 vor #429, weil #428 die
Migration bringt.

**Ein Konflikt ist absehbar:** #428 und #429 fassen beide
`api/v1/relays.py` (das Schema `RelaisStand`) und `relay-card.tsx` an.
Wer zuletzt kommt — also #429 — braucht ein develop-Einmergen.
`merge-paket` stellt die Basis selbst um; bleibt es stehen, bitte melden.
Kein Rebase, kein Force-Push.

**Nicht in dieser Zeile:** #424 (Pinning, Phase 2d) und #425 (Plugin,
Phase 3a). Beide erstellen Container neu und gehören in den
Wartungsblock.

> **Was heute nicht fertig geworden ist:** der **Relais-Verlauf**
> (Ein/Aus mit Ist/Soll, Heizdauer, kWh mit Rücksprung, Tabelle je Tag,
> CSV, 24 h / 7 Tage / 30 Tage). Das ist eine eigene Seite mit eigener
> Abfrage-Schicht und gehört nicht halbfertig in einen Merge-Lauf. Der
> Teil „Relais-Signal" daraus ist gebaut (#428) — er war die Messung,
> die in der Frage nach DR5 gefehlt hat.

*ERWARTET:* je PR „merged", danach `develop` CLEAN.

*STOPP, wenn:* ein PR DIRTY bleibt oder die CI rot wird. Dann nichts
weiter mergen, Ausgabe an mich — ich löse den Konflikt (kein Rebase, kein
Force-Push).

*Wartezeit:* das Skript wartet je PR selbst auf die CI und auf den
Deploy — bis zu 30 Minuten je PR (`-DeployTimeoutMin`). Es merged
**nichts parallel** und hält beim ersten Fehler an.

> **Sperrzeit im Skript: 14:30 bis 15:45.** In diesem Fenster merged es
> nicht (DST-Prüfung Bar). Wer dort landet, wartet oder verschiebt.

**Was das Skript selbst erledigt:** einen Zweig im Zustand `BEHIND` holt
es mit `gh pr update-branch` auf Stand. Bei `DIRTY` **hält es an** und
sagt, dass ich develop einmergen muss — genau der Fall, der zwischen #428
und #429 zu erwarten ist.

### 1.2 Läuft der Stack?

*wo:* SSH (Server)

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps --format '{{.Service}}={{.Status}}'
```

*ERWARTET:* elf Dienste `Up`, die mit Healthcheck `healthy`.

*STOPP, wenn:* ein Dienst `Restarting` zeigt oder fehlt.

### 1.3 Messwerte — der eigentliche Nachweis

*wo:* SSH (Server)

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT count(*) AS messwerte, count(DISTINCT device_id) AS geraete, max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading WHERE time > now() - interval '5 minutes';"
```

*ERWARTET:* **40–55** Messwerte von ebenso vielen Geräten, `juengste`
unter zwei Minuten alt (16.11., 07:47: 54 von 54).

*STOPP, wenn:* unter 30 Geräte oder `juengste` älter als fünf Minuten.
Dann ist der Funkweg betroffen, nicht der Merge → §10ay.

### 1.4 Die Relais

*wo:* SSH (Server)

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT d.label, (r.time AT TIME ZONE 'Europe/Vienna')::timestamp(0) AS letzte_meldung, r.relay_on, r.power_w, d.watchdog_strategy FROM device d LEFT JOIN LATERAL (SELECT * FROM relay_reading rr WHERE rr.device_id = d.id ORDER BY rr.time DESC LIMIT 1) r ON true WHERE d.kind = 'relay' ORDER BY d.id;"
```

*ERWARTET:* beide Relais mit einer Meldung aus den letzten **25 Minuten**,
`watchdog_strategy = expire_and_resend` bei beiden. `relay_on` darf
beides sein — das entscheidet der Regler.

*STOPP, wenn:* eine Meldung älter als 25 Minuten ist **und** die Leistung
0 W zeigt, während die Zone unter Soll liegt.

### 1.5 Die Kacheln

*wo:* Oberfläche → Startseite

*ERWARTET:* alle Kacheln tragen Zahlen, keine Platzhalter, keine kaputten
Umlaute. Plattenplatz **grau** mit einem Prozentwert unter 85 (16.11.:
66 %, 25 GB frei).

### 1.6 Das Aufräumen von #412

*wo:* SSH (Server), **zehn Minuten** nach dem Deploy

```bash
grep Aufraeumen /var/log/heizung-deploy.log | tail -8
```

*ERWARTET:* Zeilen `Aufraeumen: …` und `Aufraeumen fertig. Frei: … GB ->
… GB.` **Kein** `FEHLER`.

> Der Pfad hieß im Merge-Plan vom 16.11. früh falsch
> (`heizung-deploy-pull.log`, nach dem **Dienst**namen). Korrigiert in
> #426.

---

# Phase 2 — Wartungsblock

**Betreiber am Gateway, von hier bis Phase 3 fertig.**

Reihenfolge und Begründung: die Log-Grenzen (§10be) **vor** dem Neustart,
weil der Docker-Dienst die `daemon.json` beim **Start** liest. Das Pinning
(#424) **nach** der grünen Prüfliste, weil es neun Dienste neu erstellt —
und weil die neu erstellten Container dann die Log-Grenze in einem Zug
mitbekommen. Eine Neuerstellung, zwei Wirkungen, **eine** Gateway-Prüfung.

## 2a — Vorher-Werte sichern

**Ohne diese Werte kein Neustart.** Der Handgriff, der hilft, löscht die
Spur (§10ay, die Lehre vom 04.11.).

### 2a.1 Paketverlust über 48 Stunden

*wo:* SSH (Server)

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "WITH f AS (SELECT sr.device_id, sr.fcnt, sr.time, lag(sr.fcnt) OVER (PARTITION BY sr.device_id ORDER BY sr.time) AS vorher FROM sensor_reading sr WHERE sr.time > now() - interval '48 hours') SELECT count(DISTINCT device_id) AS geraete, count(*) AS angekommen, coalesce(sum(CASE WHEN vorher IS NOT NULL AND fcnt > vorher THEN fcnt - vorher - 1 ELSE 0 END), 0) AS fehlend, round(100.0 * coalesce(sum(CASE WHEN vorher IS NOT NULL AND fcnt > vorher THEN fcnt - vorher - 1 ELSE 0 END), 0) / nullif(count(*), 0), 2) AS verlust_proz FROM f;" | tee /root/vorher-verlust-48h-$(date +%F).txt
```

*ERWARTET:* rund 100 Geräte, Verlust **um 1 %** (Ausgangswert 12./13.11.:
1,19 %).

*STOPP, wenn:* der Verlust über 3 % liegt. Dann ist heute kein Tag für
einen Neustart — Ausgabe an mich.

### 2a.2 Containerzeiten

*wo:* SSH (Server)

```bash
docker inspect -f '{{.Name}} gestartet={{.State.StartedAt}} Neustarts={{.RestartCount}}' $(docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps -q chirpstack-gateway-bridge mosquitto chirpstack api) | tee /root/vorher-container-$(date +%F).txt
```

*ERWARTET:* vier Zeilen, `Neustarts=0`.

### 2a.3 Die Kachel Funk-Empfang

*wo:* Oberfläche → Startseite

**Wert ablesen und einen Screenshot machen. Ohne Screenshot kein
`reboot`.** Der Grund: nach dem Neustart ist „war das vorher auch so?"
die erste Frage, und sie ist ohne Bild nicht beantwortbar.

### 2a.4 Die ADR-Acks wegsichern

*wo:* SSH (Server)

**Pflicht, und zwar jetzt** — nicht erst vor Phase 3. Jede Neuerstellung
von chirpstack legt ein leeres Protokoll an, und `tx_power_index` steht in
**keiner** Datenbank von uns.

```bash
docker logs deploy-chirpstack-1 2>&1 | grep "LinkADRReq acknowledged" > /var/log/heizung-adr-acks-$(date +%F).log; wc -l /var/log/heizung-adr-acks-$(date +%F).log
```

*ERWARTET:* mindestens **183** Zeilen.

*STOPP, wenn:* deutlich weniger. Dann wurde der Container seither neu
erstellt und die Vorgeschichte ist schon weg — melden, bevor es weitergeht.

> **Und was diese Datei nicht leistet:** sie deckt **55 von 103**
> meldenden Geräten (gemessen 16.11.). ADR schreibt nur bei einer
> Änderung. Belastbar ist 2a.1, der Paketverlust — siehe den Kasten bei
> §10av Schritt 6a.

## 2b — Log-Grenzen einrichten (§10be)

**Dieser Handgriff startet nichts neu und erstellt keinen Container neu.**
Das ist mit Attrappen geprüft, nicht nur beabsichtigt
(`backend/tests/test_log_limits.py`).

*wo:* SSH (Server)

```bash
cd /opt/heizung-sonnblick && git log -1 --oneline
```

*ERWARTET:* der Commit aus Phase 1.

```bash
bash /opt/heizung-sonnblick/infra/deploy/install-log-limits.sh
```

*ERWARTET:* vier Zeilen `[install-log-limits]`, darunter
„logrotate --debug: Regel ist lesbar."

*STOPP, wenn:* das Skript abbricht, weil schon eine `daemon.json` mit
anderem Inhalt liegt. Es zeigt dann den Unterschied und überschreibt
nichts — Ausgabe an mich.

```bash
dockerd --validate --config-file=/etc/docker/daemon.json
```

*ERWARTET:* `configuration OK`.

*STOPP, wenn:* etwas anderes. Dann `rm /etc/docker/daemon.json` und
melden. **Eine fehlerhafte Datei hindert `dockerd` am Starten**, und
gemerkt würde das erst beim `reboot` — zum schlechtesten Zeitpunkt.

> Ab hier wirkt die **logrotate**-Regel von selbst, mit dem nächsten
> `logrotate.timer` (täglich 00:00). Die Docker-Grenze wirkt erst nach dem
> Neustart **und** einer Neuerstellung.

## 2c — Updates und Neustart (C6)

*wo:* SSH (Server). **Betreiber am Gateway.**

### 2c.1 Prüfen, dass der Plugin-Eintrag noch nicht gerendert ist

```bash
docker run --rm -v deploy_chirpstack_config_rendered:/vol:ro alpine:3.20 grep -c '^[[:space:]]*adr_plugins' /vol/chirpstack.toml || true
```

*ERWARTET:* **0**. #425 ist in Phase 1 **nicht** gemergt, der Eintrag darf
hier also nicht stehen.

*STOPP, wenn:* **1**. Dann ist das Plugin schon scharf, und der Neustart
wäre zwei Änderungen auf einmal — Ausgabe an mich.

### 2c.2a Zeigen, was ansteht — **ab hier am Gateway**

```bash
apt-get update -qq && apt list --upgradable 2>/dev/null | grep -iE 'docker|containerd' || echo '(keine Docker-Pakete im Update)'
```

*ERWARTET* (am 16.11.2026 gemessen): sechs Zeilen — `containerd.io`
2.2.3 → 2.4.2, `docker-ce` 29.4.0 → 29.9.3, dazu cli, rootless-extras,
buildx, compose-plugin.

```bash
apt list --upgradable 2>/dev/null | grep -c '^[^ ]*/' ; apt list --upgradable 2>/dev/null | grep -ci security
```

*ERWARTET:* **59** Updates, davon **0** Sicherheits-Updates.

### 2c.2b Die Docker-Pakete für heute zurückhalten

> **Befund des Betreibers, 16.11.2026.** `dist-upgrade` nimmt `docker-ce`
> und `containerd.io` mit. Beide starten beim Einspielen ihren Dienst neu
> — und damit **alle Container inklusive Mosquitto**, also die
> Gateway-Gefahr aus §10ay, **vor** dem geplanten Reboot und vor den
> T+10-Prüfungen. Zwei Störungen statt einer, und die erste ungeplant.

Bei **null** Sicherheits-Updates gibt es dafür heute keinen Grund:

```bash
apt-mark hold docker-ce docker-ce-cli docker-ce-rootless-extras containerd.io docker-buildx-plugin docker-compose-plugin
```

*ERWARTET:* sechs Zeilen `… auf Halten gesetzt.`

```bash
apt-mark showhold
```

*ERWARTET:* genau diese sechs Namen.

### 2c.2c Der Rest

```bash
DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold dist-upgrade
```

**Was die zwei `Dpkg::Options` tun:** `--force-confold` behält
**vorhandene** Konfigurationsdateien; `--force-confdef` nimmt die
Paket-Vorgabe nur dort, wo **nichts** von Hand geändert wurde. Zusammen:
keine Rückfrage, nichts Selbstgeschriebenes überschrieben. Ohne sie
bliebe `apt` an einer Dialogbox stehen, während jemand am Gateway wartet.

```bash
find /etc -name '*.dpkg-dist' -newermt '-1 hour' 2>/dev/null | head
```

*ERWARTET:* leer oder eine Handvoll Pfade — **heute nichts tun**, nur
melden.

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps --format '{{.Service}}={{.Status}}'
```

*ERWARTET:* elf Dienste `Up`, **Laufzeiten unverändert**. Genau das
belegt, dass Docker nicht angefasst wurde.

*STOPP, wenn:* ein Dienst eine Laufzeit unter fünf Minuten zeigt → der
Docker-Dienst ist doch neu gestartet. **Sofort zu den zwei
Gateway-Prüfungen aus 2c.4 springen.**

### 2c.2d Danach: das Halten wieder aufheben

**Nicht heute, aber nicht vergessen** — ein gehaltenes Paket ist still
und fällt monatelang nicht auf:

```bash
apt-mark unhold docker-ce docker-ce-cli docker-ce-rootless-extras containerd.io docker-buildx-plugin docker-compose-plugin
```

Das Docker-Upgrade gehört in einen **eigenen** Termin mit
Gateway-Prüfung: es startet beim Einspielen alle Container neu, genau wie
ein Reboot.

### 2c.3 T+7 — der Neustart

```bash
reboot
```

**Kein `systemctl restart docker` von Hand.** Das startet alle Container
neu, Mosquitto eingeschlossen — dieselbe Gateway-Gefahr für dieselbe
Wirkung, nur ohne den vorbereiteten Rahmen.

*Wartezeit:* **T+10**, also rund drei Minuten, bis die Verbindung wieder
steht.

### 2c.4 T+10 — Prüfliste, erster Teil

```bash
docker info --format '{{.LoggingDriver}}'
```

*ERWARTET:* `json-file`.

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps --format '{{.Service}}={{.Status}}'
```

*ERWARTET:* elf Dienste `Up`.

> **Korrigiert am 17.11.2026.** Hier stand ein `tail -f` auf das
> Caddy-Protokoll mit `grep router` — der **Basic-Station**-Weg. Das UG65
> spricht kein Basic Station; es publiziert per **MQTT auf 1883** und
> meldet sich bei Mosquitto als `gateway-ug65` an. Die Quelle des Fehlers
> war §10ay, das seit dem 07.11. nicht nachgezogen war; dort ist es jetzt
> ebenfalls richtig.

**Erste Prüfung: hat sich das Gateway neu verbunden?**

```bash
docker logs deploy-mosquitto-1 --since 5m 2>&1 | grep -c "u'gateway-ug65'" || true
```

*ERWARTET:* **mindestens 1** — der Reboot hat die MQTT-Sitzung beendet,
das Gateway muss sich neu anmelden.

> Im **Normalbetrieb** steht dort 0, und das ist gesund: die Sitzung wird
> einmal aufgebaut und bleibt. Am 16.11. gemessen — die letzte Verbindung
> stammte vom 10.11. Eine 0 ohne vorangegangene Unterbrechung ist kein
> Befund.

**Zweite Prüfung: kommen Messwerte?** Das misst das Ende der Kette.

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT count(*) AS messwerte, count(DISTINCT device_id) AS geraete, max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading WHERE time > now() - interval '3 minutes';"
```

*ERWARTET:* zweistellige Gerätezahl, `juengste` unter zwei Minuten.

*STOPP und Stromtrennung am UG65 nur, wenn **beides** leer bleibt* —
keine Neuanmeldung **und** keine Messwerte. Kommt eines von beiden, ist
der Weg in Ordnung.

**Wer alle Clients sehen will:**

```bash
docker logs deploy-mosquitto-1 --since 30m 2>&1 | grep -oE "u'[^']+'" | sort | uniq -c
```

*ERWARTET nach einem Neustart:* `gateway-ug65`, `chirpstack-integration`,
`chirpstack-gw-eu868`, `heizung-api*`.

### 2c.5 T+21 — Prüfliste, zweiter Teil

*Wartezeit:* von T+10 noch **zehn Minuten die Kachel Funk-Empfang
ansehen**, gegen den Screenshot aus 2a.3.

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT count(*) AS messwerte, count(DISTINCT device_id) AS geraete, max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading WHERE time > now() - interval '5 minutes';"
```

*ERWARTET:* 40–55 Messwerte, `juengste` unter zwei Minuten.

*STOPP, wenn:* die Kachel schlechter steht als auf dem Screenshot oder die
Zahl nicht zurückkommt. **Dann endet Phase 2 hier** — 2d und 2e entfallen,
Phase 3 entfällt. Die logrotate-Regel aus 2b wirkt trotzdem, und nichts
davon ist zeitkritisch: die Platte steht bei 66 %.

## 2d — #424 mergen (Pinning), nur bei grüner Prüfliste

*wo:* PowerShell (lokal)

```
merge-paket 424
```

*Wartezeit:* der Timer zieht alle 5 Minuten. **6 Minuten warten.**

> **Was dieser Merge tut:** er ändert die `image:`-Zeilen von `db`,
> `redis`, **`mosquitto`**, `chirpstack-postgres`, `chirpstack`,
> **`chirpstack-gateway-bridge`**, `caddy` und den zwei Init-Behältern.
> Der Timer erstellt jeden davon neu — deshalb steht dieser Schritt hier
> und nicht im Merge-Fenster. Nebeneffekt, der ihn hierher gehören lässt:
> weil `dockerd` die `daemon.json` beim Neustart gelesen hat, bekommen alle
> neu erstellten Container die Log-Grenze mit.

### 2d.1 Die Neuerstellung ansehen

*wo:* SSH (Server)

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps --format '{{.Service}}={{.Status}}'
```

*ERWARTET:* elf Dienste `Up`, die Infrastruktur-Dienste mit einer
Laufzeit von **unter zwei Minuten** (sie sind gerade neu entstanden).

### 2d.2 Die Log-Grenze je Container

```bash
docker inspect $(docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps -q) --format '{{.Name}} {{json .HostConfig.LogConfig.Config}}'
```

*ERWARTET:* bei **jedem** Dienst
`{"compress":"true","max-file":"16","max-size":"100m"}`.

*STOPP, wenn:* bei einem Dienst `{}` steht **und** seine Laufzeit über
zwei Minuten liegt — dann wurde er nicht neu erstellt, und das ist zu
klären, bevor es weitergeht.

### 2d.3 Die Gateway-Prüfung nach der Neuerstellung

> **Zweimal korrigiert, und die zweite Korrektur ist die wichtigere.**
> Hier stand erst die Caddy-`router`-Prüfung (falscher Weg), danach der
> Satz „`gateway-ug65` muss nicht dabei sein — das Gateway wurde nicht
> angefasst". **Auch das war falsch, und zwar gefährlich falsch:** #424
> ändert die `image:`-Zeile von **`mosquitto`**. Der Broker wird neu
> erstellt, und damit bricht **jede** MQTT-Sitzung ab — auch die des
> UG65.

**Nach 2d MUSS sich das Gateway neu anmelden:**

```bash
docker logs deploy-mosquitto-1 --since 5m 2>&1 | grep -c "u'gateway-ug65'" || true
```

*ERWARTET:* **mindestens 1**, innerhalb von zwei bis drei Minuten.

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT count(*) AS messwerte, count(DISTINCT device_id) AS geraete, max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading WHERE time > now() - interval '3 minutes';"
```

*ERWARTET:* zweistellige Gerätezahl, `juengste` unter zwei Minuten.

*STOPP, wenn:* nach **zwei bis drei Minuten** weder eine Neuanmeldung
noch Messwerte da sind → **Stromtrennung am UG65** (§10ay Schritt 5).
Stecker ziehen, zehn Sekunden warten, wieder einstecken; danach dauert es
einige Minuten.

> **Ein `--force-recreate` von `chirpstack` und `api` hilft hier nicht.**
> Das Gateway ist das, was sich neu anmelden muss; die beiden Dienste
> stehen nicht in seinem Weg. Sie neu zu erstellen wäre eine weitere
> MQTT-Unterbrechung ohne Gegenwert. Diese Zeile stand hier und ist
> **heraus**.

### 2d.4 Messwerte

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT count(*) AS messwerte, count(DISTINCT device_id) AS geraete, max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading WHERE time > now() - interval '5 minutes';"
```

*ERWARTET:* 40–55 Messwerte, `juengste` unter zwei Minuten.

## 2e — ChirpStack-API-Secret rotieren

**Anlass:** mein Notfall-Befehl vom 15.11. endete auf einem Zeilenbereich
(`sed -n '36,46p'`), und weil das Löschen der Pfadzeile den Bereich
verschob, stand `secret = …` **aufgelöst** auf dem Bildschirm und in der
Terminal-Historie (§5.89).

**Folgen, damit sie niemanden überraschen.** Das Geheimnis signiert die
API- und UI-Sitzungstoken von ChirpStack. Nach dem Wechsel sind **laufende
Anmeldungen in der ChirpStack-Oberfläche ungültig** und **ausgestellte
API-Token ebenfalls** — Sie müssen sich dort neu anmelden. **Unsere
Anwendung ist nicht betroffen:** der Downlink-Weg läuft über MQTT, nicht
über die ChirpStack-API (§5.28), und `CHIRPSTACK_API_KEY` ist ein eigenes
Geheimnis. Nur das Provisionierungs-Skript nutzt es, und das läuft im
Montagefenster.

### 2e.1 Neues Geheimnis erzeugen und einsetzen

*wo:* SSH (Server)

```bash
cd /opt/heizung-sonnblick/infra/deploy && cp .env .env.bak-vor-secret-$(date +%F) && NEU=$(openssl rand -hex 32) && sed -i "s|^CHIRPSTACK_API_SECRET=.*|CHIRPSTACK_API_SECRET=${NEU}|" .env && unset NEU && grep -c '^CHIRPSTACK_API_SECRET=' .env
```

*ERWARTET:* **1**.

> **Der Wert wird nicht angezeigt, und das ist Absicht.** `grep -c`
> zählt, `grep` würde zeigen. Niemand muss das Geheimnis sehen — der
> Sidecar liest es aus der Datei.

*STOPP, wenn:* die Zahl 0 oder größer 1 ist. Dann hat das `sed` nicht
getroffen → `cp .env.bak-vor-secret-$(date +%F) .env` und melden.

### 2e.2 Neu rendern und chirpstack neu erstellen

```bash
cd /opt/heizung-sonnblick/infra/deploy && docker compose -f docker-compose.prod.yml up -d --force-recreate --no-deps chirpstack-init chirpstack
```

*ERWARTET:* `chirpstack-init` beendet sich (`Exited (0)`), `chirpstack`
läuft.

*Wartezeit:* **60 Sekunden**, dann:

```bash
docker logs deploy-chirpstack-1 --since 3m 2>&1 | grep -ciE 'error|panic' || true
```

*ERWARTET:* **0**.

*STOPP, wenn:* größer 0 → Ausgabe an mich (die Zeilen selbst bitte mit
`grep -iE 'error|panic'`, **nicht** mit `tail`).

### 2e.3 Neu anmelden

*wo:* ChirpStack-Oberfläche

*ERWARTET:* die alte Sitzung ist abgelehnt, die neue Anmeldung geht.

### 2e.4 Messwerte

Derselbe Befehl wie 2d.4. *ERWARTET:* 40–55 Messwerte, `juengste` unter
zwei Minuten.

---

# Phase 3 — entfällt

**Entscheidung des Betreibers vom 16.11.2026: das Plugin kommt heute
nicht.** #425 bleibt fertig liegen und wird **nicht** gemergt.

**Der Grund ist eine Messung, nicht ein Zögern.** Nach der Stromtrennung
am 16.11. um 08:39 läuft Relais 108 auf **DR0** (SF12) — eine Stufe
**robuster** als die DR1, die das Plugin festnageln würde. Seither:

```
Verlust 108 seit dem Rejoin:  16 Frames angekommen, 0 fehlend  ->  0,0 %
Verlust 108 die sechs Stunden davor (DR5):                        25,8 %
SNR je Frame:  -8,5 dB      RSSI: -105 dBm
zum Vergleich 109 Panel:  SNR +4,6 dB, RSSI -99 dBm, DR5
```

Dreizehn Dezibel Unterschied im selben Haus: **der Link von 108 ist zu
schwach, die Pakete kollidieren nicht.** Und er klettert auch nicht
zurück — bei DR0 bräuchte ADR für eine Stufe nach oben ein SNR von
**+3 dB**, gemessen sind −8,5. Die Reserve von 20 dB hält ihn unten.

Das Plugin würde heute also einen Zustand verschlechtern, der
fehlerfrei läuft. **Die Regel für später steht in §10av.**

# Phase 4 — `refresh` für 108 einschalten

**109 Panel bleibt auf `expire_and_resend`** und ist damit die
Vergleichsgruppe im selben Haus bei gleichem Wetter. Die Bar erreicht ihr
Soll, die Rezeption nicht — deshalb wird dort umgeschaltet.

## 4a — Der Handgriff

**Anmeldung als `verwaltung@hotel-sonnblick.at`.** (Hier stand bis zum
17.11. `kaprun@` — falscher Benutzer.)

*wo:* PowerShell (lokal). **Das Passwort tippen Sie; es steht in keiner
Datei und erscheint nicht am Schirm.**

```powershell
$sicher = Read-Host "Passwort verwaltung@hotel-sonnblick.at" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sicher)
try { $klar = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
$body = @{ email = 'verwaltung@hotel-sonnblick.at'; password = $klar } | ConvertTo-Json -Compress
Remove-Variable klar
Invoke-RestMethod -Uri 'https://heizung.hoteltec.at/api/v1/auth/login' -Method Post -ContentType 'application/json' -Body $body -SessionVariable sitzung | Out-Null
Remove-Variable body, sicher
"angemeldet: $($sitzung.Cookies.Count) Cookie(s)"
```

*ERWARTET:* `angemeldet: 1 Cookie(s)`, keine rote Fehlermeldung.
*STOPP, wenn:* `401` → Anmeldung prüfen. Bei `500` Ausgabe an mich.

```powershell
Invoke-RestMethod -Uri 'https://heizung.hoteltec.at/api/v1/devices/109/relay/watchdog-strategy' -Method Patch -ContentType 'application/json' -Body '{"strategie":"refresh"}' -WebSession $sitzung
```

*ERWARTET:* `strategie : refresh`, `timer_sekunden : 900`.

**Die Geräte-Id ist 109, das Etikett „108".** 110 wäre „109 Panel" — und
das wollen wir hier gerade nicht.

```powershell
Remove-Variable sitzung
```

### Dieselben Schritte in Bash (Git Bash)

```bash
read -rsp "Passwort verwaltung@hotel-sonnblick.at: " P; echo; curl -s -c /tmp/h.jar -o /dev/null -w "login=%{http_code}\n" -X POST https://heizung.hoteltec.at/api/v1/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"verwaltung@hotel-sonnblick.at\",\"password\":\"$P\"}"; unset P
```

```bash
curl -s -b /tmp/h.jar -X PATCH https://heizung.hoteltec.at/api/v1/devices/109/relay/watchdog-strategy -H 'Content-Type: application/json' -d '{"strategie":"refresh"}'; echo
rm -f /tmp/h.jar
```

## 4b — Dass es gewirkt hat

*wo:* SSH (Server)

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT id, label, watchdog_strategy, (relais_ein_gesendet_at AT TIME ZONE 'Europe/Vienna')::timestamp(0) AS ein_gesendet FROM device WHERE kind = 'relay' ORDER BY id;"
```

*ERWARTET:* 109 auf **`refresh`**, 110 auf **`expire_and_resend`**.
`relais_ein_gesendet_at` bei 109 **leer** — das Umschalten setzt es
zurück, und der nächste Einschaltbefehl füllt es wieder.

*Wartezeit:* **30 Minuten**, dann die Funklast gegen die Vergleichsgruppe:

```bash
docker logs deploy-celery_worker-1 --since 30m 2>&1 | grep -c 'relais ein dev_eui=70b3d52ddd001f23' || true
docker logs deploy-celery_worker-1 --since 30m 2>&1 | grep -c 'relais ein dev_eui=70b3d52ddd001e69' || true
```

*ERWARTET:* für **108** (erste Zeile) rund **6**, für **109 Panel**
(zweite Zeile) **0 bis 1**.

**Woher die 6 kommt, und warum hier nicht „wenige" steht.** `refresh`
setzt alle `relay_refresh_intervall_s` **= 300 Sekunden** nach, mit einem
Timer von `relay_timer_refresh_s` **= 900 Sekunden**
(`tasks/relay_tasks.py` Zeilen 191/192). Also ein Befehl alle fünf
Minuten, und der Timer am Gerät läuft nie ab — das ist der ganze Zweck.
In 30 Minuten sind das sechs Befehle, **solange die Zone heizen will**.
Will sie nicht, sind es null, und das ist kein Mangel.

> Mein erster Entwurf stand hier auf „0 oder 1 in 15 Minuten, STOPP bei
> 3". Das war aus dem Timer-Wert geraten statt aus dem Abstand gelesen —
> und hätte beim ersten Blick falschen Alarm gegeben. Ein Melder, der im
> gesunden Zustand rot zeigt, wird nach dem zweiten Mal ignoriert (§5.79).

**Die Sendezeit auf DR0, gerechnet** (Betreiber, 16.11.2026): 12 × 1,32 s
= **16 s/h** auf 869,525 MHz — Teilband **g3**, dort sind 10 % erlaubt,
also 360 s/h. Das sind **4,4 % des Budgets**. Unkritisch, und damit ist
der letzte Vorbehalt gegen `refresh` auf der niedrigen Datenrate
ausgeräumt.

*ERWARTET als Lastverhältnis:* 108 bekommt etwa **sechsmal** so viele
Einschaltbefehle wie vorher (vorher: alle 30 Minuten einer, also einer
in 30 Minuten; gemessen heute 09:30 mit `expire_and_resend`: **1 in 15
Minuten**). Das ist der Preis, und er ist bekannt: ein Downlink in RX2
bei DR0 kostet 1319 ms, sechs je Stunde sind 7,9 Sekunden — weit unter
jeder Grenze.

*STOPP, wenn:* 108 **mehr als 10** in 30 Minuten zeigt (das wäre öfter als
alle drei Minuten), oder 109 Panel mehr als 2 — dann hat die Umschaltung
mehr getroffen als das eine Gerät.

## 4c — Messen ab Dienstag

*wo:* SSH (Server), **Dienstag und Mittwoch je einmal**

```bash
docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --stunden 24
```

**Was die Zahlen sagen** (die Entscheidungstabelle steht in §10bd):

| Einschaltanteil in den Stunden mit Heizwunsch | Ist unter Soll? | Schluss |
|---|---|---|
| nahe 100 % | ja | **das Panel ist zu schwach** — zweites Panel kaufen |
| nahe 100 % | nein | reicht |
| unter ~80 % | ja | die Steuerung bremst noch — Frage nicht reif |

**Ausgangswert für den Vergleich, gemessen heute 16.11. früh** (vor #417,
vor `refresh`):

```
Rezeption 06:00    66%   Soll 23   Ist 20.6   Abstand 2.4 K
Rezeption 07:00    43%   Soll 23   Ist 20.9   Abstand 2.1 K
Nachtstunden       50%   genau eine Einschaltung je Stunde
```

Die 50 Prozent in der Nacht sind das Lineal: 30 Minuten ein, 30 Minuten
aus — der Timer von 1800 Sekunden plus die Totzeit danach. Und die 66/43
Prozent bei über zwei Kelvin Abstand sind der Befund, um den es geht.

---

# Was ich zur Auswertung zurückbekomme

Bitte in dieser Reihenfolge, als Text (nicht als Bild, außer dem einen
Screenshot):

1. **Phase 1:** Ausgabe von 1.2, 1.3, 1.4 und 1.6. Von 1.5 nur, wenn
   etwas auffällt.
2. **Phase 2:** 2a.1 (Verlust 48 h), 2a.2 (Containerzeiten), 2a.4
   (Zeilenzahl), der Screenshot aus 2a.3, 2b (beide Ausgaben), 2c.4
   (Logging-Treiber, Dienste, Gateway-Status), 2c.5 (Messwerte), 2d.2
   (Log-Grenzen je Container), 2d.4, 2e.1 (die **Zahl**, nicht die Zeile),
   2e.2.
3. **Phase 3:** 3a (die Zahl), 3b (Statuszeile und die gegrepten
   Protokollzeilen), 3c (steht der Eintrag in der Liste: ja/nein), 3d
   (die LinkADRReq-Zeilen und, nach zwei Stunden, der Verlustvergleich).
4. **Phase 4:** 4a (die zwei Antwortzeilen), 4b (die Tabelle und die
   Zahl), 4c am Dienstag und Mittwoch die ganze Ausgabe.

**Wenn irgendwo ein STOPP greift:** nur die Ausgabe dieses einen Schrittes
und die Nummer. Nichts weiter ausführen.

**Querverweise:** §0.3 (Merge-Fenster und die Pflicht-Frage), §10av
(Rollout Reserve und Relais, Schritte 3/5/6), §10ay (Neustart der drei
Funk-Dienste, Stromtrennung), §10be (Log-Grenzen), §10bb (Notreparatur),
§10bc (`refresh` umschalten), §10bd (`relais_auswertung` lesen), §10bg
(Pinning nachziehen), §5.89 (Konfiguration mit Geheimnissen), §5.92
(UTC neben Ortszeit), §5.78 (`docker compose` ohne `-f`), §5.0a
(Uplink-Prüfung).
