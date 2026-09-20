"""Laufzeit-Felder zum Mailversand in global_config (Sprint 18, T4).

Drei Spalten, die **keine Konfiguration** sind. Das ist der wichtige
Unterschied zu allem anderen in dieser Tabelle: ``hotel_name``,
``alert_email``, ``alert_battery_warn_percent`` sind Einstellungen — der
Hotelier setzt sie, das System liest sie. Diese drei laufen in die
Gegenrichtung. Das System schreibt sie, der Hotelier liest sie.

- ``last_mail_attempt_at`` — wann zuletzt ein Versand versucht wurde,
  unabhaengig vom Ausgang.
- ``last_mail_ok_at`` — wann zuletzt einer geklappt hat. Wird nie
  zurueckgesetzt: die Frage "hat es ueberhaupt jemals funktioniert" ist
  am Tag der Inbetriebnahme die einzige, die zaehlt.
- ``last_mail_error`` — Grund des letzten Fehlversuchs, ``NULL`` nach
  einem Erfolg. Enthaelt nie das SMTP-Passwort (``mailer._redact``).

Warum sie trotzdem hier liegen und nicht in einer eigenen Tabelle: es
gibt genau einen Wert je Feld, nie eine Historie. Eine zweite
Singleton-Tabelle waere dieselbe Zeile mit mehr Zeremonie (S6). Wer
spaeter eine Versand-Historie will, legt sie als eigene Tabelle an — das
hier bleibt der schnelle Blick "geht es gerade oder nicht".

Anlass: bis Sprint 18 gab es keinen Mailversand. Ab jetzt gibt es einen,
und er scheitert **still**, solange die SMTP-Werte in der ``.env`` leer
sind. Ein Alarmweg, dessen Ausfall man nur im Container-Log sieht, ist
kein Alarmweg (CLAUDE.md §5.76).

Rein additiv, alle drei nullable, kein Backfill.

Revision ID: 0021_global_config_mail_status
Revises: 0020_device_hardware_number
Create Date: 2026-09-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021_global_config_mail_status"
down_revision: str | None = "0020_device_hardware_number"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "global_config",
        sa.Column("last_mail_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "global_config",
        sa.Column("last_mail_ok_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "global_config",
        sa.Column("last_mail_error", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("global_config", "last_mail_error")
    op.drop_column("global_config", "last_mail_ok_at")
    op.drop_column("global_config", "last_mail_attempt_at")
