"""Inbetriebnahme und Sperre von Relais-Aktoren (Sprint 24, S3/S4).

Dieses Modul haelt die zwei Zusicherungen zusammen, die entscheiden, ob
ein Relais ueberhaupt schalten darf:

- **S3:** ohne ``commissioned_at`` gehen **keine** Schaltbefehle an das
  Geraet, nur Lese- und Konfigurationsbefehle.
- **S4:** ``commissioned_at`` ist nur setzbar, wenn **beide**
  Ruecklesungen vorliegen — Zustand nach Stromrueckkehr **und** Zustand
  nach Erholung vom Ueberhitzungsschutz, beide auf AUS.

**Warum zwei Ruecklesungen und nicht eine.** Das Geraet hat zwei
voneinander unabhaengige Wege, von selbst wieder EIN zu werden, und bei
beiden ist die Hersteller-Vorgabe ``last_state``:

| Befehl | Fall | Vorgabe |
|---|---|---|
| ``0x5E`` | Strom kommt zurueck | ``last_state`` |
| ``0x59`` | Erholung vom Ueberhitzungsschutz | ``last_state`` |

Zum zweiten Fall sagt die Doku ausdruecklich, das Relais sei „returned to
its previous state after recovering from the protection event", und die
Erholung passiert **von selbst**. Ein Panel, das wegen Hitze
abgeschaltet hat, kaeme nach dem Abkuehlen also zurueck — ohne einen
Befehl von uns und ohne dass jemand davon erfaehrt.

**Die Sperre nach einer Schutzauslösung** ist die Folge daraus. Das
Geraet heilt sich selbst; ohne Sperre waere der Vorfall nach einer
Minute unsichtbar, der Regler schaltete wieder ein, und ein Panel mit
einem echten Fehler liefe in eine Schleife aus Abschalten und
Wiedereinschalten. Die Sperre macht aus einem selbstheilenden
Geraetezustand einen Befund, der jemanden braucht — und sie wird
ausschliesslich von einem Admin aufgehoben.

Das ist §5.76 angewandt: ueberwacht wird die **Wirkung** (das Relais hat
abgeschaltet, weil ein Schutz ausgeloest hat), nicht die Mechanik. Und es
ist die Umkehrung von §5.79: ein Melder, der sich selbst zurueckstellt,
ueberwacht nichts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind

logger = logging.getLogger(__name__)

#: Die Schutzarten, die der Codec melden kann. Als Menge und nicht als
#: Enum: die Liste steht in der Geraete-Firmware. Ein unbekannter Wert
#: setzt die Sperre trotzdem — lieber eine Sperre zu viel als eine zu
#: wenig, und der Rohwert landet im Feld.
SCHUTZARTEN = frozenset({"overheating", "overvoltage", "overcurrent", "overpower"})


class RelayNotCommissionedError(RuntimeError):
    """Ein Schaltbefehl an ein nicht in Betrieb genommenes Relais (S3)."""


class RelayProtectionLatchedError(RuntimeError):
    """Ein Schaltbefehl an ein Relais mit stehender Schutz-Sperre (S4)."""


class RelayCommissioningIncompleteError(ValueError):
    """``commissioned_at`` soll gesetzt werden, ohne beide Ruecklesungen (S4)."""


def darf_schalten(geraet: Device) -> bool:
    """Ob an dieses Relais ein Schaltbefehl gehen darf.

    Die **einzige** Stelle, die diese Frage beantwortet. Waechter und
    Regler fragen hier, nicht jeder fuer sich — sonst entsteht ein
    zweiter Pfad, auf dem eine der beiden Zusicherungen fehlt, und der
    faellt erst im Betrieb auf.
    """
    if geraet.kind != DeviceKind.RELAY:
        return False
    if geraet.retired_at is not None:
        return False
    if geraet.commissioned_at is None:
        return False
    return geraet.protection_tripped_at is None


def pruefe_schaltbefehl(geraet: Device) -> None:
    """Wie ``darf_schalten``, aber mit sprechendem Fehler.

    Fuer Aufrufer, die einen Befehl absetzen wollen: ein ``bool`` sagt
    nicht, **warum** nicht, und bei einer Sicherheitszusicherung ist das
    der wichtigere Teil der Information.
    """
    if geraet.kind != DeviceKind.RELAY:
        raise RelayNotCommissionedError(
            f"device_id={geraet.id} ist kein Relais (kind={geraet.kind})"
        )
    if geraet.retired_at is not None:
        raise RelayNotCommissionedError(f"device_id={geraet.id} ist ausgemustert")
    if geraet.commissioned_at is None:
        raise RelayNotCommissionedError(
            f"device_id={geraet.id} ist nicht in Betrieb genommen (S3) — "
            "nur Lese- und Konfigurationsbefehle zulaessig"
        )
    if geraet.protection_tripped_at is not None:
        raise RelayProtectionLatchedError(
            f"device_id={geraet.id} hat eine stehende Schutz-Sperre "
            f"({geraet.protection_kind}, seit {geraet.protection_tripped_at.isoformat()}) — "
            "Freigabe nur durch einen Admin"
        )


def vermerke_ruecklesung(
    geraet: Device,
    *,
    was: str,
    wert: str,
    now: datetime | None = None,
) -> bool:
    """Haelt das Ergebnis einer Ruecklesung fest (S4).

    ``was`` ist ``power_return`` oder ``overheating_recovery``, ``wert``
    der vom Geraet gemeldete Zustand.

    **Nur ``off`` zaehlt als bestanden.** ``last_state`` ist die Vorgabe
    des Geraets und genau der Zustand, den die Provisionierung beseitigen
    soll; ein ``last_state`` ist also kein „noch nicht", sondern ein
    **Nein**. Deshalb wird der Vermerk in diesem Fall ausdruecklich
    wieder geloescht: eine bestandene Ruecklesung von gestern darf eine
    nicht bestandene von heute nicht ueberdecken.

    Returns ob die Ruecklesung bestanden ist.
    """
    bestanden = wert == "off"
    zeit = (now or datetime.now(tz=UTC)) if bestanden else None

    if was == "power_return":
        geraet.power_return_verified_at = zeit
    elif was == "overheating_recovery":
        geraet.overheating_recovery_verified_at = zeit
    else:
        raise ValueError(f"was muss 'power_return' oder 'overheating_recovery' sein, ist {was!r}")

    logger.info(
        "ruecklesung device_id=%s was=%s wert=%s bestanden=%s",
        geraet.id,
        was,
        wert,
        bestanden,
    )
    return bestanden


def ruecklesungen_vollstaendig(geraet: Device) -> bool:
    """Ob **beide** Ruecklesungen bestanden sind (S4)."""
    return (
        geraet.power_return_verified_at is not None
        and geraet.overheating_recovery_verified_at is not None
    )


def nimm_in_betrieb(geraet: Device, *, now: datetime | None = None) -> None:
    """Setzt ``commissioned_at`` — nur mit beiden Ruecklesungen (S3 + S4).

    **Die Pruefung steht hier und nicht in der Oberflaeche.** S4 sagt
    ausdruecklich „ohne beide Verifikationen kein 'in Betrieb
    genommen'", und eine Pruefung, die nur im Formular sitzt, gilt fuer
    jeden anderen Aufrufer nicht — fuer die API, fuer ein Skript, fuer
    einen spaeteren Massen-Handgriff. Dieselbe Begruendung wie bei S6
    (Sperre im Backend, nicht nur in der UI).

    Das ist die Stelle, die Mutationsprobe **M9** angreift: faellt die
    Pruefung auf ``overheating_recovery_verified_at``, laesst sich ein
    Relais in Betrieb nehmen, das nach dem Abkuehlen von selbst wieder
    einschaltet.
    """
    fehlt = []
    if geraet.power_return_verified_at is None:
        fehlt.append("Zustand nach Stromrueckkehr (0x5E/0x5F)")
    if geraet.overheating_recovery_verified_at is None:
        fehlt.append("Zustand nach Ueberhitzungs-Erholung (0x59/0x5A)")

    if fehlt:
        raise RelayCommissioningIncompleteError(
            f"device_id={geraet.id} kann nicht in Betrieb genommen werden — "
            f"nicht verifiziert: {', '.join(fehlt)}"
        )

    geraet.commissioned_at = now or datetime.now(tz=UTC)
    logger.info("relais in betrieb genommen device_id=%s", geraet.id)


def setze_schutz_sperre(
    geraet: Device,
    *,
    art: str,
    now: datetime | None = None,
) -> bool:
    """Sperrt das Relais nach einer Schutzauslösung (S4, Nachtrag).

    **Die erste Auslösung zaehlt.** Eine bereits stehende Sperre wird
    nicht ueberschrieben: ``protection_tripped_at`` soll den Beginn des
    Vorfalls nennen, nicht die letzte Wiederholung. Bei Ueberstrom
    schaltet das Geraet laut Doku so lange ab, wie der Strom ueber der
    Schwelle liegt — das koennen viele Meldungen in Folge sein, und
    jede wuerde den Beginn nach vorn schieben.

    Returns ob diese Meldung die Sperre **gesetzt** hat.
    """
    if geraet.protection_tripped_at is not None:
        return False

    geraet.protection_tripped_at = now or datetime.now(tz=UTC)
    geraet.protection_kind = art
    logger.warning("schutz-sperre gesetzt device_id=%s art=%s", geraet.id, art)
    return True


def hebe_schutz_sperre_auf(geraet: Device) -> None:
    """Gibt das Relais wieder frei. **Nur fuer einen Admin.**

    Die Rollenpruefung sitzt am Endpunkt, nicht hier — aber der
    Docstring sagt es, damit niemand diese Funktion aus einem
    automatischen Pfad aufruft. Eine Sperre, die sich selbst aufhebt,
    ist keine (§5.79).
    """
    logger.info(
        "schutz-sperre aufgehoben device_id=%s art=%s seit=%s",
        geraet.id,
        geraet.protection_kind,
        geraet.protection_tripped_at,
    )
    geraet.protection_tripped_at = None
    geraet.protection_kind = None


async def lade_relais(session: AsyncSession, device_id: int) -> Device | None:
    """Laedt ein Relais. ``None``, wenn es keines ist oder nicht existiert."""
    geraet = await session.get(Device, device_id)
    if geraet is None or geraet.kind != DeviceKind.RELAY:
        return None
    return geraet
