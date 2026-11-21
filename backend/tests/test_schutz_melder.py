"""Meldung, wenn ein Relais sich selbst abgeschaltet hat (21.11.2026).

**Der Befund, der diese Datei nötig gemacht hat.** Loest der Schutz eines
Relais aus, sperrt die Steuerung das Geraet (S4) und der Bereich heizt
nicht mehr — gemeldet wurde das bis zum 21.11.2026 **nur** als Zeile im
Protokoll des Containers (``health_alerts.emit_relay_protection_alert``).
Die Sperre haelt, bis ein Administrator sie aufhebt; bis dahin erfuhr
niemand davon.

Die Urteile hier brauchen keine Datenbank, der Lesepfad und die Episode
schon. **Kein ``pytestmark`` auf Modulebene**: sonst prueft ein Lauf ohne
``TEST_DATABASE_URL`` gar nichts mehr (Paragraph 5.55).
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
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor, HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.services import schutz_melder
from heizung.tasks import schutz_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "sch"

AUSGELOEST = datetime(2026, 11, 21, 5, 30, tzinfo=UTC)


def _befund(
    *,
    art: str | None = "overheating",
    label: str | None = "109 Panel",
    gehaeuse_wert: int | None = 78,
) -> schutz_melder.SchutzBefund:
    return schutz_melder.SchutzBefund(
        device_id=110,
        dev_eui="70b3d52dd3034de4",
        label=label,
        ort="139",
        zone_name="Eingang",
        art=art,
        ausgeloest_am=AUSGELOEST,
        gehaeuse_wert=gehaeuse_wert,
        gehaeuse_gemeldet_am=AUSGELOEST - timedelta(minutes=3),
    )


# ---------------------------------------------------------------------------
# Die Uebersetzung und die Texte, ohne Datenbank
# ---------------------------------------------------------------------------


def test_die_vier_schutzarten_stehen_als_wort_im_text() -> None:
    """Der Empfaenger liest „Ueberhitzung", nicht ``overheating``.

    Die Marken sind die des Codec (``data.protection``) und kommen
    unveraendert aus ``device.protection_kind``.
    """
    worte = {art: _befund(art=art).art_klartext for art in schutz_melder.SCHUTZARTEN}
    assert worte == {
        "overheating": "Ueberhitzung",
        "overvoltage": "Ueberspannung",
        "overcurrent": "Ueberstrom",
        "overpower": "Ueberlast",
    }


def test_eine_unbekannte_art_wird_genannt_und_nicht_verschluckt() -> None:
    """Ein neuer Firmware-Wert darf keine Mail kosten.

    ``relay_uplink`` sperrt auch bei unbekannter Art („Lieber eine Sperre
    zu viel"). Diese Liste ist Uebersetzung, nicht Zulassung — sonst
    waere der erste neue Wert ein Vorfall ohne Nachricht.
    """
    assert _befund(art="overfrequency_protection").art_klartext == "overfrequency_protection"


def test_ohne_art_sagt_der_text_dass_das_geraet_keine_gemeldet_hat() -> None:
    klartext = _befund(art=None).art_klartext
    assert "unbekannt" in klartext
    assert "keine Art gemeldet" in klartext


def test_der_alarmtext_sagt_zuerst_die_folge() -> None:
    text_ = schutz_melder.nachricht_alarm(_befund(), zeitzone="Europe/Vienna")
    kopf = text_.split("\n\n")[0]
    assert "109 Panel" in kopf
    assert "abgeschaltet" in kopf
    assert "heizt nicht mehr" in text_, "die Folge fuer den Bereich gehoert in den Text"
    assert "Administrator" in text_, "dass die Sperre haendisch aufgeht, muss dastehen"


def test_der_alarmtext_nennt_die_ortszeit_und_nicht_die_weltzeit() -> None:
    """Die Mail liest ein Mensch (Paragraph 5.65).

    05:30 UTC ist im November 06:30 in Wien. Steht die Weltzeit da, sucht
    der Empfaenger eine Stunde zu frueh im Protokoll.
    """
    text_ = schutz_melder.nachricht_alarm(_befund(), zeitzone="Europe/Vienna")
    assert "21.11.2026 06:30" in text_
    assert "05:30" not in text_


def test_der_alarmtext_behauptet_keine_temperatur_zum_vorfall() -> None:
    """Die Temperatur der Ausloesung speichert die Steuerung nicht.

    Sie steht im Ereignis (``0x60`` Byte 2) und nur im Protokoll. Der
    Text darf die juengste regulaere Meldung nicht als Messwert zum
    Vorfall ausgeben (Paragraph 5.68).
    """
    text_ = schutz_melder.nachricht_alarm(_befund(), zeitzone="Europe/Vienna")
    assert "juengste Meldung" in text_
    assert "speichert sie nicht" in text_


def test_ohne_gehaeusewert_steht_keine_zahl_da() -> None:
    text_ = schutz_melder.nachricht_alarm(_befund(gehaeuse_wert=None), zeitzone="Europe/Vienna")
    assert "keine Meldung" in text_


def test_die_reihenfolge_der_handgriffe_steht_der_ursache_voran() -> None:
    """Erst die Ursache, dann die Sperre — nicht umgekehrt.

    Wer zuerst entsperrt, schickt den Regler in dieselbe Lage zurueck.
    """
    text_ = schutz_melder.nachricht_alarm(_befund(), zeitzone="Europe/Vienna")
    ursache = text_.index("Ursache suchen")
    entsperren = text_.index("Sperre aufheben")
    assert ursache < entsperren


def test_der_betreff_nennt_geraet_und_art() -> None:
    assert schutz_melder.betreff_alarm(_befund()) == (
        "Heizung Sonnblick: Relais 109 Panel hat sich abgeschaltet (Ueberhitzung)"
    )


def test_ohne_etikett_nennt_der_betreff_die_dev_eui() -> None:
    assert "70b3d52dd3034de4" in schutz_melder.betreff_alarm(_befund(label=None))


# ---------------------------------------------------------------------------
# Lesepfad und Episode, gegen Postgres
# ---------------------------------------------------------------------------


class Aufbau:
    """Die Ids des Testaufbaus."""

    def __init__(self, room_id: int, zone_id: int, relais_id: int) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.relais_id = relais_id


@pytest_asyncio.fixture
async def maker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Session-Fabrik auf der Test-DB — und ``DATABASE_URL`` darauf gepinnt."""
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
    sperre: datetime | None = None,
    art: str | None = "overheating",
    in_betrieb: bool = True,
    ausgemustert: bool = False,
    gehaeuse_wert: int | None = 78,
) -> Aufbau:
    """Ein Zimmer mit Zone und einem Relais, optional mit Sperre."""
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
        # schema_constraint: room.number max 20 (Paragraph 5.49)
        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(room_id=room.id, kind=HeatingZoneKind.OTHER, name="Eingang")
        session.add(zone)
        await session.flush()

        relais = Device(
            # schema_constraint: device.dev_eui max 16 (Paragraph 5.49)
            dev_eui=f"relais00{uuid.uuid4().hex[:8]}",
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label=f"{PREFIX}-{short} Panel",
            heating_zone_id=zone.id,
            health_state="healthy",
            firmware_version="1.5",
            commissioned_at=(jetzt - timedelta(hours=1)) if in_betrieb else None,
            protection_tripped_at=sperre,
            protection_kind=art if sperre else None,
            retired_at=(jetzt - timedelta(minutes=5)) if ausgemustert else None,
        )
        session.add(relais)
        await session.flush()
        if gehaeuse_wert is not None:
            session.add(
                RelayReading(
                    device_id=relais.id,
                    time=jetzt - timedelta(minutes=3),
                    relay_on=False,
                    power_w=0,
                    internal_temperature_raw=gehaeuse_wert,
                )
            )

        ids = Aufbau(room.id, zone.id, relais.id)
        await session.commit()
    return ids


