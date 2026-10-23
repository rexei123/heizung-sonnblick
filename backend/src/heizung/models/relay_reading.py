"""Zeitreihen-Messwerte von Relais-Aktoren (16ASPM).

**Warum eine eigene Tabelle und nicht ``sensor_reading``.** Die beiden
Gerätearten melden verschiedene Dinge, und keine einzige Spalte ist
gemeinsam: ``sensor_reading`` führt Raumtemperatur, Sollwert,
Ventilstellung und Batterie; ein Relais meldet Schaltzustand, Leistung,
Energie, Netzspannung, Netzstrom und seine Gehäusetemperatur. Eine
gemeinsame Tabelle hätte zwölf Spalten, von denen je Zeile die Hälfte
``NULL`` wäre — und jede Abfrage müsste zusätzlich nach Geräteart
filtern, auch die bestehenden.

Wie ``sensor_reading`` wird die Tabelle in der Migration zur
TimescaleDB-Hypertable über ``time``; die Zeit-Spalte ist deshalb Teil
des Primärschlüssels.

Keine ``created_at``/``updated_at`` — Messwerte sind unveränderlich.

**Energie ist ein Zähler, kein Messwert.** ``energy_wh`` ist der
Stand des geräteinternen Zählers, nicht der Verbrauch seit der letzten
Meldung. Er

- läuft bei 0xFFFFFFFF über (4 294 967 295 Wh, also knapp 4,3 GWh),
- wird vom Befehl ``0x26`` („Clear accumulated energy") auf 0 gesetzt,
- und beginnt nach einem Gerätetausch bei 0.

Wer ihn wie eine Temperatur differenziert, bekommt bei jedem dieser drei
Ereignisse einen **negativen** Verbrauch. Ein Verbrauch über eine Spanne
ist deshalb nur mit ausdrücklicher Behandlung des Rücksprungs zu bilden —
und Energiereports sind in Sprint 24 ausdrücklich nicht im Umfang. Die
Spalte wird gespeichert, damit sie später vorhanden ist, und sonst nicht
gelesen.

**Die Einheit der Gehäusetemperatur ist nicht belegt.** Der
Hersteller-Dekoder liest ein Byte und nennt keine Einheit; die Doku
schweigt (AE-78). Gespeichert wird deshalb der **Rohwert** als
``internal_temperature_raw``, nicht eine Zahl, die wie °C aussieht. Die
Deutung gehört in die Anzeige, sobald sie am Gerät geprüft ist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from heizung.db import Base


class RelayReading(Base):
    __tablename__ = "relay_reading"

    # Composite PK (time, device_id) wie bei ``sensor_reading``:
    # Timescale-Anforderung und natuerlicher Zugriffspfad.
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    device_id: Mapped[int] = mapped_column(
        ForeignKey("device.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    # LoRaWAN-Frame-Counter, fuer den Replay-Schutz — dieselbe Rolle wie
    # in ``sensor_reading``. Nullable, weil ein Uplink ohne fcnt denkbar
    # ist (Bestandspfad des Subscribers).
    fcnt: Mapped[int | None] = mapped_column(Integer)

    # Der Schaltzustand, wie das **Geraet** ihn meldet. Das ist die
    # einzige belastbare Quelle: was wir gesendet haben, steht in
    # ``control_command`` (derselbe Unterschied, der Sprint 20f
    # zugrunde liegt).
    relay_on: Mapped[bool | None] = mapped_column(Boolean)

    # Restlaufzeit des Relais-Timers in Sekunden, aus einer 0x58-Antwort.
    # NULL heisst "diese Zeile sagt nichts darueber" — nicht "kein Timer".
    timer_remaining_s: Mapped[int | None] = mapped_column(Integer)

    # Grund der letzten Zustandsaenderung aus 0x54, als snake_case-Marke
    # des Codecs (``radio_timer``, ``manual_button``,
    # ``overheating_protection``, ...). String und kein Enum: die Liste
    # steht in der Geraete-Firmware, nicht bei uns, und ein unbekannter
    # Wert soll als Rohwert ankommen statt eine Zeile zu verwerfen.
    change_reason: Mapped[str | None] = mapped_column(String(40))

    power_w: Mapped[int | None] = mapped_column(Integer)

    # Zaehlerstand in Wh. ``BigInteger``, weil der Rohwert bis
    # 4 294 967 295 geht und ``Integer`` bei 2 147 483 647 endet — ein
    # ``int4`` waere bei der Haelfte des Zaehlerbereichs uebergelaufen.
    energy_wh: Mapped[int | None] = mapped_column(BigInteger)

    ac_voltage_v: Mapped[int | None] = mapped_column(Integer)
    ac_current_ma: Mapped[int | None] = mapped_column(Integer)

    # Rohwert, Einheit unbelegt — siehe Modul-Docstring.
    internal_temperature_raw: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (Index("ix_relay_reading_device_time", "device_id", "time"),)
