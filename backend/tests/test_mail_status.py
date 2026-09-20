"""Sprint 18 / T4 — Sichtbarkeit des Mailversands.

Der Punkt dieser Felder ist nicht Buchhaltung, sondern **Inbetriebnahme**.
Am Tag, an dem der Hotelier die SMTP-Werte eintraegt, ist die einzige
interessante Frage: kommt jetzt etwas an oder nicht. Bis dahin scheitert
jeder Alarm still (CLAUDE.md §5.76).

Gepinnt sind vier Zusagen:

1. Ein Erfolg setzt ``last_mail_ok_at`` und **loescht** den alten Fehler.
2. Ein Fehlschlag laesst ``last_mail_ok_at`` **stehen** — "wann lief es
   zuletzt" ueberlebt jeden spaeteren Fehlversuch.
3. Das SMTP-Passwort landet nie in ``last_mail_error``.
4. ``record_attempt`` wirft nie.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command
from heizung.models.global_config import GlobalConfig
from heizung.services import mail_status
from heizung.services.mailer import MailResult

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

T1 = datetime(2026, 9, 19, 8, 0, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 19, 9, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _migrate_db() -> None:
    if not DATABASE_URL_PRESENT:
        return
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL or "")
    await asyncio.to_thread(command.upgrade, cfg, "head")


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    if not DATABASE_URL_PRESENT:
        pytest.skip(SKIP_REASON)
    eng = create_async_engine(DATABASE_URL or "")
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        try:
            yield s
        finally:
            await s.rollback()


@pytest_asyncio.fixture
async def gc(session: AsyncSession) -> AsyncIterator[GlobalConfig]:
    """Singleton-Row mit geleerten Mail-Feldern.

    Die Row wird nicht angelegt oder geloescht — sie gehoert zum Seed und
    wird von anderen Tests mitbenutzt. Nur die drei T4-Felder werden vor
    und nach dem Test zurueckgesetzt.
    """
    row = await session.get(GlobalConfig, 1)
    if row is None:
        pytest.skip("global_config-Singleton nicht geseedet")
    row.last_mail_attempt_at = None
    row.last_mail_ok_at = None
    row.last_mail_error = None
    await session.commit()
    try:
        yield row
    finally:
        row.last_mail_attempt_at = None
        row.last_mail_ok_at = None
        row.last_mail_error = None
        await session.commit()


pytestmark = pytest.mark.asyncio


async def test_erfolg_setzt_beide_zeitstempel(session: AsyncSession, gc: GlobalConfig) -> None:
    await mail_status.record_attempt(session, MailResult(True, None, "uebergeben"), now=T1)
    await session.commit()

    assert gc.last_mail_attempt_at == T1
    assert gc.last_mail_ok_at == T1
    assert gc.last_mail_error is None


async def test_fehlschlag_setzt_nur_den_versuch(session: AsyncSession, gc: GlobalConfig) -> None:
    await mail_status.record_attempt(
        session, MailResult(False, "SMTPAuthenticationError", "535 5.7.8"), now=T1
    )
    await session.commit()

    assert gc.last_mail_attempt_at == T1
    assert gc.last_mail_ok_at is None
    assert gc.last_mail_error is not None
    # Der Kurzgrund steht vorn, damit er beim Abschneiden ueberlebt.
    assert gc.last_mail_error.startswith("SMTPAuthenticationError")
    assert "535 5.7.8" in gc.last_mail_error


async def test_erfolg_loescht_den_alten_fehler(session: AsyncSession, gc: GlobalConfig) -> None:
    """Sonst stuende nach einer Reparatur weiter die alte Ursache da."""
    await mail_status.record_attempt(session, MailResult(False, "OSError", "refused"), now=T1)
    await mail_status.record_attempt(session, MailResult(True, None, "uebergeben"), now=T2)
    await session.commit()

    assert gc.last_mail_error is None
    assert gc.last_mail_ok_at == T2


async def test_fehlschlag_laesst_den_letzten_erfolg_stehen(
    session: AsyncSession, gc: GlobalConfig
) -> None:
    """Die wichtigste Zusage: "wann lief es zuletzt" ueberlebt.

    Faellt der Mailserver aus, ist genau das die Frage — seit wann. Wuerde
    ein Fehlversuch den Zeitstempel loeschen, waere sie nicht mehr
    beantwortbar.
    """
    await mail_status.record_attempt(session, MailResult(True, None, "uebergeben"), now=T1)
    await mail_status.record_attempt(session, MailResult(False, "OSError", "refused"), now=T2)
    await session.commit()

    assert gc.last_mail_ok_at == T1
    assert gc.last_mail_attempt_at == T2
    assert gc.last_mail_error is not None


async def test_langer_fehlertext_wird_gekuerzt(session: AsyncSession, gc: GlobalConfig) -> None:
    """``last_mail_error`` ist VARCHAR(200). Ein langer Server-Text darf den
    Vermerk nicht kippen — das waere ein Beobachtungsausfall genau dann,
    wenn etwas kaputt ist."""
    await mail_status.record_attempt(session, MailResult(False, "SMTPException", "x" * 500), now=T1)
    await session.commit()

    assert gc.last_mail_error is not None
    assert len(gc.last_mail_error) <= mail_status.MAX_ERROR_LEN


async def test_wirft_nicht_wenn_das_schreiben_scheitert(monkeypatch: Any) -> None:
    """Das Protokoll ist die Beobachtung, nicht die Aufgabe. Ein Fehler hier
    darf den Alarmpfad nicht abbrechen."""

    class _KaputteSession:
        async def get(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Verbindung weg")

    # Kein raise, kein Rueckgabewert — der Aufrufer merkt nichts.
    await mail_status.record_attempt(
        _KaputteSession(),  # type: ignore[arg-type]
        MailResult(True, None, "uebergeben"),
        now=T1,
    )


async def test_smtp_passwort_erreicht_die_spalte_nicht(
    session: AsyncSession, gc: GlobalConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Die Kette als Ganzes, nicht nur ein Glied davon.

    ``mailer`` entfernt das Passwort aus dem Fehlertext (``_redact``), und
    ``mail_status`` schreibt genau diesen Text in eine Spalte, die spaeter
    in der Oberflaeche steht. Waere die Redaktion je weg, stuende das
    Passwort auf dem Bildschirm — nach dem Screenshot vom 19.09. (B-18-2)
    ist das der Weg, den es nicht geben darf.

    Deshalb laeuft dieser Test durch ``send_mail`` statt ein ``MailResult``
    von Hand zu bauen: nur so faellt ein Bruch zwischen beiden Modulen auf.
    """
    import smtplib

    from heizung.services import mailer

    geheim = "streng-geheimes-passwort-xyz"

    class _Settings:
        smtp_enabled = True
        smtp_host = "mail.example.com"
        smtp_port = 587
        smtp_user = "alarm@example.com"
        smtp_password = geheim
        smtp_from = ""
        smtp_security = "starttls"
        smtp_timeout_seconds = 20

    monkeypatch.setattr(mailer, "get_settings", lambda: _Settings())

    def _explodiert(*args: Any, **kwargs: Any) -> None:
        raise smtplib.SMTPException(f"auth failed with password {geheim}")

    monkeypatch.setattr(smtplib, "SMTP", _explodiert)

    result = mailer.send_mail(recipient="chef@example.com", subject="T", body="B")
    await mail_status.record_attempt(session, result, now=T1)
    await session.commit()

    assert gc.last_mail_error is not None
    assert geheim not in gc.last_mail_error
    assert mailer.REDACTED in gc.last_mail_error
