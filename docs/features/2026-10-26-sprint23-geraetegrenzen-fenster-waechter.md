# Sprint 23 — Gerätegrenzen, Fenstererkennung, Abstands-Wächter

**Brief, kein Code.** Erstellt 21.10.2026, Frist 26.10. Start frühestens
**Mi 28.10.**, nach Rotation Teil 2 (27.10.).

**Autonomie-Stufe 1** (volle Stop-Points, CLAUDE.md §0.1): zwei der drei
Tasks schreiben in **Hardware-Befehlspfade**. T1 verändert, was das Gerät
selbst zulässt; T2 schaltet einen Algorithmus im Gerät ein, der
eigenständig das Ventil schließt. Beides ist nicht durch einen Rückweg in
der Datenbank zu heilen.

**Gesamtaufwand:** 11–16 h über drei Tasks, plus 48 h Beobachtung in T1
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

**T1.5 — Rollout** (1 h Arbeit, 48 h Wartezeit). Erst **ein** Gerät: 306
Schlafzimmer. Nach 48 h prüfen:

1. `0x15` liefert 15/25 (Abgleich bestätigt, was gesendet wurde).
2. Das Drehrad lässt sich **nicht** über 25 drehen — am Gerät zu prüfen,
   nicht am Protokoll.
3. Ein Engine-Downlink über 25 (Testfall) kommt trotzdem an.
4. Keine zusätzlichen Downlinks im Protokoll: der Abgleich darf nicht
   jede Viertelstunde senden, wenn die Grenzen stimmen.

Erst danach alle Geräte, gestaffelt.

### Risiken

| Risiko | Einschätzung |
|---|---|
| Die Hersteller-Aussage „Downlink darf überschreiten" stimmt nicht | **Pflicht-Stop.** T1.2 prüft es ausdrücklich. Dann kollidiert die Gerätegrenze mit Layer 5 und der Task wird neu geschnitten |
| Massen-Downlink aus einem UI-Klick | über den gestaffelten Pfad entschärft; der Test dafür ist ein `PATCH` auf „Bad" mit Zählung der Downlinks pro Minute |
| Codec-Re-Paste vergessen | `0x15` bleibt undekodiert, der Abgleich ist blind und sendet **nicht** (fail-closed). Kein Schaden, aber eine stille Wirkungslosigkeit — deshalb ein Test, der die dekodierten Felder in `sensor_reading` erwartet |
| Grenzen „verschwinden" nach einem Neustart unbemerkt | genau dagegen ist der `0x15`-Abgleich. Vorher war das der Grund für das wöchentliche Nachsenden |

**Aufwand T1: 7–9 h** plus 48 h Beobachtung.

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

**Aufwand T2: 3–5 h** plus 72 h Beobachtung (zwei Nächte, damit die
Absenkung zweimal gemessen ist).

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

1. **Nach T1.2**, bevor ein `0x08` an ein Gerät geht: der Beleg, dass ein
   Downlink die Gerätegrenze überschreiten darf. Hersteller-Aussage ist
   keine Messung.
2. **Nach T1.5**, vor dem Rollout auf alle Geräte: die vier Prüfungen aus
   48 h Beobachtung.
3. **Nach T2 Schritt 4**, vor dem Festschreiben des Parameters: ob die
   Nachtabsenkung einen Fehlalarm erzeugt.
4. **Vor jedem Merge:** §0.3.

**Querverweise:** B-22-1 (0x08), B-9.11y-1 (Fenster-Test ohne
Drehrad-Störung), B-17-5 (FW < 4.2), AE-47 (Hardware-First bei der
Fenstererkennung), AE-48 (Downlink-Helfer), AE-52 (Fenster
belegungsabhängig), AE-73 (Schwellen in den Settings), §5.21
(Codec-Routing über `bytes[0]`), §5.22 (Codec-Re-Paste), §5.27
(Vicki-Hardware-Realität), §5.71 (Reboot und `resync_pending`), §5.84
(relatives Kriterium gegen eine bewegte Umwelt), RUNBOOK §10af, §10ae,
§10ai.
