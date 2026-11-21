"""Meldung, wenn ein Relais warm wird (18.11.2026).

**Die Gegenprobe ist der Zweck dieser Datei.** Am 18.11.2026 stand Relais
„109 Panel" (``device.id`` 110) bei **45**, waehrend „108" (``device.id``
109) bei nahezu gleicher Last **37** meldete. Gesehen hat das der
Betreiber auf der Geraeteseite — kein Melder hat angeschlagen, weil es
keinen gab. ``api/v1/relays.py`` war der einzige Verbraucher der Schwelle
und faerbt nur die Karte.

**Und die zweite Gegenprobe, vom 21.11.2026:** dieselben Zahlen loesen
heute **keine** Mail aus. 44-45 ist der Normalbetrieb von 110, und ein
Melder, der taeglich meldet, wird abgeschaltet statt gelesen (Paragraph
5.79). Deshalb zwei Schwellen — Mail ab 50, Entwarnung unter 45 — und
deshalb pruefen
``test_der_lastwert_von_110_meldet_nicht_und_entwarnt_nicht`` und
``test_erst_ueber_50_wird_es_eine_mail`` beide Richtungen: eine Schwelle,
die nie anschlaegt, ist dasselbe wie kein Melder.

**Kein ``pytestmark`` auf Modulebene**, und das ist Absicht: die Urteile
und die Texte brauchen keine Datenbank und sollen auch ohne sie laufen.
Ein Modul-Mark haette sie mitgesprungen, und dann prueft ein Lauf ohne
``TEST_DATABASE_URL`` gar nichts mehr — ein gruener Lauf, der nichts
geprueft hat (Paragraph 5.55). Der Sprung sitzt in der ``maker``-Fixture.
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
from heizung.services import gehaeuse_melder
from heizung.tasks import gehaeuse_tasks

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"
PREFIX = "gwm"

#: Die Betriebsvorgaben, hier als Pruefstand-Werte wiederholt. **Bewusst
#: nicht importiert**: der Test soll festhalten, gegen welche Zahlen er
#: geprueft hat — zieht jemand die Vorgabe hoch, soll er nicht
#: stillschweigend mitwandern (Paragraph 5.77 in Testform).
#:
#: ``SCHWELLE_ENTWARNUNG`` ist ``SCHWELLE_MAIL - config.GEHAEUSE_TOTBAND_K``
#: und steht hier als Zahl, damit der Test die **erwartete** Ableitung
#: festhaelt und nicht dieselbe Rechnung wie der Code macht.
SCHWELLE_MAIL = 50
SCHWELLE_ENTWARNUNG = 45

#: Der gemessene Lastwert von Relais „109 Panel" am 18.11.2026. Er ist
#: der Grund fuer die zweite Schwelle und taucht unten mehrfach auf.
LASTWERT_110 = 45

#: Das Frischefenster der Vorgaben (``relay_meldeintervall_s`` 600 mal
#: ``VERALTUNGS_FAKTOR`` 2,5). Ebenfalls als Zahl und nicht gerechnet.
FRISCHE = timedelta(minutes=25)

#: Feste Uhr. Absolute Zeitwerte **und** eine stehende Uhr, beide
#: zusammen — sonst ist die Datei auf einen Tag datiert (Paragraph 5.59,
#: Nachtrag vom 01.11.2026).
JETZT = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)


def _beurteile(
    werte: tuple[int, ...],
    *,
    alter_min: int | None = 2,
    schwelle_mail: int = SCHWELLE_MAIL,
    label: str | None = "109 Panel",
    relay_on: bool | None = True,
    power_w: int | None = 1490,
) -> gehaeuse_melder.GehaeuseBefund:
    letzte = None if alter_min is None else JETZT - timedelta(minutes=alter_min)
    return gehaeuse_melder.beurteile(
        device_id=110,
        dev_eui="70b3d52dd3034de4",
        label=label,
        ort="139",
        zone_name="Eingang",
        werte=werte,
        letzte_meldung=letzte,
        relay_on=relay_on,
        power_w=power_w,
        schwelle_mail=schwelle_mail,
        frische_fenster=FRISCHE,
        now=JETZT,
    )


# ---------------------------------------------------------------------------
# Das Urteil, ohne Datenbank
# ---------------------------------------------------------------------------


def test_drei_werte_ueber_der_mail_schwelle_melden() -> None:
    befund = _beurteile((52, 51, 50))
    assert befund.heiss
    assert not befund.kuehl
    assert befund.wert == 52


def test_genau_auf_der_mail_schwelle_meldet_schon() -> None:
    """Die Schwelle gehoert zum Alarm, nicht zum Normalfall.

    Eine Grenze, die auf beiden Seiten "in Ordnung" heisst, waere eine
    Grenze ohne Wirkung.
    """
    assert _beurteile((SCHWELLE_MAIL, SCHWELLE_MAIL, SCHWELLE_MAIL)).heiss


def test_der_lastwert_von_110_meldet_nicht_und_entwarnt_nicht() -> None:
    """**Der Grund fuer die zweite Schwelle** (21.11.2026).

    Relais "109 Panel" steht bei 44-45, sobald es heizt. Mit einer
    einzigen Schwelle bei 40 waere das jeden Tag eine Mail gewesen, und
    ein Melder, der taeglich meldet, wird abgeschaltet statt gelesen
    (Paragraph 5.79).

    Der Lastwert liegt jetzt im **Totband**: kein Alarm, aber auch keine
    Entwarnung. Das zweite ist genauso wichtig — eine Entwarnung bei 45
    wuerde am naechsten Heizvorgang sofort wieder kippen, und daraus
    entstuende ein Paar Mails je Tag statt einer.
    """
    befund = _beurteile((LASTWERT_110, LASTWERT_110, LASTWERT_110 - 1))
    assert not befund.heiss, "44-45 ist der Normalbetrieb von 110"
    assert not befund.kuehl, "im Totband wird nicht entwarnt"
    assert befund.schwelle_entwarnung == SCHWELLE_ENTWARNUNG


def test_das_totband_liegt_zwischen_den_beiden_schwellen() -> None:
    """Vier Punkte, vier Urteile — beide Grenzen gehoeren geprueft."""
    assert _beurteile((SCHWELLE_MAIL,) * 3).heiss
    assert not _beurteile((SCHWELLE_MAIL - 1,) * 3).heiss
    assert not _beurteile((SCHWELLE_ENTWARNUNG,) * 3).kuehl, "die Grenze selbst entwarnt nicht"
    assert _beurteile((SCHWELLE_ENTWARNUNG - 1,) * 3).kuehl


def test_ein_einzelner_ausschlag_meldet_nicht() -> None:
    """Der Grund fuer die Entprellung: ein Wert ist kein Befund."""
    befund = _beurteile((52, 37, 36))
    assert not befund.heiss
    assert not befund.kuehl, "gemischt ist auch keine Entwarnung"


def test_zwei_werte_sind_noch_kein_urteil() -> None:
    befund = _beurteile((52, 51))
    assert not befund.vollstaendig
    assert not befund.heiss
    assert not befund.kuehl


def test_ohne_jede_meldung_gibt_es_kein_urteil() -> None:
    befund = _beurteile((), alter_min=None)
    assert not befund.frisch
    assert befund.wert is None
    assert not befund.heiss
    assert not befund.kuehl


def test_veraltete_werte_urteilen_nicht() -> None:
    """Ein Relais, das seit einer Stunde schweigt, ist kein Befund.

    Und es wird auch nicht entwarnt: eine Entwarnung ohne frischen
    Messwert waere eine Behauptung (Paragraph 5.68).
    """
    befund = _beurteile((52, 51, 50), alter_min=60)
    assert not befund.frisch
    assert not befund.heiss
    assert not befund.kuehl


def test_genau_auf_dem_frischefenster_zaehlt_noch() -> None:
    assert _beurteile((52, 51, 50), alter_min=25).heiss
    assert not _beurteile((52, 51, 50), alter_min=26).heiss


def test_drei_werte_unter_der_entwarnungs_schwelle_entwarnen() -> None:
    befund = _beurteile((44, 43, 42))
    assert befund.kuehl
    assert not befund.heiss


def test_mehr_als_drei_werte_werden_abgeschnitten() -> None:
    """Der Befund traegt genau die Werte, nach denen er geurteilt hat.

    Ein vierter, kuehler Wert von vorhin darf das Urteil nicht kippen —
    sonst stuende in der Mail eine Reihe, die zu ihrem Betreff nicht
    passt.
    """
    befund = _beurteile((52, 51, 50, 20, 20))
    assert befund.werte == (52, 51, 50)
    assert befund.heiss


def test_gegenprobe_18_11_keines_der_beiden_relais_meldet() -> None:
    """Die gemessenen Zahlen vom 18.11.2026, mit den Schwellen von heute.

    110 ("109 Panel") stand bei 45, 109 ("108") bei 37 — bei nahezu
    gleicher Last. **Beide** loesen heute keine Mail aus, und das ist der
    Zweck der Aenderung vom 21.11.: der Unterschied zwischen den Geraeten
    ist echt (7 K), aber er ist ein Fall fuer den Elektriker und nicht
    fuer eine taegliche Mail.

    Sichtbar bleibt der Unterschied trotzdem — 110 liegt im Totband, 108
    darunter.
    """
    panel = _beurteile((45, 45, 45), label="109 Panel")
    bar = _beurteile((37, 37, 37), label="108")
    assert not panel.heiss and not panel.kuehl, "110 liegt im Totband"
    assert not bar.heiss
    assert bar.kuehl, "37 liegt unter der Entwarnungs-Schwelle"


def test_erst_ueber_50_wird_es_eine_mail() -> None:
    """Die Gegenprobe zur Gegenprobe: steigt 110 weiter, meldet es doch.

    Sonst waere die hoehere Schwelle ein Melder, der nie meldet — und das
    ist dasselbe wie keiner (Paragraph 5.79).
    """
    assert _beurteile((51, 50, 50), label="109 Panel").heiss


def test_ohne_etikett_nennt_der_befund_die_dev_eui() -> None:
    """Namen statt Ids — und wenn es keinen Namen gibt, die DevEUI.

    ``device_id=110`` ist fuer den Empfaenger der Mail keine Auskunft.
    """
    assert _beurteile((52, 51, 50), label=None).name == "70b3d52dd3034de4"


# ---------------------------------------------------------------------------
# Die Texte
# ---------------------------------------------------------------------------


def test_der_alarmtext_sagt_zuerst_die_folge_und_nicht_die_diagnose() -> None:
    text_ = gehaeuse_melder.nachricht_alarm(_beurteile((52, 51, 50)))
    kopf = text_.split("\n\n")[0]
    assert "109 Panel" in kopf
    assert "52" in kopf
    assert "50" in kopf, "die Mail-Schwelle gehoert in den ersten Absatz"
    assert "52 / 51 / 50" in text_, "die Reihe belegt die Entprellung"


def test_der_alarmtext_nennt_beide_schwellen() -> None:
    """Wer die Mail liest, muss wissen, wann die naechste Nachricht kommt.

    Ohne die Entwarnungs-Schwelle im Text ist nicht zu erkennen, dass es
    ein Totband gibt — und dann sieht ein Wert von 46 nach "immer noch
    Alarm" aus, obwohl er nur noch nicht entwarnt ist.
    """
    text_ = gehaeuse_melder.nachricht_alarm(_beurteile((52, 51, 50)))
    assert "Mail-Schwelle:    50" in text_
    assert "Entwarnung unter: 45" in text_
    assert "sie zeigt, sie meldet nicht" in text_, "die Karte faerbt frueher — das gehoert dazu"


def test_der_alarmtext_nennt_die_offene_einheit() -> None:
    """Die Doku spricht die Einheit dieses Feldes nicht aus — das bleibt im Text.

    Sonst liest der Empfaenger "52 Grad" als belegten Messwert. Belegt
    sind die Aufloesung des Fuehlers und die Schutz-Temperaturen, nicht
    dieses Byte (AE-78).
    """
    text_ = gehaeuse_melder.nachricht_alarm(_beurteile((52, 51, 50)))
    assert "nicht aus" in text_, "der Vorbehalt zur Einheit fehlt"
    assert "1 Grad Aufloesung" in text_
    assert "85 Grad" in text_, "der Ueberhitzungsschutz des Geraets gehoert dazu"
    assert "Firmware 1.4" in text_, "die Vorgabe haengt an der Firmware"


def test_der_alarmtext_unterscheidet_last_von_keiner_last() -> None:
    mit = gehaeuse_melder.nachricht_alarm(_beurteile((52, 51, 50)))
    ohne = gehaeuse_melder.nachricht_alarm(_beurteile((52, 51, 50), relay_on=False, power_w=0))
    assert "1490 W" in mit
    assert "keine Last" in ohne


def test_die_entwarnung_verspricht_nicht_zu_viel() -> None:
    text_ = gehaeuse_melder.nachricht_entwarnung(_beurteile((44, 43, 42)))
    assert "44 / 43 / 42" in text_
    assert "unter 45" in text_, "die Entwarnung nennt ihre eigene Grenze"
    assert "ab 50" in text_, "und die, ab der gemeldet wurde"
    assert "sagt diese Meldung nicht" in text_


def test_der_betreff_nennt_wert_und_schwelle() -> None:
    assert gehaeuse_melder.betreff_alarm(_beurteile((52, 51, 50))) == (
        "Heizung Sonnblick: Relais 109 Panel wird warm (52 ueber Schwelle 50)"
    )


# ---------------------------------------------------------------------------
# Der Lesepfad, gegen Postgres
# ---------------------------------------------------------------------------


class Aufbau:
    """Die Ids des Testaufbaus."""

    def __init__(self, room_id: int, zone_id: int, relais_id: int, fuehler_id: int) -> None:
        self.room_id = room_id
        self.zone_id = zone_id
        self.relais_id = relais_id
        #: Ein Thermostat in derselben Zone. Er darf im Ergebnis **nicht**
        #: vorkommen — ein Vicki hat kein Gehaeuse, das hier gemeint ist.
        self.fuehler_id = fuehler_id


@pytest_asyncio.fixture
async def maker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Session-Fabrik auf der Test-DB — und ``DATABASE_URL`` darauf gepinnt.

    Der Task oeffnet seine Session selbst (``_task_session``) und liest
    dafuer ``settings.database_url``. Ohne das Pinnen wuerde er eine
    andere Datenbank sehen als der Aufbau hier (Paragraph 5.48).
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
    temperaturen: tuple[int | None, ...] = (52, 51, 50),
    abstand_min: int = 10,
    erstes_alter_min: int = 2,
    sperre: bool = False,
    ausgemustert: bool = False,
) -> Aufbau:
    """Ein Zimmer mit Zone, einem Relais und einem Thermostat.

    ``temperaturen`` sind die Gehaeusewerte, **juengster zuerst**;
    ``None`` schreibt eine Zeile ohne Temperatur (ein Lebenszeichen ohne
    Messwert). ``abstand_min`` ist der Abstand zwischen zwei Meldungen,
    ``erstes_alter_min`` das Alter der juengsten.
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
            commissioned_at=jetzt - timedelta(hours=1),
            protection_tripped_at=(jetzt - timedelta(minutes=5)) if sperre else None,
            protection_kind="overheating" if sperre else None,
            retired_at=(jetzt - timedelta(minutes=5)) if ausgemustert else None,
        )
        session.add(relais)
        await session.flush()
        for i, wert in enumerate(temperaturen):
            session.add(
                RelayReading(
                    device_id=relais.id,
                    time=jetzt - timedelta(minutes=erstes_alter_min + i * abstand_min),
                    relay_on=True,
                    power_w=1490,
                    internal_temperature_raw=wert,
                )
            )

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

        ids = Aufbau(room.id, zone.id, relais.id, fuehler.id)
        await session.commit()
    return ids


