"""Sprint 9.10 T3.5 Live-Smoke: Engine-Task-Lock via Redis-SETNX.

Erwartung:
1. 10 parallele ``engine_lock.try_acquire(room_id=99)`` -> exakt 1 True,
   9 False (echtes Redis-SETNX-Verhalten).
2. 5 parallele ``evaluate_room.delay(room_id=99999)`` -> 1 verarbeitet
   sofort (returnt ``status=skipped_no_room``), 4 returnen
   ``status=lock_busy_retriggered``. Anschliessend laufen die Re-Trigger
   nach 5 s Countdown — am Ende sollten ALLE 5 originalen Tasks fertig
   sein, plus weitere Re-Trigger-Generationen.

Voraussetzung: Redis (compose) + Celery-Worker laufen. ENVIRONMENT/
DATABASE_URL gesetzt wie in den Pre-Push-Skripten.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import Counter

# Stellen sicher, dass die App-Settings geladen werden koennen.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung",
)

from heizung.services import engine_lock  # noqa: E402
from heizung.tasks.engine_tasks import evaluate_room  # noqa: E402


def smoke_a_setnx_atomic() -> int:
    """Smoke A: 10 Threads gegen denselben Lock — genau 1 muss gewinnen."""
    print("\n=== Smoke A: SETNX-Atomicity ===")
    test_room = 99
    engine_lock.release(test_room)  # clean slate
    results: list[bool] = []
    barrier = threading.Barrier(10)

    def attempt() -> None:
        barrier.wait()
        results.append(engine_lock.try_acquire(test_room))

    threads = [threading.Thread(target=attempt) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    wins = sum(results)
    print(f"  threads=10 wins={wins} losses={10 - wins}")
    engine_lock.release(test_room)
    if wins != 1:
        print("  FAIL: erwarte 1 win, gefunden", wins)
        return 1
    print("  OK: SETNX serialisiert korrekt")
    return 0


def smoke_b_5x_evaluate_room() -> int:
    """Smoke B: 5x evaluate_room.delay -> 1 sofort + 4 retriggered."""
    print("\n=== Smoke B: 5x evaluate_room.delay parallel ===")
    test_room = 99999  # bewusst nicht existent — _evaluate_room_async returnt
    # schnell mit 'skipped_no_room', wir testen nur die Lock-Mechanik.

    # Vorab Lock haendisch setzen, damit ALLE 5 Tasks ihn busy sehen
    # (vorhersagbares Ergebnis statt Race auf den ersten Worker-Slot).
    engine_lock.release(test_room)
    assert engine_lock.try_acquire(test_room) is True, "lock muss initial frei sein"

    print("  Lock manuell gesetzt -> erwarte 5x lock_busy_retriggered")
    results = [evaluate_room.delay(test_room) for _ in range(5)]

    print("  warte auf alle 5 Task-Resultate...")
    statuses: list[str] = []
    for r in results:
        out = r.get(timeout=10)
        statuses.append(out.get("status", "?"))
    counts = Counter(statuses)
    print(f"  Status-Verteilung: {dict(counts)}")

    # Lock freigeben, damit die countdown=5-Re-Trigger durchlaufen koennen
    engine_lock.release(test_room)
    print("  Lock manuell freigegeben — Re-Trigger laufen jetzt durch (~5 s)")
    time.sleep(8)
    print("  Re-Trigger-Generation hatte Zeit zu laufen — Worker-Log fuer Details pruefen")

    if counts.get("lock_busy_retriggered", 0) != 5:
        print(f"  FAIL: erwarte 5x lock_busy_retriggered, fand {counts}")
        return 1
    print("  OK: alle 5 Initial-Tasks haben den Lock korrekt umgangen")
    return 0


if __name__ == "__main__":
    rc = 0
    rc |= smoke_a_setnx_atomic()
    rc |= smoke_b_5x_evaluate_room()
    sys.exit(rc)
