#!/bin/bash
# Taegliches DB-Backup fuer heizung-test / heizung-main (Sprint 15g, Block A).
#
# Macht je einen logischen pg_dump der beiden produktiven Datenbanken aus
# den laufenden Containern:
#   - Heizung-DB    (Service `db`, TimescaleDB pg16, User/DB `heizung`)
#   - ChirpStack-DB (Service `chirpstack-postgres`, User/DB `chirpstack`)
#
# Format: custom (`pg_dump -Fc`), komprimiert, restore via `pg_restore`.
# TimescaleDB-Hypertables (`sensor_reading` etc.) kommen mit dem logischen
# Dump vollstaendig mit. Decimal-Spalten ebenso (Custom-Format ist
# typ-erhaltend). Wichtig beim RESTORE einer TimescaleDB: erst
# `SELECT timescaledb_pre_restore();`, dann `pg_restore`, dann
# `SELECT timescaledb_post_restore();` (siehe RUNBOOK, Restore-Block).
#
# Ziel: /var/backups/heizung/  (root-only, chmod 700).
# Rotation: die 7 juengsten Dumps je DB bleiben, aeltere werden geloescht.
#
# Lokale Container-Verbindung nutzt Trust-Auth (wie rotate-secrets.sh),
# daher kein Passwort noetig. Server-.env wird nur fuer User/DB-Namen
# gelesen (Defaults heizung/heizung), nicht fuer Secrets.
#
# Log: /var/log/heizung-backup.log
#
# Aufruf: einmal taeglich via heizung-backup.timer (03:30). Manuell:
#   /opt/heizung-sonnblick/infra/deploy/backup.sh
#
# History:
#   2026-06-09  Sprint 15g Block A: Erstanlage. Voraussetzung fuer die
#               Prod-Domain-Promote (vor B-Block scharfgestellt).

set -euo pipefail

LOG=/var/log/heizung-backup.log
REPO_DIR=/opt/heizung-sonnblick
COMPOSE_DIR="$REPO_DIR/infra/deploy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.prod.yml"
ENV_FILE="$COMPOSE_DIR/.env"
BACKUP_DIR=/var/backups/heizung
KEEP=7

log() {
    echo "[$(date --iso-8601=seconds)] $*" | tee -a "$LOG"
}

# .env nur fuer Heizung-DB-Namen lesen (keine Secrets). ChirpStack-DB-Name
# ist im Compose-File hartcodiert (chirpstack/chirpstack), daher fix.
read_env_key() {
    grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

if [ ! -f "$COMPOSE_FILE" ]; then
    log "FEHLER: $COMPOSE_FILE fehlt."
    exit 1
fi

HEIZUNG_USER=$(read_env_key POSTGRES_USER); HEIZUNG_USER=${HEIZUNG_USER:-heizung}
HEIZUNG_DB=$(read_env_key POSTGRES_DB);     HEIZUNG_DB=${HEIZUNG_DB:-heizung}

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Aus dem Compose-Dir laufen, damit `docker compose` die .env automatisch
# liest (vermeidet "variable not set"-Warnungen bei exec).
cd "$COMPOSE_DIR"

TS=$(date -u +%Y%m%dT%H%M%SZ)
FAILED=0

# Einen Service-DB-Dump erzeugen, Mindestgroesse pruefen, sonst verwerfen.
dump_db() {
    local svc=$1 user=$2 db=$3 prefix=$4
    local out="$BACKUP_DIR/${prefix}-${TS}.dump"
    log "pg_dump ${db} (service ${svc}) -> ${out}"
    if ! docker compose -f "$COMPOSE_FILE" exec -T "$svc" \
            pg_dump -U "$user" -Fc "$db" > "$out" 2>>"$LOG"; then
        log "FEHLER: pg_dump ${db} fehlgeschlagen."
        rm -f "$out"
        FAILED=1
        return
    fi
    # Custom-Format-Dump hat immer einen Header; abgebrochene/leere Dumps
    # sind winzig. Schwelle 1000 Bytes faengt das ab.
    local sz
    sz=$(stat -c%s "$out")
    if [ "$sz" -lt 1000 ]; then
        log "FEHLER: Dump ${out} nur ${sz} Bytes - verdaechtig klein, verworfen."
        rm -f "$out"
        FAILED=1
        return
    fi
    log "OK: ${out} (${sz} Bytes)"
}

# Rotation: nur die KEEP juengsten Dumps eines Prefix behalten.
rotate() {
    local prefix=$1
    ls -1t "$BACKUP_DIR/${prefix}-"*.dump 2>/dev/null \
        | tail -n +$((KEEP + 1)) \
        | while read -r old; do
            log "Rotation: loesche ${old}"
            rm -f "$old"
        done
}

log "Backup-Lauf start (Ziel ${BACKUP_DIR}, behalte ${KEEP} je DB)."

dump_db db                  "$HEIZUNG_USER" "$HEIZUNG_DB" heizung
dump_db chirpstack-postgres chirpstack      chirpstack    chirpstack

rotate heizung
rotate chirpstack

if [ "$FAILED" -ne 0 ]; then
    log "Backup-Lauf mit FEHLERN beendet (siehe oben)."
    exit 1
fi

log "Backup-Lauf erfolgreich beendet."
