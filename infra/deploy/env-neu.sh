# shellcheck shell=bash
# Helfer fuer die Betriebsablaeufe: ENV_NEU und SQL.
#
# Benutzung (§10ab Teil 1, Schritt 0.6):
#
#     cd /opt/heizung-sonnblick/infra/deploy
#     . /opt/heizung-sonnblick/infra/deploy/env-neu.sh
#     ENV_NEU
#
# Diese Datei wird **gesourct**. Deshalb steht hier kein `set -e` und kein
# `set -u`: beides wuerde die interaktive Sitzung des Menschen mit kippen,
# der sie geladen hat.
#
# ---------------------------------------------------------------------------
# WARUM DAS EIN SKRIPT IST UND KEINE ZEILE ZUM KOPIEREN
# ---------------------------------------------------------------------------
#
# Die alte Fassung stand als eine Zeile in der Anleitung und lautete im Kern
# `set -a; . .env; set +a`. Am 04.11.2026 hat genau das Caddy von 06:59 bis
# 07:04 in einen Crashloop geschickt, Meldung
# `base64-decoding password … byte 46`.
#
# Der Mechanismus, und er hat zwei Haelften:
#
#   1. Ein bcrypt-Hash enthaelt Dollarzeichen. In der `.env` stehen sie
#      **verdoppelt**, weil compose die Verdopplung zu einem Zeichen
#      auflöst. Laedt die **Shell** dieselbe Datei, loest sie die
#      Verdopplung zur **Prozessnummer** auf. Aus dem Hash wird eine Zahl.
#   2. compose loest `${VAR}` **zuerst aus der Umgebung** und erst dann aus
#      der Datei. Der zerstoerte Wert gewinnt also gegen den richtigen.
#
# Die Datei war in Ordnung, die Umgebung war es nicht — und die Pruefung
# davor sah in die Datei. Vor Ort geloest wurde es mit `unset` auf die
# beiden Hash-Variablen, also damit, die Umgebung **leer** zu machen.
#
# Daraus folgt die Regel, die dieses Skript umsetzt:
#
#   **Ein Wert mit Dollarzeichen gehoert nicht in die Umgebung.** compose
#   muss ihn selbst aus der `.env` lesen, weil nur compose die Verdopplung
#   richtig auflöst. Die Umgebung kann ihn nur falsch tragen — als
#   Prozessnummer (wenn die Shell expandiert) oder mit den Dollarzeichen
#   doppelt (wenn sie es nicht tut). Beides ist falsch.
#
# Zwei Dinge kommen gratis dazu:
#
#   * **Nichts wird mehr ausgefuehrt.** `. .env` fuehrt Backticks und
#     `$(…)` in Werten aus. Hier wird gelesen, nicht interpretiert.
#   * **Eine bereits vergiftete Sitzung wird geputzt.** Wer vorher von Hand
#     `set -a; . ./.env` getippt hat, traegt den zerstoerten Wert schon.
#     ENV_NEU entfernt ihn, statt ihn stehen zu lassen.
#
# **Ein Unterschied zur alten Fassung, bewusst:** ein `#` **innerhalb**
# eines Wertes bleibt jetzt Teil des Wertes. Die Shell hat dort einen
# Kommentar gesehen, compose nicht. Da die Werte fuer compose gedacht sind,
# ist compose der richtige Maßstab — und ein Passwort mit `#` darin wird
# nicht mehr stillschweigend abgeschnitten.

# Wurzel des Repos. Normalerweise aus dem eigenen Pfad abgeleitet, damit
# derselbe Helfer im Test auf ein Wegwerf-Verzeichnis zeigen kann.
if [ -z "${HEIZUNG_WURZEL:-}" ]; then
    HEIZUNG_WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
fi
export HEIZUNG_WURZEL

HEIZUNG_ENV="${HEIZUNG_WURZEL}/infra/deploy/.env"
HEIZUNG_COMPOSE="${HEIZUNG_WURZEL}/infra/deploy/docker-compose.prod.yml"
export HEIZUNG_ENV HEIZUNG_COMPOSE

