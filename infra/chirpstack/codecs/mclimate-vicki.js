// MClimate Vicki TRV — LoRaWAN Payload Codec (strict-mode-safe)
//
// Sprint 6.8 (2026-05-01): Eigene minimal-Implementierung statt
// offizieller MClimate-Codec, weil dieser globale Variablen ohne
// `var` deklariert (toBool, tmp, motorRange1, ...). Die ChirpStack-
// Goja-JS-Engine laeuft im strict-mode und wirft ReferenceError ->
// kein `object`-Feld im MQTT-Event.
//
// Sprint 9.0 (2026-05-03): fPort-Distinction + Setpoint-Reply (0x52
// auf fPort 2) + Encode auf Command 0x51 (statt 0x02) + valveOpenness
// auf [0,100] geclampt (Bug Task #86).
//
// Sprint 9.10c (2026-05-07): Cmd-Byte-Routing statt fPort-Routing.
// Live-Daten zeigen, dass Vickis Periodic-Reports auch auf fPort 2
// senden (Annahme aus 9.0 war falsch, siehe CLAUDE.md §5.21). Der
// Command-Byte (bytes[0]) ist die einzige verlaessliche Quelle:
//   0x52  -> Setpoint-Reply (decodeCommandReply)
//   0x04  -> FW-Query-Reply (Sprint 9.11x.b, decodeCommandReply)
//   0x46  -> Open-Window-Status-Reply (Sprint 9.11x.b, decodeCommandReply)
//   sonst -> Periodic Status Report (decodePeriodicReport)
// fPort wird damit redundant fuer das Routing.
//
// Sprint 9.11x.b (2026-05-10): Drei neue Downlinks gemaess AE-48:
//   0x04        -> FW-Query (Antwort siehe 9.11x.c-Korrektur unten)
//   0x4501020F  -> Open-Window-Detection an (Vendor-Bytes, FW>=4.2)
//   0x46        -> Open-Window-Detection-Status abfragen
// Vendor-Doku: docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md.
// Backend-Helper-Architektur (Spiegel) in
// backend/src/heizung/services/downlink_adapter.py — Drift-Schutz via
// pytest-Spiegel-Test (siehe backend/tests/test_codec_mirror.py).
//
// Sprint 9.11x.c (2026-05-11): 0x04-Reply-Decoder-Fix nach Live-Recon.
//   Reply ist 3 Bytes Nibble-Split, NICHT 5 Bytes wie Vendor-Doku
//   ungenau angab. Plus Vicki packt Reply + Keep-alive im selben
//   Uplink-Frame — Rest wird mit-dekodiert und in dasselbe data-Object
//   gemergt; Reply-Felder (report_type, command) priorisieren bei
//   Konflikt. Bytes-Beleg: 04 26 44 81 14 97 62 a2 a2 11 e0 30
//   (Vicki-001, 2026-05-11).
//
// === Uplinks ===
//
// Periodic Status Report (Cmd 0x01 = v1 / 0x81 = v2; fPort 1 oder 2)
//   Byte 0  : Command-Code (0x01 = v1, 0x81 = v2)
//   Byte 1  : Target Temperature (uint8, direkt in degC)
//   Byte 2  : Sensor Temperature
//             cmd=0x01: (B2 * 165) / 256 - 40
//             cmd=0x81: (B2 - 28.33333) / 5.66666
//   Byte 3  : Relative Humidity (% = B3 * 100 / 256)
//   Byte 4  : Motor Position low byte
//   Byte 5  : Motor Range low byte
//   Byte 6  : High nibble = motor_pos high, Low nibble = motor_range high
//   Byte 7  : High nibble = battery (V = 2 + nibble * 0.1), Low nibble = status flags
//   Byte 8  : Erweiterte Status-Flags
//
// Setpoint-Reply (Cmd 0x52; typisch fPort 2)
//   Byte 0  : 0x52 = Setpoint-Reply
//   Byte 1+2: bestaetigter Setpoint * 10, Big-Endian
//
// === Downlinks ===
//
// fPort 1 (Setpoint setzen via Command 0x51)
//   Byte 0  : 0x51
//   Byte 1+2: Setpoint * 10, Big-Endian uint16
//
// Quelle: https://github.com/mclimate/lorawan-devices/blob/master/vendor/mclimate/vicki.js
// (offizieller Decoder; hier strict-mode-konform reduziert; Spike 2026-05-02
// hat Command 0x51 + 0x52 Format am realen Vicki validiert.)

