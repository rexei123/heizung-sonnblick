# 27.11.2026 — Mail-Flut zusammenfassen: eine Episode, zwei Mails

**Stand:** PR offen, nichts gemergt. Keine Migration, kein Funkbefehl,
keine Server-Änderung.

## Der Anlass

Zone Barbereich, Nacht vom 26. auf den 27.11.2026, wie es im Postfach lag:

| Uhrzeit | Mail |
|---|---|
| 22:40 | Zonen-Melder: Zone stumm |
| 23:00 | Entwarnung |
| 01:10 | Zonen-Melder: Zone stumm |
| 03:40 | Gerät offline: 109 Panel |
| 03:50 | Gerät offline: 027 Bar |
| 06:30 | Entwarnung |

**Sechs Mails, zwei Vorfälle.** Drei davon sagen nichts Neues:

* Die Mails um **03:40 und 03:50** nennen genau die zwei Geräte, die in
  der Zonen-Mail von 01:10 schon mit ihrem letzten Kontakt stehen. Zwei
  Weckrufe für eine Information, die zwei Stunden vorher vollständig im
  Postfach lag.
* Die **Entwarnung um 23:00** wurde um 01:10 widerrufen. Wer sie liest,
  hält den Vorgang für abgeschlossen.

Dieselbe Nacht ergibt mit diesem PR **vier** Mails: zwei Alarme, zwei
Entwarnungen, und die beiden Geräte-Mails entfallen.

## Was gebaut ist

### a) Geräte einer alarmierten Zone wecken nicht noch einmal

Läuft für eine Zone eine Episode „Zone ohne Fühlerwert", kommen
Geräte-offline-Mails für Geräte **dieser** Zone nicht hinaus. Die
Zonen-Mail nennt Fühler und Relais samt letzter Meldung bereits — das war
schon so und ist jetzt der Grund, die zweite Nachricht zu lassen.

Drei Eigenschaften, jede mit eigenem Test:

* **Der Filter hängt an der Zone, nicht am Haus.** Wäre er hausweit,
  hätte eine stumme Zone alle Geräte-Mails abgeschaltet.
* **Er sitzt vor der Wiederholungsbremse.** Sonst wäre ein unterdrücktes
  Gerät zusätzlich sechs Stunden gesperrt und nach dem Ende der Episode
  stumm **und** ungemeldet.
* **Er ist nachlesbar.** Jede unterdrückte Mail erzeugt eine Zeile
  `GERAETEMAIL_UNTERDRUECKT_ZONE_STUMM` im `business_audit`, mit Gerät,
  Zimmer und letztem Kontakt. Eine unterdrückte Mail, die niemand
  nachlesen kann, ist genau der stille Melder, gegen den der Filter
  gebaut ist (§5.79).

**Ehrlich zur Grenze:** unterdrückt heißt für diesen Übergang
**endgültig**, nicht verschoben. Ein Gerät wechselt nur einmal nach
`silent`. Was danach weiter meldet, ist die Zonen-Episode mit ihrer
Erinnerung alle sechs Stunden — und der Logeintrag entsteht ohnehin für
jeden Übergang.

### b) Eine Episode, ein Alarm, eine Entwarnung

Der Zustand liegt im `business_audit` und übersteht einen Neustart; vier
Marken, zwei davon mit Mail:

| Marke | Bedeutung | Mail |
|---|---|---|
| `RELAIS_ZONE_STUMM` | Alarm oder Erinnerung nach 6 h | **ja** |
| `RELAIS_ZONE_RUECKKEHR` | meldet wieder, Entwarnung steht aus | nein |
| `RELAIS_ZONE_STUMM_ERNEUT` | schweigt wieder, bevor die Rückkehr stabil war | nein |
| `RELAIS_ZONE_STUMM_ENDE` | Entwarnung | **ja** |

**Die Entwarnung wird zurückgehalten**, bis die Rückkehr
`RELAIS_ZONE_RUECKKEHR_STABIL_MIN` (Vorgabe **30 min**) gehalten hat.
Schweigt die Zone in dieser Zeit erneut, läuft dieselbe Episode weiter:
keine zweite Alarm-Mail, keine Entwarnung, kein Hin und Her.

**Warum `..._STUMM_ERNEUT` ein eigenes Token hat:** würde der Rückfall als
`RELAIS_ZONE_STUMM` vermerkt, hinge die Wiederholungsbremse an ihm — und
ein Link, der alle fünf Stunden einmal flackert, wäre nie wieder fällig.
Nach der ersten Mail käme nichts mehr. Ein Test hält das fest.

**Die Wartezeit verzögert nur die Entwarnung, nie den Alarm.**

### c) Vier Wege bleiben unverzüglich

Totalausfall, Schutzauslösung, Gehäusetemperatur ab 50 °C und die volle
Platte gehen ohne Episode, ohne Sammeln und ohne Ruhezeiten-Filter hinaus.
**Ein Ruhezeiten-Filter ist nicht gebaut** und steht auch nicht im
Backlog: eine Steuerung, die um drei Uhr schweigt, weil es Nacht ist, ist
um sieben Uhr nicht mehr zu retten.

Ein Test prüft das an den **Importen**: genau zwei Module dürfen die
Zustandsmaschine kennen (`funk_tasks` schreibt, `health_tasks` liest).
Hängt jemand später einen der vier sofortigen Melder daran, wird die
Zeile rot und die Entscheidung muss bewusst fallen. Ein zweiter Test
prüft, dass die vier Dateien überhaupt noch existieren — sonst wäre der
erste eine Behauptung über Dateien, die es nicht mehr gibt (§5.77).

