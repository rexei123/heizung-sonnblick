"""Der Provisionierungs-Auftrag im Hintergrund (01.11.2026).

**Der Anlass.** Bis zum 01.11.2026 schickte der Endpunkt die fuenf
Downlinks selbst. Mit je 15 Sekunden Pause sind das rund 75 Sekunden, und
um 10:26 brach die Oberflaeche nach etwa 30 ab (``signal is aborted
without reason``). Das Backend lief weiter und hat alles gesendet — die
Antwort auf ``0x5A`` kam um 10:28:28, beide Ruecklesungen stehen seither
auf bestaetigt.

**Der Handgriff war also erfolgreich und sah wie ein Fehlschlag aus.** Das
ist die teuerste Sorte Rueckmeldung: der naechste Schritt ist ein zweiter
Versuch, und zwei Provisionierungen gleichzeitig waeren zehn Downlinks
ohne Pause — genau der Zustand, gegen den die Pause gebaut ist.

Diese Datei prueft den **Auftrag**. Dass der Endpunkt sofort zurueckkehrt
und nur anstoesst, steht in ``test_api_relays`` — und dort wird die
**Dauer** gemessen, nicht die Abwesenheit eines ``sleep``.

DB-Tests; skip ohne ``TEST_DATABASE_URL`` (§5.50, lokal gelaufen).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.models.business_audit import BusinessAudit
from heizung.models.device import Device
from heizung.models.enums import DeviceKind, DeviceVendor
from heizung.tasks import relay_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "t24pv"

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def relais_id() -> AsyncIterator[int]:
    """Ein Relais in der Datenbank, **committet**.

    Der Auftrag oeffnet seine eigene Sitzung (``_task_session``, eigene
    Engine je Task — §5.14). Ein nur geflushtes Geraet saehe er nicht, und
    der Test waere gruen, weil der Auftrag „kein Relais" meldet (§5.87).
    """
    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    dev_eui = f"beef{uuid.uuid4().hex[:12]}"
    async with maker() as session:
        geraet = Device(
            dev_eui=dev_eui,
            kind=DeviceKind.RELAY,
            vendor=DeviceVendor.MCLIMATE,
            model="16ASPM",
            label=f"{PREFIX}-{uuid.uuid4().hex[:4]}",
            health_state="healthy",
        )
        session.add(geraet)
        await session.commit()
        geraet_id = geraet.id
    try:
        yield geraet_id
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM business_audit WHERE target_type = 'device' AND target_id = :i"),
                {"i": geraet_id},
            )
            await session.execute(text("DELETE FROM device WHERE id = :i"), {"i": geraet_id})
            await session.commit()
        await engine.dispose()


@pytest.fixture
def mitschnitt(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Downlinks und Pausen mitschreiben, ohne MQTT und ohne zu warten."""
    protokoll: dict[str, list[Any]] = {"befehle": [], "pausen": [], "beendet": []}

    def _sender(name: str) -> Any:
        async def _f(dev_eui: str, *args: Any, **kwargs: Any) -> str:
            protokoll["befehle"].append(name)
            return "topic"

        return _f

    for name in (
        "frage_version",
        "setze_zustand_nach_stromrueckkehr",
        "setze_zustand_nach_ueberhitzung",
        "frage_zustand_nach_stromrueckkehr",
        "frage_zustand_nach_ueberhitzung",
    ):
        monkeypatch.setattr(relay_tasks.relay_adapter, name, _sender(name))

    async def _schlaf(dauer: float) -> None:
        protokoll["pausen"].append(dauer)

    monkeypatch.setattr(relay_tasks.asyncio, "sleep", _schlaf)
    monkeypatch.setattr(
        relay_tasks.provision_lauf, "beende", lambda d: protokoll["beendet"].append(d)
    )
    return protokoll


@pytest.mark.asyncio
async def test_fuenf_befehle_mit_vier_pausen(
    relais_id: int, mitschnitt: dict[str, list[Any]]
) -> None:
    """Version, setzen, setzen, lesen, lesen — in dieser Reihenfolge.

    Die Version steht vorn, weil sie unabhaengig ist und das Tor in
    ``nimm_in_betrieb`` sie braucht. Erst beide Werte setzen, dann beide
    abfragen, damit die Antworten einen zusammengehoerenden Stand
    beschreiben.
    """
    ergebnis = await relay_tasks._provisioniere_async(relais_id, None)

    assert mitschnitt["befehle"] == [
        "frage_version",
        "setze_zustand_nach_stromrueckkehr",
        "setze_zustand_nach_ueberhitzung",
        "frage_zustand_nach_stromrueckkehr",
        "frage_zustand_nach_ueberhitzung",
    ]
    # Vier Pausen fuer fuenf Befehle: **zwischen** ihnen, nicht vor dem
    # ersten. Der erste trifft ein Geraet, das gerade nichts anderes zu
    # beantworten hat.
    assert mitschnitt["pausen"] == [15, 15, 15, 15]
    assert ergebnis["fehler"] is None
    assert len(ergebnis["gesendet"]) == 5
    # Die Markierung ist geloescht — sonst waere das Relais bis zum Ablauf
    # der TTL drei Minuten lang ein 409.
    assert mitschnitt["beendet"] == [relais_id]


