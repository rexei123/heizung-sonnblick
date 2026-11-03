/**
 * Feste Datenrate fuer das Geraeteprofil "Relais 16ASPM".
 *
 * VORBEREITET, NICHT AUSGEROLLT (Stand 02.11.2026). Die Entscheidung
 * haengt an der Messung am Endplatz, RUNBOOK Paragraph 10au. Eingebaut
 * wird im Rotationsfenster am Mittwoch, nicht zwischendurch.
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
 * ## Warum 109 auf SF7 festhaengt
 *
 * ADR laeuft nur, wenn das **Geraet** das ADR-Bit setzt, und
 * ChirpStacks Standard-Algorithmus **senkt die Datenrate nie** -- er
 * erhoeht sie nur. 109 ist einmal auf DR5 hochgezogen worden und bleibt
 * dort, auch bei RSSI -113 dBm. Das ist keine Fehlfunktion, das ist der
 * Algorithmus.
 *
 * ## Was dieses Plugin tut
 *
 * DR3 (SF9) festnageln und jeden Uplink zweimal senden lassen
 * (nbTrans 2), bei voller Sendeleistung (txPowerIndex 0).
 *
 * **Nur fuer das Relais-Profil.** Zugewiesen wird es je Geraeteprofil
 * ueber adr_algorithm_id; die rund hundert Vickis bleiben beim
 * Standard-Algorithmus. Eine Aenderung in region_eu868.toml waere
 * regionsweit und damit das Gegenteil davon (min_dr/max_dr gelten fuer
 * **alle** Geraete).
 *
 * ## Sendezeit, gerechnet
 *
 * Bei 26 Byte Nutzlast und BW 125 kostet ein Uplink bei SF7 82 ms und
 * bei SF9 267 ms. Mit Keepalive alle zehn Minuten und nbTrans 2 sind das
 * 3,2 s/h, also 0,09 % -- die 1-%-Grenze ist nicht in Sicht. Sendezeit
 * ist hier kein Argument gegen irgendetwas.
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
  return "Relais 16ASPM: feste Datenrate DR3, zwei Wiederholungen";
}

/**
 * Kennung. Sie steht im Geraeteprofil als adr_algorithm_id und darf
 * sich nicht mehr aendern, sobald ein Profil sie benutzt -- ein Profil
 * mit unbekannter Kennung faellt auf den Standard zurueck, und zwar
 * stillschweigend.
 */
function id() {
  return "relais_fest_dr3";
}

/** Zieldatenrate: DR3 ist SF9 in EU868. */
var ZIEL_DR = 3;

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
