---
datum: 2026-11-15
thema: Notreparatur dokumentiert, zwei Lessons, drei Hygiene-Punkte
pr: offen
---

# Ein Verweis auf einen Abschnitt, den es nicht gab

## Der Anlass

Der Statusbericht zum ADR-Plugin-Ausfall (#415) schreibt „Notreparatur
steht in §10bb". **§10bb gab es nicht.** Der Verweis entstand beim
Schreiben und ist mit #415 in den Hauptzweig gelangt — ein Zeiger auf
etwas, das nicht da ist, also genau die Klasse §5.77: er liest sich wie
ein Befund und hält jemanden davon ab, selbst nachzudenken.

Dieser PR schreibt den Abschnitt und zieht drei weitere Dinge nach.

## 1. §10bb — ChirpStack startet in Schleife

Die vier Befehle der Notreparatur vom 15.11., mit dem Volumennamen und
ohne Platzhalter: Eintrag in der gerenderten `chirpstack.toml` leeren
(Sicherungskopie daneben), nur `chirpstack` mit `--force-recreate
--no-deps` neu erstellen, Status prüfen, und **Messwerte** prüfen — `Up`
allein ist kein Beleg (§5.76).

Dazu die Begründung, warum `--no-deps` nicht optional ist (ohne es läuft
`chirpstack-init` mit und bringt den Eintrag sofort zurück), und der
Hinweis, dass die Reparatur **nicht von selbst hält**: der Timer startet
den Sidecar alle fünf Minuten neu, die Datei ist danach wieder falsch, und
der nächste Neustart fährt wieder in die Schleife.

## 2. §10bd — das Auswertungswerkzeug

Aufruf, PowerShell-Form, und vor allem die Lesetabelle: welcher
Einschaltanteil mit welchem Ist/Soll-Abstand welchen Schluss erlaubt. Dazu
drei Sätze darüber, was die Zahlen **nicht** sagen.

Der Abschnitt gehört hierher und nicht in #418, damit sich nicht drei PRs
am Ende derselben Datei streiten.

## 3. §10av — der Prüfbefehl, und warum sein Muster so aussieht

```bash
docker run --rm -v deploy_chirpstack_config_rendered:/vol:ro alpine:3.20 grep -c '^[[:space:]]*adr_plugins' /vol/chirpstack.toml
```

Erwartet **0**. Das `^[[:space:]]*` ist nicht Zierde: der Abschnitt in
`chirpstack.toml` **erklärt** den Verzicht und nennt dabei `adr_plugins`
mehrfach im Kommentar. Ein `grep -c adr_plugins` zählt die mit und meldet
eine Zahl größer null, obwohl die Konfiguration richtig ist.

## 4. Zwei neue Lessons

**§5.88 — eine Prüfung auf Nutzzeilen, nicht auf die Datei.** Dieselbe
Falle war im Test schon einmal da, nur in der anderen Richtung: der
Vorgänger von `test_die_datei_ist_nicht_verdrahtet` suchte den Dateinamen
im ganzen TOML und blieb grün, als eine Mutationsprobe die Zeile aus der
**Liste** entfernte — der Name stand noch im Kommentar darüber.

**§5.89 — eine Konfiguration mit Geheimnissen wird gezielt geprüft, nie
mit einem Zeilenfenster.** Der Notfall-Befehl endete auf `sed -n
'36,46p'`; durch das Löschen der Pfadzeile rutschte die Datei um eine
Zeile, und Zeile 46 lag auf `secret = …` — dem aufgelösten
`CHIRPSTACK_API_SECRET`.

Der Fehler ist nicht der Zahlendreher, sondern das Mittel: ein
Zeilenfenster ist eine Angabe über die Datei **vor** der Änderung und
verschiebt sich genau dann, wenn man es benutzt. Zwei Befehle statt einem
sind der Preis; beim nächsten Notfall ist das die billigere Hälfte.

Folge: `CHIRPSTACK_API_SECRET` rotieren, Liste Mi 18.11., Ablauf und
Folgen im Merge-Plan.

## 5. Hygiene: die Übergangslesung alter Audit-Namen ist weg

`AUDIT_ALTE_NAMEN` aus #411 las die Marken bis zum 14.11. mit, damit eine
beim Deploy offene Episode nicht als neu gezählt wird. Die Bedingung für
das Entfernen stand im Kommentar: „keine Episode aus der Zeit davor mehr
offen".

**Geprüft, nicht angenommen** — am Server, lesend:

```
 action                 | count | letzte
------------------------+-------+------------------------
 RELAIS_ZONE_STUMM      |     2 | 2026-11-15 05:06:12
 RELAIS_ZONE_STUMM_ENDE |     2 | 2026-11-15 05:16:12
```

Keine Zeile unter einem alten Namen. Die Übergangslesung war damit toter
Code — und toter Code in einem Melder ist nicht neutral: er sieht wie ein
Fall aus, den es gibt.

Die zwei Tests dazu fallen mit weg. Eine Probe bleibt: wird
`episode_laeuft` auf `False` gesetzt, gehen zwei Tests rot — die
Wiederholungssperre ist also weiter geprüft.

*(Nebenbei aus derselben Abfrage: der Melder hatte heute früh eine echte
Episode — 05:06 stumm, 05:16 Entwarnung. Zehn Minuten, selbst beendet.)*

## 6. Hygiene: das Leck in der Test-Datenbank hat eine Adresse

`test_funkempfang::test_lies_funkempfang_zaehlt_nur_das_fenster` fiel im
lokalen Gesamtlauf (6 Meldungen statt 4). Ursache war **nicht** der
Funkempfang, sondern `tests/test_api_rooms.py`, Fixture
`zimmer_mit_thermostat`: sie committet ein `Device` und räumt am Ende
`room` und `room_type` weg — das Gerät nicht. Da
`device.heating_zone_id` nullable ist, löscht die CASCADE vom Zimmer die
Zone und setzt das Gerät nur auf `NULL`. Jeder Lauf hinterließ ein
gesundes Thermostat ohne Label im Pool, und die Reste bekamen frische
Messwerte.

**In CI unsichtbar** (frische Datenbank je Lauf), lokal kippte es einen
**fremden** Test — und die Suche begann deshalb im Funkempfang, also an
der falschen Stelle. Das ist §5.39 in seiner teuren Form.

Die Fixture löscht das Gerät jetzt mit.

## Läufe

* `ruff check`, `ruff format --check`, `mypy` (161 Dateien) grün.
* Backend-Suite **2001 passed, 45 skipped, 1 xfailed** — ohne den
  Workaround, den ich vorher brauchte (von Hand aufräumen).
