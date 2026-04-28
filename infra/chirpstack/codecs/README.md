# LoRaWAN-Decoder (JavaScript-Codecs)

Codecs werden in ChirpStack-DeviceProfiles per JS-Runtime ausgeführt. Sie wandeln binäre Vicki/Sensor-Payloads in dekodiertes JSON.

## Konvention

- Eine Datei pro Geräte-Typ: `<vendor>-<model>-v<X>.js`
- Header-Kommentar enthält:
  - Source-URL des Hersteller-Repos
  - Commit-SHA der Quelldatei
  - Datum des Imports
- Funktionen `decodeUplink(input)` und optional `encodeDownlink(input)` nach LoRaWAN-Codec-API: https://github.com/TheThingsNetwork/lorawan-devices#payload-codecs

## Vorhanden

- `mclimate-vicki.js` — MClimate Vicki Heizkörperthermostat (TODO: in Sprint 5.4 importieren)

## Import-Skript

Das Bootstrap-Skript `infra/chirpstack/bootstrap.py` lädt die Codec-Datei und setzt sie via ChirpStack-API ins DeviceProfile. Bei Codec-Update muss das Skript erneut ausgeführt werden.
