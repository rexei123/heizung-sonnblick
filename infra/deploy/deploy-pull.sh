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
#   2. App-Images aus GHCR pullen (api, web) — mit einem Tag, der auf
#      den Commit zeigt, auf den Phase 1 gesynct hat (H-6, AE-77).
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
#   2026-10-08  H-6 (AE-77): Pinning kommt wieder, diesmal ohne die
#               Heuristik von damals. Der Tag wird aus `NEW_SHA`
#               gebildet — also aus dem Commit, auf den Phase 1 ohnehin
#               synct — und nicht aus `git log -- backend/...`. Dazu
#               `PIN_SHA` als Rueckfallpunkt, der den Timer ueberlebt.

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
# Die naechste Zeile wird vom Pin-Waechter weiter unten gegrept (er prueft
# sie im Ziel-Commit). Wer `read_env_key` umbenennt, zieht das Muster dort
# mit nach — sonst bricht jeder Pin ab, mit einer Meldung, die nach einem
# zu alten Ziel-Commit aussieht.
PIN_SHA_VAL=$(read_env_key PIN_SHA)

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

# ---------------------------------------------------------------------
# PIN_SHA: der Rueckfallpunkt gewinnt (H-6 T4)
# ---------------------------------------------------------------------
#
# Ist `PIN_SHA` in der .env gesetzt, faehrt der Server **diesen** Commit —
# Working-Tree UND Image — und folgt dem Branch nicht mehr. Leeren und einen
# Timer-Lauf abwarten holt den Branch-Kopf zurueck.
#
# **Warum der Working-Tree mitgeht.** Darin stecken die Compose-Datei, die
# Caddyfiles, die ChirpStack-TOMLs und die Mosquitto-Config. Ein Rueckfall,
# der nur das Image zurueckdreht, kombiniert alte Container mit neuer
# Compose-Datei — und wenn dazwischen ein Service dazukam oder eine
# Umgebungsvariable ihren Namen geaendert hat, startet der Stack nicht oder
# startet falsch.
#
# **Warum ein unbekannter Pin ABBRICHT und nicht auf den Branch zurueckfaellt.**
# Ein Tippfehler im Pin wuerde sonst stumm den neuesten Stand deployen —
# also genau das Gegenteil dessen, was jemand wollte, der gerade
# zurueckrollt. Lieber ein Deploy, der steht und es sagt.
#
# Migrations-Vorbehalt: ein Rueckfall ist nur ueber **additive** Migrationen
# zulaessig. Der Container fuehrt beim Start `alembic upgrade head` aus;
# rueckwaerts geht das nicht automatisch. Siehe RUNBOOK §10u.
if [ -n "$PIN_SHA_VAL" ]; then
    if ! git rev-parse --verify --quiet "${PIN_SHA_VAL}^{commit}" >/dev/null; then
        log "ABBRUCH: PIN_SHA='$PIN_SHA_VAL' ist in diesem Repo kein Commit."
        log "         Kein Rueckfall auf den Branch — das waere das Gegenteil"
        log "         dessen, was ein Pin bedeutet. Pin korrigieren oder leeren."
        ping_healthcheck "$(read_env_key HEALTHCHECK_DEPLOY_URL)" "deploy" \
            "abort: PIN_SHA '$PIN_SHA_VAL' unbekannt" || true
        exit 1
    fi
    # Der Pin-Waechter: zeigt der Pin auf einen Commit, dessen
    # deploy-pull.sh die Pin-Logik noch nicht kennt, haelt der Rueckfall
    # nicht.
    #
    # Der Timer startet dieses Skript **aus dem Working-Tree**
    # (ExecStart=/opt/heizung-sonnblick/infra/deploy/deploy-pull.sh), und der
    # Working-Tree geht beim Pin mit zurueck. Beim naechsten Tick laeuft dann
    # das alte Skript, kennt `PIN_SHA` nicht und synct auf den Branch-Kopf:
    # der Rueckfall hebt sich nach fuenf Minuten selbst auf.
    #
    # Das ist das lautlose Fehlerbild, nicht das laute. Der Lauf von Hand
    # meldet vorher korrekt „PIN_SHA gesetzt", die Pruefung nach RUNBOOK §10u
    # Schritt 5 ist gruen — und fuenf Minuten spaeter ist der Stand wieder
    # da, den jemand gerade verlassen wollte. Deshalb hier der Abbruch:
    # lieber kein Rueckfall als einer, der nicht haelt (§5.76).
    if ! git show "${PIN_SHA_VAL}:infra/deploy/deploy-pull.sh" 2>/dev/null |
        grep -q 'read_env_key PIN_SHA'; then
        log "ABBRUCH: Ziel-Commit '$PIN_SHA_VAL' enthaelt ein deploy-pull.sh"
        log "         ohne Pin-Logik. Der naechste Timer-Lauf wuerde das alte"
        log "         Skript starten, den Pin ignorieren und den Rueckfall"
        log "         aufheben. Neueren Ziel-Commit waehlen — RUNBOOK §10u,"
        log "         Schritt 0a nennt den Pruefbefehl."
        ping_healthcheck "$(read_env_key HEALTHCHECK_DEPLOY_URL)" "deploy" \
            "abort: PIN_SHA '$PIN_SHA_VAL' ohne Pin-Logik im Skript" || true
        exit 1
    fi

    ZIEL_SHA=$(git rev-parse "$PIN_SHA_VAL")
    log "PIN_SHA gesetzt: $PIN_SHA_VAL -> $ZIEL_SHA. Automatik aus,"
    log "         der Branch-Kopf wird NICHT verfolgt."
