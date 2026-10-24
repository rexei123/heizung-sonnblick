"""Relais-Uplinks verarbeiten (Sprint 24b, Paket 5).

**Zwei Dinge passieren hier, und eines davon ist eine Zusicherung.**

1. Der gemeldete Zustand wird in ``relay_reading`` geschrieben. Das ist
   die **einzige** Quelle fuer den bestaetigten Schaltzustand
   (``services/relay_state.py``) — ohne diesen Schreibpfad findet der
   Waechter nie einen Zustand, und der Orchestrator kaeme nie ueber die
   erste Abfrage hinaus.

2. Bei einer **Schutzauslösung** wird das Relais gesperrt (S4, Nachtrag
   vom 23.10.) und ein Alarm geschrieben. Die Sperre hebt nur ein Admin
   auf.

**Warum die Sperre hierher gehoert und nicht in den Waechter.** Das
Geraet erholt sich selbst: bei Ueberspannung laut Doku nach einer
Minute, bei Ueberhitzung sobald es abgekuehlt ist. Der Waechter laeuft
alle 60 Sekunden und saehe den Vorfall womoeglich nie — er saehe nur ein
Relais, das AUS meldet, und schaltete es wieder ein. Der Uplink ist der
einzige Zeitpunkt, an dem die Auslösung ueberhaupt sichtbar ist.

Das ist §5.76: ueberwacht wird die **Wirkung**, und zwar dort, wo sie
ankommt. Und es ist die Umkehrung von §5.79 — ein Melder, der sich
selbst zurueckstellt, ueberwacht nichts.

**Was hier nicht passiert:** kein Downlink. Das Geraet hat schon
abgeschaltet; ein ``0xC1 00`` obendrauf waere Sendezeit ohne Wirkung
(§0 S4). Die Zone bleibt aus, weil ``darf_schalten`` die Sperre sieht.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.services import relay_service

logger = logging.getLogger(__name__)

#: Welches Codec-Feld welche Schutzart meldet. ``protection`` nennt die
#: **Auslösung** (0x60-0x63), ``protectionRecovered`` die Erholung
#: (0x70-0x73). Nur die Auslösung sperrt.
FELD_AUSLOESUNG = "protection"
FELD_ERHOLUNG = "protectionRecovered"


def werte_aus_codec(
    obj: dict[str, Any], *, device_id: int, zeit: datetime, fcnt: int | None
) -> dict[str, Any]:
    """Projiziert den Codec-Ausgang auf eine ``relay_reading``-Zeile.

    ``None`` bleibt ``None``: ein Uplink, der nur eine Befehlsantwort
    traegt (ohne Keepalive-Schwanz), sagt nichts ueber Leistung oder
    Energie, und eine 0 waere dort eine Behauptung.
    """
    zustand = obj.get("relayState")
    return {
        "time": zeit,
        "device_id": device_id,
        "fcnt": fcnt,
        "relay_on": None if zustand is None else zustand == "ON",
        "timer_remaining_s": obj.get("relayTimerRemaining_s"),
        "change_reason": obj.get("relayChangeReason"),
        "power_w": obj.get("power_W"),
        # Der Codec liefert kWh als Dezimalzahl; gespeichert wird der
        # Rohzaehler in Wh. ``energy_raw`` ist genau das.
        "energy_wh": obj.get("energy_raw"),
        "ac_voltage_v": obj.get("acVoltage_V"),
        "ac_current_ma": obj.get("acCurrent_mA"),
        "internal_temperature_raw": obj.get("internalTemperature"),
    }


async def ist_relais(session: AsyncSession, device_id: int) -> bool:
    """Ob dieses Geraet ein Relais ist."""
    art = (await session.execute(select(Device.kind).where(Device.id == device_id))).scalar()
    return art == DeviceKind.RELAY


async def verarbeite_relais_uplink(
    session: AsyncSession,
    *,
    device_id: int,
    obj: dict[str, Any],
    zeit: datetime,
    fcnt: int | None,
) -> dict[str, Any]:
    """Schreibt die Zeitreihe und setzt bei Bedarf die Schutz-Sperre.

    Returns ein kleines Protokoll fuer den Aufrufer-Log.
    """
    werte = werte_aus_codec(obj, device_id=device_id, zeit=zeit, fcnt=fcnt)
    await session.execute(
        pg_insert(RelayReading)
        .values(**werte)
        .on_conflict_do_nothing(index_elements=["time", "device_id"])
    )

    protokoll: dict[str, Any] = {
        "relay_on": werte["relay_on"],
        "power_w": werte["power_w"],
        "sperre_gesetzt": False,
    }

    art = obj.get(FELD_AUSLOESUNG)
    if art is None:
        return protokoll

    geraet = await session.get(Device, device_id)
    if geraet is None:
        return protokoll

    # Auch eine **unbekannte** Schutzart sperrt. Lieber eine Sperre zu
    # viel: die Liste der Arten steht in der Geraete-Firmware, und ein
    # neuer Wert soll nicht dazu fuehren, dass ein Panel nach einem
    # Vorfall einfach weiterlaeuft.
    gesetzt = relay_service.setze_schutz_sperre(geraet, art=str(art))
    protokoll["sperre_gesetzt"] = gesetzt
    protokoll["schutzart"] = art

    if gesetzt:
        logger.error(
            "schutz-ausloesung device_id=%s art=%s zaehler=%s "
            "temperatur=%s spannung=%s strom=%s leistung=%s",
            device_id,
            art,
            obj.get("protectionEventCount"),
            obj.get("protectionTemperatureC"),
            obj.get("protectionVoltageV"),
            obj.get("protectionCurrentMa"),
            obj.get("protectionPowerW"),
        )
    else:
        # Eine stehende Sperre wird nicht ueberschrieben — bei Ueberstrom
        # schaltet das Geraet so lange ab, wie der Strom ueber der
        # Schwelle liegt, und das koennen viele Meldungen in Folge sein.
        logger.info(
            "schutz-ausloesung erneut gemeldet, Sperre steht bereits device_id=%s art=%s seit=%s",
            device_id,
            art,
            geraet.protection_tripped_at,
        )

    return protokoll


async def alarm_nutzlast(session: AsyncSession, *, device_id: int, art: str) -> dict[str, Any]:
    """Baut die Nutzlast fuer den Health-Alarm.

    Namen statt Ids: der Hotelier liest „Bar / Barbereich", nicht
    „device_id=57". Dieselbe Form wie die Payload-Anreicherung in
    ``health_tasks``.
    """
    zeile = (
        await session.execute(
            select(Device.dev_eui, Device.label, HeatingZone.name, Room.number)
            .select_from(Device)
            .outerjoin(HeatingZone, HeatingZone.id == Device.heating_zone_id)
            .outerjoin(Room, Room.id == HeatingZone.room_id)
            .where(Device.id == device_id)
        )
    ).first()
    dev_eui, label, zone_name, room_number = (
        zeile if zeile is not None else (None, None, None, None)
    )
    return {
        "device_id": device_id,
        "dev_eui": dev_eui,
        "device_label": label,
        "zone_name": zone_name,
        "room_name": room_number,
        "schutzart": art,
        "triggered_at": datetime.now(tz=UTC),
    }
