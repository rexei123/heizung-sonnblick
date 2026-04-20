#!/bin/sh
# Container-Entrypoint für das Heizung-Backend.
#
# Führt beim Start automatisch `alembic upgrade head` aus, bevor die API
# hochfährt. Das entkoppelt Deploys von manuellen Migrations-Schritten.
#
# - Idempotent: alembic upgrade head ist ein No-Op, wenn die DB bereits
#   am Kopf der Migrationshistorie steht.
# - Retry: max. 5 Versuche mit 3 s Pause, falls die DB beim ersten
#   Start noch nicht erreichbar ist (z. B. nach Neustart des Stacks).
# - Schlägt nach 5 Fehlversuchen fehl — Container crasht sichtbar.
# - Reicht anschließend per `exec` in den CMD (uvicorn) durch, damit
#   Signale (SIGTERM, SIGINT) korrekt am App-Prozess ankommen.

set -e

echo "[entrypoint] Starte Alembic-Migration..."

for i in 1 2 3 4 5; do
    if alembic upgrade head; then
        echo "[entrypoint] Migrationen angewendet (Kopf erreicht)."
        break
    fi
    if [ "$i" = "5" ]; then
        echo "[entrypoint] Migration nach 5 Versuchen fehlgeschlagen. Abbruch." >&2
        exit 1
    fi
    echo "[entrypoint] Migration-Versuch $i fehlgeschlagen, warte 3 s..."
    sleep 3
done

echo "[entrypoint] Starte Anwendung: $*"
exec "$@"
