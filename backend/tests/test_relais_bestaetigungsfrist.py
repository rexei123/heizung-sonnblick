"""Die Bestaetigungsfrist des Relais-Waechters (13.11.2026).

**Der Befund des Betreibers, 12.11.2026 an Relais 108.** Zehn Downlinks
fuer vier Schaltungen, und um 10:06 ein Alarm

    relais ohne bestaetigung device_id=109 ziel_ein=False versuche=3

fuer ein Relais, das zu diesem Zeitpunkt **bereits aus war** — die
Meldung dazu kam um 10:07:56.

**Die Ursache war eine Zahl aus dem falschen Vorgang.** Die Frist stand
auf **60 Sekunden**, begruendet mit Class C: der Downlink ist sofort beim
Geraet. Das stimmt und beantwortet eine andere Frage. Ein 16ASPM meldet
seinen **Zustand** nur im eigenen Takt, gemessen alle 600 Sekunden
(107 lueckenlose Meldungen in der Nacht vom 12. auf den 13.11., Abstaende
588 bis 612 s). Die Frist lag damit um den Faktor zehn unter dem
fruehesten Zeitpunkt, an dem eine Bestaetigung ueberhaupt eintreffen
kann.

Diese Datei haelt beides fest: dass die Frist aus dem Meldeintervall
kommt, und dass ein Vorgang von der gemessenen Dauer keine Wiederholung
mehr erzeugt.

Reine Funktionstests, keine Datenbank.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from heizung.config import Settings, get_settings
from heizung.models.enums import WatchdogStrategy
from heizung.rules.relais_waechter import (
    Offen,
    WaechterAktion,
    naechste_aktion,
)
from heizung.tasks.relay_tasks import waechter_schwellen

NOW = datetime(2026, 11, 12, 10, 0, 0, tzinfo=UTC)

#: Die gemessenen Abstaende der Meldungen von Relais 108, in Sekunden.
#: Nacht vom 12. auf den 13.11.2026, 107 Meldungen ohne Lücke.
GEMESSEN_MIN_S = 588
GEMESSEN_MAX_S = 612


def _settings(**ueberschreiben: object) -> Settings:
    basis: dict[str, object] = {
        "environment": "test",
        "allow_default_secrets": True,
    }
    basis.update(ueberschreiben)
    return Settings(**basis)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Die Frist kommt aus dem Meldeintervall
# ---------------------------------------------------------------------------


def test_die_frist_ist_meldeintervall_plus_zuschlag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    get_settings.cache_clear()
    try:
        s = get_settings()
        schwellen = waechter_schwellen()
        assert schwellen.bestaetigungs_frist == timedelta(
            seconds=s.relay_meldeintervall_s + s.relay_bestaetigungs_zuschlag_s
        )
    finally:
        get_settings.cache_clear()


def test_die_vorgabe_liegt_ueber_dem_gemessenen_abstand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Der Wachposten fuer den Zweck dieser Aenderung.**

    Die Frist muss **groesser** sein als der groesste gemessene Abstand
    zweier Meldungen. Sonst laeuft sie ab, bevor die Bestaetigung
    eintreffen kann, und der Waechter wiederholt einen Befehl, der bereits
    gewirkt hat — genau der Zustand vom 12.11.

    Ein Rueckfall auf 60 Sekunden, etwa durch einen kopierten
    ``.env``-Block, waere ohne diesen Test nicht zu bemerken: die Suite
    blieb gruen, und die Fehlalarme kaemen zurueck.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    get_settings.cache_clear()
    try:
        frist = waechter_schwellen().bestaetigungs_frist
        assert frist > timedelta(seconds=GEMESSEN_MAX_S), (
            f"die Frist {frist} liegt unter dem gemessenen Abstand "
            f"{GEMESSEN_MAX_S} s - der Waechter wiederholt dann planmaessig"
        )
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 2. Die Gegenprobe am Waechter
# ---------------------------------------------------------------------------


def _offener_befehl_nach(sekunden: int, *, versuche: int = 1) -> WaechterAktion:
    """Was der Waechter mit einem ``sekunden`` alten offenen EIN tut."""
    return naechste_aktion(
        strategie=WatchdogStrategy.EXPIRE_AND_RESEND,
        gewuenscht_ein=True,
        bestaetigt_ein=False,
        offen=Offen(ziel_ein=True, seit=NOW - timedelta(seconds=sekunden), versuche=versuche),
        letzter_ein_befehl=None,
        schwellen=waechter_schwellen(),
        now=NOW,
    ).aktion


@pytest.mark.parametrize("alter_s", [60, 120, GEMESSEN_MIN_S, GEMESSEN_MAX_S])
def test_gegenprobe_kein_nachsenden_innerhalb_eines_meldeintervalls(
    alter_s: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Die Gegenprobe zum 12.11.: nach 60 s geht nichts mehr hinaus.**

    Gemessen ging am 12.11. um 09:38 ein EIN hinaus und um 09:39 die
    Wiederholung — 60 Sekunden spaeter, obwohl die Bestaetigung
    fruehestens nach rund zehn Minuten kommen kann. Alle vier Zeitpunkte
    hier liegen innerhalb eines Meldeintervalls und duerfen **warten**.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    get_settings.cache_clear()
    try:
        assert _offener_befehl_nach(alter_s) is WaechterAktion.WARTE, (
            f"nach {alter_s} s darf nichts hinausgehen - die Bestaetigung kann noch nicht da sein"
        )
    finally:
        get_settings.cache_clear()


def test_nach_der_frist_wird_weiter_wiederholt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Die Bremse ist keine Aufgabe: nach der Frist geht es weiter.

    Ein Geraet, das wirklich nicht schaltet, soll einen zweiten Versuch
    bekommen — nur eben nicht nach einer Minute.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    get_settings.cache_clear()
    try:
        frist_s = int(waechter_schwellen().bestaetigungs_frist.total_seconds())
        assert _offener_befehl_nach(frist_s + 1) is WaechterAktion.SENDE_EIN
    finally:
        get_settings.cache_clear()


def test_der_alarm_kommt_spaeter_und_das_ist_der_preis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Die unbequeme Folge, als Test festgehalten.**

    Der Alarm haengt an ``versuche == max_versuche``. Mit der laengeren
    Frist liegt er bei 720 + 1440 + 1800 Sekunden, also bei rund **einer
    Stunde** statt bei sieben Minuten.

    Dieser Test behauptet nicht, dass eine Stunde richtig ist. Er haelt
    fest, dass die Verschiebung **bekannt** ist und nicht aus Versehen
    entstand: wer sie aendern will, aendert ihn mit.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    get_settings.cache_clear()
    try:
        schwellen = waechter_schwellen()
        # Die Summe der Fristen bis zum Alarm: Versuch 1, 2, 3.
        gesamt = timedelta()
        for versuche in range(1, schwellen.max_versuche + 1):
            faktor = 2 ** (versuche - 1)
            gesamt += min(schwellen.bestaetigungs_frist * faktor, schwellen.backoff_max)
        assert timedelta(minutes=50) < gesamt < timedelta(minutes=70), (
            f"der Alarm kommt nach {gesamt} - erwartet war rund eine Stunde"
        )

        # Und er kommt, wenn das Budget erschoepft ist.
        aktion = _offener_befehl_nach(
            int(schwellen.backoff_max.total_seconds()) + 1,
            versuche=schwellen.max_versuche,
        )
        assert aktion is WaechterAktion.ALARM
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 3. Der Validator
# ---------------------------------------------------------------------------


def test_eine_kappung_unter_der_frist_wird_abgewiesen() -> None:
    """Sonst kappt die Obergrenze die erste Frist — stumm.

    Die Verdopplung ist dann wirkungslos **und** die Frist selbst zu
    kurz: der Waechter wiederholte wieder, bevor eine Bestaetigung
    eintreffen kann. Eine Einstellung, die das Gegenteil ihrer Absicht
    bewirkt, soll den Start verhindern.
    """
    with pytest.raises(ValidationError, match="RELAY_BACKOFF_MAX_S"):
        _settings(
            relay_meldeintervall_s=600,
            relay_bestaetigungs_zuschlag_s=120,
            relay_backoff_max_s=300,
        )


def test_ein_meldeintervall_von_null_wird_abgewiesen() -> None:
    with pytest.raises(ValidationError, match="RELAY_MELDEINTERVALL_S"):
        _settings(relay_meldeintervall_s=0)


def test_eine_gueltige_kombination_startet() -> None:
    """Die Gegenprobe: der Validator sperrt nicht jede Verstellung.

    Ein kuerzeres Meldeintervall — etwa nach einer Umstellung am Geraet —
    muss weiter erlaubt sein.
    """
    s = _settings(
        relay_meldeintervall_s=300,
        relay_bestaetigungs_zuschlag_s=60,
        relay_backoff_max_s=1800,
    )
    assert s.relay_meldeintervall_s == 300
