"""Stuendlicher Beat-Task: die Leistungsstufen in unsere Datenbank holen.

``tx_power_index`` je Geraet stand bis zum 16.11.2026 nur in ChirpStacks
Geraetesitzung und — als Nebenprodukt — in den ``LinkADRReq
acknowledged``-Zeilen des Container-Protokolls, aus denen RUNBOOK §10av
Schritt 6a ihn liest. Die Begruendung, warum die Sitzung die bessere
Quelle ist und der Uplink keine, steht in
``services/chirpstack_session``; die Zahlen dazu in Migration 0040.

**Es wird nichts gesteuert.** Kein Downlink, kein Sollwert, kein Zustand
am Geraet. Der Task liest ChirpStacks Postgres lesend und schreibt zwei
Spalten in **unserer** Datenbank. AE-48 und CLAUDE.md §5.28 verbieten
einen zweiten **Befehls**weg zur Hardware, nicht einen lesenden
Datenpfad.

**Stuendlich, und das ist eher zu oft als zu selten.** ADR bewegt die
Stufe nur, wenn sich der Empfang stufenweise aendert; zwischen dem 15.
und 16.11. waren das 183 Aenderungen an 55 Geraeten, also rund acht je
Stunde im Haus. Ein schnellerer Takt liest dieselben 109 Zeilen oefter.
Versetzt auf Minute **:10** — die anderen stuendlichen Laeufe liegen auf
:20 (Import-Waechter), :40 (Pin-Erinnerung) und :50 (Funk-Waechter);
kein Lastproblem, nur lesbarere Logs.

**Ohne ``CHIRPSTACK_SESSION_DB_URL`` tut der Task nichts.** Das ist kein
Notnagel, sondern der Auslieferungszustand: der Zugang ist eine
Server-Aenderung (eine Nur-Lese-Rolle in ChirpStacks Postgres, RUNBOOK
§10bf), und die entscheidet der Betreiber. Bis dahin bleibt §10av
Schritt 6a bei der Protokoll-Pipeline, und die Spalten stehen auf
``NULL`` — sichtbar leer, nicht falsch gefuellt.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.celery_app import app
from heizung.config import get_settings
from heizung.services import chirpstack_session

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _task_session() -> AsyncIterator[AsyncSession]:
    """Eigene Engine + Session je Lauf (§5.14), wie in ``funk_tasks``."""
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
    dsn = settings.chirpstack_session_db_url.strip()
    if not dsn:
        # Eine Zeile je Lauf, auf INFO: der Zustand ist gewollt, aber er
        # soll nicht unsichtbar sein. Wer sich fragt, warum die Spalte
        # leer bleibt, findet die Antwort im Log des Workers.
        logger.info(
            "Leistungsstufen: CHIRPSTACK_SESSION_DB_URL nicht gesetzt, kein Lauf (RUNBOOK 10bf)"
        )
        return {"stand": "nicht_konfiguriert"}

    ergebnis = await chirpstack_session.lies_aus_chirpstack(dsn)
    async with _task_session() as session:
        bericht = await chirpstack_session.uebernehme(session, ergebnis, datetime.now(UTC))
        await session.commit()

    # Unbekannte DevEUIs sind keine Stoerung: ChirpStack kennt auch
    # Geraete, die bei uns zurueckgezogen (``retired_at``) oder nie
    # angelegt sind. Sie werden gezaehlt, damit ein Auseinanderlaufen der
    # beiden Bestaende auffaellt, bevor jemand danach sucht.
    logger.info(
        "Leistungsstufen: %d gelesen, %d zugeordnet, %d unbekannt, %d unlesbar",
        bericht.gelesen,
        bericht.zugeordnet,
        bericht.unbekannt,
        bericht.unlesbar,
    )
    return {
        "stand": "gelesen",
        "gelesen": bericht.gelesen,
        "zugeordnet": bericht.zugeordnet,
        "unbekannt": bericht.unbekannt,
        "unlesbar": bericht.unlesbar,
    }


@app.task(name="heizung.sync_leistungsstufen", bind=True)
def sync_leistungsstufen(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bind=True
    """Beat-Task stuendlich: ``tx_power_index`` je Geraet uebernehmen."""
    return asyncio.run(_run())
