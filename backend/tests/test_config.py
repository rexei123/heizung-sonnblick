"""Settings-Validator-Tests."""

import pytest

from heizung.config import Settings


def test_defaults_work_for_development() -> None:
    s = Settings(environment="development")
    assert s.secret_key == "change-me-in-production"
    assert s.environment == "development"


def test_production_rejects_default_secret() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(environment="production")


def test_production_accepts_explicit_secret() -> None:
    s = Settings(environment="production", secret_key="a" * 32)
    assert s.environment == "production"
