---
datum: 2026-11-16
thema: Übergabe — Log-Grenzen, tx_power_index geparkt, Image-Pinning vorgeschlagen
pr: offen
---

# Übergabe aus der Sitzung vom 16.11.2026

**Reine Doku.** Der Server ist in dieser Sitzung **nicht** verändert
worden — es liefen ausschließlich lesende Befehle (`stat`,
`docker inspect`, `docker logs`, `docker image inspect`, `psql`-Abfragen,
`gzip -c | wc -c`). Alles andere liegt als PR vor.

## Offene PRs

### #422 — Grenzen für die zwei Protokolle, die ohne Grenze wuchsen

**Stand:** offen, freigegeben vom Betreiber, **nicht gemergt** (CI lief
zuletzt erneut nach dem Doku-Commit `e67effb`). Branch
`chore/log-grenzen-deploy-und-docker`.

Inhalt: `infra/deploy/docker/daemon.json` (json-file, `max-size 100m`,
`max-file 16`, `compress`), `infra/deploy/logrotate/heizung-deploy`
(weekly, rotate 8, maxsize 50M, compress, delaycompress, notifempty,
missingok), `infra/deploy/install-log-limits.sh` (kopiert und prüft,
startet nichts), die Rechnung in `infra/deploy/docker/README.md`,
RUNBOOK **§10be**, `docs/status/2026-11-16-log-grenzen.md` und 22 Tests
in `backend/tests/test_log_limits.py`.

**Die Compose-Datei ist unberührt.** Der erste Deploy nach dem Merge
erstellt deshalb genau die vier Dienste neu, die jeder Merge neu erstellt
(`api`, `web`, `celery_worker`, `celery_beat`).

**Kernzahlen** (gemessen 16.11.2026, 05:45 UTC): chirpstack schreibt
**79,3 MB/Tag** (96 % des Problems, 29 GB/Jahr bei 25 GB frei),
`/var/log/heizung-deploy.log` 0,45 MB/Tag ohne jede Regel. Die Grenze
hält garantiert **1572 MB = 19,8 Tage** und bleibt bis zu einer Rate von
112,4 MB/Tag über den verlangten 14 Tagen. Der zur Prüfung
vorgeschlagene Wert `50m/5` hätte **2,6 Tage** gehalten.

### #423 — tx_power_index in unsere Datenbank (**geparkt**)

**Stand: Entwurf, CI war 4/4 grün, nicht gemergt.** Branch
`feat/tx-power-index-in-die-datenbank`, zuletzt `78d5f4d`.

**Entscheidung des Betreibers vom 16.11.:** parken. Der Weg liest ein
internes, undokumentiertes Feld der ChirpStack-Gerätesitzung (Protobuf
Feld 24) über eine eigene DB-Rolle und bricht potentiell mit jedem
ChirpStack-Update; der Nutzen (Sendestufe) ist gering gegenüber der
eigentlichen Wirkungsmessung (Paketverlust, §10av Schritt 6b). Für die
48-Stunden-Kontrolle genügen Verlust plus eine einmalige Momentaufnahme.

Was im Entwurf liegt, falls er je gebraucht wird: Migration 0040 (zwei
nullable Spalten auf `device`), `services/chirpstack_session.py`
(Dekoder), `tasks/leistungsstufen_tasks.py` (stündlich, ohne
`CHIRPSTACK_SESSION_DB_URL` ein No-op), RUNBOOK **§10bf** (Einrichtung
der Nur-Lese-Rolle) und 24 Tests. Die Nummer §10bf kollidiert nicht mit
§10be aus #422.

**Der belastbare Befund daraus bleibt gültig, unabhängig vom Entwurf:**
`integration.UplinkEvent` (ChirpStack 4.17) trägt die Sendeleistung des
Geräts **nicht** und kann es nicht — das Gateway kann sie nicht messen.
Und das Container-Protokoll kannte am 16.11. nur **55 von 109** Geräten,
weil ADR nur bei Änderung schreibt. Daraus folgt für §10av Schritt 6a:
die Protokoll-Pipeline antwortet **unvollständig**, und das sieht man ihr
nicht an. Sie steht deshalb mit diesem Hinweis in §10be.

### Image-Pinning — **nicht begonnen**

Kein Branch, kein PR, kein Commit. Es liegt nur der Vorschlag vor, und
seine Zahlen stehen unten in diesem Dokument, damit sie nicht verloren
gehen.

