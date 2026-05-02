"""Gemeinsame Test-Fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from heizung.config import get_settings
from heizung.main import app


@pytest.fixture(autouse=True)
def _ensure_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stellt sicher, dass ENVIRONMENT + ALLOW_DEFAULT_SECRETS in jedem
    Test gesetzt sind. ENVIRONMENT ist seit H-5 Pflichtfeld (kein Default
    in Settings), daher muss auch der Test-Run die env-Var setzen, sonst
    crasht jeder Settings()-Call ohne explicit environment-kwarg.

    Tests, die explicit ENVIRONMENT testen (z.B. K-3-Validator), nutzen
    monkeypatch.setenv/delenv und ueberschreiben damit diesen Default.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    # Settings-Cache leeren, damit nachfolgende get_settings() die
    # frischen env-Vars lesen.
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
