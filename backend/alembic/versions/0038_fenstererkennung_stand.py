"""sensor_reading: der Stand der Fenstererkennung im Geraet (0x46).

Die Antwort auf ``0x46`` nennt, **ob die Fenstererkennung im Geraet
eingeschaltet ist** und mit welchen Parametern. Bisher landete sie
ausschliesslich in einer Protokollzeile
(``event_type=MAINTENANCE_VICKI_CONFIG_REPORT``, bewusste S6-Entscheidung
aus Sprint 9.11x.b). Diese drei Spalten nehmen sie auf.

**Warum die Protokollzeile nicht reicht — der Anlass, 05.11.2026.** Auf
die Frage „ist die Erkennung ueberhaupt aktiv?" war im ganzen System
keine Antwort zu finden. Nicht im ``control_command`` (dort stehen nur
Sollwerte), nicht im ``business_audit`` (keine passende Aktion), und
nicht in ``sensor_reading`` (``open_window_status_reply`` steht in
``REPLY_REPORT_TYPES``, es entsteht also keine Zeile). Das Protokoll des
api-Containers reichte zum Zeitpunkt der Frage **18 Stunden** zurueck.

Damit war eine Zusicherung ueber die Anlage nur noch durch erneutes
Funken pruefbar — und das ist genau die Sorte Nichtwissen, die §5.68
verbietet: eine operative Aussage ohne Befund. Ein Protokolleintrag, der
die Antwort traegt und dann verfaellt, ist fuer eine wiederholbare Frage
kein Speicher.

**Warum in ``sensor_reading`` und nicht auf ``device``.** Praezedenzfall
``0035_geraetegrenzen_messwert`` (0x15), und aus demselben Grund: es ist
eine **Meldung des Geraets mit einem Zeitpunkt**, kein Stammdatum. Der
Leser nimmt die juengste Zeile, **die die Felder fuehrt**, und deren
``time`` ist der Bestaetigungszeitpunkt. Ein Feld auf ``device`` haette
den Zeitpunkt als zusaetzliche Spalte gebraucht und beim naechsten
Downlink eine zweite Wahrheit erzeugt.

**``ow_detection_enabled`` ist nicht ``open_window``.** Die beiden
Spalten stehen nebeneinander und beantworten verschiedene Fragen:

* ``open_window``        — „ist **jetzt** ein Fenster offen?" (Zustand)
* ``ow_detection_enabled`` — „ist die Erkennung im Geraet **eingeschaltet**?"
                             (Konfiguration)

Ein Geraet mit ``ow_detection_enabled = false`` meldet ``open_window =
false`` **immer**, und zwar ohne je gemessen zu haben. Wer die beiden
verwechselt, liest aus 604.694 Zeilen ``open_window = false`` den Befund
„es wurde nie gelueftet" statt „die Erkennung war aus". Genau diese
Verwechslung war am 05.11.2026 offen.

``NULL`` heisst „diese Zeile fuehrt das Feld nicht", nicht „aus". Ein
Keepalive ohne ``0x46``-Antwort sagt ueber den Stand nichts und darf eine
aeltere Antwort nicht ueberschreiben — dieselbe Drei-Zustands-Regel wie
bei ``open_window``, ``attached_backplate``, ``child_lock`` und
``temp_range_min``.

Migration additiv: ja — drei nullable Spalten, kein Backfill, keine
Beschraenkung auf Bestandszeilen. ``sensor_reading`` ist eine
TimescaleDB-Hypertable; ``ADD COLUMN`` mit NULL ist dort eine
Metadaten-Operation und beruehrt die Chunks nicht.

Revision ID: 0038_fenstererkennung_stand
Revises: 0037_boost_temperatur
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038_fenstererkennung_stand"
down_revision: str | None = "0037_boost_temperatur"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sensor_reading", sa.Column("ow_detection_enabled", sa.Boolean(), nullable=True))
    # Die Dauer ist ein Vielfaches von 5 Minuten und reicht bis 1275
    # (Byte * 5) — SmallInteger genuegt und ist dieselbe Wahl wie bei
    # ``temp_range_min``.
    op.add_column(
        "sensor_reading",
        sa.Column("ow_detection_duration_min", sa.SmallInteger(), nullable=True),
    )
    # Das Delta kommt als Byte/10, hat also genau eine Nachkommastelle
    # und liegt in [0.1, 6.4]. ``Numeric(3, 1)`` traegt das exakt; ein
    # Float waere hier der falsche Typ, weil die Zahl mit einer
    # Konfigurationsgrenze verglichen wird (§5.73: Decimal gegen
    # Float-Drift an der Schwelle).
    op.add_column(
        "sensor_reading",
        sa.Column("ow_detection_delta_c", sa.Numeric(precision=3, scale=1), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sensor_reading", "ow_detection_delta_c")
    op.drop_column("sensor_reading", "ow_detection_duration_min")
    op.drop_column("sensor_reading", "ow_detection_enabled")
