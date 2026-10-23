"""Enums für das Domain-Model.

Alle Enums werden als String-Enums in PostgreSQL gespeichert
(native_enum=False), damit spätere Erweiterungen via Migration einfach sind.

Bei SQLAlchemy-``Enum``-Spalten muss ``values_callable=_enum_values``
gesetzt werden, damit die ``.value`` (lowercase-Strings) persistiert
werden — nicht die Python-``.name`` (UPPERCASE).
"""

import enum
from collections.abc import Iterable


def _enum_values(enum_cls: Iterable[enum.Enum]) -> list[str]:
    """Helper für ``sa.Enum(..., values_callable=_enum_values)``.

    SQLAlchemy liefert die Enum-Klasse selbst als Iterable der Member.
    """
    return [member.value for member in enum_cls]


class RoomStatus(enum.StrEnum):
    """Operativer Status eines Zimmers.

    OCCUPIED und RESERVED steuern Vorheizen/Absenken, CLEANING hält
    komfortabel, BLOCKED setzt den Raum aus der Regel-Engine heraus
    (nur Frostschutz aktiv).
    """

    VACANT = "vacant"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    CLEANING = "cleaning"
    BLOCKED = "blocked"


class HeatingZoneKind(enum.StrEnum):
    """Funktionaler Zonen-Typ. Steuert teilweise Regel-Defaults."""

    BEDROOM = "bedroom"
    BATHROOM = "bathroom"
    LIVING = "living"
    HALLWAY = "hallway"
    OTHER = "other"


class Orientation(enum.StrEnum):
    """Himmelsrichtung der Außenfassade. Für spätere KI-Optimierung
    (solare Gewinne bei Südzimmern)."""

    NORTH = "N"
    NORTH_EAST = "NE"
    EAST = "E"
    SOUTH_EAST = "SE"
    SOUTH = "S"
    SOUTH_WEST = "SW"
    WEST = "W"
    NORTH_WEST = "NW"


class DeviceKind(enum.StrEnum):
    THERMOSTAT = "thermostat"
    SENSOR = "sensor"
    # Sprint 24: Schaltaktor. Stellt, misst aber keine Raumtemperatur —
    # den Istwert liefert in derselben Zone ein Thermostat mit der Rolle
    # "nur messen" (``Device.measure_only``).
    #
    # Die Spalte ``device.kind`` ist ``VARCHAR(20)`` **ohne**
    # CHECK-Beschraenkung (am Schema geprueft, AE-78 §1) — dieser Wert
    # braucht deshalb keine Migration. Das ist der Gegenfall zu
    # ``OverrideSource``, wo eine CHECK liegt und ein neuer Wert ohne
    # Migration beim ersten Insert scheitert (§5.45, Migration 0029).
    RELAY = "relay"


class WatchdogStrategy(enum.StrEnum):
    """Wie ein Relais eingeschaltet gehalten wird (S2, Sprint 24).

    ``EXPIRE_AND_RESEND`` ist die **Vorgabe**: ein ``0x57`` geht nur
    heraus, wenn der zuletzt **bestaetigte** Zustand AUS ist. Laeuft der
    Timer ab, meldet das Geraet den Wechsel, und erst danach wird bei
    Bedarf neu gesetzt. Damit haengt die Sicherheit nicht an der
    Bedeutung von „previous state" — die Doku definiert sie nicht
    (AE-78 §4), und ein Nachsetzen auf ein laufendes EIN koennte den
    Rueckfallzustand auf EIN festschreiben.

    ``REFRESH`` setzt den Timer periodisch neu, waehrend das Relais EIN
    ist. Das ist die kuerzere Abschaltzeit und die riskantere Variante;
    sie ist gebaut, aber je Geraet zu waehlen und **standardmaessig
    aus**. Sie darf erst benutzt werden, wenn die Messung T3.0 ergeben
    hat, dass „previous state" der dauerhafte Zustand ist und nicht der
    unmittelbar vorhergehende.
    """

    EXPIRE_AND_RESEND = "expire_and_resend"
    REFRESH = "refresh"


class DeviceVendor(enum.StrEnum):
    """Hersteller — relevant für den passenden Treiber in der
    Geräte-Abstraktionsschicht."""

    MCLIMATE = "mclimate"
    MILESIGHT = "milesight"
    MANUAL = "manual"  # Platzhalter für manuelle Eingabe / Tests


class OccupancySource(enum.StrEnum):
    MANUAL = "manual"
    PMS = "pms"


