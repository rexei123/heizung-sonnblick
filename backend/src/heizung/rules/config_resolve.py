"""Die RuleConfig-Hierarchie, einmal (Sprint 21 A1).

``rule_config`` traegt die Soll- und Zeitwerte in drei Geltungsbereichen —
``ROOM > ROOM_TYPE > GLOBAL`` —, jedes Feld ``NULL``-faehig mit der
Bedeutung "erben". Wer einen Wert braucht, muss die Kette laufen.

**Warum das hier liegt und nicht in ``engine.py``.** Die Engine hat die
Kette seit Sprint 9.8a, und seit Sprint 21 A1 braucht sie auch der
Verlauf-Endpunkt: er zeichnet das Nacht-Band, und das Nachtfenster steht
genau hier. Ein Import aus ``engine.py`` nach ``api/`` oder ``services/``
waere zirkulaer, weil ``engine.py`` selbst ``services/override_service``
importiert (CLAUDE.md §5.46 — dieselbe Lage wie bei
``rules/window_state.py``). Dieses Modul haengt nur an ``models`` und
kennt weder Engine noch Services.

**Was es nicht ist: eine zweite Wahrheit.** Die Engine ruft seit dem Auszug
dieselben zwei Funktionen. Haette der Endpunkt die Kette nachgebaut, waere
genau der Fall aus §5.53 entstanden: zwei Stellen, die dasselbe berechnen,
und beim ersten Umbau laufen sie auseinander — hier besonders tueckisch,
weil die Oberflaeche dann ein Nacht-Band zeichnet, nach dem die Engine
nicht regelt.

**Die Saison-Spalte ist bewusst nicht gefiltert.** ``rule_config.season_id``
begrenzt einen Eintrag auf einen Zeitraum (AE-26), und die Abfrage unten
beachtet das **nicht** — sie ist ein wortgleicher Auszug aus
``_load_room_context``, wo es seit Sprint 9.8a so steht. Das hier zu
aendern waere eine Verhaltensaenderung an der Engine, getarnt als
Refactoring; der Auszug muss verhaltensneutral sein (§5.47). Wer die
Saison scharf stellen will, tut das in einem eigenen Schritt und fuer
beide Aufrufer zugleich.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RuleConfigScope
from heizung.models.global_config import GlobalConfig
from heizung.models.rule_config import RuleConfig
from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE


async def lade_rule_configs(
    session: AsyncSession, *, room_id: int, room_type_id: int | None
) -> list[RuleConfig]:
    """Alle Eintraege, die fuer dieses Zimmer gelten koennen — alle drei Scopes.

    ``GLOBAL`` immer, ``ROOM_TYPE`` wenn der Typ passt, ``ROOM`` nur fuer
    dieses Zimmer. Die Reihenfolge entscheidet nicht die Abfrage, sondern
    ``resolve_rule_field``.

    Sprint 9.8a hat hier einen Fehler behoben, der sich lohnt zu kennen:
    ``room.rule_configs`` als Relationship liefert **nur** den ROOM-Scope
    (der Fremdschluessel zeigt auf das Zimmer). Wer die Relationship nimmt,
    bekommt also lautlos die halbe Hierarchie und faellt auf die
    Hardcoded-Vorgaben zurueck.
    """
    stmt = select(RuleConfig).where(
        (RuleConfig.scope == RuleConfigScope.GLOBAL)
        | (
            (RuleConfig.scope == RuleConfigScope.ROOM_TYPE)
            & (RuleConfig.room_type_id == room_type_id)
        )
        | ((RuleConfig.scope == RuleConfigScope.ROOM) & (RuleConfig.room_id == room_id))
    )
    return list((await session.execute(stmt)).scalars().all())


def resolve_rule_field(rule_configs: list[RuleConfig], field_name: str) -> Any:
    """Erster nicht-``NULL``-Wert in der Kette ROOM > ROOM_TYPE > GLOBAL.

    Gibt ``None`` zurueck, wenn kein Scope den Wert setzt — das ist ein
    gueltiges Ergebnis und heisst "nicht konfiguriert", nicht "Fehler". Die
    Engine faellt dann je Feld auf ihre eigene Vorgabe zurueck (etwa
    ``room_type.default_t_night``), der Verlauf laesst das Nacht-Band weg.

    Funktioniert fuer ``Decimal``, ``time`` und ``int`` gleich, weil nur auf
    ``is not None`` geprueft wird. **Das schliesst ``0`` ein**: eine
    konfigurierte Null gewinnt gegen das Erben, und das ist richtig — sonst
    liesse sich ein geerbter Wert nicht auf Null stellen.
    """
    by_scope: dict[RuleConfigScope, list[RuleConfig]] = {
        RuleConfigScope.ROOM: [],
        RuleConfigScope.ROOM_TYPE: [],
        RuleConfigScope.GLOBAL: [],
    }
    for rc in rule_configs:
        by_scope[rc.scope].append(rc)
    for scope in (RuleConfigScope.ROOM, RuleConfigScope.ROOM_TYPE, RuleConfigScope.GLOBAL):
        for rc in by_scope[scope]:
            value = getattr(rc, field_name, None)
            if value is not None:
                return value
    return None


async def lade_zeitzone(session: AsyncSession) -> str:
    """Die Hotel-Zeitzone aus dem ``global_config``-Singleton.

    Defensiver Rueckfall auf ``DEFAULT_HOTEL_TIMEZONE``, wenn die Zeile
    fehlt (frisches Setup vor dem Seed) oder die Spalte leer ist — AE-60.

    Jede Uhrzeit, die der Mensch sieht, haengt an diesem Wert: die Engine
    vergleicht in Ortszeit (§5.65), und eine Uhrzeit ohne ihre Zone neben
    einer anderen Uhrzeit ist die Falle aus §5.79.
    """
    gc = await session.get(GlobalConfig, 1)
    return gc.timezone if gc and gc.timezone else DEFAULT_HOTEL_TIMEZONE