else
    ZIEL_SHA=$(git rev-parse "origin/$TARGET_BRANCH")
fi

if [ "$OLD_SHA" != "$ZIEL_SHA" ]; then
    OLD_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    log "Sync $OLD_BRANCH@$OLD_SHA  ->  $ZIEL_SHA ..."
    if [ -n "$PIN_SHA_VAL" ]; then
        # Losgeloester HEAD: der Pin ist kein Branch, und ein Branch, der
        # auf einen alten Commit zeigt, waere eine zweite Wahrheit neben
        # der .env.
        git checkout --quiet --detach "$ZIEL_SHA"
    else
        git checkout --quiet "$TARGET_BRANCH"
        git reset --hard --quiet "origin/$TARGET_BRANCH"
    fi
else
    log "Working-Tree bereits auf $ZIEL_SHA."
fi

# ---------------------------------------------------------------------
# Der Image-Tag (H-6 T2)
# ---------------------------------------------------------------------
#
# `<branch>-<sha7>` — genau das Format, das `build-images.yml` vergibt
# (`type=sha,prefix={{branch}}-,format=short`). Die sieben Zeichen sind
# nicht geraten: `format=short` liefert sieben, und die Tags im GHCR
# (`develop-394a056` ...) belegen es.
#
# **Der Tag wird NICHT in die .env geschrieben** (T5). Eine Datei, die der
# Timer alle fuenf Minuten ueberschreibt, ist kein Ort fuer eine
# Entscheidung des Menschen — ein Rueckfall per .env-Eintrag waere nach
# fuenf Minuten weg. Der Wert wird je Lauf berechnet und an
# `docker compose` uebergeben; die Shell-Umgebung schlaegt dort die .env.
#
# `IMAGE_TAG` in der .env bleibt als Rueckfall fuer einen von Hand
# getippten `docker compose up -d` stehen — dann gilt der gleitende Tag,
# und das ist besser als ein leerer Wert.
IMAGE_TAG="${TARGET_BRANCH}-$(printf '%s' "$ZIEL_SHA" | cut -c1-7)"
export IMAGE_TAG
log "IMAGE_TAG=$IMAGE_TAG"

NEW_SHA="$ZIEL_SHA"

# ---------------------------------------------------------------------
# Phase 2: Images aus GHCR pullen
# ---------------------------------------------------------------------
#
# `IMAGE_TAG` ist oben aus `ZIEL_SHA` gebildet und exportiert.
#
# Der Versuch von 2026-04-30 scheiterte daran, dass er den Tag aus
# `git log -- backend/...` ableitete — also aus dem letzten Commit, der
# `backend/` beruehrt hat, und das ist bei einem Merge ein anderer als der
# Merge-Commit. Der richtige Wert steht in `ZIEL_SHA`: der Commit, auf den
# dieses Skript den Working-Tree gesynct hat (§5.4 beschreibt den alten
# Fix, nicht eine Notwendigkeit).
#
# Dass es fuer **jeden** Commit einen Tag gibt, stellt `build-images.yml`
# sicher: beruehrt ein Commit ein Image nicht, wird der Tag des Vorgaengers
# umgehaengt statt gebaut (Weg C, AE-77).