async def _raeum_auf(maker: Any, ids: Aufbau) -> None:
    async with maker() as session:
        geraete = [i for i in (ids.relais_id, ids.fuehler_id) if i]
        await session.execute(
            text("DELETE FROM business_audit WHERE target_type = 'device' AND target_id = ANY(:d)"),
            {"d": geraete},
        )
        await session.execute(
            text("DELETE FROM relay_reading WHERE device_id = ANY(:d)"), {"d": geraete}
        )
        await session.execute(text("DELETE FROM room WHERE id = :r"), {"r": ids.room_id})
        # ``room`` CASCADE raeumt die Zone, aber ``device.heating_zone_id``
        # ist nullable und wird dabei nur auf NULL gesetzt — die Geraete
        # muessen ausdruecklich weg (Paragraph 5.39).
        await session.execute(text("DELETE FROM device WHERE id = ANY(:d)"), {"d": geraete})
        await session.execute(
            text(
                "DELETE FROM room_type WHERE id NOT IN (SELECT room_type_id FROM room) "
                "AND name LIKE :p"
            ),
            {"p": f"{PREFIX}-%"},
        )
        await session.commit()


async def _lies(maker: Any) -> list[gehaeuse_melder.GehaeuseBefund]:
    async with maker() as session:
        return await gehaeuse_melder.lies_gehaeusetemperaturen(
            session, schwelle_mail=SCHWELLE_MAIL, frische_fenster=FRISCHE
        )


