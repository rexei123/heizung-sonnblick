// MClimate 16A Switch & Power Meter (16ASPM) — LoRaWAN Payload Codec
// (strict-mode-safe)
//
// Sprint 24 (2026-10-23): Infrarot-Pilot Allgemeinflaechen. Das Geraet
// schaltet 1600-W-Infrarotpanels; die Engine entscheidet, dieses Geraet
// stellt.
//
// === Warum eine eigene Implementierung und nicht der offizielle Codec ===
//
// Dieselbe Begruendung wie bei mclimate-vicki.js (Sprint 6.8): der
// offizielle MClimate-Codec deklariert globale Variablen ohne `var`.
// Die ChirpStack-Goja-Engine laeuft im strict mode und wirft dafuer
// ReferenceError — dann fehlt das `object`-Feld im MQTT-Event, und der
// Subscriber bekommt nichts. Das hat beim Vicki zwei Sprints
// Verifikationsarbeit gekostet (CLAUDE.md §5.22).
//
// Dazu ein zweiter, geraetespezifischer Grund: der offizielle Dekoder
// baut den 32-Bit-Energiezaehler mit `bytes[2] << 24`. In JavaScript ist
// `<<` ein **signierter** 32-Bit-Operator — ab 0x80000000 kippt der
// Zaehler ins Negative. Hier wird multipliziert statt geschoben.
//
// Das Byte-Format stammt aus der Hersteller-Doku, nicht aus dem
// offiziellen Codec:
//   https://docs.mclimate.eu/mclimate-lorawan-devices/devices/
//     mclimate-16a-switch-and-power-meter-lorawan-16aspm/
// Abschnitte "Relay state", "Commands cheat sheet", "Uplink decoder",
// "Communication concepts". Abgerufen 23.10.2026.
//
// === Belegte Eigenschaften des Geraets ===
//
// - **Class C** ("This is a Class C device, according to the LoRaWAN
//   1.0.3 specification"). Es hoert dauerhaft; Downlinks gehen jederzeit,
//   ohne auf ein Empfangsfenster zu warten. Das ist der Unterschied zum
//   Vicki (Class A) und der Grund, warum ein Schaltbefehl hier sofort
//   wirkt.
// - **Downlink-fPorts: 1, 2, 4-224.** fPort 1 ist zulaessig und wird
//   hier verwendet, wie beim Vicki.
// - **Uplink-fPort: nicht dokumentiert.** Deshalb routet dieser Codec
//   ausschliesslich ueber `bytes[0]` — §5.21, und der offizielle Dekoder
//   liest fPort ebenfalls nicht.
// - **Der Keepalive ist NICHT in jedem Uplink.** Die Doku:
//   "If the combined length exceeds the LoRaWAN MAC payload limit, the
//   keep-alive packet will be omitted and only the command responses will
//   be sent." Dieser Codec slict den Schwanz deshalb **nicht**
//   bedingungslos (wie der offizielle), sondern parst die
//   Befehlsantworten von vorn und behandelt genau dann einen
//   12-Byte-Rest als Keepalive, wenn er uebrig bleibt.
//
// === Uplinks ===
//
// Keepalive (bytes[0] === 0x01, 12 Bytes)
//   Byte 0     : 0x01
//   Byte 1     : interne Temperatur (uint8, Rohwert — Einheit laut Doku
//                nicht angegeben, siehe AE-78)
//   Byte 2..5  : Energiezaehler, 32 Bit big-endian, /1000 -> kWh
//   Byte 6..7  : Leistung, uint16 big-endian, W
//   Byte 8     : Netzspannung, uint8, V
//   Byte 9..10 : Netzstrom, uint16 big-endian, mA
//   Byte 11    : Relaiszustand (0x01 = ein, sonst aus)
//
// Befehlsantworten (bytes[0] !== 0x01), jeweils mit bekannter Laenge:
//   0xB1 0xSS            Relaiszustand
//   0x58 0xSS 0xHH 0xLL  Relaiszustand + Restlaufzeit des Timers in s
//   0x54 0xRR            Grund der letzten Zustandsaenderung
//   0x5F 0xMM            Zustand nach Stromrueckkehr (00 last/01 ein/02 aus)
//   0x12 0xPP            Keepalive-Periode in Minuten
//   0x04 ...             Hardware-/Softwareversion
//
// Ein unbekannter Code bricht das Parsen ab (die Laenge ist dann
// unbekannt, weiterlesen waere geraten) und liefert `unknown_reply` mit
// dem Rest als Hex — dasselbe Verhalten wie beim Vicki-Codec.

