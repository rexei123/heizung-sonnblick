// MClimate Vicki TRV — LoRaWAN Payload Codec (strict-mode-safe)
//
// Sprint 6.8 (2026-05-01): Eigene minimal-Implementierung statt
// offizieller MClimate-Codec, weil dieser globale Variablen ohne
// `var` deklariert (toBool, tmp, motorRange1, ...). Die ChirpStack-
// Goja-JS-Engine laeuft im strict-mode und wirft ReferenceError ->
// kein `object`-Feld im MQTT-Event.
//
// Quelle: https://github.com/mclimate/lorawan-devices/blob/master/vendor/mclimate/vicki.js
// (offizieller Decoder; hier strict-mode-konform reduziert auf
//  Periodic Reporting v1/v2 aka Command 0x01 / 0x81).
//
// Eingehende Payload (fPort 2, Standard-Status-Report):
//   Byte 0  : Command-Code (0x01 = v1, 0x81 = v2)
//   Byte 1  : Target Temperature (uint8, direkt in degC)
//   Byte 2  : Sensor Temperature
//             cmd=0x01: (B2 * 165) / 256 - 40
//             cmd=0x81: (B2 - 28.33333) / 5.66666
//   Byte 3  : Relative Humidity (% = B3 * 100 / 256)
//   Byte 4  : Motor Position low byte
//   Byte 5  : Motor Range low byte
//   Byte 6  : High nibble = motor_pos high, Low nibble = motor_range high
//   Byte 7  : High nibble = battery (V = 2 + tmp * 0.1), Low nibble = status flags
//   Byte 8  : Erweiterte Status-Flags

function decodeUplink(input) {
    var bytes = input.bytes;
    var data = {};

    if (!bytes || bytes.length < 9) {
        return { data: {}, errors: ['payload too short (' + (bytes ? bytes.length : 0) + ' bytes)'] };
    }

    var cmd = bytes[0];
    if (cmd !== 0x01 && cmd !== 0x81) {
        return { data: { command: cmd }, warnings: ['unknown command 0x' + cmd.toString(16)] };
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

    // snake_case fuer FastAPI-Subscriber
    data.temperature = parseFloat(sensorTemp.toFixed(2));
    data.target_temperature = bytes[1];
    data.battery_voltage = parseFloat(batteryVoltage.toFixed(2));
    data.motor_position = motorPosition;
    data.motor_range = motorRange;

    // camelCase fuer ChirpStack-UI-Anzeige
    data.sensorTemperature = data.temperature;
    data.targetTemperature = data.target_temperature;
    data.batteryVoltage = data.battery_voltage;
    data.motorPosition = data.motor_position;
    data.motorRange = data.motor_range;
    data.relativeHumidity = parseFloat((bytes[3] * 100 / 256).toFixed(2));
    data.valveOpenness = motorRange !== 0 ? Math.round((1 - motorPosition / motorRange) * 100) : 0;
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

function encodeDownlink(input) {
    var data = input.data || {};
    var bytes = [];
    var errors = [];

    if (typeof data.target_temperature === 'number') {
        var t = Math.round(data.target_temperature * 2);
        if (t < 0 || t > 255) {
            errors.push('target_temperature out of range (5..30 degC)');
            return { bytes: [], fPort: 1, errors: errors };
        }
        bytes.push(0x02);
        bytes.push(t);
        return { bytes: bytes, fPort: 1, errors: errors };
    }

    if (data.force_window_redetect === true) {
        return { bytes: [0x05], fPort: 1, errors: errors };
    }

    errors.push('no actionable downlink fields in input.data');
    return { bytes: [], fPort: 1, errors: errors };
}
