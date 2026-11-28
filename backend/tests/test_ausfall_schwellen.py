"""Alle Ausfall-Meldungen warten 180 Minuten (Betreiber, 28.11.2026).

**Die Entscheidung.** Drei Meldungen sagen „etwas ist ausgefallen", und
sie warteten unterschiedlich lang: die Zone 30 Minuten, das Haus 15, das
einzelne Geraet 180. Seit dem 28.11.2026 warten alle drei **180
Minuten**. Die Entscheidung ist die des Betreibers; dieser Testsatz
haelt sie fest und begruendet sie nicht neu.

| Meldung | Einstellung | vorher | jetzt |
|---|---|---|---|
| Zone ohne Fuehlerwert | ``relais_zone_stumm_min`` | 30 min | **180 min** |
| Keine Messwerte (Totalausfall) | ``totalausfall_min`` | 15 min | **180 min** |
| Thermostat meldet sich nicht | ``health_degraded_max_age_h`` | 3 h | **3 h** |

Die dritte Zeile hat sich **nicht** geaendert — 3 Stunden sind 180
Minuten, die Vorgabe des Betreibers war dort schon erfuellt. Der Test
unten prueft sie trotzdem mit: ohne ihn waere die Gleichheit der drei
Zahlen eine Behauptung in einem Kommentar statt eine Zusicherung.

**Was ausdruecklich nicht wartet.** Schutzausloesung, warmes Gehaeuse und
volle Platte melden unveraendert sofort. Sie sind keine Ausfaelle ueber
Zeit, sondern Ereignisse: ein Relais, dessen Schutz ausgeloest hat, hat
ausgeloest — Warten macht die Aussage nicht sicherer, nur spaeter. Der
Import-Waechter am Ende dieser Datei haelt das fest.

**Was nicht hier steht.** Wie sich die Melder **an** ihrer Grenze
verhalten (inklusiv oder exklusiv, welcher Grund vor welchem kommt),
pruefen ``test_relais_zone_melder.py`` und ``test_funkempfang.py`` mit
eigenen Pruefstand-Werten. Diese Datei prueft ausschliesslich die
**Betriebsvorgaben** und ihre Validatoren.

Reine Funktionen und Settings, keine Datenbank.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from heizung.config import (
    AUSFALL_MELDUNG_MIN_MIN,
    VERALTUNGS_FAKTOR,
    Settings,
    get_settings,
)
from heizung.services import funkempfang, relais_zone_melder
from heizung.tasks.health_tasks import _basis_state_from_age, health_schwellen

#: Die Vorgabe des Betreibers vom 28.11.2026, in Minuten.
VORGABE_MIN = 180

NOW = datetime(2026, 11, 28, 12, 0, 0, tzinfo=UTC)

#: Die drei Melder-Module, die ein Ereignis sofort melden. Sie duerfen
#: keine der Wartezeiten kennen.
EREIGNIS_MELDER = (
    "tasks/schutz_tasks.py",
    "tasks/gehaeuse_tasks.py",
    "tasks/platten_tasks.py",
)

#: Die Namen, an denen eine Wartezeit haengt.
WARTEZEITEN = (
    "relais_zone_stumm_min",
    "totalausfall_min",
    "health_degraded_max_age_h",
    "AUSFALL_MELDUNG_MIN_MIN",
)


@pytest.fixture(autouse=True)
def _frische_settings() -> None:
    """Die Vorgaben, nicht die Umgebung des Entwicklers.

    ``get_settings`` ist ``lru_cache``-gepuffert, und frueher gelaufene
    Tests setzen Umgebungsvariablen. Ohne diesen Griff pruefte der Satz
    unter Umstaenden einen Stand, den niemand konfiguriert hat.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 1. Die drei Zahlen
# ---------------------------------------------------------------------------


def test_alle_drei_ausfall_meldungen_warten_dieselbe_zeit() -> None:
    """**Der Wachposten fuer die Entscheidung vom 28.11.2026.**

    Ohne diesen Test waere ein Rueckfall auf 30 oder 15 Minuten nicht zu
    bemerken: die Suite blieb gruen, weil jeder Melder seine eigene
    Grenze korrekt einhaelt — nur eben eine andere als bestellt.
    """
    s = get_settings()
    assert s.relais_zone_stumm_min == VORGABE_MIN, "Zone ohne Fuehlerwert"
    assert s.totalausfall_min == VORGABE_MIN, "Keine Messwerte"
    assert s.health_degraded_max_age_h * 60 == VORGABE_MIN, "Thermostat meldet sich nicht"


# ---------------------------------------------------------------------------
# 2. Und sie wirken auch — eine Minute davor, eine danach
# ---------------------------------------------------------------------------


