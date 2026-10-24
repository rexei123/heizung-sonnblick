"""Relais verwalten (Sprint 24b, Paket 6).

Fuenf Handgriffe, alle **nur fuer Admins**, und die Pruefung sitzt in
jedem Fall **hier** und nicht in der Oberflaeche:

| Weg | Was |
|---|---|
| ``POST .../provision`` | ``0x5E 02`` und ``0x59 01`` senden, beides zuruecklesen |
| ``POST .../commission`` | „in Betrieb genommen" setzen — nur mit beiden Ruecklesungen (S3/S4) |
| ``DELETE .../commission`` | zuruecknehmen |
| ``POST .../release-protection`` | Schutz-Sperre aufheben |
| ``PATCH /devices/{id}/measure-only`` | Rolle „nur messen" umschalten, Kindersicherung senden |

**Warum die Pruefung im Backend und nicht im Formular** (S6-Begruendung,
hier genauso): eine Pruefung im Dialog gilt fuer die API nicht, fuer ein
Skript nicht und fuer einen spaeteren Massen-Handgriff nicht. Das ist
Mutationsprobe **M12** — faellt ``require_admin`` an einem dieser Wege,
muss ein Test rot werden.

**Jeder Handgriff schreibt Audit.** Wer ein Panel scharf schaltet oder
eine Sperre aufhebt, trifft eine Entscheidung ueber ein Geraet, das
Netzspannung schaltet. Ohne Audit ist spaeter nicht zu sagen, wer sie
getroffen hat.

**Die Provisionierung sendet, aber sie urteilt nicht.** Sie setzt die
beiden Werte und fragt sie ab; die Antwort kommt **asynchron** im
naechsten Uplink. Der Endpunkt liefert deshalb ``angefragt`` und nicht
``bestanden`` — das Urteil faellt der Subscriber, wenn die Antwort da
ist. Alles andere waere eine Zusicherung ohne Deckung.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.auth.dependencies import require_admin
from heizung.db import get_session
from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.user import User
from heizung.services import downlink_adapter, relay_adapter, relay_service
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

router = APIRouter(tags=["relays"])

DeviceIdPath = Path(..., gt=0, description="Device-Primary-Key")


class ProvisionierungErgebnis(BaseModel):
    """Was die Provisionierung **angefragt** hat.

    Bewusst nicht „bestanden": die Antworten kommen asynchron im
    naechsten Uplink, und der Subscriber vermerkt sie dann.
    """

    device_id: int
    gesendet: list[str]
    hinweis: str


class InbetriebnahmeErgebnis(BaseModel):
    device_id: int
    commissioned_at: str | None
    power_return_verified: bool
    overheating_recovery_verified: bool


class SperrErgebnis(BaseModel):
    device_id: int
    gesperrt: bool
    schutzart: str | None


class MessrolleEingabe(BaseModel):
    measure_only: bool = Field(..., description="True = Rolle 'nur messen'")


class MessrolleErgebnis(BaseModel):
    device_id: int
    measure_only: bool
    kindersicherung_gesendet: bool
    hinweis: str


async def _relais_oder_404(session: AsyncSession, device_id: int) -> Device:
    geraet = await session.get(Device, device_id)
    if geraet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"device_id={device_id} existiert nicht"
        )
    if geraet.kind != DeviceKind.RELAY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"device_id={device_id} ist kein Relais (kind={geraet.kind})",
        )
    return geraet


@router.post(
    "/devices/{device_id}/relay/provision",
    response_model=ProvisionierungErgebnis,
    summary="Relais provisionieren (S4): beide Zustaende auf AUS setzen und zuruecklesen",
)
async def provisioniere(
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ProvisionierungErgebnis:
    """Setzt und liest **beide** Rueckfallzustaende (S4).

    Vier Downlinks in dieser Reihenfolge: setzen, setzen, lesen, lesen.
    Die Reihenfolge ist nicht beliebig — erst beide Werte setzen, dann
    beide abfragen, damit die Antworten einen konsistenten Stand
    beschreiben.

    ``0x5E 02`` ist AUS nach Stromrueckkehr, ``0x59 01`` ist AUS nach
    Erholung vom Ueberhitzungsschutz. **Die Bytes sind verschieden**: bei
    ``0x5E`` ist AUS die ``02``, bei ``0x59`` die ``01``.
    """
    geraet = await _relais_oder_404(session, device_id)

    gesendet: list[str] = []
    await relay_adapter.setze_zustand_nach_stromrueckkehr(geraet.dev_eui, "off")
    gesendet.append("0x5E 02 (AUS nach Stromrueckkehr)")
    await relay_adapter.setze_zustand_nach_ueberhitzung(geraet.dev_eui, "off")
    gesendet.append("0x59 01 (AUS nach Ueberhitzungs-Erholung)")
    await relay_adapter.frage_zustand_nach_stromrueckkehr(geraet.dev_eui)
    gesendet.append("0x5F (Ruecklesung Stromrueckkehr)")
    await relay_adapter.frage_zustand_nach_ueberhitzung(geraet.dev_eui)
    gesendet.append("0x5A (Ruecklesung Ueberhitzung)")

    await record_business_action(
        session,
        user_id=user.id,
        action="RELAY_PROVISIONED",
        target_type="device",
        target_id=device_id,
        old_value=None,
        new_value={"gesendet": gesendet},
    )
    await session.commit()

    return ProvisionierungErgebnis(
        device_id=device_id,
        gesendet=gesendet,
        hinweis=(
            "Die Antworten kommen mit dem naechsten Uplink. Erst danach "
            "zeigt die Geraeteseite beide Ruecklesungen als bestanden, und "
            "erst dann laesst sich das Relais in Betrieb nehmen."
        ),
    )


@router.post(
    "/devices/{device_id}/relay/commission",
    response_model=InbetriebnahmeErgebnis,
    summary="In Betrieb nehmen (S3) — nur mit beiden Ruecklesungen (S4)",
)
async def nimm_in_betrieb(
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> InbetriebnahmeErgebnis:
    """Setzt ``commissioned_at``. **Die Pruefung liegt im Service.**

    ``relay_service.nimm_in_betrieb`` wirft, wenn eine der beiden
    Ruecklesungen fehlt. Diese Funktion faengt das und macht daraus ein
    422 mit der Liste des Fehlenden — sie prueft **nicht** selbst, sonst
    gaebe es zwei Stellen mit derselben Regel.
    """
    geraet = await _relais_oder_404(session, device_id)

    try:
        relay_service.nimm_in_betrieb(geraet)
    except relay_service.RelayCommissioningIncompleteError as fehler:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(fehler)
        ) from fehler

    await record_business_action(
        session,
        user_id=user.id,
        action="RELAY_COMMISSIONED",
        target_type="device",
        target_id=device_id,
        old_value={"commissioned_at": None},
        new_value={
            "commissioned_at": geraet.commissioned_at.isoformat()
            if geraet.commissioned_at
            else None
        },
    )
    await session.commit()

    return _inbetriebnahme_ergebnis(geraet)


@router.delete(
    "/devices/{device_id}/relay/commission",
    response_model=InbetriebnahmeErgebnis,
    summary="Inbetriebnahme zuruecknehmen — danach keine Schaltbefehle mehr",
)
async def nimm_ausser_betrieb(
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> InbetriebnahmeErgebnis:
    """Loescht ``commissioned_at``.

    **Schaltet das Relais nicht aus.** Es bekommt nur keine neuen
    Befehle mehr, und ein laufender Timer laeuft ab — genau die
    Eigenschaft, fuer die S1 gebaut ist. Wer sofort aus will, nimmt den
    Weg ueber den Regler oder schaltet die Sicherung.
    """
    geraet = await _relais_oder_404(session, device_id)
    vorher = geraet.commissioned_at
    geraet.commissioned_at = None

    await record_business_action(
        session,
        user_id=user.id,
        action="RELAY_DECOMMISSIONED",
        target_type="device",
        target_id=device_id,
        old_value={"commissioned_at": vorher.isoformat() if vorher else None},
        new_value={"commissioned_at": None},
    )
    await session.commit()
    return _inbetriebnahme_ergebnis(geraet)


@router.post(
    "/devices/{device_id}/relay/release-protection",
    response_model=SperrErgebnis,
    summary="Schutz-Sperre aufheben (nur Admin)",
)
async def hebe_sperre_auf(
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> SperrErgebnis:
    """Gibt ein Relais nach einer Schutzauslösung wieder frei.

    **Der ganze Sinn der Sperre ist, dass sie einen Menschen braucht.**
    Das Geraet erholt sich selbst; ohne diesen Handgriff waere der
    Vorfall nach einer Minute unsichtbar, und ein Panel mit echtem Fehler
    liefe in eine Schleife aus Abschalten und Wiedereinschalten. Deshalb
    ist dieser Weg nur fuer Admins — und deshalb schreibt er Audit.
    """
    geraet = await _relais_oder_404(session, device_id)
    if geraet.protection_tripped_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"device_id={device_id} hat keine stehende Schutz-Sperre",
        )

    alt = {
        "protection_tripped_at": geraet.protection_tripped_at.isoformat(),
        "protection_kind": geraet.protection_kind,
    }
    relay_service.hebe_schutz_sperre_auf(geraet)

    await record_business_action(
        session,
        user_id=user.id,
        action="RELAY_PROTECTION_RELEASED",
        target_type="device",
        target_id=device_id,
        old_value=alt,
        new_value={"protection_tripped_at": None},
    )
    await session.commit()

    return SperrErgebnis(device_id=device_id, gesperrt=False, schutzart=None)


@router.patch(
    "/devices/{device_id}/measure-only",
    response_model=MessrolleErgebnis,
    summary="Rolle 'nur messen' umschalten (nur Admin)",
)
async def setze_messrolle(
    payload: MessrolleEingabe,
    device_id: int = DeviceIdPath,
    user: User = Depends(require_admin),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> MessrolleErgebnis:
    """Schaltet die Rolle um und sendet beim Setzen die Kindersicherung.

    **Die Kindersicherung gehoert zum Setzen der Rolle, nicht daneben.**
    Ein Fuehler liegt unmontiert im Raum und hat ein drehbares Rad; ohne
    Sperre verstellt der erste Gast, der ihn findet, einen Sollwert, den
    niemand umsetzt (das Geraet bekommt keine Downlinks mehr, S7). Die
    Drehung bliebe also wirkungslos und wuerde nur die Anzeige des
    Geraets verwirren.

    Beim **Zuruecknehmen** der Rolle wird die Sperre wieder geloest: ein
    montiertes Thermostat soll am Rad bedienbar sein.

    Das Ergebnis der Sperre kommt asynchron — ``sensor_reading.child_lock``
    im naechsten Keepalive. Deshalb ``gesendet`` und nicht ``gesetzt``.
    """
    geraet = await session.get(Device, device_id)
    if geraet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"device_id={device_id} existiert nicht"
        )
    if geraet.kind == DeviceKind.RELAY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ein Relais misst nicht — die Rolle gilt nur fuer Thermostate",
        )

    alt = geraet.measure_only
    geraet.measure_only = payload.measure_only

    gesendet = False
    if alt != payload.measure_only:
        await downlink_adapter.set_child_lock(geraet.dev_eui, payload.measure_only)
        await downlink_adapter.get_child_lock(geraet.dev_eui)
        gesendet = True

    await record_business_action(
        session,
        user_id=user.id,
        action="DEVICE_MEASURE_ONLY_TOGGLED",
        target_type="device",
        target_id=device_id,
        old_value={"measure_only": alt},
        new_value={
            "measure_only": payload.measure_only,
            "kindersicherung_gesendet": gesendet,
        },
    )
    await session.commit()

    return MessrolleErgebnis(
        device_id=device_id,
        measure_only=payload.measure_only,
        kindersicherung_gesendet=gesendet,
        hinweis=(
            "Die Kindersicherung wird mit dem naechsten Keepalive bestaetigt "
            "(Feld child_lock). Bis dahin ist nicht gesichert, dass sie sitzt."
            if gesendet
            else "Rolle unveraendert — kein Downlink gesendet."
        ),
    )


def _inbetriebnahme_ergebnis(geraet: Device) -> InbetriebnahmeErgebnis:
    return InbetriebnahmeErgebnis(
        device_id=geraet.id,
        commissioned_at=geraet.commissioned_at.isoformat() if geraet.commissioned_at else None,
        power_return_verified=geraet.power_return_verified_at is not None,
        overheating_recovery_verified=geraet.overheating_recovery_verified_at is not None,
    )


def relais_antwort(geraet: Device) -> dict[str, Any]:
    """Die Relais-Felder fuer die Zonen- und Geraeteansicht (Paket 6).

    Als Funktion und nicht als Schema-Feld: die Zonenansicht reicht sie
    als Teilobjekt durch, die Geraeteseite flach. Zwei Schemata fuer
    dieselben sechs Werte waeren zwei Stellen zum Nachziehen.
    """
    return {
        "commissioned_at": geraet.commissioned_at,
        "power_return_verified": geraet.power_return_verified_at is not None,
        "overheating_recovery_verified": geraet.overheating_recovery_verified_at is not None,
        "protection_tripped_at": geraet.protection_tripped_at,
        "protection_kind": geraet.protection_kind,
        "switch_cycles": geraet.switch_cycles,
        "watchdog_strategy": geraet.watchdog_strategy,
        "darf_schalten": relay_service.darf_schalten(geraet),
    }