function decodeUplink(input) {
    var bytes = input.bytes;

    if (!bytes || bytes.length === 0) {
        return { data: {}, errors: ['empty payload'] };
    }

    // Sprint 9.10c: Routing ueber Command-Byte, nicht ueber fPort.
    // Vickis schicken Periodic-Reports auf fPort 2 (Live-Beleg
    // 2026-05-07: dev_eui 70b3d52dd3034de4, fPort=2, bytes[0]=0x81).
    var cmd = bytes[0];
    if (cmd === 0x52 || cmd === 0x04 || cmd === 0x46) {
        return decodeCommandReply(bytes);
    }
    return decodePeriodicReport(bytes);
}

function decodePeriodicReport(bytes) {
    var data = {};

    if (bytes.length < 9) {
        return {
            data: {},
            errors: ['periodic report too short (' + bytes.length + ' bytes, expected 9+)']
        };
    }

    var cmd = bytes[0];
    if (cmd !== 0x01 && cmd !== 0x81) {
        return {
            data: { command: cmd },
            warnings: ['unknown periodic report command 0x' + cmd.toString(16)]
        };
    }

    // Sensor Temperature (Formel haengt vom Command-Code ab)
    var sensorTemp;
    if (cmd === 0x01) {
        sensorTemp = (bytes[2] * 165) / 256 - 40;
    } else {
        sensorTemp = (bytes[2] - 28.33333) / 5.66666;
    }

    // Motor Range / Position (packed in bytes 4-6 mit Half-Byte-Aufteilung)
    var byte6 = bytes[6];
    var motorRangeHigh = byte6 & 0x0f;
    var motorPosHigh = (byte6 >> 4) & 0x0f;
    var motorRange = (motorRangeHigh << 8) | bytes[5];
    var motorPosition = (motorPosHigh << 8) | bytes[4];

    // Battery (high nibble von byte 7)
    var batteryNibble = (bytes[7] >> 4) & 0x0f;
    var batteryVoltage = 2 + batteryNibble * 0.1;

    // Status-Flags (low nibble byte 7 + byte 8)
    var status7 = bytes[7] & 0x0f;
    var status8 = bytes[8];

    // Valve Openness 0..100 % — Bug Task #86: Vicki kann motorPosition
    // groesser als motorRange melden (z.B. 7102 vs 5400). Ohne Clamp
    // wird der Prozentwert negativ und float, was die Persistenz-Schicht
    // (sensor_reading.valve_position als smallint) ueberlauft.
    var valveOpenness = 0;
    if (motorRange > 0) {
        valveOpenness = Math.round((1 - motorPosition / motorRange) * 100);
        if (valveOpenness < 0) valveOpenness = 0;
        if (valveOpenness > 100) valveOpenness = 100;
    }

    // snake_case fuer FastAPI-Subscriber
    data.report_type = 'periodic';
    data.temperature = parseFloat(sensorTemp.toFixed(2));
    data.target_temperature = bytes[1];
    data.battery_voltage = parseFloat(batteryVoltage.toFixed(2));
    data.motor_position = motorPosition;
    data.motor_range = motorRange;
    data.valve_openness = valveOpenness;

    // camelCase fuer ChirpStack-UI-Anzeige
    data.sensorTemperature = data.temperature;
    data.targetTemperature = data.target_temperature;
    data.batteryVoltage = data.battery_voltage;
    data.motorPosition = data.motor_position;
    data.motorRange = data.motor_range;
    data.relativeHumidity = parseFloat((bytes[3] * 100 / 256).toFixed(2));
    data.valveOpenness = valveOpenness;
    data.command = cmd;

    // Status-Flags (Bit-Layout aus offiziellem Decoder)
    data.openWindow = (status7 & 0x08) !== 0;
    data.highMotorConsumption = (status7 & 0x04) !== 0;
    data.lowMotorConsumption = (status7 & 0x02) !== 0;
    data.brokenSensor = (status7 & 0x01) !== 0;
    data.childLock = (status8 & 0x80) !== 0;
    data.calibrationFailed = (status8 & 0x40) !== 0;
    data.attachedBackplate = (status8 & 0x20) !== 0;
    data.perceiveAsOnline = (status8 & 0x10) !== 0;
    data.antiFreezeProtection = (status8 & 0x08) !== 0;

    return { data: data };
}

