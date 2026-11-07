# Abschluss 07.11.2026 — was live ist, was offen bleibt

**Stand:** 07.11.2026, Abend · dreizehn Merges · ein Vorfall, der von mir kam

## Der Tag in einem Satz

Ein Vorschlag von mir hat die Anlage um 06:09 für **31 Minuten** ohne
Messwerte stehen lassen, und der größte Teil dessen, was heute gebaut
wurde, ist die Antwort darauf: ein Melder, der diesen Ausfall gezeigt
hätte, und eine Regel, die den Fehler nicht mehr zulässt.

## Live (gemergt am 07.11.)

| PR | Was |
|---|---|
| #381 | `ENV_NEU` hat die Werte zerstört, die es laden sollte |
| #382 | §10ab C4: die Prüfung bewies nichts, die Abnahme war unbestehbar |
| #383 | §10ay: nach Mosquitto/Caddy/Bridge das Gateway prüfen |
| #384 | Compose-Befehle einzeln einfügen, `exec` mit `-T` |
| **#386** | **Der Stand der Fenstererkennung ist ablegbar** — die Antwort auf `0x46` landet in `sensor_reading` (Migration 0038). Grundlage für die Abfrage von heute |
| #387 | Sprint-25-Brief: Befehle mit Status, Bau ab Montag |
| #388 | AE-47-Grundsatz (Gerät **oder** Server) und `docker exec` ohne `-t` |
| #389 | §10ay: nach der Stromtrennung die Funkqualität prüfen |
| **#390** | **Funk-Wächter** — SNR-Einbruch gegen die Vorwoche, Melder auf die Wirkung |
| #391 | AE-84: zweites Gateway, Entscheidungsnotiz (Entwurf) |
| **#392** | **Der Vorfall und die Regel daraus** (§5.0a) |
| **#394** | **Kachel „Funk-Empfang", Mail bei Totalausfall, drei Menüpunkte weniger** |

Dazu am Abend **#393** (Ack-Fenster), **#395** (Zugang über die
öffentliche IP) und **#396** (0x46-Ergebnis, C8).

### Was davon den Betrieb verändert

* **Ein Totalausfall meldet sich jetzt selbst.** Bis heute hätte ihn
  niemand bemerkt: die Health-Stufe `silent` greift nach 3 h, der
  Funk-Wächter urteilt bei zu wenigen Daten „unbekannt", und der
  Gateway-Status wäre grün gewesen. Ab jetzt: Kachel nach 15 Minuten rot,
  Mail nach 15 Minuten, Entwarnung bei Rückkehr.
* **„Fenster offen" lügt nicht mehr.** Statt einer `0` steht dort
  „Erkennung inaktiv" — und das ist seit heute **belegt**, nicht erschlossen.
* **Firewall-Änderungen haben eine Regel** (§5.0a): vorher belegen, wer
  den Port benutzt; nachher binnen zwei Minuten messen; sonst sofort
  zurück. §10ab C4 ist auf **⛔ NIE AUSFÜHREN** gesetzt.
* **Der Zugang zum Server ist die öffentliche IP.** Tailscale wird nicht
  wiederbelebt.

## Die drei Befunde des Tages

**1. Der Datenweg des UG65 ist MQTT auf Port 1883**, angemeldet als
`gateway-ug65`. Basic Station ist eingerichtet und **unbenutzt**. Die
Annahme, auf 1883 käme von außen nichts Legitimes, war der ganze Fehler —
und sie stand auf einer **fehlenden Umgebungsvariablen**. Die
Benutzerdatenbank des Brokers ist eine gemountete Datei und überlebt das
Entfernen der Variablen. Daraus §5.0a: *nicht ableiten, lesen.*

