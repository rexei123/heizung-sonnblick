"""Erwartungszeit der Belegungsliste in global_config (Belegungs-Import-Fix).

``occupancy_import_expected_by_local TIME NOT NULL DEFAULT '12:00'`` —
die Uhrzeit, bis zu der die taegliche Belegungsliste eingetroffen sein
muss. **Ortszeit** des Hotels (``global_config.timezone``), wie alle
Hotelier-Zeitfelder in dieser Tabelle (CLAUDE.md §5.65).

Warum das eine Einstellung wird und keine Konstante bleibt: der Wert
haengt am Versandzeitpunkt, und der steht in **fremder Software**
(Casablanca). Aendert ihn jemand dort, erfahren wir es nicht — dann muss
der Hotelier nachziehen koennen, ohne auf ein Deployment zu warten.

Vorgabe 12:00: Casablanca versendet um 10:38 Ortszeit (bestaetigt
26.09.2026), das sind gut 80 Minuten Puffer, und eine fehlende Liste
faellt noch am selben Vormittag auf.

Der Wert stand vorher in der Umgebung als
``OCCUPANCY_IMPORT_EXPECTED_BY_LOCAL=09:00``. Diese Variable entfaellt —
zwei Quellen fuer denselben Wert waeren ein Drift-Risiko (§5.53), und
eine Einstellung, die der Hotelier sehen soll, gehoert nicht in eine
Datei, die nur per SSH erreichbar ist.

``NOT NULL`` mit ``server_default``, damit die bestehende Singleton-Row
den Wert direkt bekommt. Der Default bleibt auf der Spalte stehen (anders
als bei 0017): es gibt genau eine Row, ein spaeteres INSERT gibt es nicht,
und der Wert ist eine echte fachliche Vorgabe — kein Migrations-Hilfsmittel.

Revision ID: 0022_occupancy_import_expected_by
Revises: 0021_global_config_mail_status
Create Date: 2026-09-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_occupancy_import_expected_by"
down_revision: str | None = "0021_global_config_mail_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column(
            "occupancy_import_expected_by_local",
            sa.Time(),
            nullable=False,
            server_default=sa.text("'12:00:00'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("global_config", "occupancy_import_expected_by_local")
