# Sprint 23 — Gerätegrenzen, Fenstererkennung, Abstands-Wächter

**Brief, kein Code.** Erstellt 21.10.2026, Frist 26.10. Start frühestens
**Mi 28.10.**, nach Rotation Teil 2 (27.10.).

**Autonomie-Stufe 1** (volle Stop-Points, CLAUDE.md §0.1): zwei der drei
Tasks schreiben in **Hardware-Befehlspfade**. T1 verändert, was das Gerät
selbst zulässt; T2 schaltet einen Algorithmus im Gerät ein, der
eigenständig das Ventil schließt. Beides ist nicht durch einen Rückweg in
der Datenbank zu heilen.

**Gesamtaufwand:** 18–23 h über drei Tasks, plus 48 h Beobachtung in T1
und 72 h in T2, die nebenher laufen.

---

## Vor allem anderen: eine Korrektur

**Am 18.10. habe ich Ihnen gesagt, es gebe „kein Get für `0x08`", und
daraus eine Entwurfsentscheidung abgeleitet** (Neustart-Trigger plus
wöchentliches Nachsenden, weil man den Zustand nicht erfragen kann).

**Das war falsch.** Es gibt `0x15` — „Get temperature ranges", alle
Firmware-Versionen. Die Hersteller-Doku listet es; unsere **Repo-Kopie**
der Befehlstabelle (`docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md`,
abgerufen 09.05.2026) führt es nicht. Ich habe aus der Abwesenheit in
einer Zusammenfassung auf die Abwesenheit im Gerät geschlossen — §5.68,
und diesmal in der Richtung, die eine Entwurfsentscheidung verdorben
hätte.

**Folge für den Entwurf:** die Drift ist **messbar**, nicht nur
überschreibbar. Statt blind wöchentlich zu senden, fragt der Abgleich
nach und sendet nur bei Abweichung. Das ist weniger Funk, weniger
Motorbewegung und — der eigentliche Punkt — ein Melder statt einer
Hoffnung (§5.76: die Wirkung überwachen, nicht die Mechanik).

**Was daraus für die Repo-Kopie folgt:** sie ist eine **Zusammenfassung**
mit Abrufdatum, keine Quelle. Wer eine Befehlsnummer braucht, prüft sie
gegen die Hersteller-Doku. Ein Satz dazu gehört in die Kopfzeile der
Datei — eigener Mini-PR, nicht in diesem Sprint.

---

## T1 — Temperaturgrenzen am Gerät (`0x08`), B-22-1

### Belegtes Byte-Format

**Quelle:** <https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan/vicki-lorawan-device-communication-protocol/temperature-control/limit-target-temperature-range>
**Abgerufen:** 21.10.2026

**SET — `0x08`, drei Bytes:**

| Byte | Bedeutung | Kodierung |
|---|---|---|
| 0 | Befehlscode | `0x08` |
| 1 | untere Grenze | ganze °C, **ohne** Offset und Skalierung. Min./Vorgabe `0x05` = 5 °C |
| 2 | obere Grenze | ganze °C, **ohne** Offset und Skalierung. Max./Vorgabe `0x1E` = 30 °C |

**Beispiel der Doku:** `0x081018` → untere Grenze 16 °C, obere 24 °C.

**Keine Firmware-Anforderung genannt** — die Befehlstabelle führt `08`
unter „All". Für unsere Geräte (FW 4.4) also unkritisch; der
FW-Abgleich gehört trotzdem in den Vorab-Check, weil er für
`0x45` in T2 ohnehin gebraucht wird.

**GET — `0x15`, ein Byte.** Antwort: `0x15 <untere> <obere>`, je ganze °C.
Beispiel der Doku: `0x15051E` = 5 °C / 30 °C (die Werkseinstellung).

**Unsere Werte passen ohne Rechnen:** Zimmer 15/25 → `0x08 0F 19`,
Bad 18/25 → `0x08 12 19`. Beide Grenzen sind bei uns ganzzahlig
(`room_type.min/max_temp_celsius` wird über `_safe_int` gelesen,
`rules/engine.py`), es geht also keine Auflösung verloren.

### Der zweite Befund, und er macht die Sache deutlich einfacher

**Die Grenze gilt nur für das Drehrad.** Wörtlich aus derselben Seite:
der Grenzbereich greift, wenn der Benutzer die Zieltemperatur **mit der
Krone** verstellt; **Downlink-Befehle können ein Ziel darüber hinaus
setzen**.

Damit ist die Frage aus dem Auftrag beantwortet — *wie verhält sich das
Gerät bei einem Downlink-Sollwert außerhalb der Gerätegrenzen?* — und die
Antwort ist die bequemste der möglichen:

- Die Engine bleibt **unberührt**. Ein Sommermodus-Frostschutz von 10 °C
  ginge auch an einem Bad mit Untergrenze 18 durch, ein
  Fenster-Sicherheitswert ebenso.
- Es entsteht **kein** Ping-Pong zwischen Gerätegrenze und Layer 5. Das
  war das Hauptrisiko, das ich erwartet hatte; es fällt weg.
- Die Grenze wirkt genau dort, wo sie gewollt ist: am Rad des Gastes.

**Das ist eine Hersteller-Aussage, keine Messung.** Sie wird in T1.2 am
Gerät geprüft, und zwar ausdrücklich: ein Downlink mit 29 °C auf ein
Gerät mit Obergrenze 25 muss ankommen und gelten. Fällt das anders aus,
ist der Sprint an dieser Stelle zu stoppen — dann kollidiert die
Gerätegrenze mit Layer 5, und das ist eine andere Aufgabe.

### Aufbau

**T1.1 — Codec um `0x15` erweitern** (1–2 h). Der Codec routet über
`bytes[0]` (§5.21) und dekodiert heute `0x52`, `0x04`, `0x46`, `0x28`,
`0x01/0x81`. Eine `0x15`-Antwort landet derzeit als `unknown_reply`. Neu:
`temp_range_min` / `temp_range_max` im `object`-Block.