function decodeUplink(input) {
    var bytes = input.bytes;

    // **Ein leerer Uplink ist kein Fehler** (Befund des Betreibers,
    // 01.11.2026). Relais 109 schickte um 09:47:57 und 09:48:04 zwei
    // leere Frames auf **fPort 0** — das ist die MAC-Ebene von LoRaWAN,
    // dort steht nie eine Nutzlast. ChirpStack schrieb dafuer zweimal
    // ``UPLINK_CODEC ERROR`` ins Log.
    //
    // Das ist die Sorte Melder, die man nach einer Woche ueberliest
    // (§5.79): ein Fehler, der im Normalbetrieb erscheint, nimmt den
    // echten Fehlern ihre Aufmerksamkeit. „Nichts zu sagen" ist eine
    // gueltige Aussage, und sie gehoert nicht in die Fehlerliste.
    //
    // Zurueck kommt ein **leerer** Datenblock, kein eigener
    // ``report_type``: der Subscriber entscheidet an diesem Feld, und ein
    // neuer Wert waere eine Weiche, die niemand gebaut hat. Eine
    // ``relay_reading``-Zeile aus lauter ``NULL`` ist harmlos — jeder
    // Leser filtert sie (``relay_state`` ausdruecklich mit
    // ``relay_on IS NOT NULL``).
    if (!bytes || bytes.length === 0) {
        return { data: {}, errors: [] };
    }

    if (bytes[0] === 0x01) {
        return decodeKeepalive(bytes, 0);
    }

    return decodeCommandResponses(bytes);
}

// Laenge je Befehlsantwort, einschliesslich Command-Byte.
function responseLength(code) {
    if (code === 0xb1) { return 2; }
    if (code === 0x54) { return 2; }
    if (code === 0x5a) { return 2; }
    if (code === 0x5f) { return 2; }
    if (code === 0x12) { return 2; }
    if (code === 0x58) { return 4; }
    if (code === 0x5d) { return 2; }
    // 0x04 ist **3** Bytes, nicht 5: die Versionen stecken als Nibbles in
    // je einem Byte. Hier stand 5, weil die Vendor-Schreibweise
    // "0x04{HW_major}{HW_minor}{FW_major}{FW_minor}" wie vier Bytes
    // aussieht. Genau diese Stelle ist beim Vicki schon einmal korrigiert
    // worden (Sprint 9.11x.c, docs/vendor/mclimate-vicki/
    // 04-commands-cheat-sheet.md §1) — und die Korrektur ist beim zweiten
    // Geraet nicht mitgewandert. Nachgewiesen am ersten Frame von Relais
    // 109 (01.11.2026): ``04 21 15`` → HW 2.1, FW 1.5, und mit Laenge 5
    // sprang der Dekoder mitten in die naechste Antwort (§5.79).
    if (code === 0x04) { return 3; }
    // Netzwerk-Einstellungen, die das Geraet im ersten Uplink nach dem
    // Join unaufgefordert mitschickt. Alle drei aus der Hersteller-Doku
    // ("Network-related settings", abgerufen 01.11.2026) und am Frame von
    // 109 belegt.
    if (code === 0x19) { return 2; }   // Join-Wiederholung: T[s] = XX * 5
    if (code === 0x1b) { return 2; }   // Uplink-Art: 00 unbestaetigt, 01 bestaetigt
    if (code === 0x1d) { return 3; }   // Funk-Wachhund: bestaetigt, unbestaetigt
    if (code === 0xa4) { return 2; }   // LoRaWAN-Region
    // Schutz-Ereignisse: Zaehler plus Messwert.
    if (code === 0x60) { return 3; }   // Ueberhitzung: Zaehler + °C
    if (code === 0x61) { return 4; }   // Ueberspannung: Zaehler + V (16 Bit)
    if (code === 0x62) { return 4; }   // Ueberstrom: Zaehler + mA (16 Bit)
    if (code === 0x63) { return 4; }   // Ueberlast: Zaehler + W (16 Bit)
    // Erholungs-Ereignisse (FW >= 1.1).
    if (code === 0x70) { return 3; }   // Ueberhitzung: Laufzeit in s
    if (code === 0x71) { return 3; }   // Ueberspannung: Laufzeit in s
    if (code === 0x72) { return 2; }   // Ueberstrom: Geraetetemperatur
    if (code === 0x73) { return 2; }   // Ueberlast: Geraetetemperatur
    if (code === 0x1f) { return 3; }   // Ueberhitzungs-Schwellen
    return -1;
}

