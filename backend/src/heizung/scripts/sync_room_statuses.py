r"""CLI-Entrypoint fuer den einmaligen room.status-Sync (Sprint 15g T1).

Aufruf via ``python -m heizung.scripts.sync_room_statuses``.

Ruft ``occupancy_service.sync_active_rooms`` genau einmal: leitet
``room.status`` aller Raeume mit anstehendem Belegungs-Uebergang aus den
aktiven Belegungen ab (uhrzeitgenau, check_in/check_out sind UTC-Timestamps
mit den Import-Defaults 14:00/11:00 lokal). CLEANING/BLOCKED bleiben
unangetastet (Schutzklausel in ``sync_room_status``).

Dient als SOFORT-WORKAROUND fuer aktuell falsch stehende Zimmer
(z.B. Anreisen, die als RESERVED haengen, weil kein periodischer Sweep
lief). Im Normalbetrieb haelt der celery_beat-Task
``heizung.sync_room_statuses`` (alle 60 s) denselben Stand.

Auf heizung-test/heizung-main via Docker (Container-Name nicht hart
annehmen, Prod-Pattern ``deploy-api-1``):

    docker compose -f infra/deploy/docker-compose.prod.yml exec api \
      python -m heizung.scripts.sync_room_statuses
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

# App-Settings ladbar machen (Pattern aus seed_rooms.py / pair_devices.py).
# Nur im direkten CLI-Aufruf, NICHT beim Import (Sprint 19 / PR B, T16).
#
# ``python -m heizung.scripts.<name>`` setzt ``__name__`` auf ``"__main__"``;
# ein ``import`` durch die Tests tut das nicht. Der Guard trennt damit genau
# die beiden Faelle.
#
# Anlass: die Zeile ``os.environ.setdefault("DATABASE_URL", ...)`` lief bei
# JEDEM Import mit. Sobald irgendein gesammeltes Testmodul dieses Skript
# importierte, hielt ``conftest._ensure_test_admin`` eine Datenbank fuer
# konfiguriert und versuchte zu migrieren — auch bei reinen
# Funktionstests. Lokal ohne Postgres wurden daraus 817 Verbindungsfehler
# statt 45 ehrlicher Skips, und die Skip-Logik der Tests war damit
# ausgehebelt, ohne dass es jemand sah.
#
# Die DATABASE_URL-Zeile ist **ganz** entfallen, nicht nur verschoben: sie
# setzte genau den Wert, den ``Settings.database_url`` ohnehin als Default
# traegt (``config.py``). Sie hatte also keine Wirkung ausser der
# Nebenwirkung.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

from datetime import UTC, datetime  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.services.occupancy_service import sync_active_rooms  # noqa: E402

logger = logging.getLogger("sync_room_statuses")


async def main_async() -> int:
    now = datetime.now(tz=UTC)
    async with SessionLocal() as session:
        count = await sync_active_rooms(session, now)
        # Direkter Service-Aufruf ausserhalb des FastAPI-Stacks ->
        # expliziter Commit Pflicht (§5.61), sonst Rollback ohne Fehler.
        await session.commit()
    print(f"[OK] room.status-Sync: {count} aktive Raeume synchronisiert (now={now.isoformat()}).")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