**Pflicht danach:** manueller Re-Paste in der ChirpStack-Oberfläche
(§5.22, §10c.1 — die URL dort ist seit 21.10. korrigiert). Ohne den
Re-Paste bleibt die Antwort undekodiert, und T1.4 hätte keine Datenbasis.

**T1.2 — Downlink-Wrapper** (2 h). `set_temperature_range(dev_eui, min_c,
max_c)` und `get_temperature_range(dev_eui)` in
`services/downlink_adapter.py`, nach der AE-48-Helper-Architektur
(`send_raw_downlink` plus typisierte Wrapper, wie
`set_open_window_detection`). Dazu der Drift-Test gegen den
Codec-`encodeDownlink` (§5.28) und die beiden Belege aus der Doku als
Erwartungswerte (`0x081018`, `0x15051E`) — ein Test, dessen Sollwert aus
der Spezifikation kommt und nicht aus unserem eigenen Lauf (§5.79).

**T1.3 — Quelle der Werte** (1 h). Je Zone: `kind == bathroom` → Grenzen
der Bad-Vorlage, sonst die des Zimmertyps. Dieselbe Rangfolge wie der
Bad-Sollwert (`engine_tasks._dispatch_downlinks_per_zone`), und
**derselbe Helfer** `rules.engine.clamp_grenzen` — nicht eine zweite
Rechnung daneben (§5.53).

**T1.4 — Wann gesendet wird** (2–3 h). Drei Auslöser:

| Auslöser | Warum |
|---|---|
| **Grenzen in der Oberfläche geändert** (`PATCH /room-types`) | die Frage aus dem Auftrag. Ohne diesen Auslöser wirkt eine Änderung erst beim nächsten Neustart des Geräts, also womöglich monatelang nicht |
| **Nach einem Geräte-Neustart** (`resync_pending`, §5.71) | ein Neustart setzt die Grenzen auf 5/30 zurück. Der Pfad existiert und ist über die Heartbeat-Reihenfolge gestaffelt |
| **Abgleich über `0x15`** | statt blind zu senden: fragen, vergleichen, nur bei Abweichung senden |

**Zur ersten Zeile, weil sie die eigentliche Arbeit ist.** Ein `PATCH`
auf einen Raumtyp betrifft **alle** Zonen dieses Typs — bei „Bad" sind
das alle Bäder im Haus. Das sind bis zu ~45 Downlinks aus einem einzigen
Klick. Sie dürfen **nicht** sofort alle raus (Duty-Cycle, §0 S4), sondern
gehen über denselben gestaffelten Pfad wie der Neustart-Resync: Flag
setzen, der nächste Tick je Gerät sendet. Rechnung: bei einem Uplink
alle ~10 min ist das Haus in rund einer Stunde durch.

**T1.5 — Anzeige auf der Geräteseite** (2 h). Unter den übrigen
Gerätewerten:

> **Grenzen am Gerät:** 15–25 °C (bestätigt heute, 09:14)

und ohne Antwort:

> **Grenzen am Gerät:** nicht bestätigt

**Quelle ist die `0x15`-Antwort, nicht das, was wir gesendet haben.** Das
ist der ganze Punkt: `control_command` sagt, was wir wollten,
`sensor_reading` sagt, was am Gerät steht. Eine Anzeige, die das
Gesendete zeigt, wäre eine Zusicherung ohne Deckung — und zwar genau
die, die wir vor Sprint 20f für den Sollwert hatten.

**Keine neue Spalte.** Die dekodierten Felder liegen in `sensor_reading`
(T1.1); gelesen wird die **jüngste Zeile, die sie führt**, und ihr
`time` ist der Bestätigungszeitpunkt. Dieselbe Form wie
`battery_voltage_median` (AE-72): read-time abgeleitet, nichts
persistiert, keine zweite Wahrheit.

**`nicht bestätigt` heißt nicht `falsch`.** Es heißt, dass noch keine
Antwort kam — bei einem Class-A-Gerät ganz normal, solange es nicht
gesendet hat. Der Text sagt das, damit niemand daraus einen Fehler liest.
Erst wenn der Abgleich **dreimal** erfolglos gefragt hat, ist es ein
Befund, und dafür gibt es den Zähler aus `engine_abgleich` schon.

**T1.6 — Rollout** (1 h Arbeit, 48 h Wartezeit). Erst **ein** Gerät: 306
Schlafzimmer. Nach 48 h prüfen:

1. `0x15` liefert 15/25 (Abgleich bestätigt, was gesendet wurde).
2. Das Drehrad lässt sich **nicht** über 25 drehen — am Gerät zu prüfen,
   nicht am Protokoll.
3. Ein Engine-Downlink über 25 (Testfall) kommt trotzdem an.
4. Keine zusätzlichen Downlinks im Protokoll: der Abgleich darf nicht
   jede Viertelstunde senden, wenn die Grenzen stimmen.

Erst danach alle Geräte, gestaffelt.

### T1.7 — zwei Anzeigefehler in der Übersteuerungs-Historie (2–3 h)

**Beleg des Betreibers:** Zimmer 306, 21./22.10., **12 Drehungen in 16
Stunden**. Beide Fehler sind in dieser Historie unmittelbar sichtbar.

#### (a) Gekappte Übersteuerungen zeigen den Gastwert

Die Historie zeigt „30 °C, aktiv“, wirksam sind 25 °C. Der
Gastwunsch steht in `manual_override.setpoint`, gekappt wird in Layer 5
— die Historie liest den ungekappten Wert und behauptet damit eine
Wirkung, die es nicht gibt.

**Soll:** „30 °C → begrenzt auf 25 °C“, und zwar an **allen drei**
Stellen: Historie, Zonen-Karte, Übersteuerungs-Karte.