// 0x72/0x73 melden die Geraetetemperatur. Ab FW 1.3 ist das oberste Bit
// von Byte 1 ein Vorzeichen, die unteren sieben Bits der Wert — ein
// vorzeichenloses Lesen wuerde aus -2 °C eine 130 °C machen und einen
// Alarm ausloesen, der nichts mit der Lage zu tun hat.
function signedTemp(value) {
    var betrag = value & 0x7f;
    return (value & 0x80) !== 0 ? -betrag : betrag;
}

function relayStateName(value) {
    return value === 0x01 ? 'ON' : 'OFF';
}

// 0xA4 — die Region steckt in der Firmware und ist nicht verstellbar; der
// Befehl berichtet sie nur. Ein unbekannter Wert wird **nicht** geraten,
// sondern als Rohzahl gemeldet: eine falsche Regionsangabe waere eine
// Behauptung ueber das Funknetz (§5.68).
function lorawanRegionName(value) {
    if (value === 0x00) { return 'EU868'; }
    if (value === 0x01) { return 'AS923'; }
    if (value === 0x02) { return 'AU915'; }
    if (value === 0x03) { return 'US915'; }
    return 'unknown(' + value + ')';
}

// 0x54 — Grund der letzten Relais-Zustandsaenderung. Die Namen sind die
// der Doku, als snake_case-Marken: sie landen im Audit und muessen
// stabil sein, nicht schoen.
function relayChangeReason(code) {
    if (code === 0x00) { return 'device_restart'; }
    if (code === 0x01) { return 'manual_button'; }
    if (code === 0x02) { return 'overheating_protection'; }
    if (code === 0x03) { return 'overvoltage_protection'; }
    if (code === 0x04) { return 'overcurrent_protection'; }
    if (code === 0x05) { return 'overpower_protection'; }
    if (code === 0x06) { return 'radio_set_or_flip'; }
    if (code === 0x07) { return 'radio_timer'; }
    return 'unknown_' + code;
}

function powerReturnStateName(code) {
    if (code === 0x00) { return 'last_state'; }
    if (code === 0x01) { return 'on'; }
    if (code === 0x02) { return 'off'; }
    return 'unknown_' + code;
}

function toHex(bytes, from) {
    var out = '';
    var i;
    for (i = from; i < bytes.length; i += 1) {
        var h = bytes[i].toString(16);
        out += h.length === 1 ? '0' + h : h;
    }
    return out;
}

