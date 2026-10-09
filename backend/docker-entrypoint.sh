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
#
# Vorcheck (Sprint 20g, H-6 Nachtrag)
# -----------------------------------
# Vor dem Upgrade wird geprüft, ob dieses Image die Revision kennt, die in
# `alembic_version` steht. Nach einem Rückfall per PIN_SHA (RUNBOOK §10u)
# ist die Datenbank **neuer** als der Code, und `alembic upgrade head`
# bricht mit "Can't locate revision" ab — fünf Versuche, dann `exit 1`.
# Weil api, celery_worker und celery_beat dasselbe Image mit demselben
# Entrypoint fahren und `restart: always` gilt, wäre das Ergebnis ein
# Neustart-Karussell ohne API und ohne Engine.
#
# Der Vorcheck gibt 10 für "überspringen" und 0 für alles andere,
# **einschließlich jedes unklaren Falls**: er darf nie selbst zur
# Abbruchursache werden. Siehe `heizung/scripts/db_revision_check.py`.

set -e

echo "[entrypoint] Pruefe, ob dieses Image die DB-Revision kennt..."

set +e
python -m heizung.scripts.db_revision_check
VORCHECK=$?
set -e

if [ "$VORCHECK" = "10" ]; then
    # Die Meldung mit dem Grund kommt aus dem Vorcheck selbst. Hier nur
    # die Zeile, die man im `docker logs` sucht.
    echo "[entrypoint] Migration UEBERSPRUNGEN (DB neuer als dieses Image)." >&2
else
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
fi

echo "[entrypoint] Starte Anwendung: $*"
exec "$@"
