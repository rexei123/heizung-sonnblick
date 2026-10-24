"""Orchestrator fuer Relais-Zonen (Sprint 24b, Paket 3).

**Was dieser Task tut, und warum er der fehlende Teil war.** Sprint 24
hat die Entscheidungen gebaut — Zweipunktregler, Waechter, Sperren — und
niemanden, der sie ausfuehrt. Ohne diesen Task schaltet kein Relais.

Je Zone mit mindestens einem Relais:

1. **Soll** holen: der Sollwert, den die Engine fuer das Zimmer dieser
   Zone zuletzt geschrieben hat (``HARD_CLAMP`` im Schicht-Trace).
2. **Ist** holen: das Zonen-Aggregat ueber die Geraete der Zone
   (``aggregate_zone_readings``, AE-51) — also ueber die Fuehler.
3. **Veraltung** pruefen (S5): kein Messwert seit mehr als dem
   Zweieinhalbfachen des Keepalive-Intervalls.
4. **Regler** (``zweipunkt.entscheide``) → EIN, AUS oder unveraendert.
5. Je Relais der Zone: **Waechter** (``relais_waechter.naechste_aktion``)
   → senden, warten oder alarmieren.

**Was hier nicht entschieden wird.** Dieser Task enthaelt keine
Fachlogik: er holt Werte, ruft die reinen Funktionen und fuehrt deren
Ergebnis aus. Das ist der Grund, warum S1 bis S5 ohne Datenbank pruefbar
sind — und warum sie hier nicht noch einmal stehen.

**Drei Gates vor jedem Schaltbefehl**, alle in
``relay_service.darf_schalten``:

- ein Relais, kein Thermostat
- nicht ausgemustert
- ``commissioned_at`` gesetzt (S3)
- keine stehende Schutz-Sperre (S4)

Die Pruefung steht **hier** und nicht nur im Endpunkt. Mutationsproben
M10 (Inbetriebnahme ignoriert) und M11 (Sperre ignoriert) greifen genau
diese Zeile an.

**Tick-Intervall und Funkzeit.** Der Task laeuft alle **60 Sekunden**,
im selben Takt wie die Engine-Auswertung. Das ist nicht die Zahl der
Downlinks: gesendet wird nur bei einem **Wechsel** oder einer
Wiederholung.

Rechnung fuer den Pilot, mit den Vorgaben aus den Settings
(``EXPIRE_AND_RESEND``, Timer 30 min, Mindestlauf und Mindestpause je
10 min):

| Groesse | Wert |
|---|---|
| Schaltzyklen je Stunde und Relais | hoechstens **3** (10 min Lauf + 10 min Pause) |
| Downlinks je Zyklus | 2 (ein ``0x57``, ein ``0xC1 00``) |
| Downlinks je Stunde und Relais | hoechstens **6** |
| Sendezeit je Downlink bei SF7, 4 Byte | rund **50 ms** |
| Sendezeit je Stunde und Relais | rund **0,3 s** |

Bei zehn Relais sind das rund 3 Sekunden Sendezeit je Stunde, also etwa
**0,08 %** der Stunde. Die EU868-Grenze am Gateway liegt je nach Band bei
1 % oder 10 %. Zum Vergleich: die 104 Vickis bekommen ihre Sollwerte
ueber dieselbe Luftschnittstelle, und ihr Heartbeat allein sind 104
Downlinks je sechs Stunden.

**Diese Zahlen sind gerechnet, nicht gemessen.** Die Sendezeit haengt am
Spreizfaktor, den das Netz dem Geraet zuweist; bei SF12 ist sie rund
zwanzigmal hoeher. Das ist der Grund, warum der Rollout auf mehr als ein
Relais einen Pflicht-Stopp hat (RUNBOOK §10aj Schritt 8) — und warum
hier ``EXPIRE_AND_RESEND`` die Vorgabe ist: ``REFRESH`` wuerde die
Downlink-Zahl etwa **verfuenffachen** (alle 5 min je Relais statt nur
bei Wechseln).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, WatchdogStrategy
from heizung.models.heating_zone import HeatingZone
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings
from heizung.rules.relais_waechter import (
    Offen,
    WaechterAktion,
    WaechterSchwellen,
    naechste_aktion,
)
from heizung.rules.zweipunkt import (
    Schaltbefehl,
    Zonenzustand,
    ZweipunktSchwellen,
    einschalt_versatz,
    entscheide,
)
from heizung.services import relay_adapter, relay_service, relay_state
from heizung.services.device_service import get_active_devices_for_zone
from heizung.services.event_log import latest_hard_clamp_setpoint_per_room
from heizung.tasks.engine_tasks import _task_session

logger = logging.getLogger(__name__)

#: Faktor auf das Keepalive-Intervall des Fuehlers, ab dem ein Messwert
#: als veraltet gilt (S5). Zweieinhalb und nicht zwei: ein einzelner
#: verlorener Uplink soll keine Zone abschalten, zwei verlorene in Folge
#: schon. Bei einem Vicki-Intervall von einer Stunde sind das 2,5 h.
VERALTUNGS_FAKTOR = Decimal("2.5")


def zweipunkt_schwellen() -> ZweipunktSchwellen:
    """Die Regler-Parameter aus den Settings, einmal je Durchlauf."""
    s = get_settings()
    return ZweipunktSchwellen(
        ein_delta_k=s.relay_ein_delta_k,
        aus_delta_k=s.relay_aus_delta_k,
        min_lauf=timedelta(minutes=s.relay_min_lauf_min),
        min_pause=timedelta(minutes=s.relay_min_pause_min),
    )


def waechter_schwellen() -> WaechterSchwellen:
    """Die Waechter-Parameter aus den Settings, einmal je Durchlauf."""
    s = get_settings()
    return WaechterSchwellen(
        timer_expire=timedelta(seconds=s.relay_timer_expire_s),
        timer_refresh=timedelta(seconds=s.relay_timer_refresh_s),
        refresh_abstand=timedelta(seconds=s.relay_refresh_intervall_s),
        bestaetigungs_frist=timedelta(seconds=s.relay_bestaetigungs_frist_s),
        max_versuche=s.relay_max_versuche,
    )


@app.task(name="heizung.steuere_relais_zonen", bind=True)
def steuere_relais_zonen(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Beat-Einstieg. Synchron, wie alle Tasks dieses Projekts."""
    return asyncio.run(_steuere_relais_zonen_async())


