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
from heizung.services import relay_service, relay_state

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
        # Der Taster am Geraet kommt als ``0x5d`` und setzt im Codec
        # ``manualSwitch``. Das wurde bis zum 01.11.2026 **verworfen**: der
        # Zustandswechsel stand in der Zeitreihe, der Grund nicht — im
        # Audit also „ging an", nicht „jemand hat gedrueckt" (S3).
        #
        # Eingetragen wird dasselbe Wort, das ``0x54`` liefert
        # (``manual_button``), und keine zweite Schreibweise fuer dieselbe
        # Sache (§5.53). Keine Migration: ``change_reason`` ist
        # ``String(40)``.
        #
        # ``0x54`` hat Vorrang. Es ist die **Antwort auf die Frage** nach
        # dem Grund; ``manualSwitch`` ist der Nebeneffekt einer Meldung.
        # Traegt ein Frame beides, ist die Antwort die genauere Quelle.
        "change_reason": obj.get("relayChangeReason")
        or ("manual_button" if obj.get("manualSwitch") else None),
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


#: Welches Codec-Feld welche Ruecklesung belegt. Die Namen links sind die
#: des Codecs, die rechts die von ``relay_service.vermerke_ruecklesung``.
RUECKLESUNGEN: dict[str, str] = {
    "stateAfterPowerReturn": "power_return",
    "stateAfterOverheatingRecovery": "overheating_recovery",
}


async def _vermerke_ruecklesungen(
    session: AsyncSession, *, device_id: int, obj: dict[str, Any]
) -> dict[str, bool]:
    """Haelt die Antworten auf ``0x5F`` und ``0x5A`` am Geraet fest.

    **Der Befund des Betreibers, 01.11.2026, und er ist der dritte dieser
    Art an diesem Geraet.** Relais 109 hat die Ruecklesung geschickt, der
    Codec hat sie richtig dekodiert — und die Geraeteseite zeigte weiter
    „Aus nach Stromrueckkehr: nicht bestaetigt". Der Frame
    (``5f 02`` plus Keepalive, 09:48:11) trug ``stateAfterPowerReturn =
    "off"``, also ein **bestandenes** Ergebnis.

    Der Grund: ``relay_service.vermerke_ruecklesung`` hatte **keinen
    Aufrufer**. Die Funktion ist seit Sprint 24b da, ist getestet, und
    zwischen ihr und dem Uplink lag nichts. Das ist §5.87 in Reinform —
    und in derselben Woche zum dritten Mal in diesem Geraetepfad: die
    Firmware kam nicht an, der Tastendruck verlor seinen Grund, und jetzt
    die Ruecklesung. Alle drei Male war die Funktion in Ordnung.

    **Kein Zeitvergleich gegen die Provisionierungszeit**, und das ist
    eine Entscheidung mit Begruendung. Es gilt die **jüngste** Meldung:

    * Nur ``off`` setzt den Vermerk, und ``off`` kann das Geraet erst
      melden, **nachdem** ``0x5E 02`` bzw. ``0x59 01`` gesessen hat. Eine
      veraltete Antwort kann den Vermerk also nicht faelschlich setzen.
    * ``last_state`` **loescht** ihn (so war die Funktion schon gebaut).
      Eine veraltete Antwort kann ihn damit nur loeschen — die sichere
      Richtung, denn ohne Vermerk gibt es keine Inbetriebnahme.

    Das ist der Unterschied zur Kindersicherung, wo die Zeit **sehr wohl**
    zaehlt: dort ist das Geraet Class A, und die erste Meldung nach dem
    Befehl traegt noch den alten Zustand (§10ar). Ein 16ASPM ist Class C,
    bekommt den Befehl sofort und antwortet danach.

    Belegt mit den beiden Frames vom 01.11.2026: ``5a 00`` um 09:45 (vor
    dem Setzen, ``last_state``) und ``5f 02`` um 09:48 (nach dem Setzen,
    ``off``).
    """
    gefunden = {
        was: str(obj[feld]) for feld, was in RUECKLESUNGEN.items() if obj.get(feld) is not None
    }
    if not gefunden:
        return {}

    geraet = await session.get(Device, device_id)
    if geraet is None:
        logger.warning("ruecklesung ohne Geraet in der DB device_id=%s", device_id)
        return {}

    return {
        was: relay_service.vermerke_ruecklesung(geraet, was=was, wert=wert)
        for was, wert in gefunden.items()
    }


