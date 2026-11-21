"""Schemata fuer den Tagesplan eines Allgemeinbereichs (21.11.2026).

**Uhrzeiten als Zeichenkette und nicht als ``time``** — derselbe Grund wie
bei ``BetriebszeitUpdate``: ``"24:00"`` ist erlaubt und Pydantic wuerde es
als ``time`` abweisen. Das Muster steht in ``heizung.uhrzeit`` und gilt
damit fuer beide Eingaben.

**Die Ueberschneidungspruefung steht hier und nicht im Dienst.** Sie
gehoert zur Eingabe: wer zwei sich ueberschneidende Fenster schickt, hat
keinen halben Plan geschickt, sondern einen unmoeglichen. Pydantic macht
daraus eine 422 mit dem Satz, der die Stelle nennt. Die Datenbank hat
dieselbe Regel als ``EXCLUDE``-Bedingung — **nicht** als Verdopplung,
sondern weil nur sie bei zwei gleichzeitigen Anfragen haelt (§5.60,
dasselbe Doppel wie bei ``replace_device``). Und das Formular hat sie ein
drittes Mal in Zod, damit man den Fehler beim Tippen sieht und nicht beim
Speichern.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_serializer, model_validator

from heizung.uhrzeit import MUSTER, als_text, parse_minuten

#: Hoechstzahl der Fenster je Bereich. Keine technische Grenze, sondern
#: eine Aussage ueber die Eingabe: ein Tag mit mehr als zwoelf Abschnitten
#: ist keine Betriebszeit mehr, sondern ein Fahrplan — und eine unbegrenzte
#: Liste ist eine Einladung, die Tabelle als Speicher zu benutzen.
MAX_FENSTER: int = 12

#: Die Grenzen der Vicki (``engine.MIN_SETPOINT_C`` / ``MAX_SETPOINT_C``).
#: Dieselben Zahlen stehen als ``CHECK`` an der Tabelle; hier erzeugen sie
#: die lesbare Meldung.
MIN_TEMPERATUR = Decimal("10")
MAX_TEMPERATUR = Decimal("30")


class TagesplanFensterEingabe(BaseModel):
    """Ein Fenster, wie es aus dem Formular kommt."""

    von: str = Field(pattern=MUSTER, examples=["06:00"])
    bis: str = Field(pattern=MUSTER, examples=["08:00"])
    temperatur: Decimal = Field(ge=MIN_TEMPERATUR, le=MAX_TEMPERATUR, examples=["25.0"])

    @property
    def von_minute(self) -> int:
        return parse_minuten(self.von)

    @property
    def bis_minute(self) -> int:
        return parse_minuten(self.bis)


class TagesplanFensterRead(BaseModel):
    """Ein gespeichertes Fenster."""

    id: int
    von: str
    bis: str
    temperatur: Decimal

    @field_serializer("temperatur")
    def _decimal_als_zahl(self, v: Decimal) -> float:
        # §5.63: Decimal -> JSON-Zahl, nicht String. Ein String hier waere
        # im Browser ``"22.0" + 1 === "22.01"``, und genau daran ist die
        # Relais-Karte am 20.11.2026 umgefallen.
        return float(v)


class TagesplanRead(BaseModel):
    """Der Plan eines Bereichs. Leere Liste heisst: kein Plan."""

    room_id: int
    fenster: list[TagesplanFensterRead]


class TagesplanUpdate(BaseModel):
    """Der **ganze** Plan, nicht ein einzelnes Fenster.

    **Warum die ganze Liste.** Drei Gruende, und der dritte ist der
    eigentliche:

    1. Idempotenz (§0 S2): zweimal dasselbe geschickt ergibt denselben
       Zustand.
    2. Die Ueberschneidungspruefung braucht den vollstaendigen Satz. Fenster
       einzeln zu pruefen heisst, sie gegen den Bestand zu pruefen — und der
       aendert sich waehrend der Bearbeitung.
    3. **Zwei Fenster zu tauschen waere sonst unmoeglich.** Wer 06:00-08:00
       und 08:00-10:00 vertauschen will, verletzt bei jedem einzelnen
       Schritt die ``EXCLUDE``-Bedingung, ganz gleich mit welchem er
       anfaengt. Ein vollstaendiger Austausch in **einer** Transaktion hat
       das Problem nicht.
    """

    fenster: list[TagesplanFensterEingabe] = Field(max_length=MAX_FENSTER)

    @model_validator(mode="after")
    def _spanne_und_ueberschneidung(self) -> TagesplanUpdate:
        """``von < bis`` je Fenster, und keine zwei ueberschneiden sich.

        Geprueft wird in Minuten und nicht an den Zeichenketten: die
        Muster-Pruefung des Feldes hat die Form schon zugesichert, und eine
        Zahl ist die Form, in der die Tabelle und die Engine rechnen.
        """
        spannen = sorted(
            ((f.von_minute, f.bis_minute) for f in self.fenster),
            key=lambda s: s[0],
        )
        for von_minute, bis_minute in spannen:
            if von_minute >= bis_minute:
                raise ValueError(
                    f"Das Fenster {als_text(von_minute)}-{als_text(bis_minute)} endet nicht "
                    "nach seinem Beginn. Ein Fenster ueber Mitternacht gibt es nicht — "
                    "legen Sie zwei an, zum Beispiel 23:00-24:00 und 00:00-01:00."
                )
        for (_, erstes_ende), (zweiter_beginn, _) in zip(spannen, spannen[1:], strict=False):
            if zweiter_beginn < erstes_ende:
                raise ValueError(
                    f"Die Fenster ueberschneiden sich: {als_text(zweiter_beginn)} liegt noch "
                    f"in einem Fenster, das erst um {als_text(erstes_ende)} endet. Zu einer "
                    f"Uhrzeit darf nur ein Sollwert gelten, sonst entscheidet die Reihenfolge "
                    f"der Zeilen darueber, welcher. Aneinander stossen duerfen die Fenster: "
                    f"endet eines um {als_text(erstes_ende)}, darf das naechste dort beginnen."
                )
        return self
