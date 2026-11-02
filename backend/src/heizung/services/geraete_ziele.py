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

**Und die Auswahl muss eindeutig sein** (Entscheidung des Betreibers,
01.11.2026). ``--nur`` trifft nach DevEUI, Etikett, Zimmernummer oder
„Zimmer Zone"; mit den Geraetenamen 105-109 ist ``105`` beides. Trifft
eine Angabe auf **zwei verschiedenen Wegen**, bricht ``lade_ziele`` ab und
nennt beide Trefferlisten — Begruendung in
:class:`MehrdeutigeAuswahlError`. Mehrere Treffer auf **demselben** Weg
sind kein Fehler, und Ausnahmen zaehlen nicht mit.

Die Pruefung steht hier und nicht in den Werkzeugen, aus demselben Grund
wie die Ausnahmen: zwei Auswahllisten waeren zwei Wahrheiten darueber,
welche Geraete Befehle bekommen.
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
    #: Je gesuchter Angabe: auf welchem **Weg** sie getroffen hat und wen.
    #: Daraus entsteht der Abbruch bei Zweideutigkeit, siehe unten.
    treffer: dict[str, dict[str, list[str]]] = {}

    for geraet, zone_name, room_number in (await session.execute(stmt)).all():
        etikett = geraet.label.lower() if geraet.label else None
        zimmer = room_number.lower() if room_number else None
        zimmer_zone = f"{room_number} {zone_name}".lower() if room_number and zone_name else None
        namen = {geraet.dev_eui.lower()}
        if etikett:
            namen.add(etikett)
        if zimmer:
            namen.add(zimmer)
            if zimmer_zone:
                namen.add(zimmer_zone)
        if gesucht is not None and namen.isdisjoint(gesucht):
            continue

        grund = ausnahme_grund(geraet)
        if grund is not None:
            ausnahmen.append(Ausnahme(dev_eui=geraet.dev_eui, label=geraet.label, grund=grund))
            continue

        # **Gezaehlt wird erst hier, also nur fuer Geraete, die wirklich
        # einen Befehl bekaemen.** Ein Pool-Vicki mit dem Etikett „105"
        # ist eine Ausnahme und bekommt nichts; ihn mitzuzaehlen wuerde
        # jeden Lauf mit ``--nur "105"`` abbrechen, solange die neuen
        # Geraete im Lager liegen — und das waere ein Abbruch ohne Gefahr.
        # Scharf wird die Zweideutigkeit genau in dem Augenblick, in dem
        # das Geraet einer Zone zugeordnet ist und damit ein Ziel wird.
        if gesucht is not None:
            _notiere_treffer(
                treffer,
                gesucht,
                dev_eui=geraet.dev_eui,
                etikett=etikett,
                zimmer=zimmer,
                zimmer_zone=zimmer_zone,
                beschreibung=_beschreibung(geraet.dev_eui, geraet.label, room_number, zone_name),
            )

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

    _pruefe_eindeutigkeit(treffer)
    return ziele, ausnahmen


#: Die Wege, auf denen ``--nur`` ein Geraet treffen kann, in der
#: Reihenfolge, in der geprueft wird. Je Geraet gilt **ein** Weg: der
#: erste, der passt. Sonst waere ein Geraet, dessen Etikett zufaellig
#: seine eigene Zimmernummer ist, mit sich selbst zweideutig.
WEG_DEVEUI = "DevEUI"
WEG_ETIKETT = "Etikett"
WEG_ZIMMER_ZONE = "Zimmer und Zone"
WEG_ZIMMER = "Zimmernummer"


def _beschreibung(
    dev_eui: str, label: str | None, room_number: str | None, zone_name: str | None
) -> str:
    """Eine Zeile, die ein Geraet benennt, ohne Rueckfrage."""
    ort = f"{room_number} {zone_name}" if room_number and zone_name else "ohne Zone"
    return f"{label or '(ohne Etikett)'} / {dev_eui} / {ort}"


def _notiere_treffer(
    treffer: dict[str, dict[str, list[str]]],
    gesucht: set[str],
    *,
    dev_eui: str,
    etikett: str | None,
    zimmer: str | None,
    zimmer_zone: str | None,
    beschreibung: str,
) -> None:
    """Haelt fest, auf welchem Weg eine gesuchte Angabe getroffen hat."""
    for s in gesucht:
        if s == dev_eui.lower():
            weg = WEG_DEVEUI
        elif etikett is not None and s == etikett:
            weg = WEG_ETIKETT
        elif zimmer_zone is not None and s == zimmer_zone:
            weg = WEG_ZIMMER_ZONE
        elif zimmer is not None and s == zimmer:
            weg = WEG_ZIMMER
        else:
            continue
        treffer.setdefault(s, {}).setdefault(weg, []).append(beschreibung)


class MehrdeutigeAuswahlError(Exception):
    """Eine Angabe in ``--nur`` trifft auf **zwei verschiedenen Wegen**.

    **Der Anlass, 01.11.2026.** ``--nur`` waehlt nach DevEUI **oder**
    Etikett **oder** Zimmernummer **oder** „Zimmer Zone". Mit den neuen
    Geraetenamen 105-109 ist ``105`` beides: das Etikett eines
    Pool-Vickis und die Nummer eines Testzimmers. Solange das Geraet im
    Pool liegt, ist es eine Ausnahme und bekommt keinen Befehl — sobald es
    einer Zone zugeordnet ist, trifft ``--nur "105"`` die Thermostate von
    Zimmer 105 **und** das Geraet 105 dort, wo es dann sitzt.

    **Gezaehlt werden deshalb nur Ziele, keine Ausnahmen.** Ein Abbruch,
    solange die neuen Geraete im Lager liegen, waere ein Abbruch ohne
    Gefahr — und er fiele mitten in die T2-Erprobung, die ``--nur "105"``
    fuer das **Zimmer** 105 benutzt.

    **Warum ein Abbruch und keine Warnung.** Der Lauf wird abgezaehlt
    („stehen genau drei Ziele da?"), und eine Zahl, die um eins zu hoch
    ist, sieht nach einem Geraet aus, das man vergessen hatte. Das ist
    dieselbe Familie wie der Abbruch bei einem Tippfehler: ein Lauf, der
    lautlos ein Geraet zu viel trifft, ist schlimmer als einer, der nicht
    laeuft.

    **Mehrere Treffer auf demselben Weg sind kein Fehler.** Eine
    Zimmernummer trifft alle Thermostate ihres Zimmers — genau dafuer ist
    sie da.
    """

    def __init__(self, treffer: dict[str, dict[str, list[str]]]) -> None:
        self.treffer = treffer
        zeilen: list[str] = []
        for angabe, wege in sorted(treffer.items()):
            zeilen.append(f"  {angabe!r} trifft auf {len(wege)} Wegen:")
            for weg, wen in sorted(wege.items()):
                for eintrag in wen:
                    zeilen.append(f"    als {weg}: {eintrag}")
        super().__init__(
            "Mehrdeutige Auswahl - bitte genauer angeben "
            "(DevEUI oder 'Zimmer Zone' sind immer eindeutig):\n" + "\n".join(zeilen)
        )


def _pruefe_eindeutigkeit(treffer: dict[str, dict[str, list[str]]]) -> None:
    """Bricht ab, wenn eine Angabe auf zwei verschiedenen Wegen trifft."""
    mehrdeutig = {angabe: wege for angabe, wege in treffer.items() if len(wege) > 1}
    if mehrdeutig:
        raise MehrdeutigeAuswahlError(mehrdeutig)


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
