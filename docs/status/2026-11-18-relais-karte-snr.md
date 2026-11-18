---
datum: 2026-11-18
thema: Der Stand des Relais war nicht abrufbar — ein Decimal als String
pr: offen
---

# Die Relais-Karte ist zurück

**Keine Migration, kein Funkbefehl, keine Server-Änderung.** Ein
Serializer im Backend, ein toleranter Spiegel im Frontend, drei Tests,
die vorher geschwiegen haben.

## Das Fehlerbild

Auf `/devices/109` und `/devices/110` stand in Rot: **„Der Stand des
Relais ist nicht abrufbar."** Nicht ein Wert fehlte — die ganze Karte
war weg, mitsamt Schaltzustand, Sperrgrund, Wächter-Zeile und allen
vier Handgriffen. Alles andere auf der Seite (Paketverlust, Historie,
Verlauf der Heizzone) stand normal da.

## Der Befund, gemessen

Im Browser auf der Produktion, 18.11.2026 07:20:

```
GET /api/v1/devices/109/relay   ->  200
"snr_db":  "-8.0"        (String)
"rssi_dbm": -105         (Zahl)
```

Also: **kein 500, kein 401, keine falsche Route, keine Mock-Reste.** Die
Antwort war vollständig und richtig — nur hatte ein Feld den falschen
JSON-**Typ**.

`RelaisStand.snr_db` ist im Backend ein `Decimal` und stand nicht im
`field_serializer` des Modells. Pydantic schreibt ein `Decimal` ohne
Eintrag als String. Der Zod-Spiegel verlangte `z.number()`, `parse`
warf, und TanStack Query zeigte den Fehler-Zustand der Karte.

**Warum erst jetzt.** Das Feld kam am 16.11. dazu (Migration 0041).
Solange die Relais keine `rxInfo` lieferten, war es `null` — und `null`
passt in jeden Spiegel. Der Defekt lag fertig da und wartete auf den
ersten echten Wert; sichtbar wurde er mit dem Deploy von heute früh, der
den neuen Spiegel auf die inzwischen gefüllten Daten setzte. Nicht
#431–#433: die drei haben die Stelle nicht angefasst.

## Warum drei Wachposten geschwiegen haben

| Posten | Warum er nichts sah |
|---|---|
| `test_decimal_serialisierung.py` | prüft genau das — aber über eine **handgepflegte Modell-Liste**, und `RelaisStand` stand nicht darin |
| `test_api_relays.py` | `assert Decimal(str(koerper["snr_db"])) == …` — das `str()` nimmt Zahl **und** String; eine Zusicherung, die den Typ wegkonvertiert, prüft ihn nicht |
| `sprint24b-relais-karte.spec.ts` | Mock trug `snr_db: null` — meine Annahme über die Antwort, nicht ihre Gestalt |

Der Kopf von `test_decimal_serialisierung.py` warnt vor genau dieser
Falle **für Felder** und ist ihr auf der Ebene der **Modelle** erlegen.
Dieselbe Mechanik hat am 07.10.2026 die Geräteliste abgeschossen
(`a.toFixed is not a function`, siehe `lib/api/zahlen.ts`).

## Was geändert ist

| Stelle | Änderung |
|---|---|
| `api/v1/relays.py` | `field_serializer` für `RelaisStand.snr_db` **und** für die vier Decimals von `VerlaufStunde`/`VerlaufTag` — die ganze Relais-API schickt Decimals jetzt als Zahl |
| `test_decimal_serialisierung.py` | die drei Relais-Modelle eingetragen; neuer Test liest die Modelle **aus dem Modul** und verlangt den Eintrag — ein viertes Modell mit einer Temperatur macht ihn rot |
| `test_api_relays.py` | `isinstance(…, int \| float)` statt `Decimal(str(…))` |
| `test_relais_verlauf.py` | `== "20.00"` → `pytest.approx(20.0)` plus Typ-Prüfung |
| `lib/api/zahlen.ts` | `dezimalFeld` — der Zod-Helfer, der beides annimmt, zieht aus `relais-verlauf.ts` hierher, wo die Begründung seit dem 07.10. steht |
| `lib/api/relays.ts` | `snr_db: dezimalFeld` als zweite Linie |
| `sprint24b-relais-karte.spec.ts` | `STAND_MIT_FUNK` mit echten Empfangsdaten; zwei Tests — SNR als Zahl und als Zeichenkette, beide zeigen `-105 dBm · -8.0 dB` |

## Mutationsproben

| Probe | Erwartet | Ergebnis |
|---|---|---|
| `field_serializer` in `RelaisStand` entfernt | `test_decimal_feld_serialisiert_als_zahl[RelaisStand.snr_db]` rot | rot |
| `RelaisStand` aus `MODELLE` entfernt | `test_jedes_decimal_modell_der_relais_api_ist_eingetragen` rot | rot |
| `dezimalFeld` zurück auf `z.number()` | Playwright „ein SNR als Zeichenkette" rot | rot |

## Was offen bleibt

Sechs weitere Antwort-Modelle schicken ihre `Decimal`-Felder noch als
String (`EventLogRead`, `ManualOverrideResponse`, `RoomTypeRead`,
`SollwertUebernahme`, `WirksamkeitFeld`, `RuleConfigGlobalRead`). Ihre
Leser kommen damit zurecht, geprüft ist keiner. Sie umzustellen heißt,
sechs Spiegel nachzulesen — eigener PR, steht auf der Liste. Der neue
Test deckt deshalb heute nur `api/v1/relays.py` ab und sagt das in
seinem Docstring.

**Lehre:** CLAUDE.md §5.93.
