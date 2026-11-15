/**
 * Feste Datenrate fuer das Geraeteprofil "Relais 16ASPM".
 *
 * AUSGEROLLT AM 16.11.2026. Die Entscheidung hing an der Messung am
 * Endplatz (RUNBOOK Paragraph 10au), und das Kriterium ist seit dem
 * 12.11.2026 erfuellt: Relais 108 verlor an diesem Vormittag **16 Prozent**
 * seiner Meldungen (4 von 25), der Fuehler 056 im selben Raum **3,6
 * Prozent**, der Fuehler 027 an der Bar **0**.
 *
 * Die Datei stand bis dahin auf DR3 -- gebaut gegen das Problem von 109,
 * das auf DR5 festhing. Fuer 108 waere das wirkungslos gewesen: ChirpStacks
 * Standard-Algorithmus hatte es am 12.11. um 09:04 auf DR2 und um 09:27 auf
 * **DR3** hochgezogen, und dort trug der Link nicht mehr. Ziel ist deshalb
 * **DR1**.
 *
 * ## Warum ein Plugin und kein Geraetebefehl
 *
 * Es gibt im 16ASPM-Befehlssatz **keinen** Befehl fuer ADR, Datenrate,
 * Spreizfaktor oder Sendeleistung. Die Hersteller-Seite "network-related
 * settings" dokumentiert vier Befehle: 0x10/0x19 (Join-Wiederholung),
 * 0x1C/0x1D (Funk-Wachhund), 0x11/0x1B (Uplink-Art) und 0xA4 (Region,
 * nur lesbar). Und ChirpStacks Warteschlange nimmt
 * Anwendungs-Nutzlasten -- LinkADRReq ist ein MAC-Befehl, den der Server
 * selbst schickt.
 *
 * ## Warum die Geraete dort landen, wo sie landen
 *
 * ADR laeuft nur, wenn das **Geraet** das ADR-Bit setzt -- und beide
 * Relais setzen es, am 12.11. zweimal mit ``LinkADRReq acknowledged``
 * belegt. Der Standard-Algorithmus **senkt die Datenrate nie**, er erhoeht
 * sie nur, und er **senkt die Sendeleistung**, sobald die Reserve gut
 * aussieht. 109 ist einmal auf DR5 hochgezogen worden und bleibt dort,
 * auch bei RSSI -113 dBm; 108 ist auf DR3 gezogen worden und hat dort 16
 * Prozent verloren.
 *
 * **Die strukturelle Schwaeche:** der Algorithmus rechnet auf den
 * Meldungen, die **ankommen**. Die ausgefallenen sieht er nicht. Er kann
 * sich also in eine Einstellung hineinoptimieren, aus der er nicht
 * zurueckfindet -- und bei Funkstille hat er gar keine Datenpunkte mehr.
 * Das ist keine Fehlfunktion, das ist der Algorithmus.
 *
 * ## Was dieses Plugin tut
 *
 * DR1 (SF11) festnageln, jeden Uplink zweimal senden lassen (nbTrans 2),
 * bei voller Sendeleistung (txPowerIndex 0).
 *
 * **Warum DR1 und nicht DR0.** DR1 gibt 5 dB gegen DR3, DR0 gaebe 7,5 --
 * aber DR0 verbraucht bei nbTrans 2 die halbe Duty-Cycle-Grenze (0,49
 * Prozent) und laesst fuer Antworten und Wiederholungen keinen Platz. DR1
 * liegt bei 0,25 Prozent. DR0 bleibt der Rueckfall, falls DR1 noch
 * verliert.
 *
 * **Nur fuer das Relais-Profil.** Zugewiesen wird es je Geraeteprofil
 * ueber adr_algorithm_id; die rund hundert Vickis bleiben beim
 * Standard-Algorithmus. Eine Aenderung in region_eu868.toml waere
 * regionsweit und damit das Gegenteil davon (min_dr/max_dr gelten fuer
 * **alle** Geraete).
 *
 * ## Sendezeit, gerechnet
 *
 * Bei 26 Byte Nutzlast und BW 125 kostet ein Uplink bei SF7 82 ms, bei
 * SF9 267 ms und bei **SF11 (DR1) 740 ms**. Mit Keepalive alle zehn
 * Minuten und nbTrans 2 sind das 1,48 s je Vorgang, also 8,9 s/h und
 * **0,25 %** -- ein Viertel der 1-%-Grenze.
 *
 * Zum Vergleich DR0 (SF12, 1483 ms): 0,49 %, also die Haelfte der Grenze.
 * Das ist der Grund fuer DR1, und Sendezeit ist damit das einzige
 * Argument, das hier ueberhaupt eines ist -- das Relais haengt an der
 * Netzspannung, Batterie spart hier niemand.
 *
 * Teurer wird dagegen ein Downlink in RX1: er nimmt die Datenrate des
 * Uplinks, also 165 ms statt 51 ms. Das bleibt weit unter den 1319 ms,
 * die ein Class-C-Downlink ueber RX2 bei DR0/SF12 ohnehin kostet.
 *
 * ## Rueckweg
 *
 * Im Geraeteprofil den Algorithmus zurueck auf "Default ADR algorithm"
 * stellen; danach wirkt dieses Plugin fuer das Profil nicht mehr. Die
 * Datenrate der bereits beigetretenen Geraete zieht der
 * Standard-Algorithmus wieder hoch, sobald der Link es erlaubt. Den
 * Eintrag in chirpstack.toml zu entfernen ist der zweite Schritt und
 * verlangt einen Neustart von ChirpStack.
 *
 * ## Form
 *
 * ChirpStack fuehrt die Datei als **Skript** aus (rquickjs), nicht als
 * Modul: keine export-Anweisungen, keine Klassen, keine Rust-Typen.
 * Deshalb drei einfache Funktionen. Die Felder von req und der Antwort
 * stehen in der ChirpStack-Doku "Adaptive data-rate (ADR)" und im
 * Beispiel examples/adr_plugins/plugin_skeleton.js des Projekts
 * (abgerufen 02.11.2026).
 */