async def _raeum_auf(maker: Any, ids: Aufbau) -> None:
    async with maker() as session:
        await session.execute(
            text("DELETE FROM business_audit WHERE target_type = 'device' AND target_id = :d"),
            {"d": ids.relais_id},
        )
        await session.execute(
            text("DELETE FROM relay_reading WHERE device_id = :d"), {"d": ids.relais_id}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
        # ``room`` CASCADE raeumt die Zone, aber ``device.heating_zone_id``
        # ist nullable und wird dabei nur auf NULL gesetzt (Paragraph 5.39).
        await session.execute(text("DELETE FROM device WHERE id = :d"), {"d": ids.relais_id})
        await session.execute(
            text(
                "DELETE FROM room_type WHERE id NOT IN (SELECT room_type_id FROM room) "
                "AND name LIKE :p"
            ),
            {"p": f"{PREFIX}-%"},
        )
        await session.commit()


async def _lies(maker: Any) -> list[schutz_melder.SchutzBefund]:
    async with maker() as session:
        return await schutz_melder.lies_schutzsperren(session)


async def _audit_aktionen(maker: Any, device_id: int) -> list[str]:
    async with maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM business_audit "
                    "WHERE target_type = 'device' AND target_id = :d ORDER BY ts"
                ),
                {"d": device_id},
            )
        ).all()
    return [r[0] for r in rows]


