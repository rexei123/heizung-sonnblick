"""Die Gruende einer Aufhebung heissen im Frontend wie im Backend (T1.7).

**Warum es diesen Test gibt.** Die Historie im Frontend ordnete den
``revoked_reason`` ueber ein Textmuster zu — ``startsWith("auto")`` —, und
zwei von fuenf Werten fallen durch dieses Muster, weil sie nicht mit
``auto`` beginnen: ``superseded`` und ``room_override_blocked``. Beide sind
**automatische** Vorgaenge und erschienen als „manuell aufgehoben". In der
Historie von Zimmer 306 (21./22.10.2026, zwoelf Drehungen in sechzehn
Stunden) stand damit elfmal eine falsche Tatsachenbehauptung.

Seit T1.7 ist es eine **Tabelle mit genauen Schluesseln**
(``frontend/src/lib/api/aufhebungsgrund.ts``). Genaue Schluessel sind
praeziser als ein Muster — und zerbrechlicher: wer eine Konstante im
Backend umbenennt, laesst die Oberflaeche stumm auf den Rohwert
zurueckfallen. Dieser Test ist der Ersatz fuer die Pruefung, die niemand
von sich aus macht.

Dieselbe Form wie der Spiegel der Override-Quellen (#330): der Test liest
**beide** Seiten aus dem Quelltext und vergleicht sie, statt eine Liste
zu pflegen, die selbst auseinanderlaufen koennte (Paragraph 5.53).

**Was er nicht prueft:** ob der deutsche Text passend ist. Das ist eine
Frage des Geschmacks und des Betriebs; der Test prueft die Zuordnung.
"""

from __future__ import annotations

import pathlib
import re

from heizung.services.override_pms_hook import REVOKE_REASON_CHECKOUT
from heizung.services.override_service import (
    REVOKE_REASON_EXPIRED,
    REVOKE_REASON_ROOM_BLOCKED,
    REVOKE_REASON_SUPERSEDED,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
TABELLE = REPO / "frontend" / "src" / "lib" / "api" / "aufhebungsgrund.ts"

#: Die Gruende, die der Quellcode **schreibt** — je mit der Stelle, die
#: ihn schreibt. Der Vorgabewert von ``revoke_all_active_overrides``
#: (``REVOKE_REASON_CHECKOUT_FALLBACK``) steht bewusst **nicht** dabei:
#: kein Aufrufer verwendet ihn, und eine Zeile fuer einen Wert, den es im
#: Betrieb nicht gibt, waere genau die Sorte Doku, die T1.7 aufgeraeumt
#: hat.
GESCHRIEBENE_GRUENDE: dict[str, str] = {
    REVOKE_REASON_SUPERSEDED: "override_service._beende_aeltere_im_selben_bereich",
    REVOKE_REASON_CHECKOUT: "override_pms_hook.auto_revoke_on_checkout",
    REVOKE_REASON_ROOM_BLOCKED: "api/v1/rooms.set_override_block_state",
    REVOKE_REASON_EXPIRED: "override_service.cleanup_expired",
}


def _schluessel_der_tabelle() -> set[str]:
    """Die Schluessel aus ``AUFHEBUNGSGRUND``, aus dem Quelltext gelesen.

    Gelesen statt gepflegt: eine Liste hier waere die dritte Stelle, an
    der dieselben Zeichenketten stehen.
    """
    quelle = TABELLE.read_text(encoding="utf-8")
    beginn = quelle.index("export const AUFHEBUNGSGRUND")
    ende = quelle.index("\n};", beginn)
    block = quelle[beginn:ende]
    # Schluessel mit und ohne Anfuehrungszeichen: ``superseded:`` und
    # ``"auto: expired":`` — der zweite braucht sie wegen des Doppelpunkts.
    mit = set(re.findall(r'"([^"]+)":\s*"', block))
    ohne = set(re.findall(r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s", block, re.MULTILINE))
    schluessel = mit | ohne
    assert schluessel, "AUFHEBUNGSGRUND leer oder Parser passt nicht mehr"
    return schluessel


def test_jeder_geschriebene_grund_hat_einen_text() -> None:
    """Die Richtung, die den Befund von T1.7 verhindert haette."""
    tabelle = _schluessel_der_tabelle()
    fehlend = {
        grund: stelle for grund, stelle in GESCHRIEBENE_GRUENDE.items() if grund not in tabelle
    }
    assert not fehlend, (
        f"Gruende ohne Text in AUFHEBUNGSGRUND (die Oberflaeche zeigt den Rohwert): {fehlend}"
    )


def test_kein_text_fuer_einen_grund_den_niemand_schreibt() -> None:
    """Die Gegenrichtung: ein Text fuer einen Code, den es nicht gibt.

    Er ist harmlos — aber er behauptet, es gaebe diesen Vorgang, und wer
    die Tabelle liest, glaubt es. Dieselbe Klasse wie Paragraph 5.77.
    """
    ueberzaehlig = _schluessel_der_tabelle() - set(GESCHRIEBENE_GRUENDE)
    assert not ueberzaehlig, (
        "Texte fuer Gruende, die kein Aufrufer schreibt — entweder die "
        f"Stelle nachtragen oder den Eintrag entfernen: {sorted(ueberzaehlig)}"
    )


def test_die_tabelle_vergleicht_genaue_schluessel_und_kein_muster() -> None:
    """Kein ``startsWith`` mehr, und zwar belegt.

    Der Fehler war das Muster und nicht einer seiner Zweige. Ein Test, der
    nur die Zuordnung prueeft, haette den Rueckfall auf ein Muster nicht
    bemerkt — es haette fuer die vier bekannten Werte dasselbe Ergebnis
    geliefert und beim fuenften wieder geraten.
    """
    quelle = TABELLE.read_text(encoding="utf-8")
    code = "\n".join(
        zeile
        for zeile in quelle.splitlines()
        # Kommentare und Docstring-Zeilen beschreiben den alten Fehler
        # ausdruecklich — sie sollen ihn nennen duerfen.
        if not zeile.lstrip().startswith(("*", "//", "/*"))
    )
    for muster in ("startsWith(", "includes(", "endsWith("):
        assert muster not in code, (
            f"{muster} ist zurueck in der Zuordnung — T1.7 hat genau das ersetzt"
        )


def test_unbekanntes_bleibt_rohwert() -> None:
    """Die Vorgabe des Betreibers, im Quelltext belegt.

    Ein unbekannter Wert ist entweder ein neuer Code aus dem Backend oder
    ein Freitext aus der Oberflaeche. „Manuell aufgehoben" waere im ersten
    Fall falsch, im zweiten nutzlos — der Rohwert ist in beiden richtig.
    """
    quelle = TABELLE.read_text(encoding="utf-8")
    assert "AUFHEBUNGSGRUND[grund] ?? grund" in quelle, (
        "der Rueckfall auf den Rohwert ist weg — dann behauptet die "
        "Oberflaeche bei einem neuen Code etwas Falsches"
    )