async def _steuere_relais_zonen_async(*, now: datetime | None = None) -> dict[str, Any]:
    """Ein Durchlauf ueber alle Zonen mit Relais.

    ``now`` ist injizierbar, damit der Ende-zu-Ende-Test ohne
    Zeitmanipulation auskommt (§5.59 — ``freeze_time`` greift nicht in
    Fixtures, und dieser Pfad liest Zeiten aus der Datenbank).
    """
    jetzt = now or datetime.now(tz=UTC)
    ergebnis: dict[str, Any] = {
        "zonen": 0,
        "relais": 0,
        "gesendet": 0,
        "alarme": 0,
        "uebersprungen": 0,
        "details": [],
    }

    regler_schwellen = zweipunkt_schwellen()
    wschwellen = waechter_schwellen()

    async with _task_session() as session:
        zonen_ids = await _zonen_mit_relais(session)
        ergebnis["zonen"] = len(zonen_ids)

        for zone_id in zonen_ids:
            zone_ergebnis = await _steuere_eine_zone(
                session,
                zone_id=zone_id,
                regler_schwellen=regler_schwellen,
                wschwellen=wschwellen,
                jetzt=jetzt,
            )
            ergebnis["relais"] += zone_ergebnis["relais"]
            ergebnis["gesendet"] += zone_ergebnis["gesendet"]
            ergebnis["alarme"] += zone_ergebnis["alarme"]
            ergebnis["uebersprungen"] += zone_ergebnis["uebersprungen"]
            ergebnis["details"].append(zone_ergebnis)

        await session.commit()

    logger.info(
        "relais-orchestrator zonen=%s relais=%s gesendet=%s alarme=%s uebersprungen=%s",
        ergebnis["zonen"],
        ergebnis["relais"],
        ergebnis["gesendet"],
        ergebnis["alarme"],
        ergebnis["uebersprungen"],
    )
    return ergebnis


