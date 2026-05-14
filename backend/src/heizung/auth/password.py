"""Password-Hashing (Sprint 9.17, AE-50).

bcrypt mit work-factor 12 (~250 ms pro Hash auf typischer CPU).
Brute-Force-Schutz auf Login wird durch slowapi-Rate-Limit ergaenzt
(siehe ``api/v1/auth.py``).

Direkter ``bcrypt``-Backend statt ``passlib``-Wrapper: passlib 1.7.4
ist unmaintained seit 2020-10 und inkompatibel mit bcrypt >= 4.1
(``detect_wrap_bug``-Init-Pfad triggert ValueError fuer >72-Byte-
Secrets). Direkter ``bcrypt``-Call ist robuster und API-leichter.
Siehe ADR AE-50 / T3-Abweichung.

bcrypt selbst beschraenkt den Eingabe-Klartext auf 72 Bytes; laengere
Passwoerter werden zurueckgewiesen (kein Silent-Truncate). Wir lassen
das nach aussen via ``ValueError`` durch, damit ein zu langes Passwort
nicht unbemerkt ein kuerzeres mit hasht.
"""

from __future__ import annotations

import bcrypt

_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    """bcrypt-Hash erzeugen. Klartext nie loggen."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode(
        "utf-8"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Verifiziert Klartext gegen bcrypt-Hash. Konstantzeit per
    ``bcrypt.checkpw``."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Defekter/legacy Hash oder zu langes Klartext-Passwort
        # (>72 Bytes) — kein Login.
        return False