function decodeKeepalive(bytes, offset) {
    var data = {};
    var errors = [];

    if (bytes.length - offset < 12) {
        return {
            data: {},
            errors: ['keepalive too short (' + (bytes.length - offset) + ' bytes, expected 12)']
        };
    }

    data.report_type = 'keepalive';
    // Ab FW 1.3 ist Bit 7 das Vorzeichen (Hersteller-Doku „Keep-alive",
    // abgerufen 01.11.2026). Vorzeichenlos gelesen wuerde aus -2 °C eine
    // 130 °C — und das ist kein Anzeigefehler, sondern ein Wert, der an
    // der Ueberhitzungs-Schwelle als Ausloesung gelesen werden kann.
    // Relais 109 meldet FW 1.5, ist also betroffen; im ersten Frame war
    // Bit 7 frei (0x1f = 31 °C) und der Fehler deshalb unsichtbar.
    //
    // **Ohne Firmware-Weiche**, und das ist eine Entscheidung: der Codec
    // kennt die Firmware beim Dekodieren nicht (sie steht in einer
    // anderen Antwort, nicht im Keepalive). Fuer FW <= 1.2 waere die
    // Weiche ohnehin folgenlos — ein gesetztes Bit 7 hiesse dort ueber
    // 127 °C, und bei der Temperatur gibt es kein Geraet mehr, das meldet.
    data.internalTemperature = signedTemp(bytes[offset + 1]);

    // Bewusst Multiplikation statt `<< 24`: `<<` ist in JS signiert und
    // kippt den Zaehler ab 0x80000000 ins Negative. Der offizielle
    // Dekoder hat genau diesen Fehler.
    var energyRaw = (bytes[offset + 2] * 16777216)
        + (bytes[offset + 3] * 65536)
        + (bytes[offset + 4] * 256)
        + bytes[offset + 5];
    data.energy_raw = energyRaw;
    data.energy_kWh = energyRaw / 1000;

    data.power_W = (bytes[offset + 6] * 256) + bytes[offset + 7];
    data.acVoltage_V = bytes[offset + 8];
    data.acCurrent_mA = (bytes[offset + 9] * 256) + bytes[offset + 10];
    data.relayState = relayStateName(bytes[offset + 11]);

    return { data: data, errors: errors };
}

