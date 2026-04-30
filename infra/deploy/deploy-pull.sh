#!/bin/bash
# Pull-basierter Deploy.
#
# Drei Phasen, idempotent:
#   1. Working-Tree von origin/<DEPLOY_BRANCH> syncen (Compose-Schema,
#      Mosquitto-Config, Caddyfiles, ChirpStack-TOMLs, Postgres-Init).
#      DEPLOY_BRANCH leitet sich aus STAGE in der .env ab:
#         STAGE=test  ->  develop
#         STAGE=main  ->  main
#   2. App-Images aus GHCR pullen (api, web), IMAGE_TAG SHA-gepinnt.
#   3. Container-Stand aktualisieren (alle Services, recreate nur
#      bei Config- oder Image-Drift).
#
# Annahmen:
#   - /opt/heizung-sonnblick ist ein git-Checkout mit Remote `origin`.
#   - Server hat KEINE lokalen Working-Tree-Aenderungen am tracked
#     Content. Untracked Files (z.B. infra/deploy/.env) sind ok.
#   - Server ist mit `docker login ghcr.io` gegen GHCR authentifiziert.
#
# Log: /var/log/heizung-deploy.log
#
# History:
#   2026-04-29  Sprint 6.6.2: git-Sync ergaenzt. Vorher pullte das
#               Skript nur die App-Images (api, web), liess Working-
#               Tree und Infra-Container (mosquitto, chirpstack, caddy)
#               unangetastet. Compose-/Caddyfile-Aenderungen kamen so
#               nie auf den Server.
#   2026-04-29  H-6: IMAGE_TAG SHA-Pinning fuer Audit-Trail + Rollback.
#   2026-04-30  ASCII-only Re-Save (PowerShell-Encoding-Fix).

set -euo pipefail

LOG=/var/log/heizung-deploy.log
REPO_DIR=/opt/heizung-sonnblick
COMPOSE_DIR="$REPO_DIR/infra/deploy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.prod.yml"
ENV_FILE="$COMPOSE_DIR/.env"

log() {
    echo "[$(date --iso-8601=seconds)] $*" | tee -a "$LOG"
}

cd "$REPO_DIR"

# Branch-Mapping aus STAGE der .env ableiten:
#   STAGE=test  ->  origin/develop  (Pre-Production)
#   STAGE=main  ->  origin/main     (Production)
# DEPLOY_BRANCH in der .env ueberschreibt das Mapping bei Bedarf.
#
# .env wird NICHT komplett gesourct (enthaelt URLs mit Sonderzeichen).
# Nur die zwei relevanten Keys werden via grep gelesen.
if [ ! -f "$ENV_FILE" ]; then
    log "FEHLER: $ENV_FILE fehlt."
    exit 1
fi