**2. Zimmer 209 ist nicht das, wofür ich es zweimal gehalten habe.**
Erst Reboot-Gate (durch die `fcnt`-Folge widerlegt), dann Ack-Fenster
(durch die `0x28`-Weiche widerlegt). Die Erkennung läuft **nur** für
`0x28`; Gerät 60 hat an diesem Tag 52 Frames gesendet, alle `0x81`. Eine
Drehung, deren `0x28` in der Lücke verloren ging, ist aus den folgenden
Periodenberichten **nicht** rekonstruierbar. Beide Fehlschlüsse hatten
dieselbe Ursache: eine Erklärung gebaut, **ohne den Aufrufpfad zu lesen**.

**3. Die Fenstererkennung ist aus — gemessen.** Zwei von drei Geräten
haben auf `0x46` geantwortet: `enabled = false`, Werksvorgaben 1,0 °C /
10 min. Das dritte (85) hat einen einzelnen Frame verloren und verliert
**10,9 %** aller Frames bei -110 dBm.

## Offen

### Sprint 25, Rest

| | |
|---|---|
| **Zimmer 209 / die `0x28`-Lücke** | Entscheidung des Betreibers offen. Mein Vorschlag war **Option B: sichtbar machen** statt adoptieren — eine `event_log`-Zeile, wenn ein Gerät über N Periodenberichte einen abweichenden Sollwert hält. Nicht „Abweichung übernehmen": das war der Phantom-Override von Sprint 20f-b |
| **Befehle mit Status** (offen → zugestellt → bestätigt) | Brief gemergt (#387), **Bau ab Montag**. Enthält auch die Trace-Lücke (Zonen-Override im Layer-Trace unsichtbar, S3) |
| **Obere Klammer** (Engine auf die Drehrad-Spanne) | Empfehlung asymmetrisch angenommen. Bau **erst nach** der Gegenprobe „Funk-Sollwert über der Obergrenze" — die ist geplant, nicht gesendet |
| **Dashboard-Kachel für den Funk-Wächter** | im Sprint-25-Brief als spätere Aufgabe |

### Fenster, Schritt 2 und 3

**Schritt 2 — Server-Erkennung, passiv** (Lookback 25 min, Ventilstellung
als Unterscheider). Noch nicht gebaut.

* **Prüfsatz bleiben die 49 Ereignisse aus Gerät 85.** Entscheidung des
  Betreibers vom 07.11.: dort spielt der Funk **keine Rolle** — die Daten
  liegen in der Datenbank, der Verlust von 10,9 % hat sie bereits
  passiert.
* `TESTPLAN_GERAETE` wird in diesem PR **auf Zonen** gesetzt.

**Schritt 3 — Vicki-Erkennung aktivieren.** Testgeräte **86** (306
Kinderzimmer) und **24** (105 Schlafzimmer). **Nicht 85**, Begründung:
Funkverlust **10,9 %** gegen 2,7 % bei den Nachbarn — ein Test dort
mischt „hat nicht ausgelöst" mit „die Meldung ist verloren". **Nicht
Zimmer 110**, Entscheidung vom 05.11., ebenfalls schlechter Funk. Das Bad
(87) bleibt wegen der Dusche außen vor.

> **Befund zu `TESTPLAN_GERAETE`, aufgenommen am 07.11.:** die Konstante
> steht in `services/fenstererkennung.py:72` auf
> `("105", "110", "306 Schlafzimmer")` und hat **keinen einzigen
> Konsumenten** — `grep` findet nur die Definition. Sie ist damit
> zweifach überholt (110 seit 05.11., „306 Schlafzimmer" seit heute) und
> dokumentiert einen Plan, den sie nicht ausführt. Wer sie liest und die
> Namen in `--nur` tippt, zielt auf die **falschen** Geräte. Korrektur
> nach Vorgabe im Schritt-2-PR; ein Einzeiler jetzt wäre billiger als
> eine bekannt falsche Konstante über das Wochenende (§5.20, §5.77).

### Port 1883

**#385 bleibt BLOCKIERT** (Draft, Titel-Präfix `BLOCKED`). Ziel unverändert:
1883 von außen schließen. Zwei Wege, beide noch nicht entschieden:

* **Weg A** — das UG65 auf Basic Station umstellen. Voraussetzung ist
  Zugang zur UG65-Oberfläche; Menüpfade und Messplan sind noch nicht
  geschrieben.
* **Weg B** — 1883 nur für die Hotel-IP `213.153.54.49` offen lassen. Die
  Messung dazu („seit wann kommt `gateway-ug65` von dieser IP, gab es je
  eine andere") ist **noch nicht gelaufen**.

Jede Umsetzung geht über §5.0a. Nach dem heutigen Morgen gilt zusätzlich:
nicht am selben Tag wie ein anderer Firewall-Eingriff.

### Termine 11.11.2026 (Wartungstag)

| | |
|---|---|
| **C6** | apt-Updates und Server-Neustart. Am 04.11. verschoben. Danach den **Gateway-Status ausdrücklich ansehen** — am 04.11. kam es nach einer serverseitigen Unterbrechung **nicht** von selbst zurück |
| **C8** | die UFW-Regel für `tailscale0` entfernen. Einzeln, mit Messung vorher und nachher (§5.0a). Abbruch, wenn das Interface doch existiert |
| **C7-Rest** | das Backup vom 04.11. läuft an diesem Tag ab |

### Weiter offen, älter

UG65-Packet-Forwarder-Profil · `_ts_union`-Härtung in
`test_override_quellen_spiegel.py` · `pair_devices import --dry-run`
Schlusszeilen-Marke · §10at Schritt 6 für Relais 108 · neue Vickis 105–107
nach §10as · T2-Fenstertest §10ao · Abgleich und Kindersicherung · Paket 3
· Tag `v0.3.0-heizperiode` · B-22-4 (`CHIRPSTACK_BASIC_AUTH_HASH`) ·
§10a.1 (`gateway-ug65` anlegen) · der RUNBOOK-Kollisionsvorschlag ·
uneinheitliche Container-Namen im RUNBOOK · **`REASON_OFFLINE =
"offline_24h"`** (ein Name aus Sprint 11, die Schwelle ist 3 h —
Umbenennen ändert Logzeilen und Drosselungs-Schlüssel, eigener Durchgang)

## Was ich heute über meine eigene Arbeit gelernt habe

Drei Fehler, und sie haben **eine** Form: aus einem Mechanismus auf einen
Zustand geschlossen, ohne den Zustand zu lesen.

* Die fehlende Umgebungsvariable → „der User existiert nicht" → **31
  Minuten Stillstand.**
* Die `fcnt`-Folge nicht gelesen → Reboot-Gate.
* Den Aufrufpfad nicht gelesen → Ack-Fenster als Erklärung für 209.

§5.68 steht seit dem 27.05.2026 im Repo und sagt genau das. Sie heute
dreimal verletzt zu haben, ist kein Zufall, sondern der Hinweis darauf,
dass eine plausible Kette sich wie ein Befund **anfühlt** — und dass der
Unterschied allein im Nachsehen liegt.

Die zwei neuen Tests zu #393 sind die Gegenmaßnahme in der kleinsten
denkbaren Form: die Behauptung „`received_at` ist die Gateway-Zeit" steht
nicht mehr im PR-Text, sondern im Repo, wo sie bei der nächsten Änderung
rot wird.

## Querverweise

* `docs/status/2026-11-07-vorfall-1883-sperre.md` — der Ausfall
* `docs/status/2026-11-07-ui-funkempfang.md` — der Melder dagegen
* `docs/status/2026-11-07-0x46-abfrage-ergebnis.md` — die Fenstererkennung
* `docs/status/2026-11-07-zugang-oeffentliche-ip.md` — Zugang und SSH-Härtung
* RUNBOOK §5.0a (die Regel), §10ab C4 (nie ausführen), C6/C8 (11.11.)
