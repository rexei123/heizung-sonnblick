"""Der Raumtyp „Bad" als Vorlage fuer alle Bad-Zonen (18.10.2026).

**Der Anlass.** Bad-Zonen folgten dem Zimmertyp (21/18/19) — ein Bad war
also nachts so kalt wie das Schlafzimmer. Der Betreiber will fuer Baeder
belegt 22, frei 18, nachts 22, Grenzen 18/25. Genau diese Werte stehen
schon am Raumtyp **„Bad"**, und der ist **0 Zimmern** zugeordnet: er war
bis heute wirkungslos.

**Was vorher nirgends war: die Zonen-Art.** ``kind`` kam in der ganzen
Steuerlogik nicht vor — gemessen am 18.10.2026 gegen ``2d6ab24``: keine
Fundstelle fuer ``bathroom`` oder ``.kind`` in ``rules/``, ``tasks/`` oder
``services/`` ausser ``room_history.py`` (Anzeige). Die Auflösungskette
``ROOM > ROOM_TYPE > GLOBAL`` haengt am ``room_type_id`` des **Zimmers**,
und die Engine rechnet **einen** Sollwert je Zimmer.

**Die kleinste Lösung ist deshalb keine neue Schicht, sondern ein zweiter
Durchlauf mit getauschtem Raumtyp.** Die Engine rechnet den Bad-Wert mit
denselben Layer-Funktionen (1 Belegung, 2 Vorheizen/Nacht, 5 Clamp), nur
mit diesem Raumtyp. Damit gelten Vorheizen, Nachtfenster und Grenzen fuers
Bad automatisch mit — ohne eine Zeile Regel-Logik zu verdoppeln (§5.53).

**Die Kette bleibt vollstaendig.** Der zweite Durchlauf benutzt dieselbe
``lade_rule_configs``-Abfrage, nur mit der ``room_type_id`` der Vorlage:
also ``ROOM`` (dieses Zimmer) **vor** ``ROOM_TYPE`` (Bad) vor ``GLOBAL``.
Eine Zimmer-Einstellung sticht die Vorlage damit weiterhin aus — so hat
der Betreiber es verlangt, und es braucht dafuer keine eigene Logik.

**Kein neues Datenmodell.** Kein Scope-Wert, keine Spalte, keine
Migration. Die Zuordnung laeuft ueber den **Namen** des Raumtyps — und der
steht in den Einstellungen (``BAD_VORLAGE_ROOM_TYPE``, Vorgabe ``Bad``),
nicht als Konstante im Code. Der Name ist eine Betriebsentscheidung: wer
den Raumtyp umbenennt, soll den Baedern nicht ihre Vorlage nehmen muessen.
Leer oder nicht vorhanden heisst "keine Vorlage", und dann verhaelt sich
alles wie vor dem 18.10. — diese Funktion gibt ``None`` zurueck, und
weiter oben gibt es keinen Sonderfall.

**Was die Vorlage NICHT aussticht:** Zimmer- und Zonen-Übersteuerungen,
den Sommermodus, die Fenster-Sicherheit und den Demontage-Frostschutz.
Greift eine dieser zimmerweiten Entscheidungen, folgt das Bad dem
Zimmerwert — Sicherheit und eine ausdrueckliche Gast-Wahl gelten im Bad
genauso. Die Pruefung dazu steht in ``engine.evaluate_room``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.config import get_settings
from heizung.models.room_type import RoomType


async def lade_bad_vorlage(session: AsyncSession) -> RoomType | None:
    """Der Raumtyp „Bad", oder ``None`` wenn es ihn nicht gibt.

    Eine Abfrage je Engine-Evaluierung. Der Name ist ``unique``
    (``room_type.name``), die Antwort also eindeutig.

    ``None`` ist ein gueltiges Ergebnis und heisst „keine Vorlage" — die
    Baeder folgen dann dem Zimmertyp, genau wie vor dem 18.10.2026. Kein
    Fehler, kein Log-Rauschen: ein Haus ohne eigenen Bad-Raumtyp ist ein
    zulaessiger Zustand.
    """
    name = get_settings().bad_vorlage_room_type.strip()
    if not name:
        return None
    stmt = select(RoomType).where(RoomType.name == name)
    return (await session.execute(stmt)).scalar_one_or_none()
