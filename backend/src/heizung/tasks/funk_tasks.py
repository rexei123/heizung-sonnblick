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

Eigene Engine + Session pro Task-Run (§5.14), Vorbild
``tasks/occupancy_import_tasks``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.models.global_config import GlobalConfig
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.services import alert_throttle, funk_waechter, mail_status, mailer
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
