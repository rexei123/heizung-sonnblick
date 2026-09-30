#!/bin/bash
# Pull-basierter Deploy.
#
# Vier Phasen, idempotent:
#   0. Deploy-Sperre pruefen: laeuft ein Batch-Eingangstest, wird der
#      ganze Lauf uebersprungen (Sprint 20a, CLAUDE.md §0.3).
#   1. Working-Tree von origin/<DEPLOY_BRANCH> syncen (Compose-Schema,
#      Mosquitto-Config, Caddyfiles, ChirpStack-TOMLs, Postgres-Init).
#      DEPLOY_BRANCH leitet sich aus STAGE in der .env ab:
#         STAGE=test  ->  develop
#         STAGE=main  ->  main
#   2. App-Images aus GHCR pullen (api, web).
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
#   2026-09-30  Sprint 20a: Phase 0 (Deploy-Sperre). Ein Merge nach
#               develop ist ein Deploy, und ein Deploy mitten in einem
#               Eingangstest laesst ein Geraet mit ausstehendem Downlink
#               zurueck. Vorher war das eine Regel (frag vor dem Merge),
#               jetzt ein Gate.
#   2026-04-30  H-6 SHA-Pinning revertiert (Tag-Mismatch CI vs git-log).
#               Eigener Sprint, der CI-Workflow + deploy-pull synchron
#               anpasst, ist Backlog. Bis dahin: mutierender Tag aus .env.

set -euo pipefail

# LOG und REPO_DIR sind ueberschreibbar, damit das Skript testbar ist. Im
# Betrieb setzt sie niemand — der systemd-Timer ruft es ohne Umgebung auf und
# bekommt die Vorgaben. Der Test (`tests/test_deploy_pull_lock.py`) zeigt
# damit am echten Skript, dass eine gesetzte Sperre den Pull verhindert; ein
# nachgebautes Skript im Test wuerde nur sich selbst pruefen.
LOG=${DEPLOY_LOG:-/var/log/heizung-deploy.log}
REPO_DIR=${DEPLOY_REPO_DIR:-/opt/heizung-sonnblick}
COMPOSE_DIR="$REPO_DIR/infra/deploy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.prod.yml"
ENV_FILE="$COMPOSE_DIR/.env"

log() {
    echo "[$(date --iso-8601=seconds)] $*" | tee -a "$LOG"
}

