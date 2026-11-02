"""Paketverlust aus Luecken im Frame-Zaehler (02.11.2026).

**Woher die Zahl kommt.** Jeder LoRaWAN-Uplink traegt einen Zaehler, und
der zaehlt lueckenlos hoch — auch die Uplinks, die das Gateway nie
gehoert hat. Wer also die kleinste und die groesste gesehene Nummer
kennt, weiss, **wie viele** Frames unterwegs waren, und wer die Zeilen
zaehlt, weiss, wie viele angekommen sind. Die Differenz ist der Verlust,
und sie ist eine Messung, keine Schaetzung.

Anlass ist Relais 109: zwischen dem letzten Uplink vor einem Neustart
(``fCnt`` 8) und dem naechsten (``fCnt`` 13) fehlten vier Frames — rund
30 % —, waehrend das Gateway die Vickis im selben Zeitraum normal hoerte.
Diese Rechnung stand bisher in keiner Oberflaeche; sie wurde von Hand
aus den ChirpStack-Ereignissen gelesen.

**Was die Zahl nicht sagt.** Sie sagt nichts ueber die Richtung: ein
verlorener Uplink kann am Funkweg, am Gateway oder am Netz dahinter
liegen. Und sie sagt nichts ueber Downlinks — die haben keinen Zaehler,
den wir sehen.

Ein Neustart des Geraets setzt den Zaehler zurueck (§5.71 fuer die
Vicki; das 16ASPM verhaelt sich genauso, belegt am Stromausfalltest vom
01.11.2026). Eine Ruecksetzung ist **kein** Verlust: die Reihe wird dort
geteilt und beide Teile werden getrennt gerechnet.

**Die Schwelle aus §5.71 gilt hier bewusst nicht.** Dort entscheidet
``is_reboot_frame``, ob ein Drehring-Wert als Wunsch des Gastes
uebernommen wird — eine Entscheidung mit Folgen, die vorsichtig sein
muss und deshalb zusaetzlich verlangt, dass der neue Zaehler klein ist.
Hier wird nur gerechnet: **jedes** Sinken des Zaehlers ist eine
Ruecksetzung, denn ein Zaehler, der hochzaehlt, kann nicht sinken. Waere
die Schwelle auch hier in Kraft, wuerde ein Neustart mit hohem
Anfangswert als Luecke von Millionen Frames erscheinen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.relay_reading import RelayReading
from heizung.models.sensor_reading import SensorReading


@dataclass(frozen=True, slots=True)
class Paketverlust:
    """Das Ergebnis einer Auszaehlung.

    ``anteil`` ist ``None``, wenn nicht genug Frames im Fenster liegen —
    das ist nicht dasselbe wie 0 %. Bei einem einzigen Frame gibt es
    keine Luecke, die man sehen koennte, und eine 0 davor waere eine
    Behauptung ueber einen Funk, der nicht gemessen wurde.
    """

    #: Zeilen mit Zaehler im Fenster, Doppelte nur einmal.
    empfangen: int
    #: Wie viele Frames das Geraet im Fenster gesendet hat.
    erwartet: int
    #: ``erwartet - empfangen``.
    verloren: int
    #: Anteil in Prozent, auf eine Stelle gerundet. ``None`` siehe oben.
    anteil: Decimal | None
    #: Wie oft der Zaehler zurueckgesetzt wurde (Neustart, Rejoin).
    neustarts: int
    #: Zeilen mit demselben Zaehler. Mehrfachempfang, kein Verlust.
    doppelt: int
    #: Zeilen ohne Zaehler. Sie gehen in die Rechnung nicht ein.
    ohne_zaehler: int
    #: Laenge des Fensters.
    stunden: int
    #: Erste und letzte Zeile im Fenster. ``None``, wenn es keine gibt.
    von: datetime | None = None
    bis: datetime | None = None


def rechne(zaehler: Sequence[int | None], *, stunden: int) -> Paketverlust:
    """Zaehlt Luecken in einer **zeitlich geordneten** Reihe von Zaehlern.

    Die Reihenfolge ist die der Ankunft, nicht die der Zahlen. Das ist
    der Grund, warum ein Sinken als Ruecksetzung gilt und nicht als
    Umsortierung.

    Reine Funktion, keine Datenbank, keine Uhr.
    """
    reihen: list[list[int]] = []
    neustarts = 0
    ohne_zaehler = 0

    for wert in zaehler:
        if wert is None:
            ohne_zaehler += 1
            continue
        if not reihen:
            reihen.append([wert])
            continue
        # Ein Zaehler, der hochzaehlt, kann nicht sinken: hier beginnt
        # eine neue Reihe. Gleichstand ist ein Doppelter und bleibt in
        # derselben Reihe.
        if wert < reihen[-1][-1]:
            neustarts += 1
            reihen.append([wert])
        else:
            reihen[-1].append(wert)

    empfangen = 0
    erwartet = 0
    doppelt = 0
    for reihe in reihen:
        eindeutig = set(reihe)
        doppelt += len(reihe) - len(eindeutig)
        empfangen += len(eindeutig)
        erwartet += max(reihe) - min(reihe) + 1

    verloren = erwartet - empfangen
    anteil: Decimal | None = None
    if erwartet >= 2:
        anteil = (Decimal(verloren) * 100 / Decimal(erwartet)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

    return Paketverlust(
        empfangen=empfangen,
        erwartet=erwartet,
        verloren=verloren,
        anteil=anteil,
        neustarts=neustarts,
        doppelt=doppelt,
        ohne_zaehler=ohne_zaehler,
        stunden=stunden,
    )


async def fuer_geraet(
    session: AsyncSession,
    geraet: Device,
    *,
    stunden: int,
    ab: datetime | None = None,
) -> Paketverlust:
    """Liest die Zaehler des Geraets und rechnet.

    **Die Tabelle haengt an der Geraeteart**, und das ist der einzige
    Unterschied zwischen Relais und Vicki in dieser Rechnung: ein Relais
    schreibt nach ``relay_reading``, ein Thermostat nach
    ``sensor_reading``. Beide fuehren ``fcnt`` an derselben Stelle und
    mit derselben Bedeutung.

    ``ab`` schlaegt ``stunden``, wenn es gesetzt ist — das Werkzeug
    ``scripts/funkqualitaet`` rechnet ab einem genannten Zeitpunkt
    („seit 07:05, als das Relais in die Dose kam"), die Geraeteseite ab
    einer Fensterlaenge. ``stunden`` bleibt in beiden Faellen in der
    Antwort, damit die Zahl ihren Zeitraum mitbringt.

    **Zeit und Zaehler kommen aus einer Abfrage.** Zwei Abfragen waeren
    zwei Fenster, und beim naechsten Aufrufer stehen sie auseinander
    (§5.53). Gelesen werden zwei Spalten ueber den Index
    ``(device_id, time)``.
    """
    grenze = ab or (datetime.now(tz=UTC) - timedelta(hours=stunden))
    tabelle = RelayReading if geraet.kind == DeviceKind.RELAY else SensorReading

    zeilen = (
        await session.execute(
            select(tabelle.time, tabelle.fcnt)
            .where(tabelle.device_id == geraet.id)
            .where(tabelle.time >= grenze)
            .order_by(tabelle.time.asc())
        )
    ).all()

    verlust = rechne([f for _, f in zeilen], stunden=stunden)
    if not zeilen:
        return verlust
    return replace(verlust, von=zeilen[0][0], bis=zeilen[-1][0])
