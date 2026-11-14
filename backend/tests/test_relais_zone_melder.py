"""Meldung, wenn der Fuehler einer Relais-Zone schweigt (13.11.2026).

**Die Gegenprobe ist der Zweck dieser Datei.** Fuehler 056 (Zone
Eingang, Rezeption) war am 12./13.11.2026 von **14:41 bis 04:44** stumm,
vierzehn Stunden, 83 verlorene Frames. Die Zone fuehrte dabei ein Relais
in Betrieb und wurde deshalb nicht geheizt — der Zwangs-AUS des
Zweipunktreglers hat richtig gegriffen.

**Kein vorhandener Melder hat angeschlagen**, und das ist der Grund fuer
diesen Waechter:

* Die Health-Stufe ``silent`` verlangt **mehr als 24 Stunden** offline
  (AE-53). Vierzehn Stunden sind ``degraded``, und die ist stumm.
* Der hausweite Totalausfall-Waechter hat korrekt geschwiegen: 103
  Geraete online, 605 Messwerte je Stunde.
* Sichtbar war genau eine Zahl: „Geraete online" stand auf 102 von 103.

``test_gegenprobe_056_waere_nach_30_minuten_gemeldet_worden`` baut die
Luecke mit den **gemessenen** Zeiten nach.
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.config import get_settings
from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import relais_zone_melder
from heizung.tasks import funk_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "rfw"

#: Die Betriebsvorgabe, hier als Pruefstand-Wert wiederholt. **Bewusst
#: nicht importiert**: der Test soll festhalten, gegen welche Zahl er
#: geprueft hat — zieht jemand die Vorgabe hoch, soll er nicht
#: stillschweigend mitwandern (§5.77 in Testform).
GRENZE_MIN = 30

#: Die gemessenen Zeiten der Luecke vom 12./13.11.2026 (Ortszeit +01:00).
LETZTE_MELDUNG_056 = datetime(2026, 11, 12, 13, 41, 1, tzinfo=UTC)
ERSTE_DANACH_056 = datetime(2026, 11, 13, 3, 44, 8, tzinfo=UTC)


def _beurteile(
    *,
    alter_min: float | None,
    fuehler: tuple[str, ...] = ("056 Eingang",),
    relais: tuple[str, ...] = ("108 Panel",),
    relais_alter_min: float | None = 5,
    now: datetime | None = None,
) -> relais_zone_melder.ZonenBefund:
    """``relais_alter_min`` ist **frisch** vorbelegt (14.11.2026).

    Die Bestandstests dieser Datei handeln vom Fuehler; ohne eine frische
    Relais-Meldung waere in jedem von ihnen zusaetzlich das Relais stumm,
    und sie pruefen dann etwas anderes als ihr Name sagt. In der Signatur
    des Urteils gibt es diesen Default nicht — dort ist jede Beobachtung
    ein Pflicht-Argument.
    """
    jetzt = now or datetime(2026, 11, 12, 20, 0, 0, tzinfo=UTC)
    letzte = None if alter_min is None else jetzt - timedelta(minutes=alter_min)
    relais_letzte = (
        None if relais_alter_min is None else jetzt - timedelta(minutes=relais_alter_min)
    )
    return relais_zone_melder.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=fuehler,
        letzte_meldung=letzte,
        relais=relais,
        relais_letzte_meldung=relais_letzte,
        now=jetzt,
        grenze_min=GRENZE_MIN,
    )


# ---------------------------------------------------------------------------
# Das Urteil — ohne Datenbank, ohne Uhr
# ---------------------------------------------------------------------------


def test_frischer_fuehler_ist_in_ordnung() -> None:
    befund = _beurteile(alter_min=9)
    assert befund.grund is None
    assert not befund.stumm
    assert befund.alter_min == 9


def test_genau_auf_der_grenze_meldet_noch_nicht() -> None:
    """30:00 ist noch in Ordnung, die Grenze ist exklusiv.

    Die Vorgabe lautet „ohne Meldung **seit mehr als** 30 Minuten". Bei
    Zehn-Minuten-Takt liegt die dritte verpasste Meldung genau dort, und
    das Alter schwankt um Sekunden — eine inklusive Grenze wuerde beim
    Grenzfall flackern.
    """
    assert _beurteile(alter_min=GRENZE_MIN).grund is None


def test_knapp_darueber_ist_stumm() -> None:
    befund = _beurteile(alter_min=GRENZE_MIN + 1)
    assert befund.grund == relais_zone_melder.GRUND_STUMM
    assert befund.stumm


def test_noch_nie_gehoert_zaehlt_wie_stumm() -> None:
    """**Anders als beim Totalausfall**, und das ist der Unterschied.

    Dort heisst „gar keine Meldung" ein frisch aufgesetztes Haus, und
    rot zu zeigen waere eine Behauptung ueber eine Anlage, die es noch
    nicht gibt. Hier hat jemand ein Relais **ausdruecklich** in Betrieb
    genommen; ein Fuehler, der noch nie gemeldet hat, ist fuer diese
    Zone genau so wertlos wie einer, der aufgehoert hat.
    """
    befund = _beurteile(alter_min=None)
    assert befund.grund == relais_zone_melder.GRUND_STUMM
    assert befund.alter_min is None


def test_zone_ohne_fuehler_hat_einen_eigenen_grund() -> None:
    """Und er schlaegt die Stille, weil er der schwerere Mangel ist.

    Ein in Betrieb genommenes Relais ohne Fuehler kann **nie** heizen.
    Ein Waechter, der genau hier schweigt, weil es keinen Fuehler gibt,
    dessen Stille er messen koennte, waere der naechste Melder, der dann
    nichts sagt, wenn es am meisten zaehlt (§5.79).
    """
    befund = _beurteile(alter_min=1, fuehler=())
    assert befund.grund == relais_zone_melder.GRUND_KEIN_FUEHLER
    assert befund.stumm
    assert befund.alter_min is None, (
        "ohne Fuehler gibt es kein Alter - eine Zahl waere eine Behauptung"
    )


def test_gegenprobe_056_waere_nach_30_minuten_gemeldet_worden() -> None:
    """**Die Anforderung des Betreibers, an der echten Luecke geprueft.**

    Letzte Meldung 14:41:01 Ortszeit. Bei einem Beat-Takt von fuenf
    Minuten faellt die erste Pruefung nach der Schwelle auf den Lauf um
    etwa 15:15. Geprueft wird die Schwelle selbst: 30 Minuten schweigen
    noch, 31 melden.
    """
    noch_still = relais_zone_melder.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=LETZTE_MELDUNG_056,
        relais=("108 Panel",),
        relais_letzte_meldung=LETZTE_MELDUNG_056 + timedelta(minutes=GRENZE_MIN),
        now=LETZTE_MELDUNG_056 + timedelta(minutes=GRENZE_MIN),
        grenze_min=GRENZE_MIN,
    )
    assert noch_still.grund is None, "30 Minuten duerfen noch nicht melden"

    meldet = relais_zone_melder.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=LETZTE_MELDUNG_056,
        relais=("108 Panel",),
        relais_letzte_meldung=LETZTE_MELDUNG_056 + timedelta(minutes=GRENZE_MIN + 1),
        now=LETZTE_MELDUNG_056 + timedelta(minutes=GRENZE_MIN + 1),
        grenze_min=GRENZE_MIN,
    )
    assert meldet.stumm, "31 Minuten muessen melden"
    assert meldet.alter_min == GRENZE_MIN + 1

    # Und zur Mitte der Luecke, wo der Betreiber nichts erfahren hat.
    mitte = relais_zone_melder.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=LETZTE_MELDUNG_056,
        relais=("108 Panel",),
        relais_letzte_meldung=datetime(2026, 11, 12, 21, 0, 0, tzinfo=UTC),
        now=datetime(2026, 11, 12, 21, 0, 0, tzinfo=UTC),
        grenze_min=GRENZE_MIN,
    )
    assert mitte.alter_min == 438, f"die Luecke war {mitte.alter_min} Minuten"


def test_nach_der_rueckkehr_ist_es_wieder_in_ordnung() -> None:
    """Die Entwarnung braucht genau das: der Zustand kippt zurueck."""
    befund = relais_zone_melder.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=ERSTE_DANACH_056,
        relais=("108 Panel",),
        relais_letzte_meldung=ERSTE_DANACH_056 + timedelta(minutes=2),
        now=ERSTE_DANACH_056 + timedelta(minutes=2),
        grenze_min=GRENZE_MIN,
    )
    assert befund.grund is None


# ---------------------------------------------------------------------------
# Die Texte
# ---------------------------------------------------------------------------


def test_der_alarmtext_sagt_zuerst_die_folge_und_nicht_die_diagnose() -> None:
    """Wer nachts geweckt wird, braucht die Folge, nicht das Geraet.

    Der erste Satz muss „wird nicht geheizt" sagen. Welcher Fuehler
    schweigt, steht darunter — das ist die Diagnose und nicht die
    Nachricht.
    """
    befund = _beurteile(alter_min=438)
    text_ = relais_zone_melder.nachricht_alarm(befund, zeitzone="Europe/Vienna")

    erste_zeile = text_.splitlines()[0]
    assert "nicht geheizt" in erste_zeile, f"die Folge fehlt im ersten Satz: {erste_zeile!r}"
    assert "Rezeption" in erste_zeile
    assert text_.index("DER STAND") < text_.index("WAS ZU TUN IST")
    assert "056 Eingang" in text_
    assert "438 Minuten" in text_
    # Schritt 1 ist die hausweite Frage: ist es dieser Fuehler oder alle?
    assert text_.index("hausweit") < text_.index("Sendeleistung")
    assert "10av" in text_, "der Befund vom 12.11. gehoert in die Mail"


def test_der_text_ohne_fuehler_nennt_keine_minuten() -> None:
    """Es gibt dort keine Stille, nur eine fehlende Zuordnung.

    Eine Minutenzahl waere hier eine Aussage ueber eine Meldung, die es
    nie gab — und sie wuerde den Empfaenger auf Funksuche schicken,
    obwohl nichts zu suchen ist.
    """
    befund = _beurteile(alter_min=None, fuehler=())
    text_ = relais_zone_melder.nachricht_alarm(befund, zeitzone="Europe/Vienna")
    assert "kein Thermostat" in text_
    assert "Minuten" not in text_, "ohne Fuehler darf keine Minutenzahl im Text stehen"
    assert "Thermostat dieser Zone zuordnen" in text_
    assert "kein Thermostat" in relais_zone_melder.betreff_alarm(befund)


def test_die_entwarnung_verspricht_nicht_zu_viel() -> None:
    """Sie sagt „liefert wieder", nicht „ist warm" (§5.79)."""
    befund = _beurteile(alter_min=1)
    text_ = relais_zone_melder.nachricht_entwarnung(befund, zeitzone="Europe/Vienna")
    assert "wieder" in text_
    assert "sagt diese Meldung nicht" in text_
    assert "Rezeption" in relais_zone_melder.betreff_entwarnung(befund)


# ---------------------------------------------------------------------------
# Gegen echtes Postgres
# ---------------------------------------------------------------------------
#
# **Kein ``pytestmark`` auf Modulebene**, und das ist Absicht: die Urteile
# und die Texte oben brauchen keine Datenbank und sollen auch ohne sie
# laufen. Ein Modul-Mark haette sie mitgesprungen, und dann prueft ein
# Lauf ohne ``TEST_DATABASE_URL`` gar nichts mehr — ein gruener Lauf, der
# nichts geprueft hat (Paragraph 5.55). Der Sprung sitzt deshalb in der
# ``maker``-Fixture.


class Aufbau:
    """Die Ids des Testaufbaus."""

    def __init__(
        self, room_id: int, zone_id: int, fuehler_id: int, relais_id: int, nachbar_id: int
    ) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.fuehler_id = fuehler_id
        self.relais_id = relais_id
        #: Ein Geraet **ausserhalb** der Zone mit einer frischen Meldung.
        #:
        #: Damit sieht das Haus online aus, waehrend der Fuehler der Zone
        #: schweigt — genau die Lage vom 12./13.11. Ohne dieses Geraet
        #: waere die juengste Meldung des Hauses die alte der Zone, der
        #: Waechter wuerde einen Totalausfall sehen und planmaessig
        #: schweigen. Der Test haette dann das Richtige geprueft und das
        #: Falsche belegt.
        self.nachbar_id = nachbar_id


@pytest_asyncio.fixture
async def maker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Session-Fabrik auf der Test-DB — und ``DATABASE_URL`` darauf gepinnt.

    Der Task oeffnet seine Session selbst (``_task_session``) und liest
    dafuer ``settings.database_url``. Ohne das Pinnen wuerde er eine
    andere Datenbank sehen als der Aufbau hier, und die Tests waeren
    gruen oder rot aus dem falschen Grund (Paragraph 5.48).
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    get_settings.cache_clear()
    engine = create_async_engine(TEST_DB_URL)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        get_settings.cache_clear()


async def _baue(
    maker: Any,
    *,
    mit_fuehler: bool = True,
    in_betrieb: bool = True,
    sperre: bool = False,
    fuehler_alter_min: int | None = 5,
    relais_alter_min: int | None = 5,
) -> Aufbau:
    """Ein Zimmer mit einer Zone, einem Relais und (optional) einem Fuehler.

    ``relais_alter_min`` ist seit dem 14.11.2026 Teil des Aufbaus. Ohne
    eine Relais-Meldung ist das Relais **stumm** — richtig, aber nicht
    das, was die Bestandstests dieser Datei pruefen wollen. Fuenf Minuten
    sind der Normalfall eines Relais im Betrieb (Meldeintervall zehn
    Minuten); ``None`` heisst "hat noch nie gemeldet".
    """
    short = uuid.uuid4().hex[:4]
    jetzt = datetime.now(tz=UTC)
    async with maker() as session:
        rt = RoomType(
            name=f"{PREFIX}-rt-{short}",
            is_bookable=False,
            default_t_occupied=Decimal("21.0"),
        )
        session.add(rt)
        await session.flush()
        # schema_constraint: room.number max 20 (§5.49)
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
        session.add(zone)
        await session.flush()

        relais = Device(
            # schema_constraint: device.dev_eui max 16 (§5.49)
            dev_eui=f"relais00{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label="Panel",
            heating_zone_id=zone.id,
            health_state="healthy",
            firmware_version="1.5",
            power_return_verified_at=jetzt - timedelta(hours=2),
            overheating_recovery_verified_at=jetzt - timedelta(hours=2),
            commissioned_at=(jetzt - timedelta(hours=1)) if in_betrieb else None,
            protection_tripped_at=(jetzt - timedelta(minutes=5)) if sperre else None,
            protection_kind="overheating" if sperre else None,
        )
        session.add(relais)
        await session.flush()
        if relais_alter_min is not None:
            session.add(
                RelayReading(
                    device_id=relais.id,
                    time=jetzt - timedelta(minutes=relais_alter_min),
                    relay_on=False,
                    power_w=0,
                )
            )

        fuehler_id = 0
        if mit_fuehler:
            fuehler = Device(
                dev_eui=f"fuehler0{uuid.uuid4().hex[:8]}",
                kind=DeviceKind.THERMOSTAT,
                vendor=DeviceVendor.MCLIMATE,
                model="vicki",
                label=f"{PREFIX}-{short} Fuehler",
                heating_zone_id=zone.id,
                health_state="healthy",
                measure_only=True,
            )
            session.add(fuehler)
            await session.flush()
            fuehler_id = fuehler.id
            if fuehler_alter_min is not None:
                session.add(
                    SensorReading(
                        device_id=fuehler.id,
                        time=jetzt - timedelta(minutes=fuehler_alter_min),
                        temperature=Decimal("21.0"),
                    )
                )

        # Der Nachbar: keine Zone, frische Meldung. Siehe ``Aufbau``.
        nachbar = Device(
            dev_eui=f"nachbar0{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.THERMOSTAT,
            vendor=DeviceVendor.MCLIMATE,
            model="vicki",
            label=f"{PREFIX}-{short} Nachbar",
            health_state="healthy",
        )
        session.add(nachbar)
        await session.flush()
        session.add(
            SensorReading(
                device_id=nachbar.id,
                time=jetzt,
                temperature=Decimal("22.0"),
            )
        )

        await session.flush()
        ids = Aufbau(room.id, zone.id, fuehler_id, relais.id, nachbar.id)
        await session.commit()
    return ids


async def _raeum_auf(maker: Any, ids: Aufbau) -> None:
    async with maker() as session:
        geraete = [i for i in (ids.fuehler_id, ids.relais_id, ids.nachbar_id) if i]
        await session.execute(
            text(
                "DELETE FROM business_audit WHERE target_type = 'heating_zone' AND target_id = :z"
            ),
            {"z": ids.zone_id},
        )
        await session.execute(
            text("DELETE FROM sensor_reading WHERE device_id = ANY(:d)"), {"d": geraete}
        )
        # Seit dem 14.11.2026 legt der Aufbau auch eine Relais-Meldung an.
        # Bleibt sie liegen, haengt an der naechsten Geraete-Id ein
        # fremdes Lebenszeichen (Paragraph 5.39).
        await session.execute(
            text("DELETE FROM relay_reading WHERE device_id = ANY(:d)"), {"d": geraete}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
        # ``room`` CASCADE raeumt die Zone, aber ``device.heating_zone_id``
        # ist nullable und wird dabei nur auf NULL gesetzt — die Geraete
        # muessen ausdruecklich weg (§5.39).
        await session.execute(text("DELETE FROM device WHERE id = ANY(:d)"), {"d": geraete})
        await session.execute(
            text(
                "DELETE FROM room_type WHERE id NOT IN (SELECT room_type_id FROM room) "
                "AND name LIKE :p"
            ),
            {"p": f"{PREFIX}-%"},
        )
        await session.commit()


def _eigene(
    befunde: list[relais_zone_melder.ZonenBefund], ids: Aufbau
) -> relais_zone_melder.ZonenBefund:
    """Nur der eigene Aufbau. Andere Zonen des Hauses zaehlen nicht mit (§5.39)."""
    treffer = [b for b in befunde if b.zone_id == ids.zone_id]
    assert len(treffer) == 1, f"die eigene Zone wurde nicht genau einmal gefunden: {befunde}"
    return treffer[0]


async def test_frischer_fuehler_erzeugt_keinen_befund(maker: Any) -> None:
    ids = await _baue(maker, fuehler_alter_min=5)
    try:
        async with maker() as session:
            befunde = await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        assert not _eigene(befunde, ids).stumm
    finally:
        await _raeum_auf(maker, ids)


async def test_stummer_fuehler_wird_gefunden(maker: Any) -> None:
    ids = await _baue(maker, fuehler_alter_min=45)
    try:
        async with maker() as session:
            befunde = await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        befund = _eigene(befunde, ids)
        assert befund.grund == relais_zone_melder.GRUND_STUMM
        assert befund.alter_min is not None and befund.alter_min >= 45
        assert befund.relais_in_betrieb == 1
    finally:
        await _raeum_auf(maker, ids)


async def test_relais_nicht_in_betrieb_wird_nicht_geprueft(maker: Any) -> None:
    """**Die Stelle, die den Fehlalarm verhindert.**

    Ein Relais, das noch nicht in Betrieb genommen ist, schaltet nie —
    ein stummer Fuehler aendert daran nichts. Eine Mail dazu waere Laerm
    aus einem Zustand, den jemand absichtlich hergestellt hat.
    """
    ids = await _baue(maker, in_betrieb=False, fuehler_alter_min=600)
    try:
        async with maker() as session:
            befunde = await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        assert all(b.zone_id != ids.zone_id for b in befunde), (
            "eine Zone ohne Relais in Betrieb darf nicht geprueft werden"
        )
    finally:
        await _raeum_auf(maker, ids)


async def test_relais_mit_schutzsperre_wird_nicht_geprueft(maker: Any) -> None:
    """Dieselbe Grenze wie ``darf_schalten``, und sie ist **eine** Quelle.

    Ein Relais mit stehender Sperre kann ohnehin nicht schalten. Haette
    dieser Waechter seine eigene Bedingung, waere sie beim ersten
    Nachjustieren an ``darf_schalten`` falsch (§5.53).
    """
    ids = await _baue(maker, sperre=True, fuehler_alter_min=600)
    try:
        async with maker() as session:
            befunde = await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        assert all(b.zone_id != ids.zone_id for b in befunde)
    finally:
        await _raeum_auf(maker, ids)


async def test_zone_ohne_fuehler_wird_gemeldet(maker: Any) -> None:
    ids = await _baue(maker, mit_fuehler=False)
    try:
        async with maker() as session:
            befunde = await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        befund = _eigene(befunde, ids)
        assert befund.grund == relais_zone_melder.GRUND_KEIN_FUEHLER
        assert befund.fuehler == ()
    finally:
        await _raeum_auf(maker, ids)


async def test_fuehler_ohne_etikett_gilt_als_fuehler(maker: Any) -> None:
    """Sonst meldet der Waechter ``kein_fuehler`` fuer eine Zone, die einen hat.

    Das Etikett ist eine Anzeigesache; fuer die Regelung zaehlt das
    Geraet. Die Laenge der Liste **ist** die Zahl der Fuehler, deshalb
    ein Platzhalter statt eines Filters.
    """
    ids = await _baue(maker, fuehler_alter_min=45)
    async with maker() as session:
        await session.execute(
            text("UPDATE device SET label = NULL WHERE id = :d"), {"d": ids.fuehler_id}
        )
        await session.commit()
    try:
        async with maker() as session:
            befunde = await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        befund = _eigene(befunde, ids)
        assert befund.grund == relais_zone_melder.GRUND_STUMM, (
            "ein Geraet ohne Etikett ist trotzdem ein Fuehler"
        )
        assert befund.fuehler == ("ohne Etikett",)
    finally:
        await _raeum_auf(maker, ids)


async def test_der_zustand_haengt_an_der_zone_und_nicht_am_haus(maker: Any) -> None:
    """Zwei Zonen koennen unabhaengig stumm werden.

    Eine gemeinsame Marke wuerde die Entwarnung der einen Zone auf die
    andere uebertragen — und damit genau die Mail unterdruecken, die
    noch gebraucht wird.
    """
    eins = await _baue(maker, fuehler_alter_min=45)
    zwei = await _baue(maker, fuehler_alter_min=5)
    try:
        async with maker() as session:
            session.add(
                BusinessAudit(
                    user_id=None,
                    action=funk_tasks.AUDIT_ZONE_STUMM,
                    target_type="heating_zone",
                    target_id=eins.zone_id,
                    old_value=None,
                    new_value={"zone": "eins"},
                    ts=datetime.now(tz=UTC) - timedelta(minutes=10),
                )
            )
            await session.commit()

            aktion_eins, zeit_eins = await funk_tasks._letzter_zonen_stand(
                session, zone_id=eins.zone_id
            )
            aktion_zwei, _ = await funk_tasks._letzter_zonen_stand(session, zone_id=zwei.zone_id)

        assert aktion_eins == funk_tasks.AUDIT_ZONE_STUMM
        assert zeit_eins is not None
        assert aktion_zwei is None, "die Marke der einen Zone darf die andere nicht betreffen"
    finally:
        await _raeum_auf(maker, eins)
        await _raeum_auf(maker, zwei)


# ---------------------------------------------------------------------------
# Der Task: Episode, Bremse, Entwarnung
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
def kein_mailversand(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Mitschreiber statt Versand. Die Texte haben ihre eigenen Tests."""
    betreffe: list[str] = []

    def _send(*, recipient: str | None, subject: str, body: str) -> Any:
        from heizung.services.mailer import MailResult

        betreffe.append(subject)
        return MailResult(sent=True, reason=None, detail="test")

    monkeypatch.setattr(funk_tasks.mailer, "send_mail", _send)
    return betreffe