function decodeCommandReply(bytes) {
    if (bytes.length < 1) {
        return { data: {}, errors: ['command reply empty'] };
    }

    var cmd = bytes[0];

    // 0x52 = Setpoint-Reply (Vicki-Antwort auf 0x51-Downlink oder Drehring-Drehung)
    // Format: [0x52, setpoint*10 high, setpoint*10 low]
    if (cmd === 0x52) {
        if (bytes.length < 3) {
            return {
                data: { command: cmd, report_type: 'setpoint_reply' },
                errors: ['setpoint reply too short (' + bytes.length + ' bytes, expected 3)']
            };
        }
        var raw = (bytes[1] << 8) | bytes[2];
        var setpoint = raw / 10.0;
        return {
            data: {
                report_type: 'setpoint_reply',
                command: cmd,
                target_temperature: parseFloat(setpoint.toFixed(2)),
                targetTemperature: parseFloat(setpoint.toFixed(2)),
                acknowledged: true
            }
        };
    }

    // 0x04 = FW-Query-Reply (Sprint 9.11x.b, korrigiert in 9.11x.c).
    // Echtes Vicki-Layout (Live-Recon 2026-05-11, Bytes
    // `04 26 44 81 14 97 62 a2 a2 11 e0 30` von Vicki-001):
    //   Byte 0: 0x04 (Reply-Cmd)
    //   Byte 1: HW-Version, high-nibble=major, low-nibble=minor
    //           (0x26 -> HW 2.6)
    //   Byte 2: FW-Version, high-nibble=major, low-nibble=minor
    //           (0x44 -> FW 4.4)
    //   Byte 3+: optional eingebetteter Keep-alive-Frame (Cmd 0x81),
    //           wird hier mit-dekodiert und gemergt; Reply-Felder
    //           priorisieren bei Konflikt (report_type, command).
    //
    // Vendor-Doku §5 "0x04{HW_major}{HW_minor}{FW_major}{FW_minor}"
    // meinte Nibbles, nicht Bytes — Quelle ist ungenau, korrigiert in
    // docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md §1.
    if (cmd === 0x04) {
        if (bytes.length < 3) {
            return {
                data: { command: cmd, report_type: 'firmware_version_reply' },
                errors: ['fw-query reply too short (' + bytes.length + ' bytes, expected 3+)']
            };
        }
        var hwByte = bytes[1];
        var fwByte = bytes[2];
        var data = {
            report_type: 'firmware_version_reply',
            command: cmd,
            firmware_version: ((fwByte >> 4) & 0x0F) + '.' + (fwByte & 0x0F),
            hw_version: ((hwByte >> 4) & 0x0F) + '.' + (hwByte & 0x0F)
        };
        // Optional eingebetteter Keep-alive (Cmd 0x01 oder 0x81, 9 Bytes).
        // Vicki packt FW-Reply + Periodic im selben Uplink-Frame —
        // wir wollen die Periodic-Felder nicht verlieren, aber
        // report_type=firmware_version_reply MUSS bleiben, sonst
        // greift REPLY_REPORT_TYPES-Filter im Subscriber nicht und
        // _persist_uplink wuerde fuer den Reply einen sensor_reading-
        // Insert versuchen (CLAUDE.md §5.21-Pattern-Risiko).
        if (bytes.length > 3) {
            var rest = bytes.slice(3);
            if (rest.length >= 9 && (rest[0] === 0x01 || rest[0] === 0x81)) {
                var periodic = decodePeriodicReport(rest);
                if (periodic && periodic.data) {
                    for (var key in periodic.data) {
                        if (Object.prototype.hasOwnProperty.call(periodic.data, key)
                            && !Object.prototype.hasOwnProperty.call(data, key)) {
                            data[key] = periodic.data[key];
                        }
                    }
                }
            }
        }
        return { data: data };
    }

    // 0x46 = Open-Window-Status-Reply (Sprint 9.11x.b)
    // Vendor-Format: [0x46, enabled, duration_byte, delta_byte]
    //   duration_min = duration_byte * 5
    //   delta_c       = delta_byte / 10
    if (cmd === 0x46) {
        if (bytes.length < 4) {
            return {
                data: { command: cmd, report_type: 'open_window_status_reply' },
                errors: ['open-window status reply too short (' + bytes.length + ' bytes, expected 4)']
            };
        }
        var enabled = bytes[1] === 0x01;
        var durationMin = bytes[2] * 5;
        var deltaC = bytes[3] / 10.0;
        return {
            data: {
                report_type: 'open_window_status_reply',
                command: cmd,
                open_window_detection_enabled: enabled,
                open_window_detection_duration_min: durationMin,
                open_window_detection_delta_c: parseFloat(deltaC.toFixed(2))
            }
        };
    }

    return {
        data: { command: cmd, report_type: 'unknown_reply' },
        warnings: ['unknown command-reply 0x' + cmd.toString(16)]
    };
}

