---
datum: 2026-11-13
thema: Zwei ADR-Plugins — Relais auf DR1, Fühler 056 auf feste Sendeleistung
pr: offen
---

# Der Netzwerkserver hat zweimal optimiert und zweimal geschadet

Vorgabe des Betreibers vom 13.11.2026. **Kein Anwendungscode** — zwei
JavaScript-Dateien, zwei Zeilen Konfiguration, Tests, RUNBOOK. Merge und
Rollout **Mo 16.11. nachmittags**, nach den Merges am Vormittag, in einem
ChirpStack-Neustart.

## Zwei Geräte, zwei Stellschrauben, eine Ursache

ChirpStacks Standard-Algorithmus rechnet auf den Meldungen, die
**ankommen**, und sieht die ausgefallenen nicht. Er erhöht die Datenrate,
wenn die Reserve gut aussieht, und senkt die Sendeleistung. Beides ist
hier passiert, an verschiedenen Geräten.

### Relais 108 — Datenrate zu hoch gezogen

```
12.11. 09:04  LinkADRReq acknowledged  dev_eui=...dd001f23  dr=2  tx_power_index=0
12.11. 09:27  LinkADRReq acknowledged  dev_eui=...dd001f23  dr=3  tx_power_index=0
```

Nach dem Neustart um 08:40 stand 108 auf DR0/DR1. Auf **DR3** verlor es
**16 %** seiner Meldungen (4 von 25), während Fühler 056 im selben Raum
bei 3,6 % lag und 027 an der Bar bei 0. Der Algorithmus **senkt die
Datenrate nie** — er findet also nicht zurück.

### Fühler 056 — Leistung weggenommen

Vierzehn Stunden stumm, `fCnt 2904 → 2988`, **83 verlorene Frames**, am
selben Platz:

| Datum | `tx_power_index` | ≈ Leistung |
|---|---|---|
| 06.11. | 6 | 4 dBm |
| 07.–12.11. | **7** | **2 dBm** ← hier riss der Link |
| 13.11. 06:44 | 1 | 14 dBm (Korrektur) |
| 13.11. 07:54 | 5 | 6 dBm (schon wieder abwärts) |

Nach der Korrektur: RSSI von −113 auf **−104 dBm**, SNR von −0,2 auf
**+8,2 dB**. Neun dB, allein aus der Leistung — und fünf Stufen in 70
Minuten zurück. **Der Ausfall wiederholt sich von selbst.**

Dass 056 zurückkam, war Zufall: um 04:44 kam **ein** Frame durch, und
erst der gab dem Algorithmus wieder einen Messpunkt.

## Zwei Plugins, und der Unterschied ist der Kern

| Datei | Profil | Datenrate | Leistung | nbTrans |
|---|---|---|---|---|
| `relais-feste-datenrate.js` | Relais 16ASPM | fest **DR1** | 0 (voll) | **2** |
| `vicki-feste-leistung.js` | Heizung — feste Leistung (Randlage) | **adaptiv** | 0 (voll) | 1 |

**Beim Relais** ist der Spreizfaktor der Hebel, und Sendezeit kostet
nichts — Netzspannung.

**Beim Batteriegerät** ist die **Leistung** der Hebel. 056 verlor mit
voller Leistung 3,6 %; eine feste niedrige Datenrate wäre zusätzliche
Sendezeit ohne belegten Nutzen, und `nbTrans 2` würde die Sendeenergie
verdoppeln. Deshalb bleibt `dr` unverändert durchgereicht — das ist der
einzige Unterschied im Code und der ganze Unterschied im Zweck.

### Warum DR1 und nicht DR0

| DR | SF | Gewinn gegen DR3 | Sendezeit (26 B, nbTrans 2) | Auslastung |
|---|---|---|---|---|
| DR2 | SF10 | +2,5 dB | 2 × 0,37 s | 0,12 % |
| **DR1** | **SF11** | **+5 dB** | **2 × 0,74 s** | **0,25 %** |
| DR0 | SF12 | +7,5 dB | 2 × 1,48 s | 0,49 % |

DR0 verbraucht die **halbe** Duty-Cycle-Grenze und lässt für Antworten
und Wiederholungen keinen Platz. DR1 liegt bei einem Viertel. DR0 bleibt
der Rückfall, falls DR1 noch verliert.

### Warum ein eigenes Profil für 056 und nicht „Heizung"

Ein Plugin wird je **Geräteprofil** zugewiesen. Es dem Profil „Heizung"
zu geben hieße, rund hundert Vickis gleichzeitig auf volle Leistung zu
stellen — eine Entscheidung über Batterielaufzeiten im ganzen Haus, die
ihre eigene Messung braucht (Pilotgruppe, eigener Vorschlag).

