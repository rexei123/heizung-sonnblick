"""Die Temperaturgrenzen am Geraet: Soll, Ist, Vergleich (Sprint 23 T1).

**Was die Grenze tut.** ``0x08`` begrenzt den Bereich, in dem das
**Drehrad** die Zieltemperatur verstellen darf. Der Gast in 306 hat am
21./22.10.2026 zwoelf Mal gedreht, bis auf 29 °C, und jedes Mal hat Layer
5 den Wert hinterher auf 25 gekappt. Das Zimmer war richtig geheizt, das
Geraet zeigte eine Zahl, die nicht galt, und der Gast drehte weiter.

Die Grenze setzt dort an, wo das Problem entsteht: am Rad.

**Downlinks bleiben unberuehrt.** Hersteller-Aussage auf derselben Seite:
der Grenzbereich greift bei Verstellung mit der Krone, Downlink-Befehle
duerfen ein Ziel darueber hinaus setzen. Damit kollidiert die Grenze
**nicht** mit Layer 5 — ein Frostschutz von 10 °C geht auch an ein Bad
mit Untergrenze 18 durch, ein Fenster-Sicherheitswert ebenso.

Das ist eine **Aussage des Herstellers und keine Messung**. Sie wird am
Geraet geprueft, bevor irgendetwas ausgerollt wird (Pflicht-Stop,
RUNBOOK §10ap, Schritt 3). Faellt sie anders aus, ist T1 an dieser Stelle
zu stoppen: dann kollidiert die Gerätegrenze mit Layer 5, und das ist
eine andere Aufgabe.

**Soll und Ist sind zwei verschiedene Fragen.**

* *Soll* kommt aus dem Raumtyp — bei einer Bad-Zone aus dem der Vorlage,
  sonst aus dem des Zimmers. Gerechnet wird mit demselben Helfer wie
  Layer 5 (``rules.engine.grenzen_aus_raumtyp``), nicht mit einer zweiten
  Rechnung daneben (§5.53).
* *Ist* kommt aus der Antwort auf ``0x15``, also aus ``sensor_reading``.
  **Nicht** aus ``control_command``: das sagt, was wir gesendet haben,
  und eine Anzeige, die das Gesendete zeigt, waere eine Zusicherung ohne
  Deckung — genau die, die wir vor Sprint 20f fuer den Sollwert hatten.

Gelesen wird die **juengste Zeile, die die Felder fuehrt**. Ein Keepalive
ohne ``0x15``-Antwort sagt ueber die Grenzen nichts, und ihn als
„keine Grenzen" zu lesen waere derselbe Fehler, der im Mai bei
``child_lock`` und ``attached_backplate`` schon einmal gemacht wurde.

**„Nicht bestaetigt" heisst nicht „falsch".** Es heisst, dass noch keine
Antwort kam — bei einem Class-A-Geraet ganz normal, solange es nicht
gesendet hat. Der Text sagt das, damit niemand daraus einen Fehler liest.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import HeatingZoneKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.sensor_reading import SensorReading
from heizung.rules.badvorlage import lade_bad_vorlage
from heizung.rules.engine import grenzen_aus_raumtyp

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Grenzen:
    """Untere und obere Grenze in ganzen Grad Celsius."""

    min_c: int
    max_c: int

    def __str__(self) -> str:
        return f"{self.min_c}–{self.max_c} °C"


@dataclass(frozen=True, slots=True)
class Grenzbefund:
    """Was am Geraet steht — und wann es das gemeldet hat."""

    grenzen: Grenzen
    gemeldet_um: datetime


async def soll_grenzen_je_zone(
    session: AsyncSession, zone_ids: Sequence[int]
) -> dict[int, Grenzen]:
    """Die Grenzen, die fuer jede Zone gelten sollen.

    Eine Abfrage fuer alle Zonen, nicht eine je Zone: der Rollout laeuft
    ueber bis zu hundert Geraete, und eine Rundreise je Zeile waere
    hundert Rundreisen fuer eine Information (AE-72 §3).

    **Bad-Zonen folgen der Vorlage.** Dieselbe Rangfolge wie der
    Bad-Sollwert: ``kind == bathroom`` und es gibt den Vorlage-Raumtyp →
    dessen Grenzen; sonst die des Zimmertyps. Gibt es die Vorlage nicht,
    verhaelt sich alles wie vor dem 18.10. — kein Sonderfall, kein
    Fehler.
    """
    if not zone_ids:
        return {}

    vorlage = await lade_bad_vorlage(session)
    vorlage_grenzen = grenzen_aus_raumtyp(vorlage) if vorlage is not None else None

    stmt = (
        select(HeatingZone.id, HeatingZone.kind, RoomType)
        .join(Room, HeatingZone.room_id == Room.id)
        .join(RoomType, Room.room_type_id == RoomType.id)
        .where(HeatingZone.id.in_(list(zone_ids)))
    )
    ergebnis: dict[int, Grenzen] = {}
    for zone_id, kind, raumtyp in (await session.execute(stmt)).all():
        if kind == HeatingZoneKind.BATHROOM and vorlage_grenzen is not None:
            unten, oben = vorlage_grenzen
        else:
            unten, oben = grenzen_aus_raumtyp(raumtyp)
        ergebnis[zone_id] = Grenzen(min_c=unten, max_c=oben)
    return ergebnis


async def ist_grenzen_je_geraet(
    session: AsyncSession, device_ids: Sequence[int]
) -> dict[int, Grenzbefund | None]:
    """Was die Geraete zuletzt gemeldet haben, in **einer** Abfrage.

    ``None`` fuer ein Geraet heisst „noch keine Antwort auf ``0x15``" —
    nicht „keine Grenzen". Jede angefragte ID kommt im Ergebnis vor; ein
    fehlender Schluessel waere fuer den Aufrufer nicht von „nicht
    bestaetigt" zu unterscheiden, und dann muesste er raten.

    Dieselbe Form wie ``child_lock_verdicts`` und ``battery_verdicts``:
    ``DISTINCT ON (device_id)`` ueber ``ix_sensor_reading_device_time``,
    und der ``IS NOT NULL``-Filter steht in der WHERE-Klausel. Stuende er
    im Nachhinein, kaeme fuer ein Geraet, dessen juengste Zeile die
    Felder nicht fuehrt, ``None`` heraus — obwohl die Zeile davor sie
    fuehrt.
    """
    ergebnis: dict[int, Grenzbefund | None] = dict.fromkeys(device_ids)
    if not device_ids:
        return ergebnis

    stmt = (
        select(
            SensorReading.device_id,
            SensorReading.temp_range_min,
            SensorReading.temp_range_max,
            SensorReading.time,
        )
        .where(SensorReading.device_id.in_(list(device_ids)))
        .where(SensorReading.temp_range_min.is_not(None))
        .where(SensorReading.temp_range_max.is_not(None))
        .order_by(SensorReading.device_id, SensorReading.time.desc())
        .distinct(SensorReading.device_id)
    )
    for device_id, unten, oben, gemeldet_um in (await session.execute(stmt)).tuples().all():
        if unten is None or oben is None:
            continue
        ergebnis[device_id] = Grenzbefund(
            grenzen=Grenzen(min_c=unten, max_c=oben), gemeldet_um=gemeldet_um
        )
    return ergebnis


def muss_gesendet_werden(soll: Grenzen, befund: Grenzbefund | None) -> bool:
    """Weicht das Geraet vom Soll ab — oder wissen wir es nicht?

    **Ohne Antwort wird gesendet.** Das ist die bewusste Wahl: ein Geraet,
    von dem wir nichts gehoert haben, steht womoeglich auf der
    Werkseinstellung 5/30, und dann darf der Gast auf 30 drehen. Lieber
    ein Befehl zu viel als eine Grenze, die es nicht gibt.

    Umgekehrt: **stimmt die Antwort, wird nicht gesendet.** Das ist die
    vierte Pruefung des Pflicht-Stops — der Abgleich darf nicht jede
    Viertelstunde funken, wenn die Grenzen passen (S4, Batterie und
    Motor sind real).
    """
    if befund is None:
        return True
    return befund.grenzen != soll
