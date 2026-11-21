"""Tagesplan eines Allgemeinbereichs: Zeitfenster mit eigenem Sollwert.

**Der Wunsch (Brief in #421, Punkt 12).** Eine Bar soll von 06:00 bis
08:00 auf 25 °C stehen, von 08:00 bis 21:00 auf 22 °C, und sonst
abgesenkt sein. Das ist **mehr als ein Fenster**, und mehr als eines kann
die Steuerung bis heute nicht: ``rule_config`` traegt genau ein Paar
(``night_start`` / ``night_end``), das die Betriebszeit seit Sprint 24d
belegt.

**Eine Tabelle, nicht zwei** — abweichend vom Brief, der einen
``tagesplan`` mit Namen und Aktiv-Schalter und daneben seine Fenster
vorschlug. Begruendung (S6, die Beweislast liegt bei der Komplexitaet):

* Ein Bereich hat **einen** Plan. Ein Name dafuer waere ein zweiter Name
  fuer die Bar, die schon einen hat.
* „Kein Plan" braucht keinen Schalter, sondern **keine Zeile**. Ein
  Aktiv-Schalter auf ``false`` neben drei Fenstern ist ein Zustand, den
  man erklaeren muss; eine leere Liste ist keiner.
* Beides ist additiv nachruestbar, sobald jemand es braucht — ein
  nullable ``name`` und ein ``aktiv`` mit Vorgabe ``true`` aendern an den
  Bestandszeilen nichts.

**Die Erbkette hat der Plan nicht**, auch das abweichend vom Brief (dort:
hausweit / Raumtyp / Zimmer wie bei ``rule_config``). Die Betriebszeit hat
diese Frage am 24.10.2026 schon entschieden, und zwar mit Begruendung:
„Bar und Rezeption haben denselben Charakter und verschiedene Zeiten; die
Zeit gehoert zum Ort, nicht zur Art." Fuer den Plan gilt das Wort fuer
Wort. Ein hausweiter Tagesplan waere ausserdem ein Plan, der auf 47
Gaestezimmer wirkt, sobald ihn jemand anlegt.

**Minuten statt ``time``** — die Begruendung steht in ``heizung.uhrzeit``:
``"bis 24:00"`` ist bei der Betriebszeit erlaubt, und ``time`` kennt
diesen Wert nicht.

**Keine Fenster ueber Mitternacht.** ``bis_minute > von_minute`` ist eine
Beschraenkung der Datenbank, und das ist Absicht: ein umschlagendes
Fenster (23:00–01:00) waere mit der ``EXCLUDE``-Bedingung nicht pruefbar
(ein ``int4range`` kann nicht rueckwaerts laufen), und „Luecke =
Absenkung" waere nicht mehr eindeutig. Wer die Nacht ueberbruecken will,
tippt zwei Zeilen: 23:00–24:00 und 00:00–01:00. Die Lesart ist dieselbe,
die Pruefung bleibt entscheidbar.

**Die ``EXCLUDE``-Bedingung gegen Ueberschneidungen steht in Migration
0042 und nicht hier.** Sie braucht ``btree_gist`` und einen
Bereichsausdruck (``int4range(von_minute, bis_minute)``); das Schema der
Tests entsteht ohnehin durch ``alembic upgrade head`` (``conftest``), nie
durch ``create_all``. Wer sie sucht, findet sie unter
``uq_tagesplan_fenster_ohne_ueberschneidung``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, SmallInteger, func
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base
from heizung.uhrzeit import MINUTEN_PRO_TAG


class TagesplanFenster(Base):
    """Ein Zeitfenster eines Tages mit seinem Sollwert."""

    __tablename__ = "tagesplan_fenster"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Der Bereich, dem das Fenster gehoert. ``CASCADE``, weil ein
    #: geloeschtes Zimmer keine Zeiten mehr hat.
    room_id: Mapped[int] = mapped_column(
        ForeignKey("room.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Beginn in Minuten seit Mitternacht, ``0`` bis ``1439``.
    von_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    #: Ende in Minuten seit Mitternacht, ``1`` bis ``1440``. ``1440`` ist
    #: „24:00" und damit Mitternacht als **Ende** des Tages.
    bis_minute: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    #: Der Sollwert dieses Fensters. ``Numeric(4, 1)`` wie jeder andere
    #: Sollwert im Projekt — die Engine quantisiert am Ende selbst, und ein
    #: ``float`` waere die eine Stelle, an der 22,1 zu 22,099999 wird.
    temperatur: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            f"von_minute >= 0 AND bis_minute <= {MINUTEN_PRO_TAG} AND von_minute < bis_minute",
            name="ck_tagesplan_fenster_spanne",
        ),
        # Die Hardware-Grenzen der Vicki (``engine.MIN_SETPOINT_C`` /
        # ``MAX_SETPOINT_C``). Die Kappung in Schicht 5 macht die
        # eigentliche Arbeit; diese Bedingung haelt nur davon ab, eine Zahl
        # zu speichern, die nie ankommen koennte.
        CheckConstraint(
            "temperatur >= 10 AND temperatur <= 30",
            name="ck_tagesplan_fenster_temperatur",
        ),
        Index("ix_tagesplan_fenster_room_von", "room_id", "von_minute"),
    )

    def __repr__(self) -> str:  # pragma: no cover - Diagnose
        return (
            f"<TagesplanFenster id={self.id} room={self.room_id} "
            f"{self.von_minute}-{self.bis_minute} {self.temperatur}>"
        )
