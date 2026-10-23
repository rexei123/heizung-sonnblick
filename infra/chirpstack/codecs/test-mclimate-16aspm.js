// Sprint 24 — Codec-Tests fuer mclimate-16aspm.js
//
// Kein Framework. Aufruf:  node test-mclimate-16aspm.js
// Fail = process.exit(1).
//
// Geladen via `new Function`, weil ChirpStack die Datei als plain
// JS-Snippet ausfuehrt (kein module.exports) — dasselbe Verfahren wie
// test-mclimate-vicki.js.

'use strict';

var fs = require('fs');
var path = require('path');

var src = fs.readFileSync(path.join(__dirname, 'mclimate-16aspm.js'), 'utf8');
var loader = new Function(
    src + '; return { decodeUplink: decodeUplink, encodeDownlink: encodeDownlink };'
);
var codec = loader();
var decodeUplink = codec.decodeUplink;
var encodeDownlink = codec.encodeDownlink;

var failures = [];

function check(name, actual, expected) {
    var a = JSON.stringify(actual);
    var e = JSON.stringify(expected);
    if (a !== e) {
        failures.push(name + '\n  erwartet: ' + e + '\n  bekommen: ' + a);
    }
}

function hex(s) {
    var out = [];
    var i;
    for (i = 0; i < s.length; i += 2) {
        out.push(parseInt(s.substr(i, 2), 16));
    }
    return out;
}

// ---------------------------------------------------------------------------
// Keepalive
// ---------------------------------------------------------------------------

// 0x01 | T=23 | Energie 0x000003E8 = 1000 -> 1.0 kWh | P=0x0640=1600 W
// | U=230 V | I=0x1B58=7000 mA | Relais ein
var ka = decodeUplink({ bytes: hex('0117000003e80640e61b5801'), fPort: 1 });
check('keepalive report_type', ka.data.report_type, 'keepalive');
check('keepalive interne Temperatur', ka.data.internalTemperature, 23);
check('keepalive Energie kWh', ka.data.energy_kWh, 1);
check('keepalive Leistung W', ka.data.power_W, 1600);
check('keepalive Spannung V', ka.data.acVoltage_V, 230);
check('keepalive Strom mA', ka.data.acCurrent_mA, 7000);
check('keepalive Relaiszustand', ka.data.relayState, 'ON');
check('keepalive ohne Fehler', ka.errors, []);

// Der Grund, warum hier multipliziert und nicht geschoben wird: ab
// 0x80000000 kippt `<< 24` ins Negative. 0xFFFFFFFF = 4294967295.
var kaMax = decodeUplink({ bytes: hex('0117ffffffff000000000000'), fPort: 1 });
check('Energiezaehler bleibt positiv', kaMax.data.energy_raw, 4294967295);
check('Energie kWh am Zaehlerende', kaMax.data.energy_kWh, 4294967.295);

var kaShort = decodeUplink({ bytes: hex('011700'), fPort: 1 });
check('zu kurzer Keepalive meldet Fehler', kaShort.errors.length, 1);
check('zu kurzer Keepalive liefert keine Daten', kaShort.data, {});

check('leere Nutzlast', decodeUplink({ bytes: [], fPort: 1 }).errors, ['empty payload']);

// ---------------------------------------------------------------------------
// Befehlsantworten
// ---------------------------------------------------------------------------

var b1 = decodeUplink({ bytes: hex('b101'), fPort: 1 });
check('0xB1 Relais ein', b1.data.relayState, 'ON');
check('0xB1 report_type', b1.data.report_type, 'command_response');

check('0xB1 Relais aus', decodeUplink({ bytes: hex('b100'), fPort: 1 }).data.relayState, 'OFF');

// 0x58: Zustand aus, Restlaufzeit 1 s (Beispiel der Hersteller-Doku).
var t58 = decodeUplink({ bytes: hex('58000001'), fPort: 1 });
check('0x58 Zustand', t58.data.relayState, 'OFF');
check('0x58 Restlaufzeit', t58.data.relayTimerRemaining_s, 1);

// 0x58 mit 900 s (= 15 min, der Wert der Standardstrategie).
var t58b = decodeUplink({ bytes: hex('58010384'), fPort: 1 });
check('0x58 Zustand ein', t58b.data.relayState, 'ON');
check('0x58 Restlaufzeit 900 s', t58b.data.relayTimerRemaining_s, 900);

