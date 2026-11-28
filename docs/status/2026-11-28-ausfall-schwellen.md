# 28.11.2026 — Ausfall-Meldungen warten 180 Minuten

**Stand:** PR offen, nichts gemergt. Baut auf
[#444](https://github.com/rexei123/heizung-sonnblick/pull/444) auf
(Mail-Episoden); die Rückkehr-Stabilität von 30 Minuten bleibt
unverändert.

## Die Entscheidung

Vorgabe des Betreibers vom 28.11.2026: **alle Ausfall-Meldungen erst
nach 180 Minuten.** Drei Meldungen sagen „etwas ist ausgefallen", und sie
warteten unterschiedlich lang.

| Meldung | Einstellung | vorher | jetzt |
|---|---|---|---|
| Zone ohne Fühlerwert („Relais-Zone stumm") | `relais_zone_stumm_min` | 30 min | **180 min** |
| Keine Messwerte (Totalausfall) | `totalausfall_min` | 15 min | **180 min** |
| Thermostat meldet sich nicht | `health_degraded_max_age_h` | 3 h | **3 h** |

**Die dritte Zeile war schon erfüllt**, und das ist der erste Befund
dieses PR: 3 Stunden sind 180 Minuten. An der Einstellung ist deshalb
nichts geändert — sie zu „korrigieren" hätte dieselbe Zahl neu
geschrieben und dabei die Health-Stufe `silent` verschoben, an der außer
der Mail auch die Engine-Filter und die Dashboard-Kachel „Geräte online"
hängen (§5.73, drei Achsen). Der Testsatz prüft sie trotzdem mit: ohne
das wäre die Gleichheit der drei Zahlen eine Behauptung in einem
Kommentar statt eine Zusicherung.

**Unverändert sofort**, wie beauftragt: Schutzauslösung, Gehäuse ab
50 °C, volle Platte. Sie melden ein **Ereignis** und keinen Ausfall über
Zeit. Kein Ruhezeiten-Filter.

## Wo die Schwellen liegen — und warum nicht in `global_config`

Der Auftrag nannte zwei Wege: liegen die Schwellen in `global_config`,
dort ändern und in *Einstellungen* sichtbar machen; sonst `config.py` +
`.env.example` mit Validator ab 30 Minuten. **Es ist der zweite Weg**,
und das ist nicht Bequemlichkeit, sondern Befund:

`global_config.alert_device_offline_minutes` (Vorgabe 120) sieht aus wie
die gesuchte Einstellung und ist **keine**. Das Feld ist am 07.11.2026
aus `GlobalConfigRead`, `GlobalConfigUpdate`, `types.ts` und der
Einstellungsseite entfernt worden, weil es keinen Konsumenten im Backend
hatte (STATUS B-17-1 und B-18-7). Die Spalte steht noch in der
Datenbank, rückfall-sicher, und an der Stelle im Formular steht ein
Kommentar, der sagt, was dort stand und warum es weg ist. Wer sie heute
verdrahtet, verdrahtet einen Schalter, dessen Wirkung zwei Bildschirme
weiter auftaucht.

Keine der drei Schwellen liegt also in `global_config`. Alle drei
stehen in den Settings, und das aus der Begründung, die bei den
Health-Grenzen schon ausformuliert ist: wer sie verschiebt, muss den
Melde-Takt der Geräte kennen (zehn Minuten je Gerät, über hundert
Geräte) und wissen, dass dieselbe Zahl eine Dashboard-Kachel färbt.

## Was gebaut ist

### a) Die zwei Werte

`config.py`: `totalausfall_min` 15 → **180**, `relais_zone_stumm_min`
30 → **180**. `.env.example` trägt beide, `RELAIS_ZONE_STUMM_MIN` stand
dort bisher überhaupt nicht.

### b) Der Boden: mindestens 30 Minuten

`AUSFALL_MELDUNG_MIN_MIN = 30` als Modul-Konstante, geprüft für beide
geänderten Felder im Startup-Validator. **Start-Fehler und keine
Warnung**, dieselbe Haltung wie bei den übrigen Grenzen: ein Haus, dessen
Melder nach einem Tippfehler in der `.env` stumm das Falsche tut, ist
schlechter bedient als eines, dessen API nicht startet. Die Meldung nennt
das Feld.

### c) Der Validator, der die Vorgabe zunächst abgewiesen hat

**Das ist der eine Punkt, an dem der Auftrag nicht ohne Weiteres
umsetzbar war.** `relais_zone_stumm_min` hatte eine Obergrenze: er musste
unter `health_healthy_max_age_h` in Minuten liegen, also unter **120**.
Die Vorgabe 180 wäre am Start gescheitert — mit einer Fehlermeldung, die
auf eine Grenze zeigt, die der Regler **nicht hat**.

Denn der Zwangs-AUS des Zweipunktreglers greift nicht nach 120 Minuten,
sondern nach `health_healthy_max_age_h` mal `VERALTUNGS_FAKTOR` (2,5),
also nach **300**. Die 120 waren eine bewusst strengere Marke, und ihre
Begründung stand im Docstring: den echten Wert zu rechnen hätte den
Faktor an einer zweiten Stelle wiederholt (§5.53), und die strengere
Grenze „lasse jede sinnvolle Einstellung zu". Der zweite Teil stimmt seit
dem 28.11.2026 nicht mehr.

Gebaut ist deshalb die Auflösung und nicht die Umgehung:
`VERALTUNGS_FAKTOR` ist aus `tasks/relay_tasks` nach `config` gezogen —
dieselbe Stelle, an der schon `GEHAEUSE_TOTBAND_K` aus demselben Grund
liegt (der Validator braucht ihn, und `config` darf den Verbraucher nicht
importieren, sonst entsteht ein Ring über `db`). `relay_tasks` liest ihn
von dort, der Name bleibt dort stehen, weil zwei Module und zwei
Doku-Stellen ihn unter dieser Adresse nennen. **Eine Quelle, und der
Validator prüft jetzt das echte Fenster.**

Der Vorlauf bleibt damit bestehen und wird kürzer: **120 Minuten** statt
270.

### d) Eine neue Kopplung, und sie ist sichtbar

Mit `relais_zone_stumm_min = 180` ist `HEALTH_HEALTHY_MAX_AGE_H = 1`
nicht mehr zulässig — der Regler schaltete dann nach 150 Minuten ab, die
Meldung käme danach. Wer das Keepalive-Fenster kürzt, muss die Wartezeit
mitnehmen. Zwei Bestandstests in `test_health_schwellen_20e.py` haben
genau das getan und sind rot geworden; sie setzen jetzt eine passende
Wartezeit mit, jeweils mit der Begründung im Kommentar. Ein eigener Test
hält die Kopplung fest, damit sie nicht als Mangel gelesen wird.

### e) Tests

`backend/tests/test_ausfall_schwellen.py`, **12 Zusicherungen**:

1. **Die drei Zahlen sind gleich** — der Wachposten für die Entscheidung.
   Ohne ihn wäre ein Rückfall auf 30 oder 15 nicht zu bemerken: die Suite
   bliebe grün, weil jeder Melder seine eigene Grenze korrekt einhält,
   nur eben eine andere als bestellt.
2. **Und sie wirken** — je eine Minute davor und danach, gegen die
   **Betriebsvorgabe** statt gegen einen Prüfstand-Wert. Das ist der
   Unterschied zu den Melder-Tests: dort bekommt `beurteile` eine Zahl
   übergeben. Ohne diese drei wäre eine Vorgabe denkbar, die kein Melder
   liest.
3. **Die Validatoren** — vier abgewiesene Werte, eine Gegenprobe, die
   Obergrenze samt der verbleibenden 120 Minuten Vorlauf als Zahl, und
   die Kopplung aus (d).
4. **Die Ereignis-Melder kennen keine Wartezeit** — ein Wächter über den
   Syntaxbaum von `schutz_tasks`, `gehaeuse_tasks` und `platten_tasks`:
   keines der drei Module darf einen der vier Namen lesen. Ein Verweis in
   einem Kommentar ist Prosa und bleibt erlaubt. Vorbild ist der
   Import-Wächter aus #444.

## Zwei Bestandstests, die grün geblieben sind und es nicht hätten sein sollen

**`test_funkempfang.py` hat die alte Anforderung weiter bestätigt.** Die
Datei trägt ihre Schwelle als eigene Konstante (`ALARM_AB = 15`), mit dem
ausdrücklichen Hinweis, sie sei „bewusst nicht importiert … zieht jemand
die Vorgabe hoch, soll er nicht stillschweigend mitwandern". Genau das
ist eingetreten: ein Test namens
`test_gegenprobe_07_11_loest_nach_15_minuten_aus` mit dem Docstring „**Die
Anforderung des Betreibers: Alarm nach 15 Minuten**" blieb grün, während
die Anforderung eine andere war. Ein Prüfstand-Wert schützt gegen stilles
Mitwandern — nicht gegen stilles Zurückbleiben.

Der Test heißt jetzt `test_der_alarm_loest_erst_nach_der_wartezeit_aus`
und prüft 179/180. Dazu ein neuer:
**`test_der_ausfall_vom_07_11_waere_heute_ohne_mail_geblieben`**.

**`test_relais_zone_melder.py`: `GRENZE_MIN` war beides.** Dieselbe Zahl
war Prüfstand-Wert *und* Betriebsvorgabe, und der Kommentar nannte sie
so. Seit dem 28.11. sind es zwei Dinge. Die Zahl bleibt bei 30 — die
Tests dort prüfen, wie sich der Melder **an** seiner Grenze verhält, und
das ist von der Zahl unabhängig. Der Kommentar sagt das jetzt, und die
Vorgabe prüft der neue Satz.

**Vier Task-Tests in derselben Datei sind rot geworden**, und sie waren
der nützlichste Fund: sie legen einen Fühler mit 45 Minuten Alter an und
rufen dann den **Beat-Task**, und der liest die Vorgabe statt
`GRENZE_MIN`. Mit 180 Minuten war der Aufbau zu frisch, der Melder
schwieg, und das Audit, das der Test sucht, entstand nicht. Statt einer
neuen festen Zahl steht dort jetzt `_stumm_alter()` —
`relais_zone_stumm_min + 15`, gerechnet statt eingetragen. Eine feste
Zahl wäre eines Tages wieder zu frisch, und dann wäre ein Melder-Test
grün, der seinen Melder nie erreicht (§5.55).

## Was das kostet, offen notiert

**Der Funk-Ausfall vom 07.11.2026 erzeugt heute keine Mail mehr.** Er
dauerte 31 Minuten und war der Anlass für diesen Alarm: die Health-Stufe
`silent` und der Funk-Wächter hatten beide geschwiegen, und genau diese
Lücke sollte er schließen. Mit 180 Minuten schweigt jetzt auch er.

Sichtbar bleibt der kurze Ausfall: die Kachel „Funk-Empfang" wird
unverändert nach `funkempfang_gelb_max_min` (15 min) rot. Sie ist nicht
mitgewandert, weil sie nichts weckt und nur gilt, solange jemand
hinsieht. Zwischen roter Kachel und Mail liegen seither dreieinviertel
Stunden.

**Die Dashboard-Kachel „Zonen ohne Fühlerwert" wandert mit.** Sie liest
dieselbe Einstellung (`api/v1/dashboard`), eine stumme Zone erscheint
dort also erst nach drei Stunden. Zwei Grenzen für Kachel und Mail wären
zwei Wahrheiten über dieselbe Frage (§5.53) — wer die Kachel früher
färben will, braucht dafür einen eigenen Grund und eine eigene Zahl.

**Der Vorlauf vor dem Zwangs-AUS der Zone sinkt von 270 auf 120
Minuten.** Er bleibt bestehen, und der Validator hält ihn fest.

Alle drei Punkte sind Folgen der Entscheidung, nicht Mängel der
Umsetzung. Sie stehen hier, im RUNBOOK und im Handbuch, damit niemand
später einen Fehler sucht, wo eine Entscheidung steht.

## Mutationsproben

Sechs, alle rot:

| Probe | was rot wird |
|---|---|
| Zonen-Wartezeit zurück auf 30 | 3 Tests |
| Totalausfall-Wartezeit zurück auf 15 | **die API startet nicht** |
| Geräte-Wartezeit zurück auf 24 h | 3 Tests, einer davon in `test_health_schwellen_20e.py` |
| Boden von 30 Minuten entfernt | 3 der 4 Validator-Fälle |
| Obergrenze vor dem Zwangs-AUS entfernt | 2 Tests |
| Platten-Melder liest eine Wartezeit | der Import-Wächter |

**Probe 2 ist die lehrreichste.** Der alte Wert lässt sich nicht mehr
eintragen: 15 liegt unter dem Boden von 30, der Startup-Validator weist
ihn ab, und die API bleibt mit `TOTALAUSFALL_MIN muss mindestens 30 sein
(ist: 15)` im Log stehen. Ein Rückfall auf den Stand von gestern ist
damit keine stille Konfigurationsänderung mehr, sondern ein Container,
der nicht hochkommt — in dieser Richtung die bessere Hälfte des
Tauschs.

**Probe 4 hat einen Fall offengelegt, der ohne sie unbemerkt geblieben
wäre:** `totalausfall_min = 1` bleibt auch ohne den neuen Boden
abgewiesen, weil der ältere Validator (`>= funkempfang_gelb_max_min`)
greift und seine Meldung ebenfalls das Feld nennt. Der Boden
unterscheidet sich also nur im Bereich zwischen 15 und 30, und der
Testfall mit 29 ist der, der ihn wirklich prüft. Beide Fälle bleiben
stehen — der eine prüft den Boden, der andere die Reihenfolge.

## Prüfung

- `ruff check`, `ruff format --check`, `mypy src`: sauber
- `pytest` (backend): **2420 grün**, 60 übersprungen, 1 xfailed (vorher 2408
  auf dem Stand von #444; +12 in `test_ausfall_schwellen.py`)
- `tsc --noEmit`: sauber — am Frontend ist nur Handbuch-Text geändert, kein Code
- Sechs Mutationsproben, alle rot

Migration additiv: **keine Migration**
Handbuch: **angepasst** — `seite-hotel.md` (die drei Stunden, die drei
sofortigen Meldungen, der Preis) und `seite-dashboard.md` (die Kachel
wird rot, die Mail kommt später; die Zeile „ab dieser Stufe geht auch
eine Mail hinaus" war falsch geworden)

**Querverweise:** §5.53 (eine Wahrheit — der Faktor und die
Kachel-Grenze), §5.55 (der grüne Test, der seinen Melder nicht
erreicht), §5.77 (der Prüfstand-Wert, der eine überholte Anforderung
bestätigt), §5.76 (die Wirkung überwachen — hier bewusst später),
§5.79 (ein Melder, dem niemand glaubt: der Grund für die Entscheidung),
RUNBOOK §10m („Die drei Wartezeiten sind seit dem 28.11.2026 gleich").
