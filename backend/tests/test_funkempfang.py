"""Funk-Empfang: Kachel-Stufe, Totalausfall-Schwelle, Audit-Zustand (T8).

**Die Gegenprobe ist der Zweck dieser Datei.** Der Ausfall vom 07.11.2026
dauerte **31 Minuten** und hat **keinen** vorhandenen Melder erreicht:
die Health-Stufe ``silent`` greift erst nach drei Stunden, und der
Funk-Wächter (T6) urteilt bei zu wenigen Daten ``unbekannt`` — genau das,
was ein Totalausfall erzeugt.

``test_gegenprobe_07_11_loest_nach_15_minuten_aus`` baut die Lücke mit
den **gemessenen** Zeiten nach: letzte Meldung ``06:21:35Z``, erste
danach ``06:52:46Z``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.models.sensor_reading import SensorReading
from heizung.services import funkempfang
from heizung.tasks import funk_tasks

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - die DB-Tests brauchen Test-DB"

#: Die Betriebswerte, hier als Pruefstand-Werte wiederholt. **Bewusst
#: nicht importiert**: der Test soll festhalten, gegen welche Zahlen er
#: geprueft hat. Zieht jemand die Vorgabe hoch, soll er nicht
#: stillschweigend mitwandern (§5.77 in Testform).
GRUEN = 5
GELB = 15
ALARM_AB = 15

#: Die gemessenen Zeiten des Ausfalls vom 07.11.2026.
LETZTE_MELDUNG = datetime(2026, 11, 7, 6, 21, 35, 770000, tzinfo=UTC)
ERSTE_DANACH = datetime(2026, 11, 7, 6, 52, 46, 918000, tzinfo=UTC)


def _beurteile(*, alter_min: float | None, meldungen: int = 100) -> funkempfang.Funkempfang:
    now = datetime(2026, 11, 7, 12, 0, 0, tzinfo=UTC)
    letzte = None if alter_min is None else now - timedelta(minutes=alter_min)
    return funkempfang.beurteile(
        letzte_meldung=letzte,
        meldungen=meldungen,
        now=now,
        gruen_max_min=GRUEN,
        gelb_max_min=GELB,
    )


# ---------------------------------------------------------------------------
# Die Stufe — ohne Datenbank, ohne Uhr
# ---------------------------------------------------------------------------


def test_frisch_ist_online() -> None:
    befund = _beurteile(alter_min=1)
    assert befund.stufe == "online"
    assert befund.alter_min == 1
    assert not befund.ist_totalausfall


def test_genau_auf_der_gruenen_grenze_ist_noch_online() -> None:
    """Fuenf Minuten sind **online**, nicht schon verzoegert.

    Die Grenze inklusiv zu nehmen ist hier die ruhigere Wahl: bei
    10-Minuten-Takt und ueber hundert Geraeten schwankt das Alter der
    juengsten Meldung um Sekunden, und eine Kachel, die bei 5:00 gelb
    wird und bei 4:59 gruen, flackert.
    """
    assert _beurteile(alter_min=GRUEN).stufe == "online"


def test_knapp_darueber_ist_verzoegert() -> None:
    assert _beurteile(alter_min=GRUEN + 1).stufe == "verzoegert"


def test_genau_auf_der_gelben_grenze_ist_schon_rot() -> None:
    """15 Minuten sind **keine Meldungen**, nicht mehr verzoegert.

    Die Vorgabe lautet „ab 15 Minuten eine Mail“. Waere die Grenze
    inklusiv, waere die Kachel bei genau 15:00 noch gelb, waehrend der
    Alarm mailt — eine gelbe Kachel zu einer roten Mail. Dieser Test ist
    beim ersten Lauf gefallen und hat die Inkonsistenz gefunden.
    """
    befund = _beurteile(alter_min=GELB)
    assert befund.stufe == "keine_meldungen"
    assert befund.ist_totalausfall


def test_darueber_ist_keine_meldungen() -> None:
    befund = _beurteile(alter_min=GELB + 1)
    assert befund.stufe == "keine_meldungen"
    assert befund.ist_totalausfall


def test_ohne_jede_meldung_ist_unbekannt_und_kein_ausfall() -> None:
    """**Der Test, der den Fehlalarm verhindert.**

    Gar keine Meldung heisst: frisch aufgesetztes Haus. Rot zu zeigen und
    zu mailen waere eine Behauptung ueber eine Anlage, die es noch nicht
    gibt — und ein Melder, der beim Aufsetzen anschlaegt, verliert
    Gewicht, bevor er zum ersten Mal gebraucht wird (§5.79).
    """
    befund = _beurteile(alter_min=None)
    assert befund.stufe == "unbekannt"
    assert befund.alter_min is None
    assert not befund.ist_totalausfall


def test_gegenprobe_07_11_der_ausfall_ist_rot() -> None:
    """Die gemessene Luecke vom 07.11.2026, zur Mitte des Ausfalls.

    Letzte Meldung ``06:21:35``, Stand ``06:40`` — also 18 Minuten. Das
    ist ueber der gelben Grenze **und** ueber der Alarmschwelle.
    """
    stand = datetime(2026, 11, 7, 6, 40, 0, tzinfo=UTC)
    befund = funkempfang.beurteile(
        letzte_meldung=LETZTE_MELDUNG,
        meldungen=0,
        now=stand,
        gruen_max_min=GRUEN,
        gelb_max_min=GELB,
    )
    assert befund.stufe == "keine_meldungen", f"der Ausfall waere nicht rot: {befund}"
    assert befund.alter_min == 18
    assert befund.ist_totalausfall
    assert befund.alter_min >= ALARM_AB, "der Alarm haette nicht gemailt"


def test_gegenprobe_07_11_loest_nach_15_minuten_aus() -> None:
    """**Die Anforderung des Betreibers: Alarm nach 15 Minuten.**

    Bei einem Beat-Takt von fuenf Minuten faellt die erste Pruefung nach
    der Schwelle auf ``06:21:35 + 15 min = 06:36:35``, also auf den Lauf
    um etwa 06:40. Geprueft wird hier die Schwelle selbst: 14 Minuten
    schweigen noch, 15 melden.
    """
    knapp_davor = LETZTE_MELDUNG + timedelta(minutes=14)
    knapp_danach = LETZTE_MELDUNG + timedelta(minutes=15)

    vorher = funkempfang.beurteile(
        letzte_meldung=LETZTE_MELDUNG,
        meldungen=0,
        now=knapp_davor,
        gruen_max_min=GRUEN,
        gelb_max_min=GELB,
    )
    assert vorher.alter_min == 14
    assert vorher.alter_min < ALARM_AB, "14 Minuten duerfen noch nicht mailen"

    nachher = funkempfang.beurteile(
        letzte_meldung=LETZTE_MELDUNG,
        meldungen=0,
        now=knapp_danach,
        gruen_max_min=GRUEN,
        gelb_max_min=GELB,
    )
    assert nachher.alter_min == 15
    assert nachher.ist_totalausfall
    assert nachher.alter_min >= ALARM_AB, "15 Minuten muessen mailen"


def test_nach_der_ruecknahme_ist_es_wieder_online() -> None:
    """Die Entwarnung braucht genau das: der Zustand kippt zurueck."""
    befund = funkempfang.beurteile(
        letzte_meldung=ERSTE_DANACH,
        meldungen=43,
        now=ERSTE_DANACH + timedelta(minutes=2),
        gruen_max_min=GRUEN,
        gelb_max_min=GELB,
    )
    assert befund.stufe == "online"
    assert not befund.ist_totalausfall


def test_der_alarmtext_sagt_zuerst_was_zu_tun_ist() -> None:
    """Und er schickt niemanden zuerst zum Gateway.

    Am 07.11. war das Gateway in Ordnung — die Ursache war eine
    Firewall-Regel. Deshalb steht „wurde gerade etwas geaendert" als
    Schritt 1 und das Gateway als Schritt 3.
    """
    befund = _beurteile(alter_min=31, meldungen=0)
    text_ = funkempfang.nachricht_alarm(befund, zeitzone="Europe/Vienna")

    assert "WAS ZU TUN IST" in text_
    assert text_.index("WAS ZU TUN IST") < text_.index("WAS DIESE MELDUNG BEDEUTET")
    assert text_.index("Firewall") < text_.index("stromlos"), (
        "die Reihenfolge der Pruefschritte ist die Lehre aus dem 07.11."
    )
    assert "5.0a" in text_
    assert "31 Minuten" in text_


def test_die_entwarnung_verspricht_nicht_zu_viel() -> None:
    """Sie sagt „Daten kommen an", nicht „behoben"."""
    befund = _beurteile(alter_min=1, meldungen=43)
    text_ = funkempfang.nachricht_entwarnung(befund, zeitzone="Europe/Vienna")
    assert "NICHT sagt" in text_
    assert "5.0a" in text_


# ---------------------------------------------------------------------------
# Gegen echtes Postgres
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    if not DATABASE_URL:
        pytest.skip(SKIP_REASON)
    engine: AsyncEngine = create_async_engine(DATABASE_URL)
    try:
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        async with sessionmaker() as session:
            yield session
    finally:
        await engine.dispose()


async def _geraet(session: AsyncSession) -> Device:
    # schema_constraint: device.dev_eui max 16 (§5.49)
    suffix = uuid.uuid4().hex[:8]
    geraet = Device(
        dev_eui=f"fe{suffix}fe{suffix}"[:16],
        label=f"fe-{suffix}",
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
    )
    session.add(geraet)
    await session.commit()
    return geraet


async def _raeum_auf(session: AsyncSession, device_id: int) -> None:
    await session.execute(text("DELETE FROM sensor_reading WHERE device_id = :i"), {"i": device_id})
    await session.execute(text("DELETE FROM device WHERE id = :i"), {"i": device_id})
    await session.commit()


async def test_lies_funkempfang_zaehlt_nur_das_fenster(db_session: AsyncSession) -> None:
    """Die zweite Zahl ist das Zehn-Minuten-Fenster, nicht alles.

    Sie beantwortet eine andere Frage als die erste: eine **schleichende**
    Verschlechterung, bei der die juengste Meldung frisch ist und die
    Menge trotzdem einbricht.
    """
    geraet = await _geraet(db_session)
    jetzt = datetime.now(tz=UTC)
    try:
        for minuten in (1, 3, 5, 9):
            db_session.add(
                SensorReading(
                    device_id=geraet.id,
                    time=jetzt - timedelta(minutes=minuten),
                    temperature=Decimal("21.0"),
                )
            )
        # Ausserhalb des Fensters — darf nicht mitzaehlen.
        for minuten in (11, 30, 120):
            db_session.add(
                SensorReading(
                    device_id=geraet.id,
                    time=jetzt - timedelta(minutes=minuten),
                    temperature=Decimal("21.0"),
                )
            )
        await db_session.commit()

        befund = await funkempfang.lies_funkempfang(
            db_session, gruen_max_min=GRUEN, gelb_max_min=GELB, now=jetzt
        )

        assert befund.stufe == "online"
        assert befund.meldungen_zaehlfenster == 4, (
            f"das Fenster hat mehr gezaehlt als zehn Minuten: {befund.meldungen_zaehlfenster}"
        )
    finally:
        await _raeum_auf(db_session, geraet.id)


async def test_audit_spur_ist_der_zustand(db_session: AsyncSession) -> None:
    """Der Zustand kommt aus ``business_audit``, nicht aus Redis.

    Grund im Docstring von ``_letzter_totalausfall_stand``: ein
    Redis-Schluessel verliert sich beim Neustart, und ``alert_throttle``
    laesst bei Redis-Ausfall alles durch — bei einem Fuenf-Minuten-Takt
    waeren das zwoelf Mails je Stunde.
    """
    jetzt = datetime.now(tz=UTC)
    marke = uuid.uuid4().hex[:8]
    try:
        db_session.add(
            BusinessAudit(
                user_id=None,
                action=funk_tasks.AUDIT_TOTALAUSFALL,
                target_type=f"test-{marke}",
                target_id=None,
                old_value=None,
                new_value={"marke": marke},
                ts=jetzt - timedelta(minutes=30),
            )
        )
        await db_session.commit()

        aktion, zeit = await funk_tasks._letzter_totalausfall_stand(db_session)
        assert aktion == funk_tasks.AUDIT_TOTALAUSFALL, "der laufende Ausfall wurde nicht erkannt"
        assert zeit is not None

        # Entwarnung danach -> der Zustand kippt.
        db_session.add(
            BusinessAudit(
                user_id=None,
                action=funk_tasks.AUDIT_TOTALAUSFALL_ENDE,
                target_type=f"test-{marke}",
                target_id=None,
                old_value=None,
                new_value={"marke": marke},
                ts=jetzt - timedelta(minutes=5),
            )
        )
        await db_session.commit()

        aktion2, _ = await funk_tasks._letzter_totalausfall_stand(db_session)
        assert aktion2 == funk_tasks.AUDIT_TOTALAUSFALL_ENDE, (
            "nach der Entwarnung darf kein Ausfall mehr laufen"
        )
    finally:
        await db_session.execute(
            text("DELETE FROM business_audit WHERE target_type = :t"), {"t": f"test-{marke}"}
        )
        await db_session.commit()
