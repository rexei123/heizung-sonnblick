"""Sprint 23 T4-B — aus der Gast-Sperre wird ein Funkbefehl.

**Der Befund, der diesen Task verlangt hat.** Im Rad-Test von Zimmer 107
am 30.10.2026 stand die Sperre, der Gast drehte, die Drehung wurde
abgewiesen — und im ``0x28``-Frame von 11:49 stand ``childLock: false``.
Das Rad war **nicht** gesperrt. Die Sperre war bis dahin eine Entscheidung
im System: sie verhindert die Eingabe, aber am Heizkörper ließ sich weiter
drehen.

T4-A2b hat die Folge behoben (das Gerät kommt binnen einer Minute auf den
Sollwert zurück). T4-B behebt die Ursache: ``0x07 01`` legt das Rad still,
``0x07 00`` gibt es frei.

**Vier Wege setzen oder lösen die Sperre, und alle gehen durch eine
Funktion** (``child_lock.sende_bei_aenderung``):

| Weg | Prüfung hier |
|---|---|
| Sperr-Knopf in der Kopfzeile | Abschnitt 1 |
| Häkchen im Übersteuerungs-Dialog | Abschnitt 3 |
| Check-out löst die Sperre | Abschnitt 4 |
| Rolle „nur messen" | ``test_api_relays.py`` (Sprint 24c, unverändert) |

**Die beiden wichtigsten Prüfungen sind die, bei denen *nichts* passiert.**
Ein Fühler muss gesperrt bleiben, wenn die Gast-Sperre endet (sonst gibt
das Lösen das Rad eines unmontierten Geräts frei), und ein Wechsel der
Sperr-Form darf nichts senden (ein Befehl, der nichts ändert, kostet
Batterie und eine Motorbewegung, §0 S4).

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).
``set_child_lock`` ist durchweg eine Attrappe — ein Test, der funkt, wäre
ein Test, der je nach Broker ein anderes Ergebnis hat (§5.55).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from freezegun import freeze_time
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.enums import (
    DeviceKind,
    DeviceVendor,
    HeatingZoneKind,
    RoomStatus,
)
from heizung.models.heating_zone import HeatingZone
from heizung.models.occupancy import Occupancy
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import child_lock, gast_sperre
from tests.conftest import purge_test_data_by_prefix

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

# schema_constraint: room.number = VARCHAR(20) -> "t4b-" + 4 hex = 8
PREFIX = "t4b"
DEV_EUI_PATTERN = "7c107c%"

FROZEN_NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    engine = create_async_engine(TEST_DB_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
        try:
            yield session
        finally:
            await session.rollback()
            await purge_test_data_by_prefix(session, PREFIX, dev_eui_pattern=DEV_EUI_PATTERN)
    await engine.dispose()


class Funk:
    """Mitschrift der ``0x07``-Befehle: ``(dev_eui, gesperrt)``."""

    def __init__(self) -> None:
        self.befehle: list[tuple[str, bool]] = []
        self.wirft: Exception | None = None

    def werte(self) -> list[bool]:
        return [gesperrt for _, gesperrt in self.befehle]


@pytest.fixture
def funk(monkeypatch: pytest.MonkeyPatch) -> Funk:
    """Fängt ``set_child_lock`` ab, auf dem Modul, das der Dienst benutzt.

    Gepatcht wird ``child_lock.downlink_adapter`` — dasselbe Muster wie in
    ``test_api_relays.py``. Es trifft das Modul-Attribut und damit jeden
    Aufrufer; eine Attrappe, alle Wege.
    """
    f = Funk()

    async def _senden(dev_eui: str, enabled: bool, *_a: Any, **_k: Any) -> str:
        if f.wirft is not None:
            raise f.wirft
        f.befehle.append((dev_eui, enabled))
        return f"application/x/device/{dev_eui}/command/down"

    monkeypatch.setattr(child_lock.downlink_adapter, "set_child_lock", _senden)
    return f


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


async def _zimmer(
    session: AsyncSession,
    *,
    gesperrt: bool = False,
    bis_checkout: bool = False,
    belegt: bool = True,
) -> tuple[int, int]:
    """Zimmer mit einer Zone. ``(room_id, zone_id)``."""
    marker = uuid.uuid4().hex[:4]
    typ = RoomType(
        name=f"{PREFIX}-dz-{marker}",
        default_t_occupied=Decimal("21.0"),
        default_t_vacant=Decimal("18.0"),
        default_t_night=Decimal("19.0"),
    )
    session.add(typ)
    await session.flush()
    room = Room(
        number=f"{PREFIX}-{marker}",
        room_type_id=typ.id,
        status=RoomStatus.OCCUPIED if belegt else RoomStatus.VACANT,
        guest_override_blocked=gesperrt,
        guest_block_bis_checkout=bis_checkout,
    )
    session.add(room)
    await session.flush()
    if belegt:
        session.add(
            Occupancy(
                room_id=room.id,
                check_in=FROZEN_NOW - timedelta(hours=20),
                check_out=FROZEN_NOW + timedelta(days=2),
                is_active=True,
            )
        )
    zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.BEDROOM, name="Schlafzimmer")
    session.add(zone)
    await session.flush()
    await session.commit()
    return room.id, zone.id


async def _geraet(
    session: AsyncSession,
    zone_id: int | None,
    *,
    measure_only: bool = False,
    kind: DeviceKind = DeviceKind.THERMOSTAT,
    retired: bool = False,
) -> Device:
    marker = uuid.uuid4().hex[:10]
    dev = Device(
        dev_eui=f"7c107c{marker}",
        kind=kind,
        vendor=DeviceVendor.MCLIMATE,
        model="Vicki",
        heating_zone_id=zone_id,
        health_state="healthy",
        measure_only=measure_only,
        retired_at=FROZEN_NOW - timedelta(days=1) if retired else None,
    )
    session.add(dev)
    await session.flush()
    await session.commit()
    return dev


async def _audit(session: AsyncSession, room_id: int) -> dict[str, Any]:
    """Der jüngste Audit-Eintrag zu diesem Zimmer."""
    eintrag = await session.scalar(
        select(BusinessAudit)
        .where(BusinessAudit.target_type == "room")
        .where(BusinessAudit.target_id == room_id)
        .order_by(BusinessAudit.id.desc())
        .limit(1)
    )
    assert eintrag is not None, "ohne Audit-Eintrag prueft der Test nichts"
    return dict(eintrag.new_value or {})


# ---------------------------------------------------------------------------
# 1. Der Sperr-Knopf
# ---------------------------------------------------------------------------


async def test_sperren_legt_das_rad_still(db_session: AsyncSession, funk: Funk) -> None:
    """**Der Pflicht-Stop-Fall.** Sperre setzen -> ``0x07 01`` an jedes Thermostat.

    Das ist genau der Handgriff aus der Schrittliste für Zimmer 107: die
    dauerhafte Sperre setzen und am Gerät nachsehen.
    """
    room_id, zone_id = await _zimmer(db_session)
    a = await _geraet(db_session, zone_id)
    b = await _geraet(db_session, zone_id)

    befehle = await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )
    await db_session.commit()

    assert funk.werte() == [True, True], "beide Thermostate der Zone"
    assert {eui for eui, _ in funk.befehle} == {a.dev_eui, b.dev_eui}
    assert [b.gesendet for b in befehle] == [True, True]
    # Der Zeitpunkt des Befehls — ohne ihn zeigt die Geraeteseite direkt
    # nach dem Umschalten einen roten Befund (Befund 24.10.2026).
    for geraet in (a, b):
        await db_session.refresh(geraet)
        assert geraet.child_lock_commanded_at is not None


async def test_aufheben_gibt_das_rad_frei(db_session: AsyncSession, funk: Funk) -> None:
    """Sperre aufheben -> ``0x07 00``. Der zweite Teil der Schrittliste."""
    room_id, zone_id = await _zimmer(db_session, gesperrt=True)
    await _geraet(db_session, zone_id)

    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=True, sperre_nachher=False
    )

    assert funk.werte() == [False]


async def test_wechsel_der_form_sendet_nichts(db_session: AsyncSession, funk: Funk) -> None:
    """**Dauerhaft -> bis Check-out: kein Downlink.**

    Das Rad ist in beiden Formen still; sie unterscheiden sich nur darin,
    **wann** die Sperre endet. Ein Befehl, der nichts ändert, kostet
    Batterie und eine Motorbewegung (§0 S4).
    """
    room_id, zone_id = await _zimmer(db_session, gesperrt=True)
    await _geraet(db_session, zone_id)

    befehle = await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=True, sperre_nachher=True
    )

    assert funk.befehle == []
    assert befehle == []


# ---------------------------------------------------------------------------
# 2. Wo nichts hinausgehen darf
# ---------------------------------------------------------------------------


async def test_fuehler_bleibt_gesperrt_wenn_die_sperre_endet(
    db_session: AsyncSession, funk: Funk
) -> None:
    """**Die wichtigste Prüfung dieser Datei.**

    Ein Gerät mit der Rolle „nur messen" liegt unmontiert im Raum und hat
    ein drehbares Rad. Seine Sperre kommt aus der **Rolle** (S7) und nicht
    aus der Gast-Sperre — endet die Gast-Sperre, muss das Rad still
    bleiben.

    Fällt dieser Test, gibt jeder Check-out in einem Zimmer mit einem
    Fühler dessen Rad frei, und niemand sieht es: der gewollte Zustand in
    der Anzeige kommt aus derselben Funktion und stimmte weiter.

    Dieselbe Klasse wie der Befund, der ``soll_kindersicherung`` nötig
    gemacht hat (§5.53) — nur diesmal in der Gegenrichtung.
    """
    room_id, zone_id = await _zimmer(db_session, gesperrt=True)
    await _geraet(db_session, zone_id, measure_only=True)

    befehle = await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=True, sperre_nachher=False
    )

    assert funk.befehle == [], "ein Fuehler bleibt gesperrt"
    assert befehle == []


async def test_fuehler_bekommt_auch_beim_sperren_nichts(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Die Gegenrichtung: sein Rad ist schon still, es gibt nichts zu tun."""
    room_id, zone_id = await _zimmer(db_session)
    await _geraet(db_session, zone_id, measure_only=True)

    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )

    assert funk.befehle == []


