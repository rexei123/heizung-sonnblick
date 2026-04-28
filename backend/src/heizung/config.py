"""Anwendungs-Settings.

Lädt Konfiguration aus Umgebungsvariablen bzw. ``.env``. Alle Felder sind
typisiert. Ein Startup-Validator verhindert, dass das System mit
Standard-Secrets in Produktion läuft.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Laufzeit ---
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    secret_key: str = Field(default="change-me-in-production", min_length=16)

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
    def _reject_default_secrets_in_production(self) -> "Settings":
        if self.environment == "production" and self.secret_key == "change-me-in-production":
            raise ValueError(
                "SECRET_KEY muss in Produktion explizit gesetzt werden. "
                "Beispiel: openssl rand -hex 32"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Singleton-Zugriff auf die Settings."""
    return Settings()
