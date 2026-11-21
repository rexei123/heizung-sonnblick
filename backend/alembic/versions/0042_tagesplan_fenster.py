"""tagesplan_fenster: mehrere Zeitfenster am Tag, je Fenster ein Sollwert.

**Der Anlass, 21.11.2026.** Der Betreiber will fuer die
Allgemeinbereiche mehr als ein Zeitfenster: 06:00–08:00 auf 25 °C,
08:00–21:00 auf 22 °C, sonst Absenkung. Die Steuerung hat bis hierher
**ein** Fenster je Zimmer (``rule_config.night_start`` / ``night_end``),
und das belegt seit Sprint 24d die Betriebszeit.

**Was die Tabelle traegt** — die Begruendung der Form steht im Modell
(``models/tagesplan``), hier nur das Schema:

* ``room_id`` — der Bereich, ``CASCADE``.
* ``von_minute`` / ``bis_minute`` — Minuten seit Mitternacht, halboffen
  ``[von, bis)``. ``1440`` ist „24:00" und nur als **Ende** gueltig.
* ``temperatur`` — ``Numeric(4, 1)`` wie jeder Sollwert im Projekt.

**Die ``EXCLUDE``-Bedingung ist der Kern dieser Migration.** Zwei
Fenster, die sich ueberschneiden, machen die Steuerentscheidung von der
Reihenfolge der Zeilen abhaengig — und das ist der Nichtdeterminismus,
den §0 S2 verbietet. Die Pruefung im Dienst liefert die lesbare
Fehlermeldung; die Bedingung hier ist die, die auch bei zwei
gleichzeitigen Anfragen haelt (dasselbe Doppel wie bei ``replace_device``,
§5.60: der Python-Vorcheck sagt es schoen, die Datenbank sagt es
verbindlich).

``btree_gist`` ist dafuer noetig: ``room_id`` geht mit ``=`` in die
Bedingung, und ein GiST-Index kennt die Gleichheit auf ``integer`` nur mit
dieser Erweiterung. ``CREATE EXTENSION IF NOT EXISTS`` — auf
TimescaleDB ist sie vorhanden (geprueft gegen
``timescale/timescaledb:latest-pg16``, dasselbe Image wie in CI), und das
``IF NOT EXISTS`` macht den Lauf wiederholbar.

**Der ``downgrade`` nimmt die Erweiterung nicht mit.** ``DROP EXTENSION``
wuerde eine Erweiterung entfernen, die eine spaetere Migration oder eine
fremde Tabelle ebenfalls benutzen koennte; sie kostet nichts und bleibt
stehen.

Migration additiv: ja — eine neue Tabelle, kein Backfill, keine
Beschraenkung auf Bestandszeilen. Ohne Zeile in dieser Tabelle verhaelt
sich die Steuerung wie vorher.

Revision ID: 0042_tagesplan_fenster
Revises: 0041_relais_empfangsdaten
Create Date: 2026-11-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042_tagesplan_fenster"
down_revision: str | None = "0041_relais_empfangsdaten"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "tagesplan_fenster",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "room_id",
            sa.Integer(),
            sa.ForeignKey("room.id", ondelete="CASCADE", name="fk_tagesplan_fenster_room"),
            nullable=False,
        ),
        sa.Column("von_minute", sa.SmallInteger(), nullable=False),
        sa.Column("bis_minute", sa.SmallInteger(), nullable=False),
        sa.Column("temperatur", sa.Numeric(4, 1), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "von_minute >= 0 AND bis_minute <= 1440 AND von_minute < bis_minute",
            name="ck_tagesplan_fenster_spanne",
        ),
        sa.CheckConstraint(
            "temperatur >= 10 AND temperatur <= 30",
            name="ck_tagesplan_fenster_temperatur",
        ),
    )
    op.create_index("ix_tagesplan_fenster_room_id", "tagesplan_fenster", ["room_id"])
    op.create_index("ix_tagesplan_fenster_room_von", "tagesplan_fenster", ["room_id", "von_minute"])
    op.execute(
        "ALTER TABLE tagesplan_fenster ADD CONSTRAINT "
        "uq_tagesplan_fenster_ohne_ueberschneidung EXCLUDE USING gist ("
        "room_id WITH =, int4range(von_minute, bis_minute) WITH &&)"
    )


def downgrade() -> None:
    op.drop_index("ix_tagesplan_fenster_room_von", table_name="tagesplan_fenster")
    op.drop_index("ix_tagesplan_fenster_room_id", table_name="tagesplan_fenster")
    op.drop_table("tagesplan_fenster")
