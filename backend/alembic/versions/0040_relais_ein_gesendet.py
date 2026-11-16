"""device: wann zuletzt ein ``0x57`` (EIN mit Timer) an dieses Relais ging.

**Die Spalte, ohne die ``REFRESH`` einen Downlink je Minute schickt.**

Die Waechter-Strategie ``REFRESH`` setzt den Relais-Timer nach, solange
das Relais EIN ist und EIN gewuenscht bleibt. Sie braucht dafuer **einen
Zeitpunkt**: wann ging der letzte EIN-Befehl hinaus? Ohne ihn greift der
Zweig ``auffrischung_ohne_vorbefehl`` und setzt **sofort** nach.

Bis heute reichte der Orchestrator dafuer ``device.pending_since``
durch — den Zeitpunkt des **unbestaetigten** Befehls. Der wird geloescht,
sobald das Geraet den Zustand meldet (``_loesche_offen`` beim Grund
``bestaetigt``). Danach ist er ``None``, und der Waechter haette bei
jedem Durchlauf „kein Vorbefehl" gesehen. Der Orchestrator laeuft **jede
Minute**: das waeren 60 Downlinks je Stunde und Relais, also rund 79
Sekunden Sendezeit — gegen 12 Downlinks und 16 Sekunden, wenn der
Abstand von fuenf Minuten eingehalten wird.

**Gefunden wurde das nicht von den Tests.** ``REFRESH`` war nur als reine
Funktion geprueft, und dort wird ``letzter_ein_befehl`` als Argument
uebergeben — die Verdrahtung im Orchestrator hat kein Test je gesehen
(Paragraph 5.55). Nachgewiesen am 15.11.2026 mit einem Lauf gegen die
Datenbank, bevor diese Spalte existierte: drei Durchlaeufe des
Orchestrators, drei ``0x57``.

**Warum eine eigene Spalte und nicht ``pending_since`` behalten.** Die
beiden bedeuten Verschiedenes. ``pending_since`` traegt „ein Befehl
wartet auf Bestaetigung" und muss verschwinden, wenn die Bestaetigung da
ist — daran haengen die Bestaetigungsfrist, der Backoff und der Alarm.
Diese Spalte traegt „wann wurde zuletzt eingeschaltet" und muss
**bleiben**. Sie zusammenzulegen hiesse, einem Feld zwei Bedeutungen zu
geben (Paragraph 5.51), und die eine wuerde die andere beim ersten
Bestaetigungs-Uplink ueberschreiben.

``NULL`` heisst „kein EIN-Befehl bekannt". Das gilt fuer jedes Geraet vor
dieser Migration und fuer jedes Thermostat auf Dauer. Der Waechter setzt
dann einmal nach und hat danach einen Zeitpunkt — der Zustand ist also
selbstheilend und braucht keinen Backfill.

Migration additiv: ja — eine nullable Spalte auf ``device``, kein
Backfill, keine Beschraenkung auf Bestandszeilen. ``device`` ist eine
normale Tabelle mit rund 110 Zeilen, kein Hypertable.

Revision ID: 0040_relais_ein_gesendet
Revises: 0039_abgleich_erschoepft
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040_relais_ein_gesendet"
down_revision: str | None = "0039_abgleich_erschoepft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("relais_ein_gesendet_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device", "relais_ein_gesendet_at")
