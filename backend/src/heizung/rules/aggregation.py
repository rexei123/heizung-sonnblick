"""Zone-Aggregat ueber healthy Vickis (AE-51 §4.1).

Berechnet Ist-Temperatur (Mittelwert) und Fenster-Status (OR) ueber
alle Devices einer Heizzone, die der Health-State-Compute-Task aus
Sprint 11 T5 als ``healthy`` klassifiziert hat. Devices mit anderem
Health-State (``degraded``, ``silent``, ``suspicious``) fliessen
nicht in das Aggregat ein.

Heutige Konsumenten:

- **Sprint 11 T3 (dieser Sprint):** Pure-Function-Helper mit Tests,
  noch nicht in der Engine-Read-Pipeline integriert. Begruendung:
  ``_load_room_context`` laedt heute keine Reading-Daten (siehe
  Phase-0-Befund T3), Ist-Temperatur ist heute kein Engine-Input.
  Die Layer-4-Window-Detection in ``engine.layer_window_safety``
  bekommt parallel den ``health_state='healthy'``-Filter direkt
  in ihrer eigenen DB-Query — ohne diesen Helper zu nutzen, weil
  Layer 4 das OR-Aggregat in SQL/Python bereits selbst macht.

Zukuenftige Konsumenten:

- **Sprint 12 (AE-51 §4.2 Schreib-Pfad):** Symmetrische Setpoints
  ueber alle Vickis einer Zone — der Schreib-Pfad braucht das
  Aggregat als Referenz fuer die Setpoint-Pruefung.
- **Sprint 14 (UI-API Read):** Zimmer-Detail / Zone-Detail-Endpoints
  liefern Ist-Temperatur + Fenster-Status pro Zone an das Frontend.

Quantisierung folgt der Anzeige-Konvention der Vicki (0.1 °C) mit
Banker's Rounding (ROUND_HALF_EVEN), damit konsistente Vergleiche
gegen Setpoints (auch 0.1 °C) ohne Rundungs-Drift moeglich sind.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

_QUANT_TENTH: Decimal = Decimal("0.1")
_HEALTHY: str = "healthy"


@dataclass(frozen=True)
class ReadingForAggregate:
    """Ein-Vicki-Reading fuer die Zone-Aggregation.

    Enthaelt nur die Felder, die das Aggregat braucht — bewusst keine
    SQLAlchemy-ORM-Kopplung, damit der Helper pure und ohne DB testbar
    bleibt. Konsumenten projizieren ihre ORM-Rows oder Service-DTOs
    auf diesen Typ.

    ``temperature_c`` ist ``None`` zugelassen — kommt vor bei reinen
    Battery-Frames oder Reply-Frames ohne Ist-Temperatur. Solche
    Readings fliessen ebenfalls nicht in den Mittelwert ein.
    """

    temperature_c: Decimal | None
    open_window: bool | None
    health_state: str  # "healthy" | "degraded" | "silent" | "suspicious"


def aggregate_zone_readings(
    readings: list[ReadingForAggregate],
) -> tuple[Decimal | None, bool | None]:
    """Aggregiert Ist-Temperatur (Mittelwert) und Fenster (OR) ueber
    alle ``healthy`` Vickis einer Zone.

    Returns:
        ``(mean_temp_c, any_open_window)``

        - ``mean_temp_c``: arithmetischer Mittelwert ueber die
          ``temperature_c``-Werte aller healthy Readings, quantisiert
          auf 0.1 °C mit ``ROUND_HALF_EVEN``. ``None`` wenn keine
          healthy Readings mit Temperatur vorliegen (leeres Aggregat
          oder alle Temperaturen ``None``).
        - ``any_open_window``: ``True`` wenn mindestens eine healthy
          Vicki ``open_window=True`` meldet. ``False`` wenn mindestens
          eine healthy Vicki explizit ``False`` meldet und keine
          ``True``. ``None`` wenn keine healthy Readings vorliegen
          oder alle ``open_window`` der healthy Readings ``None``
          sind (Feld fehlte im Payload — Sprint 9.10 Lesson §5.27).
    """
    healthy = [r for r in readings if r.health_state == _HEALTHY]
    if not healthy:
        return None, None

    temps = [r.temperature_c for r in healthy if r.temperature_c is not None]
    if temps:
        mean = sum(temps, start=Decimal("0")) / Decimal(len(temps))
        mean_temp_c: Decimal | None = mean.quantize(_QUANT_TENTH, rounding=ROUND_HALF_EVEN)
    else:
        mean_temp_c = None

    explicit_windows = [r.open_window for r in healthy if r.open_window is not None]
    if not explicit_windows:
        any_open_window: bool | None = None
    else:
        any_open_window = any(explicit_windows)

    return mean_temp_c, any_open_window
