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
# Optionaler Off-Site-Push (Sprint 15g A3): bei gesetztem
# BACKUP_OFFSITE_TARGET werden die lokalen Dumps nach erfolgreichem Lauf
# per rsync-over-SSH auf eine Hetzner Storage Box gespiegelt. Ziel + Key +
# (optional) Port kommen aus der .env (BACKUP_OFFSITE_TARGET,
# BACKUP_OFFSITE_SSH_KEY, BACKUP_OFFSITE_SSH_PORT - Default 23). Kein
# hardcodierter Host, kein Secret im Skript. Fail-soft: Off-Site-Fehler
# markieren den Lauf NICHT als Failure (lokal ist Primaersicherung),
# werden aber mit dem Token OFFSITE_PUSH_FAILED geloggt. Kein rsync
# --delete (Off-Site-Retention bleibt Storage-Box-seitig).
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
#   2026-06-09  Sprint 15g A3: optionaler Off-Site-Push (rsync-over-SSH auf
#               Hetzner Storage Box) ergaenzt. Fail-soft, Keys aus .env.

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

# Off-Site-Push-Konfiguration (alle optional; leeres TARGET => kein Push).
OFFSITE_TARGET=$(read_env_key BACKUP_OFFSITE_TARGET)
OFFSITE_KEY=$(read_env_key BACKUP_OFFSITE_SSH_KEY)
OFFSITE_PORT=$(read_env_key BACKUP_OFFSITE_SSH_PORT); OFFSITE_PORT=${OFFSITE_PORT:-23}
OFFSITE_STATUS=skipped

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

# Off-Site-Push der lokalen Dumps auf die Storage Box (rsync-over-SSH).
# Fail-soft: setzt OFFSITE_STATUS, gibt NIE einen Fehler an den
# Haupt-Exit weiter. Leeres TARGET => sauber uebersprungen.
push_offsite() {
    if [ -z "$OFFSITE_TARGET" ]; then
        log "Off-Site: BACKUP_OFFSITE_TARGET leer - uebersprungen (nur lokales Backup)."
        OFFSITE_STATUS=skipped
        return
    fi
    if [ -z "$OFFSITE_KEY" ] || [ ! -f "$OFFSITE_KEY" ]; then
        log "OFFSITE_PUSH_FAILED: BACKUP_OFFSITE_SSH_KEY fehlt/ungueltig ('${OFFSITE_KEY}') - Off-Site uebersprungen."
        OFFSITE_STATUS=failed
        return
    fi
    if ! command -v rsync >/dev/null 2>&1; then
        log "OFFSITE_PUSH_FAILED: rsync nicht installiert - Off-Site uebersprungen."
        OFFSITE_STATUS=failed
        return
    fi
    log "Off-Site: rsync ${BACKUP_DIR}/ -> ${OFFSITE_TARGET} (ssh port ${OFFSITE_PORT}) ..."
    # Kein --delete: Off-Site akkumuliert, Retention bleibt Storage-Box-seitig.
    # BatchMode=yes => kein interaktiver Prompt, scheitert statt zu haengen.
    if rsync -a \
            -e "ssh -p ${OFFSITE_PORT} -i ${OFFSITE_KEY} -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
            "$BACKUP_DIR"/ "$OFFSITE_TARGET" >>"$LOG" 2>&1; then
        log "Off-Site: Push erfolgreich."
        OFFSITE_STATUS=ok
    else
        rc=$?
        log "OFFSITE_PUSH_FAILED: rsync-Exit ${rc} - lokales Backup bleibt Primaersicherung, Off-Site bitte pruefen."
        OFFSITE_STATUS=failed
    fi
}

log "Backup-Lauf start (Ziel ${BACKUP_DIR}, behalte ${KEEP} je DB)."

dump_db db                  "$HEIZUNG_USER" "$HEIZUNG_DB" heizung
dump_db chirpstack-postgres chirpstack      chirpstack    chirpstack

rotate heizung
rotate chirpstack

if [ "$FAILED" -ne 0 ]; then
    log "Backup-Lauf mit FEHLERN beendet (lokaler Dump fehlgeschlagen, siehe oben)."
    exit 1
fi

# Lokales Backup ist durch. Off-Site ist additiv und fail-soft: ein
# Push-Fehler markiert den Lauf NICHT als Failure (exit 0), wird aber
# laut geloggt (Token OFFSITE_PUSH_FAILED).
push_offsite

case "$OFFSITE_STATUS" in
    ok)      log "Backup-Lauf erfolgreich beendet (lokal + Off-Site)." ;;
    skipped) log "Backup-Lauf erfolgreich beendet (lokal; Off-Site nicht konfiguriert)." ;;
    failed)  log "Backup-Lauf beendet: lokal OK, OFF-SITE-PUSH FEHLGESCHLAGEN (Token OFFSITE_PUSH_FAILED im Log). Primaersicherung lokal vorhanden." ;;
esac

exit 0