async def test_neben_dem_fuehler_bekommt_das_thermostat_seinen_befehl(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Ein Zimmer mit beidem: das Thermostat ja, der Fühler nein.

    Ohne diese Prüfung wären die zwei Tests oben auch grün, wenn die
    Auswahl das ganze Zimmer überspränge, sobald ein Fühler darin hängt.
    """
    room_id, zone_id = await _zimmer(db_session)
    thermostat = await _geraet(db_session, zone_id)
    await _geraet(db_session, zone_id, measure_only=True)

    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )

    assert funk.befehle == [(thermostat.dev_eui, True)]


async def test_relais_und_ausgemustertes_bekommen_nichts(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Ein Relais hat kein Drehrad, ein ausgemustertes Gerät ist nicht da."""
    room_id, zone_id = await _zimmer(db_session)
    await _geraet(db_session, zone_id, kind=DeviceKind.RELAY)
    await _geraet(db_session, zone_id, retired=True)

    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )

    assert funk.befehle == []


async def test_ein_fehlschlag_haelt_die_sperre_nicht_auf(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Funk weg -> die Sperre gilt trotzdem, und der Grund steht im Audit.

    Die Sperre ist zuerst eine Entscheidung im System: sie wirkt über das
    Block-Gate in ``override_service``, auch wenn kein Funkbefehl ankommt.
    Das Rad stillzulegen ist die Zugabe — sie darf die Entscheidung nicht
    blockieren.

    Sichtbar bleibt der Fehlschlag auf zwei Wegen: im Audit und auf der
    Geräteseite, die gewollt gegen gemeldet vergleicht.
    """
    room_id, zone_id = await _zimmer(db_session)
    await _geraet(db_session, zone_id)
    funk.wirft = OSError("kein Broker")

    befehle = await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )

    assert len(befehle) == 1
    assert befehle[0].gesendet is False
    assert "kein Broker" in (befehle[0].fehler or "")
    eintraege = child_lock.fuer_audit(befehle)
    assert eintraege[0]["gesendet"] is False
    assert "fehler" in eintraege[0]


async def test_ohne_geraete_ist_die_liste_leer(db_session: AsyncSession, funk: Funk) -> None:
    """Ein Zimmer ohne Thermostat: nichts zu tun, und das ist kein Fehler.

    Die leere Liste im Audit heißt „nichts zu tun". Dass sie von „Befehl
    gescheitert" unterscheidbar bleibt, ist der Grund, warum der Fehler
    mit in die Einträge geht.
    """
    room_id, _ = await _zimmer(db_session)

    assert (
        await child_lock.sende_bei_aenderung(
            db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
        )
        == []
    )
    assert child_lock.fuer_audit([]) == []


# ---------------------------------------------------------------------------
# 3. Das Häkchen im Übersteuerungs-Dialog
# ---------------------------------------------------------------------------


async def test_haekchen_sendet_und_protokolliert(db_session: AsyncSession, funk: Funk) -> None:
    """``setze_bis_checkout`` schickt denselben Befehl wie der Knopf."""
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id)

    geschrieben = await gast_sperre.setze_bis_checkout(db_session, room_id=room_id, user_id=None)
    await db_session.commit()

    assert geschrieben is True
    assert funk.befehle == [(dev.dev_eui, True)]
    neu = await _audit(db_session, room_id)
    assert neu["kindersicherung"] == [{"dev_eui": dev.dev_eui, "gewollt": True, "gesendet": True}]


async def test_haekchen_bei_schon_gesperrtem_zimmer_sendet_nichts(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Dauerhaft gesperrt, dann das Häkchen: das Rad ist schon still.

    Der Weg schreibt die Form um (``bis_checkout``) und schickt nichts —
    derselbe Grund wie beim Knopf. Geprüft wird er hier zusätzlich, weil
    der Aufrufer die Lage **vorher** selbst mitgeben muss und ein
    hartkodiertes ``False`` an dieser Stelle einen Downlink zu viel
    erzeugte.
    """
    room_id, zone_id = await _zimmer(db_session, gesperrt=True)
    await _geraet(db_session, zone_id)

    await gast_sperre.setze_bis_checkout(db_session, room_id=room_id, user_id=None)
    await db_session.commit()

    assert funk.befehle == []


# ---------------------------------------------------------------------------
# 4. Der Check-out
# ---------------------------------------------------------------------------


async def test_check_out_gibt_das_rad_frei(db_session: AsyncSession, funk: Funk) -> None:
    """``loese_bei_checkout`` schickt ``0x07 00``.

    Der Check-out ist kein Knopf — und ein Zimmer, dessen Rad nach der
    Abreise gesperrt bliebe, hätte genau das Problem zurück, das die
    Sperre „bis Check-out" löst: der nächste Gast dreht, nichts passiert,
    und an der Rezeption gibt es keine Erklärung dafür.
    """
    room_id, zone_id = await _zimmer(db_session, gesperrt=True, bis_checkout=True)
    dev = await _geraet(db_session, zone_id)

    geloest = await gast_sperre.loese_bei_checkout(
        db_session, room_id, RoomStatus.OCCUPIED, RoomStatus.VACANT
    )
    await db_session.commit()

    assert geloest is True
    assert funk.befehle == [(dev.dev_eui, False)]
    neu = await _audit(db_session, room_id)
    assert neu["kindersicherung"] == [{"dev_eui": dev.dev_eui, "gewollt": False, "gesendet": True}]


async def test_dauerhafte_sperre_ueberlebt_den_check_out_auch_am_rad(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Eine **dauerhafte** Sperre bleibt — und mit ihr das stille Rad.

    ``loese_bei_checkout`` greift nur bei der Form „bis Check-out". Ohne
    diese Prüfung wäre die Änderung oben auch grün, wenn jeder Check-out
    jede Sperre löste — und dann gäbe die Abreise das Rad eines Zimmers
    frei, über das jemand dauerhaft entschieden hat.
    """
    room_id, zone_id = await _zimmer(db_session, gesperrt=True, bis_checkout=False)
    await _geraet(db_session, zone_id)

    geloest = await gast_sperre.loese_bei_checkout(
        db_session, room_id, RoomStatus.OCCUPIED, RoomStatus.VACANT
    )

    assert geloest is False
    assert funk.befehle == []


# ---------------------------------------------------------------------------
# 5. Die Anzeige, die der Pflicht-Stop liest
# ---------------------------------------------------------------------------


@freeze_time(FROZEN_NOW)
async def test_nach_dem_befehl_steht_ausstehend_und_dann_bestaetigt(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Die Kette, die der Pflicht-Stop am Bildschirm abliest.

    **Der einzige Test hier mit ``freeze_time``**, und er braucht es: der
    Dienst setzt ``child_lock_commanded_at`` auf die **echte** Uhr, und
    verglichen wird gegen die Meldung davor. Ohne Einfrieren entscheidet
    die Tageszeit des Laufs, ob die Meldung vor oder nach dem Befehl liegt
    — ein Test, der morgens anders urteilt als nachmittags (§5.59).

    **Die Zeitfolge ist die aus Zimmer 107** (Betreiber, 01.11.2026) —
    drei Meldungen um einen Befehl:

    ====== ===============================================================
    10:05  Keepalive meldet „frei" (vor dem Befehl)
    10:16  ``0x07 01`` geht hinaus
    10:23  Keepalive meldet **„frei"** — und holt den Befehl erst
           **danach** im Empfangsfenster ab (Class A)
    10:34  Keepalive meldet „gesperrt"
    ====== ===============================================================

    **Die Anzeige muss bei 10:05 und bei 10:23 „ausstehend" sagen.** Um
    10:23 sagte sie „das Gerät meldet es als frei" — ein roter Befund, elf
    Minuten vor der Bestätigung. Ein Melder, der im Normalfall rot zeigt,
    wird nach einer Woche nicht mehr gelesen (§5.79).

    Erst ab der zweiten Meldung nach dem Befehl urteilt sie, und dann in
    beide Richtungen. Das ist der Punkt, an dem die Schrittliste für 107
    den Erfolg festhält.
    """
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id)

    async def _meldung(zeit: datetime, gesperrt: bool) -> None:
        db_session.add(
            SensorReading(
                time=zeit,
                device_id=dev.id,
                temperature=Decimal("21.0"),
                child_lock=gesperrt,
            )
        )
        await db_session.commit()

    def _urteil(meldung: child_lock.Sperrmeldung | None) -> str:
        assert meldung is not None
        return child_lock.child_lock_state(
            gewollt=True,
            gemeldet=meldung.gesperrt,
            nach_befehl=meldung.nach_befehl,
            befehl_um=dev.child_lock_commanded_at,
        )

    # 10:05 — die Meldung von **vor** dem Befehl.
    await _meldung(FROZEN_NOW - timedelta(minutes=11), gesperrt=False)

    # 10:16 — der Befehl.
    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )
    await db_session.commit()
    await db_session.refresh(dev)

    assert _urteil(await child_lock.child_lock_verdict(db_session, dev.id)) == "ausstehend", (
        "die Meldung von vor dem Befehl ist keine Antwort darauf"
    )

    # 10:23 — die erste Meldung **nach** dem Befehl, und sie sagt noch
    # „frei". Genau hier stand der rote Befund.
    await _meldung(FROZEN_NOW + timedelta(minutes=7), gesperrt=False)

    assert _urteil(await child_lock.child_lock_verdict(db_session, dev.id)) == "ausstehend", (
        "die erste Meldung nach dem Befehl oeffnet nur das Empfangsfenster"
    )

    # 10:34 — die zweite. Jetzt ist der Befehl zugestellt.
    await _meldung(FROZEN_NOW + timedelta(minutes=18), gesperrt=True)

    assert _urteil(await child_lock.child_lock_verdict(db_session, dev.id)) == "bestaetigt"


