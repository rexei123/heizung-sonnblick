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
// === Uplinks ===
//
// fPort 1 (Periodic Status Reports)
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
// fPort 2 (Command Replies)
//   Byte 0  : Reply-Command-Code, z.B. 0x52 = Setpoint-Reply
//   Byte 1+2 (fuer 0x52): bestaetigter Setpoint * 10, Big-Endian
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
    var fPort = input.fPort;

    if (!bytes) {
        return { data: {}, errors: ['empty payload'] };
    }

    if (fPort === 2) {
        return decodeCommandReply(bytes);
    }

    // Default: fPort 1 (Periodic Status Report). Auch wenn fPort fehlt
    // (manche Test-Tools senden ohne fPort) versuchen wir Periodic.
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

    errors.push('no actionable downlink fields in input.data');
    return { bytes: [], fPort: 1, errors: errors };
}