@pytest.mark.asyncio
async def test_das_audit_schreibt_der_auftrag_und_erst_am_ende(
    relais_id: int, mitschnitt: dict[str, list[Any]]
) -> None:
    """``gesendet`` ist eine Aussage darueber, was hinausgegangen ist.

    Der Endpunkt schreibt deshalb **kein** Audit mehr: beim Zurueckkehren
    ist noch nichts hinaus, und ein Eintrag dort haette behauptet, was
    noch nicht geschehen war (§5.68).
    """
    await relay_tasks._provisioniere_async(relais_id, None)

    engine = create_async_engine(TEST_DB_URL or "", poolclass=None)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as pruefung:
            eintraege = list(
                (
                    await pruefung.execute(
                        select(BusinessAudit)
                        .where(BusinessAudit.target_type == "device")
                        .where(BusinessAudit.target_id == relais_id)
                        .where(BusinessAudit.action == "RELAY_PROVISIONED")
                    )
                )
                .scalars()
                .all()
            )
        assert len(eintraege) == 1, "genau ein Eintrag je Lauf"
        assert len(eintraege[0].new_value["gesendet"]) == 5
        assert eintraege[0].new_value["fehler"] is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ein_fehlschlag_loescht_die_markierung_trotzdem(
    relais_id: int, mitschnitt: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonst waere das Relais drei Minuten lang gesperrt.

    Die Markierung laeuft nach ``LAUF_TTL_S`` von selbst ab — aber bis
    dahin bekaeme jeder Versuch ein 409, und der Hausmeister steht vor
    einem Geraet, das sich nicht provisionieren laesst, **weil der letzte
    Versuch gescheitert ist**. Das ist die Sorte Sperre, die man nicht
    erklaeren kann.
    """

    async def _kaputt(dev_eui: str, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("MQTT nicht erreichbar")

    monkeypatch.setattr(relay_tasks.relay_adapter, "setze_zustand_nach_ueberhitzung", _kaputt)

    ergebnis = await relay_tasks._provisioniere_async(relais_id, None)

    assert ergebnis["fehler"] is not None
    assert "RuntimeError" in ergebnis["fehler"]
    # Zwei Befehle sind hinaus, der dritte scheiterte.
    assert len(ergebnis["gesendet"]) == 2
    assert mitschnitt["beendet"] == [relais_id]


@pytest.mark.asyncio
async def test_kein_relais_kein_befehl(mitschnitt: dict[str, list[Any]]) -> None:
    """Ein Thermostat laeuft nicht versehentlich durch diesen Pfad.

    Der Endpunkt prueft es schon (404 bei einem Nicht-Relais), aber der
    Auftrag bekommt nur eine Nummer — und eine Nummer kann zwischen
    Anstoss und Lauf ein anderes Geraet bezeichnen, wenn jemand
    ausmustert und neu anlegt.
    """
    ergebnis = await relay_tasks._provisioniere_async(10_000_000, None)

    assert ergebnis["gesendet"] == []
    assert mitschnitt["befehle"] == []


@pytest.mark.asyncio
async def test_ohne_pause_wird_nicht_geschlafen(
    relais_id: int, mitschnitt: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``relay_provision_pause_s = 0`` stellt das alte Verhalten her.

    Die 15 Sekunden sind eine **Annahme ueber fremde Hardware** und keine
    Eigenschaft unseres Systems; ``0`` muss den Rueckweg geben, sonst ist
    er nur behauptet.
    """
    from heizung.config import get_settings

    monkeypatch.setenv("RELAY_PROVISION_PAUSE_S", "0")
    get_settings.cache_clear()
    try:
        await relay_tasks._provisioniere_async(relais_id, None)
        assert mitschnitt["pausen"] == []
        assert len(mitschnitt["befehle"]) == 5
    finally:
        monkeypatch.delenv("RELAY_PROVISION_PAUSE_S", raising=False)
        get_settings.cache_clear()


def test_der_auftrag_ist_bei_celery_angemeldet() -> None:
    """Ohne Namen kein ``.delay`` — und der Endpunkt stiesse ins Leere.

    Der Name steht im Dekorator und im Aufruf; zwei Stellen, eine
    Schreibweise. Dieser Test ist der Wachposten dafuer, dass sie
    zusammenpassen, denn ein Tippfehler faellt sonst erst im Betrieb auf
    (und dann als Handgriff, der nichts tut).
    """
    assert relay_tasks.provisioniere_relais.name == "heizung.provisioniere_relais"
