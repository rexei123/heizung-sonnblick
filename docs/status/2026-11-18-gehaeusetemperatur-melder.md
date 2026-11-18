---
datum: 2026-11-18
thema: Ein warmes Relais-Gehäuse meldet sich jetzt selbst
pr: offen
---

# Die Warnschwelle hatte keinen Empfänger

**Keine Migration, kein Funkbefehl, keine Server-Änderung.** Ein Melder,
ein Beat-Eintrag, kein neuer Einstellwert — die Schwelle gab es schon.

## Der Anlass

Am 18.11.2026 stand Relais **„109 Panel"** (`device.id` 110) unter Last
bei **45**, während **„108"** (`device.id` 109) bei nahezu gleicher Last
**37** meldete. Die Warnschwelle liegt bei **40**
(`relay_gehaeusetemperatur_alarm`, `config.py:397`).

**Gesehen hat das der Betreiber, nicht die Steuerung.** Und das ist der
Befund, nicht die Zahl.

## Zwei Melder, die es nicht gab

| Stufe | Was passiert | Wer erfährt es |
|---|---|---|
| Wert ≥ Warnschwelle | Die Karte färbt ein Kennzeichen (`gehaeusetemperatur_alarm`) | nur wer gerade hinsieht |
| Überhitzungsschutz löst aus (85 nach Hersteller-Vorgabe) | Gerät schaltet selbst ab, Steuerung sperrt das Relais | **ein Logeintrag** (`health_alerts.emit_relay_protection_alert`) |

Die Schwelle hatte bis heute **genau einen** Verbraucher: das Kennzeichen
auf der Relais-Karte. Kein Audit, keine Mail, kein Eintrag im
`event_log`. Und eine Ebene höher ist es dasselbe — auch die
**Schutzauslösung** verschickt nichts. Wer nicht hinsieht, erfährt vom
Überhitzen daran, dass eine Zone nicht mehr heizt.

Das ist §5.76 wörtlich: die Mechanik war gebaut, die **Mitteilung**
fehlte. Die Sperre nach einer Auslösung ist richtig und bleibt; sie
verhindert nur nichts, solange niemand davon weiß.

## Was gebaut ist

| Stelle | Inhalt |
|---|---|
| `services/gehaeuse_melder.py` | Urteil, Lesepfad und Texte. `heiss`, wenn die **drei** jüngsten gemeldeten Werte alle auf oder über der Schwelle liegen; `kuehl`, wenn alle drei darunter liegen |
| `tasks/gehaeuse_tasks.py` | Episode je Gerät im `business_audit` (`RELAIS_GEHAEUSE_WARM` / `..._ENDE`), Mail an `global_config.alert_email` |
| `celery_app.py` | Beat-Eintrag im **Meldetakt** des Relais, aus `relay_meldeintervall_s` gerechnet statt als 600 hingeschrieben |

## Die Entscheidungen, mit Begründung

**Drei Meldungen, nicht eine.** Ein einzelner Wert kann ein Ausschlag
unter Last sein — dieselbe Erfahrung wie bei der Batterie am 29.09.2026
(§5.73). Ein Relais meldet alle zehn Minuten, drei Meldungen sind also
mindestens zwanzig Minuten über der Schwelle. **Konstante, keine
Einstellung:** das ist eine Eigenschaft der Messung, nicht die Abwägung,
die die Schwelle selbst trägt.

**Lesefenster 75 Minuten** (`MIN_MELDUNGEN × Frischefenster`). Ohne diese
Grenze könnten drei heiße Werte aus drei Tagen die Entprellung füllen,
und das sind keine drei Meldungen in Folge.

**`kuehl` ist nicht das Gegenteil von `heiss`.** Dazwischen liegt
„gemischt, zu wenige Werte oder nichts Frisches", und dann bleibt eine
laufende Episode stehen. Ein Relais, das während eines Alarms verstummt,
wird **nicht** entwarnt — eine Entwarnung ohne Messwert wäre eine
Behauptung (§5.68). Ein eigener Entwarnungs-Wert wäre eine zweite Zahl
mit derselben Herleitung (§5.53).

