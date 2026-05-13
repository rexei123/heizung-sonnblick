"""Konstanten der Regel-Engine.

Sprint 6 Hotfix (QA-Audit K-6): Bevor die volle 5-Schichten-Pipeline
(siehe AE-06) implementiert ist, definieren wir hier die Sicherheits-
Grenzwerte explizit, damit
  a) der Code-Pfad existiert (testbar, versionierbar)
  b) zukuenftige Schichten diese Werte importieren statt sie nochmal
     hartzukodieren
  c) eine Aenderung des Frostschutz-Wertes ein bewusster Code-Change
     mit Code-Review ist (Test schlaegt sonst Alarm).

WICHTIG fuer Pairing-Tag:
  Solange die Cloud-Regel-Engine leer ist, garantiert NUR der lokal im
  Vicki gesetzte Default-Setpoint Frostschutz. Beim Pairing den Vicki
  manuell auf >= FROST_PROTECTION_C konfigurieren.
"""

from decimal import Decimal
from typing import Final

# Absolute Untergrenze fuer jeden Sollwert. Niemals unterschreiten,
# unabhaengig von Belegung, Override, Nachtabsenkung.
# Quelle: STRATEGIE.md Regel 8 + Wasserrohr-Frostschutz im Hotelbereich.
FROST_PROTECTION_C: Final[Decimal] = Decimal("10.0")

# Absolute Obergrenze fuer Gast-Override. Schuetzt vor Energieverschwendung
# und Fehlbedienung. Quelle: STRATEGIE.md Regel 6.
MAX_GUEST_OVERRIDE_C: Final[Decimal] = Decimal("24.0")

# Absolute Untergrenze fuer Gast-Override. Unter diesem Wert greift die
# Belegungs-Regel oder Frostschutz, der Gast kann nicht runterregeln.
MIN_GUEST_OVERRIDE_C: Final[Decimal] = Decimal("19.0")

# Sprint 9.10 / 9.13c: Reading-Alter, ab dem ``open_window``- und
# ``attached_backplate``-Frames als veraltet gelten. 30 Min entspricht
# zwei verpassten Vicki-Periodic-Reports (Default 15 Min) — robust
# gegen Einzel-Ausfall, eng genug, dass nach Funkloch nicht stundenlang
# fehlhaltend. Geteilte Quelle fuer Layer 4 (Window + Detached) und den
# Hardware-Status-Endpoint (``/api/v1/devices/{id}/hardware-status``).
WINDOW_STALE_THRESHOLD_MIN: Final[int] = 30
