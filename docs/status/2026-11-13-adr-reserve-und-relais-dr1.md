---
datum: 2026-11-13
thema: SNR-Reserve auf 20 dB für das Haus, DR1-Plugin für die Relais
pr: offen
---

# Eine Zahl für hundert Geräte, ein Plugin für zwei

Vorgabe des Betreibers vom 13.11.2026. **Kein Anwendungscode** — eine
Zahl in der Regionsdatei, eine JavaScript-Datei, zwei Zeilen
Konfiguration, Tests, RUNBOOK. Merge und Rollout **Mo 16.11.
nachmittags**, in einem ChirpStack-Neustart.

## Zwei Schäden aus einem Algorithmus

| Ursache | Gerät | Mittel |
|---|---|---|
| Sendeleistung weggenommen | **die Vickis**, 90 von 109 auf ca. 2 dBm | `installation_margin = 20.0` — **eine Zahl, hausweit** |
| Datenrate hochgezogen | **108** auf DR3 | ADR-Plugin am Profil „Relais 16ASPM" |

**Fühler 056** war von 14:41 bis 04:44 stumm — vierzehn Stunden, `fCnt
2904 → 2988`, **83 verlorene Frames**, am selben Platz. Nach der
Korrektur auf `tx_power_index 1`: RSSI von −113 auf **−104 dBm**, SNR von
−0,2 auf **+8,2 dB**. Neun dB, allein aus der Leistung. Danach fünf
Stufen in 70 Minuten zurück nach unten.

**Relais 108** wurde am 12.11. um 09:04 auf DR2 und um 09:27 auf DR3
gezogen (beide `LinkADRReq acknowledged`) und verlor dort 16 % seiner
Meldungen.

## Die Kehrtwende gegenüber dem ersten Entwurf

Dieser PR hatte zuerst **zwei** Plugins: eines für die Relais, eines für
die Fühler (feste Leistung, Datenrate adaptiv) samt eigenem Geräteprofil
„Heizung — feste Leistung (Randlage)" und einer Pflichtliste der Geräte,
die von ihrem Profil abweichen.

**Die Frage des Betreibers hat das überholt:** `installation_margin` ist
die SNR-Reserve, auf die ADR hinoptimiert, und sie steht in der
Regionsdatei. Für die Fühler löst sie dasselbe Problem mit **einer Zahl**
statt mit einem zweiten Mechanismus — kein Sonderprofil, kein Umhängen,
keine Abweichungs-Liste, keine Codec-Falle (§5.22). §0 S6 in Reinform:
die einfachere Variante reicht, also gilt sie.

**Für das Relais reicht sie nicht.** Der Algorithmus senkt die Datenrate
**nie** (nur eine Klammer bei `dr > max_dr`). 108 bleibt auf DR3
eingeklemmt, egal wie die Reserve steht. Das Plugin bleibt deshalb
unverändert: DR1, `nbTrans 2`, `txPowerIndex 0`.

## Was 20 dB bedeuten, gerechnet

Aus `chirpstack/src/adr/default.rs`:

```rust
let snr_margin = snr_max - req.required_snr_for_dr - req.installation_margin;
let n_step = (snr_margin / 3.0) as isize;
```

Im Gleichgewicht gilt `snr_max ≈ required_snr_for_dr + installation_margin`.
Bei DR5 (SF7, −7,5 aus `config.rs::get_required_snr_for_sf`):

| Reserve | Ziel-SNR | Wirkung auf unsere 103 Vickis |
|---|---|---|
| **10 dB** (bisher) | +2,5 dB | 86 hätten **noch Spielraum nach unten**, 0 bekämen zurück |
| 15 dB | +7,5 dB | 66 Spielraum, 15 zurück — **für 056 zu knapp** (+8,2) |
| **20 dB** | **+12,5 dB** | **0** Spielraum, 70 bleiben, **33 bekommen zurück** |

**Niemand verliert etwas.** Das ist der Grund, warum eine hausweite
Änderung hier vertretbar ist, obwohl ich gegen das hausweite Plugin
argumentiert hatte.

