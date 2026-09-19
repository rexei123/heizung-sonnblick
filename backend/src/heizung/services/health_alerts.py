"""Health-Alarme: Logger je Geraet, eine Sammelmail je Lauf (AE-53).

Zwei Ebenen, bewusst getrennt:

- **Logger** — einer je Uebergang, bedingungslos, fuer jede Stufe. Das ist
  die Spur in journalctl, nach ``dev_eui`` und ``reason`` grep-bar. Sie
  entsteht auch dann, wenn keine Alarm-Adresse hinterlegt ist, die
  Wiederholungsbremse greift oder der Versand scheitert.
- **Mail** — **eine je Lauf**, nicht eine je Geraet.

Warum eine Sammelmail (Sprint 18 / T2)
--------------------------------------

Der Health-Beat laeuft alle 5 Minuten ueber alle Geraete. Faellt das
Gateway aus oder geht im Haus der Strom, kippen **alle** Vickis im selben
Tick auf ``silent`` — bei 104 Geraeten waeren das 104 Einzelmails in einer
Minute. Kein Postfach ueberlebt das, und schlimmer: die eine Information,
auf die es ankommt ("alle auf einmal, also eher Gateway als Batterie"),
geht in der Menge unter.

Die Sammelmail kehrt das um. Eine Mail, eine Liste, und die Menge selbst
ist die Diagnose.

Die Wiederholungsbremse bleibt **pro Geraet** und wirkt als Entprellung:
nur Geraete, die sie passieren, kommen in die Liste. Ein Geraet, das seit
Stunden stumm ist und bei jedem Flankenwechsel erneut gemeldet wuerde,
taucht hoechstens alle sechs Stunden auf. Bleibt nach dem Filtern nichts
uebrig, geht **keine** Mail raus — auch wenn der Lauf Uebergaenge hatte.

Nebeneffekt, der die Bremse absichert: faellt Redis aus, laesst
``alert_throttle`` alles durch (siehe dort). Ohne Aggregation waeren das
104 Mails. Mit Aggregation ist es **eine**.

Stufen
------

- **Stufe 1** (degraded, 2-24 h offline): kein Alarm, nur ``health_state``.
- **Stufe 2** (silent durch > 24 h offline): Logger **und** Sammelmail.
- **Stufe 3** (silent durch >= 10 implausible Readings in 24 h): Logger,
  **keine** Mail. Bewusst aus Sprint 18 herausgehalten — ein Geraet, das
  sendet aber Unsinn misst, ist ein anderer Vorgang als eines, das
  schweigt, und braucht einen eigenen Text samt eigener Handlungsempfehlung.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from heizung.rules.constants import DEFAULT_HOTEL_TIMEZONE
from heizung.services import alert_throttle, mailer

logger = logging.getLogger(__name__)

REASON_OFFLINE = "offline_24h"
REASON_IMPLAUSIBLE = "implausible_readings_24h"

# Ab dieser Anzahl wechselt die Mail in die Kurzform. Begruendung: eine
# Liste mit Einzelheiten zu 15 Geraeten liest niemand auf dem Telefon, und
# sie ist auch nicht noetig — bei so vielen gleichzeitig ist die Ursache
# ohnehin gemeinsam (Gateway, Strom, Netz), nicht geraetespezifisch.
KURZFORM_AB = 10


def emit_health_alert(
    *,
    level: int,
    device_id: int,
    dev_eui: str,
    reason: str,
    device_name: str | None = None,
    room_name: str | None = None,
    zone_name: str | None = None,
    triggered_at: datetime | None = None,
    last_uplink_at: datetime | None = None,
    implausible_count_24h: int | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Schreibt genau einen strukturierten WARNING-Eintrag. Versendet nichts.

    Args:
        level: ``2`` (offline_24h) oder ``3`` (implausible_readings_24h).
        device_id: Device-Primary-Key fuer DB-Korrelation.
        dev_eui: Device-EUI fuer Container-Log-grep.
        reason: ``"offline_24h"`` oder ``"implausible_readings_24h"`` —
            die Strings sind verbindlich (kommen aus AE-53 + T5).
        device_name: Geraete-Bezeichnung (``device.label``).
        room_name: Zimmer-Nummer/-Name (``room.number``) via JOIN.
        zone_name: Heizzonen-Name (``heating_zone.name``) via JOIN.
        triggered_at: Zeitpunkt der Health-Eval (UTC).
        last_uplink_at: Letztes Uplink-Reading des Devices (UTC).
        implausible_count_24h: Implausible-Counter-Stand (Stufe-3-Trigger).
        context: Optionaler Zusatz-Kontext (Backward-Compat-Slot).

    Der Versand liegt in ``handle_silent_transitions``. Diese Trennung ist
    Absicht: der Logger-Eintrag darf nie ausfallen, weil eine Mail nicht
    zugestellt werden konnte.
    """
    logger.warning(
        "health_alert",
        extra={
            "level": level,
            "device_id": device_id,
            "dev_eui": dev_eui,
            "reason": reason,
            "device_name": device_name,
            "room_name": room_name,
            "zone_name": zone_name,
            "triggered_at": triggered_at.isoformat() if triggered_at is not None else None,
            "last_uplink_at": last_uplink_at.isoformat() if last_uplink_at is not None else None,
            "implausible_count_24h": implausible_count_24h,
            "context": context or {},
        },
    )