def test_die_zone_meldet_erst_nach_der_vorgabe() -> None:
    """Gegen die **Betriebsvorgabe**, nicht gegen einen Pruefstand-Wert.

    Das ist der Unterschied zu ``test_relais_zone_melder.py``: dort
    bekommt ``beurteile`` eine Zahl uebergeben, hier kommt sie aus den
    Settings. Ohne diesen Test waere eine Vorgabe denkbar, die kein
    Melder liest.
    """
    grenze = get_settings().relais_zone_stumm_min

    def _urteil(alter_min: int) -> relais_zone_melder.ZonenBefund:
        return relais_zone_melder.beurteile(
            zone_id=1,
            zone_name="Barbereich",
            ort="Bar",
            fuehler=("027 Bar",),
            letzte_meldung=NOW - timedelta(minutes=alter_min),
            relais=("109 Panel",),
            relais_letzte_meldung=NOW,
            now=NOW,
            grenze_min=grenze,
        )

    assert _urteil(grenze - 1).grund is None, "179 Minuten melden noch nicht"
    assert _urteil(grenze).grund is None, "die Grenze selbst meldet noch nicht"
    assert _urteil(grenze + 1).grund == relais_zone_melder.GRUND_STUMM, "181 Minuten muessen melden"


def test_das_geraet_meldet_erst_nach_der_vorgabe() -> None:
    """Die Mail haengt am Uebergang nach ``silent``.

    ``degraded`` ist ausdruecklich stumm (AE-53) — ein Geraet, das 179
    Minuten schweigt, steht in der Oberflaeche und nicht im Postfach.
    """
    schwellen = health_schwellen()
    knapp_davor = NOW - timedelta(minutes=VORGABE_MIN - 1)
    knapp_danach = NOW - timedelta(minutes=VORGABE_MIN + 1)

    assert _basis_state_from_age(knapp_davor, NOW, schwellen) == "degraded"
    assert _basis_state_from_age(knapp_danach, NOW, schwellen) == "silent"


def test_der_totalausfall_mailt_erst_nach_der_vorgabe() -> None:
    """Die Kachel und die Mail trennen sich seit dem 28.11.2026 deutlich.

    Rot ist die Kachel nach ``funkempfang_gelb_max_min`` (15 min),
    gemailt wird nach ``totalausfall_min`` (180). Zwischen den beiden
    Zahlen liegen dreieinviertel Stunden, in denen die Oberflaeche den
    Ausfall zeigt und niemand geweckt wird — das ist gewollt und der
    Grund, warum die Kachel nicht mitgewandert ist.

    Der Vergleich selbst steht in ``funk_tasks._run_totalausfall``; was
    hier geprueft wird, sind seine beiden Eingangsgroessen.
    """
    s = get_settings()

    def _befund(alter_min: int) -> funkempfang.Funkempfang:
        return funkempfang.beurteile(
            letzte_meldung=NOW - timedelta(minutes=alter_min),
            meldungen=0,
            now=NOW,
            gruen_max_min=s.funkempfang_gruen_max_min,
            gelb_max_min=s.funkempfang_gelb_max_min,
        )

    frueh = _befund(s.totalausfall_min - 1)
    assert frueh.ist_totalausfall, "die Kachel ist lange rot"
    assert frueh.alter_min is not None and frueh.alter_min < s.totalausfall_min, (
        "179 Minuten duerfen nicht mailen"
    )

    spaet = _befund(s.totalausfall_min + 1)
    assert spaet.alter_min is not None and spaet.alter_min >= s.totalausfall_min, (
        "181 Minuten muessen mailen"
    )

    assert s.funkempfang_gelb_max_min < s.totalausfall_min, (
        "die Kachel muss vor der Mail rot sein, nicht danach"
    )


# ---------------------------------------------------------------------------
# 3. Die Validatoren — Start-Fehler statt stiller Fehlbedienung
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("feld", "wert"),
    [
        ("relais_zone_stumm_min", AUSFALL_MELDUNG_MIN_MIN - 1),
        ("relais_zone_stumm_min", 1),
        ("totalausfall_min", AUSFALL_MELDUNG_MIN_MIN - 1),
        ("totalausfall_min", 1),
    ],
)
def test_eine_wartezeit_unter_einer_halben_stunde_verhindert_den_start(
    feld: str, wert: int
) -> None:
    """**Vorgabe des Betreibers: keine dieser Grenzen unter 30 Minuten.**

    Bei Zehn-Minuten-Takt sind 30 Minuten drei verpasste Meldungen.
    Darunter meldet ein **einzelner** verlorener Uplink einen Ausfall,
    und nach einer Woche liest die Mails niemand mehr (Paragraph 5.79).

    Start-Fehler und keine Warnung, dieselbe Haltung wie bei den
    uebrigen Grenzen: ein Haus, dessen Melder nach einem Tippfehler in
    der ``.env`` stumm das Falsche tut, ist schlechter bedient als eines,
    dessen API nicht startet.
    """
    with pytest.raises(ValidationError) as exc:
        Settings(environment="test", **{feld: wert})
    assert feld.upper() in str(exc.value)


