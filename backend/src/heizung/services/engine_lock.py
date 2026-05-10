"""Redis-SETNX-Lock fuer Engine-Tasks (Sprint 9.10 T3.5).

Pro Raum darf zu jeder Zeit hoechstens EIN ``evaluate_room`` laufen.
Worker-Concurrency=2 + Reading-Trigger aus dem MQTT-Subscriber kann
sonst zwei parallele Evals fuer denselben Raum erzeugen — Folge:
doppelte ControlCommand-Rows, doppelte Downlinks, Hysterese-Umgehung.

Mechanik:
- ``try_acquire(room_id, ttl_s)`` macht ``SET key NX EX ttl`` und
  liefert True bei Erfolg, sonst False.
- ``release(room_id)`` loescht den Key (best effort, ignoriert Fehler).
- TTL > worst-case-Eval-Dauer: ``celery_app.task_time_limit=30`` => TTL=30s.
  Wenn ein Eval haengt und vom Worker gekillt wird, gibt der TTL den
  Lock frei und der naechste Eval kann starten.

Aufruf-Pattern:
    if not engine_lock.try_acquire(room_id):
        evaluate_room.apply_async((room_id,), countdown=5)
        return
    try:
        ...
    finally:
        engine_lock.release(room_id)

Eine eigene Connection pro Aufruf ist akzeptiert: redis-py haelt einen
Pool, fork-safe seit 4.x. Lock-Pfad ist <5 ms gegen lokales Redis.
"""

from __future__ import annotations

import logging

import redis

from heizung.config import get_settings

logger = logging.getLogger(__name__)

LOCK_KEY_TEMPLATE = "engine:eval:lock:{room_id}"
LOCK_TTL_S = 30


def _client() -> redis.Redis:
    """Sync-Redis-Client. Bewusst neu pro Call: get_settings() ist
    lru_cache't, ``redis.from_url`` baut intern einen Pool — somit
    teilen sich Calls innerhalb desselben Prozesses die Connections.
    """
    return redis.from_url(get_settings().redis_url, socket_timeout=2)


def lock_key(room_id: int) -> str:
    return LOCK_KEY_TEMPLATE.format(room_id=room_id)


def try_acquire(room_id: int, *, ttl_s: int = LOCK_TTL_S) -> bool:
    """SET key NX EX ttl — True wenn der Lock fuer diesen Raum frei war."""
    key = lock_key(room_id)
    acquired = _client().set(key, "1", nx=True, ex=ttl_s)
    return bool(acquired)


def release(room_id: int) -> None:
    """Loescht den Lock-Key. Logged Fehler, schluckt sie aber — der
    TTL fungiert als Watchdog falls Redis kurzzeitig wegbricht.
    """
    key = lock_key(room_id)
    try:
        _client().delete(key)
    except redis.RedisError:
        logger.warning(
            "engine_lock.release: redis-fehler fuer key=%s (TTL faellt zurueck)",
            key,
            exc_info=True,
        )
