"""H-6 T10 — die Erinnerung an einen gesetzten Rueckfallpunkt.

**Was auf dem Spiel steht.** Ein ``PIN_SHA`` haelt den Server auf einem
Commit und zieht keine Merges mehr. Das ist der Zweck — und wer ihn
vergisst, entwickelt wochenlang gegen einen Server, der nichts davon
mitbekommt. Die Erinnerung ist der einzige Melder dafuer.

Ein Melder, der zu oft kommt, wird ignoriert (§5.79); einer, der nie kommt,
ist von keinem Melder nicht zu unterscheiden (§5.76). Beide Richtungen sind
hier gepinnt:

* **Vor sieben Tagen keine Mail** — sonst kaeme sie mitten im Fix, fuer den
  der Pin gesetzt wurde.
* **Nach sieben Tagen eine Mail**, und danach **hoechstens woechentlich**.
* **Die Uhr startet bei einem Pin-Wechsel nicht neu** — sonst koennte man
  die Erinnerung beliebig hinausschieben, indem man neu pinnt.
* **Ein geleerter Pin loescht die Uhr** — ``PIN_SHA=`` ist kein Pin, und der
  Rueckweg aus RUNBOOK §10u Schritt 6 leert die Zeile, statt sie zu
  entfernen.
* **Der Text nennt den Weg zurueck.** Eine Erinnerung ohne Handgriff ist
  eine Beunruhigung.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
from heizung.config import get_settings
from heizung.models.global_config import GlobalConfig
from heizung.services import alert_throttle, mailer, pin_reminder

DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE_URL_PRESENT = bool(DATABASE_URL)
SKIP_REASON = "DATABASE_URL nicht gesetzt - DB-Tests brauchen Test-DB"

JETZT = datetime(2026, 10, 9, 8, 0, 0, tzinfo=UTC)
PIN = "805c31c"
PIN_NEU = "85125ae"


# ---------------------------------------------------------------------------
# Huelle
# ---------------------------------------------------------------------------


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
    """Singleton-Row mit geleerter Pin-Uhr und einem Empfaenger.

    Die Row gehoert zum Seed und wird nicht angelegt oder geloescht — nur
    die Felder, die dieser Test anfasst, werden vor und nach dem Lauf
    zurueckgesetzt (Vorbild ``test_mail_status.py``).
    """
    row = await session.get(GlobalConfig, 1)
    if row is None:
        pytest.skip("global_config-Singleton nicht geseedet")
    vorher_mail = row.alert_email
    row.pin_sha_seen = None
    row.pin_sha_seen_at = None
    row.alert_email = "alarm@example.invalid"
    await session.commit()
    try:
        yield row
    finally:
        row.pin_sha_seen = None
        row.pin_sha_seen_at = None
        row.alert_email = vorher_mail
        await session.commit()


class _Postfach:
    """Sammelt, was ``send_mail`` bekommen haette."""

    def __init__(self) -> None:
        self.mails: list[dict[str, str]] = []

    def __call__(self, *, recipient: str | None, subject: str, body: str) -> mailer.MailResult:
        self.mails.append({"recipient": recipient or "", "subject": subject, "body": body})
        return mailer.MailResult(True, None, "Testzustellung")


@pytest.fixture
def postfach(monkeypatch: pytest.MonkeyPatch) -> _Postfach:
    p = _Postfach()
    monkeypatch.setattr(pin_reminder.mailer, "send_mail", p)
    return p


@pytest.fixture
def bremse_offen(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int]]:
    """``should_send`` sagt immer ja und protokolliert die Frage.

    Die echte Bremse laeuft ueber Redis, und Redis fehlt im lokalen Lauf —
    ``should_send`` gibt dann absichtlich ``True`` zurueck (eine verpasste
    Alarm-Mail ist teurer als eine doppelte). Damit waere der Zustand aber
    nicht pruefbar: hier wird die Frage selbst zum Pruefgegenstand.
    """
    gefragt: list[tuple[str, str, int]] = []

    def _ja(kind: str, subject: str, *, ttl_s: int) -> bool:
        gefragt.append((kind, subject, ttl_s))
        return True

    monkeypatch.setattr(pin_reminder.alert_throttle, "should_send", _ja)
    return gefragt


def _pin(monkeypatch: pytest.MonkeyPatch, wert: str | None) -> None:
    """Setzt ``PIN_SHA`` in der Umgebung, wie ``env_file`` es tut."""
    if wert is None:
        monkeypatch.delenv("PIN_SHA", raising=False)
    else:
        monkeypatch.setenv("PIN_SHA", wert)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _settings_sauber() -> AsyncIterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# 1. Der leere Pin ist kein Pin
# ---------------------------------------------------------------------------


async def test_leerer_pin_ist_kein_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PIN_SHA=`` nach Schritt 6 — ohne diese Normalisierung liefe die
    Erinnerung nach dem Loesen weiter.

    Der Rueckweg leert die Zeile, statt sie zu entfernen (RUNBOOK §10u
    Schritt 6 nutzt ``sed`` auf den Wert). Das Skript liest dann einen
    leeren String, und ``""`` waere ein wahrheitsfaehiger Zustand.
    """
    _pin(monkeypatch, "")
    assert get_settings().pin_sha is None

    _pin(monkeypatch, "  805c31c  ")
    assert get_settings().pin_sha == "805c31c"


