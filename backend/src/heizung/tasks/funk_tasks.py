"""Stuendlicher Beat-Task fuer den Funk-Waechter (Sprint 25 T6).

``celery_beat`` ruft ``pruefe_funkqualitaet`` einmal je Stunde. Faellt der
hausweite SNR-Mittelwert um mehr als ``FUNK_WARN_DELTA_DB`` unter das
Mittel der Vorwoche, entsteht ein ``FUNK_QUALITAET_GEFALLEN``-Audit und —
durch die Wiederholungsbremse gefiltert — eine Mail.

**Stuendlich und nicht alle fuenf Minuten.** Der Waechter mittelt ueber
zwei Stunden; ein schnellerer Takt wuerde dieselbe Zahl oefter lesen und
nur die Bremse belasten. Nichts an der Funkqualitaet bewegt sich in
Minuten — der Sprung vom 04.11. war ein Stufenwechsel innerhalb einer
Stunde und danach 25 Stunden flach.

**Es wird nichts gesteuert.** Kein Downlink, kein Sollwert, kein Zustand
am Geraet. Der Task liest, urteilt, protokolliert und versendet.

Inzwischen wohnen hier **drei** Waechter, und sie beantworten drei
verschiedene Fragen — absichtlich getrennt, weil jede eine andere
Handlung nach sich zieht:

====================================== ============================ =======
Task                                   Frage                        Takt
====================================== ============================ =======
``pruefe_funkqualitaet``               wird das Haus schlechter      1 h
                                       empfangen als vorige Woche?
``pruefe_totalausfall``                kommt ueberhaupt noch etwas?  5 min
``pruefe_relais_zone``              hat jede Zone mit einem       5 min
                                       Relais in Betrieb einen
                                       aktuellen Fuehlerwert?
====================================== ============================ =======

Eigene Engine + Session pro Task-Run (§5.14), Vorbild
``tasks/occupancy_import_tasks``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.business_audit import BusinessAudit
from heizung.models.global_config import GlobalConfig
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.services import (
    alert_throttle,
    funk_waechter,
    funkempfang,
    mail_status,
    mailer,
    relais_zone_melder,
)
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

#: Die Aktion im ``business_audit``. Eigene Marke, damit sie neben
#: ``OCCUPANCY_IMPORT_STALE`` und ``ENGINE_ABGLEICH_ERSCHOEPFT`` steht —
#: dieselbe Familie: ein Waechter, der etwas festhaelt, ohne einzugreifen.
AUDIT_FUNK_GEFALLEN = "FUNK_QUALITAET_GEFALLEN"


@contextlib.asynccontextmanager
async def _task_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=False,
        pool_size=2,
        max_overflow=0,
    )
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _run() -> dict[str, Any]:
    """Async-Koerper des Tasks. Public fuer Tests."""
    settings = get_settings()
    schwellen = funk_waechter.Schwellen(
        warn_delta_db=settings.funk_warn_delta_db,
        min_meldungen=settings.funk_min_meldungen,
        min_geraete=settings.funk_min_geraete,
    )

    async with _task_session() as session:
        befund = await funk_waechter.pruefe_funkqualitaet(
            session,
            schwellen,
            fenster_stunden=settings.funk_fenster_stunden,
            grundlinie_tage=settings.funk_grundlinie_tage,
        )

        ergebnis: dict[str, Any] = {
            "stufe": befund.stufe,
            "grund": befund.grund,
            "delta_snr_db": str(befund.delta_snr_db) if befund.delta_snr_db is not None else None,
            "gemeldet": False,
        }
        if not befund.ist_warnung:
            return ergebnis

        # Das Audit entsteht **bedingungslos** bei einer Warnung, auch wenn
        # die Bremse greift oder keine Adresse hinterlegt ist. Es ist die
        # Spur; die Mail ist der Weckruf. Dieselbe Trennung wie bei den
        # Health-Alarmen (Logger je Uebergang, Mail gebremst).
        await record_business_action(
            session,
            user_id=None,
            action=AUDIT_FUNK_GEFALLEN,
            target_type="haus",
            target_id=None,
            old_value={
                "snr_db": str(befund.grundlinie.snr_db),
                "rssi_dbm": str(befund.grundlinie.rssi_dbm),
                "meldungen": befund.grundlinie.meldungen,
            },
            new_value={
                "snr_db": str(befund.fenster.snr_db),
                "rssi_dbm": str(befund.fenster.rssi_dbm),
                "meldungen": befund.fenster.meldungen,
                "geraete": befund.fenster.geraete,
                "delta_snr_db": str(befund.delta_snr_db),
                "delta_rssi_db": (
                    str(befund.delta_rssi_db) if befund.delta_rssi_db is not None else None
                ),
                "hinweis": (
                    "Hausweiter Abfall. Verdacht zuerst am Gateway, nicht an den "
                    "Geraeten. RUNBOOK 10ay Schritt 6."
                ),
            },
        )

        gc = await session.get(GlobalConfig, 1)
        empfaenger = gc.alert_email if gc else None
        zeitzone = (gc.timezone if gc and gc.timezone else None) or DEFAULT_HOTEL_TIMEZONE

        if not empfaenger:
            logger.info("funk_waechter_keine_alarmadresse stufe=warnung")
            await session.commit()
            return ergebnis

        if not alert_throttle.should_send(
            alert_throttle.KIND_FUNK_SCHWACH,
            alert_throttle.SUBJECT_FUNK_HAUS,
            ttl_s=settings.funk_mail_sperre_stunden * 3600,
        ):
            logger.info("funk_waechter_mail_gebremst stufe=warnung")
            await session.commit()
            return ergebnis

        result = mailer.send_mail(
            recipient=empfaenger,
            subject=funk_waechter.betreff(befund),
            body=funk_waechter.nachricht(befund, zeitzone=zeitzone),
        )
        # Pflicht fuer neue Alarmwege (``services/mail_status``): wer
        # versendet, haelt das Ergebnis fest. Sonst sieht der Naechste, der
        # nachsieht, warum keine Mail kam, den Zustand eines **anderen**
        # Alarms.
        await mail_status.record_attempt(session, result)
        await session.commit()

        if not result.sent:
            logger.warning(
                "funk_waechter_mail_nicht_zugestellt grund=%s detail=%s",
                result.reason,
                result.detail,
            )
        ergebnis["gemeldet"] = bool(result.sent)
        return ergebnis


@app.task(name="heizung.pruefe_funkqualitaet", bind=True)
def pruefe_funkqualitaet(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Stuendlicher Beat-Task: hausweiter SNR gegen das Mittel der Vorwoche."""
    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Totalausfall: gar keine Messwerte mehr (Sprint 25 T8)
