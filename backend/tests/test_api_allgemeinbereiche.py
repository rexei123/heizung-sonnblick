"""Allgemeinbereiche am Endpunkt (Sprint 24d, S6).

**Warum diese Zusicherungen hier stehen und nicht beim Dienst.** Am
21.10.2026 habe ich einen ``KeyError`` auf der Ebene des ``dict`` belegt
und daraus geschlossen, die API antworte mit 500. Sie antwortete mit 422,
aus einer ganz anderen Schicht, und der Rang-Fix allein hätte nichts
behoben (§5.83). Seither gilt: eine Zusicherung über die Antwort der API
wird **an der API** geprüft.

Geprüft wird hier:

* Ein Allgemeinbereich nimmt eine Übersteuerung **ohne Belegung** an.
* Ohne Ablauf (**M6**) und über 24 Stunden (**M8**) wird sie abgewiesen.
* Ein **Gästezimmer** nimmt die Bereichs-Quelle nicht (**M22**) — AE-58
  bleibt für Gästezimmer unverändert.
* Die Rollenprüfung sitzt im Backend (**M23**).
* Der Wunschwert wird an den Grenzen des Raumtyps gekappt.
* Nach dem Ablauf gilt wieder der Plan (**Abschlusskriterium 3**).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic.config import Config
from fastapi import params
from httpx import ASGITransport
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.api.v1.overrides import create_room_override
from heizung.auth.dependencies import require_mitarbeiter
from heizung.db import get_session
from heizung.main import app
from heizung.models.enums import HeatingZoneKind, OverrideSource
from heizung.models.heating_zone import HeatingZone
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.rules.engine import evaluate_room
from heizung.schemas.manual_override import ManualOverrideCreate
from heizung.services import override_service
from heizung.services.child_lock import child_lock_state, soll_kindersicherung

DATABASE_URL = os.environ.get("DATABASE_URL")
SKIP_REASON = "DATABASE_URL nicht gesetzt - API-Tests brauchen Test-DB"
PREFIX = "t24dapi"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason=SKIP_REASON)

BETRIEB = 21
"""Der Sollwert des Pilot-Raumtyps in diesen Tests."""


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    """``alembic upgrade head`` im Thread, einmal pro Modul."""
    if not DATABASE_URL:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def setup_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(DATABASE_URL or "")
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def http_client(setup_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    sessionmaker = async_sessionmaker(setup_engine, expire_on_commit=False)

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class _Aufbau:
    """Die IDs eines Aufbaus, plus der Weg sie wieder abzuräumen."""

    def __init__(self, room_id: int, zone_id: int, room_type_id: int) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.room_type_id = room_type_id


async def _aufbauen(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    buchbar: bool,
    max_temp: int | None = None,
) -> _Aufbau:
    """Ein Zimmer mit einer Zone, als Bereich oder als Gästezimmer.

    ``Room.number`` ist ``VARCHAR(20)`` (§5.49): ``t24dapi`` (7) + 6 Hex
    plus Trenner = 14 Zeichen.
    """
    short = uuid.uuid4().hex[:6]
    async with sessionmaker() as session:
        rt = RoomType(
            name=f"{PREFIX}-{short}",
            is_bookable=buchbar,
            default_t_occupied=Decimal(BETRIEB),
            default_t_vacant=Decimal(BETRIEB),
            default_t_night=Decimal(BETRIEB),
            max_temp_celsius=Decimal(max_temp) if max_temp is not None else None,
        )
        session.add(rt)
        await session.flush()
        # **Kein Nachziehen einer rule_config-Zeile.** Fuer einen
        # Allgemeinbereich hebt die Engine die Spalten selbst auf
        # ROOM_TYPE-Rang (``rules.engine.bereichs_kette``); fuer ein
        # Gaestezimmer entsteht der Vorrang nur ueber die Admin-Aktion.

        room = Room(number=f"{PREFIX}-{short}", room_type_id=rt.id)
        session.add(room)
        await session.flush()
        zone = HeatingZone(
            room_id=room.id,
            kind=HeatingZoneKind.COMMON_AREA if not buchbar else HeatingZoneKind.BEDROOM,
            name="Bereich",
        )
        session.add(zone)
        await session.commit()
        return _Aufbau(room.id, zone.id, rt.id)


async def _abraeumen(sessionmaker: async_sessionmaker[AsyncSession], aufbau: _Aufbau) -> None:
    """**Auch die ``rule_config``-Zeile** (§5.39).

    Der Sprint-Brief verlangt das ausdrücklich, und der Grund liegt zwei
    Tage zurück: eine stehengebliebene Zeile hat am 24.10.2026 jeden
    Engine-Test im selben Lauf auf einen anderen Sollwert gezogen. Das
    Zimmer per ``CASCADE`` loszuwerden genügt hier nicht — die Zeile hängt
    am **Raumtyp**.
    """
    async with sessionmaker() as session:
        await session.execute(
            text("DELETE FROM manual_override WHERE room_id = :r"), {"r": aufbau.room_id}
        )
        await session.execute(
            text("DELETE FROM event_log WHERE room_id = :r"), {"r": aufbau.room_id}
        )
        await session.execute(
            text("DELETE FROM heating_zone WHERE room_id = :r"), {"r": aufbau.room_id}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": aufbau.room_id})
        await session.execute(
            text("DELETE FROM rule_config WHERE room_type_id = :t"),
            {"t": aufbau.room_type_id},
        )
        await session.execute(
            text("DELETE FROM room_type WHERE id = :t"), {"t": aufbau.room_type_id}
        )
        await session.commit()


@pytest_asyncio.fixture
async def bereich(setup_engine: AsyncEngine) -> AsyncIterator[_Aufbau]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    aufbau = await _aufbauen(maker, buchbar=False)
    try:
        yield aufbau
    finally:
        await _abraeumen(maker, aufbau)


@pytest_asyncio.fixture
async def gastzimmer(setup_engine: AsyncEngine) -> AsyncIterator[_Aufbau]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    aufbau = await _aufbauen(maker, buchbar=True)
    try:
        yield aufbau
    finally:
        await _abraeumen(maker, aufbau)


@pytest_asyncio.fixture
async def bereich_mit_obergrenze(setup_engine: AsyncEngine) -> AsyncIterator[_Aufbau]:
    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    aufbau = await _aufbauen(maker, buchbar=False, max_temp=23)
    try:
        yield aufbau
    finally:
        await _abraeumen(maker, aufbau)


def _payload(**felder: object) -> dict[str, object]:
    grund = {
        "setpoint": "23",
        "source": "frontend_bereich",
        "dauer_minuten": 120,
    }
    grund.update(felder)
    return grund


# ---------------------------------------------------------------------------
# Der Hauptweg
# ---------------------------------------------------------------------------


async def test_bereich_nimmt_eine_uebersteuerung_ohne_belegung(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    """**S6.** Genau der Fall, den AE-58 bis hierher abgewiesen hat.

    Das Zimmer hat **keine** Belegung und kann keine haben. Vor diesem
    Sprint kam 409 ``ROOM_NOT_OCCUPIED``.
    """
    vorher = datetime.now(tz=UTC)
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich.room_id}/overrides",
        json=_payload(heating_zone_id=bereich.zone_id),
    )

    assert resp.status_code == 201, resp.text
    koerper = resp.json()
    assert koerper["source"] == "frontend_bereich"
    laeuft_ab = datetime.fromisoformat(koerper["expires_at"])
    # Zwei Stunden, mit Luft für die Laufzeit des Tests.
    assert vorher + timedelta(minutes=118) < laeuft_ab < vorher + timedelta(minutes=122)


async def test_ohne_dauer_wird_abgewiesen(http_client: httpx.AsyncClient, bereich: _Aufbau) -> None:
    """**Mutationsprobe M6.**

    Eine Bereichs-Übersteuerung ohne Ablauf wäre unbefristet, und eine
    Bar, die durchheizt, bemerkt niemand.
    """
    payload = _payload(heating_zone_id=bereich.zone_id)
    del payload["dauer_minuten"]
    resp = await http_client.post(f"/api/v1/rooms/{bereich.room_id}/overrides", json=payload)

    assert resp.status_code == 422, resp.text
    assert "dauer_minuten" in resp.text


async def test_mehr_als_24_stunden_wird_abgewiesen(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    """**Mutationsprobe M8.** Abgewiesen, nicht gekappt.

    Wer 48 Stunden eingibt, hat sich vertippt oder etwas anderes gemeint.
    Eine stille Kürzung auf 24 h wäre eine Antwort auf eine Frage, die
    niemand gestellt hat — und sie stünde danach als „gewollt" in der
    Historie.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich.room_id}/overrides",
        json=_payload(heating_zone_id=bereich.zone_id, dauer_minuten=48 * 60),
    )

    assert resp.status_code == 422, resp.text