// 0x54 — alle acht dokumentierten Gruende.
var gruende = [
    ['00', 'device_restart'],
    ['01', 'manual_button'],
    ['02', 'overheating_protection'],
    ['03', 'overvoltage_protection'],
    ['04', 'overcurrent_protection'],
    ['05', 'overpower_protection'],
    ['06', 'radio_set_or_flip'],
    ['07', 'radio_timer']
];
gruende.forEach(function (paar) {
    var r = decodeUplink({ bytes: hex('54' + paar[0]), fPort: 1 });
    check('0x54 Grund ' + paar[0], r.data.relayChangeReason, paar[1]);
});
check(
    '0x54 unbekannter Grund traegt den Rohwert',
    decodeUplink({ bytes: hex('54ff'), fPort: 1 }).data.relayChangeReason,
    'unknown_255'
);

// 0x5F — Zustand nach Stromrueckkehr.
check(
    '0x5F Vorgabe ist last_state',
    decodeUplink({ bytes: hex('5f00'), fPort: 1 }).data.stateAfterPowerReturn,
    'last_state'
);
check(
    '0x5F auf AUS gesetzt',
    decodeUplink({ bytes: hex('5f02'), fPort: 1 }).data.stateAfterPowerReturn,
    'off'
);

// 0x12 — Keepalive-Periode.
check(
    '0x12 Keepalive-Periode',
    decodeUplink({ bytes: hex('120f'), fPort: 1 }).data.keepAlivePeriod_min,
    15
);

// 0x5D — Umschaltung am Taster.
var manual = decodeUplink({ bytes: hex('5d01'), fPort: 1 });
check('0x5D Taster-Zustand', manual.data.relayState, 'ON');
check('0x5D als Handeingriff erkannt', manual.data.manualSwitch, true);

// ---------------------------------------------------------------------------
// Antwort PLUS Keepalive im selben Frame
// ---------------------------------------------------------------------------

// Die Doku: Antworten kommen "together with the next keep-alive message".
// 0xB1 01 gefolgt von einem vollstaendigen 12-Byte-Keepalive.
var gemischt = decodeUplink({
    bytes: hex('b101' + '0117000003e80640e61b5801'),
    fPort: 1
});
check('gemischt: Antwort erkannt', gemischt.data.relayState, 'ON');
check('gemischt: Keepalive mitgelesen', gemischt.data.power_W, 1600);
check('gemischt: Kennzeichen gesetzt', gemischt.data.keepalive_included, true);
check('gemischt: report_type bleibt die Antwort', gemischt.data.report_type, 'command_response');
check('gemischt: ohne Fehler', gemischt.errors, []);

// Zwei Antworten plus Keepalive — der Fall aus der Provisionierung
// (Zustand lesen und Stromrueckkehr-Einstellung lesen in einem Zug).
var zwei = decodeUplink({
    bytes: hex('b100' + '5f02' + '0117000003e80640e61b5800'),
    fPort: 1
});
check('zwei Antworten: Zustand', zwei.data.relayState, 'OFF');
check('zwei Antworten: Stromrueckkehr', zwei.data.stateAfterPowerReturn, 'off');
check('zwei Antworten: Keepalive', zwei.data.acVoltage_V, 230);

// Antwort OHNE Keepalive — laut Doku moeglich, wenn die MAC-Nutzlast
// nicht reicht. Der offizielle Dekoder slict den Schwanz
// bedingungslos und wuerde hier Unsinn lesen.
var ohneKa = decodeUplink({ bytes: hex('b101' + '5f02'), fPort: 1 });
check('ohne Keepalive: Zustand', ohneKa.data.relayState, 'ON');
check('ohne Keepalive: Stromrueckkehr', ohneKa.data.stateAfterPowerReturn, 'off');
check('ohne Keepalive: kein Kennzeichen', ohneKa.data.keepalive_included, undefined);
check('ohne Keepalive: kein Fehler', ohneKa.errors, []);

// Unbekannter Code: abbrechen statt raten.
var unbekannt = decodeUplink({ bytes: hex('aa01b101'), fPort: 1 });
check('unbekannter Code liefert den Rest als Hex', unbekannt.data.unknown_reply, 'aa01b101');
check('unbekannter Code meldet einen Fehler', unbekannt.errors.length, 1);

