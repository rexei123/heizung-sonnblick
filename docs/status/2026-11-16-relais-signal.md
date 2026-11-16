---
datum: 2026-11-16
thema: RSSI und SNR für Relais — und der Pfad, den noch nie ein Test gesehen hat
pr: offen
---

# Relais-Signal

**Migration 0041, additiv.** Zwei nullable Spalten auf `relay_reading`,
kein Backfill. Keine Server-Änderung in diesem PR.

## Der Anlass, und er ist eine Frage, die niemand beantworten konnte

Am 16.11.2026 hat ChirpStacks Standard-Algorithmus das Relais 108 auf
**DR5** hochgezogen — vier `LinkADRReq acknowledged` am 15. und 16.11.,
bei `installation_margin = 20` und `tx_power_index = 0`. Die Frage, die
darüber entscheidet, ob DR1 überhaupt die richtige Abhilfe ist, lautet:
*ist der Link zu schwach, oder kollidieren die Pakete?*

Sie war **nicht beantwortbar**, und nicht aus Mangel an Zeit:

* `sensor_reading` trägt `rssi_dbm` und `snr_db` — aber ein Relais
  schreibt dort nicht hin.
* `relay_reading` hatte die Spalten nicht.
* Das ChirpStack-Protokoll führt die Werte für dieses Gerät nicht.

Die Messung am selben Tag macht die Lücke konkret:

| Fenster | 108 | 109 Panel |
|---|---|---|
| 6 Stunden | **25,8 %** (31 an, 8 fehlend) | **0,0 %** (36 an) |
| 48 Stunden | 6,2 % (274 an, 17 fehlend) | 5,1 % (275 an, 14 fehlend) |

Über 48 Stunden sind beide Relais kaum zu unterscheiden; in sechs Stunden
verlor eines ein Viertel. **Der Verlust kommt in Schüben**, und ob die
Schübe Reichweite sind, sagen nur RSSI und SNR.

**Dieselbe Lücke war schon beschrieben.** `scripts/funkqualitaet.py`
nannte sie im Docstring und sagte, das Nachziehen sei „eine additive
Migration und ein eigener PR — sie würde erst ab dem Einbau Daten
sammeln und kommt für diese Messung zu spät". Das war am 03.11. richtig
und ist der Grund, warum es jetzt gebaut wird: für die **nächste** Messung
ist es nicht zu spät.

## Was geändert ist

| Stelle | Änderung |
|---|---|
| Migration 0041 | `rssi_dbm SMALLINT`, `snr_db NUMERIC(4,1)` auf `relay_reading` |
| `models/relay_reading.py` | die zwei Spalten, gleiche Typen wie in `sensor_reading` |
| `services/relay_uplink.py` | `werte_aus_codec` nimmt sie als **Parameter** |
| `services/mqtt_subscriber.py` | der Relais-Zweig liest `rxInfo` und reicht sie durch |
| `scripts/funkqualitaet.py` | liest `relay_reading` für Relais; der `if kind == RELAY: None`-Zweig ist weg |
| `api/v1/relays.py` | `rssi_dbm`, `snr_db` im `RelaisStand` |
| `components/patterns/relay-card.tsx` | Zeile „Funk (Empfang)" |
| RUNBOOK §10au Schritt 2 | stand „für Relais speichern wir das nicht" — erneuert |

**Zwei Dinge sind ausdrücklich keine zweite Wahrheit** (§5.53):

**Die 0-dB-Lücke von protojson wird nicht zweimal entschieden.**
`chirpstack.toml` setzt `json = true`, protojson lässt Felder mit
Default-Wert weg, also fehlt `"snr": 0.0` im JSON. Die Regel „Block da,
Feld weg heißt genau 0" steht in `mqtt_subscriber._snr_db` und ist dort
für den Thermostat-Pfad seit Sprint 20e belegt. Der Relais-Pfad **ruft
denselben Helfer**.

**`formatRssi` und `formatSnr` gibt es im Frontend schon.** Die neue Zeile
benutzt sie, statt eine zweite Formatierung derselben Zahl zu bauen.

