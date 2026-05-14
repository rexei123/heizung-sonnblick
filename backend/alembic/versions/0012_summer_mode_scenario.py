"""Sommermodus auf scenario_assignment migrieren (Sprint 9.16, AE-49).

Atomare Daten-Migration:

1. ``scenario.code='summer_mode'`` als System-Szenario seeden
   (idempotent).
2. Falls ``global_config.summer_mode_active=true``: identische
   Aktivierung als ``scenario_assignment(scope='global', is_active=true)``
   anlegen.
3. ``global_config.summer_mode_active`` droppen.

Downgrade re-erzeugt die Boolean-Spalte und uebertraegt den
Aktivierungszustand zurueck.

Brief-Korrektur: Sprint-Brief verwendete Spaltennamen
``scope_ref_id``/``active``/``activated_at``; Tatsaechliche Spalten
im ``scenario_assignment``-Model (Sprint 8.6) heissen
``room_type_id``/``room_id``/``season_id`` (nullable FKs analog
``rule_config``) und ``is_active``. ScenarioScope-Enum-Werte sind
lowercase (``global``/``room_type``/``room``).

Revision ID: 0012_summer_mode_scenario
Revises: 0011_config_audit
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_summer_mode_scenario"
down_revision: str | None = "0011_config_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. scenario summer_mode seeden (idempotent ueber UNIQUE(code))
    op.execute(
        """
        INSERT INTO scenario (code, name, description, is_system,
                              default_active, parameter_schema,
                              default_parameters, created_at, updated_at)
        VALUES ('summer_mode',
                'Sommermodus',
                'Heizthermostate funktionslos — Klimaanlage übernimmt. '
                'Alle Räume auf Frostschutz.',
                true, false, NULL, NULL, now(), now())
        ON CONFLICT (code) DO NOTHING
        """
    )

    # 2. Datenuebertrag: aktiver Sommermodus in scenario_assignment
    # spiegeln. WHERE NOT EXISTS verhindert Duplikat im Re-Run-Fall —
    # ON CONFLICT auf den Composite-UNIQUE-Constraint
    # (scenario_id, scope, room_type_id, room_id, season_id) waere
    # wegen der NULL-FKs in Postgres nicht zuverlaessig.
    op.execute(
        """
        INSERT INTO scenario_assignment (scenario_id, scope, room_type_id,
                                         room_id, season_id, is_active,
                                         parameters, created_at, updated_at)
        SELECT s.id, 'global', NULL, NULL, NULL, true, NULL, now(), now()
        FROM scenario s, global_config g
        WHERE s.code = 'summer_mode'
          AND g.id = 1
          AND g.summer_mode_active = true
          AND NOT EXISTS (
              SELECT 1 FROM scenario_assignment sa
              WHERE sa.scenario_id = s.id
                AND sa.scope = 'global'
                AND sa.room_type_id IS NULL
                AND sa.room_id IS NULL
                AND sa.season_id IS NULL
          )
        """
    )

    # 3. Spalte droppen
    op.drop_column("global_config", "summer_mode_active")


def downgrade() -> None:
    # 1. Spalte zurueck (Default false; Werte muessen aus
    # scenario_assignment rekonstruiert werden, siehe Schritt 2).
    op.add_column(
        "global_config",
        sa.Column(
            "summer_mode_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2. Aktive Sommermodus-Zuweisung zurueckspielen
    op.execute(
        """
        UPDATE global_config
           SET summer_mode_active = true
         WHERE id = 1
           AND EXISTS (
               SELECT 1 FROM scenario_assignment sa
               JOIN scenario s ON s.id = sa.scenario_id
               WHERE s.code = 'summer_mode'
                 AND sa.scope = 'global'
                 AND sa.room_type_id IS NULL
                 AND sa.room_id IS NULL
                 AND sa.season_id IS NULL
                 AND sa.is_active = true
           )
        """
    )

    # 3. Migrations-erzeugte Assignment + Scenario entfernen.
    # ON DELETE CASCADE auf scenario_assignment.scenario_id wuerde
    # die assignments automatisch raeumen, aber wir loeschen explizit
    # fuer Klarheit.
    op.execute(
        """
        DELETE FROM scenario_assignment
         WHERE scenario_id IN (
             SELECT id FROM scenario WHERE code = 'summer_mode'
         )
        """
    )
    op.execute("DELETE FROM scenario WHERE code = 'summer_mode' AND is_system = true")

    # 4. server_default wieder entfernen, damit das Bestandsmodell
    # ohne Default sauber bleibt (Model hatte ``default=False`` nur
    # python-seitig).
    op.alter_column("global_config", "summer_mode_active", server_default=None)