async def test_genau_24_stunden_geht_noch(http_client: httpx.AsyncClient, bereich: _Aufbau) -> None:
    """Die Grenze selbst ist erlaubt.

    Ohne diesen Test wäre ein ``<`` statt ``<=`` in der Prüfung nicht zu
    unterscheiden von der richtigen Fassung — und 24 Stunden sind die
    Vorgabe des Betreibers, nicht der erste verbotene Wert.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich.room_id}/overrides",
        json=_payload(heating_zone_id=bereich.zone_id, dauer_minuten=24 * 60),
    )

    assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# Die Gegenrichtung: Gästezimmer bleiben, wie sie sind
# ---------------------------------------------------------------------------


async def test_gastzimmer_nimmt_die_bereichs_quelle_nicht(
    http_client: httpx.AsyncClient, gastzimmer: _Aufbau
) -> None:
    """**Mutationsprobe M22.**

    Das Zimmer ist nicht belegt. Würde die Bereichs-Quelle hier
    durchgehen, wäre AE-58 über einen Umweg aufgehoben: ein Zimmer, das
    leer gemeldet ist, bekäme doch einen Sollwert — und zwar **ohne** die
    Prüfung, die für Gästezimmer gilt.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{gastzimmer.room_id}/overrides",
        json=_payload(heating_zone_id=gastzimmer.zone_id),
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "OVERRIDE_SOURCE_MISMATCH"


