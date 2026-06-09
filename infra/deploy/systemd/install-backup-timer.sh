#!/bin/bash
# Installiert den DB-Backup-Timer auf einem Server (Sprint 15g, Block A).
# Einmal ausfuehren, nachdem /opt/heizung-sonnblick ausgecheckt ist.
# Analog zu install-timer.sh (Deploy-Pull).

set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SRC_DIR/heizung-backup.service" /etc/systemd/system/
cp "$SRC_DIR/heizung-backup.timer"   /etc/systemd/system/
chmod +x /opt/heizung-sonnblick/infra/deploy/backup.sh

# Backup-Ziel anlegen (root-only).
mkdir -p /var/backups/heizung
chmod 700 /var/backups/heizung

systemctl daemon-reload
systemctl enable --now heizung-backup.timer

echo "Backup-Timer installiert. Status:"
systemctl status heizung-backup.timer --no-pager | head -10
echo
echo "Naechste Laeufe:"
systemctl list-timers heizung-backup.timer --no-pager
