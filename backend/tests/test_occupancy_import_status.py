"""Sprint 15e (AE-66) — reine Funktionstests (ohne DB).

Deckt den Zimmer-Parser, den HH:MM-Parser und die Ampel-Status-Matrix ab.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from heizung.services.occupancy_import_service import (
    compute_import_status,
    parse_hhmm,
    parse_target_room,
)

VIENNA = ZoneInfo("Europe/Vienna")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("103", "103"),
        ("52\n⇒ 101", "101"),
        ("52 => 101", "101"),
        ("12→13", "13"),
        ("  201b  ", "201b"),
        ("52\n⇒\n101", "101"),
    ],
)
def test_parse_target_room(raw: str, expected: str) -> None:
    assert parse_target_room(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("09:00", time(9, 0)), ("7:5", time(7, 5)), ("23:59", time(23, 59)), ("murks", time(9, 0))],
)
def test_parse_hhmm(raw: str, expected: time) -> None:
    assert parse_hhmm(raw) == expected


def _status(
    *,
    now_utc: datetime,
    last_success_at: datetime | None,
    today_received: bool,
) -> str:
    return compute_import_status(
        now_utc=now_utc,
        last_success_at=last_success_at,
        today_received=today_received,
        expected_by_local=time(9, 0),
        tz=VIENNA,
    )


def test_status_red_when_never() -> None:
    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    assert _status(now_utc=now, last_success_at=None, today_received=False) == "red"


def test_status_green_when_today_received() -> None:
    now = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)  # lokal 12:00, nach expected
    last = datetime(2026, 6, 6, 5, 14, tzinfo=UTC)
    assert _status(now_utc=now, last_success_at=last, today_received=True) == "green"


def test_status_green_before_expected_recent() -> None:
    # 05:00 UTC = 07:00 lokal CEST, vor 09:00; letzter Erfolg < 24 h.
    now = datetime(2026, 6, 6, 5, 0, tzinfo=UTC)
    last = datetime(2026, 6, 5, 6, 0, tzinfo=UTC)
    assert _status(now_utc=now, last_success_at=last, today_received=False) == "green"


def test_status_yellow_after_expected_no_import_today() -> None:
    # 08:00 UTC = 10:00 lokal, nach 09:00; letzter Erfolg < 24 h, heute nichts.
    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    last = datetime(2026, 6, 5, 18, 0, tzinfo=UTC)
    assert _status(now_utc=now, last_success_at=last, today_received=False) == "yellow"


def test_status_red_when_older_than_24h() -> None:
    now = datetime(2026, 6, 6, 8, 0, tzinfo=UTC)
    last = datetime(2026, 6, 5, 6, 0, tzinfo=UTC)  # > 24 h
    assert _status(now_utc=now, last_success_at=last, today_received=False) == "red"
