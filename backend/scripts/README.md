# Backend Smoke-Skripte

Hand-Verify-Skripte fuer Mechaniken, die sich nicht sinnvoll als
Pytest-Test ausdruecken lassen (echte Redis-/Celery-Last, parallele
Worker, Burst-Verhalten). Laufen ausserhalb der Test-Suite und sind
nicht in CI eingebunden.

## smoke_engine_lock.py (Sprint 9.10 T3.5)

Verifiziert AE-40 (Redis-SETNX-Lock fuer ``evaluate_room``):

1. 10 parallele ``engine_lock.try_acquire(room_id=99)`` -> exakt
   1 True, 9 False (echtes SETNX-Verhalten).
2. 5 parallele ``evaluate_room.delay(room_id=99999)`` -> 1 sofort
   verarbeitet (``status=skipped_no_room``), 4 mit
   ``status=lock_busy_retriggered``; Re-Trigger laufen nach 5 s
   Countdown durch.

Voraussetzung: Redis (compose) + Celery-Worker laufen.
ENVIRONMENT/DATABASE_URL gesetzt wie in den Pre-Push-Skripten.

```powershell
# PowerShell (lokal), Backend-Venv aktiviert:
cd C:\Users\User\dev\heizung-sonnblick\backend
$env:ENVIRONMENT = "test"
$env:DATABASE_URL = "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung"
.\.venv\Scripts\python.exe scripts\smoke_engine_lock.py
```