def _eigenes(
    befunde: list[gehaeuse_melder.GehaeuseBefund], ids: Aufbau
) -> gehaeuse_melder.GehaeuseBefund:
    """Nur der eigene Aufbau. Andere Relais des Hauses zaehlen nicht mit (Paragraph 5.39)."""
    treffer = [b for b in befunde if b.device_id == ids.relais_id]
    assert len(treffer) == 1, f"das eigene Relais wurde nicht genau einmal gefunden: {befunde}"
    return treffer[0]


async def test_drei_heisse_meldungen_werden_gefunden(maker: Any) -> None:
    ids = await _baue(maker)
    try:
        befund = _eigenes(await _lies(maker), ids)
        assert befund.werte == (52, 51, 50), "juengster Wert zuerst"
        assert befund.heiss
        assert befund.zone_name == "Eingang"
        assert befund.ort is not None, "die Zimmernummer gehoert in die Mail"
    finally:
        await _raeum_auf(maker, ids)


async def test_zeilen_ohne_temperatur_fuellen_die_entprellung_nicht(maker: Any) -> None:
    """Ein Lebenszeichen ist kein Messwert.

    Mit zwei heissen Werten und einer leeren Zeile dazwischen gibt es
    kein Urteil — und das ist richtig: zwei Werte sind zwei Werte.
    """
    ids = await _baue(maker, temperaturen=(52, None, 51))
    try:
        befund = _eigenes(await _lies(maker), ids)
        assert befund.werte == (52, 51)
        assert not befund.vollstaendig
        assert not befund.heiss
    finally:
        await _raeum_auf(maker, ids)


