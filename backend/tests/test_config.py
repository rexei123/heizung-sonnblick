"""Settings-Validator-Tests."""

import pytest

from heizung.config import Settings


def test_default_secret_blocked_in_any_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QA-Audit K-3: Default-SECRET_KEY blockt in development, test, production."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("ALLOW_DEFAULT_SECRETS", raising=False)

    for env in ("development", "test", "production"):
        with pytest.raises(ValueError, match="SECRET_KEY"):
            Settings(environment=env)


def test_explicit_secret_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mit echtem Secret ist development OK, test OK, production OK."""
    monkeypatch.delenv("ALLOW_DEFAULT_SECRETS", raising=False)
    s = Settings(environment="development", secret_key="a" * 32)
    assert s.secret_key == "a" * 32


def test_allow_default_secrets_overrides_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lokal-Dev-Backdoor: ALLOW_DEFAULT_SECRETS=1 erlaubt Default-Secret."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    s = Settings(environment="development")
    assert s.secret_key == "change-me-in-production"


def test_production_accepts_explicit_secret() -> None:
    s = Settings(environment="production", secret_key="a" * 32)
    assert s.environment == "production"