/** Anzeigename im Geraeteprofil. */
function name() {
  return "Relais 16ASPM: feste Datenrate DR1, zwei Wiederholungen";
}

/**
 * Kennung. Sie steht im Geraeteprofil als adr_algorithm_id und darf
 * sich nicht mehr aendern, sobald ein Profil sie benutzt -- ein Profil
 * mit unbekannter Kennung faellt auf den Standard zurueck, und zwar
 * stillschweigend.
 */
function id() {
  return "relais_fest_dr1";
}

/** Zieldatenrate: DR1 ist SF11 in EU868. */
var ZIEL_DR = 1;

/** Jeden Uplink zweimal. Gegen Einzelverluste, nicht gegen schlechten Link. */
var WIEDERHOLUNGEN = 2;

function handle(req) {
  // Das Geraet hat ADR nicht angefordert: nichts aendern. ChirpStack
  // ruft den Algorithmus in diesem Fall gar nicht erst auf; die
  // Pruefung steht hier, damit das Plugin auch dann nichts behauptet,
  // wenn eine spaetere Fassung es doch tut.
  if (!req.adr) {
    return {
      dr: req.dr,
      txPowerIndex: req.txPowerIndex,
      nbTrans: req.nbTrans,
    };
  }

  // Die Region gibt die Grenzen vor (min_dr/max_dr aus
  // region_eu868.toml). Ein DR ausserhalb davon waere ein LinkADRReq,
  // den das Geraet ablehnen muss -- und ein abgelehnter LinkADRReq
  // bedeutet, dass die Datenrate bleibt, wie sie war, ohne Hinweis.
  var dr = ZIEL_DR;
  if (dr < req.minDr) {
    dr = req.minDr;
  }
  if (dr > req.maxDr) {
    dr = req.maxDr;
  }

  return {
    dr: dr,
    // 0 ist die **hoechste** Sendeleistung. Bei einem Link an der Grenze
    // ist das die richtige Wahl; Strom spart hier niemand, das Relais
    // haengt an der Netzspannung.
    txPowerIndex: 0,
    nbTrans: WIEDERHOLUNGEN,
  };
}