**Ohne `darf_schalten`-Filter**, anders als beim Zonen-Melder. Ein warmes
Gehäuse ist ein warmes Gehäuse, auch wenn das Relais gesperrt ist — und
nach einer Schutzauslösung ist es **genau dann** warm. Gefiltert wird nur
der Lebenszyklus (§5.58).

**Einmal je Ereignis, ohne Wiederholung** — Vorgabe des Betreibers. Das
ist der Unterschied zu den drei älteren Meldern
(`totalausfall_wiederholung_h`, `relais_zone_wiederholung_h`,
`platte_wiederholung_h`). **Was es kostet:** dort ist die Wiederholung
gleichzeitig der zweite Versuch, wenn die erste Mail nicht hinausging.
Den gibt es hier nicht. Dass ein Versand scheiterte, steht trotzdem fest
(`mail_status` schreibt es in die `global_config`), und der
Audit-Eintrag ist ohnehin geschrieben. Die Wiederholung kostet eine
Einstellung und drei Zeilen, falls sie doch gewünscht ist.

**Die Einheit bleibt offen und wird nicht weggerechnet.**
`internal_temperature_raw` ist das Byte aus dem Keepalive, und seine
Einheit ist in der Hersteller-Doku **nicht belegt** (AE-78,
Pflicht-Prüfung in der Inbetriebnahme). Die Mail nennt die Zahl als Zahl
und die Annahme in einem Satz daneben.

## Mutationsproben

| Probe | Erwartet | Ergebnis |
|---|---|---|
| `MIN_MELDUNGEN = 1` | `test_ein_einzelner_ausschlag_meldet_nicht` rot | rot (8 Tests) |
| `kuehl` als `not heiss` | `test_waehrend_der_episode_verstummen_entwarnt_nicht` rot | rot (5 Tests) |
| Lesefenster um 30 Tage geweitet | `test_alte_meldungen_fuellen_die_entprellung_nicht` rot | rot |
| Episoden-Wache im Task entfernt | `test_episode_meldet_einmal_und_wiederholt_nicht` rot | rot |
| `retired_at`-Filter entfernt | `test_ausgemustertes_relais_kommt_nicht_vor` rot | rot |

Danach wiederhergestellt: 27 Tests der Datei grün, Gesamtlauf 2174 grün
gegen echtes Postgres (§5.50).

## Mitgenommen, auf Freigabe vom 18.11.2026

`docker-compose.yml:145` — im Healthcheck des `chirpstack`-Dienstes
`localhost` → `127.0.0.1`. **Nur die Entwicklungs-Datei.** Die
hosts-Datei im Container bildet `localhost` auf `127.0.0.1` **und** `::1`
ab, `wget` nimmt `::1` zuerst, und ChirpStack lauscht nur auf IPv4
(`0.0.0.0:8081`): gemessen **11517** Fehlversuche bei voll gesundem
Dienst. Im produktiven Stack hat der Dienst ohnehin keinen Healthcheck.

## Was offen bleibt

**Der Verlauf der Gehäusetemperatur ist nicht abfragbar.** Weder die
Relais-API noch der Verlauf-Endpunkt liefern
`internal_temperature_raw` über die Zeit — die Frage „steigt 110 über die
Tage" ist heute nur mit einer Abfrage auf `relay_reading` am Server zu
beantworten. Zwei Wege: die Spalte in den Tages-Verlauf aufnehmen
(`VerlaufTag`, dann steht sie in der Oberfläche) oder es beim
Einzelbefund belassen. Steht auf der Liste, nicht in diesem PR.

**Die RUNBOOK-Tabelle „Welche Alarme es gibt" war unvollständig**, bevor
dieser PR seine Zeile hinzufügte: der Zonen-Melder (13.11.) und der
Platten-Wächter (14.11.) fehlen dort. Dieser PR trägt den eigenen Alarm
ein und vermerkt die Lücke; sie zu schließen ist ein eigener Doku-PR.
