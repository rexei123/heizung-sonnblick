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

Die Schwelle hatte **genau einen** Verbraucher: das Kennzeichen
auf der Relais-Karte. Kein Audit, keine Mail, kein Eintrag im
`event_log`. Und eine Ebene höher war es dasselbe — auch die
**Schutzauslösung** verschickte nichts. Wer nicht hinsah, erfuhr vom
Überhitzen daran, dass eine Zone nicht mehr heizt.

Das ist §5.76 wörtlich: die Mechanik war gebaut, die **Mitteilung**
fehlte. Die Sperre nach einer Auslösung ist richtig und bleibt; sie
verhindert nur nichts, solange niemand davon weiß.

**Beide Stufen melden jetzt** (21.11., auf Auftrag des Betreibers). Die
Schutzauslösung hat einen eigenen Melder bekommen, weil sie ein eigener
Vorgang ist: oben wird es warm, hier hat das Gerät **abgeschaltet**.

**Warum die Mail nicht im Uplink-Pfad sitzt**, wo der Alarm entsteht:
`mailer.send_mail` ist synchron (SMTP) und liefe im Event-Loop des
Subscribers, der die Uplinks des ganzen Hauses annimmt — ein Mailserver,
der zehn Sekunden braucht, hielte so lange die Anlage auf. Und
`emit_relay_protection_alert` sagt in seinem eigenen Docstring, warum es
nur protokolliert: der Logeintrag darf nicht an einer Mail hängen. Also
wie bei jedem anderen Melder des Hauses — ein Beat-Task liest die
**Wirkung** (`device.protection_tripped_at`) und verschickt.

**„Einmal je Ereignis" heißt hier: je Zeitpunkt.** Verglichen wird
`protection_tripped_at` mit dem Zeitpunkt im jüngsten Audit-Eintrag des
Geräts. Eine Sperre, die eine Woche steht, ergibt **eine** Mail; ein
Gerät, das nach dem Entsperren erneut auslöst, bekommt seine zweite.
Hinge die Bremse an der Existenz eines Eintrags statt an seinem Inhalt,
bliebe der zweite Vorfall stumm — dafür gibt es eine Mutationsprobe.

**Keine Entwarnung bei der Sperre.** Sie hebt ein Administrator von Hand
auf; wer sie aufhebt, weiß es. Eine Mail darüber wäre eine Mitteilung
über die eigene Handlung.

**Und ein Filter weniger als beim Zonen-Melder:** gemeldet wird auch für
ein Relais **ohne** Inbetriebnahme. Beim Eingangstest ist eine Auslösung
der wichtigere Fall — ein Gerät, das auf dem Tisch abschaltet, soll
nicht an die Wand.

## Was gebaut ist

| Stelle | Inhalt |
|---|---|
| `services/gehaeuse_melder.py` | Urteil, Lesepfad und Texte. `heiss`, wenn die **drei** jüngsten gemeldeten Werte alle auf oder über der Mail-Schwelle liegen; `kuehl`, wenn alle drei unter der Entwarnungs-Schwelle liegen |
| `tasks/gehaeuse_tasks.py` | Episode je Gerät im `business_audit` (`RELAIS_GEHAEUSE_WARM` / `..._ENDE`), Mail an `global_config.alert_email` |
| `services/schutz_melder.py` | **Die Stufe darüber** (21.11.): Relais mit stehender Schutz-Sperre, Schutzart als Wort, Mailtext |
| `tasks/schutz_tasks.py` | Episode am **Zeitpunkt** der Auslösung (`RELAIS_SCHUTZ_GEMELDET`), alle fünf Minuten, einmal je Ereignis |
| `celery_app.py` | zwei Beat-Einträge: Gehäuse im **Meldetakt** des Relais (aus `relay_meldeintervall_s` gerechnet statt als 600 hingeschrieben), Schutz-Sperren alle fünf Minuten |

## Die Entscheidungen, mit Begründung

