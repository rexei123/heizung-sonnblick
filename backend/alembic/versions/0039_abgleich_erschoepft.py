"""device: seit wann nimmt dieses Geraet den Engine-Sollwert nicht an.

Sprint 25 (T3). Ein **Merker fuer eine Episode**: gesetzt, wenn der
Engine-Abgleich nach drei erfolglosen Nachsendungen aufgibt; geloescht
erst, wenn das Geraet einen gesendeten Sollwert **bestaetigt** — also
einen Uplink mit genau dem Wert meldet, der ihm zuletzt geschickt wurde.

**Warum eine Spalte und nicht der Redis-Zaehler, den es schon gibt.**
Der Zaehler in ``services/engine_abgleich`` ist eine **Drosselung**: er
traegt eine TTL von vier Stunden, damit sich drei Versuche ueber
eineinhalb Stunden verteilen und ein spaeterer Fall wieder drei Versuche
hat. Als Zustandsspeicher ist er damit untauglich — die erschoepfte Lage
verfaellt nach vier Stunden von selbst, ohne dass sich am Geraet etwas
geaendert hat.

Dazu kam der eigentliche Anlass: **Geraet 7, 01.11. bis 04.11.2026.**
Der Abgleich hatte aufgegeben. Dann verschob die Engine ihren Wunsch —
Nachtabsenkung, Belegungswechsel — und traf damit zufaellig den Wert, den
das Geraet ohnehin hielt. Die Aufraeum-Bedingung lautete bis heute
``ist_wert == zone_target_setpoint_c``, also „Geraet stimmt mit dem
**aktuellen Wunsch** ueberein". Sie griff, der Zaehler fiel, und der
Befund war weg — **ohne dass das Geraet je einen Befehl angenommen
hatte.** Beim naechsten Wunschwechsel begann das Spiel von vorn, mit
drei frischen Versuchen und drei weiteren Motorbewegungen.

Ein Befund, der verschwindet, weil der Beobachter seine Frage aendert,
ist kein Befund (Paragraph 5.79). Deshalb traegt der Merker jetzt die
Datenbank, und die Bedingung fuer sein Ende ist eine Aussage **ueber das
Geraet** statt ueber den Wunsch.

**Warum kein zweites Feld fuer Ist- und Soll-Wert.** Beide stehen
bereits: der gemeldete Wert in ``sensor_reading.setpoint``, der gesendete
in ``control_command.target_setpoint``. Sie hier zu spiegeln waere eine
zweite Wahrheit, die beim ersten Nachjustieren auseinanderlaeuft
(Paragraph 5.53). Die Spalte traegt genau das, was sonst nirgends steht:
**seit wann** die Lage besteht.

``NULL`` heisst „nimmt Befehle an, soweit bekannt" — nicht „geprueft und
in Ordnung". Ein Geraet, das nie einen Downlink bekommen hat, steht
ebenfalls auf ``NULL``.

Migration additiv: ja — eine nullable Spalte auf ``device``, kein
Backfill, keine Beschraenkung auf Bestandszeilen. ``device`` ist eine
normale Tabelle mit rund 110 Zeilen, kein Hypertable; eine Sperrfrist wie
in ``0038`` ist hier nicht noetig.

Revision ID: 0039_abgleich_erschoepft
Revises: 0038_fenstererkennung_stand
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039_abgleich_erschoepft"
down_revision: str | None = "0038_fenstererkennung_stand"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("abgleich_erschoepft_seit", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device", "abgleich_erschoepft_seit")