async def _zonen_mit_relais(session: AsyncSession) -> list[int]:
    """Zonen, in denen mindestens ein nicht ausgemustertes Relais haengt.

    **Ohne** Filter auf ``commissioned_at``: eine Zone mit einem noch
    nicht in Betrieb genommenen Relais soll trotzdem durchlaufen, damit
    das Ergebnis sie als ``uebersprungen`` nennt. Eine Zone, die gar
    nicht auftaucht, sieht aus wie eine, die es nicht gibt.
    """
    stmt = (
        select(Device.heating_zone_id)
        .where(Device.kind == DeviceKind.RELAY)
        .where(Device.retired_at.is_(None))
        .where(Device.heating_zone_id.is_not(None))
        .distinct()
        .order_by(Device.heating_zone_id)
    )
    return [z for z in (await session.execute(stmt)).scalars().all() if z is not None]


async def _steuere_eine_zone(
    session: AsyncSession,
    *,
    zone_id: int,
    regler_schwellen: ZweipunktSchwellen,
    wschwellen: WaechterSchwellen,
    jetzt: datetime,
) -> dict[str, Any]:
    """Regler- und Waechter-Durchlauf fuer eine Zone."""
    ergebnis: dict[str, Any] = {
        "zone_id": zone_id,
        "relais": 0,
        "gesendet": 0,
        "alarme": 0,
        "uebersprungen": 0,
    }

    zone = await session.get(HeatingZone, zone_id)
    if zone is None:
        return ergebnis

    geraete = await get_active_devices_for_zone(session, zone_id)
    relais = [d for d in geraete if d.kind == DeviceKind.RELAY]
    fuehler = [d for d in geraete if d.kind != DeviceKind.RELAY]
    ergebnis["relais"] = len(relais)

    # --- Soll: was die Engine fuer das Zimmer dieser Zone entschieden hat.
    soll_je_raum = await latest_hard_clamp_setpoint_per_room(session, [zone.room_id])
    soll_roh = soll_je_raum.get(zone.room_id)
    if soll_roh is None:
        # Noch keine Engine-Auswertung fuer dieses Zimmer. Nicht schalten —
        # und das ist kein Fehler, sondern der Zustand vor dem ersten Tick.
        ergebnis["grund"] = "kein_engine_soll"
        ergebnis["uebersprungen"] = len(relais)
        return ergebnis
    soll = Decimal(soll_roh)

    # --- Ist: Zonen-Aggregat ueber die Fuehler.
    ist, veraltet = await _ist_und_veraltung(session, fuehler, jetzt=jetzt)

    # --- Regler.
    zonen_zustand = await _zonen_schaltzustand(session, relais)
    regler = entscheide(
        ist=ist,
        soll=soll,
        zustand=zonen_zustand,
        schwellen=regler_schwellen,
        now=jetzt,
        fuehler_veraltet=veraltet,
    )
    ergebnis["soll"] = str(soll)
    ergebnis["ist"] = str(ist) if ist is not None else None
    ergebnis["regler"] = regler.befehl.value
    ergebnis["regler_grund"] = regler.grund

    gewuenscht_ein = _gewuenscht_ein(regler.befehl, zonen_zustand)

    # --- Waechter je Relais.
    versatz = timedelta(minutes=get_settings().relay_einschalt_versatz_min)
    for index, geraet in enumerate(relais):
        if not relay_service.darf_schalten(geraet):
            # S3 und S4. **Die Stelle, die M10 und M11 angreifen.**
            ergebnis["uebersprungen"] += 1
            logger.info(
                "relais uebersprungen device_id=%s commissioned=%s sperre=%s",
                geraet.id,
                geraet.commissioned_at is not None,
                geraet.protection_kind,
            )
            continue

        zustand = await relay_state.bestaetigter_zustand(session, geraet.id)
        offen = _offener_befehl(geraet)

        befehl = naechste_aktion(
            # Am Rand umwandeln, nicht per ``type: ignore`` durchreichen.
            # Die Spalte ist ``String(20)``; ein roher String haette den
            # Identitaets-Vergleich im Waechter verfehlt und waere in den
            # REFRESH-Zweig gefallen -- also in die riskantere Strategie,
            # ohne dass jemand sie gewaehlt hat. Genau das hat der
            # Ende-zu-Ende-Test gefunden, und das ``type: ignore`` hatte
            # die Meldung unterdrueckt, die es gezeigt haette.
            strategie=WatchdogStrategy(geraet.watchdog_strategy),
            gewuenscht_ein=gewuenscht_ein,
            bestaetigt_ein=zustand.ein,
            offen=offen,
            letzter_ein_befehl=geraet.pending_since,
            schwellen=wschwellen,
            now=jetzt,
        )

        # Ein bestaetigter Befehl: offenen Stand loeschen und bei einem
        # EIN einen Schaltzyklus zaehlen.
        if befehl.aktion is WaechterAktion.NICHTS and befehl.grund == "bestaetigt":
            if offen is not None and offen.ziel_ein:
                geraet.switch_cycles += 1
            _loesche_offen(geraet)
            continue

        # Unbekannter Zustand: **fragen**, nicht schweigen.
        #
        # Der Waechter schaltet bei unbekanntem Zustand bewusst nicht ein
        # (Sprint 24, AE-78 §9.3) — ein Relais, von dem wir nicht wissen,
        # ob es heizt, bekommt kein EIN. Das allein wuerde ein frisches
        # Relais aber **dauerhaft** stilllegen: ohne Zeile in
        # ``relay_reading`` gibt es keinen Zustand, und ohne Befehl gibt
        # es keine Zeile.
        #
        # Aufgefallen ist das im Ende-zu-Ende-Test, nicht beim Entwerfen:
        # der Regler sagte EIN, und es ging nichts hinaus.
        #
        # ``0xB1`` ist ein **Lese**-Befehl. Er schaltet nichts, und S3
        # erlaubt Lesen ausdruecklich auch an einem Relais, das nicht in
        # Betrieb genommen ist — hier kommt er ohnehin nur fuer
        # freigegebene Geraete zum Einsatz.
        if befehl.aktion is WaechterAktion.NICHTS and befehl.grund == "zustand_unbekannt":
            await relay_adapter.frage_zustand(geraet.dev_eui)
            ergebnis["gefragt"] = ergebnis.get("gefragt", 0) + 1
            logger.info("relais-zustand unbekannt, 0xB1 gesendet device_id=%s", geraet.id)
            continue

        if befehl.aktion is WaechterAktion.ALARM:
            ergebnis["alarme"] += 1
            logger.error(
                "relais ohne bestaetigung device_id=%s ziel_ein=%s versuche=%s",
                geraet.id,
                offen.ziel_ein if offen else None,
                offen.versuche if offen else 0,
            )
            _loesche_offen(geraet)
            continue

        if befehl.aktion is WaechterAktion.SENDE_EIN:
            # Der Versatz gilt **nur** beim Einschalten: er zieht den
            # Einschaltstrom mehrerer Panels auseinander. Beim
            # Ausschalten gibt es keinen Grund zu warten, und bei einem
            # Zwangs-AUS waere er schaedlich.
            warten = einschalt_versatz(index, versatz)
            if warten and geraet.pending_since is None and offen is None:
                faellig = zonen_zustand.seit or jetzt
                if jetzt - faellig < warten:
                    ergebnis["uebersprungen"] += 1
                    continue
            await relay_adapter.relais_ein_fuer(geraet.dev_eui, befehl.sekunden or 0)
            _setze_offen(geraet, ziel_ein=True, jetzt=jetzt, offen=offen)
            ergebnis["gesendet"] += 1
            continue

        if befehl.aktion is WaechterAktion.SENDE_AUS:
            await relay_adapter.relais_aus(geraet.dev_eui)
            _setze_offen(geraet, ziel_ein=False, jetzt=jetzt, offen=offen)
            ergebnis["gesendet"] += 1
            continue

    return ergebnis


