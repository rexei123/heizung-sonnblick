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
