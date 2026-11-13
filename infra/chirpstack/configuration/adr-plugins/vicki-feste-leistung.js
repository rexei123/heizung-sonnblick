/**
 * Feste Sendeleistung fuer Vickis in Randlage, Datenrate weiter adaptiv.
 *
 * ## Der Anlass, 12./13.11.2026
 *
 * Fuehler 056 (Zone Eingang, Rezeption) hat von 14:41 bis 04:44 **keine
 * einzige** Meldung geschickt -- vierzehn Stunden, Zaehlerstand 2904 auf
 * 2988, also **83 verlorene Frames**. Die Zone fuehrt ein Relais in
 * Betrieb; sie wurde in dieser Zeit nicht geheizt.
 *
 * Es lag nicht an der Entfernung und nicht am Gateway. Es lag an der
 * **Sendeleistung**, die ChirpStacks Standard-Algorithmus Schritt fuer
 * Schritt weggenommen hatte:
 *
 *   06.11.        tx_power_index 6   ca.  4 dBm
 *   07.11.-12.11. tx_power_index 7   ca.  2 dBm   <- hier riss der Link
 *   13.11. 06:44  tx_power_index 1   ca. 14 dBm   (Korrektur des Algorithmus)
 *
 * Am selben Platz, ohne dass jemand etwas bewegt hat, verbesserte sich
 * daraufhin RSSI von -113 auf **-104 dBm** und SNR von -0,2 auf **+8,2
 * dB**. Neun dB, allein aus der Leistung.
 *
 * **Und der Algorithmus holt sie sich wieder.** Gemessen am 13.11.
 * zwischen 06:44 und 07:54: Index 1, 2, 3, 4, 5 -- fuenf Stufen in 70
 * Minuten, auf dem Weg zurueck zu 7. Der Ausfall wiederholt sich also
 * von selbst.
 *
 * ## Warum der Algorithmus das tut, und warum es hier falsch ist
 *
 * Er rechnet auf den Meldungen, die **ankommen**, und sieht die
 * ausgefallenen nicht. Der Link sieht von innen besser aus als er ist;
 * sinkt die Reserve auf null, hat er keine Datenpunkte mehr und kann sich
 * nicht korrigieren. Dass 056 heute frueh zurueckkam, war Zufall: um
 * 04:44 kam **ein** Frame durch.
 *
 * Die Abwaegung dahinter -- Batterie gegen Reserve -- ist im Haus falsch
 * entschieden. Eine Vicki haelt mit zwei AA-Zellen eine Saison; eine
 * verlorene Meldung kostet Regelung. Bei 90 von 109 Geraeten steht der
 * Index auf 7, und im Mittel geht das gut; an den Raendern nicht.
 *
 * ## Was dieses Plugin tut -- und was ausdruecklich nicht
 *
 * Volle Sendeleistung (``txPowerIndex 0``) festnageln. **Die Datenrate
 * bleibt adaptiv**: ``dr`` wird unveraendert zurueckgegeben, der Server
 * darf sie weiter nach oben ziehen.
 *
 * Das ist der Unterschied zum Relais-Plugin daneben, und er hat einen
 * Grund. Bei 056 war der Verlust mit voller Leistung **3,6 Prozent** --
 * die Leistung ist der Hebel, nicht der Spreizfaktor. Eine feste niedrige
 * Datenrate waere zusaetzliche Sendezeit ohne belegten Nutzen, und
 * Sendezeit kostet bei einem Batteriegeraet Energie.
 *
 * ``nbTrans`` bleibt aus demselben Grund bei **1**: jede Wiederholung
 * verdoppelt die Sendeenergie. Beim Relais ist das anders, dort haengt
 * das Geraet an der Netzspannung.
 *
 * ## Warum ein eigenes Geraeteprofil und nicht das Profil "Heizung"
 *
 * Ein Plugin wird je **Geraeteprofil** zugewiesen. Es dem Profil
 * "Heizung" zu geben hiesse, rund hundert Vickis gleichzeitig auf volle
 * Leistung zu stellen -- eine Entscheidung ueber Batterielaufzeiten im
 * ganzen Haus, die ihre eigene Messung braucht (Pilotgruppe, RUNBOOK
 * Paragraph 10av).
 *
 * Deshalb ein Profil "Heizung - feste Leistung (Randlage)" als Kopie, mit
 * genau einem geaenderten Feld, und darin zunaechst **nur 056**.
 *
 * **Der Preis, und er gehoert aufgeschrieben:** ein Geraet in diesem
 * Profil haengt nicht mehr am Profil "Heizung". Wer dort spaeter etwas
 * aendert -- Uplink-Intervall, Class, Regionalparameter --, aendert es
 * fuer dieses Geraet **nicht**. Der Profilname sagt das, und RUNBOOK
 * Paragraph 10av fuehrt die Liste.
 *
 * ## Rueckweg
 *
 * Geraet zurueck auf das Profil "Heizung" -- wirkt sofort, ohne
 * Neustart. Der Standard-Algorithmus nimmt die Leistung dann innerhalb
 * einer Stunde wieder weg (gemessen: fuenf Stufen in 70 Minuten).
 *
 * ## Form
 *
 * ChirpStack fuehrt die Datei als **Skript** aus (rquickjs), nicht als
 * Modul: keine export-Anweisungen, keine Klassen. Deshalb drei einfache
 * Funktionen. Die Felder von req und der Antwort stehen in der
 * ChirpStack-Doku "Adaptive data-rate (ADR)" und im Beispiel
 * examples/adr_plugins/plugin_skeleton.js des Projekts.
 */

/** Anzeigename im Geraeteprofil. */
function name() {
  return "Vicki Randlage: feste Sendeleistung, Datenrate adaptiv";
}

/**
 * Kennung. Sie steht im Geraeteprofil als adr_algorithm_id und darf sich
 * nicht mehr aendern, sobald ein Profil sie benutzt -- ein Profil mit
 * unbekannter Kennung faellt stillschweigend auf den Standard zurueck.
 */
function id() {
  return "vicki_feste_leistung";
}

/** 0 ist die **hoechste** Sendeleistung (MaxEIRP ohne Abzug). */
var ZIEL_LEISTUNG = 0;

function handle(req) {
  // Das Geraet hat ADR nicht angefordert: nichts aendern. ChirpStack
  // ruft den Algorithmus in diesem Fall gar nicht erst auf; die Pruefung
  // steht hier, damit das Plugin auch dann nichts behauptet, wenn eine
  // spaetere Fassung es doch tut.
  if (!req.adr) {
    return {
      dr: req.dr,
      txPowerIndex: req.txPowerIndex,
      nbTrans: req.nbTrans,
    };
  }

  return {
    // **Unveraendert durchgereicht**, und das ist der Kern dieses
    // Plugins. Haette hier eine Zahl gestanden, waere es ein zweites
    // Relais-Plugin mit anderem Namen.
    dr: req.dr,
    txPowerIndex: ZIEL_LEISTUNG,
    // Eine Wiederholung, nicht zwei: jede kostet bei einem
    // Batteriegeraet doppelte Sendeenergie, und der Hebel ist die
    // Leistung.
    nbTrans: 1,
  };
}