**`rssi_dbm` und `snr_db` kommen nicht aus `obj`.** Sie stehen im
`rxInfo`-Block des Ereignisses, nicht in der Nutzlast — der Codec sieht
sie nie. Deshalb sind sie Parameter von `werte_aus_codec` und keine
`obj.get`-Zeile.

## Der wichtigste Test prüft keine Fachlichkeit

`test_der_subscriber_schreibt_die_empfangsdaten` schickt einen
Relais-Uplink durch `_persist_uplink` und sieht in der **Tabelle** nach.

**Im Subscriber-Test gab es bis heute keinen einzigen Relais-Fall.** Der
Relais-Zweig dort war nie durchgängig geprüft, nur seine Bausteine. In
genau diesem Gerätepfad ist das dreimal teuer geworden (§5.87): die
Firmware kam nicht an, der Tastendruck verlor seinen Grund, die
Rücklesung wurde nie vermerkt — **alle drei Male war die Funktion in
Ordnung und hatte keinen Aufrufer.** Ein Test, der nur `werte_aus_codec`
prüft, hätte alle drei durchgelassen und würde auch diese zwei Spalten
durchlassen.

Acht Tests, **sechs Mutationsproben, alle rot**:

| Probe | was rot wird |
|---|---|
| Subscriber reicht RSSI nicht durch | Verdrahtungstest **und** die 0-dB-Probe |
| Subscriber umgeht `_snr_db` | die 0-dB-Probe |
| `werte_aus_codec` lässt RSSI weg | drei Tests |
| `werte_aus_codec` lässt SNR weg | drei Tests |
| `funkqualitaet` liest wieder `sensor_reading` | der Werkzeug-Test |
| API nimmt nicht die jüngste Zeile | der Geräteseiten-Test |

## Ein eigenes Leck, beim Bauen gefunden und geschlossen

Der erste Gesamtlauf gegen die lokale Datenbank hatte **fünf
Fehlschläge** — in Boost- und Allgemeinbereich-Tests, die ich nicht
angefasst habe. Die Ursache war mein eigener Harness: drei Tests hier
schicken ein Ereignis durch `_persist_uplink`, und das ruft intern
`session.commit()`. Der `rollback()` am Ende räumt danach **nichts** weg.

Nachgezählt: **drei Geräte, drei Räume, drei Raumtypen** blieben liegen.
Die fünf fremden Tests prüfen hausweite Zahlen und fielen daran um.

Das ist §5.39 und dieselbe Klasse wie das Leck in
`test_api_rooms.zimmer_mit_thermostat`, das am 15.11. den
Funkempfangs-Test umgeworfen hat — und das ich in #420 geschlossen habe.
Der Kommentar im Nachbar-Harness (*„commit() wird auf der gleichen
Verbindung gemacht und beim Tear-down weggerollt"*) gilt dort, wo der
Test selbst nicht committet; hier galt er nicht. Der Fixture räumt jetzt
**nach Namen** auf, nicht nach Transaktion, und nach dem Lauf bleiben
null Zeilen.

## Was offen bleibt — für die Liste

**Die lokale Datenbank trägt Altlasten aus drei weiteren Testmodulen.**
`test_funkempfang.py::test_lies_funkempfang_zaehlt_nur_das_fenster` fällt
dort **auch allein**, ohne jede Änderung von mir. Gezählt am 16.11.:

```
praefix  | geraete
5e9e5e9e |      16
7acefeed |       3
7c107c.. |       2
```

Die Spuren führen zu `test_api_rooms.py`, `test_t4b_ausloeser.py` und
`test_trace_gesendeter_wert.py`. In der CI läuft das gegen eine frische
Datenbank und fällt nicht auf; lokal verfälscht es jeden Gesamtlauf und
kostet jedes Mal die Frage „ist das meine Änderung?". Das ist ein eigener
PR — dieselbe Art Aufräumen wie in #420, nur an drei Stellen.

**Querverweise:** RUNBOOK §10au (Schritt 2 erneuert), §10bd
(`relais_auswertung`), §5.53 (eine Wahrheit), §5.87 (eine Funktion ohne
Aufrufer), §5.39 (Testleckage), §5.51 (ein Feld, zwei Bedeutungen),
§5.55, `docs/status/2026-11-16-grosser-durchgang.md` (die Messung, aus
der die Zahlen kommen).