**Woher die Grenze kommt, ist die eigentliche Frage.** Sie steht nicht am
Override, sondern am Raumtyp, und seit dem Hotfix vom 18.10. liegt sie als
`RuleResult.clamp_grenzen_c` im Engine-Ergebnis. Die Anzeige leitet sie
**read-time** ab (`clamp_grenzen(ctx)`) und persistiert **nichts** —
dieselbe Form wie `battery_voltage_median` (AE-72, §5.73). Ein zweites
Feld am Override wäre eine zweite Wahrheit, die beim ersten
Grenzen-Wechsel auseinanderläuft.

**Und deshalb gilt die Anzeige nur für den aktiven Fall.** Eine
Bestandszeile von vorgestern gegen die **heutigen** Grenzen zu rechnen
würde eine Vergangenheit behaupten, die so nicht war. Abgelaufene Zeilen
zeigen weiter den gespeicherten Wert.

#### (b) `revoked_reason` wird falsch gedeutet — und zwar zweimal

Die heutige Zuordnung in `manual-override-panel.tsx`:

```tsx
const grund = override.revoked_reason ?? "";
if (grund.startsWith("auto")) {
  return <span …>{grund.includes("checkout") ? "mit der Abreise beendet" : "abgelaufen"}</span>;
}
return <span …>manuell aufgehoben</span>;
```

**Alle Werte, die der Quellcode schreibt** — per `grep` erhoben, nicht aus
dem Gedächtnis:

| Wert | Geschrieben in | Bedeutung | Heutige Anzeige |
|---|---|---|---|
| `superseded` | `override_service.py:487` | von einer neueren Drehung derselben Zone verdrängt | **„manuell aufgehoben“ — falsch** |
| `auto_revoke_on_checkout` | `override_pms_hook.py:102` über `revoke_all_active_overrides` | Abreise | „mit der Abreise beendet“ — richtig |
| `room_override_blocked` | `api/v1/rooms.py:287` über `revoke_all_active_overrides` | Mitarbeiter hat das Zimmer gesperrt | **„manuell aufgehoben“ — falsch** |
| `auto: expired` | `override_service.py:718` (`cleanup_expired`) | Tages-Aufräumung abgelaufener Einträge | „abgelaufen“ — richtig |
| Freitext oder `NULL` | `override_service.py:646` über `api/v1/overrides.py:242` | Aufhebung über die Oberfläche, Grund optional (max. 500 Zeichen) | „manuell aufgehoben“ — richtig |

**Es sind zwei von fünf, nicht einer.** Der Auftrag nannte `superseded`;
`room_override_blocked` fällt in dieselbe Lücke, weil die Prüfung auf das
Wortanfang-Muster `auto` beide verfehlt. Dass die Erhebung einen zweiten
Fall gefunden hat, ist der Grund für die Vorgabe „per grep, nicht aus
der Erinnerung“ — aus dem Gedächtnis hätte ich einen Wert korrigiert
und den anderen stehen lassen.

**Soll:**

| Wert | Text |
|---|---|
| `superseded` | „ersetzt (neue Drehung)“ |
| `auto_revoke_on_checkout` | „mit der Abreise beendet“ |
| `room_override_blocked` | „durch Zimmersperre beendet“ |
| `auto: expired` | „abgelaufen“ |
| `NULL` oder leer | „manuell aufgehoben“ |
| **alles andere** | **der Rohwert**, unverändert |

**Warum der Rohwert und nicht „manuell aufgehoben“.** Vorgabe des
Betreibers, und sie ist richtig: ein unbekannter Wert ist entweder ein
neuer Code, den jemand im Backend eingeführt hat, oder ein Freitext aus
der Oberfläche. Im ersten Fall ist „manuell aufgehoben“ eine
**falsche Tatsachenbehauptung**, im zweiten ist der Rohwert genau das,
was der Mitarbeiter hingeschrieben hat. Beides ist mit dem Rohwert
richtig bedient, und ein Auffangwert, der schweigt, hätte diesen Fehler
gar nicht entstehen lassen.

**Keine Zuordnung über Textmuster mehr.** `startsWith("auto")` war der
Fehler, nicht eine seiner Zweige: `superseded` und
`room_override_blocked` sind beide automatische Vorgänge, deren Namen
nicht mit `auto` beginnen. Die neue Zuordnung ist eine **Tabelle mit
genauen Schlüsseln**.

