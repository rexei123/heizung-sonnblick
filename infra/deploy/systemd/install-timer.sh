#!/bin/bash
# Installiert den Deploy-Pull-Timer auf einem Server.
# Einmal ausführen, nachdem /opt/heizung-sonnblick ausgecheckt ist.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$SRC_DIR/heizung-deploy-pull.service" /etc/systemd/system/
cp "$SRC_DIR/heizung-deploy-pull.timer"   /etc/systemd/system/
chmod +x /opt/heizung-sonnblick/infra/deploy/deploy-pull.sh

systemctl daemon-reload
systemctl enable --now heizung-deploy-pull.timer

echo "Timer installiert. Status:"
systemctl status heizung-deploy-pull.timer --no-pager | head -10
echo
echo "Nächste Läufe:"
systemctl list-timers heizung-deploy-pull.timer --no-pager