read_env_key() {
    grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

STAGE_VAL=$(read_env_key STAGE)
DEPLOY_BRANCH_VAL=$(read_env_key DEPLOY_BRANCH)

if [ -n "$DEPLOY_BRANCH_VAL" ]; then
    TARGET_BRANCH="$DEPLOY_BRANCH_VAL"
elif [ "$STAGE_VAL" = "main" ]; then
    TARGET_BRANCH="main"
elif [ "$STAGE_VAL" = "test" ]; then
    TARGET_BRANCH="develop"
else
    log "FEHLER: STAGE='$STAGE_VAL' nicht test|main; DEPLOY_BRANCH leer."
    exit 1
fi

# ---------------------------------------------------------------------
# Phase 1: Working-Tree syncen
# ---------------------------------------------------------------------

log "git fetch origin/$TARGET_BRANCH ..."
if ! git fetch --quiet origin "$TARGET_BRANCH"; then
    log "FEHLER: git fetch fehlgeschlagen."
    exit 1
fi

# Lokale Aenderungen am tracked Content blockieren das Skript, damit
# kein Hand-Hotfix unbemerkt weggeworfen wird. Untracked Files (.env
# steht in .gitignore) sind ok.
if ! git diff --quiet HEAD; then
    log "FEHLER: Lokale Aenderungen am tracked Content vorhanden."
    git status --short | tee -a "$LOG"
    log "Bitte manuell committen oder verwerfen, dann erneut deployen."
    exit 1
fi

OLD_SHA=$(git rev-parse HEAD)
NEW_SHA=$(git rev-parse "origin/$TARGET_BRANCH")

if [ "$OLD_SHA" != "$NEW_SHA" ]; then
    OLD_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    log "Sync $OLD_BRANCH@$OLD_SHA  ->  $TARGET_BRANCH@$NEW_SHA ..."
    git checkout --quiet "$TARGET_BRANCH"
    git reset --hard --quiet "origin/$TARGET_BRANCH"
else
    log "Working-Tree bereits auf origin/$TARGET_BRANCH ($NEW_SHA)."
fi

# ---------------------------------------------------------------------
# Phase 2: Images aus GHCR pullen (SHA-gepinnt)
# ---------------------------------------------------------------------
#
# H-6 (QA-Audit 2026-04-29): GHCR-Tag develop/main mutiert bei jedem
# CI-Push. Statt mutierenden Tag pinnen wir auf <branch>-<short-sha>.
# build-images.yml taggt jedes Build entsprechend (metadata-action:
# type=sha,prefix={{branch}}-,format=short).
#
# Vorteile:
#   - Audit-Trail: Log enthaelt deploy-time Image-SHA.
#   - Rollback: alter SHA bleibt in GHCR pullbar.
#   - Keine Race-Condition zwischen git pull und docker pull.
#
# Wichtig: build-images.yml triggert nur bei Aenderungen unter backend/,
# frontend/ oder .github/workflows/build-images.yml. Bei reinen Infra-,
# Caddy-, Mosquitto- oder Doku-Commits gibt es KEIN neues Image fuer
# den HEAD-SHA. Daher pinnen wir auf den SHA des letzten Commits, der
# tatsaechlich einen Image-Build getriggert hat.

HEAD_SHA=$(git -C "$REPO_DIR" rev-parse --short HEAD)
LAST_BUILD_SHA=$(git -C "$REPO_DIR" log -1 --pretty=format:%h -- \
    backend/ frontend/ .github/workflows/build-images.yml)

if [ -z "$LAST_BUILD_SHA" ]; then
    log "FEHLER: kein Build-relevanter Commit gefunden (leeres git log?)."
    exit 1
fi

if [ "$LAST_BUILD_SHA" = "$HEAD_SHA" ]; then
    log "HEAD ist build-relevant: IMAGE_TAG=${TARGET_BRANCH}-${HEAD_SHA}."
else
    log "HEAD ist Infra-/Doku-only ($HEAD_SHA). Letzter Build-Commit: $LAST_BUILD_SHA."
fi

PINNED_TAG="${TARGET_BRANCH}-${LAST_BUILD_SHA}"

cd "$COMPOSE_DIR"

log "docker compose pull api web (IMAGE_TAG=$PINNED_TAG) ..."
if ! IMAGE_TAG="$PINNED_TAG" docker compose -f "$COMPOSE_FILE" pull api web >>"$LOG" 2>&1; then
    log "FEHLER: Image-Pull fehlgeschlagen (Tag $PINNED_TAG nicht in GHCR? CI-Build noch laufend?)."
    exit 1
fi

# ---------------------------------------------------------------------
# Phase 3: Container-Stand aktualisieren
# ---------------------------------------------------------------------
#
# `up -d` ohne `--no-deps` und ohne `--force-recreate`:
#   - Container werden NUR neu erstellt, wenn sich ihre Konfiguration
#     (Compose-File) oder ihr Image-Digest geaendert hat.
#   - Sonst bleiben sie laufen, kein unnoetiger Downtime.
#
# `--remove-orphans` raeumt Services auf, die im aktuellen Compose-
# File nicht mehr existieren (z.B. wenn ein Service umbenannt wurde).
#
# IMAGE_TAG wird als Shell-env vorangestellt; docker compose
# priorisiert Shell-env vor .env-Datei.
log "docker compose up -d (IMAGE_TAG=$PINNED_TAG, alle Services) ..."
if ! IMAGE_TAG="$PINNED_TAG" docker compose -f "$COMPOSE_FILE" up -d --remove-orphans >>"$LOG" 2>&1; then
    log "FEHLER: docker compose up fehlgeschlagen."
    exit 1
fi

log "Aktiv: $(IMAGE_TAG="$PINNED_TAG" docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}}={{.Status}}' | tr '\n' ' ')"
log "Fertig (HEAD=$NEW_SHA, IMAGE_TAG=$PINNED_TAG)."
