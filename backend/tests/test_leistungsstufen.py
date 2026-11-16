"""``tx_power_index`` aus der ChirpStack-Geraetesitzung in unsere Datenbank.

**Der Quellcheck, der dieser Aenderung vorausging, steht hier als Test,
soweit er sich pruefen laesst.** Gemessen am 16.11.2026 am
Produktionsserver:

* ``integration.UplinkEvent`` (ChirpStack 4.17) hat 16 Felder und
  **keines** mit der Sendeleistung des Geraets. Das ist keine Luecke:
  das Gateway kann sie nicht messen.
* ``internal.DeviceSession`` hat sie in Feld **24**. Alle **109**
  Geraete im Haus hatten eine Sitzung (159 bis 658 Byte), alle 109
  liessen sich mit dem Parser aus ``services/chirpstack_session`` lesen,
  **0** Parse-Fehler.
* Die Verteilung daraus — 0:16, 1:1, 2:5, 3:7, 4:11, 5:6, 6:4, 7:59 —
  gegen die aus dem Container-Protokoll derselben Stunde: 0:15, 1:1,
  2:5, 3:5, 4:10, 5:6, 6:3, 7:**10**. Das Protokoll kannte 55 Geraete,
  die Sitzung 109. Die Luecke sitzt bei den eingeschwungenen Geraeten
  auf Stufe 7 — genau denen, ueber die ADR nichts mehr schreibt.
* Gegenprobe, dass der Parser das **richtige** Feld liest: Feld 25
  (``dr``) ergab 108 Geraete auf DR5 und **eines auf DR3**. Dass genau
  ein Geraet auf DR3 haengt, steht unabhaengig davon in RUNBOOK §10av
  (Relais 108, nach dem Rueckzug des ADR-Plugins).

Die Zahlen selbst sind nicht nachpruefbar ohne den Server; nachpruefbar
ist der Parser, und das ist, was hier steht.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.celery_app import app as celery_app
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.services import chirpstack_session
from heizung.services.chirpstack_session import (
    FELD_TX_POWER_INDEX,
    Leseergebnis,
    SitzungUnlesbarError,
    leistungsstufe,
)
from heizung.tasks import leistungsstufen_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
PREFIX = "t-txpi"


# ---------------------------------------------------------------------------
# Protobuf-Bytes bauen (nur fuer den Test; der Parser liest, er schreibt nie)
# ---------------------------------------------------------------------------


def _varint(wert: int) -> bytes:
    daten = bytearray()
    while True:
        byte = wert & 0x7F
        wert >>= 7
        if wert:
            daten.append(byte | 0x80)
        else:
            daten.append(byte)
            return bytes(daten)


def feld_varint(nummer: int, wert: int) -> bytes:
    return _varint(nummer << 3) + _varint(wert)


def feld_bytes(nummer: int, inhalt: bytes) -> bytes:
    return _varint(nummer << 3 | 2) + _varint(len(inhalt)) + inhalt


#: Nachgebaute Sitzung in der Feldreihenfolge, die ChirpStack schreibt:
#: ein laengenpraefixiertes Feld vorn (bei ChirpStack der ``dev_addr``
#: und das Schluesselmaterial), dann die Varints 23/24/25.
def sitzung(tx_power_index: int | None, *, dr: int = 5, nb_trans: int = 1) -> bytes:
    teile = [feld_bytes(1, b"\x01\x02\x03\x04"), feld_varint(23, nb_trans)]
    if tx_power_index is not None:
        teile.append(feld_varint(FELD_TX_POWER_INDEX, tx_power_index))
    teile.append(feld_varint(25, dr))
    return b"".join(teile)


# ---------------------------------------------------------------------------
# Der Parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stufe", [0, 1, 2, 3, 4, 5, 6, 7, 15])
def test_stufe_wird_gelesen(stufe: int) -> None:
    assert leistungsstufe(sitzung(stufe)) == stufe


def test_fehlendes_feld_heisst_stufe_null() -> None:
    """Protobuf laesst den Standardwert weg — 0 ist ein echter Wert.

    Das ist die Stelle, an der ein naiver Leser still falsch liegt: wer
    „Feld fehlt" als „unbekannt" liest, verliert genau die Geraete, die
    mit **voller** Leistung senden. Am 16.11.2026 waren das 16 von 109,
    und das Container-Protokoll bestaetigt sie als
    ``tx_power_index=0``.
    """
    assert leistungsstufe(sitzung(None)) == 0


def test_der_schluessel_im_inneren_eines_feldes_zaehlt_nicht() -> None:
    """Gelesen wird die oberste Ebene, nicht gesucht.

    Die Bytefolge des Schluessels von Feld 24 (``0xC0 0x01``) kann im
    Inneren eines laengenpraefixierten Feldes vorkommen — im
    Schluesselmaterial einer echten Sitzung ist das eine Frage der Zeit.
    Ein Parser, der die Bytes durchsucht statt die Felder abzulaufen,
    liest dort eine Stufe, die niemand gesendet hat.
    """
    falle = feld_bytes(1, feld_varint(FELD_TX_POWER_INDEX, 7) + b"\xff\x00")
    roh = falle + feld_varint(FELD_TX_POWER_INDEX, 2)
    assert leistungsstufe(roh) == 2

    # Und ohne echtes Feld 24: 0, nicht die 7 aus dem Inneren.
    assert leistungsstufe(falle) == 0


def test_stufe_ueber_funfzehn_ist_unlesbar() -> None:
    """Ein Wert jenseits von 4 Bit heisst: falsches Feld.

    ``LinkADRReq`` traegt die Stufe in vier Bit. Kommt mehr heraus, hat
    sich das interne Schema von ChirpStack verschoben — dann ist ein
    Abbruch richtig und ein geschriebener Wert falsch.
    """
    with pytest.raises(SitzungUnlesbarError):
        leistungsstufe(sitzung(16))


def test_abgeschnittene_bytes_vor_dem_feld_sind_unlesbar() -> None:
    """Bricht der Aufbau ab, **bevor** Feld 24 kommt, gibt es keine Antwort.

    Keine 0, die wie „volle Leistung" aussieht — eine Ausnahme. Der
    Unterschied ist der ganze Punkt der Spalte: ``NULL`` heisst „nicht
    gelesen", 0 heisst „volle Leistung".
    """
    roh = feld_bytes(1, b"abcd") + _varint(23 << 3) + b"\x80"
    with pytest.raises(SitzungUnlesbarError):
        leistungsstufe(roh)


def test_nach_dem_feld_wird_nicht_mehr_gelesen() -> None:
    """Gefunden ist gefunden — der Rest der Sitzung bleibt ungelesen.

    Das ist Absicht und festgehalten, damit niemand es fuer einen
    Fluechtigkeitsfehler haelt: was hinter Feld 24 steht, braucht dieses
    Modul nicht, und je weniger es von einer Nachricht mit
    Schluesselmaterial anfasst, desto besser. Ein beschaedigtes Ende
    faellt damit nicht auf — der gelesene Wert ist davon unberuehrt, und
    seine Plausibilitaet prueft der Wertebereich.
    """
    assert leistungsstufe(sitzung(4)[:-1] + b"\x80") == 4


def test_keine_bytes_in_der_fehlermeldung() -> None:
    """In derselben Nachricht stehen ``app_s_key`` und ``nwk_s_enc_key``.

    Eine Ausnahme, die den Blob mitnimmt, landet im Worker-Log, in
    Sentry, in einem Ticket. Die Meldung nennt deshalb eine Position und
    einen Grund, nie Inhalt.
    """
    geheim = b"\xde\xad\xbe\xef" * 4
    roh = feld_bytes(1, geheim) + _varint(FELD_TX_POWER_INDEX << 3) + b"\x80"
    with pytest.raises(SitzungUnlesbarError) as fehler:
        leistungsstufe(roh)
    meldung = str(fehler.value)
    assert "deadbeef" not in meldung.lower()
    assert geheim.hex() not in meldung.lower()
    assert repr(geheim) not in meldung


# ---------------------------------------------------------------------------
# Der Task ohne Zugang
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ohne_dsn_wird_nicht_gelesen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auslieferungszustand: kein Zugang, kein Lauf, kein geschriebener Wert.

    Der Zugang zu ChirpStacks Datenbank ist eine Server-Aenderung
    (§10bf) und gehoert dem Betreiber. Bis dahin darf der Task nicht
    stillschweigend scheitern, sondern gar nicht erst lesen — sonst
    steht stuendlich eine Verbindungsfehler-Spur im Log, und die liest
    nach dem zweiten Mal niemand mehr (§5.79).
    """

    async def nie_aufrufen(dsn: str) -> Leseergebnis:
        raise AssertionError(f"ohne DSN nicht lesen, bekam {dsn!r}")

    class OhneZugang:
        chirpstack_session_db_url = "   "  # auch Leerraum ist kein Zugang
        database_url = "postgresql+asyncpg://nie:nie@127.0.0.1:1/nie"

    monkeypatch.setattr(chirpstack_session, "lies_aus_chirpstack", nie_aufrufen)
    # Nicht ``get_settings.cache_clear()``: der Cache ist prozessweit, und
    # ein geleerter Cache trifft die Tests, die danach laufen.
    monkeypatch.setattr(leistungsstufen_tasks, "get_settings", OhneZugang)

    assert await leistungsstufen_tasks._run() == {"stand": "nicht_konfiguriert"}