**Der Preis, und er steht als Pflichtliste im RUNBOOK:** ein Gerät in
einem Sonderprofil bekommt Änderungen am Profil „Heizung" **nicht** —
Uplink-Intervall, Class, Regionalparameter, **Codec**. Der Codec ist der
heikelste Punkt: er lebt im Geräteprofil (§5.22), und ein Codec-Update
in „Heizung" erreicht 056 nicht.

## Die Notlösung bis zum Rollout, und was sie nicht ist

Batterie an 056 raus und rein. Das Gerät tritt neu bei, und eine neue
Sitzung beginnt bei **voller Leistung**. Dreimal im Protokoll belegt:

```
01.11. 09:42  dd001e69  tx_power_index=0  dr=3   (vorher Index 3)
01.11. 10:52  dd001e69  tx_power_index=0  dr=3   (vorher Index 3)
11.11. 07:06  d30333fb  tx_power_index=0  dr=3   (nach Join 07:01)
```

**Es kauft etwa eine Stunde**, danach nimmt ADR die Leistung wieder weg.
Gefahrlos ist es nur, weil 056 und 027 `measure_only` und **nicht
montiert** sind — kein Ventil, keine Referenzfahrt.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Relais: Zieldatenrate zurück auf DR3 | **1 Test rot** |
| Relais: Wiederholungen auf 1 | **1 Test rot** |
| Vicki: Datenrate wird doch festgenagelt | **1 Test rot** |
| Vicki: Leistung auf die niedrigste Stufe | **1 Test rot** |
| Vicki: zwei Wiederholungen statt einer | **1 Test rot** |
| Vicki: dieselbe Kennung wie das Relais-Plugin | **2 Tests rot** |
| Init-Sidecar: Kopierzeile entfernt | **1 Test rot** |
| chirpstack.toml: Plugin nicht aufgelistet | **zuerst grün — Lücke, geschlossen** |

**Die letzte Probe war eine Lücke mit Lehrwert.** Der Test suchte den
**Dateinamen** im ganzen TOML — und der steht auch im Kommentar über der
Liste. Die Probe entfernte die Zeile aus der Liste und blieb grün: ein
Test, der den Kommentar liest, prüft die Absicht statt der Wirkung
(§5.55). Er liest jetzt nur noch den Bereich zwischen `adr_plugins = [`
und `]` und verlangt dort den vollen, in Anführungszeichen gesetzten
Pfad.

## Läufe

* `infra/chirpstack`: **59 Tests grün**, mit `node` ausgeführt — nicht
  gegen einen Python-Nachbau. Die Datei lädt als **Skript** (`eval`),
  genau wie ChirpStack sie lädt; ein `export` darin würde hier scheitern.
* `ruff check`, `ruff format --check`, `mypy` grün.
* Kein Backend- und kein Frontend-Code berührt.

## Zwei Doku-Korrekturen, die mit dazugehören

**§10au Schritt 3 empfahl den Schaden als Abhilfe.** Die
Entscheidungstabelle stand für beide Zeilen auf **DR3** — also auf genau
der Datenrate, auf der 108 am 12.11. 16 % verloren hat. Der Grund ist
derselbe wie beim Algorithmus: die Zahlen stammten von 109 **ohne Panel**
in der Dose, nicht von einem Relais unter Last. Jetzt DR2 bzw. DR1.

**Der Status-Eintrag vom 02.11.** trägt einen Überholt-Vermerk mit dem
Zeiger hierher. Er bleibt als Stand vom 02.11. stehen; ohne den Vermerk
wäre er die nächste §5.77-Stelle — ein Dokument, das „nicht ausgerollt,
DR3" sagt und wie ein Befund gelesen wird.

## Was offen bleibt

**Ob der Profilwechsel von 056 einen Neu-Beitritt auslöst, ist
geschlossen und nicht gemessen.** Eine Kopie des Profils mit genau einem
geänderten Feld sollte die Sitzung nicht verwerfen; belegt ist das nicht.
Die Laufliste prüft es am Frame-Zähler (Schritt 5) — läuft `fCnt` weiter,
war es kein Rejoin. Ein Rejoin wäre kein Schaden, nur eine andere Lage.

**Die 90 Geräte auf `tx_power_index 7` bleiben unberührt.** Der Pilot ist
ein eigener Vorschlag mit Batterierechnung; dieser PR behandelt nur das
Gerät, das nachweislich ausgefallen ist.