## Entscheidungen des Betreibers vom 16.11.2026

1. **#422 einverstanden**, Merge vorab möglich (Compose unberührt).
2. **Installation am Server gehört in C6** (§10aw Block 3, apt-Updates
   und Reboot mit dem Gateway in Reichweite, verschoben auf **Mi
   18.11.2026**), und zwar **vor** den Neustart. §10be ist darauf
   umgeschrieben und nennt die Abhängigkeit.
3. **Für chirpstack reicht die globale Vorgabe** aus der `daemon.json`;
   kein `logging:`-Block in der Compose-Datei.
4. **#423 nicht mergen**, als Entwurf parken (Begründung oben).
5. **Image-Pinning: nur Vorschlag**, nicht bauen.
6. Abschnittsnummern §10be/§10bf: beliebig, Hauptsache konfliktfrei.

Dazu aus dieser Sitzung übernommen, weil es Folgen für den Termin hat:
**neu erstellt wird in §10be nur `chirpstack`.** `mosquitto`
(1,74 MB/Tag) und die Bridge (0,0003 MB/Tag) brauchen Jahre bis zur
ersten Rotation; jede Neuerstellung dort ist eine eigene Gateway-Gefahr
(§10ay, 04.11.).

## Nächste Schritte

1. **#422 mergen** (Merge-Fenster werktags 10–12, vorher die Frage nach
   einem laufenden Montage- oder Eingangstest, §0.3).
2. **Mi 18.11., C6** nach §10aw Block 3, mit §10be dazwischen:

   | C6-Zeitpunkt | Handgriff |
   |---|---|
   | vor T−10 | `bash infra/deploy/install-log-limits.sh`, dann `dockerd --validate --config-file=/etc/docker/daemon.json` |
   | T−10 | **Vorher-Wert** der Kachel Funk-Empfang ablesen **und Screenshot** (ohne Screenshot kein Reboot) |
   | T0 … T+6 | `apt-get update && apt-get dist-upgrade -y`, dann `ps` prüfen |
   | T+7 | `reboot` — damit liest der Docker-Dienst die `daemon.json`. **Kein** `systemctl restart docker` von Hand |
   | T+10 … T+21 | C6-Prüfliste, zehn Minuten Kachel ansehen |
   | nach T+21, grün | §10be Schritt 4 (ADR-Acks wegsichern, ≥ 183 Zeilen erwartet), Schritt 5 (`up -d --force-recreate chirpstack`), Schritt 6 (`map[compress:true max-file:16 max-size:100m]` bei chirpstack, `map[]` bei den übrigen zehn — richtig so) |

3. **Bricht C6 ab**, endet §10be bei Schritt 3. Die logrotate-Regel wirkt
   trotzdem (sie braucht Docker nicht), und nichts davon ist zeitkritisch:
   die Platte steht bei 66 %.
4. **Entscheidung offen:** ob der Image-Pinning-PR gebaut wird, und wenn
   ja, ob eigener Wartungstermin oder gebündelt mit C6 (unten).

## Der Pinning-Vorschlag, in Kurzform

**Richtigstellung zur Begründung:** der Neustart am Mi 18.11. kann
**keine** neue Version laden. `pull_policy: always` steht nur bei `api`,
`web` und den beiden celery-Diensten; für die Infrastruktur gilt die
Compose-Vorgabe `missing`, und alle acht Infrastruktur-Images sind lokal
vorhanden (geprüft). `deploy-pull.sh` zieht ohnehin nur `api web`.

Die echte Gefahr: sobald ein Image lokal **fehlt**, holt die nächste
Neuerstellung, was gerade unter `:4`, `:2` oder `latest-pg16` liegt. Am
14.11. wurden 108 Images entfernt; heute sind es wieder **117 Images,
29,9 GB, davon 31,3 GB reklamierbar**. Wäre das chirpstack-Image bei der
Notreparatur am 15.11. weggeräumt gewesen, hätte sie **4.18** gezogen
statt 4.17.0 — mitten im Störfall. Festnageln ist also
Wiederherstellbarkeit, nicht Schutz vor dem Mittwoch.

**Laufender Stand und Digests** (`docker image inspect`, 16.11.2026).
Vorschlag: Tag **plus** Digest je Zeile — die Zeile bleibt lesbar, der
Digest entscheidet; dazu ein Kommentar mit der Klartext-Version.