async def _zaehle_einschaltung(
    session: AsyncSession,
    *,
    device_id: int,
    neu: bool | None,
) -> bool:
    """Zaehlt eine beobachtete Einschaltung. Gibt zurueck, ob gezaehlt wurde.

    Gezaehlt wird **ein Wechsel von aus auf ein**, und nur der. Die drei
    Faelle, die nicht zaehlen, haben jeder einen Grund:

    ``neu is None``
        Eine Zeile ohne ``relay_on`` sagt nichts ueber den Zustand (etwa
        eine reine Befehlsantwort ohne Keepalive-Schwanz). Sie darf
        keinen Wechsel vortaeuschen — dieselbe Regel wie in
        ``relay_state``.

    ``vorher is None``
        **Noch nie etwas gehoert.** Dass die erste Meldung „ein" sagt,
        heisst nicht, dass das Geraet gerade angelaufen ist — es kann
        seit Tagen laufen. Eine Einschaltung zu zaehlen, die niemand
        gesehen hat, waere eine Behauptung; der Zaehler soll
        Beobachtungen zaehlen.

    ``vorher is True``
        Kein Wechsel. Das ist zugleich die **Wiederholungsfestigkeit**:
        wird dieselbe Meldung zweimal verarbeitet, hat der erste Durchlauf
        die Zeile eingefuegt, der zweite sieht sie als Vorzustand und
        zaehlt nicht erneut. Deshalb steht der Aufruf **vor** dem
        Einfuegen und nicht danach.
    """
    if neu is not True:
        return False

    vorher = await relay_state.bestaetigter_zustand(session, device_id)
    if vorher.ein is not False:
        return False

    geraet = await session.get(Device, device_id)
    if geraet is None:
        return False

    geraet.switch_cycles += 1
    logger.info(
        "einschaltung gezaehlt device_id=%s stand=%s",
        device_id,
        geraet.switch_cycles,
    )
    return True


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

    # **Der Schaltzyklus wird hier gezaehlt, vor dem Einfuegen** (Befund
    # des Betreibers, 12.11.2026). Vorher zaehlte ihn der Waechter, wenn
    # ein von ihm abgesetzter Befehl bestaetigt wurde — und verlor ihn
    # genau im Fall, fuer den der Zaehler gebaut ist.
    #
    # Gemessen am 12.11.: um 09:38 ging ein EIN hinaus, um 09:40 kippte
    # der Wunsch auf AUS (der Fuehler war wieder im Haus und ueber dem
    # Soll), und der Waechter verwarf den offenen Stand — richtig so,
    # sonst bremst sein Backoff einen Befehl, den niemand mehr will. Als
    # die Bestaetigung um 09:47 kam, gab es keinen offenen Stand mehr, an
    # dem sie haengen konnte. Das Relais hat geschaltet und der Zaehler
    # stand auf 1 statt auf 2.
    #
    # Dieselbe Spur sagt, warum **die Meldung** die richtige Stelle ist:
    # der Zustand, den das Geraet meldet, ist die einzige belastbare
    # Quelle (dieselbe Haltung wie in ``relay_state``). Was wir gesendet
    # haben, steht in ``device.pending_*`` und ist eine Absicht.
    #
    # **Was der Zaehler damit sagt, hat sich geaendert**, und das Etikett
    # in der Oberflaeche ist im selben Schritt nachgezogen: gezaehlt wird
    # jede **beobachtete** Einschaltung, auch eine ueber den Handschalter
    # oder nach einer Stromrueckkehr. Das ist mehr als „was der
    # Orchestrator bestaetigt bekam" und genau das, was der Betreiber
    # wissen will — wie oft das Panel wirklich angelaufen ist.
    gezaehlt = await _zaehle_einschaltung(session, device_id=device_id, neu=werte["relay_on"])

    await session.execute(
        pg_insert(RelayReading)
        .values(**werte)
        .on_conflict_do_nothing(index_elements=["time", "device_id"])
    )

    protokoll: dict[str, Any] = {
        "relay_on": werte["relay_on"],
        "power_w": werte["power_w"],
        "sperre_gesetzt": False,
        "einschaltung_gezaehlt": gezaehlt,
    }

    protokoll["ruecklesungen"] = await _vermerke_ruecklesungen(
        session, device_id=device_id, obj=obj
    )

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
