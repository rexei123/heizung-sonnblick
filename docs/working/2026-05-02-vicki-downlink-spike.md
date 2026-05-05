# Spike: Vicki-Setpoint-Downlink Test

**Datum:** 2026-05-02
**Ziel:** Vor Sprint-9-Start verifizieren, dass ein Setpoint-Downlink von unserem Stack (mosquitto_pub -> ChirpStack -> UG65 -> Vicki) tatsaechlich am Vicki ankommt und das Display-Soll aendert.
**Aufwand:** ca. 30 Min vom User. Davon ca. 20 Min Warten auf Vicki-Uplink (Class A).
**Risiko falls fehlt:** Sprint 9 fertig gebauter Engine-Code aber Geraete reagieren nicht. Tagelange Hotfix-Spirale.

---

## Hintergrund (knapp)

Vicki ist **LoRaWAN Class A**: ein Downlink wird NUR nach einem Uplink des Geraets versendet. Vicki sendet im Default-Intervall (typisch 15-30 Min, konfigurierbar). Das bedeutet:

- Wir queuen den Downlink in ChirpStack ein.
- Beim naechsten Vicki-Uplink schickt ChirpStack den Downlink im RX1/RX2-Window.
- Vicki uebernimmt den Setpoint und sendet im naechsten Uplink den neuen Wert zurueck.

**Worst-Case-Wartezeit:** Default-Intervall (15-30 Min) + ein zweiter Uplink (15-30 Min) zur Verifikation = bis 60 Min.

**Best-Case:** wenn Vicki gerade vor dem Pub gesendet hat, kommt der Downlink im uebernaechsten Uplink an = ca. 15-30 Min.

---

## Quellen

- MClimate Vicki Setpoint-Command (FW >= 4.3): docs.mclimate.eu/.../target-setpoint-temperature
- Cheat-Sheet: docs.mclimate.eu/.../command-cheat-sheet
- ChirpStack v4 MQTT-Downlink: chirpstack.io/docs/chirpstack/integrations/mqtt.html

---

## Vicki-Command-Format

**Command 0x51 — Set Target Temperature (FW >= 4.3, 0.1 Grad Aufloesung)**

Drei Bytes Big-Endian:
- Byte 0: `0x51`
- Bytes 1-2: Temperatur * 10 als unsigned 16-bit big-endian

Beispiele:
| Temp Soll | Berechnung | Hex-Bytes |
|---|---|---|
| 19.0 | 190 = 0x00BE | `0x51 0x00 0xBE` |
| 20.0 | 200 = 0x00C8 | `0x51 0x00 0xC8` |
| 21.5 | 215 = 0x00D7 | `0x51 0x00 0xD7` |
| 22.0 | 220 = 0x00DC | `0x51 0x00 0xDC` |

Base64-Encoding (fuer ChirpStack-MQTT-Payload):
| Hex | Base64 |
|---|---|
| `5100BE` | `UQC+` |
| `5100C8` | `UQDI` |
| `5100D7` | `UQDX` |
| `5100DC` | `UQDc` |

**Fallback Command 0x0E** (FW < 4.3, nur ganze Grad — sollte bei aktuellen Vicki nicht noetig sein):
- 2 Bytes: `0x0E <temp_celsius_unsigned_8bit>` z.B. `0x0E 0x14` fuer 20°C
- Base64: `0E14` -> `DhQ=`

---

## Spike-Plan (drei Phasen)

### Phase 1 — Vorbereitung im ChirpStack-UI (User, 5 Min)

1. Login `https://cs-test.hoteltec.at` (Admin-PW aus deiner Notiz).
2. Tenant "Hotel Sonnblick" -> Application "heizung" -> Devices.
3. **Application-ID notieren** (URL der Application enthaelt UUID, z.B. `https://cs-test.hoteltec.at/#/tenants/.../applications/abc12345-...`). Die UUID ist die Application-ID.
4. Vicki-001 (DevEUI `70b3d52dd3034de4`) auswaehlen -> Tab "LoRaWAN frames".
5. Notieren: letzte Uplink-Zeit. Damit kannst du abschaetzen, wann der naechste Uplink kommt.

