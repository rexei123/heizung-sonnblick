r"""Einmal-Backfill fuer ``device.mounted_confirmed_at`` (Sprint 20e, T2).

Migration 0027 legt die Spalte **ohne** Backfill an. Dieses Skript holt ihn
nach, weil er ein **fachliches Urteil** ist und damit nicht in eine Migration
gehoert: eine Migration laeuft genau einmal und ist nicht wiederholbar, dieses
Urteil muss man nachrechnen und notfalls erneut faellen koennen (§5.61).

**Warum er ueberhaupt gebraucht wird.** Ohne Backfill traegt jedes heute
montierte Geraet ``NULL``, bis der naechste Frame beide Bedingungen zeigt —
und ``valve_position > 0`` setzt eine Heizanforderung voraus. Im Uebergang
zwischen Montage und Heizperiode kann das Wochen dauern. Genau in dieser Zeit
soll Layer 4 die Geraete aber schon aus der Detached-Pruefung nehmen; sonst
bringt 20e nichts fuer die Geraete, um die es geht.

**Das Urteil, und wo es von T3 abweicht.** Der Subscriber (T3) verlangt beide
Merkmale im **selben** Frame. Dieses Skript laesst sie in **verschiedenen**
Frames derselben Historie gelten:

    - irgendwann ein Frame mit ``attached_backplate = true``
    - irgendwann ein Frame mit ``valve_position > 0``

Das ist absichtlich schwaecher, und der Grund ist ein Zeitproblem, kein
Bequemlichkeitsgrund: ``attached_backplate`` wird erst seit Sprint 9.11x
persistiert (Migration 0013), ``valve_position`` seit 0002. Fuer die
Pilotgeraete gibt es Zeitraeume, in denen nur eines der beiden Felder
ueberhaupt geschrieben wurde — eine Gleichzeitigkeits-Bedingung wuerde sie
nicht wegen ihres Zustands ausschliessen, sondern wegen unseres Schemas.

Die Gegenprobe gegen den naheliegenden Einwand ("beide Merkmale einzeln kann
auch ein Geraet auf dem Tisch zeigen"): das Skript betrachtet nur Geraete mit
``heating_zone_id IS NOT NULL``. Ein zugeordnetes Geraet, das in seiner
Historie den Taster gedrueckt **und** den Motor geoeffnet hatte, war montiert
— ein Pool-Geraet auf dem Werkstatt-Tisch ist nicht zugeordnet.

**Als Zeitstempel gilt der spaetere der beiden ersten Belege.** Also der
Augenblick, ab dem **beide** Merkmale gezeigt waren. Der frueheste Beleg
waere zu optimistisch (er behauptet Montage zu einem Zeitpunkt, an dem erst
die Haelfte belegt war), der juengste Frame waere beliebig (er hat mit dem
Nachweis nichts zu tun).

**Wiederholbar.** ``WHERE mounted_confirmed_at IS NULL`` steht in der
Auswahl: ein zweiter Lauf fasst nur Geraete an, die noch keinen Nachweis
haben, und ueberschreibt nie einen bestehenden — auch keinen, den der
Subscriber inzwischen gesetzt hat.

Aufruf (Vorschau, schreibt nichts):

    docker compose -f infra/deploy/docker-compose.prod.yml exec api \
      python -m heizung.scripts.backfill_mounted_confirmed

Aufruf (schreibend):

    docker compose -f infra/deploy/docker-compose.prod.yml exec api \
      python -m heizung.scripts.backfill_mounted_confirmed --apply

Die Vorschau ist der Standard, weil das Urteil im Bericht nachvollziehbar
sein soll, **bevor** es in der Datenbank steht. Das Skript nennt je Geraet
die beiden Belegzeitpunkte, damit ein unplausibler Fall auffaellt, statt in
einer Summenzeile zu verschwinden.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

# Siehe ``sync_room_statuses``: nur im direkten CLI-Aufruf, nicht beim Import.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

from dataclasses import dataclass  # noqa: E402
from datetime import datetime  # noqa: E402

from sqlalchemy import func, select, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.sensor_reading import SensorReading  # noqa: E402

logger = logging.getLogger("backfill_mounted_confirmed")


@dataclass(frozen=True, slots=True)
class Befund:
    """Ein Geraet mit beiden Belegen — und wann sie zuerst da waren."""

    device_id: int
    label: str | None
    dev_eui: str
    erster_taster: datetime
    erstes_ventil: datetime

    @property
    def nachweis_ab(self) -> datetime:
        """Der spaetere der beiden Belege: ab hier war beides gezeigt."""
        return max(self.erster_taster, self.erstes_ventil)


async def ermittle(session: AsyncSession) -> list[Befund]:
    """Kandidaten mit beiden Belegen suchen. Liest nur, schreibt nichts.

    **Eine Aggregat-Query, nicht eine je Geraet.** Zwei ``MIN``-Aggregate mit
    ``FILTER`` ueber denselben Scan; der Index
    ``ix_sensor_reading_device_time`` traegt die Gruppierung. Eine Variante
    mit ``EXISTS`` je Geraet und Merkmal waere bei 104 Geraeten 208
    Teilabfragen gegen eine Hypertable — und das Ergebnis muesste trotzdem
    ein zweites Mal nach dem Zeitstempel fragen.

    Der ``JOIN`` auf ``device`` filtert vor der Gruppierung: ohne Zuordnung
    und ohne ``retired_at IS NULL`` kein Nachweis, und ``mounted_confirmed_at
    IS NULL`` macht den Lauf wiederholbar.
    """
    erster_taster = func.min(SensorReading.time).filter(SensorReading.attached_backplate.is_(True))
    erstes_ventil = func.min(SensorReading.time).filter(SensorReading.valve_position > 0)

    stmt = (
        select(
            Device.id,
            Device.label,
            Device.dev_eui,
            erster_taster.label("erster_taster"),
            erstes_ventil.label("erstes_ventil"),
        )
        .join(SensorReading, SensorReading.device_id == Device.id)
        .where(Device.mounted_confirmed_at.is_(None))
        .where(Device.heating_zone_id.is_not(None))
        .where(Device.retired_at.is_(None))
        .group_by(Device.id, Device.label, Device.dev_eui)
        # Beide Belege muessen existieren. Die Bedingung gehoert ins HAVING
        # und nicht in die WHERE-Klausel: sie urteilt ueber das Aggregat,
        # nicht ueber die einzelne Zeile. Eine Zeile kann nicht gleichzeitig
        # "erster Taster-Frame" und "erster Ventil-Frame" sein.
        .having(erster_taster.is_not(None))
        .having(erstes_ventil.is_not(None))
        .order_by(Device.label)
    )

    rows = (await session.execute(stmt)).all()
    return [
        Befund(
            device_id=row[0],
            label=row[1],
            dev_eui=row[2],
            erster_taster=row[3],
            erstes_ventil=row[4],
        )
        for row in rows
    ]


async def schreibe(session: AsyncSession, befunde: list[Befund]) -> int:
    """Nachweise setzen. Der Aufrufer committet nicht — das tut ``main_async``.

    ``WHERE mounted_confirmed_at IS NULL`` steht erneut in jedem ``UPDATE``,
    obwohl die Auswahl schon danach gefiltert hat. Zwischen Lesen und
    Schreiben liegt die Laufzeit der Vorschau, und in dieser Zeit kann der
    Subscriber denselben Nachweis gesetzt haben. Dessen Zeitstempel ist der
    genauere (ein Frame mit beiden Merkmalen zugleich), also gewinnt er — die
    Bedingung in der Datenbank entscheidet das, nicht die Reihenfolge der
    Prozesse (§5.60).

    Gezaehlt wird ueber ``RETURNING`` und nicht ueber ``rowcount``: dasselbe
    Ergebnis, aber ohne die Typ-Wette aus §5.80 (``rowcount`` liegt je nach
    SQLAlchemy-Fassung auf ``CursorResult`` oder nur auf ``Result[Any]``, und
    der Typechecker urteilt dann in CI anders als lokal). ``replace_device``
    macht es aus demselben Grund so.
    """
    geschrieben = 0
    for b in befunde:
        result = await session.execute(
            update(Device)
            .where(Device.id == b.device_id)
            .where(Device.mounted_confirmed_at.is_(None))
            .values(mounted_confirmed_at=b.nachweis_ab)
            .returning(Device.id)
        )
        geschrieben += len(result.fetchall())
    return geschrieben


async def main_async(*, apply: bool) -> int:
    async with SessionLocal() as session:
        befunde = await ermittle(session)

        if not befunde:
            print("[OK] Keine Geraete mit beiden Belegen ohne Nachweis gefunden.")
            return 0

        modus = "SCHREIBT" if apply else "VORSCHAU (schreibt nichts)"
        print(f"[{modus}] {len(befunde)} Geraet(e) mit Montage-Nachweis aus der Historie:\n")
        for b in befunde:
            print(
                f"  {b.label or '(ohne Label)':<12} {b.dev_eui}  "
                f"Taster={b.erster_taster.isoformat()}  "
                f"Ventil={b.erstes_ventil.isoformat()}  "
                f"-> Nachweis={b.nachweis_ab.isoformat()}"
            )

        if not apply:
            print("\n[HINWEIS] Nichts geschrieben. Mit --apply erneut aufrufen.")
            return 0

        geschrieben = await schreibe(session, befunde)
        # Direkter Service-Aufruf ausserhalb des FastAPI-Stacks ->
        # expliziter Commit Pflicht (§5.61), sonst Rollback ohne Fehler.
        await session.commit()
        print(f"\n[OK] {geschrieben} Nachweis(e) gesetzt.")
        if geschrieben != len(befunde):
            print(
                f"[HINWEIS] {len(befunde) - geschrieben} Geraet(e) hatten inzwischen "
                "einen Nachweis (vermutlich vom Subscriber) und blieben unberuehrt."
            )
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_mounted_confirmed",
        description="Setzt device.mounted_confirmed_at aus der sensor_reading-Historie.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Tatsaechlich schreiben. Ohne dieses Flag nur Vorschau.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(main_async(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
