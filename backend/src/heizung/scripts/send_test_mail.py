r"""Verbindungstest fuer den Mailversand (Sprint 18).

Prueft die SMTP-Konfiguration, ohne einen echten Alarm auszuloesen. Gedacht
fuer den Moment nach dem Eintragen der Zugangsdaten in die ``.env`` — und
fuer den Tag, an dem sich der Hotelier fragt, ob die Alarme ueberhaupt noch
ankaemen.

Aufruf::

    python -m heizung.scripts.send_test_mail --to chef@hotel-sonnblick.at

Ohne ``--to`` geht die Nachricht an die in den Einstellungen hinterlegte
Alarm-Adresse (``global_config.alert_email``) — das ist der Normalfall, denn
genau diese Adresse soll geprueft werden.

Auf dem Server::

    docker exec deploy-api-1 python -m heizung.scripts.send_test_mail

Der Befehl schreibt **kein** Audit und beruehrt keine Wiederholungsbremse.
Er ist beliebig oft wiederholbar.

Exit-Codes: 0 = Nachricht uebergeben · 1 = nicht versandt (Grund steht in
der Ausgabe).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

# Siehe pair_devices: die App-Settings muessen ladbar sein, bevor
# ``heizung.db`` importiert wird.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung",
)

from heizung.config import get_settings  # noqa: E402
from heizung.db import SessionLocal  # noqa: E402
from heizung.models.global_config import GlobalConfig  # noqa: E402
from heizung.services import mailer  # noqa: E402

SUBJECT = "Heizung Sonnblick: Testnachricht"


def _body(recipient: str) -> str:
    jetzt = datetime.now(tz=UTC).astimezone().strftime("%d.%m.%Y %H:%M")
    return "\n".join(
        [
            "Dies ist eine Testnachricht der Heizungssteuerung.",
            "",
            f"Gesendet am {jetzt} an {recipient}.",
            "",
            "Wenn Sie diese Nachricht lesen, funktioniert der Alarm-Versand.",
            "Echte Alarme sehen anders aus: sie nennen im Betreff das betroffene",
            "Gerät und das Zimmer.",
            "",
            "Es wurde nichts geändert und nichts protokolliert.",
        ]
    )


async def _resolve_recipient(explicit: str | None) -> tuple[str | None, str]:
    """Empfaenger bestimmen. Gibt ``(adresse, herkunft)`` zurueck."""
    if explicit:
        return explicit, "aus --to"
    async with SessionLocal() as session:
        gc = await session.get(GlobalConfig, 1)
        return (gc.alert_email if gc is not None else None), "aus den Einstellungen"


def _print_config() -> None:
    """Zeigt die wirksame Konfiguration — ohne das Passwort."""
    s = get_settings()
    print("Konfiguration:")
    print(f"  Versand aktiv : {'ja' if s.smtp_enabled else 'NEIN (SMTP_ENABLED)'}")
    print(f"  Server        : {s.smtp_host or '(nicht gesetzt)'}:{s.smtp_port}")
    print(f"  Sicherheit    : {s.smtp_security}")
    print(f"  Benutzer      : {s.smtp_user or '(keiner — ohne Anmeldung)'}")
    print(f"  Passwort      : {'gesetzt' if s.smtp_password else 'NICHT gesetzt'}")
    print(f"  Absender      : {s.smtp_from or s.smtp_user or '(nicht bestimmbar)'}")
    print(f"  Zeitlimit     : {s.smtp_timeout_seconds} s")
    print()


async def _main_async(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="send_test_mail",
        description="Versendet eine Testnachricht ueber die konfigurierte SMTP-Verbindung.",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Zieladresse. Ohne Angabe die Alarm-Adresse aus den Einstellungen.",
    )
    args = parser.parse_args(argv)

    _print_config()

    recipient, herkunft = await _resolve_recipient(args.to)
    if not recipient:
        print(
            "[FEHLER] Keine Zieladresse. Entweder --to angeben oder in der "
            "Oberflaeche unter Einstellungen / Hotel eine Alarm-Email eintragen.",
            file=sys.stderr,
        )
        return 1

    print(f"Sende an {recipient} ({herkunft}) ...")
    result = mailer.send_mail(recipient=recipient, subject=SUBJECT, body=_body(recipient))

    if result.sent:
        print(f"[OK] {result.detail}")
        print()
        print(
            "Der Server hat die Nachricht angenommen. Das ist noch keine "
            "Zustellgarantie —\nbitte im Postfach nachsehen, auch im Spam-Ordner."
        )
        return 0

    print(f"[FEHLER] {result.detail}", file=sys.stderr)
    return 1


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    sys.exit(main())