@pytest_asyncio.fixture
def kein_mailversand(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Mitschreiber statt Versand. Die Texte haben ihre eigenen Tests."""
    betreffe: list[str] = []

    def _send(*, recipient: str | None, subject: str, body: str) -> Any:
        from heizung.services.mailer import MailResult

        betreffe.append(subject)
        return MailResult(sent=True, reason=None, detail="test")

    monkeypatch.setattr(schutz_tasks.mailer, "send_mail", _send)
    return betreffe


async def test_eine_stehende_sperre_wird_gefunden(maker: Any) -> None:
    ids = await _baue(maker, sperre=AUSGELOEST)
    try:
        treffer = [b for b in await _lies(maker) if b.device_id == ids.relais_id]
        assert len(treffer) == 1
        befund = treffer[0]
        assert befund.art == "overheating"
        assert befund.ausgeloest_am == AUSGELOEST
        assert befund.gehaeuse_wert == 78, "die juengste Meldung gehoert dazu"
        assert befund.zone_name == "Eingang"
    finally:
        await _raeum_auf(maker, ids)


async def test_ein_relais_ohne_sperre_kommt_nicht_vor(maker: Any) -> None:
    ids = await _baue(maker, sperre=None)
    try:
        assert all(b.device_id != ids.relais_id for b in await _lies(maker))
    finally:
        await _raeum_auf(maker, ids)


async def test_ein_ausgemustertes_relais_kommt_nicht_vor(maker: Any) -> None:
    """Lebenszyklus-Filter, Paragraph 5.58."""
    ids = await _baue(maker, sperre=AUSGELOEST, ausgemustert=True)
    try:
        assert all(b.device_id != ids.relais_id for b in await _lies(maker))
    finally:
        await _raeum_auf(maker, ids)


async def test_ohne_inbetriebnahme_wird_trotzdem_gemeldet(maker: Any) -> None:
    """Beim Eingangstest ist eine Ausloesung der **wichtigere** Fall.

    Der Zonen-Melder filtert auf ``darf_schalten``; hier waere das
    falsch — ein Geraet, das auf dem Tisch abschaltet, soll nicht an die
    Wand.
    """
    ids = await _baue(maker, sperre=AUSGELOEST, in_betrieb=False)
    try:
        assert any(b.device_id == ids.relais_id for b in await _lies(maker))
    finally:
        await _raeum_auf(maker, ids)


async def test_ohne_gehaeusemeldung_bleibt_der_wert_leer(maker: Any) -> None:
    ids = await _baue(maker, sperre=AUSGELOEST, gehaeuse_wert=None)
    try:
        befund = next(b for b in await _lies(maker) if b.device_id == ids.relais_id)
        assert befund.gehaeuse_wert is None
        assert befund.gehaeuse_gemeldet_am is None
    finally:
        await _raeum_auf(maker, ids)


async def test_einmal_je_ereignis_und_nicht_bei_jedem_lauf(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Die Sperre steht, bis jemand sie aufhebt — die Mail kommt einmal.

    Ohne diese Bedingung waere eine Sperre, die ueber Nacht steht, bei
    Fuenf-Minuten-Takt rund 150 Mails.
    """
    ids = await _baue(maker, sperre=AUSGELOEST)
    try:
        erst = await schutz_tasks._run_schutz()
        assert erst["sperren"] >= 1
        assert erst["gemeldet"] >= 1

        await schutz_tasks._run_schutz()
        await schutz_tasks._run_schutz()

        assert await _audit_aktionen(maker, ids.relais_id) == [
            schutz_tasks.AUDIT_SCHUTZ_GEMELDET
        ], "die Episode hat mehr als eine Zeile erzeugt"
        assert len([b for b in kein_mailversand if "abgeschaltet" in b]) == 1
    finally:
        await _raeum_auf(maker, ids)


async def test_eine_neue_ausloesung_meldet_erneut(maker: Any, kein_mailversand: list[str]) -> None:
    """**Das Ereignis ist der Zeitpunkt, nicht die Sperre.**

    Nach dem Entsperren und einer erneuten Ausloesung steht ein neuer
    ``protection_tripped_at`` — und dann muss die zweite Mail kommen.
    Haengt die Bremse an der Existenz eines Audit-Eintrags statt an
    seinem Inhalt, bleibt der zweite Vorfall stumm.
    """
    ids = await _baue(maker, sperre=AUSGELOEST)
    try:
        await schutz_tasks._run_schutz()

        async with maker() as session:
            await session.execute(
                text("UPDATE device SET protection_tripped_at = :t WHERE id = :d"),
                {"t": AUSGELOEST + timedelta(hours=4), "d": ids.relais_id},
            )
            await session.commit()

        await schutz_tasks._run_schutz()

        assert await _audit_aktionen(maker, ids.relais_id) == [
            schutz_tasks.AUDIT_SCHUTZ_GEMELDET,
            schutz_tasks.AUDIT_SCHUTZ_GEMELDET,
        ], "die zweite Ausloesung wurde nicht gemeldet"
    finally:
        await _raeum_auf(maker, ids)


async def test_ohne_sperre_bleibt_es_still(maker: Any, kein_mailversand: list[str]) -> None:
    ids = await _baue(maker, sperre=None)
    try:
        await schutz_tasks._run_schutz()
        assert await _audit_aktionen(maker, ids.relais_id) == []
    finally:
        await _raeum_auf(maker, ids)


async def test_zwei_relais_sind_zwei_vorgaenge(maker: Any, kein_mailversand: list[str]) -> None:
    """Eine gemeinsame Marke wuerde das zweite Geraet verschlucken."""
    eins = await _baue(maker, sperre=AUSGELOEST)
    zwei = await _baue(maker, sperre=AUSGELOEST + timedelta(minutes=1), art="overcurrent")
    try:
        await schutz_tasks._run_schutz()
        assert await _audit_aktionen(maker, eins.relais_id) == [schutz_tasks.AUDIT_SCHUTZ_GEMELDET]
        assert await _audit_aktionen(maker, zwei.relais_id) == [schutz_tasks.AUDIT_SCHUTZ_GEMELDET]
    finally:
        await _raeum_auf(maker, zwei)
        await _raeum_auf(maker, eins)
