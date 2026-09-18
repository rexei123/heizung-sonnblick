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

## Import-Weg

**Korrektur Sprint 17 (C1):** Ein Skript `infra/chirpstack/bootstrap.py`
existiert nicht und hat nie existiert — der Sprint-5-Plan hatte es
vorgesehen, geliefert wurde es nie. Der Eintrag hier hat vier Sprints lang
einen automatischen Import behauptet, den es nicht gab (CLAUDE.md §5.20,
aspirative Doku).

**Wie der Codec tatsächlich nach ChirpStack kommt:** manueller Re-Paste im
ChirpStack-UI, Schritt für Schritt in RUNBOOK §10c. Jeder Repo-Touch an
`mclimate-vicki.js` erfordert diesen Schritt erneut — ChirpStack zieht die
Datei nicht selbst (CLAUDE.md §5.22).

**Was es seit Sprint 17 gibt:** `infra/chirpstack/provision_devices.py` legt
*Geräte* per gRPC an. Der *Codec* ist dort bewusst nicht enthalten — das
bleibt B-9.10c-1 (`UpdateDeviceProfile` mit `payload_codec_script`). Das
Provisioning-Skript bringt die Anbindung mit, an der ein Codec-Deploy später
andocken kann.
