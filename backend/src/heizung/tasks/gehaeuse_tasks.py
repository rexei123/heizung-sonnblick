"""Beat-Task: meldet ein warmes Relais-Gehaeuse (18.11.2026).

``celery_beat`` ruft ``pruefe_gehaeusetemperatur`` **alle zehn Minuten** —
im Takt, in dem ein Relais von selbst meldet
(``relay_meldeintervall_s``). Haeufiger zu pruefen wuerde nichts
beschleunigen: zwischen zwei Uplinks gibt es keinen neuen Wert, und das
Urteil braucht drei (``gehaeuse_melder.MIN_MELDUNGEN``).

**Einmal je Ereignis, und zwar wirklich einmal.** Der Alarm kommt am
Anfang der Episode, die Entwarnung an ihrem Ende; dazwischen wiederholt
sich nichts, auch nicht nach Stunden. Das ist die Vorgabe des Betreibers
vom 18.11.2026 und der Unterschied zu den drei aelteren Meldern
(``totalausfall_wiederholung_h``, ``relais_zone_wiederholung_h``,
``platte_wiederholung_h``).

**Was dieser Verzicht kostet, und man soll es wissen:** bei den anderen
Meldern ist die Wiederholung gleichzeitig der **zweite Versuch**, falls
die erste Mail nicht hinausging. Hier gibt es den nicht. Dass ein
Versand gescheitert ist, steht trotzdem fest — ``mail_status`` schreibt
es in die Sichtbarkeits-Felder der ``global_config``, und der
Audit-Eintrag ist ohnehin geschrieben. Wer die Wiederholung doch will,
braucht eine Einstellung und drei Zeilen; die Entscheidung dagegen ist
hier festgehalten, damit sie nicht fuer ein Versehen gehalten wird.

**Der Zustand steht im ``business_audit``** und nicht in Redis — wie
beim Zonen-Melder und bei der Platte. Eine Episode muss den Neustart
ueberleben, und ``alert_throttle`` laesst bei Redis-Ausfall alles durch.
``target_type = "device"`` mit der ``device_id`` als ``target_id``: zwei
Relais koennen unabhaengig voneinander warm werden, und eine gemeinsame
Marke wuerde die Entwarnung des einen auf das andere uebertragen.

**Dieser Melder prueft die Wirkung** (Paragraph 5.76): nicht „ist der
Ueberhitzungsschutz eingestellt", sondern „wie warm ist es gerade". Der
Schutz selbst ist Sache des Geraets, und seine Ausloesung kennt die
Steuerung erst, wenn sie gemeldet wird.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.business_audit import BusinessAudit
from heizung.models.global_config import GlobalConfig
from heizung.services import gehaeuse_melder, mail_status, mailer
from heizung.services.business_audit_service import record_business_action
from heizung.tasks.relay_tasks import zustand_veraltungs_fenster

logger = logging.getLogger(__name__)

#: Die beiden Marken. Sie sind **gleichzeitig der Zustand** — die
#: juengste von beiden sagt, ob fuer dieses Geraet eine Episode laeuft.
AUDIT_GEHAEUSE_WARM = "RELAIS_GEHAEUSE_WARM"
AUDIT_GEHAEUSE_WARM_ENDE = "RELAIS_GEHAEUSE_WARM_ENDE"

#: Dieselbe Zeichenkette, die die Geraete-Handgriffe benutzen.
AUDIT_ZIEL = "device"


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


async def _letzter_stand(
    session: AsyncSession, *, device_id: int
) -> tuple[str | None, datetime | None]:
    """Die juengste der beiden Marken **dieses Geraets** — Aktion und Zeit."""
    stmt = (
        select(BusinessAudit.action, BusinessAudit.ts)
        .where(
            BusinessAudit.action.in_([AUDIT_GEHAEUSE_WARM, AUDIT_GEHAEUSE_WARM_ENDE]),
            BusinessAudit.target_type == AUDIT_ZIEL,
            BusinessAudit.target_id == device_id,
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
    befund: gehaeuse_melder.GehaeuseBefund,
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
        target_id=befund.device_id,
        old_value=None,
        new_value={
            "dev_eui": befund.dev_eui,
            "label": befund.label,
            "zone": befund.zone_name,
            "ort": befund.ort,
            # Dieselbe Reihe, die in der Mail steht. Ohne sie waere
            # nachtraeglich nicht zu sehen, **wie warm** es war, sondern
            # nur, dass es warm war (Paragraph 5.68).
            "werte": list(befund.werte),
            "schwelle": befund.schwelle,
            "letzte_meldung": (
                befund.letzte_meldung.isoformat() if befund.letzte_meldung else None
            ),
            "alter_min": befund.alter_min,
            "relay_on": befund.relay_on,
            "power_w": befund.power_w,
        },
    )

    gc = await session.get(GlobalConfig, 1)
    empfaenger = gc.alert_email if gc else None
    if not empfaenger:
        logger.info(
            "gehaeuse_keine_alarmadresse action=%s device_id=%s wert=%s",
            action,
            befund.device_id,
            befund.wert,
        )
        return False

    result = mailer.send_mail(recipient=empfaenger, subject=betreff, body=text)
    # Pflicht fuer neue Alarmwege (``services/mail_status``).
    await mail_status.record_attempt(session, result)
    if not result.sent:
        logger.warning(
            "gehaeuse_mail_nicht_zugestellt action=%s device_id=%s grund=%s",
            action,
            befund.device_id,
            result.reason,
        )
    return bool(result.sent)


async def _run_gehaeuse() -> dict[str, Any]:
    """Async-Koerper des Tasks. Public fuer Tests."""
    settings = get_settings()
    ergebnis: dict[str, Any] = {
        "relais_geprueft": 0,
        "relais_warm": 0,
        "gemailt": 0,
        "aktionen": [],
    }

    async with _task_session() as session:
        befunde = await gehaeuse_melder.lies_gehaeusetemperaturen(
            session,
            schwelle=settings.relay_gehaeusetemperatur_alarm,
            frische_fenster=zustand_veraltungs_fenster(),
        )
        ergebnis["relais_geprueft"] = len(befunde)
        ergebnis["relais_warm"] = sum(1 for b in befunde if b.heiss)

        for befund in befunde:
            letzte_aktion, _ = await _letzter_stand(session, device_id=befund.device_id)
            episode_laeuft = letzte_aktion == AUDIT_GEHAEUSE_WARM

            if befund.heiss and not episode_laeuft:
                gemailt = await _mail_und_audit(
                    session,
                    action=AUDIT_GEHAEUSE_WARM,
                    befund=befund,
                    betreff=gehaeuse_melder.betreff_alarm(befund),
                    text=gehaeuse_melder.nachricht_alarm(befund),
                )
                ergebnis["aktionen"].append(
                    {"device_id": befund.device_id, "aktion": AUDIT_GEHAEUSE_WARM}
                )
                ergebnis["gemailt"] += int(gemailt)
                continue

            if befund.kuehl and episode_laeuft:
                # Entwarnung nur, wenn eine Episode lief. Eine Entwarnung
                # ohne vorherigen Alarm waere eine Mail ueber nichts.
                gemailt = await _mail_und_audit(
                    session,
                    action=AUDIT_GEHAEUSE_WARM_ENDE,
                    befund=befund,
                    betreff=gehaeuse_melder.betreff_entwarnung(befund),
                    text=gehaeuse_melder.nachricht_entwarnung(befund),
                )
                ergebnis["aktionen"].append(
                    {"device_id": befund.device_id, "aktion": AUDIT_GEHAEUSE_WARM_ENDE}
                )
                ergebnis["gemailt"] += int(gemailt)
                continue

            if befund.heiss:
                logger.info(
                    "gehaeuse_episode_laeuft device_id=%s wert=%s schwelle=%s",
                    befund.device_id,
                    befund.wert,
                    befund.schwelle,
                )

        await session.commit()

    logger.info(
        "gehaeuse relais_geprueft=%s relais_warm=%s gemailt=%s",
        ergebnis["relais_geprueft"],
        ergebnis["relais_warm"],
        ergebnis["gemailt"],
    )
    return ergebnis


@app.task(name="heizung.pruefe_gehaeusetemperatur", bind=True)
def pruefe_gehaeusetemperatur(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Beat-Task alle zehn Minuten: wird ein Relais-Gehaeuse warm?"""
    return asyncio.run(_run_gehaeuse())