class UserRole(enum.StrEnum):
    """Benutzer-Rolle (Sprint 9.17, AE-50).

    Zwei Rollen-Modell:
      - ``admin``       — kann alles (Stammdaten, Konfiguration,
                          User-Verwaltung).
      - ``mitarbeiter`` — kann Belegungen + Manual-Overrides setzen,
                          lesen alles ausser User-Verwaltung.

    Owner / Hotelier / Techniker / Reception aus dem alten
    SPRINT-PLAN sind bewusst nicht abgebildet (YAGNI, AE-50 AE-2).
    """

    ADMIN = "admin"
    MITARBEITER = "mitarbeiter"


class RuleConfigScope(enum.StrEnum):
    """Gültigkeitsbereich einer Regelkonfiguration.

    Auflösung bei Regel-Evaluierung: ROOM > ROOM_TYPE > GLOBAL > hardcoded.
    """

    GLOBAL = "global"
    ROOM_TYPE = "room_type"
    ROOM = "room"


class CommandReason(enum.StrEnum):
    """Warum wurde ein Steuerbefehl erzeugt. Reine Audit-Information."""

    OCCUPIED_SETPOINT = "occupied_setpoint"
    VACANT_SETPOINT = "vacant_setpoint"
    NIGHT_SETBACK = "night_setback"
    DAY_SETBACK = "day_setback"
    PREHEAT_CHECKIN = "preheat_checkin"
    CHECKOUT_SETBACK = "checkout_setback"
    WINDOW_OPEN = "window_open"
    DEVICE_DETACHED = "device_detached"
    INFERRED_WINDOW = "inferred_window"
    GUEST_OVERRIDE = "guest_override"
    LONG_VACANT = "long_vacant"
    FROST_PROTECTION = "frost_protection"
    # SUMMER_MODE ist seit Sprint 9.16 (AE-49) deprecated zugunsten von
    # SCENARIO_SUMMER_MODE. Wert bleibt im Enum, damit historische
    # event_log-Eintraege weiterhin lesbar sind.
    SUMMER_MODE = "summer_mode"
    SCENARIO_SUMMER_MODE = "scenario_summer_mode"
    MANUAL = "manual"
    MANUAL_EVENT = "manual_event"
    # Sprint 12a T4 (AE-58): Auto-Detect-Override-Pfad blockt silent in
    # VACANT-Raeumen bzw. bei Fenster offen. event_log-Audit-Eintrag mit
    # diesen Reasons. KEIN control_command-Eintrag (Vicki bekommt keinen
    # Downlink).
    DEVICE_BLOCKED_VACANT = "device_blocked_vacant"
    DEVICE_BLOCKED_WINDOW = "device_blocked_window"
    # Sprint 12c (AE-58): Uebersteuerungs-Sperre pro Zimmer aktiv -> Vicki-
    # Drehring wird silent geskippt. Off-pipeline Audit via
    # ``EventLogLayer.MANUAL_OVERRIDE_BLOCKED``.
    DEVICE_BLOCKED_ROOM_BLOCKED = "device_blocked_room_blocked"
    # Sprint 15c (AE-63): Vicki-Reboot via fcnt-Reset erkannt -> Auto-
    # Detect-Adopt uebersprungen, Re-Sync auf Engine-Soll im naechsten
    # Engine-Tick erzwungen. Off-pipeline Audit via
    # ``EventLogLayer.REBOOT_RESYNC``. Auch fuer den erzwungenen
    # Re-Sync-Downlink im ``control_command.reason``.
    REBOOT_RESYNC = "reboot_resync"


class ScenarioScope(enum.StrEnum):
    """Gueltigkeitsbereich einer Szenario-Aktivierung.

    Aufloesung: ROOM > ROOM_TYPE > GLOBAL.
    Analog zu RuleConfigScope, aber separat damit Engine die beiden
    orthogonalen Konzepte (Settings vs. Szenarien) klar trennt.
    """

    GLOBAL = "global"
    ROOM_TYPE = "room_type"
    ROOM = "room"