function decodeCommandResponses(bytes) {
    var data = {};
    var errors = [];
    var i = 0;

    data.report_type = 'command_response';

    while (i < bytes.length) {
        var code = bytes[i];
        var len = responseLength(code);

        // Der uebrige Rest ist genau ein Keepalive-Block.
        if (len === -1 && bytes.length - i === 12 && code === 0x01) {
            var ka = decodeKeepalive(bytes, i);
            var key;
            for (key in ka.data) {
                if (Object.prototype.hasOwnProperty.call(ka.data, key)) {
                    // report_type der Antwort hat Vorrang (§ Vicki 9.11x.c).
                    if (key !== 'report_type') {
                        data[key] = ka.data[key];
                    }
                }
            }
            data.keepalive_included = true;
            return { data: data, errors: errors };
        }

        if (len === -1) {
            data.unknown_reply = toHex(bytes, i);
            errors.push('unknown command code 0x' + code.toString(16) + ' at offset ' + i);
            return { data: data, errors: errors };
        }

        if (bytes.length - i < len) {
            errors.push(
                'truncated response for 0x' + code.toString(16)
                + ' (' + (bytes.length - i) + ' of ' + len + ' bytes)'
            );
            return { data: data, errors: errors };
        }

        if (code === 0xb1) {
            data.relayState = relayStateName(bytes[i + 1]);
        } else if (code === 0x58) {
            data.relayState = relayStateName(bytes[i + 1]);
            data.relayTimerRemaining_s = (bytes[i + 2] * 256) + bytes[i + 3];
        } else if (code === 0x54) {
            data.relayChangeReason = relayChangeReason(bytes[i + 1]);
            data.relayChangeReasonCode = bytes[i + 1];
        } else if (code === 0x5f) {
            data.stateAfterPowerReturn = powerReturnStateName(bytes[i + 1]);
        } else if (code === 0x5a) {
            // Zustand nach Erholung vom Ueberhitzungsschutz.
            //
            // **Achtung: AUS ist hier 0x01, bei 0x5E ist AUS 0x02.**
            // Dieselbe Bedeutung, verschiedene Bytes, und 0x59 kennt
            // ueberhaupt kein "ON". Wer die Werte von 0x5E uebernimmt,
            // setzt mit 0x02 einen undokumentierten Wert.
            data.stateAfterOverheatingRecovery =
                bytes[i + 1] === 0x01 ? 'off' : (bytes[i + 1] === 0x00 ? 'last_state' : 'unknown_' + bytes[i + 1]);
        } else if (code === 0x12) {
            data.keepAlivePeriod_min = bytes[i + 1];
        } else if (code === 0x1f) {
            data.overheatingTriggerC = bytes[i + 1];
            data.overheatingRecoveryC = bytes[i + 2];
        } else if (code === 0x60) {
            data.protection = 'overheating';
            data.protectionEventCount = bytes[i + 1];
            data.protectionTemperatureC = bytes[i + 2];
        } else if (code === 0x61) {
            data.protection = 'overvoltage';
            data.protectionEventCount = bytes[i + 1];
            data.protectionVoltageV = (bytes[i + 2] * 256) + bytes[i + 3];
        } else if (code === 0x62) {
            data.protection = 'overcurrent';
            data.protectionEventCount = bytes[i + 1];
            data.protectionCurrentMa = (bytes[i + 2] * 256) + bytes[i + 3];
        } else if (code === 0x63) {
            data.protection = 'overpower';
            data.protectionEventCount = bytes[i + 1];
            data.protectionPowerW = (bytes[i + 2] * 256) + bytes[i + 3];
        } else if (code === 0x70) {
            data.protectionRecovered = 'overheating';
            data.protectionRuntimeS = (bytes[i + 1] * 256) + bytes[i + 2];
        } else if (code === 0x71) {
            data.protectionRecovered = 'overvoltage';
            data.protectionRuntimeS = (bytes[i + 1] * 256) + bytes[i + 2];
        } else if (code === 0x72) {
            data.protectionRecovered = 'overcurrent';
            data.protectionTemperatureC = signedTemp(bytes[i + 1]);
        } else if (code === 0x73) {
            data.protectionRecovered = 'overpower';
            data.protectionTemperatureC = signedTemp(bytes[i + 1]);
        } else if (code === 0x5d) {
            // Manuelle Umschaltung am Taster. Das Geraet meldet den neuen
            // Zustand von selbst — fuer S3 ist das der Nachweis, dass
            // jemand von Hand eingegriffen hat.
            data.relayState = relayStateName(bytes[i + 1]);
            data.manualSwitch = true;
        } else if (code === 0x04) {
            // Nibbles, nicht Bytes — und dieselben Feldnamen wie im
            // Vicki-Codec. Zwei Namen fuer dieselbe Zahl waeren zwei
            // Wahrheiten, und der Subscriber liest hausweit
            // ``firmware_version`` (§5.53).
            data.hw_version = ((bytes[i + 1] >> 4) & 0x0f) + '.' + (bytes[i + 1] & 0x0f);
            data.firmware_version = ((bytes[i + 2] >> 4) & 0x0f) + '.' + (bytes[i + 2] & 0x0f);
        } else if (code === 0x19) {
            // T[s] = XX * 5. Werkswert 0x78 = 600 s.
            data.joinRetryPeriod_s = bytes[i + 1] * 5;
        } else if (code === 0x1b) {
            data.uplinkType = bytes[i + 1] === 0x01 ? 'confirmed' : 'unconfirmed';
        } else if (code === 0x1d) {
            // Byte 1: bestaetigte Uplinks ohne ACK, plus 7 Minuten
            // (0x00 = aus). Byte 2: unbestaetigte in Stunden (0x00 = aus).
            // Die Rohwerte bleiben roh — die Umrechnung auf Minuten
            // braucht die Keepalive-Periode und gehoert nicht in den
            // Codec.
            data.watchdogConfirmed = bytes[i + 1];
            data.watchdogUnconfirmed_h = bytes[i + 2];
        } else if (code === 0xa4) {
            data.lorawanRegion = lorawanRegionName(bytes[i + 1]);
        }

        i += len;
    }

    return { data: data, errors: errors };
}