// Abgeschnittene Antwort.
var kurz = decodeUplink({ bytes: hex('5801'), fPort: 1 });
check('abgeschnittene 0x58 meldet Fehler', kurz.errors.length, 1);

// ---------------------------------------------------------------------------
// Downlinks
// ---------------------------------------------------------------------------

// S1: EIN nur ueber den Timer. 900 s = 15 min.
check(
    'EIN ueber Timer 900 s',
    encodeDownlink({ data: { relay_on_seconds: 900 } }).bytes,
    [0x57, 0x01, 0x03, 0x84]
);
// 1800 s = 30 min, der Wert der Standardstrategie.
check(
    'EIN ueber Timer 1800 s',
    encodeDownlink({ data: { relay_on_seconds: 1800 } }).bytes,
    [0x57, 0x01, 0x07, 0x08]
);
check(
    'EIN ueber Timer: fPort 1',
    encodeDownlink({ data: { relay_on_seconds: 60 } }).fPort,
    1
);
check(
    'Timer 0 s wird abgewiesen',
    encodeDownlink({ data: { relay_on_seconds: 0 } }).bytes,
    []
);
check(
    'Timer 65536 s wird abgewiesen',
    encodeDownlink({ data: { relay_on_seconds: 65536 } }).bytes,
    []
);
check(
    'Timer mit Bruchteil wird abgewiesen',
    encodeDownlink({ data: { relay_on_seconds: 60.5 } }).bytes,
    []
);

// S1: AUS ueber 0xC1 00. Es gibt keinen Weg, 0xC1 01 zu erzeugen.
check('AUS ueber 0xC1 00', encodeDownlink({ data: { relay_off: true } }).bytes, [0xc1, 0x00]);

check('Zustand lesen', encodeDownlink({ data: { get_relay_state: true } }).bytes, [0xb1]);
check('Timer lesen', encodeDownlink({ data: { get_relay_timer: true } }).bytes, [0x58]);
check('Grund lesen', encodeDownlink({ data: { get_relay_change_reason: true } }).bytes, [0x54]);

// S4: Zustand nach Stromrueckkehr.
check(
    'Stromrueckkehr auf AUS',
    encodeDownlink({ data: { state_after_power_return: 'off' } }).bytes,
    [0x5e, 0x02]
);
check(
    'Stromrueckkehr auf last_state',
    encodeDownlink({ data: { state_after_power_return: 'last_state' } }).bytes,
    [0x5e, 0x00]
);
check(
    'Stromrueckkehr unbekannter Wert wird abgewiesen',
    encodeDownlink({ data: { state_after_power_return: 'vielleicht' } }).bytes,
    []
);
check(
    'Stromrueckkehr lesen',
    encodeDownlink({ data: { get_state_after_power_return: true } }).bytes,
    [0x5f]
);

check(
    'Keepalive-Periode setzen',
    encodeDownlink({ data: { keepalive_period_min: 15 } }).bytes,
    [0x02, 0x0f]
);
check('Keepalive-Periode lesen', encodeDownlink({ data: { get_keepalive_period: true } }).bytes, [0x12]);
check('Version lesen', encodeDownlink({ data: { get_version: true } }).bytes, [0x04]);

check('leere Eingabe meldet einen Fehler', encodeDownlink({ data: {} }).errors.length, 1);

// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Nachtrag S4 (23.10.2026): Erholung vom Ueberhitzungsschutz und die
// Schutz-Ereignisse.
// ---------------------------------------------------------------------------

// 0x5A — und die Falle: AUS ist hier 0x01, bei 0x5E ist AUS 0x02.
check(
    '0x5A Vorgabe ist last_state',
    decodeUplink({ bytes: hex('5a00'), fPort: 1 }).data.stateAfterOverheatingRecovery,
    'last_state'
);
check(
    '0x5A auf AUS gesetzt (0x01, NICHT 0x02)',
    decodeUplink({ bytes: hex('5a01'), fPort: 1 }).data.stateAfterOverheatingRecovery,
    'off'
);
check(
    '0x5A mit 0x02 ist undokumentiert und wird als solches gemeldet',
    decodeUplink({ bytes: hex('5a02'), fPort: 1 }).data.stateAfterOverheatingRecovery,
    'unknown_2'
);

