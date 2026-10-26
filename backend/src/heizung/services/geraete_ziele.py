"""Welche Geraete Hardware-Befehle bekommen duerfen (Sprint 23).

**Eine Liste, eine Stelle.** Seit Sprint 23 gibt es zwei Pfade, die
Funkbefehle an Thermostate schicken: die Fenstererkennung (``0x45``, T2)
und die Temperaturgrenzen am Geraet (``0x08``, T1). Beide muessen
dieselben Geraete ausnehmen, und zwar genau dieselben — zwei
Auswahllisten waeren zwei Wahrheiten darueber, welche Geraete Befehle
bekommen (Paragraph 5.53). Das ist die unangenehmste Sorte: man sieht sie
erst am Geraet.

Das Modul entstand als Teil von ``services/fenstererkennung`` und ist mit
T1 hierher gezogen, weil ein Name, der nur den ersten Konsumenten nennt,
den zweiten verbirgt.

**Die Ausnahmen, und warum jede eine ist** (Ergaenzung 2 des Auftrags,
25.10.2026 — ausdruecklich mit Test):

* **nur messen** (die Vickis 027 und 056): sie liegen als Fuehler im Raum
  und bekommen bewusst keine Befehle (S7, Sprint 24c). Ein Befehl dorthin
  widerspricht der Rolle, und die Rolle ist der Grund, warum das Drehrad
  dort gesperrt ist.
* **Reserve-Pool** (Geraet 100, ohne Zone): es liegt im Lager. Ein
  Befehl an ein Geraet ohne Einsatzort hat keinen Adressaten.
* **ausgemustert**: es ist nicht mehr da.
* **kein Thermostat**: ein Relais hat kein Drehrad und misst nicht.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.room import Room

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Zielgeraet:
    """Ein Gerät, an das ``0x45`` gehen darf."""

    device_id: int
    dev_eui: str
    label: str | None
    firmware_version: str | None
    #: Die Zone, in der das Geraet haengt. Sprint 23 T1 braucht sie: die
    #: Soll-Grenzen haengen an der Zonen-Art (Bad folgt der Vorlage), und
    #: ein zweiter Datenbankgang je Geraet waere hundert Rundreisen fuer
    #: eine Information.
    heating_zone_id: int | None
    zone_name: str | None
    room_number: str | None

    @property
    def bezeichnung(self) -> str:
        """Was im Bericht steht — Zimmer und Zone, sonst das Etikett."""
        if self.room_number is not None and self.zone_name is not None:
            return f"{self.room_number} {self.zone_name}"
        return self.label or self.dev_eui


@dataclass(frozen=True, slots=True)
class Ausnahme:
    """Ein Gerät, das **nicht** beschickt wird, mit dem Grund dafür."""

    dev_eui: str
    label: str | None
    grund: str


#: Die Gründe, aus denen ein Gerät ausgenommen wird. Als Konstanten, weil
#: der Test sie prüft und der Bericht sie anzeigt — zwei Leser, eine
#: Schreibweise.
GRUND_NUR_MESSEN = "nur messen (bekommt keine Befehle, S7)"
GRUND_OHNE_ZONE = "keiner Zone zugeordnet (Reserve-Pool)"
GRUND_AUSGEMUSTERT = "ausgemustert"
GRUND_KEIN_THERMOSTAT = "kein Thermostat"


def ausnahme_grund(geraet: Device) -> str | None:
    """Warum dieses Gerät kein Ziel ist — oder ``None``, wenn es eines ist.

    **Eine Funktion und nicht nur eine WHERE-Klausel.** Die Abfrage
    filtert, der Bericht muss aber *sagen können*, welches Gerät warum
    fehlt. Eine Auswahl, die Geräte stillschweigend weglässt, ist beim
    Nachzählen nicht von einem Fehler zu unterscheiden — und bei einem
    Hardware-Lauf zählt jemand nach.

    Die Reihenfolge der Prüfungen ist die Reihenfolge der Deutlichkeit:
    ausgemustert schlägt alles, dann die Rolle, dann die Zone.
    """
    if geraet.retired_at is not None:
        return GRUND_AUSGEMUSTERT
    if geraet.kind != DeviceKind.THERMOSTAT:
        return GRUND_KEIN_THERMOSTAT
    if geraet.measure_only:
        return GRUND_NUR_MESSEN
    if geraet.heating_zone_id is None:
        return GRUND_OHNE_ZONE
    return None


async def lade_ziele(
    session: AsyncSession,
    *,
    nur: Sequence[str] | None = None,
) -> tuple[list[Zielgeraet], list[Ausnahme]]:
    """Die Geräte, an die ``0x45`` gehen darf — und die Ausgenommenen dazu.

    ``nur`` wählt nach DevEUI **oder** nach Bezeichnung (Etikett, Zimmer
    plus Zone, oder Zimmernummer allein), kleingeschrieben verglichen. Die
    Bezeichnung ist der Weg, den der Testplan nennt („105, 110, 306
    Schlafzimmer") — eine DevEUI tippt niemand ab, und sie ändert sich
    beim Gerätetausch.

    **Die Ausnahmen kommen mit zurück und werden nicht verschwiegen.**
    Wer einen Hardware-Lauf startet, zählt die Geräte; eine Liste, die
    kürzer ist als erwartet, muss ihren Grund mitbringen.
    """
    gesucht = {s.strip().lower() for s in nur} if nur else None

    stmt = (
        select(Device, HeatingZone.name, Room.number)
        .outerjoin(HeatingZone, Device.heating_zone_id == HeatingZone.id)
        .outerjoin(Room, HeatingZone.room_id == Room.id)
        .order_by(Room.number.nulls_last(), HeatingZone.name.nulls_last(), Device.dev_eui)
    )
    ziele: list[Zielgeraet] = []
    ausnahmen: list[Ausnahme] = []

    for geraet, zone_name, room_number in (await session.execute(stmt)).all():
        namen = {geraet.dev_eui.lower()}
        if geraet.label:
            namen.add(geraet.label.lower())
        if room_number:
            namen.add(room_number.lower())
            if zone_name:
                namen.add(f"{room_number} {zone_name}".lower())
        if gesucht is not None and namen.isdisjoint(gesucht):
            continue

        grund = ausnahme_grund(geraet)
        if grund is not None:
            ausnahmen.append(Ausnahme(dev_eui=geraet.dev_eui, label=geraet.label, grund=grund))
            continue

        ziele.append(
            Zielgeraet(
                device_id=geraet.id,
                dev_eui=geraet.dev_eui,
                label=geraet.label,
                firmware_version=geraet.firmware_version,
                heating_zone_id=geraet.heating_zone_id,
                zone_name=zone_name,
                room_number=room_number,
            )
        )

    return ziele, ausnahmen


def nicht_gefunden(
    nur: Sequence[str], ziele: Sequence[Zielgeraet], ausnahmen: Sequence[Ausnahme]
) -> list[str]:
    """Namen aus ``nur``, auf die kein Gerät passte.

    Ein Tippfehler im Namen würde sonst ein **leeres** Ergebnis erzeugen,
    und ein leeres Ergebnis sieht wie „alle ausgenommen" aus. Der
    Unterschied ist der zwischen „nichts zu tun" und „am falschen Gerät
    gesucht".
    """
    getroffen: set[str] = set()
    for z in ziele:
        getroffen.update(
            {z.dev_eui.lower(), z.bezeichnung.lower()}
            | ({z.label.lower()} if z.label else set())
            | ({z.room_number.lower()} if z.room_number else set())
        )
    for a in ausnahmen:
        getroffen.add(a.dev_eui.lower())
        if a.label:
            getroffen.add(a.label.lower())
    return [s for s in nur if s.strip().lower() not in getroffen]
