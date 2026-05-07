// Sprint 9.0 — Codec-Tests fuer mclimate-vicki.js
//
// Kein Framework. Aufruf:  node test-mclimate-vicki.js
// Fail = process.exit(1).
//
// Wir laden die Codec-Funktionen via eval(), weil ChirpStack die Datei
// als plain JS-Snippet ausfuehrt (kein module.exports).

'use strict';

var fs = require('fs');
var path = require('path');

var src = fs.readFileSync(path.join(__dirname, 'mclimate-vicki.js'), 'utf8');
// `new Function` umgeht den File-strict-mode des Test-Files und legt
// die Codec-Funktionen sauber im Function-Scope an.
var loader = new Function(
    src + '; return { decodeUplink: decodeUplink, encodeDownlink: encodeDownlink };'
);
var codec = loader();
var decodeUplink = codec.decodeUplink;
var encodeDownlink = codec.encodeDownlink;

var failures = [];

function eq(actual, expected, label) {
    var ok = (actual === expected) ||
        (typeof actual === 'number' && typeof expected === 'number' &&
            Math.abs(actual - expected) < 1e-6);
    if (!ok) {
        failures.push(label + ' — expected ' + JSON.stringify(expected) +
            ', got ' + JSON.stringify(actual));
    }
}

function near(actual, expected, tol, label) {
    if (typeof actual !== 'number' || Math.abs(actual - expected) > tol) {
        failures.push(label + ' — expected ~' + expected + ' (tol ' + tol +
            '), got ' + JSON.stringify(actual));
    }
}

function arrayEq(actual, expected, label) {
    var ok = Array.isArray(actual) && actual.length === expected.length;
    if (ok) {
        for (var i = 0; i < expected.length; i++) {
            if (actual[i] !== expected[i]) { ok = false; break; }
        }
    }
    if (!ok) {
        failures.push(label + ' — expected ' + JSON.stringify(expected) +
            ', got ' + JSON.stringify(actual));
    }
}

// --- Test 1: Periodic Report v1 (Command 0x01) ---
(function () {
    var bytes = [0x01, 21, 142, 64, 0x10, 0xa0, 0x14, 0xa1, 0x00];
    var r = decodeUplink({ bytes: bytes, fPort: 1 });
    eq(r.errors, undefined, 'periodic v1: no errors');
    eq(r.data.report_type, 'periodic', 'periodic v1: report_type');
    eq(r.data.command, 0x01, 'periodic v1: command');
    eq(r.data.target_temperature, 21, 'periodic v1: target');
    near(r.data.temperature, 51.5, 0.5, 'periodic v1: temperature');
    eq(r.data.openWindow, false, 'periodic v1: openWindow false');
})();

// --- Test 2: Periodic Report v2 (Command 0x81) ---
(function () {
    var bytes = [0x81, 22, 138, 80, 0x10, 0xa0, 0x14, 0xb2, 0x00];
    var r = decodeUplink({ bytes: bytes, fPort: 1 });
    eq(r.data.report_type, 'periodic', 'periodic v2: report_type');
    eq(r.data.command, 0x81, 'periodic v2: command');
    eq(r.data.target_temperature, 22, 'periodic v2: target');
    near(r.data.temperature, 19.4, 0.2, 'periodic v2: temperature');
})();

// --- Test 3: valveOpenness Clamp (Bug Task #86) ---
// Wenn motorPosition > motorRange (Vicki sendet manchmal so was),
// muss valveOpenness 0 sein (statt negativem Wert).
(function () {
    // motorPosition = (0x07 << 8) | 0xc0 = 0x07c0 = 1984
    // motorRange    = (0x00 << 8) | 0xaa = 0x00aa = 170
    // 1 - 1984/170 = -10.67 -> ohne clamp -1067
    // byte6 = (motorPosHigh << 4) | motorRangeHigh = (0x07 << 4) | 0x00 = 0x70
    var bytes = [0x01, 21, 130, 64, 0xc0, 0xaa, 0x70, 0xa0, 0x00];
    var r = decodeUplink({ bytes: bytes, fPort: 1 });
    eq(r.data.valve_openness, 0, 'clamp negativ -> 0');
    eq(r.data.valveOpenness, 0, 'clamp negativ -> 0 (camelCase)');
})();