Grundlage: höchster SNR der letzten 20 Meldungen je Gerät (48-h-Fenster)
und die aktuelle Datenrate aus ChirpStack. 103 von 109 Geräten haben
beides — es fehlen die zwei Relais (`relay_reading` führt kein SNR) und
vier Geräte, die seit Oktober bzw. 04.11. schweigen.

## Die Rückkehr der Leistung: langsam, aber nicht so langsam wie befürchtet

```rust
if n_step < 0 && self.get_history_count(req) != self.required_history_count() {
    return Ok(resp);
}
```

`required_history_count()` ist **20**, und `get_history_count` zählt nur
Einträge mit **demselben** `tx_power_index`. Eine Erhöhung ist also erst
nach **20 Meldungen mit unveränderter Stufe** möglich — bei
Zehn-Minuten-Takt alle **3 h 20 min**.

**Aber die Anpassung ist rekursiv und wendet alle Schritte in einer
Entscheidung an.** Es ist deshalb nicht „eine Stufe je 3 h 20 min",
sondern „so viele Stufen, wie `n_step` sagt, einmal je 3 h 20 min".
Gerechnet auf die Messwerte vom 13.11.:

| Einstellzeit | Geräte | Stufen zurück |
|---|---|---|
| 0 (bewegt sich nicht) | **70** | 0 |
| 3 h 20 min | 18 | 1–5 |
| 6 h 40 min | 14 | 2–4 |
| 10 h 00 min | 1 (Gerät 021, Index 6 → 1) | 5 |

**Das Haus ist nach rund zehn Stunden eingestellt**, nicht nach Tagen.
Nach unten gibt es die Bremse nicht: positive Schritte laufen ohne
Sperre, gemessen an 056 fünf Stufen in 70 Minuten.

**Für 056: eine Entscheidung, 3 h 20 min.** Wie viele Stufen dabei
zurückkommen, hängt von seiner History ab — heute stehen dort Frames von
Index 1 bis 5 durcheinander, gerechnet ergibt das **eine** Stufe. Mit
einer eingeschwungenen History auf Index 5 wären es **fünf auf einmal**,
also direkt Index 0. Deshalb der Batteriewechsel in Schritt 4 der
Laufliste: er macht aus „irgendwann heute Abend" ein „jetzt".

## Korrektur meiner Batterierechnung von heute Vormittag

Ich hatte **20 mAh je Saison** genannt, gerechnet für ein Gerät, das von
2 dBm auf 14 dBm geht. Das ist der **Höchstwert für ein einzelnes
Gerät**, nicht der Hausdurchschnitt:

* **70 von 103 Geräten bewegen sich nicht** — für sie ändert sich nichts.
* Die 33, die sich bewegen, gewinnen im Mittel **2,4 Stufen ≈ 4,8 dB**,
  landen also typisch bei 6 bis 8 dBm und nicht bei 16.
* Mehrverbrauch für ein solches Gerät: rund **6 mAh je Saison**, also
  etwa **0,3 %** einer AA-Zelle.

Die Zahlen bleiben eine Schätzung mit offengelegten Eingangsgrößen
(Sendestrom aus dem Datenblatt der Funkstufe, 82 ms Sendezeit bei SF7, 144
Uplinks am Tag), kein Messergebnis. Der Motor dominiert den Verbrauch
einer Vicki ohnehin um Größenordnungen.

## Ein gewollter Nebeneffekt: neu beigetretene Geräte bleiben auf DR3

Ein Beitritt beginnt bei DR3, und mit der Reserve von 20 dB erhöht ADR
die Datenrate nicht mehr (`n_step ≤ 0` für alle unsere Geräte). Ein Vicki
nach einem Batteriewechsel sendet also dauerhaft auf SF9 statt SF7: 267
ms statt 82 ms je Uplink, bei 144 Uplinks am Tag **38 s Sendezeit = 0,044
%** Auslastung.

