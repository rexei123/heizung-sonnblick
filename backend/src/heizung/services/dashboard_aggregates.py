"""Sprint 14c — Hotel-Aggregat-Helper fuer das Dashboard (`/api/v1/dashboard/kpi`).

Sechs read-only Aggregat-Funktionen ueber den gesamten Hotelbestand. Bewusst
duenn: jede liefert genau den Wert einer KPI-Kachel. Keine Schreib-Pfade, keine
Engine-Kopplung.

Konventionen:
- **Decimal** fuer Temperatur-Aggregate, ``ROUND_HALF_EVEN`` auf 0.1 °C
  (User-Regel + Konsistenz zu ``rules.aggregation``).
- **Lifecycle-Filter** ``Device.retired_at IS NULL`` fuer alle Device-Queries
  (CLAUDE §5.58).
- **Zone-Aggregat** wird ueber den Bestand-Helper
  ``rules.aggregation.aggregate_zone_readings`` berechnet (healthy-Filter +
  OR-Fenster + Mittelwert leben dort, eine Quelle der Wahrheit, AE-51 §4.1).
- **Engine-Tick-Marker** ist ``EventLogLayer.HARD_CLAMP`` — laeuft in beiden
  Pfaden (normal + Sommer-Fast-Path, ``engine.py``) und schliesst die
  Off-Pipeline-Inseln ``MANUAL_OVERRIDE_BLOCKED`` (synthetische ``evaluation_id``,
  §5.52) aus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import EventLogLayer, RoomStatus
from heizung.models.event_log import EventLog
from heizung.models.manual_override import ManualOverride
from heizung.models.room import Room
from heizung.models.sensor_reading import SensorReading
from heizung.rules.aggregation import ReadingForAggregate, aggregate_zone_readings
from heizung.services.battery_health import battery_verdicts
from heizung.services.valve_health import valve_verdicts

_ONLINE_STATES = ("healthy", "degraded")
_QUANT_TENTH: Decimal = Decimal("0.1")


async def count_rooms_occupied(session: AsyncSession) -> tuple[int, int]:
    """``(belegt, gesamt)``. Belegt = ``Room.status == OCCUPIED``.

    Quelle ist das persistierte ``Room.status`` (vom ``sync_room_status``-Cron
    aus aktiven Occupancies abgeleitet, §5.53). Fuer eine Uebersichts-Kachel
    ist die Sync-Latenz akzeptabel.
    """
    occupied = (
        await session.execute(
            select(func.count()).select_from(Room).where(Room.status == RoomStatus.OCCUPIED)
        )
    ).scalar_one()
    total = (await session.execute(select(func.count()).select_from(Room))).scalar_one()
    return occupied, total


async def count_devices_online(session: AsyncSession) -> tuple[int, int]:
    """``(online, zugeordnet)`` — beide **nur** ueber Geraete mit Heizzone.

    Online = ``health_state IN (healthy, degraded)``, Lifecycle-Filter
    ``retired_at IS NULL`` (§5.58).

    **Sprint 21 (B-21-2): die Zuordnung ist neu die Grenze.** Vorher zaehlte
    der Nenner alle nicht stillgelegten Geraete, also Pool und Lager mit. Ein
    Ersatzteil ohne Batterie ist korrekt "nicht online" — es stand damit im
    Nenner und nicht im Zaehler, und aus "101 von 101" wurde "101 von 104".

    Die Zahl beantwortet damit nicht mehr die Frage, fuer die sie da ist:
    **ist ein Zimmer unversorgt?** Schlimmer, sie faerbte die Kachel dauerhaft
    gelb (``online < total``), also eine Daueranzeige fuer einen
    Normalzustand — ein Melder, der immer anschlaegt, meldet nichts (§5.79).

    Die Grenze ist ``heating_zone_id IS NOT NULL`` und **nicht**
    ``mounted_confirmed_at``: gefragt ist, ob ein Zimmer versorgt ist, und
    versorgt ist es, sobald ein Geraet dafuer zustaendig ist. Die Montage ist
    eine andere Frage und hat ihre eigene Spalte.

    Was das kostet, steht in RUNBOOK §10t: ein zugeordnetes Geraet, das
    jemand ins Lager legt **ohne** Ersatz zuzuordnen, verschwindet aus
    Zaehler und Nenner — die Kachel bleibt gruen, obwohl ein Heizkoerper
    unversorgt ist. Sichtbar bleibt es auf ``/devices``.
    """
    zugeordnet_aktiv = (
        select(func.count())
        .select_from(Device)
        .where(Device.retired_at.is_(None))
        .where(Device.heating_zone_id.is_not(None))
    )
    online = (
        await session.execute(zugeordnet_aktiv.where(Device.health_state.in_(_ONLINE_STATES)))
    ).scalar_one()
    zugeordnet = (await session.execute(zugeordnet_aktiv)).scalar_one()
    return online, zugeordnet


async def count_devices_pool(session: AsyncSession) -> int:
    """Geraete ohne Heizzone und nicht stillgelegt — Pool und Lager.

    Eigene Funktion und kein drittes Element im Rueckgabewert von
    ``count_devices_online``: die Zahl beantwortet eine andere Frage
    ("wie viele Ersatzteile liegen da"), und ein Name, der "online" sagt und
    Lagerbestand zurueckgibt, ist die naechste §5.77-Stelle.

    Sie faerbt nichts. Ein Geraet im Lager ohne Batterie ist Normalzustand
    (Entscheidung des Hoteliers vom 12.10.2026) — reparierbare Koepfe
    stillzulegen waere endgueltig und falsch.
    """
    return (
        await session.execute(
            select(func.count())
            .select_from(Device)
            .where(Device.retired_at.is_(None))
            .where(Device.heating_zone_id.is_(None))
        )
    ).scalar_one()


async def count_active_overrides(session: AsyncSession) -> int:
    """Aktive Overrides = ``revoked_at IS NULL AND expires_at > now()``."""
    now = datetime.now(tz=UTC)
    return (
        await session.execute(
            select(func.count())
            .select_from(ManualOverride)
            .where(ManualOverride.revoked_at.is_(None))
            .where(ManualOverride.expires_at > now)
        )
    ).scalar_one()


async def last_engine_tick(session: AsyncSession) -> datetime | None:
    """Zeitpunkt der juengsten abgeschlossenen Engine-Evaluation (UTC).

    ``MAX(time)`` ueber ``event_log`` gefiltert auf ``layer = 'hard_clamp'``.
    ``None`` wenn noch nie ein Tick lief.
    """
    return cast(
        "datetime | None",
        (
            await session.execute(
                select(func.max(EventLog.time)).where(EventLog.layer == EventLogLayer.HARD_CLAMP)
            )
        ).scalar_one(),
    )


async def _collect_zone_aggregates(
    session: AsyncSession,
) -> list[tuple[Decimal | None, bool | None]]:
    """Pro Zone ``(mean_temp_c, any_open_window)`` ueber healthy Vickis.

    Laedt aktive Devices (``retired_at IS NULL``) mit Zone-Zuordnung und das
    juengste Reading pro Device (DISTINCT ON, eine indizierte Query), gruppiert
    nach Zone und delegiert die Aggregation an ``aggregate_zone_readings``
    (healthy-Filter dort). Zonen ohne Device tauchen nicht auf.
    """
    device_rows = (
        await session.execute(
            select(Device.id, Device.heating_zone_id, Device.health_state)
            .where(Device.retired_at.is_(None))
            .where(Device.heating_zone_id.is_not(None))
        )
    ).all()
    if not device_rows:
        return []

    # Juengstes Reading pro Device in einer Query (DISTINCT ON device_id).
    reading_rows = (
        await session.execute(
            select(
                SensorReading.device_id,
                SensorReading.temperature,
                SensorReading.open_window,
            )
            .order_by(SensorReading.device_id, SensorReading.time.desc())
            .distinct(SensorReading.device_id)
        )
    ).all()
    latest: dict[int, tuple[Decimal | None, bool | None]] = {
        row.device_id: (row.temperature, row.open_window) for row in reading_rows
    }

    by_zone: dict[int, list[ReadingForAggregate]] = {}
    for device_id, zone_id, health_state in device_rows:
        temp, open_window = latest.get(device_id, (None, None))
        by_zone.setdefault(zone_id, []).append(
            ReadingForAggregate(
                temperature_c=temp,
                open_window=open_window,
                health_state=health_state,
            )
        )

    return [aggregate_zone_readings(readings) for readings in by_zone.values()]


async def avg_room_temperature(session: AsyncSession) -> Decimal | None:
    """Mittelwert ueber die Zonen-Aggregate aller Zonen mit healthy Vickis.

    Mittelt die per-Zone-Mittelwerte (jede Zone gleich gewichtet), quantisiert
    auf 0.1 °C mit ``ROUND_HALF_EVEN``. ``None`` wenn keine Zone einen
    healthy-Temperatur-Wert liefert.
    """
    zone_means = [mean for mean, _ in await _collect_zone_aggregates(session) if mean is not None]
    if not zone_means:
        return None
    mean = sum(zone_means, start=Decimal("0")) / Decimal(len(zone_means))
    return mean.quantize(_QUANT_TENTH, rounding=ROUND_HALF_EVEN)


async def count_zones_window_open(session: AsyncSession) -> int:
    """Anzahl Zonen mit ``open_window=True`` (OR ueber healthy Vickis der Zone)."""
    return sum(1 for _, window in await _collect_zone_aggregates(session) if window is True)


async def count_valve_alerts(session: AsyncSession) -> tuple[int, int]:
    """Aktive Geraete mit Ventil-Hinweis: ``(ventil_pruefen, zu_warm)``.

    **Getrennt gezaehlt und nicht summiert.** Die beiden Hinweise bedeuten
    verschiedene Handgriffe: "Ventil klemmt zu" heisst Ventil pruefen oder
    neu kalibrieren, "Zimmer zu warm" heisst nachsehen, ob der Kopf noch
    sitzt. Eine gemeinsame Zahl haette den Hausmeister losgeschickt, ohne
    ihm zu sagen, was er mitnehmen soll.

    Die Kachel zaehlt damit **genau** die Geraete, die auch ein Badge
    tragen — beides kommt aus ``valve_verdicts``, es gibt keine zweite
    Schwelle, die davon abdriften koennte. Dieselbe Invariante wie bei der
    Batterie.

    ``unbekannt`` zaehlt in keine der beiden Zahlen. Ein Geraet mit zu
    wenigen Messwerten ist kein Befund, sondern ein Geraet ohne Aussage —
    es gehoert auf die Offline-Achse, nicht hierher.

    Zwei Queries, unabhaengig von der Geraetezahl — kein N+1.
    Lifecycle-Filter ``retired_at IS NULL`` (§5.58).
    """
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.retired_at.is_(None))))
        .scalars()
        .all()
    )
    verdicts = await valve_verdicts(session, device_ids)
    # 20e-c: die Kachel "Ventil pruefen" zaehlt **beide** Ventil-Befunde.
    # Entscheidung des Hoteliers (12.10.2026): eine Zahl fuer den
    # Tagesblick ("am Ventil ist etwas"), die Sorte steht am Geraet.
    # Deshalb heisst das Feld seit 20e-c ``valve_check_count`` und nicht
    # mehr ``valve_stuck_count`` — ein Name, der behauptet, nur klemmende
    # Ventile zu zaehlen, waere falsch (§5.77).
    ventil = sum(
        1 for v in verdicts.values() if v.state in ("ventil_klemmt_zu", "ventil_schliesst_nicht")
    )
    warm = sum(1 for v in verdicts.values() if v.state == "zimmer_zu_warm")
    return ventil, warm


async def count_battery_low(session: AsyncSession) -> int:
    """Anzahl aktiver Geraete (``retired_at IS NULL``) mit schwacher Batterie.

    Schwach = Batterie-Stufe ``warn`` oder ``kritisch`` (Sprint 20, AE-72).
    Die Kachel zaehlt damit **genau** die Geraete, die auch ein gelbes oder
    rotes Badge tragen — beides kommt aus ``battery_verdicts``, es gibt keine
    zweite Schwelle mehr, die davon abdriften koennte.

    Bis Sprint 19 stand hier ein Vergleich des juengsten
    ``battery_percent`` gegen ``alert_battery_warn_percent``, geklemmt gegen
    die fixe Kritisch-Grenze. Die Klemmung war noetig, weil die Warn-Schwelle
    konfigurierbar war und unter die Kritisch-Grenze gestellt werden konnte;
    mit festen Spannungs-Schwellen entfaellt der ganze Fall.

    Zwei Queries statt einer: erst die aktiven Geraete-IDs, dann ein
    Aggregat ueber deren 24-h-Fenster. Unabhaengig von der Geraetezahl —
    kein N+1.

    Lifecycle-Filter ``retired_at IS NULL`` (§5.58) bleibt.
    """
    device_ids = list(
        (await session.execute(select(Device.id).where(Device.retired_at.is_(None))))
        .scalars()
        .all()
    )
    verdicts = await battery_verdicts(session, device_ids)
    return sum(1 for v in verdicts.values() if v.stage in ("warn", "kritisch"))


async def count_befehle_nicht_angenommen(session: AsyncSession) -> int:
    """Aktive Geraete, bei denen der Abgleich aufgegeben hat (Sprint 25, T3).

    Quelle ist ``device.abgleich_erschoepft_seit`` (Migration 0039). Gesetzt
    heisst: drei Nachsendungen erfolglos, es wird nicht weiter gesendet, und
    das Geraet hat seither **keinen** gesendeten Sollwert bestaetigt.

    **Eine Spalte und kein Rechenweg.** Die uebrigen Zaehler dieser Datei
    leiten ihr Urteil zur Laufzeit ab (§5.73) — hier geht das nicht: die
    Zahl der Versuche lebt in Redis mit einer TTL von vier Stunden, und
    genau ihr Verfallen war der Befund, den T3 behebt. Ein Zustand, der
    bestehen soll, bis ein Geraet etwas tut, ist kein Rechenergebnis.

    **Warum die Zahl nicht „Geraete offline" doppelt.** Ein erschoepftes
    Geraet **funkt** — es meldet nur einen anderen Wert als den gesendeten.
    Auf der Offline-Achse ist es ``healthy``. Beides nebeneinander ist
    gewollt und derselbe Grund wie bei der Batterie (§5.73): zwei Fragen,
    zwei Achsen.

    Lifecycle-Filter ``retired_at IS NULL`` (§5.58).
    """
    stmt = select(func.count()).where(
        Device.retired_at.is_(None),
        Device.abgleich_erschoepft_seit.is_not(None),
    )
    return int((await session.execute(stmt)).scalar_one())


async def fenstererkennung_bestaetigt(session: AsyncSession, *, tage: int = 7) -> bool:
    """Hat in den letzten ``tage`` Tagen ein Geraet die Fenstererkennung
    als **eingeschaltet** gemeldet?

    Quelle ist ``sensor_reading.ow_detection_enabled`` — die Antwort auf
    ``0x46`` (Migration 0038). ``True`` heisst: mindestens ein Geraet hat
    bestaetigt, dass die Erkennung bei ihm laeuft.

    **Warum die Kachel das braucht.** Ohne diese Angabe zeigt „Fenster
    offen" eine **0**, und eine 0 liest sich als „es ist kein Fenster
    offen". Richtig ist aber „niemand hat gemessen": am 07.11.2026 stand
    hausweit **keine einzige** Zeile mit ``open_window = true`` — bei
    604.694 Zeilen ``false`` und 49 belegten Temperatureinbruechen allein
    in Zimmer 306. Eine 0 an dieser Stelle ist die gefaehrlichere Zahl,
    weil sie wie ein Befund aussieht (Paragraph 5.77).

    **Warum sieben Tage und nicht „jemals".** Zwei Gruende, und der
    zweite ist der wichtigere.

    Billig: ``ow_detection_enabled`` hat keinen Index, und die Spalte ist
    in fast allen Zeilen ``NULL``. „Jemals" waere ein Scan ueber alle 190
    Chunks, um eine Abwesenheit zu beweisen — je Seitenaufruf. Mit der
    Zeitgrenze schliesst TimescaleDB alle Chunks bis auf rund acht aus.

    Und inhaltlich richtig: eine Bestaetigung vom Juni ist keine Aussage
    ueber heute. Das Geraet kann getauscht, zurueckgesetzt oder neu
    gepairt worden sein. Wer wissen will, ob die Erkennung **jetzt**
    laeuft, fragt die Rueckmeldung der letzten Woche.
    """
    stmt = (
        select(SensorReading.device_id)
        .where(SensorReading.ow_detection_enabled.is_(True))
        .where(SensorReading.time > datetime.now(tz=UTC) - timedelta(days=tage))
        .limit(1)
    )
    return (await session.scalar(stmt)) is not None
