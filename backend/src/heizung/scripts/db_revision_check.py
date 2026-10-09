"""Vorcheck vor ``alembic upgrade head``: kennt dieses Image die DB-Revision?

**Sprint 20g, H-6 Nachtrag (Befund des Hoteliers, 09.10.2026).**

Der Rueckfallpunkt (AE-77, RUNBOOK §10u) setzt den Server auf ein aelteres
Image. Dessen Entrypoint fuehrt ``alembic upgrade head`` aus — und findet in
``alembic_version`` eine Revision, die es in seinem eigenen
``versions/``-Verzeichnis **nicht gibt**. Alembic bricht dann ab:

    ERROR [alembic.util.messaging] Can't locate revision identified by
    '0028_global_config_pin_seen'
    FAILED: Can't locate revision identified by '0028_global_config_pin_seen'

Der Entrypoint versucht es fuenfmal und beendet sich mit ``exit 1``. Weil
``restart: always`` gilt und **api, celery_worker und celery_beat dasselbe
Image mit demselben Entrypoint** fahren, waere das Ergebnis kein halber
Rueckfall, sondern ein Neustart-Karussell ohne API und ohne Engine — und
zwar in dem Moment, in dem jemand unter Druck zurueckrollt.

**Der eigentliche Fund ist, dass das unabhaengig von der Additivitaet
passiert.** AE-77 §8 hat Rueckfaelle „ueber additive Migrationen" erlaubt,
weil eine neue leere Spalte den alten Code nicht stoert. Das stimmt fuer das
**Schema** und half nichts: Alembic scheitert an seiner eigenen
Buchfuehrung, bevor eine Zeile Schema geprueft wird. Ohne diesen Vorcheck
machte **jede** Migration einen Rueckfall unmoeglich.

Was dieses Modul tut
--------------------

Es vergleicht die Revision in der Datenbank mit dem, was dieses Image
kennt, und sagt dem Entrypoint per Rueckgabe-Code, was zu tun ist:

=====  ==================================================================
``0``  Upgrade ausfuehren (Normalfall, und jeder unklare Fall).
``10`` Upgrade **ueberspringen**: die DB kennt eine Revision, die dieses
       Image nicht hat — sie ist also neuer als der Code. Rueckwaerts
       migriert niemand automatisch, und raten darf der Container nicht.
=====  ==================================================================

**Es gibt bewusst keinen Fehler-Code.** Dieser Vorcheck ist eine Zugabe und
darf nicht selbst zur Abbruchursache werden: ist die DB nicht erreichbar,
fehlt ``alembic.ini``, geht irgendetwas anderes schief — dann ``0``, und der
Entrypoint verhaelt sich wie vorher (fuenf Versuche, dann sichtbarer
Absturz). Der Vorcheck kann nur **verhindern**, nie zusaetzlich scheitern.

Grenze
------

Dass der Container startet, heisst nicht, dass der Rueckfall fachlich
zulaessig ist. Bei einer **nicht-additiven** Migration (Spalte entfernt,
umbenannt, verengt) laeuft der alte Code gegen ein Schema, in dem etwas
fehlt — er startet dann und scheitert spaeter an der Abfrage. Diese
Unterscheidung bleibt bei RUNBOOK §10u Schritt 0b und der Pflichtzeile im
PR-Template; sie steht hier nicht nachtraeglich zur Verfuegung.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# Rueckgabe-Codes. ``0`` ist "weiter wie bisher", und zwar auch in jedem
# Zweifelsfall — siehe Modul-Docstring.
AUSFUEHREN = 0
UEBERSPRINGEN = 10


def _url() -> str:
    """DB-URL wie ``alembic/env.py`` sie aufloest (dort Stufe 2 und 3)."""
    from heizung.config import get_settings

    return os.environ.get("TEST_DATABASE_URL") or get_settings().database_url


def _ini_pfad() -> Path:
    """``alembic.ini`` — im Container ``/app/alembic.ini`` (WORKDIR)."""
    kandidat = Path("alembic.ini")
    if kandidat.is_file():
        return kandidat
    # Lokaler Aufruf aus einem Unterverzeichnis heraus.
    return Path(__file__).resolve().parents[3] / "alembic.ini"


async def _db_revisionen(url: str) -> set[str] | None:
    """Was steht in ``alembic_version``?

    ``None`` heisst "nicht feststellbar" — frische DB ohne die Tabelle,
    DB nicht erreichbar, Rechte fehlen. Alle drei fuehren zu ``0``.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url, pool_pre_ping=False)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return {r[0] for r in rows if r[0]}
    except Exception as exc:  # noqa: BLE001 - jeder Fehler heisst hier "keine Aussage"
        print(f"[revisions-vorcheck] DB-Revision nicht feststellbar: {type(exc).__name__}")
        return None
    finally:
        await engine.dispose()


