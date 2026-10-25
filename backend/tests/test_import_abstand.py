"""Abstands-Wächter für die Belegungsliste (Sprint 23 T3).

**Die Lücke, die er schließt.** Der tägliche Wächter fragt „kam heute
**eine** Liste?". Fallen die Listen um 15:30 und 19:30 aus, bleibt die
Ampel grün (RUNBOOK §10ai) — es kam ja eine. Das Zwei-Stunden-Versprechen
des Mehrfachversands wäre gebrochen, ohne dass es jemand sieht.

**Die Schwelle ist gemessen und nicht geschätzt.** Der Sprint-Brief nennt
3 Stunden. Die Listen kommen um 08:30, 15:30 und 19:30; die **regulären**
Abstände sind damit 7 h und 4 h. Eine Schwelle von 3 h hätte jeden Tag um
11:31 angeschlagen — und ein Melder, dem niemand mehr glaubt, überwacht
nichts (§5.79, §5.84). `test_die_vorgabe_liegt_ueber_dem_groessten_
regulaeren_abstand` hält die Rechnung fest, damit die Zahl nicht beim
nächsten Lesen „aufgeräumt" wird.

Die Prüfungen laufen gegen die **Funktion** und nicht gegen den
Celery-Task: der Task ist drei Zeilen, die Entscheidung liegt im Dienst.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.business_audit import BusinessAudit
from heizung.services.occupancy_import_service import (
    ACTION_APPLIED,
    ACTION_GAP,
    TARGET_TYPE,
    run_gap_check,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t23t3"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)

WIEN = ZoneInfo("Europe/Vienna")

#: Ein Tag in der Winterzeit — keine Mehrdeutigkeit in der Ortszeit.
TAG = "2026-11-10"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _audits_raeumen() -> AsyncIterator[None]:
    """Vor **und** nach jedem Test die Audit-Zeilen dieser Datei entfernen.

    ``run_gap_check`` committet (Audit, dann Mail-Versuch), die Sitzung des
    Tests kann das also nicht zurueckrollen. Und die Idempotenz-Pruefung
    sieht Zeilen **ohne** Zeitfilter: eine stehengebliebene Zeile aus einem
    frueheren Lauf macht den naechsten Test still, und zwar mit einer
    Meldung, die wie ein Fehler in der Sache aussieht.

    Genau das ist beim Schreiben dieser Datei passiert: ein roter Lauf hat
    eine GAP-Zeile hinterlassen, und danach war der erste Test
    ``already_flagged``. Zwei Schichten, wie §5.39 verlangt — raeumen
    **vor** dem Test faengt den Rest eines abgebrochenen Laufs, raeumen
    danach den eigenen.
    """
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def raeumen() -> None:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM business_audit WHERE action = ANY(:a)"),
                {"a": [ACTION_GAP, ACTION_APPLIED]},
            )
            await session.commit()

    await raeumen()
    try:
        yield
    finally:
        await raeumen()
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
def _schwellen_zuruecksetzen() -> AsyncIterator[None]:
    """Der Dienst liest die Settings über ``get_settings`` (gecacht).

    Tests, die die Schwelle verstellen, müssen den Cache danach leeren —
    sonst trägt der nächste Test eine Einstellung, die er nicht gesetzt
    hat (§5.39 in der Konfiguration statt in der Datenbank).
    """
    yield
    get_settings.cache_clear()


def ortszeit(uhr: time) -> datetime:
    """Der UTC-Augenblick, an dem in Wien ``uhr`` ist."""
    return datetime.combine(datetime.fromisoformat(TAG).date(), uhr, tzinfo=WIEN).astimezone(UTC)


async def _liste_angewandt(session: AsyncSession, *, received_at: datetime) -> None:
    """Eine angewandte Liste, als Audit-Eintrag.

    **Am Dienst nachgesehen, nicht angenommen** (§5.62):
    ``_last_applied_received_at`` liest die jüngste
    ``OCCUPANCY_IMPORT_APPLIED``-Zeile im ``business_audit`` und holt
    ``new_value.received_at`` daraus — nicht aus ``occupancy``. Die erste
    Fassung dieser Hülle hat eine Belegung angelegt und damit nichts
    geprüft.

    ``ts`` wird ausdrücklich gesetzt: der Dienst sortiert danach, und der
    Vorgabewert wäre „jetzt" statt des Testzeitpunkts.
    """
    session.add(
        BusinessAudit(
            ts=received_at,
            user_id=None,
            action=ACTION_APPLIED,
            target_type=TARGET_TYPE,
            target_id=None,
            old_value=None,
            new_value={"received_at": received_at.isoformat(), "list_date": TAG},
        )
    )
    await session.flush()


async def _gap_audits(session: AsyncSession) -> int:
    return len(
        (await session.execute(select(BusinessAudit.id).where(BusinessAudit.action == ACTION_GAP)))
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Die vier Fälle aus dem Brief
# ---------------------------------------------------------------------------


async def test_innerhalb_des_fensters_mit_zu_grossem_abstand_schlaegt_an(
    db_session: AsyncSession,
) -> None:
    """16:30 Ortszeit, letzte Liste um 08:30 — acht Stunden, Schwelle acht.

    Genau der Fall, für den der Wächter gebaut ist: die Liste um 15:30 ist
    ausgefallen, die um 08:30 kam. Der tägliche Wächter sieht hier nichts.
    """
    jetzt = ortszeit(time(16, 31))
    await _liste_angewandt(db_session, received_at=ortszeit(time(8, 30)))

    ergebnis = await run_gap_check(db_session, now=jetzt)

    assert ergebnis["gap"] is True, ergebnis
    # Acht Stunden und eine Minute, auf eine Stelle gerundet: 8.0.
    assert ergebnis["hours"] >= 8


async def test_innerhalb_des_fensters_mit_kleinem_abstand_bleibt_still(
    db_session: AsyncSession,
) -> None:
    """11:30 Ortszeit, letzte Liste um 08:30 — drei Stunden.

    **Das ist der Tag, an dem alles in Ordnung ist**, und der Grund, warum
    die Schwelle nicht bei 3 h liegt: mit 3 h wäre dieser Test rot, und
    zwar täglich.
    """
    jetzt = ortszeit(time(11, 30))
    await _liste_angewandt(db_session, received_at=ortszeit(time(8, 30)))

    ergebnis = await run_gap_check(db_session, now=jetzt)

    assert ergebnis["gap"] is False, ergebnis
    assert ergebnis["reason"] == "within_threshold"


async def test_ueber_nacht_bleibt_still(db_session: AsyncSession) -> None:
    """03:00 Ortszeit, letzte Liste am Vorabend um 19:30 — 7,5 Stunden.

    Über der Schwelle und trotzdem still: nachts verschickt niemand eine
    Liste. Ohne diese Einschränkung schlüge der Wächter jede Nacht an.
    """
    jetzt = ortszeit(time(3, 0))
    await _liste_angewandt(db_session, received_at=ortszeit(time(19, 30)) - timedelta(days=1))

    ergebnis = await run_gap_check(db_session, now=jetzt)

    assert ergebnis["gap"] is False, ergebnis
    assert ergebnis["reason"] == "outside_window"


async def test_schwelle_leer_schaltet_den_waechter_aus(db_session: AsyncSession) -> None:
    """``None`` heißt aus — und zwar ganz, ohne Abfrage."""
    jetzt = ortszeit(time(16, 31))
    await _liste_angewandt(db_session, received_at=ortszeit(time(8, 30)))

    get_settings.cache_clear()
    altwert = os.environ.get("IMPORT_MAX_GAP_HOURS")
    os.environ["IMPORT_MAX_GAP_HOURS"] = ""
    try:
        ergebnis = await run_gap_check(db_session, now=jetzt)
    finally:
        if altwert is None:
            del os.environ["IMPORT_MAX_GAP_HOURS"]
        else:
            os.environ["IMPORT_MAX_GAP_HOURS"] = altwert
        get_settings.cache_clear()

    assert ergebnis["gap"] is False, ergebnis
    assert ergebnis["reason"] == "disabled"


# ---------------------------------------------------------------------------
# Die Ränder
# ---------------------------------------------------------------------------


async def test_am_fensterrand_wird_noch_geprueft(db_session: AsyncSession) -> None:
    """19:30 ist **innerhalb** des Fensters, 19:31 nicht mehr.

    Ein Rand, der in die falsche Richtung ausgelegt ist, kostet genau die
    Meldung über die letzte Liste des Tages — die, die am häufigsten
    ausfällt.
    """
    await _liste_angewandt(db_session, received_at=ortszeit(time(8, 30)))

    drin = await run_gap_check(db_session, now=ortszeit(time(19, 30)))
    draussen = await run_gap_check(db_session, now=ortszeit(time(19, 31)))

    assert drin["gap"] is True, drin
    assert draussen["reason"] == "outside_window"


async def test_ohne_jede_liste_haelt_sich_der_waechter_heraus(
    db_session: AsyncSession,
) -> None:
    """Noch nie eine Liste angewandt → der tägliche Wächter ist zuständig.

    Zwei Melder für denselben Zustand sind einer zu viel: der Stale-Alarm
    sagt „heute kam keine Liste", und das ist die Aussage, die zählt.
    """
    # Keine angewandte Liste im Blickfeld des Dienstes. ``DELETE`` in der
    # Sitzung, die am Ende zurueckgerollt wird — der Stand des Hauses
    # bleibt unberuehrt.
    await db_session.execute(
        text("DELETE FROM business_audit WHERE action = :a"), {"a": ACTION_APPLIED}
    )
    await db_session.flush()

    ergebnis = await run_gap_check(db_session, now=ortszeit(time(16, 31)))

    assert ergebnis["gap"] is False, ergebnis
    assert ergebnis["reason"] == "never_imported"


async def test_der_zweite_lauf_legt_nicht_nach(db_session: AsyncSession) -> None:
    """Der Beat läuft stündlich.

    Ohne die Idempotenz-Prüfung stünden bei einem längeren Ausfall fünf
    gleichlautende Einträge im Audit — und die Mail-Drosselung allein
    hätte das nicht verhindert, sie bremst nur den Versand.
    """
    jetzt = ortszeit(time(16, 31))
    await _liste_angewandt(db_session, received_at=ortszeit(time(8, 30)))

    vorher = await _gap_audits(db_session)
    erst = await run_gap_check(db_session, now=jetzt)
    zweit = await run_gap_check(db_session, now=jetzt + timedelta(hours=1))
    nachher = await _gap_audits(db_session)

    assert erst["gap"] is True
    assert zweit.get("already_flagged") is True, zweit
    assert nachher - vorher == 1, "genau ein Audit-Eintrag je Tag"

    # Aufräumen: dieser Test committet über ``run_gap_check``.


# ---------------------------------------------------------------------------
# Die Zahl selbst
# ---------------------------------------------------------------------------


def test_die_vorgabe_liegt_ueber_dem_groessten_regulaeren_abstand() -> None:
    """**Die Messung, aus der die Schwelle kommt.**

    Versandzeiten des Hauses: 08:30, 15:30, 19:30 (RUNBOOK §10ai). Die
    regulären Abstände sind damit 7 h und 4 h. Eine Schwelle, die darunter
    liegt, schlägt im Normalbetrieb an — der Sprint-Brief nannte 3.

    Dieser Test ist der Grund, warum die Zahl 8 ist, und er fällt, wenn
    jemand sie senkt **oder** wenn die Versandzeiten sich ändern und
    niemand die Schwelle nachzieht.
    """
    versand = [time(8, 30), time(15, 30), time(19, 30)]
    abstaende = [
        (
            datetime.combine(datetime.fromisoformat(TAG).date(), b)
            - datetime.combine(datetime.fromisoformat(TAG).date(), a)
        )
        / timedelta(hours=1)
        # ``strict=False`` ist hier richtig und nicht Bequemlichkeit:
        # ``zip`` laeuft ueber die Paare, und die zweite Liste ist
        # absichtlich um eins kuerzer.
        for a, b in zip(versand, versand[1:], strict=False)
    ]
    assert abstaende == [7.0, 4.0], f"Versandzeiten geaendert: {abstaende}"

    schwelle = get_settings().import_max_gap_hours
    assert schwelle is not None
    assert schwelle > max(abstaende), (
        f"Schwelle {schwelle} h liegt nicht ueber dem groessten regulaeren "
        f"Abstand ({max(abstaende)} h) — der Waechter schlaegt dann taeglich an"
    )


def test_das_versandfenster_umschliesst_die_drei_listen() -> None:
    """Das Fenster muss die erste und die letzte Liste enthalten.

    Sonst prüft der Wächter genau dann nicht, wenn es darauf ankommt.
    """
    s = get_settings()
    assert s.import_window_start_local <= time(8, 30)
    assert s.import_window_end_local >= time(19, 30)
