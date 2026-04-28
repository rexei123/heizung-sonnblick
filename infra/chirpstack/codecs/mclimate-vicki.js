// MClimate Vicki - LoRaWAN Payload Codec
//
// Status: Foundation-Variante fuer Sprint 5 (chirpstack-simulator + erste Pairings).
// Basis: MClimate-Vicki-Protokoll-Dokumentation (MClimate Developer Hub) per April 2026.
// Format: ChirpStack v4 / TheThingsNetwork Codec-API.
//
// Bei produktivem Einsatz mit echter Hardware sollten ggf. weitere Command-Codes
// und Hersteller-Updates eingepflegt werden (Sprint 6 / Hardware-Phase).
//
// Eingehende Payload (fPort 1, Standard-Status-Report):
//   Byte 0 : Command-Code
//     0x01 = Periodic Status Report (Default)
//   Byte 1 : Battery (Volt * 10 - 30)  -> 0.1V Aufloesung, Offset 3.0V
//            Bsp.: 0x09 = 4.5V (real-Wert: 3.0 + 0.9 = 3.9V)
//   Byte 2 : Internal Temperature (signed int8, Wert direkt in degC)
//   Byte 3 : Target Temperature (uint8, in 0.5degC Schritten)
//            Bsp.: 0x2A (42) -> 21.0degC
//   Byte 4 : Motor Range (uint8, 0..255 entspricht 0..100% Ventiloeffnung)
//   Byte 5 : Motor Position (uint8, aktuelle Ventiloeffnung 0..100%)
//   Byte 6 : Status Flags (Bitfield)
//     bit0 = open_window_detected
//     bit1 = child_lock
//     bit2 = manual_override
//   Byte 7+: Optional, je nach Firmware-Version (RSSI, SNR redundant, etc.)
//
// Downlink-Commands (encodeDownlink):
//   0x02 + temp_byte : Set Target Temperature (temp_byte = round(target_c * 2))
//   0x05             : Force Open Window Re-Detection

function decodeUplink(input) {
  var bytes = input.bytes;
  var fPort = input.fPort;
  var warnings = [];
  var errors = [];
  var data = {};

  if (bytes.length === 0) {
    errors.push("empty payload");
    return { data: data, warnings: warnings, errors: errors };
  }

  data.command = bytes[0];

  if (fPort === 1 && bytes[0] === 0x01) {
    // Periodic Status Report
    if (bytes.length < 7) {
      warnings.push("status report shorter than expected (" + bytes.length + " bytes)");
    }

    if (bytes.length > 1) {
      data.battery_voltage = parseFloat((3.0 + bytes[1] / 10).toFixed(2));
    }
    if (bytes.length > 2) {
      // signed int8
      var rawTemp = bytes[2];
      if (rawTemp > 127) rawTemp -= 256;
      data.temperature = rawTemp;
    }
    if (bytes.length > 3) {
      data.target_temperature = parseFloat((bytes[3] / 2).toFixed(1));
    }
    if (bytes.length > 4) {
      data.motor_range = Math.round((bytes[4] / 255) * 100);
    }
    if (bytes.length > 5) {
      data.motor_position = bytes[5];
    }
    if (bytes.length > 6) {
      var flags = bytes[6];
      data.open_window_detected = (flags & 0x01) !== 0;
      data.child_lock = (flags & 0x02) !== 0;
      data.manual_override = (flags & 0x04) !== 0;
    }
  } else {
    warnings.push("unhandled fPort/command combination: fPort=" + fPort + " cmd=0x" + bytes[0].toString(16));
    data.raw_hex = bytes.map(function (b) {
      return ("00" + b.toString(16)).slice(-2);
    }).join("");
  }

  return { data: data, warnings: warnings, errors: errors };
}

function encodeDownlink(input) {
  var data = input.data || {};
  var bytes = [];
  var errors = [];

  if (typeof data.target_temperature === "number") {
    var t = Math.round(data.target_temperature * 2);
    if (t < 0 || t > 255) {
      errors.push("target_temperature out of range (5..30 degC)");
      return { bytes: [], fPort: 1, errors: errors };
    }
    bytes.push(0x02);
    bytes.push(t);
    return { bytes: bytes, fPort: 1, errors: errors };
  }

  if (data.force_window_redetect === true) {
    return { bytes: [0x05], fPort: 1, errors: errors };
  }

  errors.push("no actionable downlink fields in input.data");
  return { bytes: [], fPort: 1, errors: errors };
}