def test_task_laeuft_auch_wirklich() -> None:
    """Registriert **und** im Beat-Plan.

    Ein Task, der im ``include`` fehlt, ist unbekannt; einer ohne
    Beat-Eintrag wird nie gerufen. Beides faellt im Betrieb nur dadurch
    auf, dass eine Spalte leer bleibt — also gar nicht.
    """
    assert "heizung.sync_leistungsstufen" in celery_app.tasks
    plan = celery_app.conf.beat_schedule["leistungsstufen-hourly"]
    assert plan["task"] == "heizung.sync_leistungsstufen"


# ---------------------------------------------------------------------------
# Die Uebernahme in unsere Spalten (braucht Postgres)
# ---------------------------------------------------------------------------

db_test = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
)


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[Any]:
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(setup_engine: Any) -> AsyncIterator[Any]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as s:
        try:
            yield s
        finally:
            await s.rollback()


async def _geraet(session: Any, eui: str, *, retired: bool = False) -> Device:
    geraet = Device(
        dev_eui=eui,
        kind=DeviceKind.THERMOSTAT,
        vendor=DeviceVendor.MCLIMATE,
        model="vicki",
        label=f"{PREFIX}-{eui[:6]}",
        health_state="healthy",
        retired_at=datetime.now(UTC) if retired else None,
    )
    session.add(geraet)
    await session.flush()
    return geraet


