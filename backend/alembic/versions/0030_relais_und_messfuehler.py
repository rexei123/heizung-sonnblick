"""Relais-Aktoren und die Fuehler-Rolle (Sprint 24, Infrarot-Pilot).

**Migration additiv: ja.** Vier neue Spalten auf ``device``, alle mit
Server-Vorgabe, plus eine neue Tabelle. Keine Spalte wird entfernt,
umbenannt oder verengt, kein Typ geaendert, keine Bestandszeile
angefasst. Ein Rueckfall per ``PIN_SHA`` (RUNBOOK §10u) bleibt damit
zulaessig (Goldene Regel 10, AE-77).

**``device.kind`` braucht nichts.** Der neue Wert ``relay`` ist ohne
Migration einfuegbar: die Spalte ist ``VARCHAR(20)`` **ohne**
CHECK-Beschraenkung. Am laufenden Schema geprueft (AE-78 §1), nicht aus
der Analogie zu ``manual_override.source`` geschlossen — dort liegt eine
CHECK, und genau deshalb hat ``frontend_24h`` am 20.10. eine Migration
gekostet (0029). Die beiden Spalten sehen im Modell gleich aus und
verhalten sich verschieden; wer das verwechselt, baut eine Migration zu
viel oder eine zu wenig.

**Warum die vier Spalten auf ``device`` und nicht in eine eigene
Tabelle.** Sie beschreiben alle genau ein Geraet, es gibt sie je Geraet
genau einmal, und drei von vier werden auf dem heissen Pfad gelesen
(Geraeteauswahl im Dispatch, Waechter je Tick). Eine Nebentabelle waere
ein Join auf jedem Tick fuer vier Werte.

``relay_reading`` wird zur TimescaleDB-Hypertable konvertiert, wie
``sensor_reading`` und ``event_log``. Chunk-Intervall 7 Tage, dieselbe
Wahl wie ``event_log`` (0003b) — ein Relais meldet nach Keepalive-Periode
und bei jedem Schaltvorgang, also in derselben Groessenordnung wie ein
Thermostat.

**Rueckweg:** ``downgrade`` entfernt Tabelle und Spalten. Die
Messwerte der Pilot-Geraete sind damit weg; das ist bei einem
Rueckfall gewollt, denn ohne die Spalten gibt es auch keine Steuerung,
die sie erzeugt. Zeilen in ``device`` bleiben unberuehrt — ein Relais
bleibt als Geraet bestehen und verliert nur seine Pilot-Eigenschaften.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0030_relais_und_messfuehler"
down_revision = "0029_override_frontend_24h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("commissioned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "device",
        sa.Column(
            "measure_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "device",
        sa.Column(
            "watchdog_strategy",
            sa.String(length=20),
            nullable=False,
            server_default="expire_and_resend",
        ),
    )
    op.add_column(
        "device",
        sa.Column(
            "switch_cycles",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Die Strategie ist eine geschlossene Liste, und sie wird vom
    # Waechter als Verzweigung gelesen. Ein Tippfehler waere dort ein
    # stiller Rueckfall auf den else-Zweig — deshalb eine CHECK, anders
    # als bei ``device.kind``. Beide Werte als Literale, damit die
    # Beschraenkung unabhaengig vom Python-Enum lesbar bleibt (dieselbe
    # Form wie ``ck_manual_override_source``).
    op.create_check_constraint(
        "ck_device_watchdog_strategy",
        "device",
        "watchdog_strategy IN ('expire_and_resend', 'refresh')",
    )

    op.create_table(
        "relay_reading",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("fcnt", sa.Integer(), nullable=True),
        sa.Column("relay_on", sa.Boolean(), nullable=True),
        sa.Column("timer_remaining_s", sa.Integer(), nullable=True),
        sa.Column("change_reason", sa.String(length=40), nullable=True),
        sa.Column("power_w", sa.Integer(), nullable=True),
        # BigInteger: der Zaehler geht bis 4 294 967 295 Wh, ``int4``
        # endet bei 2 147 483 647 — also bei der Haelfte des
        # Zaehlerbereichs.
        sa.Column("energy_wh", sa.BigInteger(), nullable=True),
        sa.Column("ac_voltage_v", sa.Integer(), nullable=True),
        sa.Column("ac_current_ma", sa.Integer(), nullable=True),
        sa.Column("internal_temperature_raw", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["device.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("time", "device_id"),
    )
    op.create_index(
        "ix_relay_reading_device_time",
        "relay_reading",
        ["device_id", "time"],
    )
    op.execute(
        "SELECT create_hypertable("
        "'relay_reading', 'time',"
        " chunk_time_interval => INTERVAL '7 days',"
        " if_not_exists => TRUE"
        ")"
    )


def downgrade() -> None:
    op.drop_index("ix_relay_reading_device_time", table_name="relay_reading")
    op.drop_table("relay_reading")
    op.drop_constraint("ck_device_watchdog_strategy", "device", type_="check")
    op.drop_column("device", "switch_cycles")
    op.drop_column("device", "watchdog_strategy")
    op.drop_column("device", "measure_only")
    op.drop_column("device", "commissioned_at")