async def test_alte_meldungen_fuellen_die_entprellung_nicht(maker: Any) -> None:
    """Drei heisse Werte mit Stunden dazwischen sind keine drei in Folge.

    Das Lesefenster ist ``MIN_MELDUNGEN * frische_fenster`` — hier 75
    Minuten. Bei 40 Minuten Abstand fallen der zweite und dritte Wert
    heraus.
    """
    ids = await _baue(maker, abstand_min=40)
    try:
        befund = _eigenes(await _lies(maker), ids)
        assert befund.werte == (52, 51), "nur die Werte im Fenster"
        assert not befund.heiss
    finally:
        await _raeum_auf(maker, ids)


async def test_ausgemustertes_relais_kommt_nicht_vor(maker: Any) -> None:
    """Lebenszyklus-Filter, Paragraph 5.58."""
    ids = await _baue(maker, ausgemustert=True)
    try:
        befunde = await _lies(maker)
        assert all(b.device_id != ids.relais_id for b in befunde)
    finally:
        await _raeum_auf(maker, ids)


async def test_der_fuehler_der_zone_kommt_nicht_vor(maker: Any) -> None:
    ids = await _baue(maker)
    try:
        befunde = await _lies(maker)
        assert all(b.device_id != ids.fuehler_id for b in befunde)
    finally:
        await _raeum_auf(maker, ids)