async def test_bereich_nimmt_die_gaste_quelle_nicht(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    """Und umgekehrt — mit einer Meldung, die etwas sagt.

    ``frontend_24h`` an einem Bereich liefe ins Belegungs-Gate und bekäme
    „nicht belegt". Für eine Bar ist das keine brauchbare Auskunft.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich.room_id}/overrides",
        json={"setpoint": "23", "source": "frontend_24h", "heating_zone_id": bereich.zone_id},
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "OVERRIDE_SOURCE_MISMATCH"
    assert "frontend_bereich" in resp.json()["detail"]


async def test_dauer_bei_einer_anderen_quelle_wird_abgewiesen(
    http_client: httpx.AsyncClient, gastzimmer: _Aufbau
) -> None:
    """Ein Feld, das wirkungslos mitfährt, ist ein Schalter ohne Wirkung.

    ``frontend_24h`` trägt seine Dauer im Namen. Nähme der Endpunkt
    daneben ein ``dauer_minuten`` an, setzte der Aufrufer einen Wert, der
    stillschweigend verfällt (§5.77).
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{gastzimmer.room_id}/overrides",
        json={
            "setpoint": "23",
            "source": "frontend_24h",
            "dauer_minuten": 120,
            "heating_zone_id": gastzimmer.zone_id,
        },
    )

    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Kappung und Ablauf
# ---------------------------------------------------------------------------


