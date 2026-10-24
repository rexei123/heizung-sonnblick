"""Die Sollwerte eines Raumtyps wirksam machen (Sprint 24d).

**Der Befund, gelesen in der Produktion am 24.10.2026.** Die hausweite
``rule_config``-Zeile traegt ``t_occupied = NULL``, ``t_vacant = NULL`` und
``t_night = 19.0``. Die Kette ``ROOM > ROOM_TYPE > GLOBAL`` faellt bei NULL
weiter durch bis auf die Spalte des Raumtyps — „Belegt" und „Frei" wirken
also heute schon. **„Nacht" nicht:** die 19,0 gewinnt gegen jeden Raumtyp.
Derselbe Grund wie beim Bad-Befund vom 18.10.

**Korrektur meiner Behauptung aus 24c.** Dort stand, die Bereiche heizten
im Haus auf den hausweiten Frei-Sollwert von 18 °C. Das war aus der
**Test**-Datenbank geschlossen — deren Seed setzt alle drei Felder — und
ohne Messung auf die Produktion uebertragen (§5.68, in eigener Sache und
zum zweiten Mal in dieser Woche).

**Wie der Vorrang jetzt entsteht, je Art des Raumtyps:**

* **Nicht buchbar** (Allgemeinbereich): die Engine hebt die drei Spalten
  auf ROOM_TYPE-Rang (``rules.engine.bereichs_kette``). Keine Zeile, keine
  Migration, kein Backfill — und damit auch nichts, was ein Rueckfall
  mitnehmen muesste.
* **Buchbar** (Gaestezimmer): unveraendert. Der Vorrang entsteht dort nur
  ueber die ausdrueckliche Admin-Aktion, die eine ROOM_TYPE-Zeile schreibt
  und vorher zeigt, was sich aendert. Automatisch waere es eine Aenderung
  am wirksamen Nachtwert jedes Gaestezimmers — der harte Stopp des
  Sprint-Briefs.

Diese Datei traegt das Nachziehen der Zeile (fuer die Admin-Aktion und fuer
ein Formular, das eine **vorhandene** Zeile bedient) und die Vorschau
„angezeigt / wirksam / Quelle".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.enums import RuleConfigScope
from heizung.models.room_type import RoomType
from heizung.models.rule_config import RuleConfig


class RegelSync(StrEnum):
    """Was das Nachziehen getan hat. Wandert in das Audit."""

    ANGELEGT = "angelegt"
    AKTUALISIERT = "aktualisiert"
    UNVERAENDERT = "unveraendert"
    UEBERSPRUNGEN = "uebersprungen"


async def lade_raumtyp_zeile(session: AsyncSession, room_type_id: int) -> RuleConfig | None:
    """Die saisonlose ROOM_TYPE-Zeile dieses Raumtyps, falls es sie gibt.

    ``season_id IS NULL`` ist Teil der Bedingung und nicht Beiwerk: der
    Eindeutigkeits-Index läuft über ``(scope, room_type_id, room_id,
    season_id)``, es kann also neben der saisonlosen Zeile weitere je
    Saison geben. Die hier gesuchte ist die, die immer gilt.
    """
    stmt = (
        select(RuleConfig)
        .where(RuleConfig.scope == RuleConfigScope.ROOM_TYPE)
        .where(RuleConfig.room_type_id == room_type_id)
        .where(RuleConfig.season_id.is_(None))
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def synchronisiere_raumtyp(
    session: AsyncSession,
    rt: RoomType,
    *,
    anlegen_erlaubt: bool | None = None,
) -> RegelSync:
    """Schreibt ``default_t_occupied/_vacant/_night`` in die ROOM_TYPE-Zeile.

    :param anlegen_erlaubt: ``None`` (Vorgabe) heißt **nicht anlegen** —
        eine vorhandene Zeile wird nachgezogen, eine neue entsteht nicht.
        ``True`` erzwingt das Anlegen; das ist der Weg der Admin-Aktion
        und **nicht** der des normalen Speicherns.

    Die Funktion ``flush``t, aber committet nicht: die Transaktion gehört
    dem Aufrufer (dieselbe Konvention wie ``device_service``, §5.61).
    """
    if anlegen_erlaubt is None:
        # Ohne ausdrueckliche Angabe entsteht **keine** Zeile. Fuer einen
        # Allgemeinbereich braucht es sie nicht (die Engine hebt die
        # Spalten selbst), fuer ein Gaestezimmer darf sie nicht nebenbei
        # entstehen. Wer sie will, sagt es.
        anlegen_erlaubt = False

    zeile = await lade_raumtyp_zeile(session, rt.id)

    if zeile is None:
        if not anlegen_erlaubt:
            return RegelSync.UEBERSPRUNGEN
        session.add(
            RuleConfig(
                scope=RuleConfigScope.ROOM_TYPE,
                room_type_id=rt.id,
                t_occupied=rt.default_t_occupied,
                t_vacant=rt.default_t_vacant,
                t_night=rt.default_t_night,
            )
        )
        await session.flush()
        return RegelSync.ANGELEGT

    # Nur die drei Sollwert-Spalten. Alles andere in der Zeile
    # (Nachtfenster, Vorheiz-Vorlauf, Fenster-Schwellen) gehört nicht zur
    # Raumtyp-Seite und wird hier nicht angefasst — wer es gesetzt hat,
    # hat es woanders gesetzt und soll es behalten.
    vorher = (zeile.t_occupied, zeile.t_vacant, zeile.t_night)
    nachher = (rt.default_t_occupied, rt.default_t_vacant, rt.default_t_night)
    if vorher == nachher:
        return RegelSync.UNVERAENDERT

    zeile.t_occupied = rt.default_t_occupied
    zeile.t_vacant = rt.default_t_vacant
    zeile.t_night = rt.default_t_night
    await session.flush()
    return RegelSync.AKTUALISIERT


# ---------------------------------------------------------------------------
# Die Vorschau: angezeigt / heute wirksam / würde wirksam
# ---------------------------------------------------------------------------

#: Die drei Felder der Raumtyp-Seite und ihre Spalte in ``rule_config``.
#: Einmal hier, damit Vorschau und Nachziehen dieselbe Liste lesen — zwei
#: Listen derselben drei Felder laufen beim vierten auseinander (§5.53).
FELDER: tuple[tuple[str, str], ...] = (
    ("default_t_occupied", "t_occupied"),
    ("default_t_vacant", "t_vacant"),
    ("default_t_night", "t_night"),
)


@dataclass(frozen=True, slots=True)
class FeldBefund:
    """Ein Feld der Raumtyp-Seite, dreifach beantwortet."""

    #: Name der Spalte auf ``room_type``, wie die Seite sie zeigt.
    feld: str
    #: Was auf der Seite steht.
    angezeigt: Decimal
    #: Was die Engine heute für ein Zimmer dieses Typs nimmt — ohne
    #: ROOM-Eintrag, denn der gilt je Zimmer und nicht je Typ.
    wirksam: Decimal | None
    #: Woher der wirksame Wert kommt: ``raumtyp`` / ``global`` /
    #: ``raumtyp_vorgabe`` (die Spalte selbst, weil niemand sonst den Wert
    #: setzt) — dieselben Marken wie im Engine-Trace.
    quelle: str


@dataclass(frozen=True, slots=True)
class RaumtypBefund:
    room_type_id: int
    name: str
    is_bookable: bool
    #: Gibt es die saisonlose ROOM_TYPE-Zeile schon?
    zeile_vorhanden: bool
    felder: tuple[FeldBefund, ...]

    @property
    def wuerde_sich_aendern(self) -> bool:
        """Würde das Nachziehen einen wirksamen Wert verschieben?"""
        return any(f.wirksam != f.angezeigt for f in self.felder)


async def wirksamkeit(
    session: AsyncSession, *, nur_buchbar: bool | None = None
) -> list[RaumtypBefund]:
    """Für jeden Raumtyp: was steht da, was wirkt, woher kommt es.

    **Eine Abfrage für alle Raumtypen**, nicht eine je Zeile — die Liste
    hat heute acht Einträge und die Vorschau läuft im Request (§5.73,
    gehoben statt je Zeile).

    ROOM-Einträge bleiben außen vor, und das ist eine Aussage und kein
    Versehen: ein ``rule_config`` im Scope ``ROOM`` gilt für **ein**
    Zimmer und schlägt beide Ebenen hier. Die Vorschau beantwortet die
    Frage für den Typ; wer für ein einzelnes Zimmer einen Eintrag hat,
    behält ihn.
    """
    stmt = select(RoomType).order_by(RoomType.id)
    if nur_buchbar is not None:
        stmt = stmt.where(RoomType.is_bookable == nur_buchbar)
    raumtypen = list((await session.execute(stmt)).scalars().all())

    zeilen_stmt = (
        select(RuleConfig)
        .where(RuleConfig.scope.in_((RuleConfigScope.ROOM_TYPE, RuleConfigScope.GLOBAL)))
        .where(RuleConfig.season_id.is_(None))
    )
    zeilen = list((await session.execute(zeilen_stmt)).scalars().all())
    je_typ = {z.room_type_id: z for z in zeilen if z.scope == RuleConfigScope.ROOM_TYPE}
    hausweit = next((z for z in zeilen if z.scope == RuleConfigScope.GLOBAL), None)

    befunde: list[RaumtypBefund] = []
    for rt in raumtypen:
        typ_zeile = je_typ.get(rt.id)
        felder: list[FeldBefund] = []
        for spalte, regel_feld in FELDER:
            angezeigt = getattr(rt, spalte)
            aus_typ = getattr(typ_zeile, regel_feld, None) if typ_zeile is not None else None
            aus_global = getattr(hausweit, regel_feld, None) if hausweit is not None else None
            if aus_typ is not None:
                # Eine ausdrueckliche ROOM_TYPE-Zeile gewinnt immer.
                wirksam, quelle = aus_typ, "raumtyp"
            elif not rt.is_bookable:
                # Allgemeinbereich: die Spalte steht auf ROOM_TYPE-Rang
                # (``rules.engine.bereichs_kette``) und schlaegt damit die
                # hausweite Zeile.
                wirksam, quelle = angezeigt, "raumtyp"
            elif aus_global is not None:
                wirksam, quelle = aus_global, "global"
            else:
                # Die hausweite Zeile laesst das Feld leer — dann faellt die
                # Kette auf die Spalte durch. Sie wirkt, aber nicht, weil
                # der Raumtyp Vorrang haette, sondern weil niemand sonst
                # etwas gesagt hat. Der Unterschied zaehlt: ein Speichern
                # auf der globalen Seite nimmt ihr die Wirkung.
                wirksam, quelle = angezeigt, "raumtyp_vorgabe"
            felder.append(
                FeldBefund(feld=spalte, angezeigt=angezeigt, wirksam=wirksam, quelle=quelle)
            )
        befunde.append(
            RaumtypBefund(
                room_type_id=rt.id,
                name=rt.name,
                is_bookable=rt.is_bookable,
                zeile_vorhanden=typ_zeile is not None,
                felder=tuple(felder),
            )
        )
    return befunde


async def nicht_buchbare_typ_ids(session: AsyncSession) -> set[int]:
    """Die IDs aller Raumtypen, die Allgemeinbereiche sind.

    Eine Abfrage je Request, nicht eine je Zimmer: die Zimmerliste
    rendert 45 Zeilen (§5.73, gehoben statt je Zeile).
    """
    stmt = select(RoomType.id).where(RoomType.is_bookable.is_(False))
    return set((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Wer nutzt den Hausstandard wirklich? (Sprint 24d)
# ---------------------------------------------------------------------------

#: Die sechs Felder der globalen Seite. Die ersten drei haben eine Spalte
#: auf ``room_type`` und koennen deshalb auch von dort kommen; die letzten
#: drei gibt es nur als ``rule_config``-Felder.
HAUSSTANDARD_FELDER: tuple[str, ...] = (
    "t_occupied",
    "t_vacant",
    "t_night",
    "night_start",
    "night_end",
    "preheat_minutes_before_checkin",
)

#: Feld -> Spalte auf ``room_type``, soweit es eine gibt.
_SPALTE_ZU_FELD = {regel: spalte for spalte, regel in FELDER}


@dataclass(frozen=True, slots=True)
class NutzungBefund:
    """Wie oft der hausweite Wert eines Feldes wirklich zum Tragen kommt."""

    feld: str
    #: Ist das Feld in der hausweiten Zeile gesetzt?
    gesetzt: bool
    #: Raumtypen, die diesen Wert tatsaechlich uebernehmen.
    raumtypen_nutzen: int
    #: Raumtypen mit eigenem Wert (Zeile oder — bei einem Bereich — Spalte).
    raumtypen_eigen: int
    #: Zimmer mit eigenem Wert fuer dieses Feld (Scope ROOM).
    zimmer_eigen: int


async def hausstandard_nutzung(session: AsyncSession) -> list[NutzungBefund]:
    """Je Feld der globalen Seite: wer nimmt den Wert, wer hat seinen eigenen.

    **Warum das auf der globalen Seite steht.** Ein hausweiter Wert sieht
    aus wie eine Einstellung fuer das ganze Haus und ist in Wirklichkeit
    eine **Vorgabe fuer den Rest** — fuer alles, was nichts eigenes sagt.
    Ohne diese Zahl ist nicht zu sehen, ob eine Aenderung dort 45 Zimmer
    bewegt oder keines. Am 24.10.2026 war der Fall eindeutig: die Felder
    „Belegt" und „Frei" sind **leer**, und die Seite zeigte trotzdem 21,0
    und 18,0 — ein Speichern haette jeden Raumtyp uebersteuert.

    Zimmer mit eigenem Wert sind **nicht** dieselbe Frage wie Raumtypen
    mit eigenem Wert, und beide stehen deshalb getrennt: ein Zimmer
    gewinnt gegen seinen Raumtyp, ein Raumtyp gegen das Haus.
    """
    hausweit_stmt = (
        select(RuleConfig)
        .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
        .where(RuleConfig.room_type_id.is_(None))
        .where(RuleConfig.room_id.is_(None))
        .where(RuleConfig.season_id.is_(None))
    )
    hausweit = (await session.execute(hausweit_stmt)).scalar_one_or_none()

    raumtypen = list((await session.execute(select(RoomType))).scalars().all())
    typ_zeilen = {
        z.room_type_id: z
        for z in (
            await session.execute(
                select(RuleConfig)
                .where(RuleConfig.scope == RuleConfigScope.ROOM_TYPE)
                .where(RuleConfig.season_id.is_(None))
            )
        )
        .scalars()
        .all()
    }
    zimmer_zeilen = list(
        (
            await session.execute(
                select(RuleConfig)
                .where(RuleConfig.scope == RuleConfigScope.ROOM)
                .where(RuleConfig.season_id.is_(None))
            )
        )
        .scalars()
        .all()
    )

    befunde: list[NutzungBefund] = []
    for feld in HAUSSTANDARD_FELDER:
        spalte = _SPALTE_ZU_FELD.get(feld)
        eigen = 0
        for rt in raumtypen:
            zeile = typ_zeilen.get(rt.id)
            hat_zeile = zeile is not None and getattr(zeile, feld, None) is not None
            # Ein Allgemeinbereich traegt seine Sollwerte in der Spalte und
            # die steht auf ROOM_TYPE-Rang (``rules.engine.bereichs_kette``).
            hat_spalte = spalte is not None and not rt.is_bookable
            if hat_zeile or hat_spalte:
                eigen += 1
        befunde.append(
            NutzungBefund(
                feld=feld,
                gesetzt=hausweit is not None and getattr(hausweit, feld, None) is not None,
                raumtypen_nutzen=len(raumtypen) - eigen,
                raumtypen_eigen=eigen,
                zimmer_eigen=sum(1 for z in zimmer_zeilen if getattr(z, feld, None) is not None),
            )
        )
    return befunde
