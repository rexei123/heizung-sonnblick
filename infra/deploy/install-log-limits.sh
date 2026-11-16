#!/bin/bash
# Richtet die beiden Log-Grenzen ein, die am 16.11.2026 gefehlt haben:
#
#   1. /etc/logrotate.d/heizung-deploy  fuer /var/log/heizung-deploy.log
#      (94,7 MB seit dem 20.04.2026, keine Regel vorhanden)
#   2. /etc/docker/daemon.json          Vorgabe max-size/max-file/compress
#      fuer den json-file-Treiber (deploy-chirpstack-1: 79,3 MB/Tag, map[])
#
# Die Rechnung hinter den Zahlen steht in infra/deploy/docker/README.md,
# die Laufliste fuer den Betreiber in docs/RUNBOOK.md §10be.
#
# Das Skript ist bewusst **nur Datei-Arbeit**. Es startet den Docker-Dienst
# nicht neu, es erstellt keinen Container neu, es ruft weder `docker` noch
# `systemctl` auf. Beides waere eine Server-Aenderung mit Nebenwirkung auf
# den laufenden Betrieb (§10ay: Mosquitto-Neustart am 04.11.; §10bb:
# chirpstack in Schleife am 15.11.) — die entscheidet der Betreiber, nicht
# dieses Skript. Was danach noch zu tun ist, schreibt es am Ende hin.
#
# Idempotent: ein zweiter Lauf auf unveraenderten Dateien aendert nichts und
# endet mit 0.
#
# ZIEL_LOGROTATE, ZIEL_DAEMON und QUELL_DIR sind ueberschreibbar, damit der
# Test (`backend/tests/test_log_limits.py`) das **echte** Skript in einem
# Wegwerf-Verzeichnis laufen lassen kann statt einen Nachbau zu pruefen
# (§5.82, dieselbe Huelle wie bei deploy-pull.sh).

set -euo pipefail

SKRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
QUELL_DIR=${QUELL_DIR:-$SKRIPT_DIR}
ZIEL_LOGROTATE=${ZIEL_LOGROTATE:-/etc/logrotate.d/heizung-deploy}
ZIEL_DAEMON=${ZIEL_DAEMON:-/etc/docker/daemon.json}

QUELLE_LOGROTATE="$QUELL_DIR/logrotate/heizung-deploy"
QUELLE_DAEMON="$QUELL_DIR/docker/daemon.json"

ERZWINGEN=0
if [ "${1:-}" = "--force" ]; then
    ERZWINGEN=1
fi

meldung() {
    echo "[install-log-limits] $*"
}

fehler() {
    echo "[install-log-limits] FEHLER: $*" >&2
    exit 1
}

for f in "$QUELLE_LOGROTATE" "$QUELLE_DAEMON"; do
    [ -f "$f" ] || fehler "Quelldatei fehlt: $f"
done

# ---------------------------------------------------------------------------
# 1. Die daemon.json pruefen, BEVOR sie kopiert wird.
#
# Eine fehlerhafte /etc/docker/daemon.json hindert den Docker-Dienst am
# Starten — gemerkt wuerde das erst beim naechsten Neustart, also moeglichst
# spaet und zum schlechtesten Zeitpunkt. Geprueft wird deshalb die Quelle,
# und §10be prueft nach dem Kopieren zusaetzlich mit
# `dockerd --validate` (das kann dieses Skript nicht, siehe Kopf).
# ---------------------------------------------------------------------------
PYTHON=""
for kandidat in python3 python; do
    if command -v "$kandidat" >/dev/null 2>&1; then
        PYTHON="$kandidat"
        break
    fi
done
[ -n "$PYTHON" ] || fehler "kein python3 gefunden — JSON-Pruefung nicht moeglich"

if ! "$PYTHON" -c "import json,sys; json.load(open(sys.argv[1]))" "$QUELLE_DAEMON"; then
    fehler "$QUELLE_DAEMON ist kein gueltiges JSON — nicht kopiert"
fi
meldung "daemon.json ist gueltiges JSON."

