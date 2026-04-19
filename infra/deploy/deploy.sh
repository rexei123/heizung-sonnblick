#!/usr/bin/env bash
#
# Deploy-Skript für Heizung Sonnblick.
# Wird von GitHub Actions (deploy-test.yml / deploy-main.yml) per SSH aufgerufen.
#
# Erwartet:
#   - Repo liegt unter /opt/heizung-sonnblick
#   - Dortiges Compose-Env-File unter infra/deploy/.env (NICHT im Git)
#   - Docker + Docker Compose installiert, User in Gruppe 'docker'
#
# Ablauf: Images bauen, Migrationen fahren, Services neu starten, Healthcheck.

set -euo pipefail

STAGE="${1:?Stage erforderlich: test oder main}"

if [[ "$STAGE" != "test" && "$STAGE" != "main" ]]; then
    echo "Ungültige Stage: $STAGE (erwartet: test|main)" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_DIR="${REPO_ROOT}/infra/deploy"
COMPOSE_FILE="${DEPLOY_DIR}/docker-compose.prod.yml"
ENV_FILE="${DEPLOY_DIR}/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "FEHLER: ${ENV_FILE} fehlt. Siehe .env.example." >&2
    exit 1
fi

export STAGE
cd "$DEPLOY_DIR"

echo "==> [${STAGE}] Images bauen"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build --pull

echo "==> [${STAGE}] Datenbank-Migrationen (Alembic)"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm api alembic upgrade head

echo "==> [${STAGE}] Services starten"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --remove-orphans

echo "==> [${STAGE}] Warte auf Healthcheck"
for i in {1..30}; do
    if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T api \
        curl --silent --fail http://localhost:8000/health > /dev/null; then
        echo "    API ist healthy."
        break
    fi
    if [[ "$i" -eq 30 ]]; then
        echo "FEHLER: API wurde nicht healthy." >&2
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" logs api --tail=100
        exit 1
    fi
    sleep 2
done

echo "==> [${STAGE}] Alte Images prunen"
docker image prune -f

echo "==> [${STAGE}] Deploy abgeschlossen."
