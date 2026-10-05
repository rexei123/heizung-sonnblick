# Sprint 20f — Gerät folgt immer der Engine

**Datum:** 2026-10-05
**Auftrag:** Hotelier, 05.10.2026 (mit zwei Nachträgen zu T2 und den
Akzeptanzkriterien am selben Tag)
**Frist:** live vor der Wiedereröffnung **01.11.2026**
**Autonomie-Stufe:** 2 (Standard). T2 und T3 berühren die Override-Logik und
den Downlink-Pfad — dort gilt Stufe 1, also Pflicht-Stop bei jeder Abweichung
vom Brief.

---

## 1. Ziel

Der Sollwert **am Gerät** entspricht immer dem Engine-Soll — außer während
eines aktiven Overrides. Handverstellung und Montage-Drehung werden korrekt
erkannt. Ein Override endet mit jeder Abreise.

---

## 2. Befunde

### 2.1 Das Gerät bleibt auf einem Wert, den niemand gesetzt hat

Geräte **048** und **057**: nach der Montage-Drehung stand am Gerät 20 °C,
der Engine-Soll war 18 °C, und es gab **keinen** Override. Die Engine hat
nicht nachgesendet. Korrigiert wurde per Hand über die Queue (`5100b4`).

Die Ursache ist kein Fehler, sondern eine Lücke im Entwurf: die Hysterese
vergleicht den neuen Sollwert mit dem **letzten selbst gesendeten**, nicht
mit dem, den das Gerät meldet
([engine.py:795-827](../../backend/src/heizung/rules/engine.py:795)). Hat die
Engine zuletzt 18 geschickt und will wieder 18, ist `delta = 0` und sie
schweigt — unabhängig davon, was am Gerät steht. Erst nach
`HEARTBEAT_INTERVAL` greift der Re-Sync.

**Die Engine kennt also ihren eigenen Willen, aber nicht den Zustand des
Geräts.** Das ist die Lücke, die T3 schließt.

### 2.2 Der Codec verwirft gültige Messwerte

Ein `0x28`-Frame (Handverstellung, FW ≥ 3.5) trägt ab Byte 2 einen
**vollständigen 9-Byte-Keepalive**. Der Codec routet alles, was nicht
`0x52`/`0x04`/`0x46` ist, nach `decodePeriodicReport`, und die bricht am
Command-Byte ab ([mclimate-vicki.js:96-101](../../infra/chirpstack/codecs/mclimate-vicki.js:96)).
Ergebnis: `{command: 0x28}` ohne Daten, und der Subscriber schreibt daraus
eine `sensor_reading`-Zeile, in der **alles NULL** ist
([mqtt_subscriber.py:236](../../backend/src/heizung/services/mqtt_subscriber.py:236)).

Der Vor-Check des Eingangstests nimmt diese Zeile als „frisches Reading",
liest `attached_backplate IS NULL` und urteilt `backplate_unknown`
([batch_inbound_test.py:467](../../backend/src/heizung/scripts/pairing/batch_inbound_test.py:467)).
Mit `--require-motor` wird daraus **`fail`** — ein terminaler Status, den
`--resume` nie wieder anfasst
([:738](../../backend/src/heizung/scripts/pairing/batch_inbound_test.py:738),
[:153](../../backend/src/heizung/scripts/pairing/batch_inbound_test.py:153)).

Am 05.10. betraf das die Geräte **038–044**. Nachgerechnet aus den
Roh-Payloads: alle sieben meldeten `attached_backplate = true` **und**
`motorRange` zwischen 434 und 527 — also montiert **und** kalibriert. Sieben
einwandfreie Geräte mit FAIL, weil ein gültiger Frame weggeworfen wurde.

Real-Payloads für die Tests (05.10.2026):

| Gerät | Payload (11 Byte) | Hand-Ziel | eingebettet | backplate |
|---|---|---|---|---|
| 015 | `28148114959500d201b030` | 20 °C | `0x81` | true |
| 104 | `281481149e8fb9b911f030` | 20 °C | `0x81` | true |

### 2.3 Was sich als Fehlalarm erwiesen hat

Zwei meiner früheren Befunde sind durch Belege des Hoteliers entkräftet, und
das gehört hierher, damit niemand ihnen nachläuft:

- **Die Folge 25/21/25 an Gerät 049 war Bedienung**, kein Engine-Fehler.
  Das Audit zeigt drei Eingaben in 14 Sekunden: `SET 09:39:41`,
  `CLEAR 09:39:48`, `SET 09:39:55`. Die Engine hat jede davon korrekt
  umgesetzt. **Maßnahme C (veraltete Auswertung verwerfen) entfällt.**