@db_test
@pytest.mark.asyncio
async def test_uebernahme_schreibt_stufe_und_zeitstempel(session: Any) -> None:
    eui = f"dead{uuid.uuid4().hex[:12]}"
    geraet = await _geraet(session, eui)
    jetzt = datetime.now(UTC)

    bericht = await chirpstack_session.uebernehme(session, Leseergebnis(stufen={eui: 6}), jetzt)

    await session.refresh(geraet)
    assert geraet.tx_power_index == 6
    assert geraet.tx_power_index_at == jetzt
    assert (bericht.gelesen, bericht.zugeordnet, bericht.unbekannt) == (1, 1, 0)


@db_test
@pytest.mark.asyncio
async def test_stufe_null_wird_geschrieben_nicht_uebersprungen(session: Any) -> None:
    """0 ist volle Sendeleistung, nicht „kein Wert".

    Ein ``if stufe:`` an der falschen Stelle wuerde genau die 16 Geraete
    vom 16.11.2026 auf ``NULL`` stehen lassen — und ``NULL`` heisst in
    dieser Spalte „noch nie gelesen".
    """
    eui = f"dead{uuid.uuid4().hex[:12]}"
    geraet = await _geraet(session, eui)

    await chirpstack_session.uebernehme(session, Leseergebnis(stufen={eui: 0}), datetime.now(UTC))

    await session.refresh(geraet)
    assert geraet.tx_power_index == 0
    assert geraet.tx_power_index_at is not None