// === Downlinks ===
//
// Spiegel zu backend/src/heizung/services/relay_adapter.py. Die Python-
// Seite ist die Quelle, dieser Abschnitt die Kopie — Drift-Schutz ueber
// backend/tests/test_codec_mirror_16aspm.py (AE-48, §5.28).
function encodeDownlink(input) {
    var data = input.data || {};
    var errors = [];

    // EIN ausschliesslich ueber den Timer (S1). Es gibt hier bewusst
    // KEINEN Weg, 0xC1 mit 01 zu senden — die Zusicherung soll nicht nur
    // im Backend stehen, sondern auch hier nicht umgehbar sein.
    if (typeof data.relay_on_seconds === 'number') {
        var secs = data.relay_on_seconds;
        if (secs < 1 || secs > 65535 || Math.floor(secs) !== secs) {
            errors.push('relay_on_seconds muss eine ganze Zahl 1..65535 sein');
            return { bytes: [], fPort: 1, errors: errors };
        }
        return {
            bytes: [0x57, 0x01, Math.floor(secs / 256), secs % 256],
            fPort: 1,
            errors: errors
        };
    }

    if (data.relay_off === true) {
        return { bytes: [0xc1, 0x00], fPort: 1, errors: errors };
    }

    if (data.get_relay_state === true) {
        return { bytes: [0xb1], fPort: 1, errors: errors };
    }

    if (data.get_relay_timer === true) {
        return { bytes: [0x58], fPort: 1, errors: errors };
    }

    if (data.get_relay_change_reason === true) {
        return { bytes: [0x54], fPort: 1, errors: errors };
    }

    if (typeof data.state_after_power_return === 'string') {
        var mode = data.state_after_power_return;
        var modeByte = -1;
        if (mode === 'last_state') { modeByte = 0x00; }
        if (mode === 'on') { modeByte = 0x01; }
        if (mode === 'off') { modeByte = 0x02; }
        if (modeByte === -1) {
            errors.push('state_after_power_return muss last_state|on|off sein');
            return { bytes: [], fPort: 1, errors: errors };
        }
        return { bytes: [0x5e, modeByte], fPort: 1, errors: errors };
    }

    if (data.get_state_after_power_return === true) {
        return { bytes: [0x5f], fPort: 1, errors: errors };
    }

    // 0x59 — Zustand nach Erholung vom Ueberhitzungsschutz.
    // Nur zwei Werte, und AUS ist hier 0x01 (nicht 0x02 wie bei 0x5E).
    if (typeof data.state_after_overheating_recovery === 'string') {
        var ohMode = data.state_after_overheating_recovery;
        if (ohMode === 'last_state') {
            return { bytes: [0x59, 0x00], fPort: 1, errors: errors };
        }
        if (ohMode === 'off') {
            return { bytes: [0x59, 0x01], fPort: 1, errors: errors };
        }
        errors.push('state_after_overheating_recovery muss last_state|off sein');
        return { bytes: [], fPort: 1, errors: errors };
    }

    if (data.get_state_after_overheating_recovery === true) {
        return { bytes: [0x5a], fPort: 1, errors: errors };
    }

    if (typeof data.keepalive_period_min === 'number') {
        var p = data.keepalive_period_min;
        if (p < 1 || p > 255 || Math.floor(p) !== p) {
            errors.push('keepalive_period_min muss eine ganze Zahl 1..255 sein');
            return { bytes: [], fPort: 1, errors: errors };
        }
        return { bytes: [0x02, p], fPort: 1, errors: errors };
    }

    if (data.get_keepalive_period === true) {
        return { bytes: [0x12], fPort: 1, errors: errors };
    }

    if (data.get_version === true) {
        return { bytes: [0x04], fPort: 1, errors: errors };
    }

    errors.push('no actionable downlink fields in input.data');
    return { bytes: [], fPort: 1, errors: errors };
}
