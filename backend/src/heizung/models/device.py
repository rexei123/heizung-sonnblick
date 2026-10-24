"""Gerät (Thermostat oder Sensor).

Herstellerunabhängige Abstraktion: nur LoRaWAN-Identifikation, Typ und
Zuordnung zur Heizzone. Die konkrete Protokoll-Implementierung liegt in
``heizung.drivers`` und greift über ``dev_eui`` auf das Gerät zu.

Keys (AppKey, NwkKey) werden NICHT hier gespeichert, sondern verschlüsselt
in einer späteren Tabelle oder per ChirpStack verwaltet.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from heizung.db import Base
from heizung.models.enums import DeviceKind, DeviceVendor, _enum_values

if TYPE_CHECKING:
    from heizung.models.heating_zone import HeatingZone


class Device(Base):
    __tablename__ = "device"

    id: Mapped[int] = mapped_column(primary_key=True)

    # LoRaWAN-Identifikation (8 Byte hex = 16 Zeichen). Eindeutigkeit unter
    # aktiven Rows (retired_at IS NULL) via Partial-Unique-Index
    # ``ix_device_dev_eui_active_unique`` (Migration 0018, AE-57). Voll-
    # Unique-Constraint aus Migration 0001 wurde abgeloest, damit DevEUI-
    # Wiederverwendung nach Werksreset moeglich ist.
    dev_eui: Mapped[str] = mapped_column(String(16), nullable=False)
    app_eui: Mapped[str | None] = mapped_column(String(16))

    kind: Mapped[DeviceKind] = mapped_column(
        SQLEnum(
            DeviceKind,
            name="device_kind",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    vendor: Mapped[DeviceVendor] = mapped_column(
        SQLEnum(
            DeviceVendor,
            name="device_vendor",
            native_enum=False,
            length=20,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(String(50), nullable=False)

    # Zuordnung zur Zone. NULL = Pool (Reserve-Vicki) oder Provisioning.
    heating_zone_id: Mapped[int | None] = mapped_column(
        ForeignKey("heating_zone.id", ondelete="SET NULL")
    )

    label: Mapped[str | None] = mapped_column(String(200))

    # Sprint 14a (D1): hersteller-uebergreifende Hardware-/Seriennummer
    # (z. B. ``MDC5419731K6UF``). Keine Format-Validierung. Eindeutigkeit
    # nur fuer gesetzte Werte via Partial-Unique-Index
    # ``ix_device_hardware_number_unique`` (Migration 0020,
    # ``WHERE hardware_number IS NOT NULL``); beliebig viele NULL erlaubt.
    hardware_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Sprint 9.11x: Schema-Vorbereitung fuer 9.11x.b (Codec-Drift-Schutz).
    # In 9.11x ungenutzt, in 9.11x.b vom MQTT-Subscriber gepflegt.
    firmware_version: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Sprint 11 (AE-53): Compute-Task aus T5 setzt den Wert periodisch.
    # DB-Default 'silent' ist Source of Truth — kein Python-Default,
    # sonst entstuenden zwei Wahrheiten.
    health_state: Mapped[str] = mapped_column(String(16), nullable=False, server_default="silent")

    # Sprint 13b.1 (AE-57): Device-Lifecycle. ``retired_at IS NULL`` ist
    # Single Source of Truth fuer "aktiv". Wird ausschliesslich von
    # ``services.device_service.retire_device`` und ``replace_device``
    # gesetzt — kein direkter Schreibpfad ueber Schema/API.
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_reason: Mapped[str | None] = mapped_column(String(255))
    replaced_by_device_id: Mapped[int | None] = mapped_column(
        ForeignKey("device.id", ondelete="SET NULL")
    )

    # Sprint 20e (T1, Migration 0027): der Montage-Nachweis. Gesetzt auf dem
    # ersten Frame, der ``attached_backplate=true`` UND ``valve_position > 0``
    # zusammen meldet — also "der Taster war gedrueckt, waehrend der Motor
    # das Ventil geoeffnet hat". Danach nie wieder geschrieben, bis
    # ``detach``/``retire``/``replace`` ihn loeschen (T12).
    #
    # Eine Lebenszyklus-Tatsache wie ``retired_at`` (AE-57), kein Zustand:
    # Layer 4 fragte bisher "sitzt das Geraet **jetzt**?" und bekam vom
    # Backplate-Taster zu oft ein falsches Nein. Der Nachweis fragt "**war**
    # es je belegt montiert?", und das kann sich nicht zurueckdrehen, solange
    # das Geraet an derselben Zone haengt.
    #
    # Schreibpfade: ``mqtt_subscriber._persist_uplink`` (setzen),
    # ``device_service``/``api.v1.devices`` (loeschen). Kein Schema-Default,
    # kein Backfill in der Migration — ``scripts/backfill_mounted_confirmed``
    # urteilt ueber die Historie (§5.61).
    mounted_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Sprint 24 (Migration 0030): Infrarot-Pilot, Relais und Fuehler ---

    # S3: ohne dieses Kennzeichen erhaelt ein Relais **keine**
    # Schaltbefehle, nur Lese- und Konfigurationsbefehle. Gesetzt wird es
    # ausschliesslich von einem Admin in der Oberflaeche, und zwar erst
    # nach der Provisionierung (S4) — ohne verifizierten Zustand nach
    # Stromrueckkehr ist es nicht setzbar.
    #
    # Eine Lebenszyklus-Tatsache wie ``mounted_confirmed_at``, kein
    # Zustand: ein Relais, das einmal in Betrieb genommen wurde, bleibt
    # es, bis jemand es ausdruecklich zuruecknimmt. Der Grund fuer ein
    # Datum statt eines Schalters ist derselbe wie dort — wer spaeter
    # fragt, wann das Panel scharf wurde, hat eine Antwort.
    commissioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # S7 / Paket E: ein Thermostat in der Rolle **nur messen**. Es
    # bekommt keine Sollwert-Downlinks, und eine Drehung am Rad erzeugt
    # keinen Override. Gedacht fuer eine unmontierte Vicki, die in einem
    # Raum mit Relais-Heizung nur den Istwert liefert.
    #
    # Nicht ``kind``, sondern ein eigenes Feld: das Geraet **ist** ein
    # Thermostat, es wird nur anders verwendet. Ein eigener ``kind``-Wert
    # haette jede bestehende Abfrage nach ``thermostat`` stillschweigend
    # um dieses Geraet verkuerzt — auch die, die es mitzaehlen wollen.
    measure_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )

    # Sprint 24d: **wann** die Kindersicherung gesendet wurde.
    #
    # Ohne diese Zeit ist eine alte Antwort nicht von einer Ablehnung zu
    # unterscheiden. Direkt nach dem Umschalten ist die juengste Meldung
    # die vom Keepalive davor; sie sagt „Rad frei", und das war bis zur
    # Sekunde vorher richtig. Die Geraeteseite zeigte deshalb einen roten
    # Befund im Normalfall (Befund des Betreibers, 24.10.2026).
    #
    # ``NULL`` heisst „kein Befehl bekannt" — fuer Geraete, die vor der
    # Migration 0033 umgeschaltet wurden.
    child_lock_commanded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # S2 / Paket C: Waechter-Strategie je Relais. Vorgabe ist
    # ``expire_and_resend``; ``refresh`` ist gebaut, aber bewusst nicht
    # die Vorgabe (Begruendung im Enum-Docstring).
    watchdog_strategy: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="expire_and_resend"
    )

    # S4 (Nachtrag 23.10.): die **zwei** Ruecklesungen, ohne die ein
    # Relais nicht in Betrieb genommen werden darf. Beide tragen den
    # Zeitpunkt der **Bestaetigung durch das Geraet**, nicht den des
    # Sendens — ein bestaetigter Downlink sagt, dass der Frame ankam,
    # nicht dass die Einstellung sitzt.
    #
    # Warum zwei und nicht einer: das Geraet hat zwei voneinander
    # unabhaengige Wege, von selbst wieder EIN zu werden.
    #
    #   0x5E  nach Stromrueckkehr        Vorgabe: last_state
    #   0x59  nach Ueberhitzungs-Erholung Vorgabe: last_state
    #
    # Die Doku sagt zur Erholung ausdruecklich, das Relais sei „returned
    # to its previous state after recovering from the protection event" —
    # ein Relais, das wegen Hitze abgeschaltet hat, kaeme nach dem
    # Abkuehlen also von selbst zurueck, und zwar ohne jeden Befehl von
    # uns. Deshalb reicht die eine Ruecklesung nicht.
    power_return_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    overheating_recovery_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # S4 (Nachtrag 23.10.): Sperre nach einer Schutzauslösung. Gesetzt
    # vom Uplink-Pfad, geloescht **nur** von einem Admin.
    #
    # Das Geraet erholt sich bei Ueberhitzung und Ueberspannung von
    # selbst (laut Doku nach einer Minute bei Spannung). Genau deshalb
    # braucht es hier eine Sperre: ohne sie waere der Vorfall nach einer
    # Minute unsichtbar, der Regler schaltete wieder ein, und ein
    # Panel mit einem echten Fehler ginge in eine Schleife aus
    # Abschalten und Wiedereinschalten. Die Sperre macht aus einem
    # selbstheilenden Geraetezustand einen Befund, der jemanden braucht.
    protection_tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Art der Auslösung als Marke des Codecs (``overheating``,
    # ``overvoltage``, ``overcurrent``, ``overpower``). String und kein
    # Enum: die Liste steht in der Firmware, und ein unbekannter Wert
    # soll als Rohwert ankommen statt die Sperre zu verhindern.
    protection_kind: Mapped[str | None] = mapped_column(String(20))

    # Sprint 24b (Migration 0031): der **offene** Befehl. Was gesendet und
    # noch nicht vom Geraet bestaetigt ist.
    #
    # Der **bestaetigte** Zustand steht bewusst nicht hier, sondern wird
    # aus ``relay_reading`` abgeleitet (``services/relay_state.py``). Eine
    # Kopie daneben waere eine zweite Wahrheit, die beim ersten verpassten
    # Uplink auseinanderlaeuft (§5.53) — und bei einem Schaltzustand ist
    # die falsche Haelfte genau die, auf die sich der Waechter verlassen
    # wuerde.
    pending_target_on: Mapped[bool | None] = mapped_column(Boolean)
    pending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Paket C: Zahl der Schaltvorgaenge, hochgezaehlt bei jedem
    # **bestaetigten** Wechsel nach EIN. Ein Relais hat eine endliche
    # Zahl mechanischer Schaltungen, und die Akzeptanzgrenze des
    # Feldtests ist in Zyklen je Stunde formuliert — ohne Zaehler ist sie
    # nicht pruefbar.
    switch_cycles: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    heating_zone: Mapped[HeatingZone | None] = relationship(back_populates="devices")

    # Selbst-referenzielle Cross-Reference Alt -> Neu beim Tausch
    # (AE-57 Entscheidung 6). ``remote_side=[id]`` zeigt SQLAlchemy, dass
    # ``id`` die "many"-Seite ist und ``replaced_by_device_id`` die FK.
    # noqa A003: id shadowing is SQLAlchemy canonical pattern in class body.
    replaced_by: Mapped[Device | None] = relationship(
        "Device",
        foreign_keys=[replaced_by_device_id],
        remote_side=[id],  # noqa: A003
    )
