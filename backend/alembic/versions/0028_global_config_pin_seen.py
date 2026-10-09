"""``global_config.pin_sha_seen`` / ``pin_sha_seen_at`` — seit wann der Server gepinnt ist.

**Sprint 20g, H-6 T10.** Ein gesetzter ``PIN_SHA`` haelt den Server auf einem
Commit und **zieht keine Merges mehr** (AE-77 §5). Das ist der Zweck — und
die Gefahr, wenn man es vergisst. Die Erinnerung dazu (Mail nach sieben
Tagen, danach woechentlich) braucht genau eine Tatsache, die sich nirgends
ablesen laesst: **seit wann** steht der Pin.

**Warum nicht in Redis.** ``alert_throttle`` haelt seine Bremsen dort, und
das passt bei sechs Stunden. Der Redis-Dienst hat in
``docker-compose.prod.yml`` **kein Volume** — jeder Neustart leert ihn. Bei
einer Sieben-Tage-Uhr waere das der stille Ausfall aus §5.76: der Zaehler
springt auf Null zurueck, die Erinnerung kommt nie, und niemand bemerkt es,
weil ein ausbleibender Hinweis nichts hinterlaesst. Fuer die kurzen TTLs ist
die Fluechtigkeit harmlos (eine Mail zu viel), fuer diese Uhr nicht.

**Warum nicht im Skript.** ``deploy-pull.sh`` laeuft alle fuenf Minuten und
koennte jeden Zustand nur in eine Datei legen, die der naechste
``git reset --hard`` entfernt.

**Laufzeit-Felder, keine Konfiguration.** Wie ``last_mail_attempt_at`` &
Co. (Migration 0021): geschrieben ausschliesslich von
``services/pin_reminder``, nicht Teil von ``GlobalConfigUpdate``. Ein PATCH
darauf waere das Faelschen eines Messwerts.

``pin_sha_seen_at`` ist bewusst **nicht** an den SHA gekoppelt: wandert der
Pin von einem Commit zum naechsten, laeuft die Uhr weiter. Gemessen wird
"der Server folgt dem Branch nicht", und dieser Zustand haelt ueber einen
Pin-Wechsel hinweg an. Sonst koennte man die Erinnerung beliebig
hinausschieben, indem man neu pinnt.

``VARCHAR(40)``: ein voller SHA-1 hat 40 Zeichen. Gespeichert wird, was in
der ``.env`` steht (meist die siebenstellige Kurzform) — die Laenge deckt
beide Formen.

Revision-ID unter 32 Zeichen (``alembic_version.version_num`` ist
``VARCHAR(32)``): ``0028_global_config_pin_seen`` = 27 Zeichen (CLAUDE.md
§5.80, dritter Fall).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_global_config_pin_seen"
down_revision: str | None = "0027_device_mounted_conf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("global_config", sa.Column("pin_sha_seen", sa.String(40), nullable=True))
    op.add_column(
        "global_config",
        sa.Column("pin_sha_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("global_config", "pin_sha_seen_at")
    op.drop_column("global_config", "pin_sha_seen")
