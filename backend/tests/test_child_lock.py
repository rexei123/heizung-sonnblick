"""Zustand der Kindersicherung (Sprint 24c).

Die Ableitung ist eine reine Funktion und prüfbar ohne Datenbank. Der
Abfrage-Teil braucht Postgres und steht unten.
"""

from __future__ import annotations

import os
import typing
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.sensor_reading import SensorReading
from heizung.schemas.device import DeviceRead
from heizung.services.child_lock import (
    ChildLockState,
    child_lock_state,
    child_lock_verdict,
    child_lock_verdicts,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24cl"


# ---------------------------------------------------------------------------
# Die reine Ableitung
# ---------------------------------------------------------------------------


def test_rolle_gesetzt_und_rad_gesperrt_ist_bestaetigt() -> None:
    assert child_lock_state(measure_only=True, gemeldet=True) == "bestaetigt"


def test_rolle_gesetzt_und_rad_frei_ist_fehlgeschlagen() -> None:
    """Der Downlink ist hinausgegangen, das Gerät meldet das Gegenteil.

    ``fehlgeschlagen`` und nicht ``abweichend``: der Befehl ist nicht
    angekommen oder wurde überschrieben, und das braucht einen Namen,
    der zum Handeln auffordert.
    """
    assert child_lock_state(measure_only=True, gemeldet=False) == "fehlgeschlagen"


def test_ohne_rolle_ist_ein_freies_rad_bestaetigt() -> None:
    """Die Regel gilt in **beide** Richtungen.

    Beim Zurücknehmen der Rolle wird die Sperre gelöst; ein freies Rad
    ist dann der gewollte Zustand. Ohne diese Symmetrie bräuchte der
    Dienst zwei Regeln, und die zweite würde beim ersten Umbau
    vergessen.
    """
    assert child_lock_state(measure_only=False, gemeldet=False) == "bestaetigt"


def test_ohne_rolle_ist_ein_gesperrtes_rad_fehlgeschlagen() -> None:
    assert child_lock_state(measure_only=False, gemeldet=True) == "fehlgeschlagen"


def test_keine_meldung_ist_ausstehend_und_nicht_fehlgeschlagen() -> None:
    """``None`` heißt „nichts gehört", nicht „Rad frei".

    Der Unterschied ist der ganze Grund für ``ausstehend``: ein Gerät,
    von dem wir nichts gehört haben, hat die Sperre nicht verweigert.
    Wäre ``None`` wie ``False`` behandelt, stünde direkt nach dem
    Umschalten ein roter Befund auf der Geräteseite — bei einem
    Funkgerät der Normalfall.
    """
    assert child_lock_state(measure_only=True, gemeldet=None) == "ausstehend"
    assert child_lock_state(measure_only=False, gemeldet=None) == "ausstehend"


def test_das_schema_spiegelt_die_drei_zustaende() -> None:
    """Spiegel-Test: das Inline-``Literal`` im Schema gegen den Dienst.

    Die Schema-Schicht hängt bewusst nicht von der Service-Schicht ab
    (dieselbe Konvention wie bei ``valve_state`` und ``battery_state``) —
    und genau deshalb braucht es diesen Test. Zwei Listen derselben drei
    Werte laufen beim ersten neuen Zustand auseinander, und zwar stumm:
    das Schema würde den neuen Wert mit einem Validierungsfehler
    abweisen, und der sieht nach einem Datenfehler aus.
    """
    aus_dienst = set(typing.get_args(ChildLockState))
    feld = DeviceRead.model_fields["child_lock_state"]
    aus_schema = set(typing.get_args(feld.annotation))

    assert aus_dienst == aus_schema, (
        f"nur im Dienst: {sorted(aus_dienst - aus_schema)} | "
        f"nur im Schema: {sorted(aus_schema - aus_dienst)}"
    )


# ---------------------------------------------------------------------------
# Die Abfrage
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
class TestAbfrage:
    @pytest_asyncio.fixture
    async def db_session(self) -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            yield session
            await session.rollback()
        await engine.dispose()

    async def _geraet(self, session: AsyncSession) -> Device:
        dev = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{PREFIX}-fuehler",
            health_state="healthy",
        )
        session.add(dev)
        await session.flush()
        return dev

    async def test_ohne_zeile_kommt_none(self, db_session: AsyncSession) -> None:
        dev = await self._geraet(db_session)
        assert await child_lock_verdict(db_session, dev.id) is None

    async def test_jede_angefragte_id_kommt_im_ergebnis_vor(self, db_session: AsyncSession) -> None:
        """Ein fehlender Schlüssel wäre für den Aufrufer nicht von „keine
        Meldung" zu unterscheiden, und dann müsste er raten."""
        dev = await self._geraet(db_session)
        ergebnis = await child_lock_verdicts(db_session, [dev.id, 999_999])
        assert set(ergebnis) == {dev.id, 999_999}
        assert ergebnis[999_999] is None

    async def test_eine_zeile_ohne_das_feld_ueberdeckt_die_davor_nicht(
        self, db_session: AsyncSession
    ) -> None:
        """**Der Fall, für den der ``IS NOT NULL``-Filter in der WHERE-Klausel
        steht und nicht im Nachhinein.**

        Die jüngste Zeile führt das Feld nicht (etwa eine reine
        Befehlsantwort), die Zeile davor schon. Würde die Abfrage einfach
        die jüngste nehmen und danach filtern, käme ``None`` heraus — und
        die Geräteseite zeigte nach jedem Antwort-Frame „ausstehend",
        obwohl die Sperre bestätigt ist.
        """
        dev = await self._geraet(db_session)
        jetzt = datetime.now(tz=UTC)
        db_session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=10),
                device_id=dev.id,
                temperature=Decimal("21.0"),
                child_lock=True,
            )
        )
        db_session.add(
            SensorReading(
                time=jetzt - timedelta(minutes=5),
                device_id=dev.id,
                temperature=Decimal("21.0"),
                child_lock=None,
            )
        )
        await db_session.flush()

        assert await child_lock_verdict(db_session, dev.id) is True

    async def test_die_juengste_meldung_mit_feld_gewinnt(self, db_session: AsyncSession) -> None:
        dev = await self._geraet(db_session)
        jetzt = datetime.now(tz=UTC)
        for minuten, gesperrt in ((10, True), (5, False)):
            db_session.add(
                SensorReading(
                    time=jetzt - timedelta(minutes=minuten),
                    device_id=dev.id,
                    temperature=Decimal("21.0"),
                    child_lock=gesperrt,
                )
            )
        await db_session.flush()

        assert await child_lock_verdict(db_session, dev.id) is False

    async def test_leere_anfrage_gibt_leeres_ergebnis(self, db_session: AsyncSession) -> None:
        assert await child_lock_verdicts(db_session, []) == {}
