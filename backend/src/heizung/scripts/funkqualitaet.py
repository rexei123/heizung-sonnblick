r"""Funkqualitaet eines Geraets ueber ein Zeitfenster (02.11.2026).

**Wofuer.** Relais 109 steht seit dem 02.11.2026 um 07:05 Ortszeit am
Endplatz in der Dose am Eingang — nur Zuleitung, kein Panel,
zurueckgenommen. Nach 12 bis 24 Stunden soll eine Zahl auf dem Tisch
liegen, an der die Entscheidung ueber ein ADR-Plugin haengt (DR3,
``nbTrans`` 2, nur fuer das Profil „Relais 16ASPM"). Vorher zu
entscheiden hiesse, eine Datenrate gegen eine provisorische Position zu
waehlen.

Aufruf (Prod-Container heisst ``deploy-api-1``):

    docker exec <api> python -m heizung.scripts.funkqualitaet \
        --geraet 109 --seit "2026-11-02 07:05"

    docker exec <api> python -m heizung.scripts.funkqualitaet --stunden 24

``--seit`` ist **Ortszeit** (Europe/Vienna), weil der Mensch sie so
aufgeschrieben hat. Ohne Angabe gilt ``--stunden`` (Vorgabe 24).

**Es wird nichts gesendet.** Dieses Werkzeug liest, deshalb hat es
keinen ``--ausfuehren``-Schalter.

Was es NICHT liefert
--------------------

**RSSI und SNR gibt es nur fuer Vickis, DR fuer niemanden.** Die
Empfangsdaten stehen in ``sensor_reading`` (``rssi_dbm``, ``snr_db``);
``relay_reading`` hat diese Spalten nicht, und die Datenrate speichern
wir gar nicht. Fuer ein Relais stehen in den Spalten deshalb Striche und
kein Wert — eine Null waere eine Behauptung ueber einen Funk, den wir
nicht gemessen haben.

Beide Zahlen liegen fuer 109 trotzdem vor, nur nicht bei uns:
**ChirpStack → Device 109 → der Metrik-Reiter** fuehrt RSSI, SNR und die
Verteilung der Datenraten je Stunde. Der Weg steht in RUNBOOK
Paragraph 10au. Die Spalten in ``relay_reading`` nachzuziehen ist eine
additive Migration und ein eigener PR — sie wuerde erst ab dem Einbau
Daten sammeln und kommt fuer diese Messung zu spaet.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

# Siehe ``geraetegrenzen``: der Guard trennt den CLI-Aufruf vom Import
# durch die Tests.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

import asyncio  # noqa: E402

from sqlalchemy import or_, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.device import Device  # noqa: E402
from heizung.models.enums import DeviceKind  # noqa: E402
from heizung.models.sensor_reading import SensorReading  # noqa: E402
from heizung.services import paketverlust  # noqa: E402

logger = logging.getLogger("funkqualitaet")

ZONE = "Europe/Vienna"


@dataclass(frozen=True, slots=True)
class Zeile:
    geraet: Device
    verlust: paketverlust.Paketverlust
    rssi_min: int | None
    rssi_median: int | None
    snr_min: Decimal | None
    snr_median: Decimal | None


def _ortszeit(wert: datetime | None) -> str:
    """Zeitpunkt in Ortszeit, mit Zone im Text.

    Eine Uhrzeit ohne Zone neben einer anderen ohne Zone sieht wie ein
    Vergleich aus und ist keiner (Paragraph 5.79, Belegungs-Import).
    """
    if wert is None:
        return "—"
    return wert.astimezone(ZoneInfo(ZONE)).strftime("%d.%m. %H:%M")


def _parse_seit(text: str) -> datetime:
    """``--seit`` als **Ortszeit** lesen.

    Der Mensch tippt die Uhrzeit, die an seiner Wand steht. Sie als UTC
    zu lesen waere im Winter eine Stunde daneben und im Sommer zwei —
    dieselbe Falle wie in Paragraph 5.65, nur am Eingang statt im Regler.
    """
    roh = datetime.fromisoformat(text)
    if roh.tzinfo is None:
        roh = roh.replace(tzinfo=ZoneInfo(ZONE))
    return roh.astimezone(UTC)


async def _empfangsdaten(
    session: AsyncSession, device_id: int, ab: datetime
) -> tuple[int | None, int | None, Decimal | None, Decimal | None]:
    """RSSI und SNR, kleinster Wert und Mittelwert der Reihe.

    Der **Median** und nicht der Durchschnitt: ein einzelner Ausreisser
    nach unten — ein Frame, den ein zweites Gateway schwach mitgehoert
    hat — soll das Bild nicht verschieben. Dieselbe Wahl wie bei der
    Batterie (AE-72).
    """
    zeilen = (
        await session.execute(
            select(SensorReading.rssi_dbm, SensorReading.snr_db)
            .where(SensorReading.device_id == device_id)
            .where(SensorReading.time >= ab)
        )
    ).all()

    rssis = [r for r, _ in zeilen if r is not None]
    snrs = [s for _, s in zeilen if s is not None]
    return (
        min(rssis) if rssis else None,
        int(median(rssis)) if rssis else None,
        min(snrs) if snrs else None,
        Decimal(median(snrs)).quantize(Decimal("0.1")) if snrs else None,
    )


async def _lade(args: argparse.Namespace) -> int:
    ab = (
        _parse_seit(args.seit)
        if args.seit
        else datetime.now(tz=UTC) - timedelta(hours=args.stunden)
    )
    stunden = max(1, round((datetime.now(tz=UTC) - ab).total_seconds() / 3600))

    async with SessionLocal() as session:
        stmt = select(Device).where(Device.retired_at.is_(None)).order_by(Device.label)
        if args.geraet:
            muster = f"%{args.geraet}%"
            stmt = stmt.where(
                or_(
                    Device.label.ilike(muster),
                    Device.dev_eui.ilike(muster),
                    Device.hardware_number.ilike(muster),
                )
            )
        geraete = list((await session.execute(stmt)).scalars().all())

        if not geraete:
            print(f"Kein Geraet gefunden fuer '{args.geraet}'.")
            return 1

        zeilen: list[Zeile] = []
        for geraet in geraete:
            verlust = await paketverlust.fuer_geraet(session, geraet, stunden=stunden, ab=ab)
            if geraet.kind == DeviceKind.RELAY:
                rssi_min = rssi_med = None
                snr_min = snr_med = None
            else:
                rssi_min, rssi_med, snr_min, snr_med = await _empfangsdaten(session, geraet.id, ab)
            zeilen.append(Zeile(geraet, verlust, rssi_min, rssi_med, snr_min, snr_med))

    _zeige(zeilen, ab=ab)
    return 0


def _zeige(zeilen: list[Zeile], *, ab: datetime) -> None:
    print(f"\nFunkqualitaet seit {_ortszeit(ab)} Ortszeit ({ZONE})\n")

    kopf = [
        "Geraet",
        "Art",
        "empf.",
        "erw.",
        "verl.",
        "Verlust",
        "Neust.",
        "RSSI min/med",
        "SNR min/med",
        "erster",
        "letzter",
    ]
    tabelle: list[list[str]] = []
    for z in zeilen:
        v = z.verlust
        tabelle.append(
            [
                z.geraet.label or z.geraet.dev_eui,
                "Relais" if z.geraet.kind == DeviceKind.RELAY else "Vicki",
                str(v.empfangen),
                str(v.erwartet),
                str(v.verloren),
                f"{v.anteil} %" if v.anteil is not None else "—",
                str(v.neustarts),
                f"{z.rssi_min} / {z.rssi_median}" if z.rssi_min is not None else "—",
                f"{z.snr_min} / {z.snr_median}" if z.snr_min is not None else "—",
                _ortszeit(v.von),
                _ortszeit(v.bis),
            ]
        )

    breiten = [max(len(kopf[i]), max(len(t[i]) for t in tabelle)) for i in range(len(kopf))]
    print("  " + " | ".join(kopf[i].ljust(breiten[i]) for i in range(len(kopf))))
    print("  " + "-+-".join("-" * b for b in breiten))
    for t in tabelle:
        print("  " + " | ".join(t[i].ljust(breiten[i]) for i in range(len(kopf))))

    relais = [z for z in zeilen if z.geraet.kind == DeviceKind.RELAY]
    if relais:
        print(
            "\n  RSSI, SNR und die Datenrate speichern wir fuer Relais nicht."
            "\n  Sie stehen in ChirpStack: Device -> Metriken (RUNBOOK Paragraph 10au)."
        )
    wenig = [z for z in zeilen if z.verlust.anteil is None]
    if wenig:
        print(
            "\n  „—" + "“ im Verlust heisst: unter zwei Frames im Fenster."
            "\n  Das ist nicht 0 % — ohne zwei Frames gibt es keine Luecke zu sehen."
        )
    neustarts = [z for z in zeilen if z.verlust.neustarts]
    if neustarts:
        print(
            "\n  Eine Ruecksetzung des Zaehlers ist ein Neustart und KEIN Verlust."
            "\n  Die Reihe wird dort geteilt und beide Teile getrennt gerechnet."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Paketverlust aus fCnt-Luecken, dazu RSSI/SNR bei Vickis. Liest nur."
    )
    parser.add_argument(
        "--geraet",
        help="Teil von Etikett, DevEUI oder Hardware-Nummer. Ohne Angabe: alle.",
    )
    parser.add_argument(
        "--seit",
        help='Beginn des Fensters in ORTSZEIT, z. B. "2026-11-02 07:05".',
    )
    parser.add_argument(
        "--stunden",
        type=int,
        default=24,
        help="Fenster in Stunden, wenn --seit fehlt. Vorgabe 24.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    return _verteile(args)


def _verteile(args: argparse.Namespace) -> int:
    """Startet den Lauf — **und nur das**.

    Eigene Funktion aus demselben Grund wie in ``geraetegrenzen``: ein
    Test, der ``main()`` aufruft, startet sonst mit ``asyncio.run`` einen
    zweiten Event-Loop mitten in der pytest-Sitzung (Paragraph 5.14).
    """
    return asyncio.run(_lade(args))


if __name__ == "__main__":
    sys.exit(main())