**Zwei Schwellen, und die erste Fassung hatte eine zu wenig** (Nachtrag
vom 21.11.2026, Entscheidung des Betreibers). Gemeldet wurde ab
`relay_gehaeusetemperatur_alarm` (40) — und **110 erreicht 44–45 bei
jedem normalen Heizvorgang**. Dieser Melder hätte also täglich
geschrieben, und ein Melder, der täglich schreibt, wird abgeschaltet
statt gelesen (§5.79). Die Zahl, die sich als Grenze las, war der
Normalbetrieb eines der beiden Geräte.

| Schwelle | Wert | Aufgabe |
|---|---|---|
| `relay_gehaeusetemperatur_alarm` | 40 | färbt **nur** das Kennzeichen auf der Karte. Zeigt, meldet nicht |
| `relay_gehaeusetemperatur_mail` | **50** | löst die Mail aus. Die einzige Zahl, die der Melder liest |
| abgeleitet: `mail − GEHAEUSE_TOTBAND_K` | **45** | darunter wird entwarnt |

Die Entwarnung ist **keine zweite Einstellung**, sondern der Abstand
(`config.GEHAEUSE_TOTBAND_K = 5`): zieht jemand die Mail-Schwelle hoch,
wandert sie mit. Eine fest eingetragene 45 wäre beim ersten
Nachjustieren falsch (§5.53). Ein Startup-Validator weist `mail < alarm`
ab (die Mail käme, bevor die Karte etwas zeigt) und `mail ≤ Totband`
(die Entwarnung läge bei null und würde nie erreicht — eine Episode, die
nicht enden kann, ist schlimmer als keine).

**Drei Meldungen, nicht eine.** Ein einzelner Wert kann ein Ausschlag
unter Last sein — dieselbe Erfahrung wie bei der Batterie am 29.09.2026
(§5.73). Ein Relais meldet alle zehn Minuten, drei Meldungen sind also
mindestens zwanzig Minuten über der Schwelle. **Konstante, keine
Einstellung:** das ist eine Eigenschaft der Messung, nicht die Abwägung,
die die Schwelle selbst trägt. Entprellung und Totband sind dabei
**zwei** Dinge: drei Meldungen bei 49 nach drei bei 50 sind ein Alltag,
kein Ereignisende — das trägt nur das Totband.

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

**Die Einheit wird nicht weggerechnet.** `internal_temperature_raw` ist
das Byte aus dem Keepalive. Die Mail nennt die Zahl als Zahl und den
Vorbehalt in einem Satz daneben — siehe den Abschnitt zur Quellenlage
unten.

## Die Hersteller-Angaben, nachgelesen am 18.11.2026

Quelle: `docs.mclimate.eu`, Gerätehandbuch **16ASPM**, Abschnitte
*Sensors*, *Placement Guidelines* und *Protections*.

| Angabe | Wert | Abschnitt |
|---|---|---|
| Interner Fühler | „Resolution: 1°C, Accuracy: ±1°C" | Sensors |
| Überhitzungsschutz, **ab FW 1.4** | Auslösung `0x55` = **85 °C**, Erholung `0x46` = **70 °C** | Protections |
| Überhitzungsschutz, **bis FW 1.3** | Auslösung `0x5F` = **95 °C**, Erholung 70 °C | Protections |
| Einstellbarer Bereich | 30…100 °C, Auflösung 1 °C | Protections |
| Einbau | „must be installed in a place that ensures good cooling. **Install vertically** for improved cooling!" | Placement Guidelines |
| Obergrenze der Umgebungstemperatur | **steht dort nicht** | — |

Beide Relais des Hauses melden **FW 1.5**, für sie gilt also 85/70.

**Zwei Korrekturen am Bestand** (`config.py`, Kommentar über der
Schwelle): Die Einheit war dort als „nicht dokumentiert" geführt — sie
ist besser gestützt als das, nur für dieses eine Keepalive-Feld nicht
ausgesprochen. Und die dort genannten **60 °C** zulässiger
Umgebungstemperatur habe ich in keiner Quelle wiedergefunden; die Doku
nennt überhaupt keine Obergrenze, die Anleitung 0–40 °C. Der Kommentar
sagt das jetzt, statt einen Widerspruch zwischen zwei Datenblättern zu
behaupten, von denen eines nicht auffindbar ist (§5.68).

## Mutationsproben

Vom 18.11., Gehäuse-Melder:

