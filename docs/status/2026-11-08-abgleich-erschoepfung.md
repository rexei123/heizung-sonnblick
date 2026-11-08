---
datum: 2026-11-08
sprint: 25
thema: T3 — die erschöpfte Abgleich-Lage bleibt stehen
pr: 398
---

# Sprint 25 T3 — eine erschöpfte Lage verschwindet nicht mehr von selbst

## Der Befund des Betreibers

Gerät 7, 01.11. bis 04.11.2026. Der Abgleich hatte nach drei erfolglosen
Nachsendungen aufgegeben. Dann verschob die Engine ihren Wunsch —
Nachtabsenkung, Belegungswechsel — und traf damit den Wert, den das Gerät
ohnehin hielt. Der Befund war weg, **ohne dass das Gerät je einen Befehl
angenommen hatte.**

Die Aufräum-Bedingung lautete:

```python
elif ist_wert is not None and ist_wert == zone_target_setpoint_c:
    erfolg_gemeldet(dev.dev_eui)
```

Das ist eine Aussage über den **Wunsch**, nicht über das Gerät.

## Was geändert ist

**1. Der Vergleich.** Bestätigt ist, was das Gerät vom **zuletzt
gesendeten** Wert meldet, nicht vom aktuellen Wunsch. `prev_sp` kommt aus
`_last_command_for_device` und filtert auf `sent_to_gateway_at IS NOT
NULL` — ein nie abgeschickter Befehl gilt nicht als bestätigt.

**2. Der Merker.** `device.abgleich_erschoepft_seit` (Migration 0039,
additiv). Der Redis-Zähler bleibt, was er ist: eine Drosselung mit vier
Stunden Frist. Als Zustandsspeicher war er untauglich — die Lage verfiel
von selbst, ohne dass sich am Gerät etwas geändert hatte.

**3. Die zweite Hälfte des Falls, die mir erst der eigene Test gezeigt
hat.** Siehe unten — sie ist der eigentliche Inhalt dieses PRs.

**4. Sichtbar.** Dashboard-Kachel „Befehle nicht angenommen" (gelb, mit
Verweis auf die gefilterte Geräteliste), Auswahl auf der Geräteseite,
und eine Mail **einmal je Episode**.

## Die zweite Hälfte — der Test, der meinen eigenen Entwurf widerlegt hat

Mein erster Test sollte belegen, dass der Merker einen Wunschwechsel
überlebt. Er fiel — aber nicht an der Stelle, die ich erwartet hatte:
es ging ein Downlink hinaus, den ich nicht vorhergesehen hatte.

Der Grund ist richtig. Verschiebt die Engine ihren Wunsch von 18 auf 20,
dann vergleicht die **Hysterese** gegen den zuletzt gesendeten Wert (18),
sieht ein Delta von 2 und sendet die 20. Das ist korrekt.

Die Folge daraus ist es nicht: im nächsten Tick ist der zuletzt gesendete
Wert **20** und das Gerät meldet **20** — weil es die ganze Zeit 20
hielt. Mein neuer Vergleich hätte das als Bestätigung gelesen. Der Befund
wäre einen Tick später doch verschwunden, und mein Test hätte es nicht
gemerkt, weil er nur den ersten Tick prüfte.

Deshalb gibt es `_hat_wirklich_uebernommen`: ein Befehl, der einem Gerät
den Wert schickt, den es ohnehin meldet, belegt nichts. Die Frage ist
nicht „stimmen die Werte überein", sondern „hat sich am Gerät etwas
**geändert**". Eine Query, und nur für Geräte mit gesetztem Merker — im
Normalfall wäre sie Last ohne Aussage.

**Im Zweifel zählt es als Übernahme.** Fehlt die Vorgeschichte, ist die
Frage nicht entscheidbar, und ein Befund, den niemand abstellen kann, ist
schlimmer als einer, der neunzig Minuten später wiederkommt (§5.79).

## Was ich *nicht* geändert habe

Der Steuerpfad bleibt unangetastet: kein Eingriff in die Befehle, keine
Änderung an Drosselung, Versuchszahl oder Hysterese. Die Vorgabe lautete
**sichtbar machen**, und genau das ist es.

Dass die Hysterese einen Wert sendet, den das Gerät schon hält, ist eine
vermeidbare Motorbewegung — aber sie gehört zu **T1 (Entprellen)** und
nicht hierher (§5.1).

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Vergleich zurück auf den Wunsch | **2 Tests rot** |
| `_hat_wirklich_uebernommen` immer `True` | **1 Test rot** |
| Merker wird nicht gesetzt | **2 Tests rot** |
| Lifecycle-Filter im Zähler weg | **1 Test rot** |
| Audit und Mail bei jedem Tick | **2 Tests rot** |

## Läufe

* Backend: **1878 passed, 45 skipped** (vorher 1871) — `TEST_DATABASE_URL`
  gesetzt, die DB-Tests sind **gelaufen**, nicht übersprungen.
* Frontend: `tsc`, `eslint` grün. e2e **373 passed** mit `--workers=1`,
  wie die CI läuft.
* Zwei Tests fallen lokal **nur** im parallelen Lauf („Kacheln
  einspaltig", und ein Warn-Banner-Test, den dieser PR nicht berührt):
  `boundingBox` null und ein CSS-Timeout auf einer belasteten Maschine.
  Mit einem Worker und bei dreifacher Wiederholung der betroffenen Datei
  grün.

## Eine Richtigstellung in eigener Sache

In den PR-Texten zu **#393** und **#394** habe ich geschrieben, die
DB-Tests seien übersprungen, „weil Docker Desktop lokal nicht läuft".
**Das war falsch, und zwar in der Begründung.** Der Container
`heizung-test-db` läuft seit dem 07.11. 09:34 UTC. Übersprungen wurden
die Tests, weil ich `TEST_DATABASE_URL` nicht gesetzt hatte — meine
eigene Umgebung, nicht Docker.

Folge: rund 980 Tests, die ich als „in CI abgedeckt" geführt habe, waren
lokal nie gelaufen. Sie sind heute grün, es ist also kein Schaden
entstanden — aber die Aussage war eine Behauptung über einen Zustand, den
ich nicht gelesen hatte (§5.68), und sie stand in zwei PR-Texten, die
später als Beleg gelesen werden. Als Kommentar an beiden PRs
richtiggestellt.

## Offen

* Die Zahl der **Versuche** steht weiter nur in Redis. Für die Kachel
  genügt das; wer sie in der Oberfläche sehen will, braucht eine zweite
  Spalte — und dafür ist der Nutzen heute nicht belegt (§0 S6).
* Eine eigene Pille am Gerät (wie Batterie und Ventil) ist nicht gebaut.
  Die Auswahl in der Liste reicht, um die Geräte zu finden.