def test_gueltige_wartezeiten_werden_angenommen() -> None:
    """Gegenprobe: ohne sie waere ein Validator, der alles ablehnt, gruen."""
    s = Settings(
        environment="test",
        relais_zone_stumm_min=AUSFALL_MELDUNG_MIN_MIN,
        totalausfall_min=AUSFALL_MELDUNG_MIN_MIN,
    )
    assert s.relais_zone_stumm_min == AUSFALL_MELDUNG_MIN_MIN
    assert s.totalausfall_min == AUSFALL_MELDUNG_MIN_MIN


def test_die_warnung_der_zone_liegt_vor_dem_zwangs_aus() -> None:
    """Die Reihenfolge, die der Melder ueberhaupt erst sinnvoll macht.

    Der Zweipunktregler schaltet eine Zone ohne frischen Istwert
    zwangsweise ab, nach ``health_healthy_max_age_h`` mal
    ``VERALTUNGS_FAKTOR`` — mit den Vorgaben nach 300 Minuten. Die
    Meldung muss davor liegen, sonst meldet sie etwas, das schon
    passiert ist.

    **Mit der Vorgabe vom 28.11.2026 bleiben 120 Minuten Vorlauf** statt
    vorher 270. Das ist der Preis der Entscheidung und steht hier als
    Zahl, damit er nicht in Erinnerung bleibt als „aendert nichts".
    """
    s = get_settings()
    abschalt_min = int(s.health_healthy_max_age_h * VERALTUNGS_FAKTOR * 60)

    assert abschalt_min == 300, "die Rechnung des Reglers"
    assert s.relais_zone_stumm_min < abschalt_min
    assert abschalt_min - s.relais_zone_stumm_min == 120, "der verbleibende Vorlauf"

    with pytest.raises(ValidationError) as exc:
        Settings(environment="test", relais_zone_stumm_min=abschalt_min)
    assert "RELAIS_ZONE_STUMM_MIN" in str(exc.value)


def test_wer_das_keepalive_fenster_kuerzt_muss_die_wartezeit_mitnehmen() -> None:
    """Die neue Kopplung, ausdruecklich festgehalten.

    Mit ``health_healthy_max_age_h = 1`` schaltet der Regler nach 150
    Minuten ab — die Wartezeit von 180 liegt dann **dahinter**, und der
    Start bricht ab. Das ist kein Mangel, sondern die Reihenfolge aus dem
    Test darueber. Wer am Keepalive-Fenster dreht, bekommt die Antwort
    beim Hochfahren und nicht nach dem ersten unbemerkten Ausfall.
    """
    with pytest.raises(ValidationError):
        Settings(environment="test", health_healthy_max_age_h=1, health_degraded_max_age_h=3)

    s = Settings(
        environment="test",
        health_healthy_max_age_h=1,
        health_degraded_max_age_h=3,
        relais_zone_stumm_min=60,
    )
    assert s.relais_zone_stumm_min == 60


# ---------------------------------------------------------------------------
# 4. Die Ereignis-Melder bleiben unverzueglich
# ---------------------------------------------------------------------------


def test_die_ereignis_melder_kennen_keine_wartezeit() -> None:
    """**Der Waechter gegen die naechste Buendelung.**

    Schutzausloesung, warmes Gehaeuse und volle Platte melden sofort.
    Haengt jemand spaeter einen der drei an eine Wartezeit, wird diese
    Zeile rot — und die Entscheidung muss bewusst fallen, statt in einem
    Nachjustieren mitzulaufen.

    Geprueft wird der **Syntaxbaum** und nicht der Text: ein Verweis in
    einem Kommentar oder Docstring ist Prosa und darf dort stehen, ein
    gelesener Name nicht. Vorbild ist der Import-Waechter in
    ``test_mail_episoden.py``.
    """
    quelle = Path(__file__).resolve().parents[1] / "src" / "heizung"
    gefunden: dict[str, set[str]] = {}

    for datei in EREIGNIS_MELDER:
        pfad = quelle / datei
        assert pfad.exists(), f"{datei} gibt es nicht mehr — der Waechter zeigt ins Leere"
        baum = ast.parse(pfad.read_text(encoding="utf-8"))
        namen = {k.attr for k in ast.walk(baum) if isinstance(k, ast.Attribute)}
        namen |= {k.id for k in ast.walk(baum) if isinstance(k, ast.Name)}
        treffer = namen & set(WARTEZEITEN)
        if treffer:
            gefunden[datei] = treffer

    assert not gefunden, (
        f"Ereignis-Melder lesen eine Wartezeit: {gefunden}. "
        "Unverzueglich heisst unverzueglich — siehe RUNBOOK 10m."
    )
