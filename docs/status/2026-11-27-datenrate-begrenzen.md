# 27.11.2026 — Datenrate hausweit begrenzen (`max_dr = 2`)

**Stand:** PR offen, nichts gemergt, nichts ausgerollt. Rollout und
Kontrolle: RUNBOOK §10bj.

**Der Anlass** ist der Lauf `funkqualitaet --stunden 720` vom 27.11.2026:
rund zwölf Geräte mit 4,8 bis 25 % Verlust (004 mit 25 %, 001 mit 22 %,
dazu 007, 027, 021, 109 Panel, 026, 046, 056, 028, 002, 025), alle mit
SNR-Minima um −10 bis −13 dB. Der Rest des Hauses liegt unter 2 %.

**Das Ziel des Betreibers:** alle Geräte zentral auf eine robuste
Datenrate, **ohne Batteriewechsel und ohne Gang ins Zimmer.**

## 1. Die Quellenlage — fünf Fragen, fünf Antworten

Alle Stellen aus `chirpstack/chirpstack` am Tag **v4.17.0**, dem Digest
in `docker-compose.prod.yml` entsprechend, abgerufen am 27.11.2026.

### a) Schlüssel und Ort — und ja, er wirkt auf den Standard-ADR

`max_dr` steht in `region_eu868.toml` unter `[regions.network]`, neben
`min_dr` und `installation_margin`. Im Programm ist es
`config.rs`, `struct RegionNetwork { pub max_dr: u8 }`, und es landet
unverändert in der ADR-Anfrage (`downlink/data.rs`,
`_request_adr_change`):

```rust
installation_margin: self.network_conf.installation_margin,
min_dr: self.network_conf.min_dr,
max_dr: self.network_conf.max_dr,
```

Der Algorithmus je Gerät wird über das **Geräteprofil** gewählt
(`adr::handle(&self.device_profile.adr_algorithm_id, &req)`). Die Vickis
laufen auf `default`, und `default` liest `req.max_dr`. Die Grenze wirkt
also auf genau den Algorithmus, um den es geht.

**Je Gerät ist sie nicht einstellbar.** ChirpStack kennt `max_dr` nur in
der Region — wer ein einzelnes Gerät anders behandeln will, braucht ein
ADR-Plugin. Genau deshalb gibt es eines für das Relais.

### b) Er senkt **aktiv** ab — das ist die Entscheidung für Weg 2a

`adr/default.rs`, woertlich:

```rust
// Lower the DR only if it exceeds the max. allowed DR.
if req.dr > max_dr {
    resp.dr = max_dr;
}
```

Drei Dinge daran sind wichtig:

1. **Die Klammer sitzt vor der Schrittrechnung** und ist an keine
   Vorgeschichte gebunden. Sie greift bei jedem Durchlauf, an dem
   `req.adr` gesetzt ist — auch bei dem Rücksprung weiter unten
   (`if n_step < 0 && history != 20 { return Ok(resp) }`), denn `resp`
   trägt die gesenkte Rate schon.
2. **Weicht die Antwort von der Anfrage ab, entsteht ein `LinkADRReq`**
   (`_request_adr_change`, Vergleich auf `dr`, `tx_power_index`,
   `nb_trans`).
3. **Eine anstehende MAC-Anweisung reicht allein als Grund für einen
   Downlink** (`_something_to_send`: Warteschlange leer, kein ACK
   fällig, aber `mac_commands` nicht leer → es wird gesendet).

Zusammen: jedes Gerät über der Grenze wird beim **nächsten eigenen
Uplink** abgesenkt. Bei sechs Meldungen je Stunde sind das zehn Minuten
hausweit, ohne einen Befehl von unserer Seite.

**Die Gegenrichtung gibt es nicht.** Bei negativen Schritten erhöht
`get_ideal_tx_power_index_and_dr` ausschließlich die Sendeleistung
(`tx_power_index.saturating_sub(1)`); die Datenrate lässt es, wo sie
ist. **Ein Gerät, das an der Schwelle wackelt, bleibt oben** — dauerhaft,
von sich aus. Diese Grenze ist der einzige Weg nach unten.

**Die Voraussetzung ist das ADR-Bit des Geräts.** `ds.adr` kommt aus
`pl.fhdr.f_ctrl.adr`, also aus dem Uplink. Ist es `false`, gibt der
Algorithmus die Anfrage unverändert zurück, und die Grenze erreicht das
Gerät nicht. Für 001, 004 und 027 ist `adr: true` in den Events belegt.