function encodeDownlink(input) {
    var data = input.data || {};
    var errors = [];

    if (typeof data.target_temperature === 'number') {
        var setpoint = data.target_temperature;
        if (setpoint < 5 || setpoint > 30) {
            errors.push('target_temperature out of range (5..30 degC)');
            return { bytes: [], fPort: 1, errors: errors };
        }
        // Command 0x51 + 16-bit BE Setpoint*10 (Spike 2026-05-02 validiert).
        var raw = Math.round(setpoint * 10);
        var hi = (raw >> 8) & 0xff;
        var lo = raw & 0xff;
        return { bytes: [0x51, hi, lo], fPort: 1, errors: errors };
    }

    if (data.force_window_redetect === true) {
        return { bytes: [0x05], fPort: 1, errors: errors };
    }

    // Sprint 9.11x.b — drei neue Commands (AE-48). Spiegel zum Backend-
    // Helper backend/src/heizung/services/downlink_adapter.py. Drift-
    // Schutz via tests/test_codec_mirror.py (hardcoded Erwartungs-Bytes).

    // 0x04 — Firmware-Version abfragen.
    if (data.query_firmware_version === true) {
        return { bytes: [0x04], fPort: 1, errors: errors };
    }

    // 0x45 — Open-Window-Detection setzen (FW>=4.2, 0.1 °C-Resolution).
    // Vendor-Format: [0x45, enabled, duration_min/5, delta_c*10].
    if (typeof data.set_open_window_detection === 'object' && data.set_open_window_detection !== null) {
        var owSet = data.set_open_window_detection;
        var enabled = owSet.enabled === true;
        var durationMin = owSet.duration_min;
        var deltaC = owSet.delta_c;
        if (typeof durationMin !== 'number' || durationMin < 5 || durationMin > 1275 || durationMin % 5 !== 0) {
            errors.push('duration_min muss 5..1275 in 5-Min-Schritten sein');
            return { bytes: [], fPort: 1, errors: errors };
        }
        if (typeof deltaC !== 'number' || deltaC < 0.1 || deltaC > 6.4) {
            errors.push('delta_c muss 0.1..6.4 °C sein');
            return { bytes: [], fPort: 1, errors: errors };
        }
        var enabledByte = enabled ? 0x01 : 0x00;
        var durationByte = Math.floor(durationMin / 5);
        var deltaByte = Math.round(deltaC * 10);
        return { bytes: [0x45, enabledByte, durationByte, deltaByte], fPort: 1, errors: errors };
    }

    // 0x46 — Open-Window-Detection-Status abfragen.
    if (data.get_open_window_detection === true) {
        return { bytes: [0x46], fPort: 1, errors: errors };
    }

    errors.push('no actionable downlink fields in input.data');
    return { bytes: [], fPort: 1, errors: errors };
}