# Dead-Man-Ping (Sprint 18). Die Begruendung steht unten an der Aufrufstelle;
# die Definition steht hier oben, weil der Uebersprungen-Pfad (Sprint 20a,
# Deploy-Sperre) sie vor Phase 1 braucht und Shell-Funktionen vor ihrem
# Aufruf definiert sein muessen.
#
# Der Ping darf den Lauf nie abbrechen: `|| true` am Aufruf, `return 0` hier.
#
# Dritter Parameter (optional) ist der Body. healthchecks.io haengt ihn an
# den Ping-Eintrag — damit steht im Monitor nicht nur DASS gepingt wurde,
# sondern warum. Ohne Body wird ein GET geschickt wie bisher.
ping_healthcheck() {
    local url="$1"
    local label="$2"
    local body="${3:-}"
    if [ -z "$url" ]; then
        return 0
    fi
    if [ -n "$body" ]; then
        if curl -fsS -m 10 --retry 3 --data-raw "$body" "$url" >/dev/null 2>&1; then
            log "Dead-Man-Ping ${label}: ok (${body})."
        else
            log "Dead-Man-Ping ${label}: fehlgeschlagen. Lauf bleibt erfolgreich."
        fi
        return 0
    fi
    if curl -fsS -m 10 --retry 3 "$url" >/dev/null 2>&1; then
        log "Dead-Man-Ping ${label}: ok."
    else
        log "Dead-Man-Ping ${label}: fehlgeschlagen. Lauf bleibt erfolgreich."
    fi
    return 0
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
# Phase 0: Deploy-Sperre pruefen (Sprint 20a)
# ---------------------------------------------------------------------
#
# Ein Batch-Eingangstest laeuft ueber `docker compose exec` im
# api-Container. Phase 3 (`up -d`) rekreiert diesen Container, sobald ein
# neues Image da ist — der Lauf stirbt dann mitten in einer
# Bestaetigungs-Kette.
#
# Was dabei NICHT verloren geht: die bereits beurteilten Geraete
# (`_finalize_device` committet je Geraet, `--resume` setzt auf). Verloren
# ist das Geraet, das gerade auf seine Bestaetigung wartete — es hat
# Downlinks bekommen, aber kein Urteil, und der Resume-Lauf schickt sie
# erneut. Doppelte Befehle an ein Geraet, dessen erste Runde niemand mehr
# zuordnen kann: CLAUDE.md §0 S4.
#
# Der Eingangstest setzt deshalb einen Redis-Key mit TTL
# (`services/deploy_lock.py`). Steht er, wird der GANZE Lauf
# uebersprungen — nicht nur Phase 3. Ein halber Deploy (Working-Tree
# gesynct, Images gezogen, Container alt) waere ein Zustand, den niemand
# erwartet und den der naechste Lauf auch nicht als solchen erkennt.
#
# Faellt die Abfrage aus (Stack unten, redis-Container weg), wird NICHT
# gesperrt: dann laeuft auch kein Eingangstest, denn der braucht denselben
# Stack. Eine Sperre bei unbekanntem Zustand wuerde den Deploy bei jedem
# Redis-Ausfall lahmlegen — und das ist der Fall, in dem man deployen will.
LOCK_KEY="heizung:lock:inbound_test"

lock_ttl() {
    # Gibt die Rest-TTL in Sekunden aus, oder leer wenn nicht abfragbar.
    # redis-cli TTL: -2 = Key fehlt, -1 = Key ohne Ablauf.
    docker compose -f "$COMPOSE_FILE" exec -T redis \
        redis-cli --raw TTL "$LOCK_KEY" 2>/dev/null | tr -d '\r' | head -n1
}

TTL_RAW=$(lock_ttl || true)

if [ -z "$TTL_RAW" ]; then
    log "Deploy-Sperre: nicht abfragbar (Redis/Stack nicht erreichbar) — fahre fort."
elif [ "$TTL_RAW" = "-2" ]; then
    : # Key fehlt: keine Sperre, normaler Lauf.
elif [ "$TTL_RAW" = "-1" ]; then
    # Key ohne TTL. Sollte es nicht geben (`deploy_lock.acquire` setzt immer
    # eine), waere aber der gefaehrlichste Fall: eine Sperre, die nie
    # verfaellt. Deshalb sperren und den Zustand benennen, damit jemand
    # nachsieht, statt still zu deployen.
    log "ABBRUCH: Deploy-Sperre $LOCK_KEY steht OHNE TTL. Das ist kein normaler"
    log "         Zustand — ein Lauf setzt immer eine TTL. Bitte pruefen:"
    log "         docker compose -f $COMPOSE_FILE exec -T redis redis-cli GET $LOCK_KEY"
    ping_healthcheck "$(read_env_key HEALTHCHECK_DEPLOY_URL)" "deploy" \
        "skipped: inbound_test lock (ohne TTL — bitte pruefen)" || true
    exit 0
elif [ "$TTL_RAW" -gt 0 ] 2>/dev/null; then
    LOCK_BIS=$(date -d "+${TTL_RAW} seconds" --iso-8601=seconds)
    log "UEBERSPRUNGEN: Eingangstest laeuft (Sperre $LOCK_KEY, TTL ${TTL_RAW}s)."
    log "               Naechster Versuch beim naechsten Timer-Lauf."
    # Gepingt wird trotzdem — sonst schlaegt der Deploy-Monitor nach 20 min
    # Karenz an, und ein Montage-Lauf dauert 1-3 Stunden. Ein Falsch-Alarm
    # bei jedem Lauf macht den Melder wertlos (CLAUDE.md §5.79). Der Body
    # sagt, warum nicht deployt wurde, damit der Zustand im Monitor steht
    # und nicht nur im Server-Log.
    ping_healthcheck "$(read_env_key HEALTHCHECK_DEPLOY_URL)" "deploy" \
        "skipped: inbound_test lock (TTL bis ${LOCK_BIS})" || true
    exit 0
else
    log "Deploy-Sperre: unerwartete TTL-Antwort '$TTL_RAW' — fahre fort."
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
# Phase 2: Images aus GHCR pullen
# ---------------------------------------------------------------------
#
# IMAGE_TAG kommt aus .env (mutierender Tag develop/main).
# Sprint 6 H-6 (SHA-Pinning) wurde mehrfach versucht und revertiert:
# build-images.yml taggt mit GitHub-push-event-SHA (= Merge-Commit auf
# Ziel-Branch). Eine deploy-Logik aus dem lokalen git log findet aber
# den Source-Branch-Commit. Tag-Mismatch -> Pull schlaegt fehl.
# H-6 deferred auf eigenen Sprint, der CI + deploy-pull synchron anpasst.

cd "$COMPOSE_DIR"

log "docker compose pull api web ..."
if ! docker compose -f "$COMPOSE_FILE" pull api web >>"$LOG" 2>&1; then
    log "FEHLER: Image-Pull fehlgeschlagen (ggf. ghcr-Login pruefen)."
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

log "docker compose up -d (alle Services) ..."
if ! docker compose -f "$COMPOSE_FILE" up -d --remove-orphans >>"$LOG" 2>&1; then
    log "FEHLER: docker compose up fehlgeschlagen."
    exit 1
fi

log "Aktiv: $(docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}}={{.Status}}' | tr '\n' ' ')"
log "Fertig (HEAD=$NEW_SHA)."

# ---------------------------------------------------------------------
# Dead-Man-Ping (Sprint 18)
# ---------------------------------------------------------------------
#
# Ueberwacht wird die WIRKUNG, nicht die Mechanik (CLAUDE.md 5.76): der
# Monitor auf healthchecks.io schlaegt Alarm, wenn dieser Ping ausbleibt.
# Ob der Timer laeuft, ob systemd ihn kennt, ob das Skript ausfuehrbar ist
# - all das braucht niemand einzeln zu pruefen. Bleibt der Ping aus, ist
# irgendetwas davon kaputt.
#
# Die Stelle ist mit Absicht hier unten: erreicht wird sie nur, wenn Fetch,
# Working-Tree-Sync, Image-Pull und `up -d` durch sind. Jeder Fehlerpfad
# oben endet in `exit 1`, also ohne Ping. Der No-op-Lauf ("Working-Tree
# bereits auf origin/<branch>") laeuft dagegen bis hierher durch und pingt
# - er IST ein erfolgreicher Lauf, nur ohne Aenderung.
#
# Der Ping darf den Lauf nie abbrechen. Deshalb `|| true` in der Funktion,
# `return 0` am Ende und der Aufruf ohne `set -e`-Exposition.
HEALTHCHECK_DEPLOY_URL=$(read_env_key HEALTHCHECK_DEPLOY_URL)
ping_healthcheck "$HEALTHCHECK_DEPLOY_URL" "deploy" || true