# ---------------------------------------------------------------------------

#: Die beiden Audit-Marken. Sie sind **gleichzeitig der Zustand** — siehe
#: ``_letzter_totalausfall_stand``.
AUDIT_TOTALAUSFALL = "FUNK_TOTALAUSFALL"
AUDIT_TOTALAUSFALL_ENDE = "FUNK_TOTALAUSFALL_ENDE"


def _zeitzone(gc: GlobalConfig | None) -> str:
    return (gc.timezone if gc and gc.timezone else None) or DEFAULT_HOTEL_TIMEZONE


async def _letzter_totalausfall_stand(
    session: AsyncSession,
) -> tuple[str | None, datetime | None]:
    """Die juengste der beiden Marken — Aktion und Zeitpunkt.

    **Warum der Zustand aus ``business_audit`` kommt und nicht aus Redis.**
    Er muss zwei Dinge beantworten: laeuft gerade ein Ausfall (fuer die
    Entwarnung), und wann wurde zuletzt gemailt (fuer die Wiederholung).
    Beide stehen in den Zeilen, die dieser Task ohnehin schreibt.

    Ein Redis-Schluessel waere die naheliegende Wahl und die schlechtere:
    er verliert sich beim Neustart, und ``alert_throttle`` laesst bei
    Redis-Ausfall **alles** durch (siehe dort). Bei einem Alarm mit genau
    einem Gegenstand und einem Fuenf-Minuten-Takt waeren das zwoelf Mails
    je Stunde, solange Redis weg ist — der Melder wuerde seinen eigenen
    Ausfall vertonen (Paragraph 5.79).

    Die Audit-Tabelle ueberlebt den Neustart, und die Spur **ist** der
    Zustand. Eine Wahrheit statt zwei (Paragraph 5.53).
    """
    stmt = (
        select(BusinessAudit.action, BusinessAudit.ts)
        .where(BusinessAudit.action.in_([AUDIT_TOTALAUSFALL, AUDIT_TOTALAUSFALL_ENDE]))
        .order_by(BusinessAudit.ts.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None, None
    return row[0], row[1]


async def _mail_und_audit(
    session: AsyncSession,
    *,
    action: str,
    befund: funkempfang.Funkempfang,
    betreff: str,
    text: str,
) -> bool:
    """Audit **bedingungslos**, Mail nur mit Adresse. Gibt zurueck, ob gemailt wurde.

    Dieselbe Trennung wie bei den Health-Alarmen: die Zeile ist die Spur,
    die Mail der Weckruf. Ohne Alarm-Adresse entsteht die Zeile trotzdem —
    sonst waere der Vorgang nachher nicht nachvollziehbar.
    """
    await record_business_action(
        session,
        user_id=None,
        action=action,
        target_type="haus",
        target_id=None,
        old_value=None,
        new_value={
            "letzte_meldung": (
                befund.letzte_meldung.isoformat() if befund.letzte_meldung else None
            ),
            "alter_min": befund.alter_min,
            "meldungen_10min": befund.meldungen_zaehlfenster,
            "stufe": befund.stufe,
        },
    )

    gc = await session.get(GlobalConfig, 1)
    empfaenger = gc.alert_email if gc else None
    if not empfaenger:
        logger.info("totalausfall_keine_alarmadresse action=%s", action)
        return False

    result = mailer.send_mail(recipient=empfaenger, subject=betreff, body=text)
    # Pflicht fuer neue Alarmwege (``services/mail_status``).
    await mail_status.record_attempt(session, result)
    if not result.sent:
        logger.warning(
            "totalausfall_mail_nicht_zugestellt action=%s grund=%s",
            action,
            result.reason,
        )
    return bool(result.sent)


async def _run_totalausfall() -> dict[str, Any]:
    """Async-Koerper des Tasks. Public fuer Tests."""
    settings = get_settings()
    async with _task_session() as session:
        befund = await funkempfang.lies_funkempfang(
            session,
            gruen_max_min=settings.funkempfang_gruen_max_min,
            gelb_max_min=settings.funkempfang_gelb_max_min,
        )
        letzte_aktion, letzte_zeit = await _letzter_totalausfall_stand(session)
        ausfall_laeuft = letzte_aktion == AUDIT_TOTALAUSFALL
        zeitzone = _zeitzone(await session.get(GlobalConfig, 1))

        ergebnis: dict[str, Any] = {
            "stufe": befund.stufe,
            "alter_min": befund.alter_min,
            "meldungen_10min": befund.meldungen_zaehlfenster,
            "gemailt": False,
            "aktion": None,
        }

        # Die Schwelle des Alarms ist **nicht** die der Kachel: die Kachel
        # wird bei ``funkempfang_gelb_max_min`` rot, gemailt wird erst ab
        # ``totalausfall_min``. Der Validator in den Settings haelt die
        # Reihenfolge fest — sonst findet jemand eine gelbe Kachel zu
        # einer roten Mail.
        reif = (
            befund.ist_totalausfall
            and befund.alter_min is not None
            and befund.alter_min >= settings.totalausfall_min
        )

        if reif:
            # Wiederholungsbremse aus der Audit-Spur, nicht aus Redis.
            zu_frueh = (
                ausfall_laeuft
                and letzte_zeit is not None
                and datetime.now(tz=UTC) - letzte_zeit
                < timedelta(hours=settings.totalausfall_wiederholung_h)
            )
            if zu_frueh:
                logger.info("totalausfall_gebremst alter_min=%s", befund.alter_min)
                return ergebnis
            ergebnis["aktion"] = AUDIT_TOTALAUSFALL
            ergebnis["gemailt"] = await _mail_und_audit(
                session,
                action=AUDIT_TOTALAUSFALL,
                befund=befund,
                betreff=funkempfang.betreff_alarm(befund),
                text=funkempfang.nachricht_alarm(befund, zeitzone=zeitzone),
            )
            await session.commit()
            return ergebnis

        # Kein Ausfall. Lief einer, folgt die Entwarnung — und zwar nur
        # dann. Eine Entwarnung ohne vorherigen Alarm waere eine Mail
        # ueber nichts.
        if ausfall_laeuft and befund.stufe in ("online", "verzoegert"):
            ergebnis["aktion"] = AUDIT_TOTALAUSFALL_ENDE
            ergebnis["gemailt"] = await _mail_und_audit(
                session,
                action=AUDIT_TOTALAUSFALL_ENDE,
                befund=befund,
                betreff=funkempfang.betreff_entwarnung(),
                text=funkempfang.nachricht_entwarnung(befund, zeitzone=zeitzone),
            )
        await session.commit()
        return ergebnis


@app.task(name="heizung.pruefe_totalausfall", bind=True)
def pruefe_totalausfall(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Beat-Task alle 5 Minuten: kommen ueberhaupt noch Messwerte an?"""
    return asyncio.run(_run_totalausfall())


# ---------------------------------------------------------------------------
# Fuehler einer Relais-Zone schweigt (13.11.2026)
# ---------------------------------------------------------------------------

#: Die beiden Audit-Marken. Wie beim Totalausfall sind sie **gleichzeitig
#: der Zustand** — nur je Zone statt je Haus (``target_id`` ist die
#: Zonen-Id). Siehe ``_letzter_zonen_stand``.
AUDIT_ZONE_STUMM = "RELAIS_ZONE_STUMM"
AUDIT_ZONE_STUMM_ENDE = "RELAIS_ZONE_STUMM_ENDE"

#: Die Namen bis zum 14.11.2026, als der Melder nur den Fuehler kannte.
#:
#: **Sie werden mitgelesen, und zwar nur gelesen.** Eine Episode, die zum
#: Zeitpunkt des Deploys offen ist, traegt noch die alte Marke; ohne sie
#: hier haette der erste Durchlauf danach keine laufende Episode gesehen
#: und eine zweite Alarm-Mail fuer denselben Vorgang geschickt. Ein
#: Melder, der beim Umbenennen seiner eigenen Marken Fehlalarm gibt, ist
#: die Sorte, die man nach einer Woche ueberliest (Paragraph 5.79).
#:
#: Entfernbar, sobald keine Episode aus der Zeit vor dem 14.11.2026 mehr
#: offen sein kann — also nach dem ersten Durchlauf, in dem alle
#: Relais-Zonen melden. Wer das aufraeumt, prueft es mit der Abfrage in
#: ``docs/status/2026-11-14-melder-relais-stumm.md``.
AUDIT_ALTE_NAMEN = ("RELAIS_ZONE_FUEHLER_STUMM", "RELAIS_ZONE_FUEHLER_STUMM_ENDE")


async def _letzter_zonen_stand(
    session: AsyncSession, *, zone_id: int
) -> tuple[str | None, datetime | None]:
    """Die juengste der beiden Marken **dieser Zone** — Aktion und Zeit.

    Derselbe Entwurf wie beim Totalausfall und aus demselben Grund: der
    Zustand muss den Neustart ueberleben, und ``alert_throttle`` laesst
    bei Redis-Ausfall alles durch. Was hier dazukommt, ist der Filter auf
    ``target_id`` — zwei Zonen koennen unabhaengig voneinander stumm
    werden, und eine gemeinsame Marke wuerde die Entwarnung der einen auf
    die andere uebertragen.
    """
    stmt = (
        select(BusinessAudit.action, BusinessAudit.ts)
        .where(
            BusinessAudit.action.in_([AUDIT_ZONE_STUMM, AUDIT_ZONE_STUMM_ENDE, *AUDIT_ALTE_NAMEN]),
            BusinessAudit.target_type == "heating_zone",
            BusinessAudit.target_id == zone_id,
        )
        .order_by(BusinessAudit.ts.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None, None
    return row[0], row[1]


async def _zonen_mail_und_audit(
    session: AsyncSession,
    *,
    action: str,
    befund: relais_zone_melder.ZonenBefund,
    betreff: str,
    text: str,
) -> bool:
    """Audit **bedingungslos**, Mail nur mit Adresse. Gibt zurueck, ob gemailt wurde."""
    await record_business_action(
        session,
        user_id=None,
        action=action,
        target_type="heating_zone",
        target_id=befund.zone_id,
        old_value=None,
        new_value={
            "zone": befund.zone_name,
            "ort": befund.ort,
            "fuehler": list(befund.fuehler),
            "letzte_meldung": (
                befund.letzte_meldung.isoformat() if befund.letzte_meldung else None
            ),
            "alter_min": befund.alter_min,
            "relais": list(befund.relais),
            "relais_letzte_meldung": (
                befund.relais_letzte_meldung.isoformat() if befund.relais_letzte_meldung else None
            ),
            "relais_alter_min": befund.relais_alter_min,
            "relais_stumm": befund.relais_stumm,
            "relais_in_betrieb": befund.relais_in_betrieb,
            "grund": befund.grund,
            # Dieselbe Liste, die in der Mail steht. Ohne sie waere im
            # Audit nachtraeglich nicht zu sehen, **wer** geschwiegen hat,
            # sondern nur, dass die Zone stumm war (Paragraph 5.68: ein
            # Befund braucht seine Zahlen, sonst wird er zur Behauptung).
            "schweigende_geraete": list(befund.schweigende_geraete),
        },
    )

    gc = await session.get(GlobalConfig, 1)
    empfaenger = gc.alert_email if gc else None
    if not empfaenger:
        logger.info(
            "relais_zone_keine_alarmadresse action=%s zone_id=%s",
            action,
            befund.zone_id,
        )
        return False

    result = mailer.send_mail(recipient=empfaenger, subject=betreff, body=text)
    # Pflicht fuer neue Alarmwege (``services/mail_status``).
    await mail_status.record_attempt(session, result)
    if not result.sent:
        logger.warning(
            "relais_zone_mail_nicht_zugestellt action=%s zone_id=%s grund=%s",
            action,
            befund.zone_id,
            result.reason,
        )
    return bool(result.sent)


async def _run_relais_zone() -> dict[str, Any]:
    """Async-Koerper des Tasks. Public fuer Tests."""
    settings = get_settings()
    async with _task_session() as session:
        zeitzone = _zeitzone(await session.get(GlobalConfig, 1))

        ergebnis: dict[str, Any] = {
            "zonen_geprueft": 0,
            "zonen_stumm": 0,
            "gemailt": 0,
            "aktionen": [],
        }

        # **Bei hausweitem Ausfall schweigt dieser Melder.** Dann kommt
        # ueberhaupt nichts an, die Totalausfall-Mail sagt das bereits,
        # und jede Zonen-Mail daneben ist dieselbe Nachricht in kleinerer
        # Schrift. Der Wert dieses Waechters liegt genau im anderen Fall:
        # das Haus ist in Ordnung und **eine** Zone ist blind — so war es
        # am 12./13.11. bei Fuehler 056.
        #
        # Folge, und sie ist gewollt: endet der hausweite Ausfall und
        # bleibt eine Zone stumm, beginnt die Episode erst dann. Das ist
        # richtig — vorher war sie kein eigener Vorgang.
        funk = await funkempfang.lies_funkempfang(
            session,
            gruen_max_min=settings.funkempfang_gruen_max_min,
            gelb_max_min=settings.funkempfang_gelb_max_min,
        )
        if funk.ist_totalausfall:
            ergebnis["uebersprungen"] = "totalausfall"
            logger.info("relais_zone_uebersprungen grund=totalausfall")
            return ergebnis

        befunde = await relais_zone_melder.lies_relais_zonen(
            session, grenze_min=settings.relais_zone_stumm_min
        )
        ergebnis["zonen_geprueft"] = len(befunde)
        ergebnis["zonen_stumm"] = sum(1 for b in befunde if b.stumm)

        jetzt = datetime.now(tz=UTC)
        for befund in befunde:
            letzte_aktion, letzte_zeit = await _letzter_zonen_stand(session, zone_id=befund.zone_id)
            # Der alte Alarm-Name zaehlt mit, der alte Entwarnungs-Name
            # nicht: eine beendete Episode ist beendet, egal wie sie
            # hiess.
            episode_laeuft = letzte_aktion in (AUDIT_ZONE_STUMM, AUDIT_ALTE_NAMEN[0])

            if befund.stumm:
                zu_frueh = (
                    episode_laeuft
                    and letzte_zeit is not None
                    and jetzt - letzte_zeit < timedelta(hours=settings.relais_zone_wiederholung_h)
                )
                if zu_frueh:
                    logger.info(
                        "relais_zone_gebremst zone_id=%s grund=%s alter_min=%s relais_alter_min=%s",
                        befund.zone_id,
                        befund.grund,
                        befund.alter_min,
                        befund.relais_alter_min,
                    )
                    continue
                gemailt = await _zonen_mail_und_audit(
                    session,
                    action=AUDIT_ZONE_STUMM,
                    befund=befund,
                    betreff=relais_zone_melder.betreff_alarm(befund),
                    text=relais_zone_melder.nachricht_alarm(befund, zeitzone=zeitzone),
                )
                ergebnis["aktionen"].append({"zone_id": befund.zone_id, "aktion": AUDIT_ZONE_STUMM})
                ergebnis["gemailt"] += int(gemailt)
                continue

            # Kein Befund. Lief eine Episode, folgt die Entwarnung — und
            # nur dann. Eine Entwarnung ohne vorherigen Alarm waere eine
            # Mail ueber nichts.
            if episode_laeuft:
                gemailt = await _zonen_mail_und_audit(
                    session,
                    action=AUDIT_ZONE_STUMM_ENDE,
                    befund=befund,
                    betreff=relais_zone_melder.betreff_entwarnung(befund),
                    text=relais_zone_melder.nachricht_entwarnung(befund, zeitzone=zeitzone),
                )
                ergebnis["aktionen"].append(
                    {"zone_id": befund.zone_id, "aktion": AUDIT_ZONE_STUMM_ENDE}
                )
                ergebnis["gemailt"] += int(gemailt)

        await session.commit()
        return ergebnis


@app.task(name="heizung.pruefe_relais_zone", bind=True)
def pruefe_relais_zone(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Beat-Task alle 5 Minuten: hat jede Relais-Zone einen aktuellen Wert?"""
    return asyncio.run(_run_relais_zone())
