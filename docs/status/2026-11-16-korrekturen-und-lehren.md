---
datum: 2026-11-16
thema: Drei Korrekturen und eine Lehre vom 15./16.11.
pr: offen
---

# Drei Korrekturen und eine Lehre

**Reine Doku plus zwei Tests.** Keine Migration, keine Server-Änderung,
kein Code im Steuerpfad.

## 1. §10av Schritt 6a antwortet nur für die Hälfte der Geräte

Gemessen am 16.11.2026:

```
Geraete im ADR-Protokoll: 55
Geraete in unserer DB:    109
davon mit Messwert in 24h: 103
```

**Warum.** ADR schreibt `LinkADRReq acknowledged` nur, wenn es etwas
**ändert**. Ein Gerät, dessen Stufe seit Tagen passt, steht nicht im
Protokoll. Dazu beginnt das Protokoll bei der letzten Neuerstellung des
chirpstack-Behälters (15.11., 07:59 UTC), nicht beim Rollout.

**Warum das Mittwoch zählt.** Der Vorher-Wert „rund 90 Geräte auf Stufe
7" stammt aus einem viel länger laufenden Protokoll. „Ein Drittel ist auf
eine kleinere Stufe gegangen" und „die Hälfte der Geräte steht nicht im
Protokoll" sehen in der Ausgabe von 6a **gleich** aus. Der Kasten sagt
das, und er sagt auch, was stattdessen gilt: **Schritt 6b**, der
Paketverlust, liest unsere eigene Datenbank, deckt alle 103 meldenden
Geräte und hat für beide Zeiträume dieselbe Grundlage. Gehen 6a und 6b
auseinander, gilt 6b.

Der Hinweis stand bisher nur in §10be (aus #422) und dort nur in der
Form „eine Neuerstellung legt ein leeres Protokoll an" — also über einen
anderen Fall. Dass ein **intaktes** Protokoll schon unvollständig ist,
stand in keinem Abschnitt. Wer am Mittwoch 6a ausführt, liest §10av, nicht
§10be.

## 2. Ein toter Verweis aus meinem eigenen #420

§10bb nannte die Lehre „Konfiguration mit Geheimnissen gezielt prüfen"
als **§5.90**. Diese Nummer gibt es nicht; gemeint ist **§5.89**. Von
dort ist die falsche Nummer in die Übergabe einer zweiten Sitzung
gewandert und wäre ohne diese Korrektur weitergereist.

**Ein toter Verweis wird schlimmer, nicht besser.** Solange die Nummer
frei ist, merkt man beim Nachschlagen, dass etwas fehlt. Sobald
irgendwann eine Lehre 5.90 entsteht, zeigt der Verweis stillschweigend
auf eine **fremde** Lehre — und sieht dann richtig aus. Darum bleibt
5.90 frei: #424 bringt §5.91, dieser PR §5.92.

## 3. Der falsche Pfad im Merge-Plan

Der Prüfschritt für #412 nannte `/var/log/heizung-deploy-pull.log`. Die
Datei gibt es nicht; sie heißt `/var/log/heizung-deploy.log`
(`deploy-pull.sh` Zeile 52). Der Name kam vom **Dienst**
(`heizung-deploy-pull.service`). Am Server meldete der Befehl
`No such file or directory` — und das hätte wie ein Problem mit #412
ausgesehen.

## Die Lehre: §5.92 — ein Protokoll in UTC neben einer Uhr in Ortszeit

Am 16.11. habe ich dem Betreiber gemeldet, der Regler stehe seit einer
Stunde. Serverzeit 08:52 CET, letzte Worker-Zeile „07:52". Ich habe nach
Sperren, OOM-Kills und Warteschlangen gesucht, nichts gefunden, und das
Ganze als dringend eskaliert.

**Es war nichts.** Die Container protokollieren in UTC, die Shell
antwortet in CET. „07:52" war 08:52 Ortszeit, eine Minute vor meinem
Blick. Der Beweis lag daneben: jüngste `event_log`-Zeile 08:53:23, 1078
Zeilen in fünf Minuten.

**Zum zweiten Mal in zwei Tagen** — am 15.11. hatte dieselbe
Verwechslung eine Downlink-Verzögerung vermuten lassen, die es nicht gab.
Beim zweiten Mal war der Schaden größer, weil ich die Fehldiagnose nicht
nur gedacht, sondern gemeldet habe.

Die Regel ist mechanisch: ein Zeitstempel aus `docker logs` wird **nie**
mit einer Wallclock-Erwartung verglichen. Und „läuft der Dienst?" wird an
**Daten** gemessen, nicht an Protokollzeilen — eine fehlende Logzeile hat
viele harmlose Ursachen, eine fehlende `event_log`-Zeile hat keine.

## Was die Tests zusichern

`backend/tests/test_runbook_warnkaesten.py`, zwei Zusicherungen, fünf
Mutationsproben, alle rot. Zwei blieben im ersten Durchgang grün und
haben eine echte Schwäche gezeigt: ich hatte auf **nackte Zahlen** im
ganzen Abschnitt geprüft, und „55" steckt auch in „§5.55", „6b" kommt
anderswo in §10av vor. Jetzt sind die Zusicherungen an den **Kasten** und
an die **Beschriftung** der Zahl gebunden (`ADR-Protokoll:\s*55`).
Dieselbe Familie wie §5.88.

## Was nicht gebaut wurde, und warum — für die Liste

Naheliegend wäre ein allgemeiner Verweis-Prüfer: *jeder `§`-Verweis zeigt
auf einen Abschnitt, den es gibt.* Er hätte **beide** toten Verweise
dieses Wochenendes gefangen — §5.90 hier und §10bb am 15.11.

Gemessen am 16.11. scheitert er an den **überlappenden Nummernräumen**:

* `§5.0` und `§5.0a` sind **RUNBOOK**-Abschnitte, `§5.89` ist eine
  **CLAUDE.md**-Lehre. Der Verweis sagt nicht, in welches Dokument er
  zeigt.
* 49 weitere Nummern (`§0.3` 22×, `§0.1` 17×, `§6.1` 12×, `§2.4` 10× …)
  stehen in CLAUDE.md nicht als Überschrift, sondern als tiefere
  Gliederungsebene — 227 Verweise insgesamt.

Ein belastbarer Prüfer braucht ein Anker-Inventar beider Dateien und eine
Triage dieser 49 Nummern. Das ist ein eigener PR, keine Zeile hier. Im
RUNBOOK selbst ist die Lage dagegen sauber: nach dieser Korrektur bleibt
genau **ein** toter Abschnitts-Verweis, `§10bf`, und der zeigt
absichtlich auf den geparkten Entwurf #423.

**Querverweise:** §5.92 (neu), §5.89 (die richtig zitierte Lehre), §5.88
(Prüfung auf die Stelle, nicht auf die Datei), §5.65 (dieselbe
Zeitzonen-Verwechslung im Code), §5.68, §5.79, RUNBOOK §10av, §10bb,
§10be, `docs/status/2026-11-16-merge-plan.md`,
`docs/status/2026-11-16-uebergabe-sitzung-2.md`.
