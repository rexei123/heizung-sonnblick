"""Beat-Task: warnt, wenn die Platte voll laeuft (14.11.2026).

``celery_beat`` ruft ``pruefe_plattenplatz`` **stuendlich**. Eine Mail
kommt davon hoechstens einmal am Tag (``platte_wiederholung_h``); der
stuendliche Takt ist nur die Gelegenheit, nachzusehen.

**Warum stuendlich und nicht alle fuenf Minuten.** Die Platte fuellt sich
in Tagen, nicht in Minuten — und die Messung ist ein Syscall, sie kostet
nichts. Haeufiger zu messen wuerde die Mail nicht frueher schicken,
sondern nur das Protokoll fuellen.

**Warum ein eigenes Modul und nicht ``funk_tasks``.** Dort stehen die
Funk-Waechter; eine Platte hat mit Funk nichts zu tun. Die
Episoden-Mechanik ist dieselbe und bewusst **nicht** geteilt: sie ist
zwanzig Zeilen, und der Unterschied steckt im ``target_type``. Ein
gemeinsamer Helfer mit zwei Aufrufern waere ein Ort, an dem eine
Aenderung fuer den einen den anderen trifft (Paragraph 5.1).

**Der Zustand steht in ``business_audit``** und nicht in Redis. Eine
Episode muss den Neustart ueberleben: ``alert_throttle`` laesst bei
Redis-Ausfall alles durch, und dann kaeme die Mail stuendlich. Dieselbe
Entscheidung wie beim Totalausfall und beim Zonen-Melder.

``target_type = "server"`` mit ``target_id = NULL``: es gibt keine Zeile,
auf die der Eintrag zeigen koennte. Die Platte ist der Server.
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
from heizung.services import mail_status, mailer, plattenplatz
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

#: Die beiden Marken der Episode. Dieselbe Form wie beim Zonen-Melder:
#: die juengste von beiden sagt, ob eine Episode laeuft.
AUDIT_PLATTE_VOLL = "PLATTE_FAST_VOLL"
AUDIT_PLATTE_VOLL_ENDE = "PLATTE_FAST_VOLL_ENDE"

#: Kein Gegenstueck in der Datenbank — die Platte ist der Server.
AUDIT_ZIEL = "server"


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


async def _letzter_stand(session: AsyncSession) -> tuple[str | None, datetime | None]:
    """Die juengste der beiden Marken — Aktion und Zeit."""
    stmt = (
        select(BusinessAudit.action, BusinessAudit.ts)
        .where(
            BusinessAudit.action.in_([AUDIT_PLATTE_VOLL, AUDIT_PLATTE_VOLL_ENDE]),
            BusinessAudit.target_type == AUDIT_ZIEL,
        )
        .order_by(BusinessAudit.ts.desc())
        .limit(1)
    )
    zeile = (await session.execute(stmt)).first()
    if zeile is None:
        return None, None
    return zeile[0], zeile[1]


async def _mail_und_audit(
    session: AsyncSession,
    *,
    action: str,
    stand: plattenplatz.PlattenStand,
    betreff: str,
    text: str,
) -> bool:
    """Audit **bedingungslos**, Mail nur mit Adresse.

    Der Audit-Eintrag ist der Zustand der Episode — er darf nicht davon
    abhaengen, ob eine Adresse eingetragen ist. Sonst beginnt die Episode
    jedes Mal von vorn, und bei nachgetragener Adresse kaeme eine
    Entwarnung ohne Alarm.
    """
    await record_business_action(
        session,
        user_id=None,
        action=action,
        target_type=AUDIT_ZIEL,
        target_id=None,
        old_value=None,
        new_value={
            "prozent": stand.prozent,
            "belegt_b": stand.belegt_b,
            "frei_b": stand.frei_b,
            "gesamt_b": stand.gesamt_b,
        },
    )

    gc = await session.get(GlobalConfig, 1)
    empfaenger = gc.alert_email if gc else None
    if not empfaenger:
        logger.info("platte_keine_alarmadresse action=%s prozent=%s", action, stand.prozent)
        return False

    result = mailer.send_mail(recipient=empfaenger, subject=betreff, body=text)
    # Pflicht fuer neue Alarmwege (``services/mail_status``).
    await mail_status.record_attempt(session, result)
    if not result.sent:
        logger.warning("platte_mail_nicht_zugestellt action=%s grund=%s", action, result.reason)
    return bool(result.sent)


async def _run_plattenplatz() -> dict[str, Any]:
    """Async-Koerper des Tasks. Public fuer Tests."""
    settings = get_settings()
    grenze = settings.platte_warn_prozent
    stand = plattenplatz.lies_plattenstand(grenze_prozent=grenze)

    ergebnis: dict[str, Any] = {
        "prozent": stand.prozent,
        "frei_gb": stand.frei_gb,
        "warnt": stand.warnt,
        "aktion": None,
        "gemailt": 0,
    }

    async with _task_session() as session:
        letzte_aktion, letzte_zeit = await _letzter_stand(session)
        episode_laeuft = letzte_aktion == AUDIT_PLATTE_VOLL
        jetzt = datetime.now(tz=UTC)

        if stand.warnt:
            zu_frueh = (
                episode_laeuft
                and letzte_zeit is not None
                and jetzt - letzte_zeit < timedelta(hours=settings.platte_wiederholung_h)
            )
            if zu_frueh:
                logger.info("platte_gebremst prozent=%s", stand.prozent)
            else:
                gemailt = await _mail_und_audit(
                    session,
                    action=AUDIT_PLATTE_VOLL,
                    stand=stand,
                    betreff=plattenplatz.betreff_alarm(stand),
                    text=plattenplatz.nachricht_alarm(stand, grenze_prozent=grenze),
                )
                ergebnis["aktion"] = AUDIT_PLATTE_VOLL
                ergebnis["gemailt"] = int(gemailt)
        elif episode_laeuft:
            # Entwarnung nur, wenn eine Episode lief. Eine Entwarnung ohne
            # vorherigen Alarm waere eine Mail ueber nichts.
            gemailt = await _mail_und_audit(
                session,
                action=AUDIT_PLATTE_VOLL_ENDE,
                stand=stand,
                betreff=plattenplatz.betreff_entwarnung(stand),
                text=plattenplatz.nachricht_entwarnung(stand, grenze_prozent=grenze),
            )
            ergebnis["aktion"] = AUDIT_PLATTE_VOLL_ENDE
            ergebnis["gemailt"] = int(gemailt)

        await session.commit()

    logger.info(
        "platte prozent=%s frei_gb=%s warnt=%s aktion=%s",
        stand.prozent,
        stand.frei_gb,
        stand.warnt,
        ergebnis["aktion"],
    )
    return ergebnis


@app.task(name="heizung.pruefe_plattenplatz", bind=True)
def pruefe_plattenplatz(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Stuendlicher Beat-Task: warnt, wenn die Platte voll laeuft."""
    return asyncio.run(_run_plattenplatz())
