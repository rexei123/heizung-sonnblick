---
datum: 2026-11-16
thema: tx_power_index steht jetzt in unserer Datenbank — 109 Geräte statt 55
pr: offen
---

# Der Uplink trägt die Sendeleistung nicht, und kann es nicht

**Migration: ja** (0040, zwei nullable Spalten auf `device`, kein
Backfill). **Keine Server-Änderung in diesem PR** — der Zugang, den der
Task braucht, ist eine Nur-Lese-Rolle in ChirpStacks Postgres, und die
richtet der Betreiber ein (§10bf). Ohne sie läuft der Task leer und
schreibt nichts.

## Der Quellcheck zuerst, weil er die Lösung bestimmt hat

Die Aufgabe kam aus PR #422: §10av Schritt 6a liest `tx_power_index` je
Gerät aus dem Container-Protokoll, und deshalb musste die Log-Grenze dort
1572 MB halten. Die naheliegende Annahme war, den Wert am ohnehin
verarbeiteten Uplink mitzuschreiben. **Die trägt nicht.**

Geprüft am Protobuf-Schema von ChirpStack 4.17
(`api/proto/integration/integration.proto`): `UplinkEvent` hat 16 Felder
— `adr`, `dr`, `f_cnt`, `tx_info`, `rx_info` und weitere — und **keines**
mit der Sendeleistung des Geräts. Das ist keine Lücke im Schema, sondern
Physik: **das Gateway kann die Sendeleistung des Geräts nicht messen.**
Nur der Netzserver kennt sie, weil er sie selbst befohlen hat.

Wo sie steht: `internal.DeviceSession`, Feld **24**
(`uint32 tx_power_index = 24;`, Nachbarn `nb_trans = 23`, `dr = 25`).
ChirpStack 4 hält diese Nachricht protobuf-serialisiert in
`device.device_session` seiner eigenen Postgres-Instanz.

## Was die neue Quelle besser macht

Am 16.11.2026, 05:45 UTC, beide Quellen in derselben Stunde gegengerechnet:

| `tx_power_index` | Geräte-Sitzung | Container-Protokoll |
|---|---|---|
| 0 | 16 | 15 |
| 1 | 1 | 1 |
| 2 | 5 | 5 |
| 3 | 7 | 5 |
| 4 | 11 | 10 |
| 5 | 6 | 6 |
| 6 | 4 | 3 |
| 7 | **59** | **10** |
| **Summe** | **109** | **55** |

**Die Lücke sitzt bei den eingeschwungenen Geräten.** ADR protokolliert
nur, wenn es etwas ändert — ein Gerät auf Stufe 7, an dem sich nichts
bewegt, kommt tagelang nicht vor, obwohl sein Wert weiter gilt. Das
Protokoll kannte nach 21,8 Stunden die Hälfte der Geräte, und §10av
Schritt 6a erwartet „rund 90 Geräte auf `tx_power_index=7`".

Dazu kommen die zwei Mängel, die PR #422 beschrieben hat: eine
Neuerstellung des Containers legt das Protokoll leer an, und es wächst
mit 79,3 MB/Tag, wovon diese Zeilen 0,19 % sind.

## Geprüft, nicht angenommen

Der **ausgelieferte** Dekoder — derselbe Quelltext, der in
`services/chirpstack_session.py` steht — ist gegen die echten Sitzungen
am Server gelaufen: **109 Geräte gelesen, 0 unlesbar**, Verteilung wie in
der Tabelle oben. Die Rohbytes haben dabei den Server nicht verlassen.

Gegenprobe, dass der Dekoder das **richtige** Feld liest: Feld 25 (`dr`)
ergab 108 Geräte auf DR5 und **genau eines auf DR3**. Dass ein Relais auf
DR3 hängt, steht unabhängig davon in §10av — Gerät 108, seit dem Rückzug
des ADR-Plugins am 15.11.

## Zwei Dinge, die leicht still falsch wären

**„Feld fehlt" heißt 0, nicht „unbekannt".** Protobuf lässt Felder mit
dem Standardwert weg. 16 der 109 Sitzungen hatten kein Feld 24 — und
genau diese 16 zeigt das Protokoll als `tx_power_index=0`, also volle
Sendeleistung. Wer „fehlt" als `NULL` schreibt, verliert die Gruppe, die
am dichtesten am Gateway sitzt. Ein Test hält das fest.

**Der Schlüssel von Feld 24 (`0xC0 0x01`) kommt auch im Inneren anderer
Felder vor** — im Schlüsselmaterial einer echten Sitzung ist das eine
Frage der Zeit. Der Parser läuft deshalb die obersten Felder **ab** und
sucht die Bytes nicht; ein Test baut genau diese Falle.

## Was es kostet

Eine Nur-Lese-Rolle in einer Datenbank, die einem anderen Dienst gehört,
mit `SELECT` auf **zwei Spalten einer Tabelle**. Die Wurzelschlüssel
(`device_keys`) bleiben außer Reichweite. In `device_session` stehen die
Sitzungsschlüssel; der Code liest ein Varint-Feld daraus und bringt die
Bytes in keine Meldung, kein Log und keine Ausnahme —
`test_keine_bytes_in_der_fehlermeldung` prüft das.

Und eine Kopplung an ein **internes** Schema von ChirpStack: Feld 24 ist
nicht Teil der öffentlichen API und kann sich mit einer Hauptversion
verschieben. Der Schutz davor ist kein Vertrauen, sondern ein
Wertebereich: über 15 (vier Bit in `LinkADRReq`) bricht der Dekoder ab,
statt eine Zahl zu schreiben, die niemand gesendet hat. Ein Gerät mit
unlesbarer Sitzung wird gezählt und übersprungen, nicht zum Abbruch des
ganzen Laufs.

**Kein `chirpstack-api`-Paket im API-Image.** Gelesen wird ein einziges
Varint-Feld; dafür braucht es keinen Protobuf-Compiler und keine zweite
Abhängigkeit (dieselbe Begründung wie in
`infra/chirpstack/requirements-provision.txt`).

**Kein zweiter Befehlsweg.** AE-48 und §5.28 halten Downlinks auf dem
MQTT-Pfad. Hier wird gelesen, aus einer Tabelle, nicht über die
gRPC-API — die den Wert ohnehin nicht herausgibt. Ein `SELECT` setzt
keinen Sollwert und füllt keine Queue.

## Offen

* **§10bf ist nicht eingerichtet.** Bis dahin bleibt §10av Schritt 6a bei
  der Protokoll-Pipeline, die jetzt ausdrücklich als Rückfall mit ihrer
  Unvollständigkeit dort steht.
* Die Abschnittsnummer **§10bf** setzt voraus, dass PR #422 (§10be) vorher
  landet. Wird #422 nicht gemergt, ist hier auf §10be umzunummerieren.
* Die Spalte beantwortet „welche Stufe, wann gelesen" — **keine
  Historie**. Für eine Verlaufskurve bräuchte es eine eigene Tabelle; dafür
  gibt es bisher keinen Anlass (§10av vergleicht zwei Zeitpunkte, und
  beide kann man notieren).
