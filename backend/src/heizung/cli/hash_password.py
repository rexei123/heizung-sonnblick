"""bcrypt-Password-Hasher (Sprint 9.17, AE-50, AE-5 Bootstrap).

Hilfsskript zum Erzeugen des ``INITIAL_ADMIN_PASSWORD_HASH``-Werts
fuer die ENV-Variable.

Aufruf::

    python -m heizung.cli.hash_password '<klartext>'

Gibt den bcrypt-Hash auf stdout aus. Klartext darf NICHT geloggt
oder in Files persistiert werden.
"""

from __future__ import annotations

import sys

from heizung.auth.password import hash_password


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("Usage: python -m heizung.cli.hash_password '<klartext>'\n")
        return 2
    password = sys.argv[1]
    if not password:
        sys.stderr.write("Passwort darf nicht leer sein\n")
        return 2
    sys.stdout.write(hash_password(password) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
