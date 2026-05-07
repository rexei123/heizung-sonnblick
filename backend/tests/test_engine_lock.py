"""Sprint 9.10 T3.5 — Engine-Task-Lock-Tests.

Deckt:
- ``engine_lock.try_acquire`` / ``release`` als Pure-Helper-Tests
  (FakeRedis-Mock, kein Daemon noetig).
- ``evaluate_room`` Task-Wrapper: Lock acquired -> Eval laeuft +
  Lock freigegeben; Lock busy -> apply_async-Retrigger + KEIN Eval;
  Exception -> Lock dennoch freigegeben.
- Verschiedene room_ids -> beide laufen nebeneinander.

Concurrent-Test mit echtem Redis ist im T3.5-Live-Smoke gegen den
Compose-Stack abgedeckt (siehe Sprint-Bericht), nicht hier.
"""

from __future__ import annotations

from typing import Any

import pytest

from heizung.services import engine_lock
from heizung.tasks import engine_tasks

# ---------------------------------------------------------------------------
# FakeRedis: nur die zwei Operationen, die engine_lock nutzt.
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimaler In-Memory-Stand-in fuer ``redis.Redis``.

    Implementiert nur ``set(..., nx=True, ex=...)`` und ``delete``.
    TTL wird ignoriert — Tests setzen den Lock manuell zurueck wo noetig.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,  # noqa: ARG002 - TTL irrelevant fuer Test
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key: str) -> int:
        if key in self.store:
            del self.store[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(engine_lock, "_client", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# engine_lock — Pure-Helper-Tests
# ---------------------------------------------------------------------------


def test_try_acquire_returns_true_for_free_room(fake_redis: _FakeRedis) -> None:
    assert engine_lock.try_acquire(42) is True
    assert "engine:eval:lock:42" in fake_redis.store


def test_try_acquire_returns_false_for_locked_room(fake_redis: _FakeRedis) -> None:
    fake_redis.store["engine:eval:lock:42"] = "1"
    assert engine_lock.try_acquire(42) is False


def test_release_removes_lock(fake_redis: _FakeRedis) -> None:
    fake_redis.store["engine:eval:lock:42"] = "1"
    engine_lock.release(42)
    assert "engine:eval:lock:42" not in fake_redis.store


def test_locks_are_room_scoped(fake_redis: _FakeRedis) -> None:
    """Verschiedene room_ids haben unabhaengige Locks."""
    assert engine_lock.try_acquire(1) is True
    assert engine_lock.try_acquire(2) is True
    assert "engine:eval:lock:1" in fake_redis.store
    assert "engine:eval:lock:2" in fake_redis.store


# ---------------------------------------------------------------------------
# evaluate_room Task-Wrapper — Lock-Verhalten
# ---------------------------------------------------------------------------


def test_evaluate_room_runs_when_lock_free(
    fake_redis: _FakeRedis,  # noqa: ARG001 - Fixture aktiviert Mock
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lock akquiriert -> _evaluate_room_async laeuft, Lock danach frei."""
    impl_calls: list[int] = []

    def fake_impl(room_id: int) -> dict[str, Any]:
        impl_calls.append(room_id)
        return {"room_id": room_id, "status": "ok"}

    async def _async_wrapper(room_id: int) -> dict[str, Any]:
        return fake_impl(room_id)

    monkeypatch.setattr(engine_tasks, "_evaluate_room_async", _async_wrapper)

    apply_calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        engine_tasks.evaluate_room,
        "apply_async",
        lambda *args, **kw: apply_calls.append((args, kw)),
    )

    result = engine_tasks.evaluate_room.run(7)

    assert result == {"room_id": 7, "status": "ok"}
    assert impl_calls == [7]
    assert apply_calls == [], "kein Re-Trigger wenn Lock frei"
    assert engine_lock.try_acquire(7) is True, "Lock muss nach Eval freigegeben sein"


def test_evaluate_room_skips_when_lock_busy(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vorab gehaltener Lock -> Eval skippt, apply_async wird gerufen."""
    fake_redis.store["engine:eval:lock:7"] = "1"

    impl_calls: list[int] = []

    async def _async_wrapper(room_id: int) -> dict[str, Any]:
        impl_calls.append(room_id)
        return {}

    monkeypatch.setattr(engine_tasks, "_evaluate_room_async", _async_wrapper)

    apply_calls: list[dict[str, Any]] = []

    def _capture(task_args: tuple[Any, ...], **kwargs: Any) -> None:
        apply_calls.append({"args": task_args, "kwargs": kwargs})

    monkeypatch.setattr(engine_tasks.evaluate_room, "apply_async", _capture)

    result = engine_tasks.evaluate_room.run(7)

    assert result["status"] == "lock_busy_retriggered"
    assert result["retrigger_in_s"] == engine_tasks.EVAL_LOCK_RETRIGGER_DELAY_S
    assert impl_calls == [], "Eval-Impl darf NICHT laufen wenn Lock busy"
    assert apply_calls == [
        {
            "args": (7,),
            "kwargs": {"countdown": engine_tasks.EVAL_LOCK_RETRIGGER_DELAY_S},
        }
    ], f"erwarte 1 apply_async((7,), countdown=5), gefunden {apply_calls}"
    # Lock bleibt unangetastet — wer ihn hielt, gibt ihn frei.
    assert fake_redis.store.get("engine:eval:lock:7") == "1"


def test_evaluate_room_releases_lock_on_exception(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exception in der Eval-Pipeline -> Lock dennoch freigegeben (try/finally)."""

    async def _boom(room_id: int) -> dict[str, Any]:  # noqa: ARG001
        raise RuntimeError("simulated engine crash")

    monkeypatch.setattr(engine_tasks, "_evaluate_room_async", _boom)
    monkeypatch.setattr(
        engine_tasks.evaluate_room,
        "apply_async",
        lambda *_a, **_k: None,
    )

    with pytest.raises(RuntimeError, match="simulated engine crash"):
        engine_tasks.evaluate_room.run(11)

    assert "engine:eval:lock:11" not in fake_redis.store, (
        "Lock muss auch bei Exception freigegeben werden"
    )


def test_evaluate_room_different_rooms_no_blocking(
    fake_redis: _FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sequenzielle Calls fuer verschiedene rooms blockieren sich nicht.

    Mock-basiert; ein echter Concurrent-Test mit Threads gegen Redis ist
    im Live-Smoke abgedeckt (eigener Sprint-Bericht-Schritt).
    """
    impl_calls: list[int] = []

    async def _async_wrapper(room_id: int) -> dict[str, Any]:
        # Lock ist fuer den gerade evaluierten Raum gehalten —
        # ein anderer Raum darf trotzdem akquirieren.
        assert engine_lock.try_acquire(room_id + 100) is True
        impl_calls.append(room_id)
        return {"room_id": room_id, "status": "ok"}

    monkeypatch.setattr(engine_tasks, "_evaluate_room_async", _async_wrapper)
    monkeypatch.setattr(
        engine_tasks.evaluate_room,
        "apply_async",
        lambda *_a, **_k: None,
    )

    engine_tasks.evaluate_room.run(1)
    engine_tasks.evaluate_room.run(2)

    assert impl_calls == [1, 2]
    # fake_redis hat die jeweils inneren Acquire (room+100) noch im Store —
    # die outer Locks sind gefreed. Smoke-Check:
    assert "engine:eval:lock:1" not in fake_redis.store
    assert "engine:eval:lock:2" not in fake_redis.store
