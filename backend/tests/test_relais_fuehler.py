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
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.services import relais_fuehler
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
    now: datetime | None = None,
) -> relais_fuehler.ZonenBefund:
    jetzt = now or datetime(2026, 11, 12, 20, 0, 0, tzinfo=UTC)
    letzte = None if alter_min is None else jetzt - timedelta(minutes=alter_min)
    return relais_fuehler.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=fuehler,
        letzte_meldung=letzte,
        relais_in_betrieb=1,
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
    assert befund.grund == relais_fuehler.GRUND_STUMM
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
    assert befund.grund == relais_fuehler.GRUND_STUMM
    assert befund.alter_min is None


def test_zone_ohne_fuehler_hat_einen_eigenen_grund() -> None:
    """Und er schlaegt die Stille, weil er der schwerere Mangel ist.

    Ein in Betrieb genommenes Relais ohne Fuehler kann **nie** heizen.
    Ein Waechter, der genau hier schweigt, weil es keinen Fuehler gibt,
    dessen Stille er messen koennte, waere der naechste Melder, der dann
    nichts sagt, wenn es am meisten zaehlt (§5.79).
    """
    befund = _beurteile(alter_min=1, fuehler=())
    assert befund.grund == relais_fuehler.GRUND_KEIN_FUEHLER
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
    noch_still = relais_fuehler.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=LETZTE_MELDUNG_056,
        relais_in_betrieb=1,
        now=LETZTE_MELDUNG_056 + timedelta(minutes=GRENZE_MIN),
        grenze_min=GRENZE_MIN,
    )
    assert noch_still.grund is None, "30 Minuten duerfen noch nicht melden"

    meldet = relais_fuehler.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=LETZTE_MELDUNG_056,
        relais_in_betrieb=1,
        now=LETZTE_MELDUNG_056 + timedelta(minutes=GRENZE_MIN + 1),
        grenze_min=GRENZE_MIN,
    )
    assert meldet.stumm, "31 Minuten muessen melden"
    assert meldet.alter_min == GRENZE_MIN + 1

    # Und zur Mitte der Luecke, wo der Betreiber nichts erfahren hat.
    mitte = relais_fuehler.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=LETZTE_MELDUNG_056,
        relais_in_betrieb=1,
        now=datetime(2026, 11, 12, 21, 0, 0, tzinfo=UTC),
        grenze_min=GRENZE_MIN,
    )
    assert mitte.alter_min == 438, f"die Luecke war {mitte.alter_min} Minuten"


def test_nach_der_rueckkehr_ist_es_wieder_in_ordnung() -> None:
    """Die Entwarnung braucht genau das: der Zustand kippt zurueck."""
    befund = relais_fuehler.beurteile(
        zone_id=299,
        zone_name="Eingang",
        ort="Rezeption",
        fuehler=("056 Eingang",),
        letzte_meldung=ERSTE_DANACH_056,
        relais_in_betrieb=1,
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
    text_ = relais_fuehler.nachricht_alarm(befund, zeitzone="Europe/Vienna")

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
    text_ = relais_fuehler.nachricht_alarm(befund, zeitzone="Europe/Vienna")
    assert "kein Thermostat" in text_
    assert "Minuten" not in text_, "ohne Fuehler darf keine Minutenzahl im Text stehen"
    assert "Thermostat dieser Zone zuordnen" in text_
    assert "kein Thermostat" in relais_fuehler.betreff_alarm(befund)


def test_die_entwarnung_verspricht_nicht_zu_viel() -> None:
    """Sie sagt „liefert wieder", nicht „ist warm" (§5.79)."""
    befund = _beurteile(alter_min=1)
    text_ = relais_fuehler.nachricht_entwarnung(befund, zeitzone="Europe/Vienna")
    assert "wieder" in text_
    assert "sagt diese Meldung nicht" in text_
    assert "Rezeption" in relais_fuehler.betreff_entwarnung(befund)


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
) -> Aufbau:
    """Ein Zimmer mit einer Zone, einem Relais und (optional) einem Fuehler."""
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