## Der echte Ablauf als Prüfsatz

`test_mail_episoden.py` spielt die Nacht im Fünf-Minuten-Takt des
Beat-Tasks gegen die reine Entscheidungsfunktion. Minute 0 ist 22:40; die
Zone schweigt in `[0, 20)` und `[150, 470)`.

| Minute | Uhrzeit | Schritt |
|---|---|---|
| 0 | 22:40 | **Alarm** |
| 20 | 23:00 | Rückkehr vermerkt (keine Mail) |
| 50 | 23:30 | **Entwarnung** — 30 Minuten später als vorher |
| 150 | 01:10 | **Alarm** |
| 470 | 06:30 | Rückkehr vermerkt |
| 500 | 07:00 | **Entwarnung** |

**Die Wartezeit greift in dieser Nacht nicht**, und das steht so im Test:
die Rückkehr um 23:00 hat zwei Stunden gehalten, die Entwarnung war
berechtigt — nur dreißig Minuten zu früh. Die Einsparung von sechs auf
vier Mails kommt allein aus (a).

**Was die Wartezeit verhindert**, zeigt die zweite Zeitreihe: fällt die
Zone um 23:20 wieder aus — zwanzig Minuten nach der Rückkehr —, ist es
**eine** Episode. Dann: Alarm 22:40, Erinnerung 04:40 (sechs Stunden
später, weil die Episode fast acht Stunden dauert), Entwarnung 07:00.
Drei Mails statt vier, und keine davon behauptet zwischendurch, es sei
vorbei.

**Eine Erwartung im Test war falsch, nicht der Code.** Beim ersten
Schreiben stand dort „zwei Mails"; die Erinnerung nach sechs Stunden war
nicht eingerechnet. Der Eintrag bleibt im Docstring stehen, weil die Zahl
sonst wie eine Herleitung aussieht.

**Zeiten sind Abstände, keine Daten** (§5.59). Der Anker kommt aus der
echten Uhr, verglichen wird nur mit Differenzen — die Datei hängt an
keinem Kalender.

## Mutationsproben: neun, alle rot

| Probe | was rot wird |
|---|---|
| Wartezeit unwirksam (`>=` immer wahr) | 5 Tests, darunter der DB-Ablauf |
| Rückfall gilt als neuer Vorfall (`alarm`) | 2 Tests |
| Rückfall trägt die Alarm-Marke | die Bremsen-Zusicherung |
| Unterdrückung entfernt | 4 Tests |
| Unterdrückung hausweit statt je Zone | der Zonen-Test |
| Filter hinter die Bremse verschoben | der Zeitfenster-Test |
| `offene_zonen` nennt auch geschlossene | der DB-Test |
| `zonen_episode` in `gehaeuse_tasks` importiert | der Import-Wachposten |
| Rückkehr wird nicht vermerkt | 5 Tests |

## Zwei Bestandstests angepasst (§5.47)

`test_rueckkehr_erzeugt_die_entwarnung` verlangte die Entwarnung im ersten
sauberen Lauf — und genau das war der Fall vom 26./27.11. Der Test heißt
jetzt `test_rueckkehr_wird_vermerkt_und_die_entwarnung_wartet` und prüft
die Wartezeit mit. `test_der_zustand_haengt_an_der_zone_und_nicht_am_haus`
liest den Zustand über die neue Naht statt über die entfallene Hilfsfunktion.

**Dass sie angepasst werden mussten, ist der Beleg, dass dieser PR nicht
verhaltensneutral ist** — er soll es auch nicht sein.

Beim Schreiben der neuen Tests ist ein eigener Fehler aufgefallen, der
hier steht, weil er sich wiederholen kann: die erste Fassung alterte nur
die `RUECKKEHR`-Zeile im Audit, um die Wartezeit zu überspringen. Damit
rutschte sie **vor** den Alarm, `lies_stand` sah wieder „stumm", und der
Test war rot aus dem falschen Grund. Der Zustand hängt an der
Reihenfolge; eine Verschiebung muss sie erhalten.

## Was offen bleibt

**Ob die ganze Nacht eine Episode sein sollte.** Mit 30 Minuten sind es
zwei (die Rückkehr um 23:00 hielt 130 Minuten). Wer die Nacht als **einen**
Vorfall sehen will, setzt `RELAIS_ZONE_RUECKKEHR_STABIL_MIN` über 130 —
dann gibt es für diese Nacht einen Alarm und eine Entwarnung. Das ist eine
Abwägung, keine Technik: eine lange Wartezeit verschweigt eine echte
Rückkehr entsprechend lange. **Vorgegeben waren 30 Minuten, gebaut sind
30.**

**Die anderen Melder bündeln nicht.** Belegungsliste, Funkqualität und
„Gerät nimmt den Sollwert nicht an" haben jeweils eigene Bremsen und sind
in diesem PR unangetastet. Sie waren in der Nacht vom 26./27.11. nicht
beteiligt.

**Querverweise:** RUNBOOK „Episoden: warum seit 27.11.2026 weniger Mails
kommen" (unter §10m), `services/zonen_episode`, §5.79 (ein Melder, dem
niemand glaubt), §5.76 (Wirkung statt Mechanik), §5.47 (angepasste
Bestandstests), §5.59 (Abstände statt Daten), §0 S3 (Auditierbarkeit).
