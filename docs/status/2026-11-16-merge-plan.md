---
datum: 2026-11-16
thema: Merge-Plan für das Fenster 10–12 Uhr
pr: —
---

# Merge-Plan Mo 16.11.2026, Fenster 10–12

Fünf PRs, alle 4/4 grün. Zwei davon sind **Steuerpfad** und unten
besonders markiert.

## Vor dem ersten Merge

**Pflicht-Frage (§0.3):** Läuft gerade ein Montage- oder Eingangstest?
Ein Deploy rekreiert den api-Container mitten im Lauf, und das Gerät, das
dabei in der Bestätigungs-Kette hängt, bekommt die Downlinks beim Resume
**erneut**.

## Die Reihenfolge, eine `merge-paket`-Zeile

```
420 -> 421 -> 419 -> 418 -> 412 -> 417 -> 416
```

| PR | Thema | Steuerpfad? | Wirkt sofort? |
|---|---|---|---|
| [#420](https://github.com/rexei123/heizung-sonnblick/pull/420) | Notreparatur als §10bb, zwei Lessons, Hygiene | nein | nein (Doku + Testhygiene) |
| [#421](https://github.com/rexei123/heizung-sonnblick/pull/421) | Drei Vorprüfungen (Plugin-Format, Verdichtung, Tagesplan) | nein | nein (nur Doku) |
| [#419](https://github.com/rexei123/heizung-sonnblick/pull/419) | Eingangstest ohne Relais | nein | nein (Montage-Werkzeug) |
| [#418](https://github.com/rexei123/heizung-sonnblick/pull/418) | Auswertungswerkzeug | nein | nein (eigener Aufruf) |
| [#412](https://github.com/rexei123/heizung-sonnblick/pull/412) | Platten-Warnung + Aufräumen | nein | ja (Kachel, Deploy-Aufräumen) |
| [#417](https://github.com/rexei123/heizung-sonnblick/pull/417) | Mindestpause nach langem Lauf | **ja** | **ja** |
| [#416](https://github.com/rexei123/heizung-sonnblick/pull/416) | Timer nachsetzen (`refresh`) | **ja** | **nein** — siehe unten |

**Ein Konflikt ist absehbar und harmlos:** #420 hängt §10bb und §10bd an
das Ende von `docs/RUNBOOK.md`, #416 hängt dort §10bc an. Wer zuletzt
kommt, braucht ein `develop`-Einmergen. `merge-paket` stellt die Basis
selbst um; bleibt es stehen, bitte melden — kein Rebase, kein
Force-Push.

**Warum diese Reihenfolge.** Die drei harmlosen zuerst: wenn im Fenster
etwas klemmt, ist der Steuerpfad noch nicht angefasst. #417 vor #416,
weil #417 der **Rückfall** ist — läuft `refresh` am Gerät nicht wie
gedacht, bleibt die halbierte Totzeit trotzdem.

**#416 ändert von sich aus nichts.** Er macht die Strategie `refresh`
nur *verfügbar*; die Vorgabe bleibt `expire_and_resend`. Das Umschalten
ist ein eigener Handgriff (§10bc) und gehört **nicht** in denselben
Schritt — erst messen, was #417 allein bringt.

**#416 und #417 fassen beide `relay_tasks.py` an**, an verschiedenen
Stellen. Nach dem Merge des ersten wird der zweite BEHIND;
`merge-paket` stellt die Basis selbst um. Sollte dabei ein Konflikt
auftreten: develop einmergen, kein Rebase, kein Force-Push.

---

## Prüfschritte je PR

### Nach allen Merges: läuft der Stack?

**SSH (Server)**

```bash
docker compose -f /opt/heizung-sonnblick/infra/deploy/docker-compose.prod.yml ps --format '{{.Service}}={{.Status}}'
```

*Erwartet:* elf Dienste `Up`, die mit Healthcheck `healthy`.

**SSH (Server)** — Messwerte, der eigentliche Nachweis:

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT count(*) AS messwerte, count(DISTINCT device_id) AS geraete, max(time) AT TIME ZONE 'Europe/Vienna' AS juengste FROM sensor_reading WHERE time > now() - interval '5 minutes';"
```

*Erwartet:* 40–55 Messwerte von ebenso vielen Geräten, jüngste unter zwei
Minuten alt.

### #420 und #421 — Doku

Kein Prüfschritt am Server. #420 enthält zwei Code-Änderungen, die sich
**nicht** sehen lassen: die Übergangslesung alter Audit-Namen ist weg
(nachweislich toter Code, am Server geprüft) und eine Test-Fixture räumt
ihr Gerät auf. Der Melder verhält sich unverändert.

### #419 — Eingangstest ohne Relais

Kein Prüfschritt am Server. Der Lauf findet im Montagefenster statt, und
dort zeigt `list-pool` seit diesem PR die Geräteart.

### #418 — Auswertungswerkzeug

**Der erste Lauf gegen die Produktion**, SSH (Server):

```bash
docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --stunden 24
```

*Erwartet:* zwei Abschnitte (Rezeption/Eingang, Bar/Barbereich), je Stunde
eine Zeile, Einschaltanteil 50–67 %, Soll 23 bzw. 22 (bzw. 23 an der Bar,
solange die Übersteuerung von 09:42 läuft).

**STOPP, wenn:** Fehlermeldung statt Tabelle. Das Werkzeug lief bisher nur
gegen die Test-Datenbank; die Abfragen dahinter sind an den
Produktionsdaten belegt, das Programm nicht. Ausgabe an mich.

### #412 — Platten-Warnung + Aufräumen

**Zehn Minuten nach dem Deploy**, SSH (Server):

```bash
grep Aufraeumen /var/log/heizung-deploy-pull.log | tail -8
```

*Erwartet:* Zeilen `Aufraeumen: Grenze …`, `… Tag(s) werden geloescht …`
oder `Aufraeumen: nichts aelter als 7 Tage …`, und `Aufraeumen fertig.
Frei: … GB -> … GB.` **Kein** `FEHLER`.

Dazu die Kachel „Plattenplatz" auf dem Dashboard: ein Prozentwert und
„… GB frei", grau (nicht rot), solange unter 85 %.

### #417 — Mindestpause (Steuerpfad)

**Nach zwei Stunden**, SSH (Server):

```bash
docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --stunden 2
```

*Erwartet:* Einschaltanteil in den Stunden mit Heizwunsch **über 67 %**,
Richtung 75. Das ist die Wirkung dieses PRs: die Totzeit nach einem
Timer-Ablauf sinkt von zwanzig auf etwa zehn Minuten.

**STOPP, wenn:** der Anteil unter 60 % fällt oder die Zahl der
Einschaltungen je Stunde über 2 steigt. Dann taktet das Panel, und das
wäre genau der Fall, gegen den die Pause gebaut ist.

### #416 — `refresh` verfügbar (Steuerpfad, wirkt erst nach dem Handgriff)

**Dass er nichts geändert hat**, SSH (Server):

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT id, label, watchdog_strategy, relais_ein_gesendet_at FROM device WHERE kind = 'relay' ORDER BY id;"
```

*Erwartet:* beide auf `expire_and_resend`, `relais_ein_gesendet_at` leer
oder gesetzt — beides in Ordnung.

Das Umschalten ist der **nächste** Schritt und braucht Ihre Entscheidung,
siehe „Offene Entscheidungen".

---

## Test der Übersteuerung an der Bar (für den Betreiber)

#414 ist seit 15.11. ~09:40 live, und **er hat sich schon bewährt**: Sie
haben um **09:42** den Barbereich auf 23 gestellt (Übersteuerung 655,
`frontend_bereich`, Zone 302), und der Regler rechnet seither mit 23.
Vorher hätte er mit 22 gerechnet — dem Wert des Raumtyps.

Wenn Sie es selbst nachvollziehen wollen, in vier Schritten:

**1.** Oberfläche → Zimmer **Bar** → Bereich/Zone **Barbereich** →
Wunschtemperatur **24** setzen (ein Wert, den weder Raumtyp noch die
laufende Übersteuerung hat, damit er eindeutig ist).

**2.** Eine Minute warten. Der Orchestrator läuft jede Minute.

**3.** SSH (Server):

```bash
docker logs deploy-celery_worker-1 --since 3m 2>&1 | grep -o "'zone_id': 302[^}]*" | tail -1
```

*Erwartet:* `'soll': '24'`. Steht dort 22 oder 23, wirkt die
Übersteuerung nicht — Ausgabe an mich.

**4.** Zum Vergleich die Anzeige: dieselbe Zone in der Oberfläche muss
ebenfalls **24** zeigen. Beide lesen seit #414 denselben Helfer; wenn sie
auseinanderlaufen, ist das ein Befund.

**Zurücknehmen:** Übersteuerung in der Oberfläche aufheben, dann gilt
wieder der Raumtyp (22).

---

## Termine Mi 18.11.

### 1. 48-h-Kontrolle #406

Schritte **6a bis 6d** aus §10av, die vier Befehle. Vorher-Werte liegen
auf dem Server (`/root/rollout-vorher-*`). Vergleichsliste um **026, 001,
024, 002** ergänzt — 056 ist von 93 % auf 4 % gefallen und nicht mehr das
auffällige Gerät.

Ausgangswerte: **93 Geräte auf `tx_power_index=7`**, hausweiter Verlust
**1,19 %** über 48 h.

### 2. C6 Server-Neustart nach §10aw

**Die Laufliste braucht drei Änderungen gegenüber der letzten Fassung:**

* **Relais sind in Betrieb.** 108 und 109 schalten echte Panels. Nach dem
  Neustart gilt: Stromrückkehr-Verhalten ist auf AUS geprüft (beide
  Rücklesungen), das Panel bleibt also aus, bis der Regler es einschaltet.
  Prüfschritt: nach dem Hochlauf eine Runde des Orchestrators abwarten und
  `relais-orchestrator` im Worker-Log ansehen (`zonen=2 relais=2`).
* **Das ADR-Plugin ist draußen** (#415). Die gerenderte `chirpstack.toml`
  darf keinen `adr_plugins`-Eintrag haben, sonst startet ChirpStack in
  Schleife — genau das war der Ausfall vom 15.11., 08:53–09:00. Prüfschritt
  **vor** dem Neustart:

  ```bash
  docker run --rm -v deploy_chirpstack_config_rendered:/vol:ro alpine:3.20 grep -c '^[[:space:]]*adr_plugins' /vol/chirpstack.toml
  ```

  *Erwartet:* **0**. Steht dort 1, **nicht neu starten** — melden.
* **Die Reserve steht auf 20 dB.** Nach dem Neustart ist zu prüfen, dass
  sie noch steht (§10av Schritt 2d) — sie kommt aus der Regionsdatei und
  sollte, aber „sollte" ist kein Befund.

### 3. ChirpStack-API-Secret rotieren

**Anlass:** mein Notfall-Befehl vom 15.11. endete auf einem
Zeilenbereich (`sed -n '36,46p'`), und weil das Löschen der Pfadzeile den
Bereich verschob, stand `secret = …` aufgelöst auf dem Bildschirm.

**Ablauf:**

1. Neues Geheimnis erzeugen (32 Byte, Base64 oder Hex).
2. `CHIRPSTACK_API_SECRET` in `/opt/heizung-sonnblick/infra/deploy/.env`
   ersetzen.
3. `docker compose -f … up -d chirpstack-init chirpstack` — der Sidecar
   rendert die TOML neu, ChirpStack startet mit dem neuen Wert.
4. Neu anmelden in der Oberfläche.

**Folgen:** Das Geheimnis signiert die API- und UI-Sitzungstoken von
ChirpStack. Nach dem Wechsel sind **laufende Anmeldungen in der
ChirpStack-Oberfläche ungültig** und **ausgestellte API-Token ebenfalls**.
**Unsere Anwendung ist nicht betroffen:** der Downlink-Weg läuft über MQTT,
nicht über die ChirpStack-API (§5.28), und `CHIRPSTACK_API_KEY` ist ein
eigenes Geheimnis — nur das Provisionierungs-Skript nutzt es, und das läuft
im Montagefenster.

**Regel daraus, für mich:** eine Konfigurationsdatei mit Geheimnissen wird
**gezielt** geprüft (`grep -n adr_plugins`, `grep -c`), nie mit einem
Zeilenfenster um die geänderte Stelle. Ein Fenster verschiebt sich, sobald
man etwas löscht — also genau dann, wenn man es benutzt.

---

## Offene Entscheidungen

### 1. Wann wird `refresh` eingeschaltet? — *Empfehlung: Dienstag*

#416 macht es nur verfügbar. Mein Vorschlag: **Montag nur #417 wirken
lassen und messen**, Dienstag im Fenster 108 auf `refresh` umschalten
(ein Befehl, §10bc), dann messen. So ist jede Änderung einer Zahl
zuzuordnen. Beides am selben Tag zu schalten wäre schneller und würde
die Wirkung nicht mehr trennen.

### 2. Erst 108 oder beide Relais? — *Empfehlung: erst 108*

Die Rezeption ist der Problemfall (erreicht die 23 nie). Die Bar erreicht
ihr Soll. Eines umzuschalten gibt einen Vergleich im selben Haus bei
gleichem Wetter — zwei gleichzeitig nicht.

### 3. Zweites Panel für die Rezeption? — *Empfehlung: noch nicht
entscheiden*

Bei 60–67 % Einschaltanteil liefert ein 1,5-kW-Panel effektiv 0,9 kW. Mit
`refresh` sind es 1,5 kW, also **zwei Drittel mehr**. Die Frage „reicht
ein Panel" ist erst nach zwei bis drei Tagen mit durchlaufendem Panel
beantwortbar. Werkzeug und Kriterium stehen (#418).

### 4. Zweiter Versuch mit dem ADR-Plugin? — *Empfehlung: nicht vor einem
Test in der richtigen Engine*

Die Reserve von 20 dB wirkt (056 ist von Stufe 5 auf 0 und von 93 % auf
4 % Verlust). Offen bleibt 108 auf DR3 mit 16 % Verlust. Ein zweiter
Versuch braucht erst den Befund, in welcher Form ChirpStack 4.17 `id()`
erwartet — und einen Test, der die Datei so lädt wie ChirpStack. Ohne den
wäre ein zweiter Ausfall nicht mehr Pech.

### 5. Reihenfolge der restlichen Punkte

Nicht gebaut sind: **Anzeige-PR**, **Relais-Verlauf**, **Relais-Signal**
(Punkte 5–7 des Auftrags). Das sind drei Oberflächen-PRs mit
e2e-Anteil — in der Zeit, die heute blieb, nicht in der Qualität
machbar, in der die übrigen PRs stehen. Mein Vorschlag für die
Reihenfolge: **Anzeige-PR zuerst** (er behebt sieben konkrete
Missverständnisse in der täglichen Sicht), dann Relais-Signal (klein,
additive Migration), dann Relais-Verlauf (der größte).