// Derselbe Wortsinn, verschiedene Bytes -- genau das soll dieser Test
// festhalten, damit niemand die Werte von 0x5E uebernimmt.
check(
    'AUS nach Stromrueckkehr ist 0x5E 02',
    encodeDownlink({ data: { state_after_power_return: 'off' } }).bytes,
    [0x5e, 0x02]
);
check(
    'AUS nach Ueberhitzung ist 0x59 01',
    encodeDownlink({ data: { state_after_overheating_recovery: 'off' } }).bytes,
    [0x59, 0x01]
);
check(
    'last_state nach Ueberhitzung ist 0x59 00',
    encodeDownlink({ data: { state_after_overheating_recovery: 'last_state' } }).bytes,
    [0x59, 0x00]
);
check(
    '0x59 kennt kein ON -- unbekannter Wert wird abgewiesen',
    encodeDownlink({ data: { state_after_overheating_recovery: 'on' } }).bytes,
    []
);
check(
    'Erholungszustand lesen',
    encodeDownlink({ data: { get_state_after_overheating_recovery: true } }).bytes,
    [0x5a]
);

// Schutz-Ereignisse. Beispiele der Hersteller-Doku.
var ov = decodeUplink({ bytes: hex('60053c'), fPort: 1 });
check('0x60 Art', ov.data.protection, 'overheating');
check('0x60 Zaehler', ov.data.protectionEventCount, 5);
check('0x60 Temperatur', ov.data.protectionTemperatureC, 60);

var uv = decodeUplink({ bytes: hex('61030104'), fPort: 1 });
check('0x61 Art', uv.data.protection, 'overvoltage');
check('0x61 Zaehler', uv.data.protectionEventCount, 3);
check('0x61 Spannung 260 V', uv.data.protectionVoltageV, 260);

var oc = decodeUplink({ bytes: hex('62031952'), fPort: 1 });
check('0x62 Strom 6482 mA', oc.data.protectionCurrentMa, 6482);

var op = decodeUplink({ bytes: hex('630307d0'), fPort: 1 });
check('0x63 Leistung 2000 W', op.data.protectionPowerW, 2000);

// Erholungs-Ereignisse.
check(
    '0x70 Laufzeit 42 s',
    decodeUplink({ bytes: hex('70002a'), fPort: 1 }).data.protectionRuntimeS,
    42
);
check(
    '0x71 Laufzeit 26 s',
    decodeUplink({ bytes: hex('71001a'), fPort: 1 }).data.protectionRuntimeS,
    26
);
check(
    '0x72 Geraetetemperatur 62 °C',
    decodeUplink({ bytes: hex('723e'), fPort: 1 }).data.protectionTemperatureC,
    62
);
check(
    '0x73 Geraetetemperatur 47 °C',
    decodeUplink({ bytes: hex('732f'), fPort: 1 }).data.protectionTemperatureC,
    47
);

// Das Vorzeichen-Bit ab FW 1.3. Ohne seine Behandlung wuerde aus -2 °C
// eine 130 °C -- und ein Alarm, der nichts mit der Lage zu tun hat.
check(
    '0x72 negative Temperatur (Vorzeichen-Bit)',
    decodeUplink({ bytes: hex('7282'), fPort: 1 }).data.protectionTemperatureC,
    -2
);

// Ueberhitzungs-Schwellen des Geraets (Vorgabe FW >= 1.4: 85/70 °C).
var sch = decodeUplink({ bytes: hex('1f5546'), fPort: 1 });
check('0x1F Auslöseschwelle 85 °C', sch.data.overheatingTriggerC, 85);
check('0x1F Erholungsschwelle 70 °C', sch.data.overheatingRecoveryC, 70);

// Ein Schutz-Ereignis kommt laut Doku mit dem Keepalive.
var mitKa = decodeUplink({
    bytes: hex('60053c' + '0117000003e80640e61b5800'),
    fPort: 1
});
check('Schutz-Ereignis plus Keepalive: Art', mitKa.data.protection, 'overheating');
check('Schutz-Ereignis plus Keepalive: Relais aus', mitKa.data.relayState, 'OFF');
check('Schutz-Ereignis plus Keepalive: Kennzeichen', mitKa.data.keepalive_included, true);

// -------------------------------------------------------------------------

if (failures.length > 0) {
    console.error(failures.length + ' Fehlschlag/Fehlschlaege:\n');
    failures.forEach(function (f) { console.error('  ' + f + '\n'); });
    process.exit(1);
}
console.log('alle Codec-Tests 16ASPM gruen');