// --- Test 4: valveOpenness normaler Bereich ---
(function () {
    // motorPosition=100, motorRange=200 -> 1 - 100/200 = 0.5 = 50%
    var bytes = [0x01, 21, 130, 64, 100, 200, 0x00, 0xa0, 0x00];
    var r = decodeUplink({ bytes: bytes, fPort: 1 });
    eq(r.data.valve_openness, 50, 'valve 50%');
})();

// --- Test 5: Setpoint-Reply auf fPort 2 (Command 0x52) ---
(function () {
    // Setpoint 21.5 °C -> raw = 215 = 0x00D7
    var bytes = [0x52, 0x00, 0xd7];
    var r = decodeUplink({ bytes: bytes, fPort: 2 });
    eq(r.errors, undefined, 'setpoint reply: no errors');
    eq(r.data.report_type, 'setpoint_reply', 'setpoint reply: report_type');
    eq(r.data.command, 0x52, 'setpoint reply: command');
    eq(r.data.target_temperature, 21.5, 'setpoint reply: target_temperature');
    eq(r.data.acknowledged, true, 'setpoint reply: acknowledged');
})();

// --- Test 6: Setpoint-Reply 19 °C (ganzzahlig) ---
(function () {
    // 19.0 -> raw 190 = 0x00BE
    var bytes = [0x52, 0x00, 0xbe];
    var r = decodeUplink({ bytes: bytes, fPort: 2 });
    eq(r.data.target_temperature, 19, 'setpoint reply 19 grad');
})();

// --- Test 7: encodeDownlink Setpoint 21 °C ---
(function () {
    var r = encodeDownlink({ data: { target_temperature: 21 } });
    eq(r.fPort, 1, 'encode: fPort 1');
    arrayEq(r.bytes, [0x51, 0x00, 0xd2], 'encode 21°C -> 0x51 0x00 0xd2');
    eq(r.errors.length, 0, 'encode: no errors');
})();

// --- Test 8: encodeDownlink Setpoint 19.5 °C ---
(function () {
    var r = encodeDownlink({ data: { target_temperature: 19.5 } });
    arrayEq(r.bytes, [0x51, 0x00, 0xc3], 'encode 19.5°C -> 0x51 0x00 0xc3');
})();

// --- Test 9: encodeDownlink Out-of-range ---
(function () {
    var r = encodeDownlink({ data: { target_temperature: 50 } });
    arrayEq(r.bytes, [], 'encode 50°C -> empty');
    eq(r.errors.length, 1, 'encode 50°C -> 1 error');
})();

// --- Test 10: encodeDownlink min 5 °C ---
(function () {
    var r = encodeDownlink({ data: { target_temperature: 5 } });
    arrayEq(r.bytes, [0x51, 0x00, 0x32], 'encode 5°C -> 0x51 0x00 0x32');
})();

// --- Test 11: encodeDownlink max 30 °C ---
(function () {
    var r = encodeDownlink({ data: { target_temperature: 30 } });
    arrayEq(r.bytes, [0x51, 0x01, 0x2c], 'encode 30°C -> 0x51 0x01 0x2c');
})();

// --- Test 12: Unbekanntes Cmd-Byte auf fPort 2 (Sprint 9.10c-Routing) ---
// Mit Cmd-Byte-Routing (statt fPort-Routing) wird ein nicht-0x52-cmd
// auf fPort 2 als Periodic-Versuch interpretiert. Bei nur 1 Byte ist
// das "too short" — assertion auf den errors-Array.
(function () {
    var r = decodeUplink({ bytes: [0x99], fPort: 2 });
    eq(r.errors && r.errors.length, 1, 'fPort2 + unknown cmd: too-short error');
    eq(r.data.report_type, undefined, 'fPort2 + unknown cmd: kein report_type');
})();

// --- Test 13: Periodic-Report ohne fPort (Test-Tools) ---
(function () {
    var bytes = [0x01, 21, 142, 64, 0x10, 0xa0, 0x14, 0xa1, 0x00];
    var r = decodeUplink({ bytes: bytes });  // kein fPort
    eq(r.data.report_type, 'periodic', 'no fPort -> periodic default');
})();

