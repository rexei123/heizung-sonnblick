"""Geteilter sync-Redis-Client-Builder (Sprint 11 T5).

Ehemals ``engine_lock._client`` (Sprint 9.10 T3.5, AE-40). Wird ab T5
zusaetzlich von ``mqtt_subscriber`` (Implausible-Counter ueber
``asyncio.to_thread``) und ``health_tasks`` (Compute-Task) verwendet.

Bewusst sync und neu pro Call: ``get_settings()`` ist ``lru_cache``'t,
``redis.from_url`` baut intern einen Pool — somit teilen sich Calls
innerhalb desselben Prozesses die Connections (redis-py fork-safe
seit 4.x).
"""

from __future__ import annotations

import redis

from heizung.config import get_settings


def get_redis_client() -> redis.Redis:
    """Sync-Redis-Client mit ``socket_timeout=2``. redis-py poolt intern."""
    return redis.from_url(get_settings().redis_url, socket_timeout=2)