def _bekannte_revisionen(ini: Path) -> set[str] | None:
    """Alle Revisionen, die dieses Image in ``versions/`` hat."""
    try:
        cfg = Config(str(ini))
        skript = ScriptDirectory.from_config(cfg)
        return {rev.revision for rev in skript.walk_revisions()}
    except Exception as exc:  # noqa: BLE001 - siehe oben
        print(f"[revisions-vorcheck] Revisionen nicht lesbar: {type(exc).__name__}")
        return None


def entscheiden(in_db: set[str] | None, bekannt: set[str] | None) -> int:
    """Die Entscheidung, ohne Datenbank und ohne Dateisystem.

    Getrennt von ``pruefen``, damit sie pruefbar ist, ohne die Revision in
    der gemeinsamen Test-Datenbank zu verbiegen — ein Test, der dort
    ``alembic_version`` umschreibt und beim Abbruch nicht zurueckstellt,
    legt jede folgende Testdatei lahm.
    """
    if bekannt is None or in_db is None:
        return AUSFUEHREN
    if not in_db:
        # Tabelle da, aber leer: alembic-Stand "nichts angewendet".
        print("[revisions-vorcheck] alembic_version ist leer - Upgrade laeuft.")
        return AUSFUEHREN

    unbekannt = sorted(in_db - bekannt)
    if not unbekannt:
        print(f"[revisions-vorcheck] DB-Revision bekannt ({', '.join(sorted(in_db))}).")
        return AUSFUEHREN

    # Der Fall, um den es geht.
    print("")
    print("=" * 70)
    print("[revisions-vorcheck] MIGRATION UEBERSPRUNGEN - die Datenbank ist")
    print("                     NEUER als dieser Programmstand.")
    print("")
    print(f"  In der Datenbank steht:   {', '.join(unbekannt)}")
    print("  Dieses Image kennt das nicht.")
    print("")
    print("  Das ist der erwartete Zustand nach einem Rueckfall per PIN_SHA")
    print("  (RUNBOOK 10u). Die Anwendung startet; 'alembic upgrade head'")
    print("  waere abgebrochen und haette den Container am Start gehindert.")
    print("")
    print("  WICHTIG: zusaetzliche Spalten stoeren den alten Code nicht.")
    print("  Wurde dagegen etwas ENTFERNT, UMBENANNT oder VERENGT, laeuft")
    print("  dieser Stand gegen ein Schema, in dem etwas fehlt - dann ist")
    print("  der Rueckfall nicht zulaessig (RUNBOOK 10u, Schritt 0b).")
    print("=" * 70)
    print("")
    return UEBERSPRINGEN


def pruefen() -> int:
    """Liest beide Seiten und entscheidet. Wirft nicht."""
    bekannt = _bekannte_revisionen(_ini_pfad())
    in_db = asyncio.run(_db_revisionen(_url())) if bekannt is not None else None
    return entscheiden(in_db, bekannt)


def main() -> int:
    """Faengt alles ab: dieser Vorcheck darf nie die Abbruchursache sein.

    Die Zweige in ``pruefen`` fangen ihre eigenen Fehler, aber nicht jeden
    denkbaren — ein ``UnicodeEncodeError`` beim Ausgeben etwa, wenn der
    Container ohne UTF-8-Locale laeuft. Genau dort wird der Vorcheck sonst
    stillschweigend wirkungslos: ein anderer Rueckgabe-Code als 10 heisst
    fuer den Entrypoint "ausfuehren", und das Neustart-Karussell waere
    zurueck. Die ausgegebenen Zeichenketten sind deshalb ASCII (§5.3), und
    hier liegt der Fangnetz-Fall darunter.
    """
    try:
        return pruefen()
    except BaseException as exc:  # noqa: BLE001 - absichtlich alles
        print(f"[revisions-vorcheck] Vorcheck selbst gescheitert: {type(exc).__name__}")
        print("[revisions-vorcheck] Weiter wie bisher: Upgrade wird versucht.")
        return AUSFUEHREN


if __name__ == "__main__":
    sys.exit(main())
