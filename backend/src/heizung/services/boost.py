"""Boost: ein Klick macht warm, bis das Nachtfenster wechselt (02.11.2026).

**Was ein Boost ist.** Eine Uebersteuerung, bei der die Rezeption nichts
auswaehlt: Wert und Ende kommen vom Server. Der Knopf heisst
„Boost bis HH:MM" und sagt damit vorher, was er tut.

**Festlegungen des Betreibers vom 31.10.2026**, und sie sind der Grund
fuer fast jede Zeile hier:

1. **Eine aktive ``frontend_*``-Uebersteuerung schliesst Boost aus** —
   mit Grund, nicht stillschweigend. Weder „Boost ersetzt sie" noch
   „Boost legt sich darueber"; das war Variante (c). Der Grund gegen
   beide: #340 soll sich nicht wiederholen. ``device`` und
   ``device_manual`` werden wie ueblich ersetzt (das macht der
   Stapel-Abbau in ``override_service.create``, hier ist nichts zu tun).
2. **Eine Regel fuer belegt und frei.** Das Ende kommt aus dem
   Nachtfenster **des Zimmers**, ueber die Kette und nicht aus
   ``global_config``.
3. **Ohne konfiguriertes Nachtfenster: abweisen** mit Grund. Keine
   erfundene Dauer.
4. **Kein Mindestmass.** Ein Boost um 19:55 endet um 20:00, und der Knopf
   zeigt die Endzeit vorher.

**Das Ende ist der naechste Wechsel des Nachtfensters**, und das ist eine
Ableitung aus Festlegung 2, die den Nachtfall mit abdeckt: im Tag endet
der Boost bei ``night_start`` — genau wie festgelegt —, in der Nacht bei
``night_end``. Die Lesart „immer der naechste ``night_start``" waere um
23:00 bei ``night_start`` 22:00 ein **23-Stunden-Boost**; das ist nicht,
was das Wort verspricht. Beide Faelle sind derselbe Satz: der Boost endet,
wenn die naechste Temperatur-Regel uebernimmt.

**Der Wert kommt aus ``rule_config.boost_temperature``**, derselben Kette
wie jeder Sollwert (Zimmer > Raumtyp > hausweit), und **nur** von dort.
Migration ``0037`` setzt die hausweite Zeile auf 23,0, wenn sie leer ist
— den Wert, den der Betreiber festgelegt hat. Steht trotzdem nirgends
einer, wird abgewiesen mit „Boost-Temperatur nicht eingestellt".

**Kein Rueckfall auf eine andere Spalte**, und das ist eine Korrektur:
der erste Entwurf nahm ``guest_override_max``, wenn nichts gesetzt war.
Das ist die **Gast-Obergrenze** und kann 25 sein, waehrend der Boost-Wert
23 ist — ein Rueckfall darauf macht aus einem Boost stillschweigend das
Maximum (Widerspruch des Betreibers vom 02.11.2026).

**Gekappt wird nicht hier.** Die Grenzen je Zone wirken weiter unten
(Engine-Layer 5 und ``geraetegrenzen``), und das ist richtig: ein Boost
soll dieselbe Obergrenze haben wie jede andere Uebersteuerung, nicht eine
eigene. Wer hier kappte, haette zwei Kappungen mit zwei Wahrheiten
(§5.53).

**Was dieses Modul nicht tut: schreiben.** Es beurteilt die Lage und
rechnet Wert und Ende. Angelegt wird ueber ``override_service.create``,
mit denselben Gates wie jede andere Uebersteuerung — die Sperre, das
offene Fenster und der Stapel-Abbau gelten unveraendert.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import OverrideSource, RuleConfigScope
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig
from heizung.rules.config_resolve import lade_rule_configs, lade_zeitzone, resolve_rule_field
from heizung.rules.scenarios import is_summer_mode_active
from heizung.services.override_service import OverrideError, get_active, stand_je_zimmer

#: Maschinenlesbare Marken fuer die Gruende. Die Oberflaeche darf ihre
#: eigenen Saetze haben; diese Marken sind der Vertrag.
GRUND_SOMMERMODUS = "sommermodus"
GRUND_DAUERHAFT_GESPERRT = "dauerhaft_gesperrt"
GRUND_ALLGEMEINBEREICH = "allgemeinbereich"
GRUND_KEIN_NACHTFENSTER = "kein_nachtfenster"
GRUND_KEIN_WERT = "kein_boostwert"
GRUND_UEBERSTEUERUNG_AKTIV = "uebersteuerung_aktiv"

#: Die Quellen, die einen Boost ausschliessen (Festlegung 1). Ein Boost
#: selbst steht hier bewusst **nicht** drin: einen laufenden Boost darf
#: ein neuer ersetzen — er endet ohnehin am selben Zeitpunkt, und der
#: Stapel-Abbau raeumt den alten weg. Alles andere waere ein Knopf, der
#: nach dem ersten Druck bis zur Nacht nichts mehr tut.
AUSSCHLIESSENDE_QUELLEN: frozenset[OverrideSource] = frozenset(
    {
        OverrideSource.FRONTEND_24H,
        OverrideSource.FRONTEND_CHECKOUT,
        OverrideSource.FRONTEND_BEREICH,
        OverrideSource.FRONTEND_4H,
        OverrideSource.FRONTEND_MIDNIGHT,
    }
)


class BoostNichtMoeglichError(OverrideError):
    """Ein Boost wurde verlangt, der nicht geht — mit Grund.

    Erbt von ``OverrideError`` und wird damit vom app-weiten Handler in
    ``heizung.main`` als ``409`` mit ``detail`` und ``error_code``
    gerendert. ``grund`` kommt als Top-Level-Feld mit, damit die
    Oberflaeche nicht am Satz entlang vergleichen muss (§5.64 — ein
    Diskriminator gehoert ins Feld, nicht in den Text).

    **Warum ueberhaupt ein Fehler, wenn die Oberflaeche den Knopf schon
    ausgraut.** Weil das Ausgrauen Bequemlichkeit ist und kein Schutz:
    die Lage kann sich zwischen dem Laden der Liste und dem Klick
    geaendert haben, und wer den Weg direkt aufruft, hat nie einen Knopf
    gesehen (§5.30).
    """

    error_code = "BOOST_NICHT_MOEGLICH"

    def __init__(self, message: str, *, grund: str) -> None:
        super().__init__(message)
        self.grund = grund

    def response_extras(self) -> dict[str, str]:
        return {"grund": self.grund}


@dataclass(frozen=True, slots=True)
class Boostlage:
    """Ob ein Boost geht, und wenn nicht, warum.

    ``moeglich`` und ``grund`` schliessen sich aus: bei ``moeglich`` ist
    der Grund ``None``, sonst ist er gesetzt. ``ende`` und ``wert`` sind
    bei ``moeglich`` **immer** gesetzt — der Knopf traegt die Endzeit in
    seiner Beschriftung, und ein Knopf ohne Endzeit waere eine Zusage
    ohne Inhalt.
    """

    moeglich: bool
    grund: str | None
    hinweis: str | None
    ende: datetime | None
    wert: Decimal | None


def naechster_nachtfenster_wechsel(
    jetzt_lokal: datetime, night_start: time, night_end: time
) -> datetime:
    """Der naechste Zeitpunkt, an dem das Nachtfenster wechselt.

    Im Tag ist das ``night_start`` (Festlegung 2 des Betreibers), in der
    Nacht ``night_end``. Reine Funktion, Ortszeit hinein, Ortszeit heraus.

    **Der Fall, der die Ableitung noetig macht:** ``night_start`` 22:00,
    jetzt 23:00. „Der naechste ``night_start``" waere morgen 22:00, also
    ein Boost von 23 Stunden. Der naechste **Wechsel** ist 06:00.

    Ein Nachtfenster ohne Ausdehnung (``night_start == night_end``) hat
    keinen Wechsel; der Aufrufer weist das ab, hier wird es nicht
    abgefangen, damit der Fall nicht zweimal entschieden wird.
    """
    jetzt_zeit = jetzt_lokal.time()
    if night_start <= night_end:
        # Nachtfenster innerhalb eines Tages, etwa 01:00 bis 05:00.
        in_der_nacht = night_start <= jetzt_zeit < night_end
    else:
        # Ueber Mitternacht, etwa 22:00 bis 06:00.
        in_der_nacht = jetzt_zeit >= night_start or jetzt_zeit < night_end

    ziel = night_end if in_der_nacht else night_start
    kandidat = jetzt_lokal.replace(hour=ziel.hour, minute=ziel.minute, second=0, microsecond=0)
    if kandidat <= jetzt_lokal:
        kandidat += timedelta(days=1)
    return kandidat


def _satz_uebersteuerung(aktiv: ManualOverride, zone: str) -> str:
    """Der Satz, den der Betreiber am 31.10.2026 wortgleich festgelegt hat."""
    ende = aktiv.expires_at.astimezone(ZoneInfo(zone)).strftime("%H:%M")
    wert = f"{aktiv.setpoint.quantize(Decimal('1'))} °C"
    return f"Übersteuerung aktiv ({wert} bis {ende}) – Wert dort ändern"


def beurteile(
    *,
    room: Room,
    raumtyp: RoomType | None,
    kette: list[RuleConfig],
    aktiv: ManualOverride | None,
    sommermodus: bool,
    zone: str,
    jetzt: datetime,
) -> Boostlage:
    """Beurteilt eine Lage — **ohne Datenbank**.

    Alles, was die Entscheidung braucht, kommt als Argument. Das ist der
    Grund, warum die Zimmer-Liste mit **einer** Abfrage je Gegenstand
    auskommt und nicht mit vier je Zimmer: bei 104 Zeilen waere das sonst
    dasselbe N+1-Muster, das R-D fuer diese Liste ausgeschlossen hat
    (§5.73 — wenn read-time, dann gehoben und nicht je Zeile).

    **Die Reihenfolge der Gruende ist verbindlich**, weil der Mensch
    genau einen Satz zu sehen bekommt und es der richtige sein soll:

    1. **Sommermodus** — es heizt ueberhaupt nichts. Jeder andere Grund
       waere hier eine Nebensaechlichkeit.
    2. **Dauerhafte Sperre** — eine Entscheidung ueber das Zimmer.
    3. **Allgemeinbereich** — dort gibt es einen anderen Weg, und der
       Satz nennt ihn.
    4. **Kein Nachtfenster** — ohne Ende kein Boost (Festlegung 3).
    5. **Kein Boost-Wert** — ohne Wert kein Boost.
    6. **Aktive Uebersteuerung** — zuletzt, weil sie die einzige ist, die
       sich von selbst loest.
    """
    if sommermodus:
        return Boostlage(False, GRUND_SOMMERMODUS, "Sommermodus aktiv", None, None)

    # Die Sperre „bis Check-out" trifft das Rad des Gastes, nicht das
    # Personal (Sprint 23 T4-A2) — ein Boost kommt dort also durch,
    # genau wie jede andere ``frontend_*``-Quelle.
    if room.guest_override_blocked and not room.guest_block_bis_checkout:
        return Boostlage(False, GRUND_DAUERHAFT_GESPERRT, "Dauerhaft gesperrt", None, None)

    if raumtyp is not None and not raumtyp.is_bookable:
        return Boostlage(
            False,
            GRUND_ALLGEMEINBEREICH,
            "Allgemeinbereich – Übersteuerung über Zimmerseite",
            None,
            None,
        )

    night_start = resolve_rule_field(kette, "night_start")
    night_end = resolve_rule_field(kette, "night_end")
    if not isinstance(night_start, time) or not isinstance(night_end, time):
        return Boostlage(
            False, GRUND_KEIN_NACHTFENSTER, "Kein Nachtfenster konfiguriert", None, None
        )
    if night_start == night_end:
        # Ein Fenster ohne Ausdehnung hat keinen Wechsel. Derselbe Satz
        # wie oben: aus der Sicht des Lesers ist nichts konfiguriert.
        return Boostlage(
            False, GRUND_KEIN_NACHTFENSTER, "Kein Nachtfenster konfiguriert", None, None
        )

    # **Kein Rueckfall auf eine andere Spalte** (Widerspruch des
    # Betreibers vom 02.11.2026). Der erste Entwurf nahm hier
    # ``guest_override_max``, wenn ``boost_temperature`` leer war. Das ist
    # fachlich falsch: ``guest_override_max`` ist die **Gast-Obergrenze**
    # und kann 25 sein, waehrend der festgelegte Boost-Wert 23 ist. Ein
    # Rueckfall auf eine Grenze, die eine andere Frage beantwortet, macht
    # aus einem Boost stillschweigend das Maximum — und zwar dort, wo
    # niemand hinsieht, weil beides eine plausible Zahl ist.
    #
    # Der Wert steht deshalb ausdruecklich in den Daten; Migration
    # ``0037`` setzt die hausweite Zeile auf 23,0, wenn sie leer ist.
    # Steht er trotzdem nirgends, wird abgewiesen — mit einem Grund, der
    # sagt, was zu tun ist.
    wert = resolve_rule_field(kette, "boost_temperature")
    if not isinstance(wert, Decimal):
        return Boostlage(
            False,
            GRUND_KEIN_WERT,
            "Boost-Temperatur nicht eingestellt",
            None,
            None,
        )

    ende_lokal = naechster_nachtfenster_wechsel(
        jetzt.astimezone(ZoneInfo(zone)), night_start, night_end
    )
    ende = ende_lokal.astimezone(UTC)

    if aktiv is not None and aktiv.source in AUSSCHLIESSENDE_QUELLEN:
        return Boostlage(
            False,
            GRUND_UEBERSTEUERUNG_AKTIV,
            _satz_uebersteuerung(aktiv, zone),
            ende,
            wert,
        )

    return Boostlage(True, None, None, ende, wert)


async def lage(
    session: AsyncSession,
    room: Room,
    *,
    jetzt: datetime | None = None,
    sommermodus: bool | None = None,
) -> Boostlage:
    """Die Lage **eines** Zimmers. Laedt und beurteilt.

    Der Weg fuer den Knopf-Druck: dort geht es um ein Zimmer, und vier
    Abfragen sind der richtige Preis fuer eine Entscheidung, die etwas
    schreibt. Fuer die Liste gibt es ``lage_je_zimmer``.
    """
    now = jetzt or datetime.now(tz=UTC)
    if sommermodus is None:
        sommermodus = await is_summer_mode_active(session)

    return beurteile(
        room=room,
        raumtyp=await session.get(RoomType, room.room_type_id),
        kette=await lade_rule_configs(session, room_id=room.id, room_type_id=room.room_type_id),
        # ``get_active`` nimmt seine eigene Uhr (``_now``) und kein
        # ``now``-Argument. Das ist hier ohne Folge: der Unterschied sind
        # Millisekunden, und die Frage lautet „laeuft gerade einer".
        aktiv=await get_active(session, room.id),
        sommermodus=sommermodus,
        zone=await lade_zeitzone(session),
        jetzt=now,
    )


async def lage_je_zimmer(
    session: AsyncSession,
    rooms: Sequence[Room],
    *,
    jetzt: datetime | None = None,
    aktive: dict[int, ManualOverride | None] | None = None,
) -> dict[int, Boostlage]:
    """Die Lage **vieler** Zimmer, mit vier Abfragen fuer alle zusammen.

    Vier und nicht vier je Zimmer: Sommermodus, Zeitzone, die
    Regelketten und die laufenden Uebersteuerungen. Die Raumtypen kommen
    aus einer fuenften.

    **Die Kette wird einmal geladen und dann je Zimmer gefiltert.** Das
    ist derselbe Filter, den ``lade_rule_configs`` in SQL macht; ihn hier
    in Python zu wiederholen ist die Ausnahme, die der Mengenzugriff
    verlangt — und sie ist eng: dasselbe Feld, dieselben drei Scopes,
    dieselbe Rangfolge in ``resolve_rule_field``.
    """
    now = jetzt or datetime.now(tz=UTC)
    if not rooms:
        return {}

    sommermodus = await is_summer_mode_active(session)
    zone = await lade_zeitzone(session)
    if aktive is None:
        # **Der Listen-Endpunkt gibt sie mit**, weil er sie ohnehin fuer
        # die Spalte braucht und die R-D-Pruefung genau **eine**
        # ``manual_override``-Abfrage je Seitenaufruf zulaesst. Ohne das
        # Argument fragt diese Funktion selbst -- fuer Aufrufer, die den
        # Stand nicht schon haben.
        stand = await stand_je_zimmer(session, [r.id for r in rooms])
        aktive = {rid: eintrag.zimmerweite for rid, eintrag in stand.items()}

    typ_ids = {r.room_type_id for r in rooms if r.room_type_id is not None}
    raumtypen: dict[int, RoomType] = {}
    if typ_ids:
        raumtypen = {
            rt.id: rt
            for rt in (await session.execute(select(RoomType).where(RoomType.id.in_(typ_ids))))
            .scalars()
            .all()
        }

    room_ids = [r.id for r in rooms]
    alle = (
        (
            await session.execute(
                select(RuleConfig).where(
                    (RuleConfig.scope == RuleConfigScope.GLOBAL)
                    | (
                        (RuleConfig.scope == RuleConfigScope.ROOM_TYPE)
                        & (RuleConfig.room_type_id.in_(typ_ids or [-1]))
                    )
                    | (
                        (RuleConfig.scope == RuleConfigScope.ROOM)
                        & (RuleConfig.room_id.in_(room_ids))
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    ergebnis: dict[int, Boostlage] = {}
    for room in rooms:
        kette = [
            rc
            for rc in alle
            if rc.scope == RuleConfigScope.GLOBAL
            or (rc.scope == RuleConfigScope.ROOM_TYPE and rc.room_type_id == room.room_type_id)
            or (rc.scope == RuleConfigScope.ROOM and rc.room_id == room.id)
        ]
        ergebnis[room.id] = beurteile(
            room=room,
            raumtyp=raumtypen.get(room.room_type_id) if room.room_type_id else None,
            kette=kette,
            aktiv=aktive.get(room.id),
            sommermodus=sommermodus,
            zone=zone,
            jetzt=now,
        )
    return ergebnis