@db_test
@pytest.mark.asyncio
async def test_grossschreibung_trifft_dasselbe_geraet(session: Any) -> None:
    """ChirpStack liefert die DevEUI klein, unsere Zeilen sind gemischt.

    ``pair_devices`` und der Hardware-Import haben ueber die Jahre beides
    geschrieben. Ein Vergleich ohne ``lower()`` wuerde einen Teil des
    Bestands stumm nicht treffen — und „nicht getroffen" sieht aus wie
    „kein Wert".
    """
    eui = f"DEAD{uuid.uuid4().hex[:12].upper()}"
    geraet = await _geraet(session, eui)

    bericht = await chirpstack_session.uebernehme(
        session, Leseergebnis(stufen={eui.lower(): 3}), datetime.now(UTC)
    )

    await session.refresh(geraet)
    assert geraet.tx_power_index == 3
    assert bericht.zugeordnet == 1


@db_test
@pytest.mark.asyncio
async def test_zurueckgezogenes_geraet_bekommt_nichts(session: Any) -> None:
    """``retired_at`` ist die Grenze fuer „aktiv" (AE-57).

    ChirpStack kennt ausgebaute Geraete weiter; ihre Sitzung altert dort
    vor sich hin. Ein Wert an einer zurueckgezogenen Zeile waere eine
    frische Zahl zu einem Geraet, das nicht mehr im Haus haengt.
    """
    eui = f"dead{uuid.uuid4().hex[:12]}"
    geraet = await _geraet(session, eui, retired=True)

    bericht = await chirpstack_session.uebernehme(
        session, Leseergebnis(stufen={eui: 7}), datetime.now(UTC)
    )

    await session.refresh(geraet)
    assert geraet.tx_power_index is None
    assert (bericht.zugeordnet, bericht.unbekannt) == (0, 1)


@db_test
@pytest.mark.asyncio
async def test_unlesbare_sitzung_zaehlt_und_blockiert_nicht(session: Any) -> None:
    """Ein Geraet mit kaputter Sitzung darf die anderen 108 nicht mitnehmen."""
    eui = f"dead{uuid.uuid4().hex[:12]}"
    geraet = await _geraet(session, eui)

    bericht = await chirpstack_session.uebernehme(
        session,
        Leseergebnis(stufen={eui: 2}, unlesbar=["cafe0000cafe0000"]),
        datetime.now(UTC),
    )

    await session.refresh(geraet)
    assert geraet.tx_power_index == 2
    assert bericht.unlesbar == 1


@db_test
@pytest.mark.asyncio
async def test_ohne_treffer_wird_nichts_geschrieben(session: Any) -> None:
    eui = f"dead{uuid.uuid4().hex[:12]}"
    geraet = await _geraet(session, eui)

    bericht = await chirpstack_session.uebernehme(
        session, Leseergebnis(stufen={}, unlesbar=[eui]), datetime.now(UTC)
    )

    await session.refresh(geraet)
    assert geraet.tx_power_index is None
    assert bericht == chirpstack_session.Uebernahmebericht(unlesbar=1)


@db_test
@pytest.mark.asyncio
async def test_spalten_sind_in_der_datenbank(session: Any) -> None:
    """Migration 0040 ist eingespielt — sonst laeuft der Task gegen eine Wand.

    Der Test liest die Spalten ueber das Modell; faellt er aus, fehlt die
    Migration in der Testdatenbank und nicht die Logik.
    """
    eui = f"dead{uuid.uuid4().hex[:12]}"
    await _geraet(session, eui)
    zeilen = (
        await session.execute(
            select(Device.tx_power_index, Device.tx_power_index_at).where(Device.dev_eui == eui)
        )
    ).all()
    assert zeilen == [(None, None)]
