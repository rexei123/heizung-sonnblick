# Test-Uplinks (Mock-Frames für lokale Entwicklung)

Sprint 5 nutzt diese JSON-Files, um ChirpStack-Application-Uplinks zu fingieren ohne echte Hardware. Die Frames werden direkt aufs Application-MQTT-Topic publiziert; ChirpStack ist dabei kein Decoder im Loop. Echte End-to-End-Validierung mit Codec + Gateway-Frames kommt in Sprint 6 mit echter Hardware.

## Format

ChirpStack v4 publiziert decoded Uplinks als JSON auf `application/{app-id}/device/{dev-eui}/event/up`. Felder:

- `deviceInfo` — Tenant/App/Device-Metadaten (UUIDs)
- `data` — Base64 der raw Bytes (informativ, FastAPI nutzt `object`)
- `object` — vom JS-Codec dekodierte Werte
- `fCnt`, `fPort` — LoRaWAN-Frame-Metadaten
- `rxInfo[]` — Gateway-Empfangsinfo (RSSI, SNR)
- `txInfo` — Modulation, Frequenz

## Vorhandene Files

- `vicki-status-001.json` — typischer Vicki-Status-Frame, fCnt 1, decoded Object enthält Battery 3.9 V, Temperatur 24 degC, Target 21.0 degC, Motor 100 %.

## Verwendung

```powershell
docker run --rm --network heizung-sonnblick_default `
  -v "${PWD}/infra/chirpstack/test-uplinks:/data:ro" `
  eclipse-mosquitto:2 `
  mosquitto_pub -h mosquitto -p 1883 `
    -t "application/13ca59f4-a3da-447d-82cc-9b8ea3289ee7/device/0011223344556677/event/up" `
    -f /data/vicki-status-001.json
```

## Parallel mitlauschen

```powershell
docker compose exec mosquitto mosquitto_sub -h localhost -p 1883 -t 'application/#' -v
```