### Phase 2 — Downlink einqueuen (User, SSH heizung-test)

**SSH-Terminal (heizung-test, root):**

Variable setzen — `<APP_ID>` aus Phase 1 ersetzen:

```bash
APP_ID="<APP_ID-UUID-AUS-CHIRPSTACK-URL-EINFUEGEN>"
DEV_EUI="70b3d52dd3034de4"
TARGET_TEMP_C="20.0"
```

Pre-Check: Mosquitto erreichbar?

```bash
docker exec heizung-sonnblick-mosquitto-1 mosquitto_pub \
  -h 127.0.0.1 -p 1883 \
  -t "test/spike-precheck" \
  -m "ping" \
  -d
# Erwartet: "Client null sending CONNECT" und "PUBLISH" ohne Fehler
```

Downlink einqueuen — Setpoint **20.0 Grad**:

```bash
docker exec heizung-sonnblick-mosquitto-1 mosquitto_pub \
  -h 127.0.0.1 -p 1883 \
  -t "application/${APP_ID}/device/${DEV_EUI}/command/down" \
  -m '{"devEui":"'"${DEV_EUI}"'","confirmed":true,"fPort":1,"data":"UQDI"}' \
  -d
```

(Base64 `UQDI` = Hex `5100C8` = Command 0x51, Wert 200, also 20.0 Grad.)

ChirpStack-UI gegenpruefen — im Vicki-001-Tab "Queue" sollte der Downlink jetzt sichtbar sein.

### Phase 3 — Warten + Verifikation (User, ca. 15-60 Min)

Beobachten in ChirpStack-UI Tab "LoRaWAN frames":

1. Naechster Uplink kommt (wann auch immer das normale Vicki-Intervall faellt).
2. Direkt danach sollte ein Downlink im Frame-Log auftauchen — im selben Slot oder kurz danach.
3. Der **uebernaechste Vicki-Uplink** sollte den neuen Setpoint von 20.0 enthalten.
4. **Vicki-Display am Heizkoerper:** Soll-Anzeige aendert sich auf 20.0.

Im Frontend pruefen:
```
https://heizung-test.hoteltec.at/devices/<vicki-001-id>
```
Setpoint-KPI-Card sollte 20.0 zeigen (zwei Uplinks nach dem Spike-Pub).

---

## Erfolgs-Kriterien

- [ ] Mosquitto-Pre-Check (Phase 2) gibt keinen Fehler.
- [ ] ChirpStack-UI zeigt Downlink in Queue.
- [ ] Im LoRaWAN-frames-Log erscheint ein Downlink-Eintrag.
- [ ] Naechster Vicki-Uplink (im uebernaechsten Slot) zeigt Setpoint 20.0.
- [ ] Vicki-Display zeigt 20.0.
- [ ] Frontend `/devices/<id>` zeigt Setpoint 20.0.

Wenn alle 6 Punkte gruen: **Spike erfolgreich, Sprint 9 kann mit Engine-Bau starten.**

---

## Fehlerbilder + Reaktion

### Fall A: ChirpStack-Queue zeigt Downlink, aber kein Frame-Eintrag

Vicki hat keinen Uplink gesendet -> wir warten weiter. Vicki-Default-Intervall ist 15-30 Min.

Nach 60 Min ohne Uplink: Vicki ist offline. Pruefen via:
```bash
docker exec heizung-sonnblick-mosquitto-1 mosquitto_sub \
  -h 127.0.0.1 -p 1883 \
  -t "application/${APP_ID}/device/${DEV_EUI}/event/up" \
  -v
```
Wenn nichts kommt -> Vicki ist offline. Reset-Knopf am Vicki druecken (3 Sek).

### Fall B: Downlink im Frame-Log, aber Vicki-Display aendert sich nicht

Vicki hat den Downlink empfangen, aber Command nicht akzeptiert. Moegliche Ursachen:

1. **fPort falsch:** Andere Vicki-Versionen wollen fPort 10 statt 1. Test wiederholen mit `"fPort":10`.
2. **Command 0x51 nicht unterstuetzt:** Vicki-FW < 4.3. Fallback Command 0x0E:
   ```bash
   docker exec heizung-sonnblick-mosquitto-1 mosquitto_pub \
     -h 127.0.0.1 -p 1883 \
     -t "application/${APP_ID}/device/${DEV_EUI}/command/down" \
     -m '{"devEui":"'"${DEV_EUI}"'","confirmed":true,"fPort":1,"data":"DhQ="}' \
     -d
   ```
   (`DhQ=` = `0E14` = Command 0x0E, Temperatur 20 als ein Byte = 0x14.)
3. **Vicki im Operational Mode 1 oder 2 (nicht 0):** Vicki muss im "Online Mode" mit Cloud-Steuerung sein. Pruefen via Vicki-Display oder letztes Uplink-Payload.

### Fall C: Mosquitto-Pre-Check schlaegt fehl

```
Connection error: Connection refused
```
Mosquitto-Container down. `docker compose ps` pruefen, ggf. `docker compose up -d mosquitto`.

### Fall D: ChirpStack-UI zeigt "Queue empty" obwohl mosquitto_pub erfolgreich

ChirpStack-MQTT-Subscription kollidiert oder Topic falsch. Pruefen:

```bash
docker exec heizung-sonnblick-mosquitto-1 mosquitto_sub \
  -h 127.0.0.1 -p 1883 \
  -t "application/+/device/+/command/down" \
  -v
```

Dann Pub erneut. Wenn der Sub-Echo den Command zeigt aber ChirpStack-Queue leer bleibt: ChirpStack-MQTT-Integration nicht aktiv. ChirpStack-UI -> Application -> "Integrations" -> MQTT muss "enabled" sein.

---

## Was tun nach Spike-Resultat

### Erfolg

User meldet "Spike OK, Setpoint 20.0 angekommen". Claude:
1. CONTEXT.md aktualisieren: Vicki-Downlink verifiziert.
2. Sprint 9 kann starten — Engine-Code mit gleichem MQTT-Pattern + base64-Encoding der 3 Bytes.
3. Im Sprint-9-Code wird der Code als Helper modularisiert: `encode_setpoint_command(temp_c: Decimal) -> bytes`.

### Fehler im Fall A (Vicki offline)

Hardware-Aktion noetig. Kein Software-Bug. Wir notieren und gehen Sprint 8 trotzdem weiter (Sprint 8 braucht Downlink nicht).

### Fehler im Fall B (Vicki nimmt nicht an)

Sprint-9-Plan anpassen:
- Codec-Erweiterung um `encodeDownlink` Funktion in der ChirpStack-DeviceProfile-JS-Codec-Datei.
- Explizite fPort-Tests (1, 10, 32).
- Operational-Mode-Check vor jedem Downlink.

Spike-Aufwand: +1-2 h, aber wir machen das in Sprint 9.0 (vor Engine-Code), nicht erst spaet.

### Fehler im Fall C/D (Infra)

Sprint 8 ist nicht betroffen. Aber bevor Sprint 9 startet, muss Mosquitto-Setup repariert werden. Eigene Mini-Sprint-Aufgabe.

---

## Was Claude waehrend des Wartens parallel macht

User sagt "Spike laeuft, warte auf Uplink." -> Claude beginnt mit Sprint 8.1 (Migration 0003a) auf Branch `feat/sprint8-stammdaten-belegung`. Sprint 8 ist vom Spike-Resultat unabhaengig.

User sagt "Spike OK." -> Claude bestaetigt und arbeitet weiter an Sprint 8 (oder beginnt parallel mit Sprint-9-Vorbereitung wenn Sprint 8 schon weit ist).

User sagt "Spike Fehler Fall X" -> Claude analysiert + schlaegt naechste Schritte vor + aktualisiert Sprint-9-Plan.

---

*Spike-Doku Ende. User-Action: Phase 1+2+3 ausfuehren, Resultat melden.*