**Das ist Absicht und steht so im RUNBOOK** — robuster, und die
1-%-Grenze ist nicht in Sicht. Wer die Datenrate zurück will, senkt die
Reserve; es gibt keinen Weg, sie je Gerät zu erhöhen, weil der
Algorithmus sie nie senkt und wir sie nicht von Hand setzen können.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Relais: Zieldatenrate zurück auf DR3 | **1 Test rot** |
| Relais: Wiederholungen auf 1 | **1 Test rot** |
| Reserve zurück auf 10 dB | **1 Test rot** |
| Reserve auf 15 dB (für 056 zu knapp) | **1 Test rot** |
| Init-Sidecar: Kopierzeile entfernt | **1 Test rot** |
| chirpstack.toml: Plugin nicht aufgelistet | **zuerst grün — Lücke, geschlossen** |
| Relais: Leistung durchgereicht statt festgenagelt | **zuerst grün — Lücke, geschlossen** |

**Zwei Proben waren Lücken, und beide aus demselben Grund: der Test
prüfte etwas, das ohnehin stimmte.**

Die zweite ist die lehrreichere. Die Probe ersetzte `txPowerIndex: 0`
durch `req.txPowerIndex` — also „durchreichen statt festnageln" — und
blieb grün, weil die Standard-Anfrage im Test selbst schon Index 0
trägt. Durchreichen liefert dann dieselbe Null. Der Fall aus dem Betrieb
ist ein anderer: ADR hatte **109** am 13.11. auf Index 6 gesenkt. Der
neue Test fragt mit Index 6 und verlangt 0.

**Die erste Lücke mit Lehrwert.** Der Test suchte den
**Dateinamen** im ganzen TOML — und der steht auch im Kommentar über der
Liste. Die Probe entfernte die Zeile aus der Liste und blieb grün: ein
Test, der den Kommentar liest, prüft die Absicht statt der Wirkung
(§5.55). Er liest jetzt nur den Bereich zwischen `adr_plugins = [` und
`]` und verlangt dort den vollen, in Anführungszeichen gesetzten Pfad.

Die Probe „Reserve zurück auf 10 dB" ist der Wachposten für die
Entscheidung selbst: ein Rückfall wäre ohne Test nicht zu bemerken, denn
nichts bricht und nichts meldet — die Leistung sickert über Stunden
wieder weg.

## Läufe

* `infra/chirpstack`: **54 Tests grün**, mit `node` ausgeführt — nicht
  gegen einen Python-Nachbau. Die Datei lädt als **Skript** (`eval`),
  genau wie ChirpStack sie lädt.
* `ruff check`, `ruff format --check`, `mypy` grün.
* Kein Backend- und kein Frontend-Code berührt.

## Zwei Doku-Korrekturen, die mit dazugehören

**§10au Schritt 3 empfahl den Schaden als Abhilfe.** Die
Entscheidungstabelle stand für beide Zeilen auf **DR3** — also auf genau
der Datenrate, auf der 108 am 12.11. 16 % verloren hat. Die Zahlen
stammten von 109 **ohne Panel** in der Dose. Jetzt DR2 bzw. DR1.

**Der Status-Eintrag vom 02.11.** trägt einen Überholt-Vermerk mit Zeiger
hierher. Ohne ihn wäre er die nächste §5.77-Stelle — ein Dokument, das
„nicht ausgerollt, DR3" sagt und wie ein Befund gelesen wird.

## Was offen bleibt

**Die 48-Stunden-Kontrolle braucht einen Vorher-Wert**, und der ist am
Montag **vor** dem Neustart zu nehmen. Beide Abfragen stehen in §10av
Schritt 6: die Verteilung der Leistungsstufen (aus dem ChirpStack-Log,
weil `tx_power_index` nur in der Geräte-Sitzung lebt) und der hausweite
Paketverlust mit der Liste der schlechtesten Geräte.

**Der Mittelwert verdeckt den Rand.** Der hausweite Verlust lag in der
Nacht vom 12. auf den 13.11. bei rund 1 %, und darin steckten 93 % von
056. Deshalb die zweite Abfrage, und deshalb bleibt der Blick auf 056,
085, 041, 069 und 005.
