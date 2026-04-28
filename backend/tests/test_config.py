"""Settings-Validator-Tests."""

import pytest

from heizung.config import Settings


def test_defaults_work_for_development(monkeypatch: pytest.MonkeyPatch) -> None:
    # SECRET_KEY-Env entfernen, damit der echte Default greift.
    # CI exportiert SECRET_KEY fuer andere Tests; hier wollen wir den Default sehen.
    monkeypatch.delenv("SECRET_KEY", raising=False)
    s = Settings(environment="development")
    assert s.secret_key == "change-me-in-production"
    assert s.environment == "development"


def test_production_rejects_default_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(environment="production")


def test_production_accepts_explicit_secret() -> None:
    s = Settings(environment="production", secret_key="a" * 32)
    assert s.environment == "production"
