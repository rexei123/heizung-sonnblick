"""Anwendungs-Settings.

Lädt Konfiguration aus Umgebungsvariablen bzw. ``.env``. Alle Felder sind
typisiert. Ein Startup-Validator verhindert, dass das System mit
Standard-Secrets in irgendeinem Modus laeuft (QA-Audit K-3).

Lokale Entwickler koennen die Validierung gezielt deaktivieren:
  ALLOW_DEFAULT_SECRETS=1 (nur fuer reine Dev-Maschine)
"""

import os
from decimal import Decimal
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

    # --- Auth (Sprint 9.17, AE-50) ---
    # Feature-Flag fuer kontrollierte Aktivierung. AE-6: Default false,
    # heizung-test wird mit false released, Strategie-Chat kippt nach
    # erfolgreichem Bootstrap-Admin-Login auf true.
    auth_enabled: bool = False
    # JWT signing. Bei None: Fallback auf ``secret_key`` (operativ
    # einfacher; bei separatem Geheimnis explizit setzen).
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_hours: int = 12
    auth_cookie_name: str = "heizung_session"
    # Cookie secure-Flag: in production HTTPS-only, lokal HTTP zulassen.
    auth_cookie_secure: bool = True
    # Rate-Limit auf /auth/login (slowapi). 5 Versuche pro Minute pro IP.
    auth_login_rate_limit: str = "5/minute"
    # Bootstrap-Admin via ENV (AE-5). Migration 0014 nutzt diese Werte
    # einmalig beim alembic upgrade, wenn user-Tabelle leer ist.
    initial_admin_email: str | None = None
    initial_admin_password_hash: str | None = None

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

    # --- ChirpStack (Sprint 9.2) ---
    # Application-ID aus dem Tenant „Hotel Sonnblick" / Application „Heizung".
    # Server-spezifisch in .env zu setzen. Default ist die Test-Server-ID.
    chirpstack_app_id: str = "b7d74615-aaaa-bbbb-cccc-000000000000"
    # Topic-Pattern fuer Downlinks an Devices via ChirpStack-Application-Server.
    # ChirpStack v4 erwartet: application/{ApplicationID}/device/{DevEUI}/command/down
    downlink_topic_template: str = "application/{app_id}/device/{dev_eui}/command/down"

    # --- Belegungs-Import-Webhook (Sprint 15e, AE-66) ---
    # Shared Secret fuer den mailparser->Casablanca-Webhook. Konstant-Zeit-
    # Vergleich gegen den Header ``X-Webhook-Token``. Leer = fail-closed
    # (Endpoint lehnt jede Anfrage mit 401 ab). Server-spezifisch in .env
    # setzen, NIE committen.
    occupancy_import_token: str = ""
    # Die Erwartungszeit der Belegungsliste stand hier bis zum 26.09.2026 als
    # OCCUPANCY_IMPORT_EXPECTED_BY_LOCAL="09:00". Sie ist nach
    # ``global_config.occupancy_import_expected_by_local`` umgezogen
    # (Migration 0022, Vorgabe 12:00 Ortszeit) und in der Oberflaeche
    # editierbar: der Wert haengt am Versandzeitpunkt in fremder Software und
    # muss ohne Deployment aenderbar sein. Zwei Quellen fuer denselben Wert
    # waeren ein Drift-Risiko (§5.53).

    # --- SMTP (Sprint 18) -------------------------------------------------
    # Zugangsdaten kommen ausschliesslich aus der Umgebung, nie aus der
    # Datenbank und nie aus einem Argument. Der EMPFAENGER dagegen steht in
    # ``global_config.alert_email`` — er ist eine Hotelier-Einstellung und
    # gehoert in die Oberflaeche, nicht in die .env.
    #
    # ``smtp_enabled=False`` ist die Vorgabe: ohne gesetzte Zugangsdaten
    # soll nichts versucht werden. Der Versand meldet dann "deaktiviert"
    # statt in einen Verbindungsfehler zu laufen.
    smtp_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # Absender. Leer -> ``smtp_user`` wird verwendet; viele Anbieter
    # verlangen ohnehin, dass Absender und angemeldetes Konto uebereinstimmen.
    smtp_from: str = ""
    # starttls: Klartext-Verbindung auf 587, danach Upgrade (Standard).
    # ssl:      implizites TLS ab dem ersten Byte, ueblich auf 465.
    # none:     ohne Verschluesselung — nur fuer einen lokalen Relay im
    #           selben Netz vertretbar, nie ueber das Internet.
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    # Zeitlimit je Verbindungsversuch. Der Alarm laeuft im Celery-Beat;
    # ein haengender SMTP-Server darf den Tick nicht blockieren.
    smtp_timeout_seconds: int = 20

    # --- Dead-Man-Checks (Sprint 18) --------------------------------------
    # Ping-URLs eines externen Monitors (healthchecks.io). Bleibt eine URL
    # leer, wird nicht gepingt — das Feature ist damit pro Umgebung
    # zuschaltbar, ohne Code-Aenderung.
    #
    # Ueberwacht wird die WIRKUNG, nicht die Mechanik (CLAUDE.md §5.76):
    # bleibt der Ping aus, schlaegt der Monitor Alarm, ganz gleich ob Beat,
    # Worker, Timer, Skript oder Netzwerk der Grund ist.
    #
    # Die Werte sind Geheimnisse im schwachen Sinn — wer die URL kennt, kann
    # den Monitor gruen halten und damit einen Ausfall verdecken. Sie
    # gehoeren deshalb in die .env, nicht ins Repo.
    healthcheck_engine_url: str = ""
    healthcheck_deploy_url: str = ""
    healthcheck_backup_url: str = ""

    # --- Batterie-Schwellen (Sprint 20b, AE-73) ---------------------------
    # Die zwei Grenzen der Batterie-Stufen, in Volt, auf dem 24-h-Median der
    # Geraete-Spannung. ``ok`` ab ``battery_ok_min_v``, ``kritisch`` bis
    # einschliesslich ``battery_critical_max_v``, dazwischen ``warn``.
    #
    # Warum sie hier stehen und nicht als Konstante im Code: die Werte sind
    # eine **Einschaetzung**, nicht eine Eigenschaft der Hardware. Wie weit
    # man eine Zelle ausnutzen will, haengt am Haus — Hotel Sonnblick ist
    # thermisch saniert, ein Ventil, das einen Tag nicht regelt, kostet dort
    # kaum Komfort. Nach der Montage wird nachjustiert, und das soll ohne
    # Code-Aenderung gehen (AE-73).
    #
    # Warum NICHT in ``global_config`` (also in die Oberflaeche): die Stufen
    # sind keine Hotelier-Einstellung wie die Alarm-Mail oder die
    # Offline-Minuten. Wer sie verschiebt, muss wissen, was der 0.1-V-Raster
    # des Codecs hergibt und wo die Spec-Untergrenze liegt — sonst entsteht
    # ein Feld, dessen Wirkung niemand vorhersagen kann. Umgekehrt zum
    # Belegungs-Zeitpunkt (AE-66), der aus genau dem Grund in die DB umgezogen
    # ist: der haengt an fremder Software und aendert sich ohne Vorwarnung.
    #
    # ``Decimal``, nicht ``float``: 2.9 und 2.6 haben in IEEE-754 keine exakte
    # Darstellung, und der Vergleich laeuft genau auf diesen Rasterpunkten.
    # Pydantic parst den env-String direkt nach ``Decimal`` — exakt, solange
    # der Wert als Dezimalzahl notiert ist.
    #
    # **Bewusst ohne Plausibilitaets-Grenze gegen den Spec-Betriebsbereich**
    # (2.7-3.6 VDC). Der Default 2.6 liegt selbst darunter: das ist die
    # Entscheidung von AE-73, die Zelle bis an den Ausfall auszunutzen. Eine
    # Schranke, die das verbietet, haette diesen Sprint blockiert.
    battery_ok_min_v: Decimal = Decimal("2.9")
    battery_critical_max_v: Decimal = Decimal("2.6")

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

    @model_validator(mode="after")
    def _battery_schwellen_sind_geordnet(self) -> "Settings":
        """AE-73: ``kritisch``-Grenze muss unter der ``ok``-Grenze liegen.

        Bei ``critical_max >= ok_min`` gibt es keinen ``warn``-Bereich mehr,
        und ``battery_stage_from_volts`` wuerde je nach Reihenfolge der
        Vergleiche ein Ergebnis liefern, das niemand erwartet: bei
        ``critical_max = ok_min`` ist der Grenzwert selbst gleichzeitig
        ``kritisch`` (<=) und ``ok`` (>=) — die Reihenfolge im Code
        entscheidet, nicht die Konfiguration.

        Das ist ein Start-Fehler und keine Warnung: ein Haus, dessen
        Batterie-Anzeige nach einem Tippfehler in der ``.env`` stumm das
        Gegenteil meldet, ist schlimmer bedient als eines, dessen API nicht
        startet. Der Fehler steht beim Hochfahren im Container-Log.
        """
        if self.battery_critical_max_v >= self.battery_ok_min_v:
            raise ValueError(
                "BATTERY_CRITICAL_MAX_V muss kleiner als BATTERY_OK_MIN_V sein "
                f"(ist: {self.battery_critical_max_v} >= {self.battery_ok_min_v}). "
                "Sonst gibt es keine Stufe 'schwach', und der Grenzwert selbst "
                "waere gleichzeitig kritisch und ok."
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
