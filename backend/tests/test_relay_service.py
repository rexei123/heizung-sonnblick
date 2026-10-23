"""Inbetriebnahme und Schutz-Sperre von Relais (Sprint 24, S3/S4).

Reine Funktionen auf einem ORM-Objekt, keine Datenbank: ``darf_schalten``
und ``nimm_in_betrieb`` entscheiden allein aus den Feldern. Das ist
Absicht — die Zusicherungen S3 und S4 sollen ohne Datenbank pruefbar
sein, damit sie auch im Waechter-Pfad billig bleiben.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.services import relay_service
from heizung.services.relay_service import (
    RelayCommissioningIncompleteError,
    RelayNotCommissionedError,
    RelayProtectionLatchedError,
)

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def _relais(**felder: object) -> Device:
    """Ein Relais im Speicher, ohne Datenbank.

    Die Vorgaben entsprechen einem frisch angelegten Geraet: nichts
    verifiziert, nicht in Betrieb genommen, keine Sperre.
    """
    standard: dict[str, object] = {
        "id": 1,
        "dev_eui": "beef000000000001",
        "kind": DeviceKind.RELAY,
        "vendor": DeviceVendor.MCLIMATE,
        "model": "16ASPM",
        "commissioned_at": None,
        "power_return_verified_at": None,
        "overheating_recovery_verified_at": None,
        "protection_tripped_at": None,
        "protection_kind": None,
        "retired_at": None,
    }
    standard.update(felder)
    return Device(**standard)


def _betriebsbereit(**felder: object) -> Device:
    """Ein Relais, das alles hinter sich hat: beide Ruecklesungen, in Betrieb."""
    standard: dict[str, object] = {
        "power_return_verified_at": NOW - timedelta(hours=1),
        "overheating_recovery_verified_at": NOW - timedelta(hours=1),
        "commissioned_at": NOW - timedelta(minutes=30),
    }
    standard.update(felder)
    return _relais(**standard)


# ---------------------------------------------------------------------------
# S3 — ohne Inbetriebnahme kein Schaltbefehl
# ---------------------------------------------------------------------------


def test_nicht_in_betrieb_genommen_darf_nicht_schalten() -> None:
    """Mutationsprobe **M3** in Testform."""
    assert relay_service.darf_schalten(_relais()) is False
    with pytest.raises(RelayNotCommissionedError, match="nicht in Betrieb genommen"):
        relay_service.pruefe_schaltbefehl(_relais())


def test_in_betrieb_genommen_darf_schalten() -> None:
    geraet = _betriebsbereit()
    assert relay_service.darf_schalten(geraet) is True
    relay_service.pruefe_schaltbefehl(geraet)  # kein Fehler


def test_kein_relais_darf_nicht_schalten() -> None:
    """Ein Thermostat laeuft nicht versehentlich durch diesen Pfad."""
    geraet = _betriebsbereit(kind=DeviceKind.THERMOSTAT)
    assert relay_service.darf_schalten(geraet) is False
    with pytest.raises(RelayNotCommissionedError, match="kein Relais"):
        relay_service.pruefe_schaltbefehl(geraet)


def test_ausgemustertes_relais_darf_nicht_schalten() -> None:
    """AE-57: ein retired Geraet bekommt keine Befehle, auch kein Relais."""
    geraet = _betriebsbereit(retired_at=NOW - timedelta(days=1))
    assert relay_service.darf_schalten(geraet) is False


# ---------------------------------------------------------------------------
# S4 — zwei Ruecklesungen, nicht eine
# ---------------------------------------------------------------------------


def test_ohne_jede_ruecklesung_keine_inbetriebnahme() -> None:
    with pytest.raises(RelayCommissioningIncompleteError) as fehler:
        relay_service.nimm_in_betrieb(_relais(), now=NOW)
    assert "Stromrueckkehr" in str(fehler.value)
    assert "Ueberhitzungs-Erholung" in str(fehler.value)


def test_nur_stromrueckkehr_verifiziert_reicht_nicht() -> None:
    """**Mutationsprobe M9 in Testform.**

    Das ist der Fall, den der Nachtrag vom 23.10. verlangt: ohne die
    zweite Ruecklesung laesst sich das Relais nicht in Betrieb nehmen.
    Faellt diese Pruefung, kaeme ein Panel nach dem Abkuehlen von selbst
    wieder EIN — die Doku sagt zur Erholung ausdruecklich „returned to
    its previous state", und die Vorgabe von 0x59 ist ``last_state``.
    """
    geraet = _relais(power_return_verified_at=NOW - timedelta(minutes=5))
    with pytest.raises(RelayCommissioningIncompleteError) as fehler:
        relay_service.nimm_in_betrieb(geraet, now=NOW)
    assert "Ueberhitzungs-Erholung" in str(fehler.value)
    assert "Stromrueckkehr" not in str(fehler.value), "die erste ist ja erledigt"
    assert geraet.commissioned_at is None


def test_nur_ueberhitzung_verifiziert_reicht_nicht() -> None:
    """Die Gegenrichtung — damit die Pruefung nicht nur auf einem Feld sitzt."""
    geraet = _relais(overheating_recovery_verified_at=NOW - timedelta(minutes=5))
    with pytest.raises(RelayCommissioningIncompleteError) as fehler:
        relay_service.nimm_in_betrieb(geraet, now=NOW)
    assert "Stromrueckkehr" in str(fehler.value)


def test_mit_beiden_ruecklesungen_gelingt_die_inbetriebnahme() -> None:
    geraet = _relais(
        power_return_verified_at=NOW - timedelta(minutes=5),
        overheating_recovery_verified_at=NOW - timedelta(minutes=4),
    )
    relay_service.nimm_in_betrieb(geraet, now=NOW)
    assert geraet.commissioned_at == NOW


# ---------------------------------------------------------------------------
# Ruecklesungen: nur ``off`` zaehlt
# ---------------------------------------------------------------------------


def test_off_zaehlt_als_bestanden() -> None:
    geraet = _relais()
    assert (
        relay_service.vermerke_ruecklesung(geraet, was="power_return", wert="off", now=NOW) is True
    )
    assert geraet.power_return_verified_at == NOW


def test_last_state_ist_ein_nein_und_kein_noch_nicht() -> None:
    """``last_state`` ist die Hersteller-Vorgabe und genau der Zustand,
    den die Provisionierung beseitigen soll."""
    geraet = _relais()
    assert (
        relay_service.vermerke_ruecklesung(geraet, was="power_return", wert="last_state", now=NOW)
        is False
    )
    assert geraet.power_return_verified_at is None


def test_eine_nicht_bestandene_ruecklesung_loescht_den_alten_vermerk() -> None:
    """**Der Fall, der ohne ausdruecklichen Code durchgerutscht waere.**

    Ein Relais war verifiziert, und eine spaetere Ruecklesung meldet
    ``last_state`` — etwa weil jemand das Geraet zurueckgesetzt hat.
    Wuerde der alte Vermerk stehen bleiben, gaelte das Relais weiter als
    geprueft, obwohl es inzwischen von selbst einschalten kann.
    """
    geraet = _relais(power_return_verified_at=NOW - timedelta(days=1))
    assert (
        relay_service.vermerke_ruecklesung(geraet, was="power_return", wert="last_state", now=NOW)
        is False
    )
    assert geraet.power_return_verified_at is None


def test_unbekanntes_ruecklesungs_ziel_ist_ein_fehler() -> None:
    with pytest.raises(ValueError, match="power_return"):
        relay_service.vermerke_ruecklesung(_relais(), was="irgendwas", wert="off")


def test_ruecklesungen_vollstaendig() -> None:
    assert relay_service.ruecklesungen_vollstaendig(_relais()) is False
    assert relay_service.ruecklesungen_vollstaendig(_betriebsbereit()) is True


# ---------------------------------------------------------------------------
# Schutz-Sperre
# ---------------------------------------------------------------------------


def test_schutzausloesung_sperrt_das_relais() -> None:
    geraet = _betriebsbereit()
    assert relay_service.setze_schutz_sperre(geraet, art="overheating", now=NOW) is True
    assert geraet.protection_tripped_at == NOW
    assert geraet.protection_kind == "overheating"
    assert relay_service.darf_schalten(geraet) is False
    with pytest.raises(RelayProtectionLatchedError, match="overheating"):
        relay_service.pruefe_schaltbefehl(geraet)


def test_die_erste_ausloesung_zaehlt() -> None:
    """Eine stehende Sperre wird nicht ueberschrieben.

    Bei Ueberstrom schaltet das Geraet laut Doku so lange ab, wie der
    Strom ueber der Schwelle liegt — das koennen viele Meldungen in Folge
    sein, und jede wuerde den Beginn des Vorfalls nach vorn schieben.
    """
    geraet = _betriebsbereit()
    relay_service.setze_schutz_sperre(geraet, art="overcurrent", now=NOW)
    assert (
        relay_service.setze_schutz_sperre(geraet, art="overcurrent", now=NOW + timedelta(minutes=5))
        is False
    )
    assert geraet.protection_tripped_at == NOW, "der Beginn bleibt der Beginn"


def test_sperre_gilt_auch_fuer_ein_nicht_in_betrieb_genommenes_relais() -> None:
    """Beide Gruende sperren unabhaengig voneinander."""
    geraet = _relais(protection_tripped_at=NOW, protection_kind="overvoltage")
    assert relay_service.darf_schalten(geraet) is False


def test_freigabe_hebt_die_sperre_auf() -> None:
    geraet = _betriebsbereit(protection_tripped_at=NOW, protection_kind="overheating")
    relay_service.hebe_schutz_sperre_auf(geraet)
    assert geraet.protection_tripped_at is None
    assert geraet.protection_kind is None
    assert relay_service.darf_schalten(geraet) is True


def test_die_vier_schutzarten_sind_benannt() -> None:
    """Spiegel zu den Marken, die der Codec setzt.

    Ein neuer Wert in der Firmware soll hier auffallen und nicht
    stillschweigend als unbekannt durchlaufen — die Sperre greift
    trotzdem, aber die Oberflaeche braucht einen Namen.
    """
    erwartet = {"overheating", "overvoltage", "overcurrent", "overpower"}
    assert erwartet == relay_service.SCHUTZARTEN