**Spiegel-Test, Pflicht.** Wie bei den Override-Quellen (#330): ein Test
hält die Tabelle im Frontend gegen die Konstanten im Backend. Die vier
Codes stehen dort bereits als Konstanten oder Literale
(`REVOKE_REASON_SUPERSEDED`, `REVOKE_REASON_CHECKOUT`,
`"room_override_blocked"`, `"auto: expired"`); die beiden letzten gehören
im Zuge dieses Tasks ebenfalls zu Konstanten gemacht, sonst prüft der
Spiegel gegen eine Zeichenkette, die jemand beim Umbenennen übersieht.

**Ein Nebenbefund aus der Erhebung:** `test_override_service.py:382`
erwartet `auto: guest checked out` — eine Zeichenkette, die **kein**
Aufrufer im Quellcode schreibt (der Haken schreibt
`auto_revoke_on_checkout`). Der Test gibt sich den Grund selbst mit und
ist damit nicht falsch, aber er dokumentiert einen Wert, den es nicht
gibt. Im Zuge des Tasks mitziehen.

### Der Pflicht-Stop vor dem ersten Rollout, als Versuch

**Aufbau:** ein Gerät mit Grenzen **15/25** (also 306 Schlafzimmer nach
T1.6 Schritt 1). Dann ein Downlink mit **10 °C** — der Frostschutzfall,
und zugleich der Wert, der am weitesten **unter** der unteren Grenze liegt.

**Die Frage:** übernimmt das Gerät die 10?

| Ergebnis | Bedeutung | Konsequenz |
|---|---|---|
| Gerät meldet **10** | die Hersteller-Aussage stimmt, Downlinks überschreiten die Grenze | Rollout frei |
| Gerät meldet **15** | das Gerät kappt auch Downlinks | **Stop.** Der Task wird neu geschnitten |
| Gerät meldet **gar nichts** | Downlink verloren oder nicht bestätigt | wiederholen; bleibt es dabei, ist es ein Funkbefund und kein Grenzbefund |

**Warum der Frostschutzfall und nicht ein beliebiger Wert.** Wenn das
Gerät Downlinks kappt, ist die teuerste Richtung **nach unten**: ein
Sommermodus- oder Fenster-Frostschutz von 10 °C würde an einer
Untergrenze von 15 hängenbleiben, und ein Bad mit 18 würde im Winter bei
offenem Fenster auf 18 weiterheizen. Nach oben wäre eine Kappung
ärgerlich, nach unten ist sie ein Sicherheitsmangel.

**Geprueft wird am gemeldeten Sollwert, nicht am Protokoll.** Was wir
gesendet haben, steht in `control_command` — was das Gerät daraus
gemacht hat, steht in `sensor_reading.setpoint` des nächsten Uplinks.
Nur das zweite beantwortet die Frage (derselbe Unterschied, der Sprint
20f zugrunde liegt).

**Danach den Wert wieder zurückstellen** — 10 °C in einem belegten
Zimmer ist kein Zustand, den man über Nacht stehen lässt. Der Versuch
gehört in ein **freies** Zimmer, oder in die Minuten vor dem nächsten
Engine-Tick, der den regulären Wert ohnehin wiederherstellt.

### Risiken

| Risiko | Einschätzung |
|---|---|
| Die Hersteller-Aussage „Downlink darf überschreiten" stimmt nicht | **Pflicht-Stop.** T1.2 prüft es ausdrücklich. Dann kollidiert die Gerätegrenze mit Layer 5 und der Task wird neu geschnitten |
| Massen-Downlink aus einem UI-Klick | über den gestaffelten Pfad entschärft; der Test dafür ist ein `PATCH` auf „Bad" mit Zählung der Downlinks pro Minute |
| Codec-Re-Paste vergessen | `0x15` bleibt undekodiert, der Abgleich ist blind und sendet **nicht** (fail-closed). Kein Schaden, aber eine stille Wirkungslosigkeit — deshalb ein Test, der die dekodierten Felder in `sensor_reading` erwartet |
| Grenzen „verschwinden" nach einem Neustart unbemerkt | genau dagegen ist der `0x15`-Abgleich. Vorher war das der Grund für das wöchentliche Nachsenden |

**Aufwand T1: 11–14 h** plus 48 h Beobachtung. T1.5 (Anzeige am Gerät)
und T1.7 (Historie) kamen am 22.10. dazu.

---

## T2 — Vicki-Fenstererkennung (`0x45`, FW ≥ 4.2)

### Byte-Format (im Repo belegt)

`docs/vendor/mclimate-vicki/01-open-window-detection.md`, abgerufen
09.05.2026:

| Byte | Bedeutung |
|---|---|
| 0 | `0x45` |
| 1 | `1` = ein, `0` = aus |
| 2 | Dauer × 5 min (Vorgabe `2` = 10 min) |
| 3 | Delta × 10 (Minimum 0.2 °C) |

`get_open_window_detection` (`0x46`) ist **schon gebaut** und wird vom
Codec dekodiert — anders als bei T1 fehlt hier nichts.

**Werkszustand: ausgeschaltet.** Das ist der Befund aus §5.27, und er ist
der Grund, warum `openWindow` seit Sprint 9.11 immer `false` meldet.

### Was das Delta bedeutet — belegt und unbelegt

**Vorbedingung des Betreibers (22.10.):** bevor aus dem 306-Verlauf
geschlossen wird, die Erkennung „hätte nicht ausgelöst“, ist die
Semantik des Deltas zu belegen. Das ist geschehen, und das Ergebnis ist
**zur Hälfte negativ**.

Quelle: Hersteller-Seite „Open window detection“,
`https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan/vicki-lorawan-device-communication-protocol/open-window-detection`,
**abgerufen 22.10.2026**.

| Frage | Antwort |
|---|---|
| Interne Messrate der Erkennung | **belegt:** „The detection algorithm takes readings every 1 minute“ |
| Bezugsgröße des Vergleichs | **nicht belegt.** Die Seite sagt nur „a sudden drop in temperature“ und „if the temperature dropped more than the threshold value, the valve is closed“. Gegen **welchen** Vorwert verglichen wird, steht nicht da |
| Messrate im Verhältnis zur Senderate | **nicht belegt.** Die Seite nennt die Messrate, zum Sendeintervall sagt sie nichts |
| Byte-Format | belegt und deckungsgleich mit der Repo-Kopie: Byte 1 Bit 0 ein/aus (Vorgabe **aus**), Byte 2 Dauer in 5-Minuten-Schritten (Vorgabe 10 min), Byte 3 Delta × 10 (Vorgabe 1,0 °C, Minimum 0,2 °C) |

Im Abschnitt zu den 0,1-Grad-Befehlen steht „A new temperature value is
obtained every minute“ mit einem Vergleich gegen den Vorwert — das
**deutet** auf ein Ein-Minuten-Fenster, die Seite schreibt es aber nicht
hin.

**Warum diese Lücke die ganze Schlussfolgerung trägt.** Der 306-Verlauf
hat rund **0,22 K/min**:

| Annahme über das Fenster | Abfall im Fenster | Bei Delta 1,0 |
|---|---|---|
| **pro Minute** | 0,22 K | löst **nicht** aus |
| über 20 Minuten | 4,4 K | löst aus |

Die Aussage kippt also vollständig an einem Punkt, den die Doku offen
lässt. Deshalb steht in diesem Brief **nicht**, die Onboard-Erkennung
hätte das Fenster in 306 nicht erkannt. Sie ist **unbelegt**, und sie wird
nicht durch Lesen entschieden, sondern durch die Messung in T2.5.

### Parameter-Vorschlag

**Delta 1.0 °C, Dauer 10 min** — und das ist bewusst **nicht** der
empfindlichste Wert.

**Begründung, und sie dreht die naheliegende Erwartung um.** Der
Vicki-Sensor sitzt **am Heizkörper**. Was er misst, folgt dem Ventil
stärker als dem Raum. Jede Absenkung, die **wir** schicken — Nacht,
Check-out, Fenster-Sicherheit — schließt das Ventil, der Heizkörper kühlt
ab, und der Sensor sieht einen schnellen Abfall. Bei 0.5 °C je Minute
hätten wir gute Aussichten, unsere **eigene** Nachtabsenkung als offenes
Fenster erkannt zu bekommen.

Das ist §5.84 in anderer Gestalt: ein Melder, dessen Messgröße von etwas
anderem bewegt wird — hier nicht vom Wetter, sondern von unserer eigenen
Steuerhandlung. Deshalb der konservative Wert, und deshalb steht die
Nachtabsenkung ausdrücklich im Testplan.

**Dauer 10 min (Vorgabe), nicht länger.** Die Rollenteilung ist die aus
der Hersteller-Doku und aus AE-47: das Gerät ist der **schnelle lokale
Trigger**, die Engine ist die **Instanz**. Sie sieht das `openWindow`-Flag,
die Belegung, den Backplate-Zustand und die Nachbarzonen; das Gerät sieht
einen Temperaturabfall. Je kürzer das Gerät eigenmächtig zuhält, desto
früher entscheidet die Stelle mit dem vollständigen Bild.

**Was im Sprint zu messen ist, bevor der Wert festgeschrieben wird:** ob
1.0 °C bei einem **echten** offenen Fenster überhaupt auslöst. Der
Hersteller nennt die Erkennung selbst „not 100% reliable"; es ist
möglich, dass 1.0 °C am Heizkörper-Sensor zu grob ist. Dann ist die
Antwort **nicht** automatisch ein kleinerer Wert, sondern die Frage, ob
die Geräteerkennung überhaupt etwas beiträgt, das die Backend-Logik nicht
schon hat.

### T2.5 — Delta 0,2 als Messung, auf **einem** Gerät (Vorgabe 23.10.)

Weil die Bezugsgröße unbelegt ist, wird sie **gemessen** statt
angenommen: `0x45` mit **Delta 0,2** (dem Minimum) auf **genau einem**
Gerät — **306 Schlafzimmer**, weil für dieses Zimmer ein dokumentierter
Verlauf vorliegt.

**Was die Messung beantwortet.** Bei 0,2 K löst die Erkennung aus, sobald
im Bezugsfenster 0,2 K fehlen. Aus dem **Zeitpunkt** der Auslösung im
Verhältnis zum Verlauf lässt sich die Bezugsgröße rückwärts bestimmen:
schlägt sie bei einem Abfall von 0,22 K/min schon nach einer Minute an,
ist das Fenster eine Minute; braucht sie Minuten, ist es länger.

**Delta 0,2 ist ein Messwert, kein Betriebswert.** Es ist der
empfindlichste mögliche Wert und wird mit Fehlalarmen antworten — das ist
der Zweck. Er bleibt **nicht** stehen.

**Ein Gerät, nicht drei.** Die Begründung ist dieselbe wie beim
Pflicht-Stop in T1: ein Fehlalarm zieht über Layer 4 ein Zimmer auf den
Sicherheitswert, und das soll bei einer Messung höchstens **ein** Zimmer
treffen. Die drei Geräte aus dem Testplan bekommen den **vorsichtigen**
Wert; 306 Schlafzimmer bekommt zusätzlich die Messung, zeitlich davor.

**Das Abbruchkriterium gilt vollständig und ohne Ausnahme für die
Messung.** Löst die Erkennung bei Delta 0,2 durch unsere eigene
Absenkung aus — und bei diesem Wert ist das zu **erwarten** —, dann wird
sie auf **allen** Testgeräten abgeschaltet, und die Testwoche ist
beendet. Das ist nicht widersprüchlich, sondern der Preis: wer messen
will, wo die Schwelle liegt, riskiert, die Woche damit zu beenden.
Deshalb steht die Messung **am Anfang** des Testfensters und nicht in der
Mitte.

**Die Absenkung beginnt um 20:00** (siehe Rahmen unten) — die Messung
gehört also in den Vormittag, mit mindestens einem vollen Tag Abstand zur
nächsten Absenkung, sonst ist nicht zu unterscheiden, was ausgelöst hat.

### Wechselwirkung mit der Engine

| Stelle | Verhalten |
|---|---|
| `sensor_reading.open_window` | wird vom Codec gefüllt und von `rules/window_state.detect_open_window_zones` gelesen |
| **Layer 4** (`layer_window_safety`) | belegungsabhängig: frei → Frostschutz, belegt → Frei-Sollwert (AE-52). Verwirft dabei `zone_overrides` komplett — Sicherheit schlägt jede Komfort-Wahl |
| **Layer 3** | ein Gast-Override wird bei offenem Fenster abgewiesen (`override_service.create`, Window-Gate) |
| **Bad-Vorlage** | eine zimmerweite Entscheidung; bei Fenster-Trigger gilt der Sicherheitswert auch im Bad (§10ae) |

**Die Wechselwirkung, die gemessen werden muss:** während das Gerät
eigenmächtig zuhält (10 min), schickt die Engine womöglich einen
Sollwert. Was gewinnt? Die Doku sagt dazu nichts. **Das ist der Kern des
Tests**, nicht ein Nebenaspekt — wenn das Gerät unsere Downlinks in
diesem Fenster verwirft, entsteht genau die Lage, gegen die der
Engine-Abgleich (20f T3) gebaut ist, und er würde alle 15 min nachsenden.

### Abbruchkriterium (Vorgabe des Betreibers, 22.10.)

**Löst die Onboard-Erkennung in der Testwoche auch nur ein einziges Mal
durch eine eigene Absenkung aus — Nacht, Check-out, Fenster-Sicherheit —
wird sie auf allen Testgeräten abgeschaltet** (`0x45` mit
`enabled = 0`), der Befund dokumentiert, und **in derselben Woche nicht
nachjustiert.**

**Warum kein Nachjustieren.** Die naheliegende Reaktion wäre, das Delta
hochzudrehen, bis es ruhig ist. Das ist derselbe Zug, den §5.82 als
Fehler benennt: den Melder leiser stellen, statt die Ursache zu
verstehen. Und die Ursache wäre hier bekannt und unveränderlich — der
Sensor sitzt am Heizkörper, und unsere Absenkung kühlt ihn. Ein
größeres Delta verschiebt nur, wie stark die Absenkung sein muss.

**Ein einziges Auftreten genügt**, und das ist strenger als es klingt:
ein Fehlalarm bedeutet, dass Layer 4 ein Zimmer auf den Sicherheitswert
zieht, während niemand ein Fenster geöffnet hat — bei einem belegten
Zimmer in der Nacht. Eine Erkennung, die das kann, ist schlechter als
keine; die Backend-Logik liefert heute schon einen brauchbaren Befund
ohne diesen Nebenwirkung.

**Dokumentiert wird**, bei welcher Gelegenheit es auslöste (Uhrzeit,
Zone, `event_log`-Zeile, Temperaturverlauf der zehn Minuten davor) —
nicht nur die Tatsache. Ohne den Verlauf ist beim nächsten Versuch
wieder alles offen.

**Der Rückweg ist derselbe Befehl**: `0x45 00 …` schaltet aus, `0x46`
bestätigt es. Kein Neustart, keine Datenbankänderung — das ist der Grund,
warum dieser Task überhaupt mit einem so scharfen Kriterium arbeiten
kann.

**Rahmen (Betreiberentscheidung 22.10.): die Nachtabsenkung bleibt
20:00–06:00.** Sie wird für diesen Sprint **nicht** verschoben, auch nicht
versuchsweise — eine verschobene Absenkung hätte den Testfall gegen den
306-Verlauf unvergleichbar gemacht.

**Für das Abbruchkriterium gilt die Absenkung ab 20:00.** Das ist keine
Formalie: löst die Erkennung um 20:05 aus, ist das ein Treffer des
Kriteriums und kein Zufall, und die Testwoche endet. Wer die Absenkung
erst ab 22:00 rechnet, hätte zwei Stunden, in denen ein Fehlalarm als
„unklar“ durchgeht — und genau so werden Kriterien weich.

### Testfall mit Realdaten: Zimmer 306 (Vorgabe 22.10.)

**Beobachtung des Betreibers.** Am 22.10. gegen 06:00 wurde in 306
gelüftet, bei geöffnetem Fenster:

| Zone | Von | Nach | Dauer | Gradient |
|---|---|---|---|---|
| Schlafzimmer | 25 °C | 18,5 °C | ~30 min | ~0,217 K/min |
| Bad | 25 °C | 20 °C | ~30 min | ~0,167 K/min |

Dazu am 21.10. gegen 16:30 ein **kurzes** Lüften mit rund **−2 K**.

**Was dieser Verlauf wert ist.** Er ist der einzige belegte Fall eines
**echten** offenen Fensters an unserer Hardware, mit zwei Zonen
gleichzeitig und mit einem zweiten, schwächeren Ereignis als
Gegenprobe. Jede Schwelle, die wir wählen — am Gerät oder im Backend —
muss gegen diesen Verlauf gehalten werden, und zwar in **beide**
Richtungen: sie muss beim Lüften anschlagen und bei der Nachtabsenkung
schweigen.

**Der Verlauf ist noch nicht exportiert, und ich kann ihn nicht
exportieren** — diese Sitzung hat keinen SSH-Zugang. Die Zahlen oben sind
**Angaben des Betreibers**, keine aus der Datenbank gelesenen Werte, und
sie sind hier als solche gekennzeichnet (§5.68). Fertige Abfrage für den
Export:

```sql
-- SSH (heizung-test, root)
SET TIME ZONE 'Europe/Vienna';
SELECT sr.time, hz.name AS zone, d.dev_eui,
       sr.temperature, sr.setpoint, sr.valve_position, sr.open_window
  FROM sensor_reading sr
  JOIN device d       ON d.id = sr.device_id
  JOIN heating_zone hz ON hz.id = d.heating_zone_id
  JOIN room r          ON r.id = hz.room_id
 WHERE r.number = '306'
   AND sr.time >= '2026-10-21 16:00'
   AND sr.time <  '2026-10-22 08:00'
 ORDER BY hz.name, sr.time;
```

Dazu der Engine-Blick auf dieselbe Spanne, damit unsere **eigenen**
Sollwert-Änderungen im Verlauf sichtbar sind — ohne sie ist ein Abfall
nicht zuzuordnen:

```sql
SET TIME ZONE 'Europe/Vienna';
SELECT cc.created_at, d.dev_eui, cc.setpoint_celsius, cc.reason, cc.detail
  FROM control_command cc
  JOIN device d ON d.id = cc.device_id
  JOIN heating_zone hz ON hz.id = d.heating_zone_id
  JOIN room r ON r.id = hz.room_id
 WHERE r.number = '306'
   AND cc.created_at >= '2026-10-21 16:00'
   AND cc.created_at <  '2026-10-22 08:00'
 ORDER BY cc.created_at;
```

**Wie er Testfall wird.** Die exportierten Zeilen gehen als Fixture in
den Sprint (CSV oder ein Python-Literal, keine Live-Abfrage im Test) und
tragen **drei** Abschnitte: das Lüften am 22.10., das kurze Lüften am
21.10. und — das ist der wichtigste — eine **Nachtabsenkung ohne
Lüften**. Der dritte fehlt in der Beobachtung und ist mit zu exportieren;
ohne ihn prüft der Testfall nur die eine Richtung.

### Plan B — nur dokumentiert, nicht gebaut

**Ausdrücklich keine Entscheidung.** Der Betreiber hat am 22.10.
festgehalten: Plan B bleibt Plan B, und ob er kommt, wird **nach** dem
T2-Test entschieden, nicht vorher. Dieser Abschnitt hält den Entwurf
fest, damit er im Entscheidungsmoment nicht erst erdacht werden muss.

**Der Entwurf:** serverseitige Fenstererkennung aus dem
Temperaturgradienten.

| Teil | Wert |
|---|---|
| Auslöser | Abfall **≥ 3 K in 20 min** in einer Zone |
| Sperre | **nicht** innerhalb von 30 min nach einer eigenen Sollwert-Senkung in derselben Zone |
| Reaktion | Ventil 20 min zu |

**Was er besser kann als die Geräteerkennung:** er kennt unsere eigenen
Sollwert-Änderungen. Genau das ist die Schwäche, die T2 beim Gerät
vermutet — der Vicki-Sensor sitzt am Heizkörper und sieht unsere
Absenkung als Abfall, und er kann nicht wissen, dass wir sie verursacht
haben. Die 30-Minuten-Sperre ist deshalb nicht ein Detail, sondern der
ganze Grund für Plan B.

**Was er nicht kann:** schnell sein. 20 Minuten Fenster heißt, dass die
Erkennung im besten Fall nach 20 Minuten greift, während das Gerät nach
einer Minute messen kann. Plan B ist die **gründlichere**, nicht die
schnellere Lösung — und bei einem offenen Fenster im Winter sind 20
Minuten Heizen aus dem Fenster heraus.

**Gegen den 306-Verlauf gerechnet, soweit die Angaben reichen:**

| Fall | Abfall in 20 min | ≥ 3 K? |
|---|---|---|
| Lüften 22.10., Schlafzimmer (0,217 K/min) | ~4,3 K | **ja** |
| Lüften 22.10., Bad (0,167 K/min) | ~3,3 K | **ja**, aber knapp |
| Kurzes Lüften 21.10. (−2 K insgesamt) | < 3 K | **nein** |

Das Bad liegt mit 3,3 K rund 10 % über der Schwelle. **Eine Schwelle, die
einen bekannten Fall so knapp trifft, ist keine Schwelle, sondern ein
Zufall** (§5.84). Vor einem Bau wäre sie an mehr als einem Verlauf zu
prüfen — und der dritte Abschnitt des Testfalls (Nachtabsenkung ohne
Lüften) entscheidet, ob 3 K überhaupt über der Absenkung liegt. **Das ist
heute nicht bekannt**, und ohne diese Zahl ist Plan B nicht
entscheidungsreif.

Dass das kurze Lüften **nicht** anschlägt, ist übrigens kein Mangel: zwei
Kelvin bei geschlossenem Fenster nach fünf Minuten sind kein Fall, bei
dem ein Ventil zufahren muss.

**Regressionstest, falls gebaut:** derselbe 306-Verlauf als Fixture, drei
Zusicherungen — greift beim Lüften am 22.10., greift **nicht** bei der
Nachtabsenkung, greift **nicht** beim kurzen Lüften am 21.10. Die mittlere
ist die, die den Entwurf trägt.

### Testplan

Drei Geräte: **105, 110, 306 Schlafzimmer**. Je Gerät:

1. `0x45` setzen, mit `0x46` zurücklesen (Bestätigung, dass es ankam).
2. **Echtes Fenster öffnen**, 15 min, niemand fasst das Gerät an
   (B-9.11y-1 nennt genau diese Bedingung — der Kältepack-Test vom
   11.05. hat sich selbst gestört).
3. Prüfen: `open_window=true` in `sensor_reading`, Layer-4-Trigger im
   `event_log`, und **was in diesen 10 min mit unseren Downlinks
   passiert**.
4. **Nachtabsenkung abwarten** (ohne Fenster) und prüfen, dass
   `open_window` **false** bleibt. Das ist der Fehlalarm-Test, und er ist
   der wichtigere der beiden.

**Aufwand T2: 5–7 h** plus 72 h Beobachtung (zwei Nächte, damit die
Absenkung zweimal gemessen ist). T2.5 Delta-Messung und der
Realdaten-Testfall kamen am 22./23.10. dazu; Plan B ist reine
Dokumentation und kostet in diesem Sprint nichts.

### Risiken

| Risiko | Einschätzung |
|---|---|
| Fehlalarm durch unsere eigene Absenkung | das Hauptrisiko. Konservatives Delta plus Nacht-Test. Tritt es auf: Erkennung wieder ausschalten (`0x45 00 …`), nicht „Delta hochdrehen bis es ruhig ist" (§5.82) |
| Gerät verwirft Downlinks während der Schließzeit | zu messen. Falls ja, braucht der Engine-Abgleich eine Ausnahme für diese 10 min, sonst Doppel-Downlinks |
| FW < 4.2 bei einzelnen Geräten | `0x45` greift dort nicht; `0x06` wäre der andere Befehl. Betroffene Zonen stehen in RUNBOOK §10h (B-17-5). Im Sprint **nicht** nachziehen — erst die drei Testgeräte |

---

## T3 — Abstands-Wächter Belegungsliste (Punkt 4)

**Die Lücke:** der Wächter fragt „kam heute **eine** Liste?". Fallen die
Listen um 15:30 und 19:30 aus, bleibt die Ampel grün (§10ai). Das
Zwei-Stunden-Versprechen wäre gebrochen, ohne dass es jemand sieht.

**Aufbau** (2 h):

- Einstellung `IMPORT_MAX_GAP_HOURS` in `config.Settings`, leer = aus,
  Vorgabe **3**. **Keine Migration** — dieselbe Form wie die
  Batterie-Schwellen (AE-73): eine Abwägung, die pro Haus verstellbar
  ist, gehört in die Settings und nicht in `global_config`, solange die
  Oberfläche sie nicht braucht.
- Der **stündliche** Beat, der schon läuft
  (`occupancy-import-freshness-hourly`), vergleicht zusätzlich
  `last_success_at` gegen die Schwelle.
- Gleicher Audit- und Mailpfad wie der heutige Stale-Alarm, gleiche
  Tagesdrosselung (`alert_throttle`).

**Eine Bedingung, ohne die es ein Lärmgerät wird:** der Abstand gilt nur
**innerhalb des Versandfensters**. Zwischen 19:30 und 08:30 liegen 13
Stunden, und die sind normal. Ohne diese Einschränkung schlägt der
Wächter jede Nacht an — und ein Melder, dem niemand glaubt, überwacht
nichts (§5.79).

**Tests:** innerhalb des Fensters mit Abstand > 3 h → Alarm; mit Abstand
< 3 h → still; über Nacht → still; Schwelle leer → ganz aus.

**Aufwand T3: 2 h.** Risiko gering, keine Hardware.

---

## Reihenfolge und Begründung

**T3 → T1 → T2.**

**T3 zuerst**, obwohl es das kleinste ist: es ist das einzige ohne
Hardware-Berührung, es schließt eine Lücke, die seit dem 20.10. offen
ist, und es kann am ersten Tag gemergt werden. Danach ist der
Mehrfachversand vollständig überwacht, während die beiden
Hardware-Tasks laufen.

**T1 vor T2**, aus zwei Gründen:

1. T1 ist **belegt** — Byte-Format, Wertebereiche, GET-Befehl und die
   Downlink-Ausnahme stehen schwarz auf weiß. T2 braucht erst eine
   Messung, bevor der Parameter feststeht.
2. T1 hat den **unmittelbaren** Nutzen: der Gast dreht heute auf 29 und
   die Engine kappt hinterher (§10af). T2 verbessert eine Erkennung, die
   heute gar nicht läuft — also nichts, was schlechter wird, wenn es eine
   Woche später kommt.

**Beide Hardware-Tasks nicht parallel.** Wenn in derselben Woche
Gerätegrenzen und Fenstererkennung auf dieselben Geräte gehen und etwas
Unerwartetes passiert, ist die Ursache nicht zuzuordnen. 306 Schlafzimmer
steht in **beiden** Testplänen — ein weiterer Grund, sie zu trennen.

---

## Was ausdrücklich nicht in diesem Sprint ist

| | |
|---|---|
| `scope="col"` an den Tabellenköpfen | gemessen am 19.10.: **0** Spaltenköpfe auf der API-Seite. Eigener kleiner PR |
| B-22-5 (BOM in `Caddyfile.main`) | Backlog, keine Aktion (Entscheidung 21.10.) |
| Kopfzeile der Vendor-Kopie | der Satz, dass sie eine Zusammenfassung mit Abrufdatum ist. Mini-PR, nicht hier — aber **vor** dem nächsten Mal, dass jemand eine Befehlsnummer daraus liest |
| FW < 4.2 für die Fenstererkennung | B-17-5, nach T2 |

---

## Pflicht-Stops

1. **Nach T1.2**, bevor ein `0x08` an mehr als ein Gerät geht: der
   Versuch mit Grenze 15/25 und Downlink **10 °C** — übernimmt das
   Gerät die 10? Aufbau und die drei möglichen Ergebnisse stehen in T1.
   Hersteller-Aussage ist keine Messung.
2. **Nach T1.6**, vor dem Rollout auf alle Geräte: die vier Prüfungen aus
   48 h Beobachtung.
3. **Vor T2.5**, der Messung mit Delta 0,2: sie geht an **ein** Gerät
   (306 Schlafzimmer), am Vormittag, mit einem Tag Abstand zur nächsten
   Absenkung. Bei diesem Wert ist ein Fehlalarm zu **erwarten** — er
   beendet die Testwoche nach dem Abbruchkriterium, und das ist der Preis
   der Messung, kein Widerspruch.
4. **Nach T2 Schritt 4**, vor dem Festschreiben des Parameters: ob die
   Nachtabsenkung einen Fehlalarm erzeugt. **Ein einziges Auftreten
   beendet den Task für diese Woche** (Abbruchkriterium, siehe T2) —
   kein Nachjustieren. Die Absenkung gilt **ab 20:00**.
5. **Vor einer Entscheidung über Plan B**: der dritte Abschnitt des
   306-Testfalls (Nachtabsenkung **ohne** Lüften). Ohne diese Zahl ist
   nicht bekannt, ob 3 K über der eigenen Absenkung liegen, und Plan B
   ist nicht entscheidungsreif.
6. **Vor jedem Merge:** §0.3.

**Querverweise:** B-22-1 (0x08), B-9.11y-1 (Fenster-Test ohne
Drehrad-Störung), B-17-5 (FW < 4.2), AE-47 (Hardware-First bei der
Fenstererkennung), AE-48 (Downlink-Helfer), AE-52 (Fenster
belegungsabhängig), AE-73 (Schwellen in den Settings), §5.21
(Codec-Routing über `bytes[0]`), §5.22 (Codec-Re-Paste), §5.27
(Vicki-Hardware-Realität), §5.71 (Reboot und `resync_pending`), §5.84
(relatives Kriterium gegen eine bewegte Umwelt), RUNBOOK §10af, §10ae,
§10ai.