class OverrideSource(enum.StrEnum):
    """Quelle einer Manual-Override-Aktion (Sprint 9.9 Engine Layer 3).

    **Ablauf, Stand 20.10.2026 (Fix A, Entscheidung des Betreibers).**

    ``device``        Drehring-Drehung am Vicki, erkannt ueber Setpoint-Diff
                      ``last_engine_setpoint`` vs. ``target_temperature`` aus
                      Periodic-Report (AE-45). Ablauf **24 h**.
    ``device_manual``  Handverstellung am Drehrad, **ausdruecklich** gemeldet
                      ueber einen ``0x28``-Frame (FW >= 3.5, Sprint 20f T1/T2).
                      Ablauf **24 h**.
    ``frontend_24h``  Rezeption setzt "fuer 24 Stunden". Ablauf now + 24 h.
    ``frontend_checkout``  Rezeption setzt "bis Check-out". Ablauf
                      ``next_checkout_at``.
    ``frontend_4h``   **Historisch.** Rezeption setzte "fuer 4 Stunden",
                      Ablauf now + 4 h. Seit Fix A nicht mehr waehlbar.
    ``frontend_midnight``  **Historisch.** Rezeption setzte "bis
                      Mitternacht", Ablauf heute 23:59 lokal. Seit Fix A
                      nicht mehr waehlbar.

    **Jede Drehung beginnt die 24 Stunden neu**, weil jede Drehung einen
    **neuen** Eintrag anlegt und Layer 3 den juengsten nimmt. Das ist keine
    zusaetzliche Mechanik, sondern eine Eigenschaft des Modells — und sie
    gehoert hierher, damit niemand sie fuer eine Luecke haelt und eine
    Verlaengerungs-Logik dazubaut.

    **Die Abreise beendet jeden Override**, unabhaengig vom Ablauf
    (``override_pms_hook.auto_revoke_on_checkout``). Mit 24 h kann ein
    Override den Check-out jetzt **ueberleben**, und damit ist dieser Haken
    nicht mehr Beiwerk, sondern die einzige Stelle, die ihn dann beendet.

    **Warum ``device`` und ``device_manual`` weiter getrennt sind, obwohl
    beide 24 h bekommen.** Der Unterschied war nie nur der Ablauf: ``device``
    ist ein *abgeleiteter* Befund (kann auch Reboot-Drift oder ein verlorener
    Downlink sein), ``device_manual`` eine *Meldung des Geraets*. Im Audit
    sind das verschiedene Aussagen, und die Vorrang-Reihenfolge nutzt sie:
    ``device_manual`` liegt **ueber** ``device`` (die ausdrueckliche Meldung
    schlaegt die Vermutung) und **unter** allen ``frontend_*`` (Mitarbeiter
    schlaegt Gast, AE-58). Sie zusammenzulegen, weil zufaellig derselbe
    Ablauf gilt, wuerde diese Unterscheidung wegwerfen.

    **Was Fix A geaendert hat und was nicht.** Geaendert: der Ablauf von
    ``device`` (vorher bis Check-out, bis zu 7 Tage Hard-Cap) und von
    ``device_manual`` (vorher 4 h). Nicht geaendert: Bestandszeilen — ein
    vorhandener Eintrag behaelt sein ``expires_at``.
    """

    DEVICE = "device"
    DEVICE_MANUAL = "device_manual"
    FRONTEND_24H = "frontend_24h"
    FRONTEND_CHECKOUT = "frontend_checkout"
    #: Historisch, seit Fix A (20.10.2026) nicht mehr waehlbar. Bleibt als
    #: Wert erhalten, weil die Historie ihre Etiketten braucht.
    FRONTEND_4H = "frontend_4h"
    FRONTEND_MIDNIGHT = "frontend_midnight"


class EventLogLayer(enum.StrEnum):
    """Welche Engine-Pipeline-Schicht hat den Eintrag erzeugt.

    Pro Engine-Evaluation entsteht ein Eintrag pro durchlaufener Schicht.
    AUDIT auch wenn unveraendert: KI-Vorbereitung gemaess AE-08.
    """

    SUMMER_MODE_FAST_PATH = "summer_mode_fast_path"
    BASE_TARGET = "base_target"
    TEMPORAL_OVERRIDE = "temporal_override"
    MANUAL_OVERRIDE = "manual_override"
    GUEST_OVERRIDE = "guest_override"
    WINDOW_SAFETY = "window_safety"
    DEVICE_DETACHED = "device_detached"
    HARD_CLAMP = "hard_clamp"
    INFERRED_WINDOW_OBSERVATION = "inferred_window_observation"
    # Sprint 12a T4 (AE-58): off-pipeline Audit-Schicht fuer device_adapter
    # Pre-Insert-Skip (VACANT-Raum oder Fenster offen). Erzeugt synthetische
    # evaluation_id, gehoert KEINER Engine-Tick-Evaluation an.
    MANUAL_OVERRIDE_BLOCKED = "manual_override_blocked"
    # Sprint 15c (AE-63): off-pipeline Audit-Schicht fuer device_adapter
    # Reboot-Gate. Vicki-Reboot via fcnt-Reset erkannt, Auto-Detect-Adopt
    # uebersprungen + Redis-Re-Sync-Flag gesetzt. Synthetische
    # evaluation_id (uuid4), gehoert KEINER Engine-Tick-Evaluation an.
    REBOOT_RESYNC = "reboot_resync"