def handle_silent_transitions(transitions: list[dict[str, Any]], *, recipient: str | None) -> int:
    """Logger je Uebergang, danach **eine** Sammelmail fuer Stufe 2.

    Der Einstiegspunkt fuer ``health_tasks``. Reihenfolge ist verbindlich:
    erst alle Logger-Eintraege, dann der Versand. Ein haengender SMTP-Server
    darf nicht dazu fuehren, dass die Haelfte der Uebergaenge keine Spur
    hinterlaesst.

    :param transitions: Uebergaenge ``vorher != silent -> jetzt == silent``,
        wie ``health_tasks`` sie sammelt.
    :param recipient: Alarm-Adresse aus ``global_config.alert_email``.
        ``None`` oder leer heisst "keine hinterlegt" — dann bleibt es bei
        den Logger-Eintraegen.
    :return: Anzahl der Geraete in der versandten Mail. ``0`` heisst: keine
        Mail verschickt. Rueckgabe dient dem Aufrufer als Kennzahl fuer
        seinen eigenen Log-Eintrag.
    """
    for t in transitions:
        emit_health_alert(
            level=3 if t["reason"] == REASON_IMPLAUSIBLE else 2,
            device_id=t["device_id"],
            dev_eui=t["dev_eui"],
            reason=t["reason"],
            device_name=t.get("device_name"),
            room_name=t.get("room_name"),
            zone_name=t.get("zone_name"),
            triggered_at=t.get("triggered_at"),
            last_uplink_at=t.get("last_uplink_at"),
            implausible_count_24h=t.get("implausible_count_24h"),
        )

    if not recipient:
        return 0

    # Nur Stufe 2. Stufe 3 bleibt in diesem Sprint Logger-only.
    kandidaten = [t for t in transitions if t["reason"] != REASON_IMPLAUSIBLE]

    # Die Bremse wird fuer JEDES Geraet einzeln gefragt, auch wenn am Ende
    # eine gemeinsame Mail rausgeht. Sonst wuerde ein einziges frisches
    # Geraet die Sperre aller anderen aufheben und sie erneut auflisten.
    zu_melden = [
        t
        for t in kandidaten
        if alert_throttle.should_send(
            alert_throttle.KIND_DEVICE_SILENT,
            t["dev_eui"],
            ttl_s=alert_throttle.TTL_DEVICE_SILENT_S,
        )
    ]

    if not zu_melden:
        if kandidaten:
            logger.info(
                "health_alert_sammelmail_entfaellt",
                extra={"kandidaten": len(kandidaten), "grund": "alle gebremst"},
            )
        return 0

    result = mailer.send_mail(
        recipient=recipient,
        subject=_subject(zu_melden),
        body=_body(zu_melden),
    )
    if not result.sent:
        logger.warning(
            "health_alert_sammelmail_nicht_zugestellt",
            extra={"anzahl": len(zu_melden), "grund": result.reason, "detail": result.detail},
        )
    return len(zu_melden)


# ---------------------------------------------------------------------------
# Textbausteine
# ---------------------------------------------------------------------------


def _ort(t: dict[str, Any]) -> str:
    """Zimmer und Zone als eine lesbare Ortsangabe."""
    room_name = t.get("room_name")
    zone_name = t.get("zone_name")
    if room_name and zone_name:
        return f"Zimmer {room_name} / {zone_name}"
    if room_name:
        return f"Zimmer {room_name}"
    if zone_name:
        return str(zone_name)
    return "ohne Zuordnung (Pool)"