cd "$COMPOSE_DIR"

log "docker compose pull api web (IMAGE_TAG=$IMAGE_TAG) ..."
if ! docker compose -f "$COMPOSE_FILE" pull api web >>"$LOG" 2>&1; then
    # Der Pull ist gleichzeitig die Existenzpruefung: er aendert keinen
    # Container, nur den lokalen Image-Speicher. Ein Fehlschlag bricht also
    # ab, **bevor** Phase 3 etwas anfasst — kein halber Deploy.
    #
    # Zwei Ursachen, zwei Reaktionen, und sie zu unterscheiden ist die Arbeit
    # des Diagnose-Schritts: ein **fehlender Tag** heisst, dass ein Build
    # nicht gelaufen ist (dann wartet man auf ihn oder pinnt woanders hin);
    # eine **unerreichbare Registry** ist voruebergehend (dann holt der
    # naechste Timer-Lauf es nach). Ohne diese Unterscheidung sucht jemand
    # im falschen System.
    log "FEHLER: Image-Pull fehlgeschlagen (IMAGE_TAG=$IMAGE_TAG)."
    for IMG in heizung-api heizung-web; do
        REF="ghcr.io/rexei123/$IMG:$IMAGE_TAG"
        if docker manifest inspect "$REF" >/dev/null 2>&1; then
            log "         $REF: vorhanden."
        else
            log "         $REF: NICHT vorhanden oder nicht abfragbar."
        fi
    done
    log "         Fehlt der Tag, ist der Build zu diesem Commit nicht gelaufen"
    log "         (build-images.yml pruefen). Ist er da, war es die Registry"
    log "         oder der ghcr-Login — der naechste Lauf holt es nach."
    ping_healthcheck "$(read_env_key HEALTHCHECK_DEPLOY_URL)" "deploy" \
        "abort: pull failed for $IMAGE_TAG" || true
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

# ---------------------------------------------------------------------
# Abschluss-Zeile (H-6 T6)
# ---------------------------------------------------------------------
#
# Die Zeile, die bei „seit wann laeuft was" gelesen wird. Sie nennt Commit,
# Tag und die beiden Digests zusammen — vorher stand der Commit im Log und
# der Digest in `docker images`, und niemand hielt sie gegeneinander.
# Das war §5.68 in der Infrastruktur: „der Server laeuft auf develop" ist
# eine Behauptung, solange niemand den Commit nennen kann.
API_DIGEST=$(docker image inspect --format '{{index .RepoDigests 0}}' \
    "ghcr.io/rexei123/heizung-api:$IMAGE_TAG" 2>/dev/null | cut -d@ -f2 | cut -c1-19)
WEB_DIGEST=$(docker image inspect --format '{{index .RepoDigests 0}}' \
    "ghcr.io/rexei123/heizung-web:$IMAGE_TAG" 2>/dev/null | cut -d@ -f2 | cut -c1-19)
if [ -n "$PIN_SHA_VAL" ]; then
    log "Fertig. HEAD=$NEW_SHA IMAGE_TAG=$IMAGE_TAG api=${API_DIGEST:-?} web=${WEB_DIGEST:-?} PIN=$PIN_SHA_VAL"
else
    log "Fertig. HEAD=$NEW_SHA IMAGE_TAG=$IMAGE_TAG api=${API_DIGEST:-?} web=${WEB_DIGEST:-?}"
fi

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
#
# Bei gesetztem Pin traegt der Ping ihn im Body. Grund: ein Pin, den jemand
# gesetzt und vergessen hat, ist ein Server, der weitere Merges nicht mehr
# zieht — und das faellt in einem gruenen Monitor nicht auf. Die
# woechentliche Erinnerung per Mail ist ein eigener Task (T10).
HEALTHCHECK_DEPLOY_URL=$(read_env_key HEALTHCHECK_DEPLOY_URL)
if [ -n "$PIN_SHA_VAL" ]; then
    ping_healthcheck "$HEALTHCHECK_DEPLOY_URL" "deploy" \
        "ok: pinned to $IMAGE_TAG (automatik aus)" || true
else
    ping_healthcheck "$HEALTHCHECK_DEPLOY_URL" "deploy" || true
fi
