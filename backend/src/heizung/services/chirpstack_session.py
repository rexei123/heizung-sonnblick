"""``tx_power_index`` aus der ChirpStack-Geraetesitzung lesen.

**Warum es diesen Umweg gibt.** Die Leistungsstufe eines Geraets
(``tx_power_index``, 0 = volle Leistung) steht bisher in **keiner**
Datenbank von uns. RUNBOOK §10av Schritt 6a liest sie aus dem jeweils
letzten ``LinkADRReq acknowledged`` in ``docker logs
deploy-chirpstack-1`` — und das hat drei Maengel, die am 16.11.2026
gemessen wurden:

1. **ADR protokolliert nur, wenn es etwas aendert.** Ist die Leistung
   eines Geraets eingeschwungen, kommt tagelang keine neue Zeile. In
   21,8 Stunden Protokoll standen Acks von **55** Geraeten — die
   Sitzung kennt **109**.
2. **Eine Neuerstellung des Containers legt ein leeres Protokoll an.**
   Danach ist die Vorgeschichte weg, unabhaengig von jeder Grenze.
3. Das Protokoll waechst mit 79,3 MB/Tag, wovon 0,19 % diese Zeilen
   sind (PR #422, ``infra/deploy/docker/README.md``).

**Warum nicht aus dem Uplink.** Geprueft am Protobuf-Schema von
ChirpStack 4.17 (``api/proto/integration/integration.proto``):
``UplinkEvent`` hat 16 Felder — ``adr``, ``dr``, ``f_cnt``, ``tx_info``,
``rx_info`` und weitere — aber **keines** mit der Sendeleistung des
Geraets. Das ist keine Luecke im Schema, sondern Physik: das Gateway
kann die Sendeleistung des Geraets nicht messen. Nur der Netzserver
kennt sie, weil er sie selbst befohlen hat.

**Wo sie steht.** In ``internal.DeviceSession``, Feld **24**
(``api/proto/internal/internal.proto``: ``uint32 tx_power_index = 24;``,
Nachbarfelder ``nb_trans = 23``, ``dr = 25``). ChirpStack 4 haelt diese
Nachricht protobuf-serialisiert in der Spalte ``device.device_session``
(``bytea``) seiner eigenen Postgres-Instanz.

**Die Zusicherung dieses Moduls ist, dass es nur liest.** Ein
``SELECT`` auf eine Tabelle eines anderen Dienstes, keine Steuerleitung
zur Hardware — AE-48 und CLAUDE.md §5.28 verbieten einen zweiten
Befehlsweg (gRPC fuer Downlinks), nicht einen lesenden Datenpfad.
Geschrieben wird ausschliesslich in **unsere** Spalten.

**Und das Zweite, das hier Zusicherung ist: die Sitzungsdaten enthalten
Schluesselmaterial.** In derselben Nachricht stehen ``nwk_s_enc_key``,
``app_s_key`` und die Frame-Counter. Deshalb trifft dieses Modul die
Rohbytes nie in einer Meldung, einem Log oder einer Ausnahme — Fehler
nennen die DevEUI und eine Position, nie den Inhalt. ``test_keine_bytes
_in_der_fehlermeldung`` haelt das fest.

**Kein Protobuf-Paket als Abhaengigkeit.** Gelesen wird genau ein
Varint-Feld auf oberster Ebene; dafuer braucht es keinen Compiler und
keine ``chirpstack-api``-Abhaengigkeit im API-Image (dieselbe
Begruendung wie in ``infra/chirpstack/requirements-provision.txt``). Der
Parser laeuft die obersten Felder ab und ueberspringt alles, was er
nicht braucht — er darf die Bytes nicht nach dem Schluessel
*durchsuchen*, weil dieselbe Bytefolge in einem verschachtelten Feld
vorkommen kann.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from heizung.models.device import Device

logger = logging.getLogger(__name__)

#: Feldnummer von ``tx_power_index`` in ``internal.DeviceSession``
#: (ChirpStack 4.17). Eine Zahl aus einem **internen** Schema: sie ist
#: nicht Teil der oeffentlichen API und kann sich mit einer Hauptversion
#: aendern. Deshalb prueft ``leistungsstufe`` den Wertebereich, und
#: deshalb schreibt der Task bei unlesbaren Daten nichts statt zu raten.
FELD_TX_POWER_INDEX = 24

#: ``LinkADRReq`` traegt die Leistungsstufe in 4 Bit (LoRaWAN 1.0.x,
#: Region EU868: 0..7 belegt). Ein Wert darueber heisst, dass hier nicht
#: das Feld gelesen wurde, das gemeint war — etwa nach einem
#: Schemawechsel.
MAX_TX_POWER_INDEX = 15


class SitzungUnlesbarError(ValueError):
    """Die Sitzungsbytes passen nicht zum erwarteten Protobuf-Aufbau.

    Die Meldung enthaelt **nie** Bytes aus der Sitzung (Schluesselmaterial).
    """


@dataclass(frozen=True)
class Leseergebnis:
    """Was ein Lauf gegen die ChirpStack-Datenbank gefunden hat."""

    #: DevEUI (hex, klein) -> ``tx_power_index``.
    stufen: dict[str, int] = field(default_factory=dict)
    #: DevEUIs, deren Sitzung nicht gelesen werden konnte. Nur die EUI.
    unlesbar: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Uebernahmebericht:
    """Was davon in unsere Spalten gelandet ist."""

    gelesen: int = 0
    zugeordnet: int = 0
    unbekannt: int = 0
    unlesbar: int = 0


def _varint(roh: bytes, i: int) -> tuple[int, int]:
    wert = 0
    schritt = 0
    while True:
        if i >= len(roh):
            raise SitzungUnlesbarError(f"Varint reicht ueber das Ende hinaus (Position {i})")
        byte = roh[i]
        i += 1
        wert |= (byte & 0x7F) << schritt
        if not byte & 0x80:
            return wert, i
        schritt += 7
        if schritt > 63:
            raise SitzungUnlesbarError(f"Varint laenger als 64 Bit (Position {i})")


def _oberste_felder(roh: bytes) -> Iterator[tuple[int, int | None]]:
    """Laeuft die obersten Protobuf-Felder ab.

    Liefert ``(Feldnummer, Wert)``; der Wert ist nur bei Varint-Feldern
    gesetzt, alles andere wird uebersprungen. Ein Durchlauf, keine Suche:
    die Bytefolge des Schluessels von Feld 24 kann auch im Inneren eines
    laengenpraefixierten Feldes stehen, und eine Suche wuerde dort
    fuendig.
    """
    i = 0
    while i < len(roh):
        schluessel, i = _varint(roh, i)
        nummer, typ = schluessel >> 3, schluessel & 7
        if nummer == 0:
            raise SitzungUnlesbarError(f"Feldnummer 0 (Position {i})")
        if typ == 0:
            wert, i = _varint(roh, i)
            yield nummer, wert
        elif typ == 1:
            i += 8
        elif typ == 2:
            laenge, i = _varint(roh, i)
            i += laenge
        elif typ == 5:
            i += 4
        else:
            raise SitzungUnlesbarError(f"Wire-Typ {typ} nicht verwendbar (Position {i})")
        if i > len(roh):
            raise SitzungUnlesbarError(f"Feld reicht ueber das Ende hinaus (Position {i})")


def leistungsstufe(roh: bytes) -> int:
    """``tx_power_index`` aus den Sitzungsbytes.

    **Fehlt das Feld, ist die Antwort 0 und nicht „unbekannt".** Protobuf
    laesst Felder mit dem Standardwert weg, und 0 ist hier ein echter
    Wert — volle Sendeleistung. Am 16.11.2026 betraf das 16 der 109
    Geraete; genau diese 16 hat auch das Protokoll mit
    ``tx_power_index=0`` gezeigt (15 davon innerhalb seiner 21,8
    Stunden). Wer „fehlt" als NULL schreibt, verliert die Gruppe, die
    am dichtesten am Gateway sitzt.
    """
    for nummer, wert in _oberste_felder(roh):
        if nummer == FELD_TX_POWER_INDEX and wert is not None:
            if wert > MAX_TX_POWER_INDEX:
                raise SitzungUnlesbarError(
                    f"tx_power_index {wert} liegt ueber {MAX_TX_POWER_INDEX} — "
                    "das gelesene Feld ist nicht das gemeinte"
                )
            return wert
    return 0


#: Nur lesen, und nur die zwei Spalten, die gebraucht werden. Kein
#: ``select *`` — die Zeile enthaelt Schluesselmaterial, und was nicht
#: geholt wird, kann auch nicht versehentlich protokolliert werden.
SQL_SITZUNGEN = text(
    "select encode(dev_eui, 'hex') as dev_eui, device_session "
    "from device where device_session is not null"
)


async def lies_aus_chirpstack(dsn: str) -> Leseergebnis:
    """Liest die Leistungsstufen aller Geraete aus ChirpStacks Postgres.

    Eine unlesbare Sitzung laesst den Lauf **nicht** scheitern: sie wird
    gezaehlt und uebersprungen. Ein Geraet, dessen Bytes nicht passen,
    darf die 108 anderen nicht mitnehmen.
    """
    engine = create_async_engine(dsn, echo=False, pool_pre_ping=False, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as verbindung:
            zeilen = (await verbindung.execute(SQL_SITZUNGEN)).all()
    finally:
        await engine.dispose()

    stufen: dict[str, int] = {}
    unlesbar: list[str] = []
    for dev_eui, sitzung in zeilen:
        eui = str(dev_eui).lower()
        try:
            stufen[eui] = leistungsstufe(bytes(sitzung))
        except SitzungUnlesbarError as fehler:
            # Die EUI und der Grund, nie die Bytes.
            logger.warning("Sitzung von %s nicht lesbar: %s", eui, fehler)
            unlesbar.append(eui)
    return Leseergebnis(stufen=stufen, unlesbar=unlesbar)


async def uebernehme(
    session: AsyncSession,
    ergebnis: Leseergebnis,
    jetzt: datetime,
) -> Uebernahmebericht:
    """Schreibt die Stufen an unsere aktiven Geraete.

    ``tx_power_index_at`` wird bei **jedem** Lauf gesetzt, auch wenn der
    Wert gleich bleibt: die Spalte beantwortet „wie frisch ist diese
    Auskunft", nicht „wann hat sich etwas geaendert". Ein Wert ohne
    Zeitstempel waere genau die Annahme, die §0 S5 verbietet.

    Committet **nicht** — das tut der Aufrufer, wie bei
    ``record_business_action``.
    """
    if not ergebnis.stufen:
        return Uebernahmebericht(unlesbar=len(ergebnis.unlesbar))

    treffer = (
        await session.execute(
            select(Device).where(
                Device.retired_at.is_(None),
                func.lower(Device.dev_eui).in_(ergebnis.stufen.keys()),
            )
        )
    ).scalars()

    zugeordnet = 0
    for geraet in treffer:
        stufe = ergebnis.stufen.get(geraet.dev_eui.lower())
        if stufe is None:
            continue
        geraet.tx_power_index = stufe
        geraet.tx_power_index_at = jetzt
        zugeordnet += 1

    await session.flush()
    return Uebernahmebericht(
        gelesen=len(ergebnis.stufen),
        zugeordnet=zugeordnet,
        unbekannt=len(ergebnis.stufen) - zugeordnet,
        unlesbar=len(ergebnis.unlesbar),
    )