| Compose-Zeile | Dienst | Tag heute | läuft | Digest (`sha256:`) |
|---|---|---|---|---|
| 21 | `db` | `timescale/timescaledb:latest-pg16` | PostgreSQL 16.13, timescaledb 2.26.3 | `95a7997408e3295935e4afe8af8c09aae22bd51732131d1e7351c63d6198a71c` |
| 36 | `redis` | `redis:7-alpine` | Redis 7.4.8 | `7aec734b2bb298a1d769fd8729f13b8514a41bf90fcdd1f38ec52267fbaa8ee6` |
| 45 | `mosquitto` | `eclipse-mosquitto:2` | 2.1.2 | `a908c65cc8e67ec9d292ef27c2c0360dbaaee7eb1b935cdd194e67697f15dea1` |
| 68 | `chirpstack-postgres` | `postgres:16-alpine` | PostgreSQL 16.13 | `4e6e670bb069649261c9c18031f0aded7bb249a5b6664ddec29c013a89310d50` |
| 86, 120 | die zwei Init-Behälter | `alpine:3.20` | — | `d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc` |
| 142 | `chirpstack-gateway-bridge` | `chirpstack/chirpstack-gateway-bridge:4` | 4.1.1 | `14a1b367a33b349d3e0a7375e221588def43374cd7ea312e2eb8f4b7c23481b1` |
| 157 | `chirpstack` | `chirpstack/chirpstack:4` | 4.17.0 | `72cabb115c67be01878a3489ad28cb10a529b441e92ec6942fe038ca6a569752` |
| 332 | `caddy` | `caddy:2-alpine` | v2.11.2 | `834468128c7696cec0ceea6172f7d692daf645ae51983ca76e39da54a97c570d` |
| 178, 204, 243, 321 | `api`, `web`, `celery_*` | `ghcr.io/…:${IMAGE_TAG:-develop}` | `develop-c157988` | unverändert, H-6 pinnt je Commit |

**Welche Dienste der Merge neu erstellt:** jeden, dessen Zeile sich
ändert — also `db`, `redis`, **`mosquitto`**, `chirpstack-postgres`,
`chirpstack`, **`chirpstack-gateway-bridge`**, `caddy` und die zwei
Init-Behälter, dazu wie immer `api`, `web`, `celery_worker`,
`celery_beat`. Und zwar **innerhalb von fünf Minuten**: der Timer zieht
`origin/develop` und ruft `docker compose up -d` (§0.3). Ein Pinning-PR
gehört deshalb selbst in einen Wartungstermin, nicht ins Merge-Fenster.

**Zwei Wege:**

1. **Eigener Wartungstermin** — PR mergen, Timer erstellt neu, danach
   §10ay. Sauber getrennt, kostet einen weiteren Termin mit demselben
   Gateway-Risiko.
2. **Mit C6 bündeln** — `daemon.json` einrichten → `reboot` →
   C6-Prüfliste grün → **dann** den Pinning-PR mergen → der Timer
   erstellt die Infrastruktur-Dienste neu → §10ay. **Nebeneffekt:** weil
   der Docker-Dienst die `daemon.json` beim Neustart gelesen hat,
   bekommen alle neu erstellten Container in einem Zug auch die
   Log-Grenze — genau das, was §10be Schritt 5 für `mosquitto`, die
   Bridge, `caddy`, `db`, `redis` und `chirpstack-postgres` einzeln nicht
   riskieren wollte. Eine Neuerstellung, zwei Wirkungen, eine
   Gateway-Prüfung. Preis: zwei Änderungen gleichzeitig im Spiel, wenn
   etwas klemmt.

**Kosten des Festnagelns:** Sicherheitspatches für `postgres`, `caddy`
und `redis` kommen danach nie mehr von selbst mit. Dagegen hilft nur ein
Ritual — einmal je Quartal oder bei einem CVE, der zählt, die Digests
bewusst nachziehen, in einem eigenen PR mit einem Termin für die
Neuerstellung. Der Pinning-PR sollte dieses Rezept als RUNBOOK-Abschnitt
gleich mitbringen, sonst ist der eingefrorene Stand in einem Jahr ein
unbemerkter Dauerzustand.

## Stand der Arbeitskopie

Beide Branches sind gepusht, der Arbeitsbaum ist leer, nichts liegt
halbfertig lokal. Die Wegwerf-Container dieser Sitzung (ein Postgres und
ein Redis für den Testlauf) sind entfernt; `heizung-test-db` und der
lokale Compose-Stack wurden nicht angefasst.
