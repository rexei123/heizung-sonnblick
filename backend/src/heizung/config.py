"""Anwendungs-Settings.

Lädt Konfiguration aus Umgebungsvariablen bzw. ``.env``. Alle Felder sind
typisiert. Ein Startup-Validator verhindert, dass das System mit
Standard-Secrets in irgendeinem Modus laeuft (QA-Audit K-3).

Lokale Entwickler koennen die Validierung gezielt deaktivieren:
  ALLOW_DEFAULT_SECRETS=1 (nur fuer reine Dev-Maschine)
"""

import os
from functools import lru_cache
from typing import Final, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default-Werte, die NIE in einem produktiven Setup landen duerfen.
# Bei Aenderung hier auch die .env.example aktualisieren.
_DEFAULT_SECRET_KEY: Final[str] = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Laufzeit ---
    # ENVIRONMENT ist Pflichtfeld (QA-Audit H-5): kein Default, damit
    # Server- oder Container-Setups nie versehentlich als "development"
    # laufen, wenn die env-Var fehlt. Lokal in `.env` setzen, im Test-
    # Run via conftest-Fixture, im Container via env_file.
    environment: Literal["development", "test", "production"]
    log_level: str = "INFO"
    secret_key: str = Field(default=_DEFAULT_SECRET_KEY, min_length=16)

    # --- Infrastruktur ---
    database_url: str = "postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung"
    redis_url: str = "redis://localhost:6379/0"

    # --- Wetter (Hotel Sonnblick Kaprun) ---
    openmeteo_latitude: float = 47.272
    openmeteo_longitude: float = 12.753

    # --- LoRaWAN / MQTT (Sprint 5) ---
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str | None = None
    mqtt_password: str | None = None
    mqtt_topic: str = "application/+/device/+/event/up"
    mqtt_client_id: str = "heizung-api-subscriber"
    mqtt_enabled: bool = True

    @model_validator(mode="after")
    def _reject_default_secrets(self) -> "Settings":
        """QA-Audit K-3: Default-Secrets in JEDEM Modus blockieren.

        Lokale Dev-Maschine kann via ALLOW_DEFAULT_SECRETS=1 abkuerzen.
        Server-Setup MUSS echte Secrets setzen.
        """
        if os.getenv("ALLOW_DEFAULT_SECRETS") == "1":
            return self

        if self.secret_key == _DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY ist auf Default-Wert. Echtes Secret setzen "
                "(`openssl rand -hex 32`) oder ALLOW_DEFAULT_SECRETS=1 "
                "fuer lokale Dev-Maschine."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Singleton-Zugriff auf die Settings.

    `Settings()` wird ohne kwargs aufgerufen — alle Felder kommen aus
    Umgebungsvariablen bzw. .env. Mypy sieht das nicht und meckert
    `environment` als fehlendes Required-Argument; wird per type-ignore
    unterdrueckt.
    """
    return Settings()  # type: ignore[call-arg]