# ENV_LESEN — die .env in die Umgebung laden, ohne sie zu zerstoeren.
#
# Still, solange nichts zurueckgehalten wurde. Fuer die Pruefbefehle, deren
# Antwort eine einzige Zahl ist: zwei Zeilen Rauschen davor sind der Weg,
# auf dem man die Zahl ueberliest.
#
# Ausgabe nur im Ausnahmefall: die **Namen** der zurueckgehaltenen Werte.
# Namen, nie Werte — die Ausgabe landet in einem tmux-Protokoll.
ENV_LESEN() {
    if [ ! -f "$HEIZUNG_ENV" ]; then
        echo "ENV_NEU: ${HEIZUNG_ENV} nicht gefunden" >&2
        return 1
    fi

    local zeile schluessel wert zurueckgehalten=""

    # `read -r` expandiert nicht. Das ist der ganze Trick.
    while IFS= read -r zeile || [ -n "$zeile" ]; do
        # Leerzeilen und ganze Kommentarzeilen.
        case "$zeile" in
            ''|'#'*) continue ;;
        esac
        # Nur Zeilen der Form NAME=…
        case "$zeile" in
            [A-Za-z_]*=*) ;;
            *) continue ;;
        esac

        schluessel="${zeile%%=*}"
        wert="${zeile#*=}"

        # Umschliessende Anfuehrungszeichen entfernen, wie compose es tut.
        case "$wert" in
            \"*\") wert="${wert#\"}"; wert="${wert%\"}" ;;
            \'*\') wert="${wert#\'}"; wert="${wert%\'}" ;;
        esac

        # Der eigentliche Punkt: Werte mit Dollarzeichen bleiben draussen,
        # und ein schon vorhandener (womoeglich zerstoerter) Wert wird
        # entfernt, damit compose die Datei liest.
        case "$wert" in
            *'$'*)
                unset "$schluessel"
                zurueckgehalten="${zurueckgehalten} ${schluessel}"
                continue
                ;;
        esac

        export "${schluessel}=${wert}"
    done < "$HEIZUNG_ENV"

    if [ -n "$zurueckgehalten" ]; then
        echo "Nicht in die Umgebung gelegt (Dollarzeichen, compose liest sie aus der .env):${zurueckgehalten}"
    fi
}

# ENV_NEU — ENV_LESEN, und dazu den IMAGE_TAG auf den Stand des Servers.
#
# Das ist der Aufruf vor **jedem** `docker compose`. Er sagt laut, welchen
# Tag er gesetzt hat, weil genau das die Frage ist, die man an dieser
# Stelle hat.
ENV_NEU() {
    ENV_LESEN || return 1
    IMAGE_TAG="develop-$(git -C "$HEIZUNG_WURZEL" rev-parse --short HEAD)"
    export IMAGE_TAG
    echo "IMAGE_TAG=$IMAGE_TAG"
}

# ENV_BRAUCHE — abbrechen, wenn ein Wert fehlt, den der naechste Befehl
# als **Argument** weitergibt.
#
# ENV_LESEN haelt Werte mit Dollarzeichen bewusst zurueck, und fuer compose
# ist das richtig. Ein Shell-Befehl, der so einen Wert weitergibt, bekaeme
# dagegen eine leere Zeichenfolge — und `mosquitto_passwd -b` legt dann
# stillschweigend ein **leeres Passwort** an. Das ist schlimmer als ein
# Abbruch, und es ist eine Falle, die das Zurueckhalten erst erzeugt hat.
ENV_BRAUCHE() {
    local name status=0
    for name in "$@"; do
        if [ -z "${!name:-}" ]; then
            echo "FEHLER: ${name} ist nicht gesetzt. Entweder fehlt der Wert in der .env, oder er enthaelt ein Dollarzeichen und wurde zurueckgehalten — dann gehoert er nicht als Argument in einen Shell-Befehl." >&2
            status=1
        fi
    done
    return $status
}

# SQL — eine Abfrage gegen die Betriebsdatenbank.
SQL() {
    docker compose -f "$HEIZUNG_COMPOSE" exec -T db \
        psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off -tAc "$1"
}

# PRUEF_HASH_UMGEBUNG — die Pruefung, die am 04.11. gefehlt hat.
#
# Die alte Kontrolle las die **Datei** und war deshalb blind fuer den
# Fehler, der in der **Umgebung** steckte. Diese hier sieht auf beide
# Stellen und nennt keinen Wert.
PRUEF_HASH_UMGEBUNG() {
    local name status=0
    for name in "$@"; do
        if [ -n "${!name+gesetzt}" ]; then
            echo "FEHLER: ${name} steht in der Umgebung — compose wuerde diesen Wert nehmen, nicht den aus der .env. 'unset ${name}' oder ENV_NEU." >&2
            status=1
        elif grep -q "^${name}=.*\\\$\\\$" "$HEIZUNG_ENV"; then
            echo "OK: ${name} nur in der .env, mit verdoppelten Dollarzeichen."
        else
            echo "FEHLER: ${name} fehlt in der .env oder die Dollarzeichen sind nicht verdoppelt." >&2
            status=1
        fi
    done
    return $status
}
