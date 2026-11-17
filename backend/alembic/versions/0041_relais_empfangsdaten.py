"""relay_reading: RSSI und SNR, die zwei Zahlen, die dem Relais fehlten.

**Der Anlass, 16.11.2026.** Relais 108 wurde vom
Standard-ADR-Algorithmus auf **DR5** hochgezogen — vier ``LinkADRReq
acknowledged`` am 15. und 16.11., bei ``installation_margin = 20`` und
voller Sendeleistung. Die Frage „warum klettert er trotz der strengeren
Reserve" war **nicht beantwortbar**, und zwar nicht aus Mangel an Zeit:

* ``sensor_reading`` traegt ``rssi_dbm`` und ``snr_db`` — aber ein Relais
  schreibt nicht dorthin.
* ``relay_reading`` hatte die Spalten nicht.
* Das ChirpStack-Protokoll fuehrt die Werte fuer dieses Geraet nicht.

Damit stand die einzige Zahl, die den Unterschied zwischen „der Link ist
zu schwach" und „die Pakete kollidieren" macht, nirgends. Der
Standard-Algorithmus rechnet auf dem SNR der **angekommenen** Meldungen;
ob er bei 108 mit +2 dB oder +14 dB gerechnet hat, entscheidet, ob DR1
ueberhaupt die richtige Abhilfe ist.

**Dieselbe Luecke war schon beschrieben.** ``scripts/funkqualitaet.py``
nennt sie im Docstring und sagt, das Nachziehen sei „eine additive
Migration und ein eigener PR — sie wuerde erst ab dem Einbau Daten
sammeln und kommt fuer diese Messung zu spaet". Das war am 03.11. richtig
und ist der Grund, warum es jetzt gebaut wird: fuer die **naechste**
Messung ist es nicht zu spaet.

**Gleiche Typen wie in ``sensor_reading``, mit Absicht.** ``SmallInteger``
fuer RSSI (ganze dBm, immer negativ), ``Numeric(4, 1)`` fuer SNR (ein
Dezimal, kann negativ sein). Eine andere Wahl hier waere ein Feld mit
zwei Bedeutungen je Tabelle (Paragraph 5.51), und die Auswertung muesste
beide Formen kennen.

``NULL`` heisst **nicht** „kein Empfang", sondern „diese Zeile sagt
nichts darueber". Das gilt fuer jede Zeile vor dieser Migration, und es
gilt dauerhaft fuer Uplinks, deren Ereignis keinen ``rxInfo``-Block
traegt. Eine 0 waere dort eine Behauptung ueber einen Funk, den wir nicht
gemessen haben — genau der Satz, der im Docstring von ``funkqualitaet``
schon stand.

**Die 0-dB-Luecke von protojson gilt hier genauso**, und sie wird
deshalb nicht zweimal gebaut: ``services/mqtt_subscriber._snr_db``
entscheidet fuer **beide** Pfade, dass „Block da, Feld weg" genau 0
bedeutet. Der Relais-Pfad ruft denselben Helfer (Paragraph 5.53, eine
Wahrheit).

Migration additiv: ja — zwei nullable Spalten, kein Backfill, keine
Beschraenkung auf Bestandszeilen. ``relay_reading`` ist ein Hypertable;
``ADD COLUMN`` ohne Vorgabewert wandert durch die Chunks, ohne Zeilen
anzufassen.

Revision ID: 0041_relais_empfangsdaten
Revises: 0040_relais_ein_gesendet
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041_relais_empfangsdaten"
down_revision: str | None = "0040_relais_ein_gesendet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("relay_reading", sa.Column("rssi_dbm", sa.SmallInteger(), nullable=True))
    op.add_column("relay_reading", sa.Column("snr_db", sa.Numeric(4, 1), nullable=True))


def downgrade() -> None:
    op.drop_column("relay_reading", "snr_db")
    op.drop_column("relay_reading", "rssi_dbm")