def _eigene(befunde: list[relais_fuehler.ZonenBefund], ids: Aufbau) -> relais_fuehler.ZonenBefund:
    """Nur der eigene Aufbau. Andere Zonen des Hauses zaehlen nicht mit (§5.39)."""
    treffer = [b for b in befunde if b.zone_id == ids.zone_id]
    assert len(treffer) == 1, f"die eigene Zone wurde nicht genau einmal gefunden: {befunde}"
    return treffer[0]


async def test_frischer_fuehler_erzeugt_keinen_befund(maker: Any) -> None:
    ids = await _baue(maker, fuehler_alter_min=5)
    try:
        async with maker() as session:
            befunde = await relais_fuehler.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        assert not _eigene(befunde, ids).stumm
    finally:
        await _raeum_auf(maker, ids)


async def test_stummer_fuehler_wird_gefunden(maker: Any) -> None:
    ids = await _baue(maker, fuehler_alter_min=45)
    try:
        async with maker() as session:
            befunde = await relais_fuehler.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        befund = _eigene(befunde, ids)
        assert befund.grund == relais_fuehler.GRUND_STUMM
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
            befunde = await relais_fuehler.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
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
            befunde = await relais_fuehler.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        assert all(b.zone_id != ids.zone_id for b in befunde)
    finally:
        await _raeum_auf(maker, ids)


async def test_zone_ohne_fuehler_wird_gemeldet(maker: Any) -> None:
    ids = await _baue(maker, mit_fuehler=False)
    try:
        async with maker() as session:
            befunde = await relais_fuehler.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        befund = _eigene(befunde, ids)
        assert befund.grund == relais_fuehler.GRUND_KEIN_FUEHLER
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
            befunde = await relais_fuehler.lies_relais_zonen(session, grenze_min=GRENZE_MIN)
        befund = _eigene(befunde, ids)
        assert befund.grund == relais_fuehler.GRUND_STUMM, (
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
                    action=funk_tasks.AUDIT_FUEHLER_STUMM,
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

        assert aktion_eins == funk_tasks.AUDIT_FUEHLER_STUMM
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
        erst = await funk_tasks._run_relais_fuehler()
        assert erst.get("uebersprungen") != "totalausfall", (
            "der Pruefstand hat keine frischen hausweiten Meldungen"
        )
        assert erst["zonen_stumm"] >= 1

        zweit = await funk_tasks._run_relais_fuehler()

        aktionen = await _audit_aktionen(maker, ids.zone_id)
        assert aktionen == [funk_tasks.AUDIT_FUEHLER_STUMM], (
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
        await funk_tasks._run_relais_fuehler()

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

        await funk_tasks._run_relais_fuehler()

        aktionen = await _audit_aktionen(maker, ids.zone_id)
        assert aktionen == [
            funk_tasks.AUDIT_FUEHLER_STUMM,
            funk_tasks.AUDIT_FUEHLER_STUMM_ENDE,
        ], f"Alarm und Entwarnung fehlen oder stehen falsch: {aktionen}"
    finally:
        await _raeum_auf(maker, ids)


async def test_ohne_vorherigen_alarm_keine_entwarnung(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Eine Entwarnung ueber nichts ist eine Mail ueber nichts."""
    ids = await _baue(maker, fuehler_alter_min=5)
    try:
        await funk_tasks._run_relais_fuehler()
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
        ergebnis = await funk_tasks._run_relais_fuehler()
        assert ergebnis.get("uebersprungen") == "totalausfall"
        assert await _audit_aktionen(maker, ids.zone_id) == [], (
            "bei hausweitem Ausfall darf keine Zonen-Zeile entstehen"
        )
    finally:
        await _raeum_auf(maker, ids)
