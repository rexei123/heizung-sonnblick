"""Settings-Validator-Tests."""

import pytest

from heizung.config import GEHAEUSE_TOTBAND_K, Settings


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


def test_environment_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """QA-Audit H-5: ENVIRONMENT ist Pflichtfeld, kein stiller Default."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    # _model_config ignoriert .env-Datei nicht komplett, daher ein
    # Cwd-Wechsel nicht moeglich; pydantic raised wenn weder kwarg
    # noch env_file noch env-Var einen Wert liefert.
    with pytest.raises(ValueError, match="environment"):
        Settings(_env_file=None)


def test_environment_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Literal verhindert Tippfehler wie 'prod' oder 'dev'."""
    monkeypatch.setenv("ALLOW_DEFAULT_SECRETS", "1")
    with pytest.raises(ValueError):
        Settings(environment="prod")


def test_gehaeuse_vorgaben_stehen_wie_vereinbart() -> None:
    """Die Karte faerbt ab 40, die Mail kommt ab 50, entwarnt wird unter 45.

    Die Zahlen stehen hier, damit eine Aenderung an den Vorgaben eine
    bewusste ist — der Abstand zwischen Mail und Entwarnung ist das
    Totband und entscheidet, ob ein Geraet im Normalbetrieb taeglich
    meldet (Entscheidung vom 21.11.2026).
    """
    s = Settings(environment="test", secret_key="b" * 32)
    assert s.relay_gehaeusetemperatur_alarm == 40
    assert s.relay_gehaeusetemperatur_mail == 50
    assert s.relay_gehaeusetemperatur_mail - GEHAEUSE_TOTBAND_K == 45


def test_mail_schwelle_unter_der_karten_schwelle_wird_abgewiesen() -> None:
    """Sonst kaeme die Mail, bevor die Oberflaeche etwas zeigt."""
    with pytest.raises(ValueError, match="RELAY_GEHAEUSETEMPERATUR_MAIL"):
        Settings(
            environment="test",
            secret_key="b" * 32,
            relay_gehaeusetemperatur_alarm=40,
            relay_gehaeusetemperatur_mail=39,
        )


def test_mail_schwelle_im_totband_wird_abgewiesen() -> None:
    """Eine Episode, die nicht enden kann, ist schlimmer als keine.

    Bei einer Mail-Schwelle von 5 oder weniger liegt die Entwarnung bei
    null oder darunter — sie wird nie erreicht, und das Geraet bekommt
    nie einen zweiten Alarm.
    """
    with pytest.raises(ValueError, match="Totband"):
        Settings(
            environment="test",
            secret_key="b" * 32,
            relay_gehaeusetemperatur_alarm=1,
            relay_gehaeusetemperatur_mail=GEHAEUSE_TOTBAND_K,
        )
