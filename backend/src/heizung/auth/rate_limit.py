"""Rate-Limit-Singleton (Sprint 9.17, AE-50 / R3).

slowapi-Limiter wird einmal modul-global instanziiert, damit die
Route-Dekoratoren in ``api/v1/auth.py`` und der Exception-Handler in
``main.py`` dieselbe Instance teilen. Key: Client-IP.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
