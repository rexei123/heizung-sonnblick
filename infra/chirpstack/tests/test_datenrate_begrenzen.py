"""Die Obergrenze der Datenrate -- die Zahl, die Geraete aktiv absenkt.

**Der Anlass** ist der Lauf ``funkqualitaet --stunden 720`` vom
27.11.2026: rund zwoelf Geraete mit 4,8 bis 25 Prozent Verlust, bei
SNR-Minima um -10 bis -13 dB. Die Schwelle fuer DR5 (SF7) liegt bei
**-7,5 dB** -- diese Meldungen kommen also unterhalb der Schwelle an
oder gar nicht. 004 verliert ein Viertel, 001 ein Fuenftel.

**Warum eine Zahl in der Region und kein Plugin.** Der
Standard-Algorithmus hat genau eine Stelle, an der er eine Datenrate
**senkt** -- woertlich aus ``chirpstack/src/adr/default.rs`` (4.17.0):

    // Lower the DR only if it exceeds the max. allowed DR.
    if req.dr > max_dr {
        resp.dr = max_dr;
    }

Bei negativen Schritten erhoeht er ausschliesslich die **Sendeleistung**
(``tx_power_index.saturating_sub(1)``); die Datenrate laesst er, wo sie
ist. Ein Geraet, das an der Schwelle wackelt, bleibt deshalb oben --
dauerhaft, von sich aus. Die Grenze ist der einzige Weg nach unten.

**Und sie wirkt aktiv, nicht erst kuenftig.** Die Klammer sitzt vor der
Schrittrechnung und greift bei jedem Durchlauf, an dem ``adr`` gesetzt
ist. Weicht die Antwort von der Anfrage ab, haengt ChirpStack einen
``LinkADRReq`` an (``downlink/data.rs``, ``_request_adr_change``), und
eine anstehende MAC-Anweisung reicht **allein** als Grund fuer einen
Downlink (``_something_to_send``). Jedes Geraet wird also beim naechsten
eigenen Uplink abgesenkt -- bei sechs Meldungen je Stunde binnen zehn
Minuten, ohne Batteriewechsel und ohne Handgriff am Gerät.

**Was diese Datei prueft und was nicht.** Geprueft wird, dass die Zahl
dort steht, dass unsere Konfiguration im echten Abbild laedt und dass
ChirpStack genau diesen Schluessel liest. **Nicht** geprueft wird der
ausgehende ``LinkADRReq`` -- dafuer braeuchte es einen angemeldeten
Gateway, eine ABP-Sitzung und einen Uplink mit gueltigem MIC. Der
Nachweis dafuer ist der Quellcode oben und die Kontrolle nach dem
Rollout (RUNBOOK Paragraph 10bj): die Datenrate der Problemgeraete in
den ChirpStack-Events und ein ``funkqualitaet``-Lauf nach 24 Stunden.
Diese Grenze zu ziehen ist ehrlicher, als einen Test zu behaupten, der
mehr zeigt als er zeigt (Paragraph 5.68).
"""

from __future__ import annotations

import math
import pathlib
import re

import pytest
from conftest import (
    KONFIG,
    baue_konfiguration,
    starte_chirpstack,
)

#: Die Zielgrenze. DR2 ist SF10, Schwelle -15 dB.
ZIEL_DR = 2

#: Der Rahmen, mit dem gerechnet wird: 9 Byte Nutzlast (die gemessene
#: Laenge eines Vicki-Statusberichts, ``gRKdYZmZEeAw`` aus den
#: Live-Frames) plus 13 Byte LoRaWAN -- MHDR, DevAddr, FCtrl, FCnt,
#: FPort, MIC.
RAHMEN_BYTE = 22

#: Meldungen je Geraet und Stunde, und die Zahl der Geraete im Haus.
MELDUNGEN_H = 6
GERAETE = 109

#: Drei Kanaele, nicht acht. ``enabled_uplink_channels = []`` heisst
#: „alle der Region", und die Region definiert **keine**
#: ``extra_channels`` -- es bleiben die drei Vorgabekanaele 868,1 /
#: 868,3 / 868,5 MHz. Wer hier acht annimmt, rechnet die Kanalbelegung
#: um den Faktor 2,7 zu guenstig.
KANAELE = 3