@freeze_time(FROZEN_NOW)
async def test_ein_verweigerndes_geraet_faellt_bei_der_zweiten_meldung_auf(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Die Gegenprobe: ein Gerät, das die Sperre wirklich verweigert.

    Dieselbe Zeitfolge, nur meldet das Gerät auch bei der zweiten Meldung
    „frei". Dann ist es eine **Antwort**, und die Anzeige sagt
    „fehlgeschlagen".

    Ohne diese Prüfung wäre die Änderung oben auch grün, wenn die Anzeige
    **immer** „ausstehend" sagte — und ein Melder, der nie etwas sagt, ist
    dasselbe wie keiner (§5.79).
    """
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id)

    async def _meldung(zeit: datetime) -> None:
        db_session.add(
            SensorReading(
                time=zeit,
                device_id=dev.id,
                temperature=Decimal("21.0"),
                child_lock=False,
            )
        )
        await db_session.commit()

    await _meldung(FROZEN_NOW - timedelta(minutes=11))
    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )
    await db_session.commit()
    await db_session.refresh(dev)

    await _meldung(FROZEN_NOW + timedelta(minutes=7))
    await _meldung(FROZEN_NOW + timedelta(minutes=18))

    meldung = await child_lock.child_lock_verdict(db_session, dev.id)
    assert meldung is not None
    assert meldung.nach_befehl == 2
    assert (
        child_lock.child_lock_state(
            gewollt=True,
            gemeldet=meldung.gesperrt,
            nach_befehl=meldung.nach_befehl,
            befehl_um=dev.child_lock_commanded_at,
        )
        == "fehlgeschlagen"
    )


@freeze_time(FROZEN_NOW)
async def test_eine_meldung_ohne_das_feld_zaehlt_nicht_mit(
    db_session: AsyncSession, funk: Funk
) -> None:
    """Eine Zeile ohne ``child_lock`` oeffnet das Urteil nicht.

    **Die Luecke, die eine Mutationsprobe gezeigt hat.** Gezaehlt werden
    die Meldungen seit dem Befehl — aber nur die, die das Feld
    **fuehren**. Eine Befehlsantwort oder ein Frame ohne das 0x80-Bit sagt
    nichts ueber die Sperre; zaehlte sie mit, waere das Urteil nach einer
    einzigen echten Meldung offen und der rote Befund waere zurueck.

    Dieselbe Drei-Zustands-Regel wie ueberall: ``NULL`` ist keine Aussage.
    """
    room_id, zone_id = await _zimmer(db_session)
    dev = await _geraet(db_session, zone_id)

    async def _meldung(zeit: datetime, gesperrt: bool | None) -> None:
        db_session.add(
            SensorReading(
                time=zeit,
                device_id=dev.id,
                temperature=Decimal("21.0"),
                child_lock=gesperrt,
            )
        )
        await db_session.commit()

    await _meldung(FROZEN_NOW - timedelta(minutes=11), gesperrt=False)
    await child_lock.sende_bei_aenderung(
        db_session, room_id=room_id, sperre_vorher=False, sperre_nachher=True
    )
    await db_session.commit()
    await db_session.refresh(dev)

    # Zwei Zeilen nach dem Befehl, aber nur **eine** fuehrt das Feld.
    await _meldung(FROZEN_NOW + timedelta(minutes=5), gesperrt=None)
    await _meldung(FROZEN_NOW + timedelta(minutes=7), gesperrt=False)

    meldung = await child_lock.child_lock_verdict(db_session, dev.id)
    assert meldung is not None
    assert meldung.nach_befehl == 1, "die Zeile ohne das Feld darf nicht mitzaehlen"
    assert (
        child_lock.child_lock_state(
            gewollt=True,
            gemeldet=meldung.gesperrt,
            nach_befehl=meldung.nach_befehl,
            befehl_um=dev.child_lock_commanded_at,
        )
        == "ausstehend"
    )
