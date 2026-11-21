"""Beat-Task: meldet eine Schutz-Sperre am Relais (21.11.2026).

``celery_beat`` ruft ``pruefe_schutzsperren`` **alle fuenf Minuten**. Die
Begruendung fuer den Takt ist nicht die Messung, sondern die Folge: eine
Sperre heisst, dass der Bereich nicht mehr heizt, und das soll niemand
erst am naechsten Morgen erfahren. Schneller waere wirkungslos — die
Sperre entsteht aus einem Uplink, und der kommt, wann er kommt.

**Warum hier und nicht im Subscriber**, und was „einmal je Ereignis"
genau heisst: siehe ``services/schutz_melder``. Kurz: die Mail darf den
Uplink-Pfad nicht an einem Mailserver haengen lassen, und das Ereignis
ist der **Zeitpunkt** der Ausloesung, nicht die Dauer der Sperre.

**Der Zustand steht im ``business_audit``** und nicht in Redis — wie bei
allen Meldern dieses Hauses. ``target_type = "device"``,
``target_id = device_id``, und der Zeitpunkt der Ausloesung steht im
``new_value``. Genau dieser Zeitpunkt ist der Vergleich: gleich heisst
„schon gemeldet", verschieden heisst „neues Ereignis".

**Eine Marke, keine zweite fuer das Ende.** Eine Entwarnung gibt es
nicht; die Sperre hebt ein Administrator von Hand auf, und wer sie
aufhebt, weiss es.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.business_audit import BusinessAudit
from heizung.models.global_config import GlobalConfig
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.services import mail_status, mailer, schutz_melder
from heizung.services.business_audit_service import record_business_action

logger = logging.getLogger(__name__)

#: Die Marke im ``business_audit``. Eigener Name neben
#: ``RELAIS_GEHAEUSE_WARM``: das ist ein anderer Vorgang — dort wird es
#: warm, hier hat das Geraet abgeschaltet.
AUDIT_SCHUTZ_GEMELDET = "RELAIS_SCHUTZ_GEMELDET"

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


async def _schon_gemeldet(session: AsyncSession, *, befund: schutz_melder.SchutzBefund) -> bool:
    """Steht im Audit schon ein Eintrag fuer **dieses** Ereignis?

    Verglichen wird der Zeitpunkt der Ausloesung, nicht die Existenz
    eines Eintrags: ein Geraet, das nach dem Entsperren erneut ausloest,
    hat einen neuen Zeitpunkt und bekommt seine zweite Mail.

    Gelesen wird nur der **juengste** Eintrag. Mehr braucht es nicht —
    ein aelterer Zeitpunkt kann nicht der aktuelle sein, weil eine
    stehende Sperre nicht ueberschrieben wird (``relay_uplink``), und
    eine neue Sperre ist spaeter als jede alte.
    """
    stmt = (
        select(BusinessAudit.new_value)
        .where(
            BusinessAudit.action == AUDIT_SCHUTZ_GEMELDET,
            BusinessAudit.target_type == AUDIT_ZIEL,
            BusinessAudit.target_id == befund.device_id,
        )
        .order_by(BusinessAudit.ts.desc())
        .limit(1)
    )
    zeile = (await session.execute(stmt)).first()
    if zeile is None or not isinstance(zeile[0], dict):
        return False
    return zeile[0].get("ausgeloest_am") == befund.ausgeloest_am.isoformat()


async def _mail_und_audit(
    session: AsyncSession,
    *,
    befund: schutz_melder.SchutzBefund,
    zeitzone: str,
) -> bool:
    """Audit **bedingungslos**, Mail nur mit Adresse.

    Der Audit-Eintrag ist der Zustand — er darf nicht davon abhaengen, ob
    eine Adresse eingetragen ist. Sonst wuerde dasselbe Ereignis bei
    jedem Lauf erneut versucht, und bei nachgetragener Adresse kaeme eine
    Mail zu einem Vorfall von vorgestern.
    """
    await record_business_action(
        session,
        user_id=None,
        action=AUDIT_SCHUTZ_GEMELDET,
        target_type=AUDIT_ZIEL,
        target_id=befund.device_id,
        old_value=None,
        new_value={
            "dev_eui": befund.dev_eui,
            "label": befund.label,
            "zone": befund.zone_name,
            "ort": befund.ort,
            "art": befund.art,
            # **Der Schluessel des Ereignisses.** Siehe ``_schon_gemeldet``.
            "ausgeloest_am": befund.ausgeloest_am.isoformat(),
            "gehaeuse_wert": befund.gehaeuse_wert,
        },
    )

    gc = await session.get(GlobalConfig, 1)
    empfaenger = gc.alert_email if gc else None
    if not empfaenger:
        logger.info(
            "schutz_keine_alarmadresse device_id=%s art=%s",
            befund.device_id,
            befund.art,
        )
        return False

    result = mailer.send_mail(
        recipient=empfaenger,
        subject=schutz_melder.betreff_alarm(befund),
        body=schutz_melder.nachricht_alarm(befund, zeitzone=zeitzone),
    )
    # Pflicht fuer neue Alarmwege (``services/mail_status``).
    await mail_status.record_attempt(session, result)
    if not result.sent:
        logger.warning(
            "schutz_mail_nicht_zugestellt device_id=%s grund=%s",
            befund.device_id,
            result.reason,
        )
    return bool(result.sent)


async def _run_schutz() -> dict[str, Any]:
    """Async-Koerper des Tasks. Public fuer Tests."""
    ergebnis: dict[str, Any] = {"sperren": 0, "gemeldet": 0, "gemailt": 0}

    async with _task_session() as session:
        gc = await session.get(GlobalConfig, 1)
        # Dieselbe Lesart wie bei den Funk-Meldern: die Mail liest ein
        # Mensch, also Ortszeit, und der Rueckfall ist die geteilte
        # Konstante — nicht eine eigene Zeichenkette (Paragraph 5.65).
        zeitzone = (gc.timezone if gc and gc.timezone else None) or DEFAULT_HOTEL_TIMEZONE

        befunde = await schutz_melder.lies_schutzsperren(session)
        ergebnis["sperren"] = len(befunde)

        for befund in befunde:
            if await _schon_gemeldet(session, befund=befund):
                continue
            gemailt = await _mail_und_audit(session, befund=befund, zeitzone=zeitzone)
            ergebnis["gemeldet"] += 1
            ergebnis["gemailt"] += int(gemailt)
            logger.error(
                "schutz_sperre_gemeldet device_id=%s art=%s ausgeloest=%s",
                befund.device_id,
                befund.art,
                befund.ausgeloest_am.isoformat(),
            )

        await session.commit()

    logger.info(
        "schutz sperren=%s gemeldet=%s gemailt=%s",
        ergebnis["sperren"],
        ergebnis["gemeldet"],
        ergebnis["gemailt"],
    )
    return ergebnis


@app.task(name="heizung.pruefe_schutzsperren", bind=True)
def pruefe_schutzsperren(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Beat-Task alle fuenf Minuten: hat ein Relais sich selbst abgeschaltet?"""
    return asyncio.run(_run_schutz())
