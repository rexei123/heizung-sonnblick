"""Der bestaetigte Schaltzustand eines Relais (Sprint 24b).

**Eine Quelle, kein Spiegel.** Der Zustand steht in ``relay_reading`` —
das ist, was das **Geraet** gemeldet hat. Eine Kopie auf ``device``
waere schneller zu lesen und beim ersten verpassten Uplink falsch
(§5.53). Bei einem Schaltzustand ist die falsche Haelfte der Kopie genau
die, auf die sich der Waechter verlassen wuerde.

Abgeleitet werden **drei** Angaben, und die zweite ist die schwierigere:

- **was** gilt: der ``relay_on`` der jüngsten Zeile, die ihn fuehrt.
- **seit wann** es gilt: der Zeitpunkt der Zeile, mit der dieser Zustand
  begonnen hat. Das ist nicht die jüngste Zeile, sondern die erste nach
  dem letzten Wechsel — der Zweipunktregler rechnet seine
  Mindestlaufzeit daran, und wer den jüngsten Zeitpunkt nimmt, bekommt
  eine Mindestlaufzeit, die bei jedem Keepalive neu beginnt und damit
  nie ablaeuft.
- **wann es zuletzt gemeldet wurde**: der Zeitpunkt der jüngsten Zeile.
  Das ist die Angabe, an der der Waechter entscheidet, ob er dem Zustand
  noch glaubt (``gemeldet``, 14.11.2026).

**``seit`` und ``gemeldet`` sind zwei verschiedene Zeiten, und die
Verwechslung ist teuer.** Ein Relais, das seit zwei Stunden EIN meldet,
hat ``seit`` vor zwei Stunden und ``gemeldet`` vor zehn Minuten — es ist
frisch. Ein Relais, das vor zwei Stunden das letzte Mal EIN gemeldet hat
und seither schweigt, hat **dieselbe** ``seit`` und ein ``gemeldet`` vor
zwei Stunden — es ist stumm, und was dort gerade gilt, weiss niemand.
Wer die Frische an ``seit`` misst, haelt ein laufendes Panel fuer stumm
und ein stummes fuer laufend.

``NULL``-Zeilen zaehlen nicht mit: eine Zeile ohne ``relay_on`` (etwa
eine reine Befehlsantwort ohne Keepalive-Schwanz) sagt nichts ueber den
Zustand und darf einen Wechsel nicht vortaeuschen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.relay_reading import RelayReading


@dataclass(frozen=True, slots=True)
class RelaisZustand:
    """Der bestaetigte Zustand eines Relais.

    ``ein is None`` heisst **unbekannt** — es gibt keine Zeile, die den
    Zustand fuehrt. Das ist nicht dasselbe wie AUS, und der Waechter
    behandelt es getrennt: bei unbekanntem Zustand wird nicht
    eingeschaltet.

    ``gemeldet`` ist der Zeitpunkt der jüngsten Zeile, die den Zustand
    fuehrt — nicht der Beginn des Zustands (``seit``). Ist ``ein`` nicht
    ``None``, dann ist auch ``gemeldet`` gesetzt; beide kommen aus
    derselben Zeile.
    """

    ein: bool | None
    seit: datetime | None
    gemeldet: datetime | None


async def bestaetigter_zustand(session: AsyncSession, device_id: int) -> RelaisZustand:
    """Liest den bestaetigten Zustand und seinen Beginn.

    Zwei Abfragen statt einer Fensterfunktion, und das ist Absicht: die
    erste liefert den Zustand, die zweite den letzten **Wechsel**. Eine
    Fensterfunktion ueber alle Zeilen des Geraets waere eleganter und
    muesste die ganze Historie lesen; so werden zwei Zeilen gelesen,
    beide ueber ``ix_relay_reading_device_time``.
    """
    jüngste = (
        await session.execute(
            select(RelayReading.time, RelayReading.relay_on)
            .where(RelayReading.device_id == device_id)
            .where(RelayReading.relay_on.is_not(None))
            .order_by(RelayReading.time.desc())
            .limit(1)
        )
    ).first()

    if jüngste is None:
        return RelaisZustand(ein=None, seit=None, gemeldet=None)

    zeit, ein = jüngste

    # Die jüngste Zeile mit dem **anderen** Zustand. Alles danach hat
    # denselben Zustand wie jetzt, der Beginn liegt also unmittelbar
    # dahinter.
    letzter_wechsel = (
        await session.execute(
            select(RelayReading.time)
            .where(RelayReading.device_id == device_id)
            .where(RelayReading.relay_on.is_not(None))
            .where(RelayReading.relay_on.is_(not ein))
            .order_by(RelayReading.time.desc())
            .limit(1)
        )
    ).scalar()

    if letzter_wechsel is None:
        # Nie etwas anderes gemeldet: der Zustand gilt seit der ersten
        # Zeile, die wir haben.
        erste = (
            await session.execute(
                select(RelayReading.time)
                .where(RelayReading.device_id == device_id)
                .where(RelayReading.relay_on.is_not(None))
                .order_by(RelayReading.time.asc())
                .limit(1)
            )
        ).scalar()
        return RelaisZustand(ein=ein, seit=erste, gemeldet=zeit)

    # Die erste Zeile **nach** dem Wechsel ist der Beginn.
    beginn = (
        await session.execute(
            select(RelayReading.time)
            .where(RelayReading.device_id == device_id)
            .where(RelayReading.relay_on.is_not(None))
            .where(RelayReading.time > letzter_wechsel)
            .order_by(RelayReading.time.asc())
            .limit(1)
        )
    ).scalar()

    return RelaisZustand(ein=ein, seit=beginn or zeit, gemeldet=zeit)