def _gewuenscht_ein(befehl: Schaltbefehl, zustand: Zonenzustand) -> bool:
    """Uebersetzt die Regler-Entscheidung in den **Wunsch** des Waechters.

    ``UNVERAENDERT`` heisst nicht „nichts tun", sondern „der bisherige
    Wunsch gilt weiter" — sonst wuerde der Waechter bei jedem Tick im
    Totband einen AUS-Wunsch sehen und das Relais abschalten, obwohl der
    Regler es gerade bewusst laufen laesst.
    """
    if befehl is Schaltbefehl.EIN:
        return True
    if befehl is Schaltbefehl.AUS:
        return False
    return zustand.ein


async def _zonen_schaltzustand(session: AsyncSession, relais: list[Device]) -> Zonenzustand:
    """Der Schaltzustand der Zone aus ihren Relais.

    Alle Relais einer Zone folgen derselben Entscheidung (Vorgabe des
    Briefs), also ist der Zustand der Zone der Zustand ihrer Relais. Bei
    mehreren gilt die Zone als **ein**, sobald eines ein ist — das ist die
    sichere Richtung fuer die Mindestlaufzeit und fuer den Zwangs-AUS.

    ``seit`` ist der **frueheste** Beginn unter den eingeschalteten
    Relais. Beim spaetesten zu rechnen wuerde die Mindestlaufzeit mit
    jedem versetzt zugeschalteten Panel neu starten.
    """
    ein = False
    seit: datetime | None = None
    for geraet in relais:
        zustand = await relay_state.bestaetigter_zustand(session, geraet.id)
        if zustand.ein:
            ein = True
            if zustand.seit is not None and (seit is None or zustand.seit < seit):
                seit = zustand.seit
        elif not ein and zustand.seit is not None and (seit is None or zustand.seit < seit):
            seit = zustand.seit
    return Zonenzustand(ein=ein, seit=seit)