async def test_relais_mit_schutzsperre_wird_trotzdem_geprueft(maker: Any) -> None:
    """Nach einer Ausloesung ist das Gehaeuse **genau dann** warm.

    Der Zonen-Melder filtert auf ``darf_schalten`` und laesst ein
    gesperrtes Relais aus. Hier waere das falsch — die Begruendung steht
    im Modulkopf des Melders.
    """
    ids = await _baue(maker, sperre=True)
    try:
        assert _eigenes(await _lies(maker), ids).heiss
    finally:
        await _raeum_auf(maker, ids)


# ---------------------------------------------------------------------------
# Der Task: Episode, einmal je Ereignis, Entwarnung
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
def kein_mailversand(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Mitschreiber statt Versand. Die Texte haben ihre eigenen Tests."""
    betreffe: list[str] = []

    def _send(*, recipient: str | None, subject: str, body: str) -> Any:
        from heizung.services.mailer import MailResult

        betreffe.append(subject)
        return MailResult(sent=True, reason=None, detail="test")

    monkeypatch.setattr(gehaeuse_tasks.mailer, "send_mail", _send)
    return betreffe


async def _audit_aktionen(maker: Any, device_id: int) -> list[str]:
    async with maker() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM business_audit "
                    "WHERE target_type = 'device' AND target_id = :d "
                    "ORDER BY ts"
                ),
                {"d": device_id},
            )
        ).all()
    return [r[0] for r in rows]


async def test_der_task_liest_die_mail_schwelle_und_nicht_die_der_karte(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """**Welche der beiden Einstellungen der Task liest, prueft nur dieser Test.**

    Die Urteils-Tests oben geben ``schwelle_mail`` selbst mit — sie
    koennen deshalb nicht merken, wenn der Task die falsche Einstellung
    einsetzt. Aufgefallen ist die Luecke in einer Mutationsprobe am
    21.11.2026: ``relay_gehaeusetemperatur_alarm`` statt ``..._mail``
    liess die ganze reine Testreihe gruen (Paragraph 5.55 — ein Posten,
    der nichts bewacht).

    Der Aufbau ist der gemessene Lastwert von 110. Mit der richtigen
    Einstellung (50) liegt er im Totband und erzeugt **nichts**; mit der
    Schwelle der Karte (40) waere es ein Alarm — also genau die taegliche
    Mail, die diese Aenderung verhindern soll.
    """
    ids = await _baue(maker, temperaturen=(LASTWERT_110, LASTWERT_110, LASTWERT_110 - 1))
    try:
        ergebnis = await gehaeuse_tasks._run_gehaeuse()
        assert all(a["device_id"] != ids.relais_id for a in ergebnis["aktionen"])
        assert await _audit_aktionen(maker, ids.relais_id) == [], (
            "der Lastwert von 110 hat eine Episode erzeugt — liest der Task die Schwelle der Karte?"
        )
        assert kein_mailversand == []
    finally:
        await _raeum_auf(maker, ids)


async def test_episode_meldet_einmal_und_wiederholt_nicht(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Einmal je Ereignis — die Vorgabe des Betreibers vom 18.11.2026.

    Der Melder laeuft im Zehn-Minuten-Takt. Ohne diese Bedingung waeren
    das sechs Mails je Stunde, und ein Melder, der so oft meldet, wird
    abgeschaltet statt gelesen (Paragraph 5.79).
    """
    ids = await _baue(maker)
    try:
        erst = await gehaeuse_tasks._run_gehaeuse()
        assert erst["relais_warm"] >= 1

        zweit = await gehaeuse_tasks._run_gehaeuse()
        dritt = await gehaeuse_tasks._run_gehaeuse()

        aktionen = await _audit_aktionen(maker, ids.relais_id)
        assert aktionen == [gehaeuse_tasks.AUDIT_GEHAEUSE_WARM], (
            f"die Episode hat mehr als eine Zeile erzeugt: {aktionen}"
        )
        for lauf in (zweit, dritt):
            assert all(a["device_id"] != ids.relais_id for a in lauf["aktionen"]), (
                "ein Folgelauf hat noch einmal gemeldet"
            )
    finally:
        await _raeum_auf(maker, ids)


async def test_rueckkehr_erzeugt_die_entwarnung(maker: Any, kein_mailversand: list[str]) -> None:
    """Ein Alarm ohne Entwarnung laesst den Empfaenger im Ungewissen."""
    ids = await _baue(maker)
    try:
        await gehaeuse_tasks._run_gehaeuse()
        assert await _audit_aktionen(maker, ids.relais_id) == [gehaeuse_tasks.AUDIT_GEHAEUSE_WARM]

        # Drei kuehle Meldungen oben drauf — die alten rutschen aus dem
        # Urteil, weil es nur die drei juengsten nimmt.
        jetzt = datetime.now(tz=UTC)
        async with maker() as session:
            for i, wert in enumerate((36, 37, 38)):
                session.add(
                    RelayReading(
                        device_id=ids.relais_id,
                        time=jetzt + timedelta(seconds=10 + i),
                        relay_on=False,
                        power_w=0,
                        internal_temperature_raw=wert,
                    )
                )
            await session.commit()

        await gehaeuse_tasks._run_gehaeuse()
        assert await _audit_aktionen(maker, ids.relais_id) == [
            gehaeuse_tasks.AUDIT_GEHAEUSE_WARM,
            gehaeuse_tasks.AUDIT_GEHAEUSE_WARM_ENDE,
        ]
    finally:
        await _raeum_auf(maker, ids)


async def test_ohne_vorherigen_alarm_keine_entwarnung(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Eine Entwarnung ohne Alarm waere eine Mail ueber nichts."""
    ids = await _baue(maker, temperaturen=(30, 31, 32))
    try:
        await gehaeuse_tasks._run_gehaeuse()
        assert await _audit_aktionen(maker, ids.relais_id) == []
        assert kein_mailversand == []
    finally:
        await _raeum_auf(maker, ids)


async def test_waehrend_der_episode_verstummen_entwarnt_nicht(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Ein Relais, das nichts mehr sagt, ist nicht abgekuehlt.

    Die Werte sind da, aber veraltet — dann bleibt die Episode stehen.
    Die Gegenprobe zu ``kuehl`` als „nicht heiss" (Paragraph 5.68).
    """
    ids = await _baue(maker)
    try:
        await gehaeuse_tasks._run_gehaeuse()
        async with maker() as session:
            await session.execute(
                text(
                    "UPDATE relay_reading SET time = time - interval '90 minutes' "
                    "WHERE device_id = :d"
                ),
                {"d": ids.relais_id},
            )
            await session.commit()

        await gehaeuse_tasks._run_gehaeuse()
        assert await _audit_aktionen(maker, ids.relais_id) == [
            gehaeuse_tasks.AUDIT_GEHAEUSE_WARM
        ], "ein verstummtes Relais wurde entwarnt"
    finally:
        await _raeum_auf(maker, ids)


async def test_der_zustand_haengt_am_geraet_und_nicht_am_haus(
    maker: Any, kein_mailversand: list[str]
) -> None:
    """Zwei Relais, zwei Episoden.

    Eine gemeinsame Marke wuerde die Entwarnung des einen auf das andere
    uebertragen — genau der Fall vom 18.11.2026, an dem ein Relais warm
    war und das andere nicht.
    """
    heiss = await _baue(maker)
    kuehl = await _baue(maker, temperaturen=(30, 31, 32))
    try:
        await gehaeuse_tasks._run_gehaeuse()
        assert await _audit_aktionen(maker, heiss.relais_id) == [gehaeuse_tasks.AUDIT_GEHAEUSE_WARM]
        assert await _audit_aktionen(maker, kuehl.relais_id) == []
    finally:
        await _raeum_auf(maker, kuehl)
        await _raeum_auf(maker, heiss)