def _zimmer(t: dict[str, Any]) -> str:
    """Nur die Zimmernummer — fuer die Kurzform."""
    return str(t.get("room_name") or "Pool")


def _wann(ts: datetime | None) -> str:
    if ts is None:
        return "unbekannt"
    return ts.astimezone(ZoneInfo(DEFAULT_HOTEL_TIMEZONE)).strftime("%d.%m.%Y %H:%M")


def _subject(zu_melden: list[dict[str, Any]]) -> str:
    """Der Betreff muss auf einem Sperrbildschirm lesbar sein."""
    if len(zu_melden) == 1:
        t = zu_melden[0]
        geraet = t.get("device_name") or "Thermostat"
        return f"Heizung Sonnblick: {geraet} meldet sich nicht — {_ort(t)}"
    return f"Heizung Sonnblick: {len(zu_melden)} Thermostate melden sich nicht"


def _body(zu_melden: list[dict[str, Any]]) -> str:
    """Klartext fuer den Hotelier. Kein Fachjargon, ein konkreter Rat."""
    anzahl = len(zu_melden)
    zeilen: list[str] = []

    if anzahl >= KURZFORM_AB:
        zimmer = sorted({_zimmer(t) for t in zu_melden})
        zeilen += [
            f"{anzahl} Thermostate haben sich seit über 24 Stunden nicht gemeldet.",
            "",
            "Betroffene Zimmer:",
            "  " + ", ".join(zimmer),
            "",
            "Bei dieser Anzahl ist die Ursache fast immer gemeinsam, nicht",
            "gerätebezogen. Zuerst prüfen, in dieser Reihenfolge:",
            "",
            "  1. Ist das LoRaWAN-Gateway erreichbar und am Strom?",
            "  2. Gab es einen Stromausfall im Haus?",
            "  3. Betrifft es ein einzelnes Geschoss? Dann eher Funk als Gerät.",
            "",
            "Die Einzelheiten je Gerät stehen in der Geräte-Übersicht der",
            "Oberfläche. Sie hier aufzulisten würde die Nachricht unlesbar machen.",
        ]
    elif anzahl == 1:
        t = zu_melden[0]
        zeilen += [
            f"Gerät:   {t.get('device_name') or '(unbenannt)'}  ({t['dev_eui']})",
            f"Ort:     {_ort(t)}",
            f"Erkannt: {_wann(t.get('triggered_at'))}",
            "",
            f"Seit über 24 Stunden kein Lebenszeichen. "
            f"Letzte Meldung: {_wann(t.get('last_uplink_at'))}.",
            "",
            "Wahrscheinlichste Ursachen, in dieser Reihenfolge:",
            "  1. Batterien leer — zwei Mignon-Zellen (AA), Wechsel dauert eine Minute.",
            "  2. Gerät wurde abgenommen und liegt irgendwo.",
            "  3. Funkverbindung gestört (selten, betrifft dann meist mehrere Geräte",
            "     im selben Geschoss).",
        ]
    else:
        zeilen += [
            f"{anzahl} Thermostate haben sich seit über 24 Stunden nicht gemeldet:",
            "",
        ]
        for t in sorted(zu_melden, key=lambda x: (_zimmer(x), x["dev_eui"])):
            name = t.get("device_name") or "(unbenannt)"
            zeilen.append(f"  {_ort(t)}")
            zeilen.append(f"    Gerät {name} ({t['dev_eui']})")
            zeilen.append(f"    Letzte Meldung: {_wann(t.get('last_uplink_at'))}")
            zeilen.append("")
        zeilen += [
            "Wahrscheinlichste Ursachen, in dieser Reihenfolge:",
            "  1. Batterien leer — zwei Mignon-Zellen (AA) je Gerät.",
            "  2. Gerät wurde abgenommen.",
            "  3. Funkverbindung gestört — betrifft dann meist mehrere Geräte",
            "     im selben Geschoss. Liegen die Zimmer oben beieinander,",
            "     ist das die wahrscheinlichste Ursache.",
        ]

    zeilen += [
        "",
        "Die Heizung regelt in den betroffenen Zonen weiter nach dem letzten",
        "bekannten Stand. Es wird nichts abgeschaltet.",
        "",
        "Ein Gerät erscheint frühestens nach 6 Stunden erneut in einer solchen",
        "Meldung, solange es stumm bleibt.",
    ]
    return "\n".join(zeilen)
