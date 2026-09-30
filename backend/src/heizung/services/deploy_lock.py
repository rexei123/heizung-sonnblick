"""Deploy-Sperre fuer langlaufende Geraete-Vorgaenge (Sprint 20a).

Der Deploy-Timer auf heizung-test zieht ``origin/develop`` alle fuenf
Minuten und ruft ``docker compose up -d``. Das rekreiert den api-Container,
sobald ein neues Image da ist — und ein Batch-Eingangstest laeuft ueber
``docker compose exec`` in genau diesem Container.

Was dabei verloren geht, ist **nicht** die bisherige Arbeit:
``batch_inbound_test._finalize_device`` committet je Geraet, ``--resume``
setzt korrekt auf. Verloren ist das Geraet, das in der Bestaetigungs-Kette
hing — es hat Downlinks bekommen, aber kein Urteil, und der Resume-Lauf
schickt sie **erneut**. Doppelte Befehle an ein Geraet, dessen erste Runde
niemand mehr zuordnen kann: das ist S4.

Bis heute war die Absicherung eine Regel (CLAUDE.md §0.3): vor jedem Merge
nach develop wird gefragt, ob ein Lauf offen ist. Die Regel traegt nur,
solange sie gestellt wird. Dieses Modul ist das technische Gate dahinter.

Mechanik
--------

Ein einzelner Redis-Key. Der Eingangstest setzt ihn beim Start, verlaengert
ihn im Lauf und loescht ihn am Ende; ``deploy-pull.sh`` fragt ihn vor dem
Fetch ab und ueberspringt den ganzen Lauf, wenn er steht.

**Die TTL ist die eigentliche Sicherung, nicht das Loeschen.** Stirbt der
Prozess hart — Container-Stop, ``kill -9``, Stromausfall — laeuft kein
``finally``. Dann muss die Sperre von selbst verfallen, sonst blockiert ein
abgestuerzter Testlauf jeden Deploy auf Dauer. Umgekehrt darf sie nicht so
kurz sein, dass sie zwischen zwei Verlaengerungen ausfaellt: der laengste
Abstand im Lauf ist ein Warte-Fenster (Heartbeat bis 15 min, Ventil-Frames
bis zum Timeout), deshalb ``Timeout + 15 min`` als Standard.

Der Key ist **nicht** ``nx``-gesetzt. Zwei parallele Eingangstests sind
kein Szenario, das dieses Modul verhindern soll — es geht um den Deploy,
und zwei Laeufe wollen dieselbe Sperre. Wer Ueberschneidung verhindern
will, braucht eine eigene Zusicherung; ``nx`` hier wuerde den zweiten Lauf
ohne Sperre weiterfahren lassen, also das Gegenteil des Gewuenschten.

Bei Redis-Fehler geben alle Funktionen ``False`` zurueck und loggen. Der
Aufrufer entscheidet — ``pair_devices`` bricht ab, weil ein Lauf ohne
Sperre genau das Risiko ist, das hier ausgeschlossen werden soll.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import redis

from heizung.services import redis_client

logger = logging.getLogger(__name__)

# Voll qualifiziert, damit der Key im Redis-Bestand zuordenbar ist: es ist
# eine Sperre (nicht ein Zaehler, nicht ein Flag) und sie gehoert dem
# Eingangstest. Derselbe Aufbau wie ``heizung:lock:*`` im engine_lock.
DEPLOY_LOCK_KEY = "heizung:lock:inbound_test"

# Sicherheitsnetz oberhalb des laengsten Warte-Fensters im Lauf.
LOCK_TTL_MARGIN_S = 15 * 60


def _client() -> redis.Redis:
    return redis_client.get_redis_client()


def acquire(*, ttl_s: int) -> bool:
    """Setzt die Sperre mit TTL. ``True`` bei Erfolg.

    Ueberschreibt eine bestehende Sperre bewusst (kein ``nx``) — siehe
    Modul-Docstring.
    """
    try:
        _client().set(DEPLOY_LOCK_KEY, _stamp(), ex=ttl_s)
        logger.info("deploy_lock: gesetzt, TTL %ds", ttl_s)
        return True
    except redis.RedisError:
        logger.warning("deploy_lock.acquire: redis-fehler", exc_info=True)
        return False


def refresh(*, ttl_s: int) -> bool:
    """Verlaengert die TTL. ``True`` bei Erfolg.

    Bewusst ``set`` und nicht ``expire``: fiel Redis zwischendurch aus und
    ist der Key verschwunden, stellt ``set`` ihn wieder her. ``expire``
    wuerde auf einen fehlenden Key ``False`` liefern und die Sperre bliebe
    weg — der Lauf liefe dann ungeschuetzt weiter, ohne dass es jemand
    merkt.
    """
    try:
        _client().set(DEPLOY_LOCK_KEY, _stamp(), ex=ttl_s)
        return True
    except redis.RedisError:
        logger.warning("deploy_lock.refresh: redis-fehler", exc_info=True)
        return False


def release() -> bool:
    """Loescht die Sperre. ``True`` wenn der Key danach weg ist.

    Auch ``True``, wenn er schon weg war (TTL abgelaufen) — der gewuenschte
    Endzustand ist erreicht, und ein Fehler waere hier eine Falschmeldung
    im Abschlussbericht.
    """
    try:
        _client().delete(DEPLOY_LOCK_KEY)
        logger.info("deploy_lock: freigegeben")
        return True
    except redis.RedisError:
        logger.warning("deploy_lock.release: redis-fehler", exc_info=True)
        return False


def held_until() -> datetime | None:
    """Ablaufzeitpunkt der Sperre, oder ``None`` wenn sie nicht steht.

    Fuer den Bericht und fuer den Ping-Text des Deploy-Skripts. Bei
    Redis-Fehler ``None`` — ein unbekannter Zustand wird nicht als "steht
    nicht" gemeldet, sondern der Aufrufer sieht die Logzeile.
    """
    try:
        ttl = _client().ttl(DEPLOY_LOCK_KEY)
    except redis.RedisError:
        logger.warning("deploy_lock.held_until: redis-fehler", exc_info=True)
        return None
    # redis-py: -2 = Key fehlt, -1 = Key ohne TTL.
    if not isinstance(ttl, int) or ttl < 0:
        return None
    return datetime.now(tz=UTC) + timedelta(seconds=ttl)


def _stamp() -> str:
    """Wert des Keys: der Setz-Zeitpunkt, damit er im Log lesbar ist."""
    return datetime.now(tz=UTC).isoformat()


@contextmanager
def held(*, ttl_s: int) -> Iterator[None]:
    """Haelt die Sperre fuer die Dauer des Blocks.

    ``release`` laeuft im ``finally`` und damit auch bei ``KeyboardInterrupt``
    (Strg-C) und bei ``SystemExit`` — die CLI wandelt SIGTERM in Letzteres,
    damit ein ``docker stop`` denselben Weg nimmt.

    **Ohne Ausweg.** Es gibt keinen Schalter, der den Lauf ohne Sperre
    erlaubt. Ein erster Entwurf hatte einen (``--no-deploy-lock``, gedacht
    fuer "Redis nicht erreichbar, Test muss trotzdem laufen"); er ist
    entfernt, weil der Anwendungsfall nicht traegt:

    * Redis ist ein Container im selben Stack wie der api-Container, in dem
      der Test laeuft. Ein ``docker compose up -d redis`` behebt den Ausfall
      in Sekunden — das ist schneller als die Ueberlegung, ob man den
      Schalter setzen darf.
    * In genau diesem Zustand ist das Gate ohnehin unwirksam: die Abfrage in
      ``deploy-pull.sh`` scheitert dann auch, das Skript fuehrt fort. Der
      Schalter haette also nicht geschuetzt, sondern nur erlaubt, ungeschuetzt
      zu fahren.
    * Und er stand in dieser Fehlermeldung. Wer sie liest, kopiert eher den
      Schalter als den Redis-Neustart — eine Einladung, die Absicherung zu
      umgehen, statt die Ursache zu beheben.

    Raises:
        RuntimeError: wenn die Sperre nicht gesetzt werden konnte.
    """
    if not acquire(ttl_s=ttl_s):
        raise RuntimeError(
            "Deploy-Sperre konnte nicht gesetzt werden (Redis nicht erreichbar). "
            "Ohne sie koennte ein Deploy den Lauf mitten in einer "
            "Bestaetigungs-Kette abbrechen und ein Geraet mit ausstehendem "
            "Downlink zuruecklassen.\n"
            "Redis starten, dann erneut versuchen:\n"
            "  docker compose -f infra/deploy/docker-compose.prod.yml up -d redis"
        )
    try:
        yield
    finally:
        release()