### c) Class-C-Relais: dieselbe Grenze, aber ein anderer Weg hinein

Drei getrennte Punkte, alle gemessen am Quellcode:

**Die Grenze gilt auch für das Relais**, solange sein Profil auf
`default` steht. Mit `max_dr = 2` ist DR5 für 108 künftig ausgeschlossen
— genau die Hochstufung vom 16.11.2026, die das ADR-Plugin verhindern
sollte.

**Der `LinkADRReq` erreicht es nur über einen Uplink.** Der
Class-B/C-Weg (`_handle_schedule_next_queue_item`) ruft
`set_mac_commands()` **nicht** — er schickt nur Warteschlangen-Einträge.
MAC-Anweisungen entstehen allein im Uplink-Antwortpfad
(`handle_response`). Das Relais sendet ebenfalls sechs Meldungen je
Stunde, der Unterschied ist also praktisch keiner; die Annahme „Class C
bekommt es sofort" wäre aber falsch.

**Die Downlinks selbst werden davon nicht länger.** Class-C-Downlinks
gehen über RX2, und `rx2_dr = 0` ist fest — SF12, unabhängig von der
Datenrate der Uplinks. Was sich ändert, sind die **RX1**-Fenster der
Vickis: bei `rx1_dr_offset = 0` folgt die Downlink-Rate der
Uplink-Rate, ein Sollwert-Befehl braucht dort künftig 371 ms statt
57 ms. Bei der Befehlsdichte nach dem Entprellen (PR #441) ist das
nichts, aber es gehört gesagt.

### d) 027 auf DR3 nach dem Rejoin: ADR, nicht die Join-Rate

**Nicht endgültig entscheidbar ohne die Events** — der Befehl dafür
steht in §10bj, Schritt 4.4. Was der Quellcode sagt, ist aber eindeutig
genug für eine Richtung:

Nach einer Anmeldung ist `uplink_adr_history` **leer**
(`uplink/data.rs`, `set_adr`). Dann ist `get_max_snr` = −999, die
Schrittzahl stark negativ, und der Rücksprung bei `n_step < 0` greift:
**nichts ändert sich.** Die Vorgeschichte wächst mit jeder Meldung, und
**nach oben braucht ADR keine volle Vorgeschichte** — die Prüfung auf
20 Einträge steht nur im negativen Zweig. Eine einzige gute Meldung
genügt also.

Für einen Schritt nach oben verlangt der Algorithmus
`max_snr >= required_snr_for_dr + installation_margin`, bei Reserve 20:

| von | Schwelle | nötiges bestes SNR |
|---|---|---|
| DR0 | −20,0 dB | ≥ 0 dB |
| DR1 | −17,5 dB | ≥ +2,5 dB |
| DR2 | −15,0 dB | ≥ +5 dB |
| DR3 | −12,5 dB | ≥ +7,5 dB |

**Ein Gerät, dessen bestes SNR zwischen +5 und +7,5 dB liegt, landet
genau auf DR3 und bleibt dort** — und zwar binnen weniger Meldungen nach
dem Join. Das ist der Zustand von 027 um 10:37 bei fCnt 24. Die Reserve
von 20 dB hat die Hochstufung also **nicht verhindert**, sie hat sie nur
bei DR3 statt bei DR5 angehalten.

**Und das ist der eigentliche Befund:** der Algorithmus rechnet mit dem
**besten** SNR der letzten 20 Meldungen (`get_max_snr`), nicht mit dem
Mittel und nicht mit dem schlechtesten. In einem Haus, in dem dieselbe
Strecke je nach Tür, Möbel und Person um 20 dB schwankt, optimiert er
damit auf den günstigsten Augenblick und ignoriert den teuersten. Die
Reserve soll das abfangen — aber sie wirkt auf denselben Maximalwert.
Wer DR5 über die Reserve verhindern wollte, bräuchte bei beobachteten
Spitzen um +10 dB eine Reserve um 30, und die würde allen Geräten die
Sendeleistung festnageln. **Eine harte Grenze ist der einfachere und
deterministische Hebel** (§0 S6).

### e) Warum DR2 und nicht DR3

Die Schwellen sind Hardware (`config::get_required_snr_for_sf`): DR3
(SF9) −12,5 dB, DR2 (SF10) −15 dB.

| Gerät | SNR min (720 h) | reicht DR3? | reicht DR2? |
|---|---|---|---|
| 046 | −13,2 dB | **nein** | ja, 1,8 dB |
| 056 | −15,8 dB | **nein** | knapp nein |
| übrige zehn | −10 bis −13 dB | grenzwertig | ja |

**DR3 hätte genau die zwei Geräte nicht erreicht, um die es geht.** Dazu
zwei Einschränkungen, die in dieselbe Richtung zeigen:

* **Die Minima sind beschnitten.** Meldungen unterhalb der
  Demodulations-Schwelle kommen nie an und stehen in keiner Statistik.
  Was gemessen ist, ist die Untergrenze des *Messbaren* — der echte
  Rand liegt tiefer.
* **Das Fenster von 720 Stunden schließt die Leistungskorrektur vom
  16.11.2026 mit ein** (Reserve 10 → 20, bei 056 neun dB Gewinn). Die
  Minima stammen also teils aus der Zeit *davor*. Deshalb ist 056 nicht
  der Maßstab: eine Grenze für 109 Geräte nach dem schlechtesten Wert
  eines einzelnen Geräts aus der Zeit vor einer Korrektur zu ziehen,
  wäre die falsche Richtung.

**DR1 wurde verworfen.** Es würde 056 abdecken, kostet aber die doppelte
Sendezeit von DR2 für alle und löst ein Einzelproblem auf Kosten des
Hauses. Bleibt 056 nach dem Rollout auffällig, ist es ein Fall für sich
— und steht ohnehin auf „nur messen".

## 2. Funklast — gerechnet, nicht geschätzt

22 Byte je Meldung (9 Byte Nutzlast aus den Live-Frames plus 13 Byte
LoRaWAN), 125 kHz, CR 4/5, Präambel 8, Kopf explizit, CRC an. Formel im
Test, damit die Zahlen hier nachgerechnet und nicht geglaubt werden
müssen (`test_die_funklast_rechnung_im_kommentar_stimmt`).

| DR | SF | Schwelle | Sendezeit | je Gerät (6/h) | Kanallast 109 Geräte | mit nbTrans 2 |
|---|---|---|---|---|---|---|
| 5 | 7 | −7,5 dB | 57 ms | 0,009 % | 0,34 % | 0,69 % |
| 3 | 9 | −12,5 dB | 206 ms | 0,034 % | 1,25 % | 2,49 % |
| **2** | **10** | **−15,0 dB** | **371 ms** | **0,062 %** | **2,24 %** | **4,49 %** |
| 1 | 11 | −17,5 dB | 741 ms | 0,124 % | 4,49 % | 8,98 % |
| 0 | 12 | −20,0 dB | 1483 ms | 0,247 % | 8,98 % | 17,96 % |

**Die Vorschrift erlaubt 1 % je Gerät und Unterband** (36 s/h) — DR2
liegt mit 0,062 % um den Faktor 16 darunter. Die Kanallast ist keine
Vorschrift, sondern Belegung; sie teilt sich auf **drei** Kanäle, nicht
acht: `enabled_uplink_channels = []` heißt „alle der Region", und die
Region definiert keine `extra_channels`. Ein Test hält das fest, weil
die Rechnung sonst beim ersten Zusatzkanal still falsch wird.

**Die Sendezeit ist hier nicht die Grenze, das Funkbudget ist es.** Und
was gegenläufig wirkt: ADR fordert ab 5 % Verlust Wiederholungen
(`get_nb_trans`, bei 25 % Verlust `nbTrans = 2`). Die vier
Problemgeräte senden heute also doppelt — das fällt mit dem Verlust weg.

**Batterie:** 144 Meldungen am Tag × 371 ms × ca. 40 mA ≈ 0,6 mAh/Tag,
rund 18 mAh im Monat gegen 2,7 bei DR5. Ein frisches AA-Paar hat über
2000 mAh, und der Ventilmotor kostet ein Vielfaches davon. Die
heutigen Wiederholungen kosten mehr als der Unterschied.

## 3. Was geprüft wird — und was nicht

**Im echten Abbild** (`chirpstack/chirpstack:4`, Digest aus
`docker-compose.prod.yml`), gegen eine Wegwerf-Datenbank, drei Läufe,
zusammen 20 Sekunden:

1. Unsere Konfiguration lädt, `Setting up regions` erscheint, **und der
   Dienst läuft danach weiter**. Am Server wäre ein Abbruch eine
   Neustart-Schleife — am 15.11.2026 sieben Minuten ohne Verarbeitung.
2. **Ein unlesbarer Wert bricht den Start ab**, und die Meldung nennt
   `max_dr`. Das ist der Nachweis, dass ChirpStack genau diesen
   Schlüssel liest — und nicht nur, dass der Behälter startet.
3. **Ein unbekannter Schlüssel wird stillschweigend übergangen.** Das
   ist die Begründung für (2), gemessen: `RegionNetwork` trägt
   `#[serde(default)]`, und `impl Default` setzt `max_dr: 0`. Ein
   Tippfehler im Namen wäre also nicht wirkungslos, sondern **DR0 für
   alle** — SF12, 1,5 s je Meldung, 9 % Kanalbelegung, lautlos.

**Nicht geprüft wird der ausgehende `LinkADRReq`.** Dafür bräuchte es
einen angemeldeten Gateway, eine ABP-Sitzung und einen Uplink mit
gültigem MIC — ein eigener Prüfstand. Der Nachweis ist stattdessen der
Quellcode in Abschnitt 1b und die Kontrolle nach dem Rollout (§10bj,
Schritt 4.3 bis 4.6). Diese Grenze auszusprechen ist ehrlicher, als
einen Test zu behaupten, der mehr zeigt als er zeigt (§5.68).

**Mutationsproben: sechs, alle rot.**

| Probe | was rot wird |
|---|---|
| `max_dr` zurück auf 5 | der Wachposten |
| eine Sendezeit im Kommentar um 1 ms verschoben | die Funklast-Rechnung |
| Zielgrenze im Test auf DR3 | die Begründung „DR3 reicht nicht" |
| unlesbarer Wert unter erfundenem Namen | die Engine-Probe |
| `region_text`-Übersteuerung ignoriert | **beide** Engine-Proben |
| Kanalzahl 8 statt 3 | die Kanallast-Zahlen |

Die fünfte Probe hat einen echten Mangel gefunden: ohne die
Rücklese-Zusicherung `_pruefe_uebergeben` blieb die dritte Probe grün,
obwohl sie die **gute** Datei prüfte — grün aus dem falschen Grund
(§5.55). Der Test liest die übergebene Datei jetzt zurück.

## 4. Offene Punkte

**Der Prüfstand steht doppelt.** `test_adr_plugins.py` bringt in PR #425
denselben Docker-Aufbau in der Datei selbst mit. Dieser PR legt ihn als
`tests/conftest.py` daneben, statt #425 zu erweitern — **Begründung
siehe unten**. Wird #425 gemergt, gehört die dortige Fassung gelöscht
und durch die geteilte ersetzt (§5.53).

**Warum nicht in #425 hinein.** Dort hängt eine offene Frage: das Plugin
nagelt das Relais auf **DR1** fest, und das RUNBOOK sagt seit dem
17.11.2026 mit Messung das Gegenteil — 108 läuft seit der Stromtrennung
fehlerfrei auf **DR0**, eine Stufe robuster, und „Dafür gilt:
`ZIEL_DR = 0`, nicht 1". #425 zu mergen würde das Relais also auf eine
Rate setzen, die die eigene Doku als die schlechtere ausweist. Die
Datenraten-Grenze soll an dieser Entscheidung nicht hängen; sie macht
das Plugin zugleich weniger dringlich, weil sie DR5 für 108 ohnehin
ausschließt.

**Die Datenrate steht nicht in unserer Datenbank.** `sensor_reading`
führt `rssi_dbm` und `snr_db`, aber kein DR-Feld. Ein Verlauf ist nur in
ChirpStack sichtbar, und nur solange dessen Events reichen — eine
Wirkungskontrolle über Wochen ist damit nicht möglich. Für die Liste,
nicht für diesen PR.

**Querverweise:** RUNBOOK §10bj (Rollout), §10av (Reserve 20 dB, das
ADR-Plugin und der Nachtrag vom 17.11.), §5.68 (Behauptung vs. Befund),
§5.76 (Wirkung statt Mechanik), §5.77 (der Vermerk, der seinen Zustand
wechselt), §0 S6 (die einfachere Variante trägt).