- **Der Override endet bei Abreise korrekt.** Override 37 (Zimmer 207,
  Zone 244, `frontend_midnight`) wurde am 05.10. um 12:06 UTC widerrufen,
  über `auto_revoke_on_checkout`
  ([override_pms_hook.py:56](../../backend/src/heizung/services/override_pms_hook.py:56)).
  Meine gegenteilige Vorhersage war falsch: der Aufruf hängt zwei Ebenen
  tiefer in `sync_room_status` hinter einem funktionslokalen Import
  ([occupancy_service.py:251-257](../../backend/src/heizung/services/occupancy_service.py:251)),
  und die Audit-Aktion heißt `OVERRIDES_AUTO_REVOKED_ON_CHECKOUT`, nicht
  `MANUAL_OVERRIDE_CLEAR`.

### 2.4 Fachliche Regel des Hotels

**Ein Override endet mit jeder Abreise. Keine Ausnahme bei Folgebuchung.**
Überlappende Buchungen bleiben unberührt, weil das Zimmer dabei `OCCUPIED`
bleibt und der Statuswechsel gar nicht eintritt.

---

## 3. Vorab-Analysen, die der Auftrag verlangt

### 3.1 Wird `CLEANING` im Betrieb überhaupt gesetzt? — Nur von Hand, und das hat Folgen für T5

**Automatisch nie.** `derive_room_status` kennt den Wert nicht, und
`sync_room_status` **schützt** ihn ausdrücklich: ist ein Zimmer `CLEANING`,
kehrt die Funktion sofort zurück
([occupancy_service.py:242](../../backend/src/heizung/services/occupancy_service.py:242)).

Gesetzt wird `CLEANING` ausschließlich über `PATCH /api/v1/rooms/{id}` durch
einen **Admin**, aus der Status-Auswahl der Zimmer-Oberfläche
([room-form.tsx:162](../../frontend/src/components/patterns/room-form.tsx:162),
[zimmer/page.tsx:131](../../frontend/src/app/zimmer/page.tsx:131)).

**Daraus folgt eine Abweichung vom Auftrag, die vor der Umsetzung geklärt
sein muss.** T5 verlangt den Widerruf „bei jedem Wechsel OCCUPIED → nicht
OCCUPIED, auch → CLEANING". Dieser Wechsel kann über
`auto_revoke_on_checkout` **nicht** laufen: der Hook wird nur aus
`sync_room_status` gerufen, und dort entsteht `CLEANING` nie. Der
PATCH-Endpoint setzt `status` direkt per `setattr`
([rooms.py:181](../../backend/src/heizung/api/v1/rooms.py:181)) — ohne
Widerruf, **ohne Audit** und ohne Engine-Trigger.

Der Widerruf für den CLEANING-Fall braucht also einen zweiten Aufrufpunkt im
PATCH-Endpoint. Das ist eine Erweiterung gegenüber dem Brief-Wortlaut und
kostet zusätzlich **1 h** (plus Audit für die Statusänderung, das heute
fehlt).

**Rückfrage an den Hotelier:** Wird `CLEANING` im Haus tatsächlich benutzt?
Wenn nicht, ist der zweite Aufrufpunkt YAGNI (§0 S6) und T5 beschränkt sich
auf das Entfernen des Gnadenfensters. Der Code kann die Frage nicht
beantworten — er bietet den Zustand nur an.

### 3.2 Bit `0x40` im letzten Keepalive-Byte — es ist bereits dekodiert und wird verworfen

`0x40` ist **`calibrationFailed`**, und der Codec setzt es seit Sprint 6.8
([mclimate-vicki.js:163](../../infra/chirpstack/codecs/mclimate-vicki.js:163)).
Es kommt also im ChirpStack-`object` an — aber `_map_to_reading` liest es
nicht, und `sensor_reading` hat keine Spalte dafür. Der Wert wird bei jedem
Frame weggeworfen.

Gerät **026** mit `…f070`: `status8 = 0x70`, also

| Bit | Flag | Wert |
|---|---|---|
| `0x80` | `childLock` | false |
| **`0x40`** | **`calibrationFailed`** | **true** |
| `0x20` | `attachedBackplate` | true |
| `0x10` | `perceiveAsOnline` | true |
| `0x08` | `antiFreezeProtection` | false |