| Probe | Erwartet | Ergebnis |
|---|---|---|
| `MIN_MELDUNGEN = 1` | `test_ein_einzelner_ausschlag_meldet_nicht` rot | rot (8 Tests) |
| `kuehl` als `not heiss` | `test_waehrend_der_episode_verstummen_entwarnt_nicht` rot | rot (5 Tests) |
| Lesefenster um 30 Tage geweitet | `test_alte_meldungen_fuellen_die_entprellung_nicht` rot | rot |
| Episoden-Wache im Task entfernt | `test_episode_meldet_einmal_und_wiederholt_nicht` rot | rot |
| `retired_at`-Filter entfernt | `test_ausgemustertes_relais_kommt_nicht_vor` rot | rot |

Vom 21.11., zwei Schwellen und Schutz-Melder:

| Probe | Erwartet | Ergebnis |
|---|---|---|
| Task liest `..._alarm` statt `..._mail` | `test_der_task_liest_die_mail_schwelle_und_nicht_die_der_karte` rot | **zuerst NEIN** — siehe unten; nach dem neuen Test rot (2 Tests) |
| `GEHAEUSE_TOTBAND_K = 0` | `test_der_lastwert_von_110_meldet_nicht_und_entwarnt_nicht` rot | rot (5 Tests) |
| `kuehl` als `not heiss` | `test_waehrend_der_episode_verstummen_entwarnt_nicht` rot | rot (8 Tests) |
| Schutz-Bremse an der Existenz statt am Zeitpunkt | `test_eine_neue_ausloesung_meldet_erneut` rot | rot |
| Schutz-Melder ohne `retired_at`-Filter | `test_ein_ausgemustertes_relais_kommt_nicht_vor` rot | rot |
| unbekannte Schutzart stillschweigend als „Schutz" übersetzt | `test_eine_unbekannte_art_wird_genannt_und_nicht_verschluckt` rot | rot |

**Die erste Probe hat eine echte Lücke gefunden**, und das ist der
Grund, warum sie hier mit ihrem Fehlschlag steht: zieht man die
Mail-Schwelle im Task auf die der Karte zurück, blieb die **ganze reine
Testreihe grün**. Die Urteils-Tests geben `schwelle_mail` selbst mit —
sie können gar nicht merken, welche Einstellung der Task einsetzt. Rot
wurde nur ein Episoden-Test, und das aus einem Nebengrund (seine kühlen
Werte lagen dann über der verschobenen Entwarnungs-Schwelle). Ein Posten,
der das Eigentliche nicht bewacht (§5.55).

Geschlossen mit
`test_der_task_liest_die_mail_schwelle_und_nicht_die_der_karte`: der
Aufbau ist der **gemessene Lastwert von 110**, und er darf keine Episode
erzeugen. Mit der Schwelle der Karte wäre es ein Alarm — also genau die
tägliche Mail, die diese Änderung verhindern soll. Dazu drei
Validator-Tests in `test_config.py`.

Danach wiederhergestellt: 61 Tests der drei Dateien grün, Gesamtlauf
grün gegen echtes Postgres (§5.50).

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
dieser PR seine Zeilen hinzufügte: der Zonen-Melder (13.11.) und der
Platten-Wächter (14.11.) fehlen dort. Dieser PR trägt die eigenen Alarme
ein und vermerkt die Lücke; sie zu schließen ist ein eigener Doku-PR.

**Der nächste PR** (vom Betreiber am 21.11. so vorgegeben, nicht in
diesem): Max und Mittel der Gehäusetemperatur im Tages-Verlauf, der
Stundengrenzen-Fix für die 193 Wh bei 0 % Einschaltanteil
(`services/relais_verlauf._ANTEIL_SQL` schlägt den Zählersprung einer
Spanne der Stunde ihrer **früheren** Meldung zu, die Einschaltdauer
dagegen dem Zustand an deren Anfang) und die Doku-Lücke der Alarmtabelle.

**Was dieser PR nicht beantwortet:** ob 110 über die Tage **steigt**. Das
braucht die Abfrage auf `relay_reading` am Server — der Melder sieht nur
die letzten 75 Minuten.