async def test_wunschwert_wird_an_der_raumtyp_grenze_gekappt(
    http_client: httpx.AsyncClient, bereich_mit_obergrenze: _Aufbau
) -> None:
    """28 gewünscht, 23 erlaubt → 23 gespeichert.

    Die Engine kappt ohnehin (Layer 5). Entscheidend ist, dass die
    **Historie** den Wert trägt, der gilt: stünde dort 28 und im Trace
    23, sähe das nach einem Fehler aus.
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich_mit_obergrenze.room_id}/overrides",
        json=_payload(setpoint="28", heating_zone_id=bereich_mit_obergrenze.zone_id),
    )

    assert resp.status_code == 201, resp.text
    assert float(resp.json()["setpoint"]) == 23.0


async def test_trace_zeigt_den_wert_und_danach_wieder_den_plan(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine, bereich: _Aufbau
) -> None:
    """**Abschlusskriterium 3**, Engine-Hälfte.

    Setzen → der Trace zeigt 23. Ablauf → der Trace zeigt wieder 21, den
    Betrieb-Sollwert des Raumtyps. Der Ablauf wird hier **vorgezogen**
    statt abgewartet: zwei Stunden Wartezeit in einem Test wären keine
    Prüfung, sondern eine Zeitreise mit Risiko (§5.59 — eine halb
    gefälschte Uhr ist schlimmer als keine).
    """
    resp = await http_client.post(
        f"/api/v1/rooms/{bereich.room_id}/overrides",
        json=_payload(heating_zone_id=bereich.zone_id),
    )
    assert resp.status_code == 201, resp.text
    override_id = resp.json()["id"]

    maker = async_sessionmaker(setup_engine, expire_on_commit=False)
    async with maker() as session:
        ergebnis = await evaluate_room(session, bereich.room_id)
        assert ergebnis is not None
        # Der Eintrag traegt eine Zone, also steht er in ``zone_overrides``
        # und nicht in ``setpoint_c`` (AE-58 Option G) — genau so legt die
        # Oberflaeche ihn an, und genau das liest der Dispatch je Geraet.
        assert ergebnis.zone_overrides.get(bereich.zone_id) == 23, (
            f"die Uebersteuerung gilt (zone_overrides={ergebnis.zone_overrides})"
        )

        # Ablauf vorziehen: dieselbe Zeile, nur mit Frist in der
        # Vergangenheit. Layer 3 sucht nach ``expires_at > now``.
        eintrag = await session.get(ManualOverride, override_id)
        assert eintrag is not None
        eintrag.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        await session.commit()

        danach = await evaluate_room(session, bereich.room_id)
        assert danach is not None
        assert danach.zone_overrides == {}, "der abgelaufene Eintrag wirkt nicht mehr"
        assert danach.setpoint_c == BETRIEB, "nach dem Ablauf gilt wieder der Plan"
        basis = next(s for s in danach.layers if s.layer.value == "base_target")
        assert basis.extras is not None
        assert basis.extras["betriebsbereich"] is True


# ---------------------------------------------------------------------------
# Die Rollenprüfung
# ---------------------------------------------------------------------------


def test_der_endpunkt_traegt_die_rollenpruefung() -> None:
    """**Mutationsprobe M23**, und die Begründung, warum sie so aussieht.

    Das Haus hat **zwei** Rollen, ``admin`` und ``mitarbeiter`` (AE-50),
    und beide sind Personal. Eine Anfrage mit gültiger Sitzung, die 403
    bekommt, gibt es hier also nicht — der Sprint-Brief setzt eine dritte
    Rolle voraus, die es nicht gibt, und sie zu erfinden wäre eine
    Änderung am Rollenmodell und nicht an diesem Sprint.

    Unter ``AUTH_ENABLED=false`` liefert ``get_current_user`` zudem einen
    System-Nutzer mit Admin-Rechten; eine Anfrage **ohne** Cookie ist
    deshalb kein Beleg (Lehre aus 24b, wo genau diese Probe wertlos war).

    Bleibt die Prüfung am Bauteil selbst: der Endpunkt muss die
    Abhängigkeit **tragen**. Wer die Rollenprüfung in die Oberfläche
    verlegt und sie hier entfernt, macht diesen Test rot — und das ist
    genau die Mutation, um die es geht.
    """
    sig = inspect.signature(create_room_override)
    abhaengigkeiten = [
        p.default.dependency
        for p in sig.parameters.values()
        if isinstance(p.default, params.Depends)
    ]
    assert require_mitarbeiter in abhaengigkeiten, (
        "POST /rooms/{id}/overrides ohne require_mitarbeiter — "
        "die Rollenpruefung liegt dann nur noch in der Oberflaeche"
    )


# ---------------------------------------------------------------------------
# Die Vorschau und die Freigabe-Aktion
# ---------------------------------------------------------------------------


async def test_vorschau_nennt_quelle_und_abweichung(
    http_client: httpx.AsyncClient, gastzimmer: _Aufbau
) -> None:
    resp = await http_client.get("/api/v1/room-types/sollwert-wirksamkeit")

    assert resp.status_code == 200, resp.text
    mein = next(b for b in resp.json() if b["room_type_id"] == gastzimmer.room_type_id)
    assert mein["is_bookable"] is True
    assert mein["zeile_vorhanden"] is False
    felder = {f["feld"]: f for f in mein["felder"]}
    assert felder["default_t_vacant"]["quelle"] in {"global", "raumtyp_vorgabe"}


async def test_freigabe_aktion_macht_die_werte_wirksam(
    http_client: httpx.AsyncClient, gastzimmer: _Aufbau
) -> None:
    """Der ausdrückliche Weg für einen buchbaren Raumtyp, mit Audit."""
    resp = await http_client.post(
        f"/api/v1/room-types/{gastzimmer.room_type_id}/sollwerte-uebernehmen", json={}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["ergebnis"] == "angelegt"

    nachher = await http_client.get("/api/v1/room-types/sollwert-wirksamkeit")
    mein = next(b for b in nachher.json() if b["room_type_id"] == gastzimmer.room_type_id)
    assert mein["zeile_vorhanden"] is True
    felder = {f["feld"]: f for f in mein["felder"]}
    assert felder["default_t_vacant"]["quelle"] == "raumtyp"


async def test_die_vorschau_liegt_nicht_hinter_der_id_route(
    http_client: httpx.AsyncClient,
) -> None:
    """Die Routen-Reihenfolge, als Zusicherung.

    ``/{room_type_id}`` trägt ``gt=0``; stünde es vor
    ``/sollwert-wirksamkeit``, käme hier 422 statt 200. Dieselbe Falle wie
    bei den Playwright-Routen in 24b, nur eine Schicht tiefer — und sie
    fällt sonst erst in der Oberfläche auf.
    """
    resp = await http_client.get("/api/v1/room-types/sollwert-wirksamkeit")
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Das Zimmer selbst
# ---------------------------------------------------------------------------


async def test_zimmer_meldet_sich_als_allgemeinbereich(
    http_client: httpx.AsyncClient, bereich: _Aufbau, gastzimmer: _Aufbau
) -> None:
    """**Abschlusskriterium 2**, API-Hälfte — beide Richtungen in einem Test.

    Ein Test, der nur die ``true``-Seite prüft, wäre auch grün, wenn das
    Feld immer ``true`` wäre.
    """
    b = await http_client.get(f"/api/v1/rooms/{bereich.room_id}")
    g = await http_client.get(f"/api/v1/rooms/{gastzimmer.room_id}")

    assert b.status_code == 200, b.text
    assert b.json()["ist_allgemeinbereich"] is True
    assert g.json()["ist_allgemeinbereich"] is False


async def test_die_liste_fuehrt_die_marke_mit(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    """Die Liste rendert 45 Zeilen — die Marke kommt dort aus **einem**
    Aggregat und nicht aus einer Abfrage je Zeile (§5.73)."""
    resp = await http_client.get("/api/v1/rooms", params={"limit": 1000})

    assert resp.status_code == 200, resp.text
    mein = next(r for r in resp.json() if r["id"] == bereich.room_id)
    assert mein["ist_allgemeinbereich"] is True


# ---------------------------------------------------------------------------
# Quellen-Spiegel
# ---------------------------------------------------------------------------


def test_jede_frontend_quelle_ist_im_rang_tisch() -> None:
    """Der Tisch, dessen Lücke am 21.10. die Rezeption gekostet hat.

    ``test_override_quellen_spiegel.py`` hält ihn schon gegen den ganzen
    Enum; hier steht die Frage noch einmal für die **neue** Quelle, weil
    sie in diesem Sprint entstanden ist und der Fehler damals genau so
    aussah: ein neuer Wert, eine nicht nachgezogene Liste.
    """
    from heizung.services.override_service import _QUELLEN_RANG

    assert OverrideSource.FRONTEND_BEREICH in _QUELLEN_RANG


# ---------------------------------------------------------------------------
# Die zwei Schichten der Dauer-Pflicht, je einzeln festgenagelt
# ---------------------------------------------------------------------------
#
# Die Pflicht steht im Schema **und** im Dienst. Das ist Absicht (der
# Dienst ist auch von einem Aufrufer erreichbar, der nicht durch das Schema
# kommt), hat aber eine Folge fuer die Mutationsproben: wird nur eine der
# beiden entfernt, antwortet die API weiter mit 422, und die Tests oben
# bleiben gruen. Sie pruefen die **Wirkung**, und die Wirkung haelt.
#
# Diese vier Tests nageln die Schichten einzeln fest, damit M6 und M8 je
# Schicht eine rote Zusicherung haben und nicht nur zusammen.


def test_schema_verlangt_die_dauer() -> None:
    """**M6, Schema-Schicht.**"""
    with pytest.raises(ValidationError, match="dauer_minuten"):
        ManualOverrideCreate(setpoint=Decimal(23), source="frontend_bereich")


def test_schema_weist_mehr_als_24_stunden_ab() -> None:
    """**M8, Schema-Schicht.**"""
    with pytest.raises(ValidationError):
        ManualOverrideCreate(
            setpoint=Decimal(23), source="frontend_bereich", dauer_minuten=24 * 60 + 1
        )


def test_dienst_verlangt_die_dauer() -> None:
    """**M6, Dienst-Schicht.**"""
    now = datetime.now(tz=UTC)
    with pytest.raises(ValueError, match="dauer_minuten"):
        override_service.compute_expires_at(OverrideSource.FRONTEND_BEREICH, now)


def test_dienst_weist_mehr_als_24_stunden_ab() -> None:
    """**M8, Dienst-Schicht.**"""
    now = datetime.now(tz=UTC)
    with pytest.raises(ValueError, match="ausserhalb"):
        override_service.compute_expires_at(
            OverrideSource.FRONTEND_BEREICH, now, dauer_minuten=24 * 60 + 1
        )


async def test_ein_neuer_bereich_ist_sofort_wirksam(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Ein neu angelegter Allgemeinbereich wirkt **ohne** weiteren Handgriff.

    Und zwar **ohne** ``rule_config``-Zeile: der Vorrang kommt aus der
    Kette, nicht aus Daten. Das ist der Unterschied zur ersten Fassung
    dieses Sprints, die eine Zeile geschrieben hat — eine Zeile waere eine
    zweite Wahrheit neben der Spalte, und ein Backfill haette sie fuer
    jeden Bereich anlegen muessen.
    """
    short = uuid.uuid4().hex[:6]
    resp = await http_client.post(
        "/api/v1/room-types",
        json={
            "name": f"{PREFIX}-neu-{short}",
            "is_bookable": False,
            "default_t_occupied": 21.0,
            "default_t_vacant": 21.0,
            "default_t_night": 20.0,
        },
    )
    assert resp.status_code == 201, resp.text
    rt_id = resp.json()["id"]

    try:
        vorschau = await http_client.get("/api/v1/room-types/sollwert-wirksamkeit")
        mein = next(b for b in vorschau.json() if b["room_type_id"] == rt_id)
        assert mein["zeile_vorhanden"] is False, (
            "ein Allgemeinbereich braucht keine ROOM_TYPE-Zeile — "
            "die Kette hebt seine Spalten selbst"
        )
        felder = {f["feld"]: f for f in mein["felder"]}
        assert felder["default_t_vacant"]["quelle"] == "raumtyp"
        assert float(felder["default_t_vacant"]["wirksam"]) == 21.0
        assert mein["wuerde_sich_aendern"] is False
    finally:
        maker = async_sessionmaker(setup_engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(
                text("DELETE FROM rule_config WHERE room_type_id = :t"), {"t": rt_id}
            )
            await session.execute(text("DELETE FROM room_type WHERE id = :t"), {"t": rt_id})
            await session.commit()


async def test_ein_neues_gaestezimmer_bleibt_unwirksam(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Die Gegenprobe zu M18 — sonst waere „immer anlegen" auch gruen."""
    short = uuid.uuid4().hex[:6]
    resp = await http_client.post(
        "/api/v1/room-types",
        json={"name": f"{PREFIX}-gastneu-{short}", "is_bookable": True},
    )
    assert resp.status_code == 201, resp.text
    rt_id = resp.json()["id"]

    try:
        vorschau = await http_client.get("/api/v1/room-types/sollwert-wirksamkeit")
        mein = next(b for b in vorschau.json() if b["room_type_id"] == rt_id)
        assert mein["zeile_vorhanden"] is False, (
            "ein buchbarer Raumtyp hat beim Anlegen eine ROOM_TYPE-Zeile bekommen — "
            "damit verschiebt das Speichern die Sollwerte von Gaestezimmern"
        )
        # Und die Spalte gewinnt dort **nicht** gegen den Hausstandard.
        felder = {f["feld"]: f for f in mein["felder"]}
        assert felder["default_t_night"]["quelle"] in {"global", "raumtyp_vorgabe"}
    finally:
        maker = async_sessionmaker(setup_engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(
                text("DELETE FROM rule_config WHERE room_type_id = :t"), {"t": rt_id}
            )
            await session.execute(text("DELETE FROM room_type WHERE id = :t"), {"t": rt_id})
            await session.commit()


async def test_betrieb_zieht_belegt_gleich(
    http_client: httpx.AsyncClient, setup_engine: AsyncEngine
) -> None:
    """Bei einem Bereich ist „Betrieb" beides — auch in der Spalte.

    Sonst bliebe in ``default_t_occupied`` ein Wert, den niemand sieht und
    der bei einem von Hand gesetzten Status ``occupied`` ploetzlich gilt.
    """
    short = uuid.uuid4().hex[:6]
    resp = await http_client.post(
        "/api/v1/room-types",
        json={
            "name": f"{PREFIX}-gleich-{short}",
            "is_bookable": False,
            "default_t_occupied": 17.0,
            "default_t_vacant": 21.0,
            "default_t_night": 20.0,
        },
    )
    assert resp.status_code == 201, resp.text
    rt_id = resp.json()["id"]

    try:
        assert float(resp.json()["default_t_occupied"]) == 21.0
    finally:
        maker = async_sessionmaker(setup_engine, expire_on_commit=False)
        async with maker() as session:
            await session.execute(
                text("DELETE FROM rule_config WHERE room_type_id = :t"), {"t": rt_id}
            )
            await session.execute(text("DELETE FROM room_type WHERE id = :t"), {"t": rt_id})
            await session.commit()


# ---------------------------------------------------------------------------
# Betriebszeit am Endpunkt
# ---------------------------------------------------------------------------


async def test_betriebszeit_setzen_und_wieder_loeschen(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    """Der Handgriff, den der Betreiber nach dem Merge macht.

    ``24:00`` ist dabei die Eingabe und nicht ``00:00`` — sie ist die
    natuerliche Schreibweise fuer „bis Mitternacht", und das Backend
    bildet sie ab.
    """
    resp = await http_client.patch(
        f"/api/v1/rooms/{bereich.room_id}/betriebszeit",
        json={"von": "15:00", "bis": "24:00"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["betriebszeit_von"] == "15:00:00"
    assert resp.json()["betriebszeit_bis"] == "00:00:00"

    leer = await http_client.patch(
        f"/api/v1/rooms/{bereich.room_id}/betriebszeit",
        json={"von": None, "bis": None},
    )
    assert leer.status_code == 200, leer.text
    assert leer.json()["betriebszeit_von"] is None


async def test_betriebszeit_an_einem_gaestezimmer_abgewiesen(
    http_client: httpx.AsyncClient, gastzimmer: _Aufbau
) -> None:
    """Intern ist es das Nacht-Fenster.

    An einem Gaestezimmer wuerde dieselbe Eingabe die Nachtabsenkung
    dieses Zimmers umstellen — unter einem Namen, der etwas anderes sagt.
    """
    resp = await http_client.patch(
        f"/api/v1/rooms/{gastzimmer.room_id}/betriebszeit",
        json={"von": "07:00", "bis": "22:00"},
    )

    assert resp.status_code == 422, resp.text
    assert "Allgemeinbereich" in resp.text


async def test_unsinnige_uhrzeit_wird_abgewiesen(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    resp = await http_client.patch(
        f"/api/v1/rooms/{bereich.room_id}/betriebszeit",
        json={"von": "25:00", "bis": "22:00"},
    )
    assert resp.status_code == 422, resp.text


async def test_halbe_betriebszeit_am_endpunkt_abgewiesen(
    http_client: httpx.AsyncClient, bereich: _Aufbau
) -> None:
    """Ein Fenster mit einem Ende und ohne Anfang wuerde nichts tun."""
    resp = await http_client.patch(
        f"/api/v1/rooms/{bereich.room_id}/betriebszeit",
        json={"von": "07:00", "bis": None},
    )
    assert resp.status_code == 422, resp.text


async def test_ein_gaestezimmer_meldet_keine_betriebszeit(
    http_client: httpx.AsyncClient, gastzimmer: _Aufbau
) -> None:
    """Die Felder sind dort ``None`` — auch wenn eine ROOM-Zeile existiert.

    Dieselbe Zeile traegt bei einem Gaestezimmer das Nacht-Fenster. Sie
    unter dem Namen „Betriebszeit" auszuliefern hiesse, zwei Dinge gleich
    zu nennen, die verschieden gemeint sind.
    """
    resp = await http_client.get(f"/api/v1/rooms/{gastzimmer.room_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["betriebszeit_von"] is None
    assert resp.json()["betriebszeit_bis"] is None


# ---------------------------------------------------------------------------
# Kindersicherung: „ausstehend" bis zum naechsten Keepalive
# ---------------------------------------------------------------------------


def test_eine_meldung_von_vor_dem_befehl_ist_ausstehend() -> None:
    """**Mutationsprobe M25.**

    Direkt nach dem Umschalten auf „nur messen" ist die juengste Meldung
    die vom Keepalive **davor**: sie sagt „Rad frei", und das war bis zur
    Sekunde vorher richtig. Ohne den Zeitvergleich stand dort ein roter
    Befund im Normalfall — und ein Melder, der im Normalfall rot zeigt,
    wird nach einer Woche nicht mehr gelesen (§5.79).
    """
    befehl = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False),
            gemeldet=False,
            gemeldet_um=befehl - timedelta(minutes=10),
            befehl_um=befehl,
        )
        == "ausstehend"
    )


def test_eine_meldung_nach_dem_befehl_entscheidet() -> None:
    """Die Gegenprobe — sonst waere „immer ausstehend" auch gruen.

    Kommt nach dem Befehl eine Meldung und sagt „Rad frei", ist das eine
    **Antwort** und ein Befund.
    """
    befehl = datetime(2026, 10, 24, 8, 0, tzinfo=UTC)
    nachher = befehl + timedelta(minutes=5)
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False),
            gemeldet=False,
            gemeldet_um=nachher,
            befehl_um=befehl,
        )
        == "fehlgeschlagen"
    )
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False),
            gemeldet=True,
            gemeldet_um=nachher,
            befehl_um=befehl,
        )
        == "bestaetigt"
    )


def test_ohne_befehlszeit_urteilt_es_wie_vorher() -> None:
    """Bestandsgeraete vor Migration 0033 tragen ``NULL``.

    Dann wird nicht geraten: die Funktion urteilt wie in 24c. Ein
    stillschweigendes „ausstehend" fuer jedes Geraet ohne Befehlszeit
    waere ein Melder, der nie etwas sagt.
    """
    assert (
        child_lock_state(
            gewollt=soll_kindersicherung(measure_only=True, gast_sperre=False),
            gemeldet=False,
            gemeldet_um=datetime(2026, 10, 24, 8, 0, tzinfo=UTC),
            befehl_um=None,
        )
        == "fehlgeschlagen"
    )
