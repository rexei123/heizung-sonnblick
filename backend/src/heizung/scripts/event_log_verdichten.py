r"""event_log verdichten — Trockenlauf als Standard (27.11.2026).

**Wofuer.** ``event_log`` waechst um rund **4,8 GB im Monat** (gemessen
14.11.2026). Am 13.11. war die Platte zu 94 Prozent belegt, und gefunden
wurde das beim Nachsehen nach etwas anderem. Bei 100 Prozent nimmt
Postgres keine Schreibvorgaenge mehr an: keine Messwerte, keine
Engine-Auswertung, keine Relais-Bestaetigungen.

Aufruf (Prod-Container heisst ``deploy-api-1``):

    docker exec deploy-api-1 python -m heizung.scripts.event_log_verdichten
    docker exec deploy-api-1 python -m heizung.scripts.event_log_verdichten --ausfuehren
    docker exec deploy-api-1 python -m heizung.scripts.event_log_verdichten --zuruecknehmen

**PowerShell (lokal)**, mit der ``srv``-Funktion aus RUNBOOK Paragraph 4:

    srv 'docker exec deploy-api-1 python -m heizung.scripts.event_log_verdichten'

Verdichten, nicht loeschen
--------------------------

Die naheliegende Antwort auf eine grosse Tabelle ist, alte Zeilen
wegzuwerfen. Das waere hier ein **S3-Verstoss**: der Engine-Trace ist das
Protokoll jeder Sollwert-Entscheidung, und ein Protokoll mit Loechern
beantwortet die Frage „warum war das Zimmer kalt" nicht mehr.

TimescaleDB kann die Chunks einer Hypertable **spaltenweise** ablegen.
Keine Zeile geht verloren, Abfragen lesen weiter, und die Form dieser
Daten verdichtet aussergewoehnlich gut: der immer gleiche JSONB-Kontext
steht nach der Umstellung einmal statt tausendmal.

**Gemessen in der Vorpruefung vom 27.11.2026** (eigene Datenbank,
dasselbe Image ``timescale/timescaledb:latest-pg16``, TimescaleDB 2.26.3,
6 Millionen Zeilen in der Form des Betriebs): **148 MB je Chunk vor der
Verdichtung, 2,6 MB danach — Faktor 57**. Lesen aus einem verdichteten
Chunk: unveraendert. Schreiben in den jungen Chunk: unveraendert.

**Das ist eine Messung an nachgebauten Daten, keine Zusage fuer die
Anlage.** Der Trockenlauf unten nennt deshalb den Faktor, den **diese**
Datenbank bereits erreicht hat, sobald der erste echte Lauf gelaufen ist —
und bis dahin sagt er, dass er ihn nicht kennt (Paragraph 5.68).

Was dieses Werkzeug nicht tut
-----------------------------

* **Es laeuft nicht von selbst.** Kein Beat-Eintrag, keine
  ``add_compression_policy``, kein Aufruf aus einer Migration — ein Lauf
  nach dem Merge war ausdruecklich nicht gewollt. Wer die Verdichtung
  dauerhaft will, entscheidet das getrennt; der Platz dafuer ist eine
  Policy, und sie gehoert in einen eigenen PR.
* **Es loescht nichts.** Keine Zeile, kein Chunk, keine Tabelle.
* **Es faellt nicht ueber einen bereits verdichteten Chunk.** Der Lauf ist
  wiederholbar; schon verdichtete Chunks werden uebersprungen und
  gezaehlt.

Der Rueckweg
------------

``--zuruecknehmen`` packt alle verdichteten Chunks wieder aus. Das ist
derselbe Weg, den die Datenbank beim Lesen ohnehin geht, nur dauerhaft —
und er ist der Grund, warum dieser Schritt in ein Wartungsfenster
gehoert, in dem jemand am Rechner sitzt: ausgepackt braucht die Tabelle
wieder ihren vollen Platz, und der muss frei sein.

Ein Hinweis zur Sicherung
-------------------------

Die Verdichtung schreibt die Chunks neu. Vorher gehoert eine Sicherung
dazu — nicht weil der Vorgang als unsicher gilt, sondern weil er die
Tabelle anfasst, in der das Protokoll der Steuerung steht. Die Schritte
stehen im RUNBOOK (Paragraph 10bh).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.db import SessionLocal

#: Die Tabelle. Als Konstante, damit der Name einmal im Modul steht —
#: und nicht in sechs Abfragen.
TABELLE = "event_log"

#: Chunks, die **juenger** sind, bleiben unangetastet. Das Chunk-Intervall
#: ist sieben Tage (Migration 0003b); mit 14 bleiben der laufende und der
#: vorige Chunk unverdichtet. Beide werden noch beschrieben — der laufende
#: ohnehin, der vorige, solange eine Auswertung mit altem Zeitstempel
#: nachkommt.
#:
#: Verdichtete Chunks nehmen in TimescaleDB 2.26 auch Einfuegungen an. Die
#: Grenze ist trotzdem da, weil ein Einfuegen in einen verdichteten Chunk
#: teurer ist als in einen normalen, und weil dieses Werkzeug nicht
#: entscheiden soll, wie teuer der laufende Betrieb sein darf.
VORGABE_TAGE = 14


@dataclass(frozen=True, slots=True)
class ChunkStand:
    """Ein Chunk und was wir ueber ihn wissen."""

    name: str
    bytes_gesamt: int
    verdichtet: bool


async def _hypertable_vorhanden(session: AsyncSession) -> bool:
    """Ob ``event_log`` in dieser Datenbank eine Hypertable ist.

    **Geprueft und nicht angenommen.** Ohne TimescaleDB-Erweiterung gibt
    es die Katalogsicht nicht, und die Fehlermeldung von Postgres
    („relation does not exist") sagt dann etwas anderes, als los ist.
    """
    da = await session.scalar(
        text("SELECT to_regclass('timescaledb_information.hypertables') IS NOT NULL")
    )
    if not da:
        return False
    return bool(
        await session.scalar(
            text(
                "SELECT count(*) > 0 FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = :t"
            ),
            {"t": TABELLE},
        )
    )


async def lies_chunks(session: AsyncSession, *, aelter_als_tage: int) -> list[ChunkStand]:
    """Die Chunks jenseits der Grenze, mit Groesse und Zustand.

    ``show_chunks`` liefert die Namen, ``chunks_detailed_size`` die Bytes
    und ``timescaledb_information.chunks`` das Kennzeichen, ob ein Chunk
    schon verdichtet ist. Drei Quellen, **eine** Abfrage: zwei Abfragen
    waeren zwei Zeitpunkte, und zwischen ihnen kann ein Chunk entstehen.
    """
    zeilen = (
        await session.execute(
            text("""
            SELECT c.chunk_schema || '.' || c.chunk_name AS name,
                   c.is_compressed AS verdichtet,
                   coalesce(d.total_bytes, 0) AS bytes_gesamt
            FROM timescaledb_information.chunks c
            LEFT JOIN LATERAL (
                SELECT sum(total_bytes) AS total_bytes
                FROM chunks_detailed_size(
                    format('%I.%I', c.chunk_schema, c.chunk_name)::regclass)
            ) d ON true
            WHERE c.hypertable_name = :t
              AND c.range_end < now() - make_interval(days => :tage)
            ORDER BY c.range_end
            """),
            {"t": TABELLE, "tage": aelter_als_tage},
        )
    ).all()
    return [
        ChunkStand(
            name=str(z.name),
            bytes_gesamt=int(z.bytes_gesamt or 0),
            verdichtet=bool(z.verdichtet),
        )
        for z in zeilen
    ]


async def lies_faktor(session: AsyncSession) -> tuple[int, int] | None:
    """Was diese Datenbank bisher erreicht hat: (vorher, nachher) in Bytes.

    ``None``, solange **kein** Chunk verdichtet ist. Dann gibt es keinen
    Faktor, und eine Zahl aus der Vorpruefung hier auszugeben hiesse, eine
    Messung an nachgebauten Daten als Befund dieser Anlage auszugeben
    (Paragraph 5.68).
    """
    zeile = (
        await session.execute(
            text(
                "SELECT sum(before_compression_total_bytes) AS vorher, "
                "       sum(after_compression_total_bytes) AS nachher "
                "FROM chunk_compression_stats(:t)"
            ),
            {"t": TABELLE},
        )
    ).first()
    if zeile is None or zeile.vorher is None or not zeile.nachher:
        return None
    return int(zeile.vorher), int(zeile.nachher)


def _mb(bytes_: int) -> str:
    return f"{bytes_ / 1024 / 1024:,.1f} MB".replace(",", " ")


async def _trockenlauf(session: AsyncSession, *, tage: int) -> int:
    chunks = await lies_chunks(session, aelter_als_tage=tage)
    offen = [c for c in chunks if not c.verdichtet]
    schon = [c for c in chunks if c.verdichtet]

    print("\nTrockenlauf. Es wird **nichts** geaendert.\n")
    print(f"  Tabelle:            {TABELLE}")
    print(f"  Grenze:             Chunks, die vor mehr als {tage} Tagen endeten")
    print(f"  Chunks jenseits:    {len(chunks)}")
    print(f"  davon verdichtet:   {len(schon)}")
    print(f"  davon offen:        {len(offen)}")
    print(f"  Platz der offenen:  {_mb(sum(c.bytes_gesamt for c in offen))}")

    faktor = await lies_faktor(session)
    if faktor is None:
        print(
            "\n  Faktor dieser Datenbank: **unbekannt** — es ist noch kein Chunk\n"
            "  verdichtet. Die Vorpruefung vom 27.11.2026 hat an nachgebauten\n"
            "  Daten Faktor 57 gemessen; das ist kein Befund dieser Anlage."
        )
    else:
        vorher, nachher = faktor
        print(
            f"\n  Faktor dieser Datenbank: {vorher / nachher:.1f} "
            f"({_mb(vorher)} -> {_mb(nachher)}, aus den schon verdichteten Chunks)"
        )

    if not offen:
        print("\n  Nichts zu tun.")
        return 0
    print("\n  Mit --ausfuehren werden die offenen Chunks verdichtet.")
    print("  Vorher die Sicherung nach RUNBOOK Paragraph 10bh.")
    return 0


async def _schalte_verdichtung_ein(session: AsyncSession) -> None:
    """Setzt die Verdichtungs-Eigenschaften der Hypertable, einmalig.

    ``segmentby = room_id``: die Abfragen dieser Tabelle lesen „alle
    Eintraege eines Zimmers im Zeitraum" (Index ``ix_event_log_room_time``,
    Engine-Trace-Panel, ``room_history``). Wer danach segmentiert, packt
    zum Lesen nur die Segmente eines Zimmers aus.

    ``orderby`` nennt **alle** uebrigen Spalten des Primaerschluessels.
    Ohne sie warnt TimescaleDB („column ... should be used for segmenting
    or ordering"), und die Warnung hat einen Grund: der Schluessel ist
    ``(time, room_id, evaluation_id, layer)``, und eine Eindeutigkeit, die
    die Datenbank nach der Verdichtung nicht mehr pruefen kann, ist keine.
    Die Vorpruefung hat beide Formen gemessen: Faktor 58,6 ohne, 57,2 mit —
    der Unterschied ist kleiner als der Grund.
    """
    await session.execute(
        text(f"""
        ALTER TABLE {TABELLE} SET (
            timescaledb.compress,
            timescaledb.compress_segmentby = 'room_id',
            timescaledb.compress_orderby = 'time DESC, evaluation_id, layer'
        )
        """)  # noqa: S608 — ``TABELLE`` ist eine Modulkonstante, keine Eingabe
    )


async def _ausfuehren(session: AsyncSession, *, tage: int) -> int:
    chunks = await lies_chunks(session, aelter_als_tage=tage)
    offen = [c for c in chunks if not c.verdichtet]
    if not offen:
        print("\nNichts zu tun: jenseits der Grenze ist kein offener Chunk.")
        return 0

    print(f"\nEchter Lauf. {len(offen)} Chunk(s), {_mb(sum(c.bytes_gesamt for c in offen))}.")
    await _schalte_verdichtung_ein(session)

    gewonnen = 0
    for c in offen:
        vorher = c.bytes_gesamt
        # ``compress_chunk`` ist je Chunk eine eigene Transaktion wert:
        # bricht einer ab, bleiben die vorherigen verdichtet. Ein Lauf,
        # der alles oder nichts macht, waere bei zwanzig Chunks ein
        # Alles-oder-nichts ueber Stunden.
        await session.execute(text("SELECT compress_chunk(:c)"), {"c": c.name})
        await session.commit()
        nachher = (
            await session.scalar(
                text("SELECT sum(total_bytes) FROM chunks_detailed_size(cast(:c AS regclass))"),
                {"c": c.name},
            )
            or 0
        )
        gewonnen += vorher - int(nachher)
        print(f"  {c.name}: {_mb(vorher)} -> {_mb(int(nachher))}")

    print(f"\nFrei geworden: {_mb(gewonnen)}")
    print("Die Zeilen sind **alle** noch da; Abfragen lesen unveraendert.")
    return 0


async def _zuruecknehmen(session: AsyncSession, *, tage: int) -> int:
    """Packt die verdichteten Chunks wieder aus — der Rueckweg.

    **Er braucht Platz.** Ausgepackt belegt die Tabelle wieder ihre volle
    Groesse; wer zurueckgeht, prueft vorher ``df``.
    """
    chunks = await lies_chunks(session, aelter_als_tage=tage)
    verdichtet = [c for c in chunks if c.verdichtet]
    if not verdichtet:
        print("\nNichts zurueckzunehmen: kein verdichteter Chunk jenseits der Grenze.")
        return 0

    faktor = await lies_faktor(session)
    if faktor is not None:
        vorher, nachher = faktor
        print(f"\nAchtung: ausgepackt braucht es wieder rund {_mb(vorher)} statt {_mb(nachher)}.")
    print(f"{len(verdichtet)} Chunk(s) werden ausgepackt.")
    for c in verdichtet:
        await session.execute(text("SELECT decompress_chunk(:c)"), {"c": c.name})
        await session.commit()
        print(f"  {c.name}: ausgepackt")
    return 0


async def _lauf(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        if not await _hypertable_vorhanden(session):
            print(
                f"'{TABELLE}' ist in dieser Datenbank keine TimescaleDB-Hypertable.\n"
                "Ohne Hypertable gibt es keine Chunks und nichts zu verdichten."
            )
            return 2
        if args.zuruecknehmen:
            return await _zuruecknehmen(session, tage=args.aelter_als_tage)
        if args.ausfuehren:
            return await _ausfuehren(session, tage=args.aelter_als_tage)
        return await _trockenlauf(session, tage=args.aelter_als_tage)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="event_log_verdichten",
        description=("Verdichtet alte Chunks von event_log. Ohne --ausfuehren wird nur gezaehlt."),
    )
    parser.add_argument(
        "--ausfuehren",
        action="store_true",
        help="Wirklich verdichten. Ohne diesen Schalter wird nichts geaendert.",
    )
    parser.add_argument(
        "--zuruecknehmen",
        action="store_true",
        help="Rueckweg: verdichtete Chunks wieder auspacken. Braucht den Platz zurueck.",
    )
    parser.add_argument(
        "--aelter-als-tage",
        type=int,
        default=VORGABE_TAGE,
        help=f"Nur Chunks, die vor mehr als N Tagen endeten. Vorgabe {VORGABE_TAGE}.",
    )
    args = parser.parse_args()
    if args.ausfuehren and args.zuruecknehmen:
        # Beides zusammen ist kein Lauf, sondern ein Tippfehler — und ein
        # Tippfehler, der die Tabelle zweimal anfasst.
        print("--ausfuehren und --zuruecknehmen zusammen ergeben keinen Lauf.")
        return 2
    if args.aelter_als_tage < 7:
        # Sieben Tage ist das Chunk-Intervall. Darunter liegt der
        # laufende Chunk, in den die Engine jede Minute schreibt.
        print("--aelter-als-tage unter 7 trifft den laufenden Chunk. Abgebrochen.")
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return _verteile(args)


def _verteile(args: argparse.Namespace) -> int:
    """Startet den Lauf — und nur das (Paragraph 5.14, zweiter Event-Loop)."""
    return asyncio.run(_lauf(args))


if __name__ == "__main__":
    sys.exit(main())
