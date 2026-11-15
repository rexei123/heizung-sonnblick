"""Sprint 14c — Dashboard-KPI-Schema (`GET /api/v1/dashboard/kpi`).

Ein flaches Read-Schema fuer die 6 Uebersichts-Kacheln auf ``/``. Additiv
erweiterbar (B-14c-FU-1: PMS-/Wetter-Kacheln nach Sprint 16a) ohne Bruch.

``avg_temperature_celsius`` wird als ``field_serializer``->``float`` ausgegeben
(Konvention wie ``DeviceActiveOverrideRead`` / ``SensorReadingRead``), damit der
Frontend-Zod-Spiegel eine JSON-Zahl erhaelt (§5.63). ``last_engine_tick`` ist
UTC ISO-8601 — das Frontend lokalisiert (Europe/Vienna, §5.65).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer


class DashboardKpiRead(BaseModel):
    """Aggregierte Hotel-KPIs fuer das Dashboard."""

    model_config = ConfigDict(from_attributes=True)

    rooms_occupied: int
    rooms_total: int
    avg_temperature_celsius: Decimal | None
    # Sprint 21 (B-21-2): beide Zahlen zaehlen **zugeordnete** Geraete, das
    # Lager steht getrennt daneben. ``devices_total`` hiess das Feld bis
    # dahin — ein Name, der "alle" sagt und nicht alle zaehlt, waere die
    # naechste §5.77-Stelle, deshalb umbenannt statt umgedeutet.
    devices_online: int
    devices_assigned: int
    devices_pool: int
    active_overrides: int
    zones_window_open: int
    last_engine_tick: datetime | None
    # Sprint 15d (AE-65), Eingangsgroesse seit Sprint 20 die Spannung
    # (AE-72): aktive Geraete mit Batterie-Stufe ``warn`` oder ``kritisch``.
    #
    # Der Vermerk hier stand bis Sprint 20e auf "juengster battery_percent <
    # alert_battery_warn_percent". Beides gilt nicht mehr: die Stufe rechnet
    # auf dem 24-h-Median der Spannung, und die konfigurierbare
    # Prozent-Schwelle ist mit AE-72 entfallen (§5.77 — ein ueberholter
    # Vermerk wird wie ein Befund gelesen).
    battery_low_count: int
    # Sprint 20e (T7/T10): Ventil-Hinweise, getrennt gezaehlt. Siehe
    # ``dashboard_aggregates.count_valve_alerts`` fuer die Begruendung,
    # warum es zwei Zahlen sind und nicht eine.
    # 20e-c: zaehlt beide Ventil-Befunde ("Ventil klemmt zu" und "Ventil
    # schliesst nicht"). Hiess bis dahin ``valve_stuck_count`` — der Name
    # haette nach der Erweiterung etwas Falsches behauptet (§5.77).
    valve_check_count: int = 0
    room_too_warm_count: int = 0

    # --- Sprint 25 T8: Kachel „Funk-Empfang" ------------------------------
    # Liest das **Ende** der Kette (``sensor_reading``) und bewusst nicht
    # den ChirpStack-Gateway-Status: am 07.11.2026 war das Gateway in
    # Ordnung, Port 1883 gesperrt und die Zahl der Meldungen null. Ein
    # Gateway-Status haette gruen gezeigt.
    #
    # Die Stufe wird **serverseitig** gebildet, weil die Schwellen in den
    # Settings stehen. Sie im Frontend zu rechnen hiesse, die Schwellen
    # dort zu wiederholen — eine zweite Wahrheit (Paragraph 5.53).
    funkempfang_stufe: Literal["online", "verzoegert", "keine_meldungen", "unbekannt"]
    funkempfang_letzte_meldung: datetime | None
    funkempfang_alter_min: int | None
    funkempfang_meldungen_10min: int
    # Sprint 25 T8: ob ueberhaupt ein Geraet die Fenstererkennung als
    # eingeschaltet gemeldet hat (letzte 7 Tage). Steuert, ob die Kachel
    # „Fenster offen" eine Zahl oder „Erkennung inaktiv" zeigt. Siehe
    # ``dashboard_aggregates.fenstererkennung_bestaetigt``.
    fenstererkennung_aktiv: bool = False

    # --- Sprint 25 T3: „Geraete nehmen Befehle nicht an" ------------------
    # Aktive Geraete mit gesetztem ``abgleich_erschoepft_seit``: der
    # Abgleich hat nach drei Versuchen aufgegeben, und das Geraet hat
    # seither keinen gesendeten Sollwert bestaetigt.
    #
    # **Eigene Achse, kein Teil von „Geraete online".** Ein solches Geraet
    # funkt — es meldet nur einen anderen Wert als den gesendeten. Es ist
    # auf der Offline-Achse ``healthy`` und gehoert deshalb nicht in deren
    # Zahl (derselbe Grund wie bei der Batterie, Paragraph 5.73).
    befehle_nicht_angenommen: int = 0

    # --- 13.11.2026: Kachel „Fuehler Relais-Zone" -------------------------
    # Zonen, in denen ein Relais **in Betrieb** ist und kein aktueller
    # Fuehlerwert mehr ankommt. Ohne Zonenwert schaltet der
    # Zweipunktregler bewusst ab (Zwangs-AUS, S5) — die Zone heizt dann
    # nicht mehr, und anders als bei einem Vicki gibt es kein Geraet, das
    # nach seinem eigenen internen Fuehler weiterregelt.
    #
    # **Eigene Achse, kein Teil von „Geraete online".** Der Fuehler 056
    # war am 12./13.11. vierzehn Stunden stumm und dabei
    # ``health_state = degraded`` — auf der Offline-Achse also kein
    # Alarm, weil die Stufe ``silent`` mehr als 24 Stunden verlangt. Die
    # Kachel „Geraete online" stand auf 102 von 103, und niemand liest
    # daraus, dass die Rezeption blind ist (dieselbe Begruendung wie bei
    # der Batterie, Paragraph 5.73: zwei Fragen, zwei Achsen).
    #
    # Die Stufe wird **serverseitig** gebildet, weil die Grenze in den
    # Settings steht (``Settings.relais_zone_stumm_min``). Sie im Frontend zu
    # rechnen hiesse, die Grenze dort zu wiederholen (Paragraph 5.53).
    relais_zonen_stumm: int = 0
    #: Alter der juengsten Meldung in der am laengsten stummen Zone, in
    #: Minuten. ``None``, wenn keine Zone stumm ist **oder** wenn die
    #: stumme Zone gar keinen Fuehler hat — dort gibt es kein Alter, und
    #: eine 0 waere dann eine Behauptung ueber eine Meldung, die es nicht
    #: gibt.
    relais_zonen_stille_min: int | None = None

    @field_serializer("avg_temperature_celsius")
    def _avg_to_float(self, v: Decimal | None) -> float | None:
        return float(v) if v is not None else None