def _sendezeit_s(sf: int, nutzlast_byte: int = RAHMEN_BYTE) -> float:
    """Sendezeit einer LoRa-Meldung in Sekunden (125 kHz, CR 4/5).

    Die Formel steht so im Semtech-Rechenblatt: Symbolzeit ``2**SF/BW``,
    Praeambel ``(8 + 4,25)`` Symbole, dazu die Nutzlast-Symbole. ``DE``
    (low data rate optimize) ist ab SF11 gesetzt, ``CRC`` an, Kopf
    explizit.
    """
    de = 1 if sf >= 11 else 0
    tsym = float(2**sf) / 125_000
    praeambel = (8 + 4.25) * tsym
    zaehler = 8 * nutzlast_byte - 4 * sf + 28 + 16
    nenner = 4 * (sf - 2 * de)
    symbole = 8 + max(math.ceil(zaehler / nenner) * 5, 0)
    return praeambel + symbole * tsym


def _region_text() -> str:
    return (KONFIG / "region_eu868.toml").read_text(encoding="utf-8")


# ---------------------------------------------------------------- Stufe 1


def test_die_obergrenze_der_datenrate_steht_auf_zwei() -> None:
    """**Der Wachposten fuer die Entscheidung vom 27.11.2026.**

    Ein Rueckfall auf 5 waere ohne diesen Test nicht zu bemerken: nichts
    bricht, nichts meldet. Die Geraete wandern ueber Tage wieder nach
    oben, bis sie an der Schwelle wackeln, und der Verlust steht erst im
    naechsten ``funkqualitaet``-Lauf -- vier Wochen spaeter.

    **Die Zahl steht in der Region und nicht im Geraeteprofil**, weil
    ChirpStack sie nur dort kennt (``config.rs``, ``RegionNetwork``). Je
    Geraet ist sie nicht einstellbar; wer das braucht, braucht ein
    ADR-Plugin -- und genau dafuer gibt es eines fuer das Relais.
    """
    zeilen = [z.strip() for z in _region_text().splitlines() if z.strip().startswith("max_dr")]
    assert zeilen == [f"max_dr = {ZIEL_DR}"], (
        f"erwartet genau eine Zeile 'max_dr = {ZIEL_DR}', gefunden: {zeilen}"
    )


def test_die_schwelle_von_dr2_liegt_unter_den_gemessenen_minima() -> None:
    """**Warum 2 und nicht 3** -- die Begruendung, nachrechenbar.

    Die Demodulations-Schwellen sind Hardware und stehen in
    ``config::get_required_snr_for_sf``: DR3 (SF9) -12,5 dB, DR2 (SF10)
    -15 dB. Die schlechtesten Minima im Lauf vom 27.11.2026 sind
    **-13,2 dB** (046) und **-15,8 dB** (056). Eine Grenze bei DR3
    haette genau die zwei Geraete nicht erreicht, um die es geht.

    Und die Minima sind **beschnitten**: Meldungen unterhalb der
    Schwelle kommen nie an und stehen in keiner Statistik. Was gemessen
    ist, ist die Untergrenze des Messbaren, nicht die des Funks -- der
    Abstand nach unten ist also eher zu klein angesetzt als zu gross.

    056 liegt auch unter der DR2-Schwelle. Das ist bewusst nicht der
    Maßstab: sein Minimum stammt aus einem 720-Stunden-Fenster, das die
    Leistungskorrektur vom 16.11.2026 mit einschliesst (Reserve 10 ->
    20, bei 056 neun dB Gewinn). Eine Grenze fuer alle 109 Geraete nach
    dem schlechtesten Wert eines einzelnen Geraets aus der Zeit **vor**
    der Korrektur zu ziehen, waere die falsche Richtung.
    """
    schwelle = {5: -7.5, 3: -12.5, 2: -15.0, 1: -17.5}
    assert schwelle[ZIEL_DR] < -13.2, (
        "die Zielgrenze muss unter dem schlechtesten gemessenen Minimum von 046 liegen, "
        "sonst erreicht sie das Geraet nicht, um das es geht"
    )
    assert schwelle[3] > -13.2, (
        "wenn DR3 unter -13,2 dB liegt, ist die Begruendung fuer DR2 hinfaellig "
        "und dieser Abschnitt gehoert neu geschrieben"
    )