Zum Vergleich: die sieben Geräte aus 2.2 hatten `0x30` — identisch, **außer**
`calibrationFailed`.

**Das ist derselbe Befund wie 2.2, nur eine Ebene tiefer: die Information
kommt an und wir werfen sie weg.** Und sie ist genau die, die fehlt: ein
Gerät, dessen Kalibrierung fehlgeschlagen ist, fährt das Ventil nicht
richtig — und der Eingangstest beurteilt es über das Ventilkriterium, ohne
den Grund nennen zu können. Gerät 026 ist der erste belegte Fall.

T7 ist damit von „Analyse" auf **„umsetzen"** zu heben: Migration 0025 für
`sensor_reading.calibration_failed`, Durchreichen im Subscriber,
Berücksichtigung im Vor-Check (ein `calibrationFailed = true` ist ein
Befund mit Namen, kein `fail` ohne Begründung). Aufwand **1,5 h** statt 1 h.

### 3.3 `device_manual` braucht eine Migration

`manual_override.source` trägt eine DB-CHECK-Beschränkung mit den vier
heutigen Werten als Literale
([0008_manual_override.py:57-60](../../backend/alembic/versions/0008_manual_override.py:57)).
Ein fünfter Wert ist ohne Migration nicht einfügbar — der Insert schlägt mit
`CheckViolation` fehl. §5.45 ist die verwandte Lesson (dort war es die
Längenbeschränkung von `CommandReason`).

`device_manual` hat 13 Zeichen und passt in `length=30`. Gebraucht wird also
**nur** das Neuschreiben des CHECK, keine Spaltenänderung. Aufwand T2
dadurch **3 h** statt 2 h.

---