# ---------------------------------------------------------------------------
# 2. Kopieren, aber nichts Fremdes ueberschreiben.
#
# Am Server gab es am 16.11.2026 keine /etc/docker/daemon.json. Sollte dort
# inzwischen eine liegen, steht darin moeglicherweise etwas, das dieses
# Skript nicht kennt (Registry-Spiegel, Adressbereiche). Dann wird nicht
# kopiert, sondern der Unterschied gezeigt.
# ---------------------------------------------------------------------------
kopieren() {
    local quelle="$1" ziel="$2" name="$3"

    if [ -f "$ziel" ]; then
        if cmp -s "$quelle" "$ziel"; then
            meldung "$name: unveraendert, nichts zu tun."
            return 0
        fi
        if [ "$ERZWINGEN" -eq 0 ]; then
            meldung "$name: $ziel existiert und ist ANDERS. Nicht ueberschrieben."
            meldung "Unterschied (links vorhanden, rechts neu):"
            diff -u "$ziel" "$quelle" || true
            meldung "Mit --force erzwingen, wenn der Inhalt rechts gewollt ist."
            return 1
        fi
        cp "$ziel" "$ziel.vorher-$(date +%Y%m%d%H%M%S)"
        meldung "$name: Vorversion gesichert."
    fi

    mkdir -p "$(dirname "$ziel")"
    cp "$quelle" "$ziel"
    chmod 0644 "$ziel"
    meldung "$name: geschrieben nach $ziel."
    return 0
}

AUSSTEHEND=0
kopieren "$QUELLE_DAEMON" "$ZIEL_DAEMON" "daemon.json" || AUSSTEHEND=1
kopieren "$QUELLE_LOGROTATE" "$ZIEL_LOGROTATE" "logrotate-Regel" || AUSSTEHEND=1

# ---------------------------------------------------------------------------
# 3. Die logrotate-Regel trocken laufen lassen.
#
# `logrotate --debug` rotiert nichts, es liest nur und meldet, was es taete.
# Fehlt logrotate (z. B. in CI), wird die Pruefung uebersprungen statt den
# Lauf scheitern zu lassen — kopiert ist die Regel dann trotzdem.
# ---------------------------------------------------------------------------
if [ -f "$ZIEL_LOGROTATE" ]; then
    if command -v logrotate >/dev/null 2>&1; then
        if logrotate --debug "$ZIEL_LOGROTATE" >/dev/null 2>&1; then
            meldung "logrotate --debug: Regel ist lesbar."
        else
            meldung "WARNUNG: logrotate --debug meldet einen Fehler. Ausgabe:"
            logrotate --debug "$ZIEL_LOGROTATE" || true
            AUSSTEHEND=1
        fi
    else
        meldung "logrotate nicht vorhanden — Trockenlauf uebersprungen."
    fi
fi

# ---------------------------------------------------------------------------
# 4. Was dieses Skript bewusst NICHT tut.
# ---------------------------------------------------------------------------
cat <<'HINWEIS'

[install-log-limits] Die Dateien liegen. Was noch fehlt, macht dieses Skript
[install-log-limits] absichtlich nicht — Laufliste: docs/RUNBOOK.md §10be.
[install-log-limits]
[install-log-limits]   logrotate: wirkt von selbst mit dem naechsten
[install-log-limits]     logrotate.timer (taeglich 00:00). Nichts zu tun.
[install-log-limits]
[install-log-limits]   daemon.json: wirkt erst, wenn der Docker-Dienst sie
[install-log-limits]     gelesen hat UND ein Container neu ERSTELLT wird.
[install-log-limits]     Ein Neustart (auch der des Servers) genuegt nicht —
[install-log-limits]     ein neu gestarteter Container behaelt seine alte
[install-log-limits]     Log-Vorgabe.
[install-log-limits]     Vor dem Neustart des Dienstes pruefen mit:
[install-log-limits]       dockerd --validate --config-file=/etc/docker/daemon.json
[install-log-limits]
[install-log-limits]   VOR einer Neuerstellung von chirpstack: die ADR-Acks
[install-log-limits]     wegsichern (§10be Schritt 4). Eine Neuerstellung legt
[install-log-limits]     ein leeres Protokoll an, und §10av Schritt 6a hat
[install-log-limits]     keine zweite Quelle.
HINWEIS

if [ "$AUSSTEHEND" -ne 0 ]; then
    meldung "Mindestens ein Schritt ist offen (siehe oben)."
    exit 1
fi

meldung "Fertig."
