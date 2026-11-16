"""device: die Sendeleistung des Geraets, in unserer Datenbank.

16.11.2026. ``tx_power_index`` ist die Leistungsstufe, die ADR dem Geraet
befohlen hat (0 = volle Leistung, in EU868 bis 7, je Stufe rund 2 dB
weniger). Bis hierher stand der Wert in **keiner** Datenbank von uns.

**Woher er bisher kam.** RUNBOOK §10av Schritt 6a liest ihn aus dem
jeweils letzten ``LinkADRReq acknowledged`` in ``docker logs
deploy-chirpstack-1``. Am 16.11.2026 gemessen, warum das die schlechtere
Quelle ist:

* **ADR protokolliert nur, wenn es etwas aendert.** Nach 21,8 Stunden
  Protokoll standen dort Acks von **55** Geraeten — die Geraetesitzung
  kennt **109**. Ein Geraet, dessen Leistung eingeschwungen ist, kommt
  tagelang nicht vor, obwohl sein letzter Wert weiter gilt.
* **Eine Neuerstellung des Containers legt das Protokoll leer an**, mit
  und ohne Grenze. Die Vorgeschichte ist dann weg.
* Das Protokoll waechst mit 79,3 MB/Tag, wovon diese Zeilen 0,19 %
  ausmachen (PR #422, ``infra/deploy/docker/README.md``).

**Warum nicht aus dem Uplink.** Geprueft am Protobuf-Schema von
ChirpStack 4.17: ``integration.UplinkEvent`` hat 16 Felder, keines davon
traegt die Sendeleistung des Geraets — und kann es nicht, weil das
Gateway sie nicht messen kann. Sie steht in
``internal.DeviceSession``, Feld 24, das ChirpStack binaer in
``device.device_session`` seiner eigenen Postgres-Instanz haelt. Gelesen
wird sie von ``tasks.leistungsstufen_tasks`` (stuendlich, nur SELECT),
dekodiert in ``services/chirpstack_session``.

**Zwei Spalten und nicht eine.** ``tx_power_index_at`` haelt fest, wann
der Wert **gelesen** wurde — nicht, wann er sich geaendert hat. Ohne
diese Zeit ist ein Wert aus einem stehengebliebenen Task nicht von einem
frischen zu unterscheiden (§0 S5: letzter bekannter guter Stand mit
Zeitstempel schlaegt jede Annahme). Die Oberflaeche und Schritt 6a
koennen damit sagen „Stand von 14:50" statt „so ist es".

``NULL`` heisst „noch nie gelesen", und zwar in beiden Spalten: kein
Backfill (§5.61), weil die Historie dafuer fehlt — das Protokoll kennt
nur die Haelfte der Geraete. Der erste Lauf des Tasks fuellt sie. Die
Stufe **0** ist dagegen ein echter Wert (volle Leistung); am 16.11.
betraf sie 16 der 109 Geraete, und genau diese 16 laesst Protobuf im
Sitzungs-Blob weg, weil 0 der Standardwert ist.

``SmallInteger``: der Wertebereich ist 0..15 (``LinkADRReq`` traegt die
Stufe in 4 Bit).

Migration additiv: ja — zwei nullable Spalten auf ``device``, kein
Backfill, keine Beschraenkung auf Bestandszeilen. ``device`` ist eine
normale Tabelle mit rund 110 Zeilen, kein Hypertable; eine Sperrfrist wie
in ``0038`` ist nicht noetig.

Revision ID: 0040_tx_power_index
Revises: 0039_abgleich_erschoepft
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040_tx_power_index"
down_revision: str | None = "0039_abgleich_erschoepft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("device", sa.Column("tx_power_index", sa.SmallInteger(), nullable=True))
    op.add_column(
        "device",
        sa.Column("tx_power_index_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("device", "tx_power_index_at")
    op.drop_column("device", "tx_power_index")