def test_die_funklast_rechnung_im_kommentar_stimmt() -> None:
    """**Die Zahlen in der Regionsdatei sind nachgerechnet, nicht geschaetzt.**

    Eine Sendezeit-Rechnung im Kommentar, die niemand nachrechnet, ist
    eine Behauptung an der Stelle, an der spaeter jemand eine
    Entscheidung darauf stuetzt (Paragraph 5.68). Dieser Test rechnet
    sie aus der Formel und verlangt, dass die Datei dasselbe sagt.

    Faellt er nach einer Aenderung der Grenze, ist nicht die Formel
    falsch -- dann steht im Kommentar noch die Rechnung der alten Zahl.
    """
    region = _region_text()
    sendezeit = {5: _sendezeit_s(7), 3: _sendezeit_s(9), 2: _sendezeit_s(10)}

    for dr, s in sendezeit.items():
        marke = f"{s * 1000:.0f} ms"
        assert marke in region, (
            f"die Sendezeit fuer DR{dr} ist {marke}; der Kommentar nennt sie nicht"
        )

    for dr in (ZIEL_DR, 5):
        anteil = MELDUNGEN_H * sendezeit[dr] / 3600 * 100
        marke = f"{anteil:.3f}".replace(".", ",") + " %"
        assert marke in region, (
            f"der Sendezeit-Anteil je Geraet bei DR{dr} ist {marke}; der Kommentar nennt ihn nicht"
        )
        assert anteil < 1.0, (
            f"DR{dr} reisst mit {anteil:.3f} % die Ein-Prozent-Grenze je Geraet -- "
            "dann ist die Grenze nicht zulaessig"
        )

    last = GERAETE * MELDUNGEN_H * sendezeit[ZIEL_DR] / 3600 / KANAELE * 100
    for wert in (last, last * 2):
        marke = f"{wert:.1f}".replace(".", ",") + " %"
        assert marke in region, f"die Kanalbelegung {marke} steht nicht im Kommentar"


def test_die_region_definiert_keine_zusatzkanaele() -> None:
    """**Die stille Voraussetzung der Funklast-Rechnung.**

    Mit drei Kanaelen ist die Belegung 2,2 %, mit acht waeren es 0,8 %.
    Kommen eines Tages ``extra_channels`` dazu, wird die Rechnung im
    Kommentar zu pessimistisch -- und, schlimmer, jemand liest sie als
    aktuellen Befund. Dann gehoert beides nachgezogen.
    """
    abschnitte = re.findall(
        r"^\s*\[\[regions\.network\.extra_channels\]\]", _region_text(), re.MULTILINE
    )
    assert abschnitte == [], (
        "die Region definiert jetzt Zusatzkanaele -- die Funklast-Rechnung im "
        f"Kommentar geht von {KANAELE} Kanaelen aus und ist nachzuziehen"
    )


# ---------------------------------------------------------------- Stufe 2

#: Ein Wert, den ChirpStack nicht als Zahl lesen kann.
UNLESBAR = 'max_dr = "zwei"'

#: Derselbe unlesbare Wert unter einem Namen, den ChirpStack nicht kennt.
ERFUNDEN = 'max_datenrate = "zwei"'


def _mit_ersetzter_grenze(ersatz: str) -> str:
    region = _region_text()
    kaputt, ersetzt = re.subn(
        rf"^    max_dr = {ZIEL_DR}$", f"    {ersatz}", region, flags=re.MULTILINE
    )
    assert ersetzt == 1, (
        f"erwartet genau eine Zeile 'max_dr = {ZIEL_DR}' zum Umbiegen, gefunden: {ersetzt} -- "
        "ohne sie prueft die Probe nichts"
    )
    return kaputt


def _pruefe_uebergeben(konfig: pathlib.Path, zeile: str) -> None:
    """Die umgebogene Datei ist auch die, die der Behaelter bekommt.

    Ohne diese Zusicherung bliebe die Probe unten gruen, wenn die
    Uebersteuerung nicht ankommt: ChirpStack laeuft dann mit der **guten**
    Datei, und „laeuft" war genau das Erwartete -- gruen aus dem falschen
    Grund (Paragraph 5.55). Gefunden mit der Mutationsprobe, die
    ``region_text`` ignoriert.
    """
    uebergeben = (konfig / "region_eu868.toml").read_text(encoding="utf-8")
    assert zeile in uebergeben, (
        f"die Zeile {zeile!r} steht nicht in der Datei, die der Behaelter bekommt -- "
        "die Uebersteuerung kommt nicht an, und die Probe prueft die gute Fassung"
    )


