#!/bin/bash
# Pull-basierter Deploy.
#
# Zieht die aktuellen Images aus GHCR und tauscht Container, deren
# Image-Digest sich geändert hat. Idempotent — kann beliebig oft
# laufen (z. B. alle 5 Min per Cron).
#
# Annahmen:
#   - /opt/heizung-sonnblick/infra/deploy/.env existiert und setzt
#     STAGE, IMAGE_TAG, PUBLIC_HOSTNAME, POSTGRES_* etc.
#   - Server ist mit `docker login ghcr.io` gegen GHCR authentifiziert.
#
# Log: /var/log/heizung-deploy.log

set -euo pipefail

LOG=/var/log/heizung-deploy.log
COMPOSE_DIR=/opt/heizung-sonnblick/infra/deploy
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.prod.yml"

log() {
    echo "[$(date --iso-8601=seconds)] $*" | tee -a "$LOG"
}

cd "$COMPOSE_DIR"

log "Pulling images (api, web)…"
if ! docker compose -f "$COMPOSE_FILE" pull api web >>"$LOG" 2>&1; then
    log "Pull fehlgeschlagen (ggf. Login zu ghcr.io nötig)."
    exit 1
fi

# docker compose up -d ist idempotent — tauscht nur Container, deren
# Image-Digest sich geändert hat. Keine Race-Conditions, keine
# unnötigen Restarts.
log "Container-Stand aktualisieren…"
docker compose -f "$COMPOSE_FILE" up -d --no-deps api web >>"$LOG" 2>&1

log "Aktiv: $(docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}}={{.Status}}' | tr '\n' ' ')"
log "Fertig."
