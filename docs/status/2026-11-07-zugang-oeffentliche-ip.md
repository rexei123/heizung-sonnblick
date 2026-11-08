# Zugang zum Server: die öffentliche IP, und eine URL statt zwei

**Stand:** 07.11.2026 · Entscheidung des Betreibers · Doku-PR, kein Code

## Der Anlass

Ich wollte lesen, ob #386 auf dem Server angekommen ist, und kam nicht
hin. `ssh root@heizung-test` lief in einen Zeitüberlauf — und ein
Zeitüberlauf sagt nicht, warum. Die Suche danach hat zwei Dinge gefunden,
die beide schon länger so waren:

| Messung | Ergebnis |
|---|---|
| `tailscale ping heizung-test` | `peer's node key has expired` |
| `systemctl is-active tailscaled` (auf dem Server) | `inactive` |
| Node-Key-Ablauf | **17.10.2026** |
| `heizung.hoteltec.at` → TLS | 200, Zertifikat gültig bis 04.01.2027 |
| `heizung-test.hoteltec.at` → TLS | TLS-Alert 80, **kein Zertifikat** |
| Caddy-Zertifikatsspeicher | `heizung.hoteltec.at`, `cs-test.hoteltec.at` |
| `ssh root@157.90.17.150` | funktioniert, `hostname` = `heizung-test` |

## Die Entscheidung

**Tailscale wird nicht wiederbelebt.** Zugang ist die öffentliche IP
`157.90.17.150` mit dem Schlüssel `id_ed25519_heizung`. Es gibt **eine**
URL, `https://heizung.hoteltec.at`.

## Was dieser PR ändert

* **RUNBOOK:** ein Zugangs-Block direkt unter der Überschrift, 7 ×
  `root@heizung-test` → `root@157.90.17.150`, 19 × die tote URL in
  `curl`-Zeilen → `heizung.hoteltec.at`. Die Server-Tabelle sagt jetzt in
  der Überschrift, dass die Tailscale-Spalte Geschichte ist.
* **CLAUDE.md §1:** eine Produktivumgebung statt zwei.
* **CLAUDE.md §4:** der Zugangsweg, der zweite Server mit seinem
  tatsächlichen Zustand, UFW samt Port 1883, und die gemessene
  SSH-Härtung.

## Das eigentliche Ärgernis: der Befund war notiert

`heizung-test.hoteltec.at` wird seit dem **09.06.2026** nicht mehr
bedient, und das stand im RUNBOOK — an **zwei** Stellen, ausdrücklich:

> „Zweitname (nicht mehr bedient)" — §4.4-Tabelle
>
> „**Achtung:** §10g nennt hier noch `heizung-test.hoteltec.at` … Richtig
> ist `heizung.hoteltec.at`." — §10i

**Fünf Monate.** In der Zwischenzeit standen rund zwanzig `curl`-Zeilen in
demselben Dokument weiter auf dem toten Namen. Wer §10g öffnet und eine
Zeile kopiert, liest den Hinweis in §10i nicht — er steht woanders.

Das ist §5.77 in seiner teuersten Form: nicht eine falsche Aussage,
sondern eine **richtige**, die an der Stelle steht, an der niemand sucht.
Ein Hinweis auf einen Fehler ersetzt die Korrektur nicht; er verlängert
die Zeit, in der jemand den Fehler trotzdem kopiert — und er beruhigt
dabei, weil die Sache ja „dokumentiert" ist.

## SSH-Härtung: gefragt, gemessen, nichts geändert

| Einstellung (`sshd -T`) | Wert |
|---|---|
| `PasswordAuthentication` | **no** |
| `KbdInteractiveAuthentication` | **no** |
| `PermitRootLogin` | **without-password** (nur Schlüssel) |
| `PermitEmptyPasswords` | no |
| `MaxAuthTries` | 6 |
| `fail2ban` | **active**, Jail `sshd`: 6432 Fehlversuche, 466 Sperren, 1 aktuell |

Also: **kein Passwort-Pfad**, root nur mit Schlüssel, und ein Wächter, der
nachweislich arbeitet.

**Eine Feinheit, die zur Familie dieses PRs gehört.**
`/etc/ssh/sshd_config` sagt in Zeile 42 `PermitRootLogin no` — und das
gilt nicht. Das `Include /etc/ssh/sshd_config.d/*.conf` steht in Zeile
12, in sshd gewinnt der **erste** gefundene Wert, und das ist
`prohibit-password` aus `00-root-login.conf`. Wer die Hauptdatei allein
liest, bekommt die **strengere** Antwort, als die Wirklichkeit hergibt.
Hier ist das harmlos (beide Werte sperren das Passwort), aber die Methode
ist es nicht: `sshd -T` fragt den Dienst, die Datei fragt die Absicht.

## Was offen bleibt

* **`heizung-main`** (`157.90.30.116`, der alte Prod-Server, seit dem
  Promote Rückfall-Reserve, Stilllegung C1): in Tailscale seit etwa dem
  18.10.2026 offline. Ob er über seine öffentliche IP erreichbar ist,
  **habe ich nicht probiert** — es war nicht gefragt. Die RUNBOOK-Befehle
  mit `root@heizung-main` sind damit ohne geprüftes Ziel und als solche
  markiert.
* **`frontend/.env.local`** des Betreibers enthält
  `API_PROXY_TARGET=https://heizung-test.hoteltec.at` — den toten Namen.
  Folge: ein lokales `npm run dev` erreicht die API nicht. Die Datei ist
  nicht im Repo und gehört ihm; **nicht angefasst**, gemeldet.
* Die **UFW-Regel für `tailscale0`** tut ohne laufendes Tailscale nichts.
  Kein Risiko, nur ein Rest — und Reste in einer Firewall-Tabelle sind
  der Stoff, aus dem der 07.11. war.

## Querverweise

* `docs/status/2026-11-07-vorfall-1883-sperre.md` — Port 1883, derselbe Tag
* CLAUDE.md §5.77 (der notierte, nicht nachgezogene Befund), §5.68
  (Server-Zustand messen, nicht behaupten)
* RUNBOOK §1 Server-Übersicht, §4.4 DNS, §10i