// --- Test 14: Setpoint-Reply zu kurz ---
(function () {
    var r = decodeUplink({ bytes: [0x52, 0x00], fPort: 2 });
    eq(r.errors && r.errors.length, 1, 'setpoint reply too short -> error');
})();

// --- Test 15: Periodic Report Window-Open Flag ---
(function () {
    // status7 high nibble = battery, low nibble = flags. openWindow = bit 3 (0x08).
    var bytes = [0x01, 20, 130, 60, 0x10, 0xa0, 0x14, 0xa8, 0x00];
    //                                                       ^^ 0xa8 = battery=10 + flags=0x08
    var r = decodeUplink({ bytes: bytes, fPort: 1 });
    eq(r.data.openWindow, true, 'openWindow flag');
})();

// --- Sprint 9.10c: Cmd-Byte-Routing (statt fPort-Routing) ---

// --- Test 16: Periodic v2 (cmd=0x81) auf fPort 2 (Live-Beleg 2026-05-07) ---
// Regression-Wand: Vor 9.10c hat fPort=2 immer decodeCommandReply ausgeloest,
// 0x81 wurde dort als unknown_reply abgewuergt. Jetzt: Cmd-Byte-Routing
// erkennt 0x81 als Periodic, unabhaengig vom fPort.
(function () {
    var bytes = [0x81, 22, 138, 80, 0x10, 0xa0, 0x14, 0xb2, 0x00];
    var r = decodeUplink({ bytes: bytes, fPort: 2 });
    eq(r.data.report_type, 'periodic', 'periodic v2 fPort2: report_type');
    eq(r.data.command, 0x81, 'periodic v2 fPort2: command');
    eq(r.data.target_temperature, 22, 'periodic v2 fPort2: target');
    near(r.data.temperature, 19.4, 0.2, 'periodic v2 fPort2: temperature');
})();

// --- Test 17: Periodic v1 (cmd=0x01) auf fPort 1 (unveraendertes Verhalten) ---
// Sicherstellt, dass der Routing-Refactor das fPort-1-Standard-Verhalten
// nicht regrediert.
(function () {
    var bytes = [0x01, 21, 142, 64, 0x10, 0xa0, 0x14, 0xa1, 0x00];
    var r = decodeUplink({ bytes: bytes, fPort: 1 });
    eq(r.data.report_type, 'periodic', 'periodic v1 fPort1: report_type');
    eq(r.data.command, 0x01, 'periodic v1 fPort1: command');
})();

// --- Test 18: Setpoint-Reply (cmd=0x52) auf fPort 2 (unveraendertes Verhalten) ---
// Reply-Pfad muss erhalten bleiben — Vicki-Drehring/Engine-Ack laeuft hier rein.
(function () {
    var bytes = [0x52, 0x00, 0xd2];  // setpoint 21 °C
    var r = decodeUplink({ bytes: bytes, fPort: 2 });
    eq(r.data.report_type, 'setpoint_reply', 'setpoint reply fPort2: report_type');
    eq(r.data.target_temperature, 21, 'setpoint reply fPort2: target');
})();

// --- Test 19: Setpoint-Reply ohne fPort (Robustness) ---
// Test-Tools/Replays liefern manchmal kein fPort. Cmd-Byte-Routing entscheidet
// trotzdem korrekt: 0x52 -> Reply.
(function () {
    var bytes = [0x52, 0x00, 0xc3];  // setpoint 19.5 °C
    var r = decodeUplink({ bytes: bytes });  // kein fPort
    eq(r.data.report_type, 'setpoint_reply', 'setpoint reply no fPort: report_type');
    eq(r.data.target_temperature, 19.5, 'setpoint reply no fPort: target');
})();

// --- Resultat ---
if (failures.length === 0) {
    console.log('OK — 19/19 tests passed');
    process.exit(0);
} else {
    console.error('FAIL — ' + failures.length + ' failure(s):');
    failures.forEach(function (f) { console.error('  ' + f); });
    process.exit(1);
}