async def _ist_und_veraltung(
    session: AsyncSession,
    fuehler: list[Device],
    *,
    jetzt: datetime,
) -> tuple[Decimal | None, bool]:
    """Zonen-Ist und ob der Fuehler veraltet ist (S5).

    Der Istwert kommt aus ``aggregate_zone_readings`` (AE-51) — also aus
    demselben Helfer, den die Zonen-Anzeige benutzt. Zwei Rechnungen fuer
    dieselbe Zahl waeren zwei Wahrheiten.

    **Veraltet heisst: kein Messwert im Fenster.** Das Fenster ist das
    Zweieinhalbfache des Keepalive-Intervalls des Fuehlers. Ein einzelner
    verlorener Uplink soll keine Zone abschalten, zwei in Folge schon.
    """
    if not fuehler:
        return None, False

    s = get_settings()
    fenster = timedelta(hours=float(Decimal(s.health_healthy_max_age_h) * VERALTUNGS_FAKTOR))
    schwelle = jetzt - fenster

    readings: list[ReadingForAggregate] = []
    irgendwas_frisch = False
    for geraet in fuehler:
        zeile = (
            await session.execute(
                select(SensorReading.time, SensorReading.temperature, SensorReading.open_window)
                .where(SensorReading.device_id == geraet.id)
                .order_by(SensorReading.time.desc())
                .limit(1)
            )
        ).first()
        if zeile is None:
            continue
        zeit, temperatur, fenster_offen = zeile
        if zeit >= schwelle:
            irgendwas_frisch = True
        readings.append(
            ReadingForAggregate(
                temperature_c=temperatur,
                open_window=fenster_offen,
                health_state=geraet.health_state,
            )
        )

    ist, _ = aggregate_zone_readings(readings)
    return ist, not irgendwas_frisch


def _offener_befehl(geraet: Device) -> Offen | None:
    if geraet.pending_target_on is None or geraet.pending_since is None:
        return None
    return Offen(
        ziel_ein=geraet.pending_target_on,
        seit=geraet.pending_since,
        versuche=geraet.pending_attempts or 1,
    )


def _setze_offen(geraet: Device, *, ziel_ein: bool, jetzt: datetime, offen: Offen | None) -> None:
    geraet.pending_target_on = ziel_ein
    geraet.pending_since = jetzt
    geraet.pending_attempts = (offen.versuche + 1) if offen is not None else 1


def _loesche_offen(geraet: Device) -> None:
    geraet.pending_target_on = None
    geraet.pending_since = None
    geraet.pending_attempts = 0