## 4. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T1** | **Codec `0x28`.** Reply-Teil (Byte 0–1: Command + Hand-Sollwert) und eingebetteten Keepalive (Byte 2+) dekodieren und mergen, Muster von `0x04` ([mclimate-vicki.js:214-245](../../infra/chirpstack/codecs/mclimate-vicki.js:214)). **Umgekehrte Regel beachten:** der Frame darf **keinen** Reply-`report_type` bekommen und nicht in `REPLY_REPORT_TYPES` landen ([mqtt_subscriber.py:49](../../backend/src/heizung/services/mqtt_subscriber.py:49)) — bei `0x04` muss er drinstehen, damit **kein** Reading geschrieben wird, hier wollen wir das Reading. Tests mit beiden Real-Payloads aus 2.2, plus Spiegel-Test gegen `downlink_adapter` (§5.28). | 2 h |
| **T2** | **Handverstellung als Override.** `0x28` mit abweichendem Sollwert: Zimmer **OCCUPIED** → Override mit Quelle **`device_manual`**, Ablauf **4 h**, im Audit sichtbar; endet zusätzlich mit der Abreise (T5). Zimmer **nicht OCCUPIED** (Montage, Leerstand) → **kein** Override, T3 stellt den Engine-Soll wieder her. Enthält **Migration 0026** für den CHECK (§3.3). Pflicht-Tests: Gast-Override hat Vorrang vor `device_manual`. | 3 h |
| **T3** | **Engine-Abgleich.** Gerät-Ist (letzter gemeldeter `sensor_reading.setpoint`) ≠ Engine-Soll **und** kein aktiver Override → erneut senden, Hysterese umgehen. **Begrenzung ist Pflicht:** höchstens **eine** Nachsendung je Gerät je **30 min**; nach **drei** erfolglosen Versuchen Audit-Eintrag plus Warnung und **Stopp**. Zähler und Drosselung in Redis, Muster aus `alert_throttle` und `resync_flag`. | 3 h |
| **T4** | **Vor-Check.** Wartet auf einen Frame **mit** `attached_backplate`, bis `--heartbeat-wait`. **Altersgrenze vom Wartefenster trennen** — heute ist beides dieselbe Zahl ([batch_inbound_test.py:401](../../backend/src/heizung/scripts/pairing/batch_inbound_test.py:401), `max_age_s == wait_s == 900`), weshalb bei 038–044 **keine Sekunde** gewartet wurde. Urteil nach Ablauf bleibt `backplate_unknown`, **nicht** `no_uplink` — der Funk hat funktioniert. | 1,5 h |
| **T5** | **Override endet bei jeder Abreise.** `CHECKOUT_GRACE_WINDOW` entfernen ([override_pms_hook.py:73-82](../../backend/src/heizung/services/override_pms_hook.py:73)), Test [:148](../../backend/tests/test_override_pms_hook.py:148) umdrehen. Der CLEANING-Teil **erst nach der Rückfrage aus §3.1**; wenn ja, zweiter Aufrufpunkt im PATCH-Endpoint plus Audit (+1 h), Test [:193](../../backend/tests/test_override_pms_hook.py:193) anpassen. | 1 h (+1 h) |
| **T6** | **Trace-Text.** „kein zimmerweiter Override" statt „kein aktiver Override" ([engine-decision-panel.tsx:338](../../frontend/src/components/patterns/engine-decision-panel.tsx:338)); bei vorhandenen Zonen-Einträgen Verweis auf den Block „Pro-Zone-Setpoints". e2e-Test. | 0,5 h |
| **T7** | **`calibrationFailed` persistieren** (§3.2, von Analyse auf Umsetzung gehoben): **Migration 0025** für `sensor_reading.calibration_failed`, Durchreichen in `_map_to_reading`, im Vor-Check als eigener benannter Befund. | 1,5 h |
| **T8** | **Doku.** `STATUS.md`-Abschnitt plus Kopf und §1 (§5.26), AE-Eintrag für den Engine-Abgleich (T3 ändert die Zusicherung „die Engine sendet nur bei eigener Änderung" — das ist eine Architektur-Entscheidung), RUNBOOK-Handgriff „Gerät steht auf einem falschen Wert — was tun". | 1 h |

**Summe: 13,5 h** (14,5 h mit dem CLEANING-Teil).

**Zwei Migrationen, nicht eine.** Der erste Entwurf dieses Briefs sah beide
Spalten in einer Datei 0025 vor. Das geht nicht: `calibration_failed` gehört
zu T7 und damit in PR 1, der CHECK für `device_manual` zu T2 und damit in
PR 2. Eine gemeinsame Datei müsste quer über zwei PRs liegen. Also
**0025** (`sensor_reading.calibration_failed`, PR 1) und **0026** (CHECK auf
`manual_override.source`, PR 2) — jede in dem PR, dessen Code sie braucht.
Das ist auch die sauberere Form: eine Migration, die zur Hälfte ungenutzt
deployt wird, ist eine Migration, deren Zweck man später nicht mehr erkennt.

### PR-Schnitt

| PR | Inhalt | Begründung |
|---|---|---|
| 1 | **T1 + T4 + T7** | Ein Thema: der `0x28`-Frame und was aus seinen Daten wird. Migration 0025, Codec, Subscriber, Vor-Check. Behebt die falschen FAILs — der nächste Montagetag braucht das zuerst. |
| 2 | **T2 + T3** | Ein Thema: wer bestimmt den Sollwert am Gerät. Teilt sich den Override-Pfad und die Tests; getrennt wären die Vorrang-Tests zweimal zu schreiben. |
| 3 | **T5 + T6** | Ein Thema: Override-Lebensdauer und ihre Darstellung. Beides klein, beides unabhängig vom Downlink-Pfad. |
| 4 | **T8** | Doku, nach den drei anderen — sonst stehen dort Zahlen, die noch nicht stimmen. |

§0.3 vor **jedem** Merge.

---

## 5. Akzeptanzkriterien

1. **Handverstellung in belegtem Zimmer:** das Gerät behält den Gastwert
   **4 h** bzw. bis zur Abreise, danach gilt der Engine-Soll. Test **und**
   Realtest an einem Gerät.
2. **Handverstellung in unbelegtem Zimmer:** spätestens **45 min** später
   steht das Gerät wieder auf dem Engine-Soll. Test **und** Realtest an einem
   Gerät. (Die 45 min sind der schlechteste Fall aus 30-min-Drosselung plus
   10-min-Keepalive.)
3. Die beiden `0x28`-Payloads aus §2.2 werden **vollständig** dekodiert,
   `attached_backplate` und `setpoint` landen im Reading, und es entsteht
   **kein** falscher Vor-Check-FAIL.
4. Die Abreise beendet **jeden** Override, auch bei Folgebuchung mit Lücke.
5. Der Abgleich sendet **nie öfter als 1×/30 min je Gerät** und stoppt nach
   drei erfolglosen Versuchen mit Audit und Warnung.
6. `calibrationFailed = true` erscheint im Vor-Check als benannter Befund,
   nicht als unbegründetes `fail`.

**Gegenprobe als Pflicht** (§5.79): vor jedem PR wird der alte Code-Stand
wiederhergestellt und belegt, dass die neuen Tests fallen — mit dem Bild, das
der Hotelier gemeldet hat. Ein Regressionstest, der gegen den Fehler nicht
rot ist, prüft nichts.

---

## 6. Definition of Done

`mypy`, `ruff check`, `ruff format --check`, `npm run type-check`,
`npm run lint`, `pytest`, Playwright, CI grün; gemergt nach `develop`;
Merge-Anker `collected N = passed + xfailed`, **0 skipped**, `head_sha` gegen
PR-HEAD, Image-SHA-Beleg; Eintrag im Stand-Dokument (`STATUS.md`, §5.26).

---

## 7. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| **T3 kostet bei schwachem Funk Batterie.** Jede Nachsendung ist eine Motorbewegung (§0 S4). | Die Begrenzung ist **nicht** optional: 1×/30 min, Stopp nach drei Versuchen. Ein Test, der das Überschreiten erzwingt, gehört dazu. |
| **T2/T3 berühren den Override-Pfad.** Ein Fehler dort lässt ein Zimmer kalt oder heizt es durch. | Vorrang-Tests für den Gast-Override sind zwingend: `frontend_*` schlägt `device_manual` schlägt `device` ([override_service.py:384-397](../../backend/src/heizung/services/override_service.py:384)). |
| **T3 kann mit einem laufenden Eingangstest kollidieren:** der Test setzt Sollwerte, die Engine zieht sie zurück. | Prüfen, ob der Abgleich Pool-Geräte ausschließt (ohne Zone kein Engine-Soll — vermutlich schon durch `room_id is None`). Im PR belegen. |
| **Deploy während eines Eingangstests.** | §0.3 vor jedem Merge, zusätzlich zur Redis-Sperre aus Sprint 20a. |
| **T1 ändert den Codec**, und der wird nicht automatisch ausgerollt. | §5.22: nach dem Merge manueller Re-Paste in der ChirpStack-UI **je Server**, danach Verifikation am Events-Tab eines aktiven Vickis. Gehört in den PR-Text als Nachlauf-Schritt. |

---

## 8. Nicht in 20f (Backlog)

- **A** Downlink unterdrücken, bis der vorige bestätigt ist, und **B**
  Ack-Fenster an Class A anpassen: **erst nach T3 bewerten.** T3 deckt
  verlorene Downlinks teilweise ab — möglicherweise genügt das, und dann
  wäre A ein Mechanismus ohne Anlass (§0 S6).
- Queue vor dem Einreihen leeren (Optimierung; braucht gRPC, §5.28).
- `AwareDatetime` in `OccupancyCreate` — heute wird ein naiver Zeitstempel
  angenommen, obwohl die Beschreibung „timezone-aware" behauptet
  ([schemas/occupancy.py:16](../../backend/src/heizung/schemas/occupancy.py:16)).
- „Stornieren" nur bei laufenden oder künftigen Belegungen anbieten.
- Paketverlust je Gerät aus `fcnt`-Lücken.

**Folge für Sprint 20e:** Die **15-Minuten-Sperre für die Montage-Drehung**
aus dem 20e-Gate wird durch T2 in der neuen Fassung weitgehend
gegenstandslos — in einem unbelegten Zimmer entsteht gar kein Override, und
die Montage findet in unbelegten Zimmern statt. Sie bleibt nur für den Fall
„Montage im belegten Zimmer" relevant. Vor 20e neu bewerten, nicht blind
umsetzen.

---

## 9. Querverweise

- **Befunde:** §2.2 → `batch_inbound_test.py`, §2.3 → `override_pms_hook.py`
- **Lessons:** §5.21 (Hardware-Annahmen über das Payload-Byte), §5.22
  (Codec-Deploy ist nicht automatisch), §5.28 (Downlinks über MQTT, nicht
  gRPC), §5.45 (Enum-Beschränkungen vor der Erweiterung prüfen), §5.71
  (Reboot-Drift und das M1-Risiko eines langlebigen DEVICE-Overrides), §5.76
  (Wirkung überwachen statt Mechanik — T3 ist genau das: nicht „habe ich
  gesendet", sondern „steht der Wert am Gerät"), §5.79 (Gegenprobe als
  Pflicht)
- **ADRs:** AE-45 (Drehring-Auto-Detect), AE-52 (Fenster vor Komfort), AE-58
  (Override-Modell, OCCUPIED-Gate), AE-63 (Reboot-Re-Sync — der einzige
  bestehende Hysterese-Bypass, Vorbild für T3), AE-74 (Montage-Status, 20e)