async def _audit_aktionen(maker: Any, zone_id: int) -> list[str]:
    async with maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM business_audit "
                    "WHERE target_type = 'heating_zone' AND target_id = :z "
                    "ORDER BY ts"
                ),
                {"z": zone_id},
            )
        ).all()
    return [r[0] for r in rows]


async def test_episode_meldet_einmal_und_bremst_dann(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Einmal je Episode, nicht alle fuenf Minuten.

    Ohne Bremse waeren das bei Fuenf-Minuten-Takt zwoelf Mails je
    Stunde — und ein Melder, der so oft meldet, wird abgeschaltet statt
    gelesen (§5.79).
    """
    ids = await _baue(maker, fuehler_alter_min=45)
    try:
        # Das Haus muss online sein, sonst ueberspringt der Waechter
        # (und genau das prueft der Test darunter).
        erst = await funk_tasks._run_relais_zone()
        assert erst.get("uebersprungen") != "totalausfall", (
            "der Pruefstand hat keine frischen hausweiten Meldungen"
        )
        assert erst["zonen_stumm"] >= 1

        zweit = await funk_tasks._run_relais_zone()

        aktionen = await _audit_aktionen(maker, ids.zone_id)
        assert aktionen == [funk_tasks.AUDIT_ZONE_STUMM], (
            f"die Episode hat mehr als eine Zeile erzeugt: {aktionen}"
        )
        assert all(a["zone_id"] != ids.zone_id for a in zweit["aktionen"]), (
            "der zweite Lauf haette gebremst sein muessen"
        )
    finally:
        await _raeum_auf(maker, ids)


async def test_rueckkehr_erzeugt_die_entwarnung(maker: Any, kein_mailversand: list[str]) -> None:
    """Ein Alarm ohne Entwarnung laesst den Empfaenger im Ungewissen."""
    ids = await _baue(maker, fuehler_alter_min=45)
    try:
        await funk_tasks._run_relais_zone()

        # Der Fuehler meldet wieder.
        async with maker() as session:
            session.add(
                SensorReading(
                    device_id=ids.fuehler_id,
                    time=datetime.now(tz=UTC),
                    temperature=Decimal("21.5"),
                )
            )
            await session.commit()

        await funk_tasks._run_relais_zone()

        aktionen = await _audit_aktionen(maker, ids.zone_id)
        assert aktionen == [
            funk_tasks.AUDIT_ZONE_STUMM,
            funk_tasks.AUDIT_ZONE_STUMM_ENDE,
        ], f"Alarm und Entwarnung fehlen oder stehen falsch: {aktionen}"
    finally:
        await _raeum_auf(maker, ids)


async def test_ohne_vorherigen_alarm_keine_entwarnung(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Eine Entwarnung ueber nichts ist eine Mail ueber nichts."""
    ids = await _baue(maker, fuehler_alter_min=5)
    try:
        await funk_tasks._run_relais_zone()
        assert await _audit_aktionen(maker, ids.zone_id) == []
    finally:
        await _raeum_auf(maker, ids)


async def test_bei_hausweitem_ausfall_schweigt_dieser_melder(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonst ist die Zonen-Mail dieselbe Nachricht in kleinerer Schrift.

    Der Wert dieses Waechters liegt im anderen Fall: das Haus ist in
    Ordnung und **eine** Zone ist blind — so war es am 12./13.11.
    """
    ids = await _baue(maker, fuehler_alter_min=600)

    async def _totalausfall(session: Any, **_: Any) -> Any:
        from heizung.services.funkempfang import Funkempfang

        return Funkempfang(None, 400, 0, "keine_meldungen")

    monkeypatch.setattr(funk_tasks.funkempfang, "lies_funkempfang", _totalausfall)
    try:
        ergebnis = await funk_tasks._run_relais_zone()
        assert ergebnis.get("uebersprungen") == "totalausfall"
        assert await _audit_aktionen(maker, ids.zone_id) == [], (
            "bei hausweitem Ausfall darf keine Zonen-Zeile entstehen"
        )
    finally:
        await _raeum_auf(maker, ids)


# ---------------------------------------------------------------------------
# Die zweite Geraeteart: das Relais selbst (14.11.2026)
# ---------------------------------------------------------------------------


def test_stummes_relais_bei_gesundem_fuehler_hat_seinen_eigenen_grund() -> None:
    """**Die Luecke, die Punkt 2 schliesst.**

    Der Fuehler meldet, das Relais nicht. Bis zum 14.11. war das kein
    Befund: der Melder hat nur den Fuehler gemessen, und die Zone galt
    als in Ordnung — waehrend niemand mehr wusste, ob das Panel heizt.
    """
    befund = _beurteile(alter_min=5, relais_alter_min=40)

    assert befund.stumm
    assert befund.grund == relais_zone_melder.GRUND_RELAIS_STUMM
    assert befund.relais_stumm is True
    assert befund.relais_alter_min == 40
    assert befund.schweigende_geraete == ("108 Panel",)


def test_stummer_fuehler_schlaegt_stummes_relais() -> None:
    """Die Reihenfolge der Gruende, und sie folgt der Folge.

    Schweigen beide, ist der Grund der Fuehler: ohne Fuehlerwert heizt
    die Zone **nicht**, das ist die haertere Aussage als ein unbekannter
    Schaltzustand. Gemeldet wird trotzdem beides — sonst fehlte in der
    Mail genau die Haelfte, die einen Geraetefehler von einem
    Verbindungsausfall unterscheidet.
    """
    befund = _beurteile(alter_min=40, relais_alter_min=40)

    assert befund.grund == relais_zone_melder.GRUND_STUMM
    assert befund.relais_stumm is True
    assert befund.schweigende_geraete == ("056 Eingang", "108 Panel")


def test_frisches_relais_bleibt_unerwaehnt() -> None:
    """Die Gegenprobe: ein meldendes Relais steht in keiner Mail."""
    befund = _beurteile(alter_min=40, relais_alter_min=5)

    assert befund.grund == relais_zone_melder.GRUND_STUMM
    assert befund.relais_stumm is False
    assert befund.schweigende_geraete == ("056 Eingang",)


def test_relais_das_noch_nie_gemeldet_hat_zaehlt_wie_stumm() -> None:
    """Dieselbe Lesart wie beim Fuehler.

    Ein in Betrieb genommenes Relais, von dem noch nie eine Zeile
    angekommen ist, ist fuer die Zone genauso wertlos wie eines, das
    aufgehoert hat — und „in Betrieb genommen" heisst, dass jemand es
    ausdruecklich freigegeben hat.
    """
    befund = _beurteile(alter_min=5, relais_alter_min=None)

    assert befund.grund == relais_zone_melder.GRUND_RELAIS_STUMM
    assert befund.relais_alter_min is None


def test_die_grenze_gilt_fuer_das_relais_genauso() -> None:
    """30 Minuten schweigen noch, 31 melden — dieselbe Zahl, dieselbe Kante."""
    assert _beurteile(alter_min=5, relais_alter_min=GRENZE_MIN).grund is None
    assert (
        _beurteile(alter_min=5, relais_alter_min=GRENZE_MIN + 1).grund
        == relais_zone_melder.GRUND_RELAIS_STUMM
    )


def test_die_zahl_der_relais_kommt_aus_der_liste() -> None:
    """``relais_in_betrieb`` ist eine Eigenschaft, keine zweite Angabe.

    Vorher war es ein eigenes Feld. Zwei Angaben, die dasselbe zaehlen,
    laufen beim ersten Fehlgriff auseinander — und dann steht in der Mail
    „2 in Betrieb" neben einem einzigen Etikett (Paragraph 5.53).
    """
    befund = _beurteile(alter_min=5, relais=("108 Panel", "109 Panel"))
    assert befund.relais_in_betrieb == 2


# ---------------------------------------------------------------------------
# Die Texte der zweiten Geraeteart
# ---------------------------------------------------------------------------


def test_der_betreff_nennt_die_geraeteart() -> None:
    """Sonst weiss niemand, wohin er gehen soll.

    „Ohne Meldung seit 40 Minuten" liesse offen, ob der Hausmeister zum
    Fuehler oder zum Panel muss — und das ist die Frage, die eine Mail
    nachts beantworten soll.
    """
    nur_relais = relais_zone_melder.betreff_alarm(_beurteile(alter_min=5, relais_alter_min=40))
    assert "Relais" in nur_relais

    beide = relais_zone_melder.betreff_alarm(_beurteile(alter_min=40, relais_alter_min=40))
    assert "Fuehler und Relais" in beide


def test_der_text_zum_stummen_relais_behauptet_nicht_die_zone_sei_kalt() -> None:
    """**Die Folge ist bei den beiden Geraetearten nicht dieselbe.**

    Ohne Fuehlerwert heizt die Zone nicht. Schweigt nur das Relais, sind
    Soll und Ist da und unbekannt ist allein der Schaltzustand. Beides in
    einen Satz zu fassen hiesse, einen der Faelle falsch zu beschreiben —
    und eine Mail, die „wird nicht geheizt" sagt, wenn vielleicht geheizt
    wird, ist die Sorte, der man nach dem zweiten Mal nicht mehr glaubt.
    """
    text = relais_zone_melder.nachricht_alarm(
        _beurteile(alter_min=5, relais_alter_min=40), zeitzone="Europe/Vienna"
    )

    assert "wird gerade nicht geheizt" not in text
    assert "Schaltzustand" in text
    assert "108 Panel" in text
    assert "Hat das Panel Strom?" in text


def test_bei_beiden_stummen_geraeten_steht_beides_in_einer_mail() -> None:
    """Eine Zone, ein Vorgang, eine Mail (Paragraph 5.79).

    Und der Hinweis, der die Diagnose spart: schweigen beide zugleich,
    ist der Weg verdaechtig und nicht das Geraet.
    """
    text = relais_zone_melder.nachricht_alarm(
        _beurteile(alter_min=40, relais_alter_min=45), zeitzone="Europe/Vienna"
    )

    assert "056 Eingang" in text
    assert "AUCH DAS RELAIS SCHWEIGT" in text
    assert "108 Panel" in text
    assert "Gateway" in text


def test_auch_die_zone_ohne_fuehler_nennt_ein_stummes_relais() -> None:
    """Der schwerere Mangel verdeckt den zweiten nicht.

    Ohne Fuehler heizt die Zone nie — das ist der Grund. Schweigt
    zusaetzlich das Relais, gehoert es in dieselbe Mail: wer die
    Zuordnung nachtraegt und dann auf ein stummes Panel trifft, hat zwei
    Wege gemacht.
    """
    text = relais_zone_melder.nachricht_alarm(
        _beurteile(alter_min=None, fuehler=(), relais_alter_min=40),
        zeitzone="Europe/Vienna",
    )

    assert "kein Thermostat" in text
    assert "AUCH DAS RELAIS SCHWEIGT" in text


# ---------------------------------------------------------------------------
# Der Lesepfad aus der Datenbank
# ---------------------------------------------------------------------------


async def test_stummes_relais_wird_in_der_datenbank_gefunden(maker: Any) -> None:
    """Ende zu Ende: Fuehler frisch, Relais seit 40 Minuten still."""
    ids = await _baue(maker, fuehler_alter_min=5, relais_alter_min=40)
    try:
        async with maker() as session:
            befund = _eigene(
                await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN),
                ids,
            )
        assert befund.grund == relais_zone_melder.GRUND_RELAIS_STUMM
        assert befund.relais == ("Panel",)
        assert befund.relais_alter_min is not None
        assert befund.relais_alter_min >= GRENZE_MIN
    finally:
        await _raeum_auf(maker, ids)


async def test_eine_meldung_ohne_schaltzustand_ist_trotzdem_ein_lebenszeichen(
    maker: Any,
) -> None:
    """Gezaehlt wird „gehoert", nicht „geschaltet".

    Eine Zeile ohne ``relay_on`` — etwa eine reine Befehlsantwort — sagt
    nichts darueber, was am Relais gilt. Dass es **sendet**, sagt sie
    sehr wohl. Die Frage „welcher Zustand gilt" steht im Waechter und
    filtert dort sehr wohl auf ``relay_on``.
    """
    ids = await _baue(maker, fuehler_alter_min=5, relais_alter_min=40)
    try:
        async with maker() as session:
            session.add(
                RelayReading(
                    device_id=ids.relais_id,
                    time=datetime.now(tz=UTC) - timedelta(minutes=2),
                    relay_on=None,
                    power_w=None,
                )
            )
            await session.commit()
        async with maker() as session:
            befund = _eigene(
                await relais_zone_melder.lies_relais_zonen(session, grenze_min=GRENZE_MIN),
                ids,
            )
        assert befund.grund is None, "die Zone ist zu hoeren"
        assert befund.relais_stumm is False
    finally:
        await _raeum_auf(maker, ids)


async def test_das_audit_haelt_fest_wer_geschwiegen_hat(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Ohne diese Liste bleibt im Audit nur „die Zone war stumm".

    Wer spaeter nachliest, muss sehen, **welches** Geraet — sonst ist der
    Eintrag eine Behauptung ohne Zahlen (Paragraph 5.68).
    """
    ids = await _baue(maker, fuehler_alter_min=5, relais_alter_min=40)
    try:
        await funk_tasks._run_relais_zone()
        async with maker() as session:
            zeile = (
                await session.execute(
                    text(
                        "SELECT new_value FROM business_audit "
                        "WHERE target_type = 'heating_zone' AND target_id = :z "
                        "ORDER BY ts DESC, id DESC LIMIT 1"
                    ),
                    {"z": ids.zone_id},
                )
            ).scalar_one()
        assert zeile["grund"] == relais_zone_melder.GRUND_RELAIS_STUMM
        assert zeile["relais_stumm"] is True
        assert zeile["schweigende_geraete"] == ["Panel"]
        assert zeile["relais_alter_min"] >= GRENZE_MIN
    finally:
        await _raeum_auf(maker, ids)


async def test_eine_episode_unter_dem_alten_namen_laeuft_weiter(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """**Die Luecke, die Mutationsprobe M10 gefunden hat.**

    Bis zum 14.11.2026 hiess die Alarm-Marke
    ``RELAIS_ZONE_FUEHLER_STUMM``. Eine Episode, die beim Deploy offen
    ist, traegt noch diesen Namen. Liest der Melder nur den neuen, sieht
    er keine laufende Episode — und schickt fuer denselben Vorgang eine
    zweite Alarm-Mail.

    Ein Melder, der beim Umbenennen seiner eigenen Marken Fehlalarm gibt,
    ist die Sorte, die man nach einer Woche ueberliest (Paragraph 5.79).
    """
    ids = await _baue(maker, fuehler_alter_min=45)
    try:
        async with maker() as session:
            await session.execute(
                text(
                    "INSERT INTO business_audit (ts, user_id, action, target_type, "
                    "target_id, old_value, new_value) VALUES "
                    "(now(), NULL, :a, 'heating_zone', :z, NULL, '{}'::jsonb)"
                ),
                {"a": funk_tasks.AUDIT_ALTE_NAMEN[0], "z": ids.zone_id},
            )
            await session.commit()

        ergebnis = await funk_tasks._run_relais_zone()

        aktionen = await _audit_aktionen(maker, ids.zone_id)
        assert aktionen == [funk_tasks.AUDIT_ALTE_NAMEN[0]], (
            f"es haette keine zweite Alarm-Zeile geben duerfen: {aktionen}"
        )
        assert all(a["zone_id"] != ids.zone_id for a in ergebnis["aktionen"])
        assert kein_mailversand == []
    finally:
        await _raeum_auf(maker, ids)


async def test_eine_entwarnung_unter_dem_alten_namen_beendet_die_episode(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Die Gegenprobe: der alte **Entwarnungs**-Name zaehlt nicht als offen.

    Sonst waere jede vor dem 14.11. beendete Episode wieder offen, und
    die erste stille Zone bekaeme eine Entwarnung fuer einen Alarm, den
    niemand erhalten hat.
    """
    ids = await _baue(maker, fuehler_alter_min=5)
    try:
        async with maker() as session:
            await session.execute(
                text(
                    "INSERT INTO business_audit (ts, user_id, action, target_type, "
                    "target_id, old_value, new_value) VALUES "
                    "(now(), NULL, :a, 'heating_zone', :z, NULL, '{}'::jsonb)"
                ),
                {"a": funk_tasks.AUDIT_ALTE_NAMEN[1], "z": ids.zone_id},
            )
            await session.commit()

        await funk_tasks._run_relais_zone()

        aktionen = await _audit_aktionen(maker, ids.zone_id)
        assert aktionen == [funk_tasks.AUDIT_ALTE_NAMEN[1]], (
            f"eine beendete Episode wurde wieder aufgenommen: {aktionen}"
        )
        assert kein_mailversand == []
    finally:
        await _raeum_auf(maker, ids)
