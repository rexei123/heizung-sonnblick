"""Zustand der Kindersicherung (Sprint 24c, Sprint 23 T4-B).

**Die Bestandstests gehen seit T4-B durch ``soll_kindersicherung``**, auch
wo die Gast-Sperre nicht die Rolle spielt. Sie koennten ``gewollt``
direkt setzen — dann wuerden sie den neuen Parameternamen pruefen und
nicht die Kette, die im Betrieb laeuft (Paragraph 5.79, zweiter Teil: ein
Erwartungswert ohne Herkunft prueft nur, dass sich nichts geaendert hat).

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
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.schemas.device import DeviceRead
from heizung.services.child_lock import (
    ChildLockState,
    child_lock_state,
    child_lock_verdict,
    child_lock_verdicts,
    gast_sperren_je_geraet,
    soll_kindersicherung,
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24cl"


# ---------------------------------------------------------------------------
# Die reine Ableitung
# ---------------------------------------------------------------------------


def test_rolle_gesetzt_und_rad_gesperrt_ist_bestaetigt() -> None:
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False), gemeldet=True
        )
        == "bestaetigt"
    )


def test_rolle_gesetzt_und_rad_frei_ist_fehlgeschlagen() -> None:
    """Der Downlink ist hinausgegangen, das Gerät meldet das Gegenteil.

    ``fehlgeschlagen`` und nicht ``abweichend``: der Befehl ist nicht
    angekommen oder wurde überschrieben, und das braucht einen Namen,
    der zum Handeln auffordert.
    """
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False), gemeldet=False
        )
        == "fehlgeschlagen"
    )


def test_ohne_rolle_ist_ein_freies_rad_bestaetigt() -> None:
    """Die Regel gilt in **beide** Richtungen.

    Beim Zurücknehmen der Rolle wird die Sperre gelöst; ein freies Rad
    ist dann der gewollte Zustand. Ohne diese Symmetrie bräuchte der
    Dienst zwei Regeln, und die zweite würde beim ersten Umbau
    vergessen.
    """
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=False, gast_sperre=False), gemeldet=False
        )
        == "bestaetigt"
    )


def test_ohne_rolle_ist_ein_gesperrtes_rad_fehlgeschlagen() -> None:
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=False, gast_sperre=False), gemeldet=True
        )
        == "fehlgeschlagen"
    )


def test_keine_meldung_ist_ausstehend_und_nicht_fehlgeschlagen() -> None:
    """``None`` heißt „nichts gehört", nicht „Rad frei".

    Der Unterschied ist der ganze Grund für ``ausstehend``: ein Gerät,
    von dem wir nichts gehört haben, hat die Sperre nicht verweigert.
    Wäre ``None`` wie ``False`` behandelt, stünde direkt nach dem
    Umschalten ein roter Befund auf der Geräteseite — bei einem
    Funkgerät der Normalfall.
    """
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False), gemeldet=None
        )
        == "ausstehend"
    )
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=False, gast_sperre=False), gemeldet=None
        )
        == "ausstehend"
    )


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

        meldung = await child_lock_verdict(db_session, dev.id)
        assert meldung is not None
        assert meldung.gesperrt is True
        # Sprint 24d: die Zeit kommt mit. Ohne sie ist eine Meldung von
        # **vor** dem Befehl nicht von einer Ablehnung zu unterscheiden.
        assert meldung.gemeldet_um == jetzt - timedelta(minutes=10)

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

        meldung = await child_lock_verdict(db_session, dev.id)
        assert meldung is not None
        assert meldung.gesperrt is False
        assert meldung.gemeldet_um == jetzt - timedelta(minutes=5)

    async def test_leere_anfrage_gibt_leeres_ergebnis(self, db_session: AsyncSession) -> None:
        assert await child_lock_verdicts(db_session, []) == {}

    # -----------------------------------------------------------------
    # Sprint 23 T4-B: die Gast-Sperre je Geraet, gehoben
    # -----------------------------------------------------------------

    async def _geraet_im_zimmer(
        self, session: AsyncSession, *, gesperrt: bool, bis_checkout: bool = False
    ) -> Device:
        """Ein Geraet mit Zone und Zimmer. Gibt das Geraet.

        Schema-Grenzen (Paragraph 5.49): ``room.number`` max 20 Zeichen,
        ``device.dev_eui`` genau 16. Der Suffix ist deshalb acht Hex und
        nicht eine Uhrzeit.
        """
        kurz = uuid.uuid4().hex[:8]
        rt = RoomType(name=f"{PREFIX}-rt-{kurz}")
        session.add(rt)
        await session.flush()
        room = Room(
            number=f"{PREFIX}-{kurz}",
            room_type_id=rt.id,
            guest_override_blocked=gesperrt,
            guest_block_bis_checkout=bis_checkout,
        )
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="zone")
        session.add(zone)
        await session.flush()
        dev = Device(
            dev_eui=f"beef{uuid.uuid4().hex[:12]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{PREFIX}-im-zimmer",
            health_state="healthy",
            heating_zone_id=zone.id,
        )
        session.add(dev)
        await session.flush()
        return dev

    async def test_gast_sperre_wird_ueber_zone_und_zimmer_gefunden(
        self, db_session: AsyncSession
    ) -> None:
        """Der Weg ist Geraet -> Zone -> Zimmer, und er muss stimmen.

        Ein falscher Join liefert hier kein Fehlerbild, sondern ein
        stilles ``False`` — und damit ein Rad, das freigegeben wird,
        obwohl die Sperre steht.
        """
        gesperrt = await self._geraet_im_zimmer(db_session, gesperrt=True)
        frei = await self._geraet_im_zimmer(db_session, gesperrt=False)

        ergebnis = await gast_sperren_je_geraet(db_session, [gesperrt.id, frei.id])
        assert ergebnis[gesperrt.id] is True
        assert ergebnis[frei.id] is False

    async def test_beide_formen_der_sperre_zaehlen(self, db_session: AsyncSession) -> None:
        """Dauerhaft und bis Check-out sind beide eine Sperre.

        Die Formen unterscheiden sich darin, **wann** sie enden, nicht
        darin, ob das Rad still sein soll. Wer hier
        ``guest_block_bis_checkout`` mitliest, baut einen Unterschied,
        den es nicht gibt.
        """
        bis_checkout = await self._geraet_im_zimmer(db_session, gesperrt=True, bis_checkout=True)
        dauerhaft = await self._geraet_im_zimmer(db_session, gesperrt=True)

        ergebnis = await gast_sperren_je_geraet(db_session, [bis_checkout.id, dauerhaft.id])
        assert ergebnis[bis_checkout.id] is True
        assert ergebnis[dauerhaft.id] is True

    async def test_ein_geraet_ohne_zimmer_steht_mit_false_drin(
        self, db_session: AsyncSession
    ) -> None:
        """Ein Pool-Geraet hat keine Zone — und damit keinen Gast.

        Es **fehlt nicht** im Ergebnis: ein fehlender Schluessel waere
        fuer den Aufrufer nicht von "nicht gesperrt" zu unterscheiden,
        und das Pflicht-Argument in ``_build_device_read`` waere dann ein
        ``KeyError`` statt einer Antwort.
        """
        ohne = await self._geraet(db_session)
        ergebnis = await gast_sperren_je_geraet(db_session, [ohne.id, 999_999])
        assert set(ergebnis) == {ohne.id, 999_999}
        assert ergebnis[ohne.id] is False
        assert ergebnis[999_999] is False

    async def test_leere_anfrage_ergibt_leeres_ergebnis_ohne_abfrage(
        self, db_session: AsyncSession
    ) -> None:
        """Eine leere Geraeteliste ist kein Sonderfall, sondern der Pool
        eines Hauses ohne Reserve. ``IN ()`` waere ein SQL-Fehler."""
        assert await gast_sperren_je_geraet(db_session, []) == {}


# ---------------------------------------------------------------------------
# Sprint 23 T4-B — der gewollte Zustand hat zwei Gruende
#
# Die Tests oben prueffen ``child_lock_state`` mit einem fertigen
# ``gewollt``. Hier geht es um die Stelle davor: wie aus zwei Gruenden
# **einer** gewollter Zustand wird, und dass keiner der beiden verloren
# geht.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("measure_only", "gast_sperre", "erwartet"),
    [
        (True, True, True),
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ],
)
def test_soll_kindersicherung_ist_oder_nicht_und(
    measure_only: bool, gast_sperre: bool, erwartet: bool
) -> None:
    """Jeder Grund allein genuegt, und keiner hebt den anderen auf.

    Die vollstaendige Tabelle und nicht nur die interessanten Zeilen: die
    Funktion hat vier Faelle, und welcher spaeter falsch wird, weiss man
    vorher nicht. Die dritte Zeile ist die neue, die zweite die, die beim
    Zuruecknehmen der Rolle nicht verloren gehen darf.
    """
    assert soll_kindersicherung(measure_only=measure_only, gast_sperre=gast_sperre) is erwartet


def test_gast_sperre_allein_macht_ein_gesperrtes_rad_bestaetigt() -> None:
    """Das erste der beiden Fehlerbilder aus AE-80 §6, als Test.

    Ohne die gemeinsame Funktion haette ``child_lock_state`` fuer ein
    gast-gesperrtes Normalgeraet "fehlgeschlagen" gemeldet: gewollt waere
    ``measure_only=False``, gemeldet "gesperrt". Ein Melder, der im
    Normalfall rot zeigt, wird nach einer Woche nicht mehr gelesen
    (Paragraph 5.79).
    """
    gewollt = soll_kindersicherung(measure_only=False, gast_sperre=True)
    assert child_lock_state(gewollt=gewollt, gemeldet=True) == "bestaetigt"


def test_ohne_beide_gruende_ist_ein_gesperrtes_rad_weiter_fehlgeschlagen() -> None:
    """Die Gegenprobe: ohne Grund bleibt ein gesperrtes Rad ein Fehlschlag.

    Sonst waere die Aenderung oben nicht eine Erweiterung des gewollten
    Zustands, sondern das Abschalten des Melders.
    """
    gewollt = soll_kindersicherung(measure_only=False, gast_sperre=False)
    assert child_lock_state(gewollt=gewollt, gemeldet=True) == "fehlgeschlagen"