@pytest.mark.slow
def test_die_grenze_laedt_in_der_echten_engine(
    funk_backend: dict[str, str], tmp_path: pathlib.Path
) -> None:
    """**Die Bedingung, ohne die diese Aenderung nicht ausgerollt wird.**

    Kein Nachbau: ``chirpstack/chirpstack:4`` aus der
    Produktions-Compose, unsere ``chirpstack.toml``, unsere
    ``region_eu868.toml``. Zwei Zusicherungen:

    * Das Protokoll erreicht ``Setting up regions`` -- die Regionsdatei
      wurde gelesen und angenommen.
    * Der Dienst **laeuft danach weiter**. Ein Konfigurationsfehler
      beendet ChirpStack mit Exit 1, und am Server bedeutet das eine
      Neustart-Schleife: am 15.11.2026 sieben Minuten, in denen die
      Anlage nichts verarbeitet hat. Der Unterschied steht nicht in
      einer Textzeile, sondern im Zustand des Dienstes.

    MQTT-Fehler im Protokoll sind **erwartet** und kein Mangel: der Test
    gibt keinen Broker, und ChirpStack laeuft ohne ihn weiter.
    """
    konfig = tmp_path / "cfg"
    baue_konfiguration(konfig, funk_backend)
    protokoll, status, code = starte_chirpstack(funk_backend, konfig)

    assert "Setting up regions" in protokoll, (
        f"ChirpStack ist nicht bis zu den Regionen gekommen.\nProtokoll:\n{protokoll[-2000:]}"
    )
    assert status == "running", (
        f"ChirpStack ist beendet (Status {status}, Exit {code}) -- am Server waere das "
        f"eine Neustart-Schleife.\nProtokoll:\n{protokoll[-2000:]}"
    )


@pytest.mark.slow
def test_ein_unlesbarer_wert_bricht_den_start_ab(
    funk_backend: dict[str, str], tmp_path: pathlib.Path
) -> None:
    """**Die Probe, die „die Einstellung wird geladen" beweisbar macht.**

    Dass der Dienst mit unserer Konfiguration laeuft, zeigt noch nicht,
    dass er *diese Zeile* liest. Hier wird der **Wert** unlesbar gemacht:
    liest ChirpStack ``regions.network.max_dr``, kann es ``"zwei"`` nicht
    als ``u8`` deuten und bricht ab.

    **Und die Probe faengt den Tippfehler mit.** Stuende der Schluessel
    falsch in unserer Datei, traefe die Ersetzung ebenfalls den falschen
    Namen -- der wird stillschweigend uebergangen (siehe die naechste
    Probe), der Dienst startet, und dieser Test wird rot.
    """
    konfig = tmp_path / "cfg-unlesbar"
    baue_konfiguration(konfig, funk_backend, region_text=_mit_ersetzter_grenze(UNLESBAR))
    _pruefe_uebergeben(konfig, UNLESBAR)
    protokoll, status, code = starte_chirpstack(funk_backend, konfig)

    assert status == "exited" and code == 1, (
        "ChirpStack hat einen unlesbaren max_dr-Wert hingenommen -- dann liest es den "
        f"Schluessel nicht, und die Grenze waere wirkungslos. Status {status}, Exit {code}."
        f"\nProtokoll:\n{protokoll[-2000:]}"
    )
    assert "max_dr" in protokoll, (
        "der Abbruch nennt max_dr nicht -- dann ist es ein anderer Fehler als der "
        f"erwartete.\nProtokoll:\n{protokoll[-2000:]}"
    )


@pytest.mark.slow
def test_ein_unbekannter_schluessel_wird_stillschweigend_uebergangen(
    funk_backend: dict[str, str], tmp_path: pathlib.Path
) -> None:
    """**Warum ein Tippfehler hier teuer ist -- gemessen, nicht vermutet.**

    ``RegionNetwork`` traegt ``#[serde(default)]``, und ``impl Default``
    setzt ``max_dr: 0`` (``config.rs``). Ein verschriebener Name waere
    damit nicht wirkungslos, sondern **DR0** fuer alle Geraete: SF12,
    1,5 s Sendezeit je Meldung, rund 9 % Kanalbelegung. Lautlos, mit
    gruenem Behaelter.

    Dieser Test haelt diese Eigenschaft fest -- er ist die Begruendung
    fuer die Probe davor. Wird er eines Tages rot, weil ChirpStack
    unbekannte Schluessel ablehnt, ist der Tippfehler kein stilles
    Risiko mehr, und der Warnkasten in der Regionsdatei gehoert
    gestrichen (Paragraph 5.77).
    """
    konfig = tmp_path / "cfg-erfunden"
    baue_konfiguration(konfig, funk_backend, region_text=_mit_ersetzter_grenze(ERFUNDEN))
    _pruefe_uebergeben(konfig, ERFUNDEN)
    protokoll, status, code = starte_chirpstack(funk_backend, konfig)

    assert status == "running", (
        "ChirpStack hat einen unbekannten Schluessel abgelehnt (Status "
        f"{status}, Exit {code}). Das waere eine gute Nachricht -- dann ist ein "
        "Tippfehler nicht mehr still, und die Begruendung der Probe davor gehoert "
        f"neu geschrieben.\nProtokoll:\n{protokoll[-2000:]}"
    )