# ---------------------------------------------------------------------------
# 2. Die Uhr
# ---------------------------------------------------------------------------


async def test_erster_lauf_startet_die_uhr_ohne_mail(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin gerade gesetzt: Uhr startet, **keine** Mail.

    Die Mail jetzt waere das Gegenteil einer Erinnerung — der Pin wurde
    vor Minuten gesetzt, der Grund liegt auf dem Tisch.
    """
    _pin(monkeypatch, PIN)

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "uhr_gestartet"
    assert gc.pin_sha_seen == PIN
    assert gc.pin_sha_seen_at == JETZT
    assert postfach.mails == []


async def test_vor_sieben_tagen_keine_mail(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sechs Tage und 23 Stunden: noch nichts.

    Die Grenze wird knapp geprueft, nicht grosszuegig — ein Melder, der
    einen Tag zu frueh kommt, verliert seine Glaubwuerdigkeit genauso wie
    einer, der zu spaet kommt (§5.79).
    """
    _pin(monkeypatch, PIN)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=6, hours=23)

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "laeuft"
    assert bericht["tage"] == 6
    assert postfach.mails == []


async def test_nach_sieben_tagen_kommt_die_mail(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    bremse_offen: list[tuple[str, str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sieben Tage: Mail an die Alarm-Adresse, mit Woche als Rhythmus."""
    _pin(monkeypatch, PIN)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=7)

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "erinnert"
    assert bericht["tage"] == 7
    assert len(postfach.mails) == 1
    assert postfach.mails[0]["recipient"] == "alarm@example.invalid"
    # Der Rhythmus danach ist eine Woche — nicht sechs Tage, nicht zwei.
    assert bremse_offen == [
        (alert_throttle.KIND_PIN_ACTIVE, alert_throttle.SUBJECT_PIN_ACTIVE, 7 * 24 * 3600)
    ]


async def test_versand_wird_protokolliert(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    bremse_offen: list[tuple[str, str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pflicht fuer jeden Alarmweg: ``mail_status.record_attempt``.

    Ohne diese Zeile waere der neue Weg unbeobachtet, und wer nachsieht,
    warum keine Mail kam, sieht den Zustand eines **anderen** Alarms
    (Docstring von ``services/mail_status``).
    """
    _pin(monkeypatch, PIN)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=9)
    gc.last_mail_attempt_at = None
    gc.last_mail_ok_at = None

    await pin_reminder.run_pin_reminder(session, now=JETZT)
    await session.commit()

    assert gc.last_mail_attempt_at is not None
    assert gc.last_mail_ok_at is not None


# ---------------------------------------------------------------------------
# 3. Pin-Wechsel verschiebt nichts
# ---------------------------------------------------------------------------


async def test_pin_wechsel_startet_die_uhr_nicht_neu(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    bremse_offen: list[tuple[str, str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin wandert von einem Commit zum naechsten — die Mail kommt trotzdem.

    Gemessen wird "der Server folgt dem Branch nicht", und das haelt ueber
    einen Pin-Wechsel hinweg an. Startete die Uhr neu, koennte man die
    Erinnerung beliebig hinausschieben, ohne den Zustand zu beenden.
    """
    _pin(monkeypatch, PIN_NEU)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=8)

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "erinnert"
    assert bericht["tage"] == 8
    # Der SHA wird nachgezogen, damit die Mail den aktuellen Stand nennt.
    assert gc.pin_sha_seen == PIN_NEU
    assert gc.pin_sha_seen_at == JETZT - timedelta(days=8)
    assert PIN_NEU in postfach.mails[0]["body"]


# ---------------------------------------------------------------------------
# 4. Die Bremse
# ---------------------------------------------------------------------------


async def test_zweiter_lauf_in_derselben_woche_bremst(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der Task laeuft stuendlich — ohne Bremse waeren das 168 Mails je Woche."""
    _pin(monkeypatch, PIN)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=10)
    monkeypatch.setattr(
        pin_reminder.alert_throttle,
        "should_send",
        lambda kind, subject, *, ttl_s: False,  # noqa: ARG005 - Attrappe
    )

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "gebremst"
    assert postfach.mails == []


# ---------------------------------------------------------------------------
# 5. Der Rueckweg
# ---------------------------------------------------------------------------


async def test_geloester_pin_loescht_die_uhr(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nach Schritt 6: Uhr weg, Bremse frei.

    Die Bremse muss mit — sonst haengt die erste Mail der **naechsten**
    Pin-Periode an einem Schluessel aus der vorigen.
    """
    _pin(monkeypatch, None)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=20)
    freigegeben: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pin_reminder.alert_throttle,
        "reset",
        lambda kind, subject: freigegeben.append((kind, subject)),
    )

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "kein_pin"
    assert gc.pin_sha_seen is None
    assert gc.pin_sha_seen_at is None
    assert freigegeben == [(alert_throttle.KIND_PIN_ACTIVE, alert_throttle.SUBJECT_PIN_ACTIVE)]
    assert postfach.mails == []


async def test_kein_pin_und_keine_uhr_ist_still(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der Normalfall, 8760 Laeufe im Jahr: nichts schreiben, nichts melden."""
    _pin(monkeypatch, None)
    geschrieben: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pin_reminder.alert_throttle,
        "reset",
        lambda kind, subject: geschrieben.append((kind, subject)),
    )

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "kein_pin"
    # Kein ``reset`` im Normalfall: der Task soll nicht jede Stunde eine
    # Redis-Loeschung schicken, um nichts zu tun.
    assert geschrieben == []


# ---------------------------------------------------------------------------
# 6. Ohne Empfaenger
# ---------------------------------------------------------------------------


async def test_ohne_empfaenger_keine_mail_aber_ein_hinweis(
    session: AsyncSession,
    gc: GlobalConfig,
    postfach: _Postfach,
    bremse_offen: list[tuple[str, str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keine Alarm-Adresse: kein Versand, aber der Zustand steht im Bericht.

    Still durchlaufen waere das Fehlerbild aus §5.76 — ein Alarmweg, dessen
    Ausfall nur bemerkt, wer zufaellig hinsieht.
    """
    _pin(monkeypatch, PIN)
    gc.pin_sha_seen = PIN
    gc.pin_sha_seen_at = JETZT - timedelta(days=8)
    gc.alert_email = None

    bericht = await pin_reminder.run_pin_reminder(session, now=JETZT)

    assert bericht["aktion"] == "kein_empfaenger"
    assert bericht["tage"] == 8
    assert postfach.mails == []


# ---------------------------------------------------------------------------
# 7. Der Text
# ---------------------------------------------------------------------------


async def test_text_nennt_stand_folge_und_rueckweg() -> None:
    """Eine Erinnerung ohne Handgriff ist eine Beunruhigung.

    Geprueft wird nicht die Formulierung, sondern dass die drei Dinge
    drinstehen, die der Leser um 22 Uhr braucht: was gilt, was es
    bedeutet, und wie er es beendet.
    """
    body = pin_reminder._body(pin=PIN, tage=9, seit="30.09.2026")

    assert "9 Tagen" in body
    assert "30.09.2026" in body
    assert PIN in body
    # Die Folge, nicht die Mechanik: "zieht keine Merges" ist das, was man
    # im Betrieb merkt.
    assert "keine Merges" in body
    # Der Weg zurueck, mit Fundstelle.
    assert "§10u" in body
    assert "Schritt 6" in body
    # Und die Einordnung: Entscheidung, nicht Fehler.
    assert "kein Fehler" in body


async def test_datum_steht_in_ortszeit() -> None:
    """Ein UTC-Zeitstempel kurz vor Mitternacht ist in Wien schon morgen.

    §5.74-Familie: ein Kalendertag, der aus einem Zeitstempel entsteht,
    muss durch die Hotel-Zeitzone — sonst nennt die Mail den Vortag.
    """
    kurz_vor_mitternacht = datetime(2026, 9, 30, 22, 30, 0, tzinfo=UTC)

    assert pin_reminder._lokales_datum(kurz_vor_mitternacht, "Europe/Vienna") == "01.10.2026"
    # Unbekannte Zone darf nichts kippen — Vorgabe greift.
    assert pin_reminder._lokales_datum(kurz_vor_mitternacht, "Mars/Olympus") == "01.10.2026"


# ---------------------------------------------------------------------------
# 8. Der Beat-Slot
# ---------------------------------------------------------------------------


async def test_task_ist_stuendlich_eingeplant() -> None:
    """Kein fester Tages-Slot (§5.79) und registriert — sonst laeuft nichts.

    Der zweite Teil ist der wichtigere: ein Task, der in ``include`` fehlt,
    wird vom Worker nicht gefunden, und ``beat`` schickt ihn ins Leere.
    """
    from celery.schedules import crontab

    from heizung.celery_app import app

    eintrag: dict[str, Any] = app.conf.beat_schedule["pin-reminder-hourly"]
    assert eintrag["task"] == "heizung.check_pin_reminder"
    assert eintrag["schedule"] == crontab(minute=40)
    assert "heizung.tasks.pin_reminder_tasks" in app.conf.include
