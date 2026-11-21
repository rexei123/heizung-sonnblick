"""Meldung, wenn ein Relais sich selbst abgeschaltet hat (21.11.2026).

**Der Anlass.** Beim Bauen des Gehaeuse-Melders fiel auf, dass die Stufe
**darueber** ebenfalls stumm ist: loest der Ueberhitzungs-, Ueberstrom-,
Ueberspannungs- oder Ueberlastschutz des Geraets aus, dann

* schaltet das Geraet selbst ab,
* setzt ``relay_service.setze_schutz_sperre`` die Sperre
  (``device.protection_tripped_at``), und die Zone heizt nicht mehr,
* schreibt ``health_alerts.emit_relay_protection_alert`` einen
  **Logeintrag** — und damit endet es.

Niemand erfaehrt es. Die Sperre haelt, bis ein Administrator sie aufhebt;
bis dahin bleibt der Bereich kalt, und die einzige Spur ist eine Zeile im
Protokoll des Containers. Das ist derselbe Befund wie beim warmen
Gehaeuse, nur mit der schwereren Folge (Paragraph 5.76: die Mechanik war
gebaut, die Mitteilung fehlte).

Warum die Mail nicht im Uplink-Pfad sitzt
-----------------------------------------

Naheliegend waere, sie dort zu schicken, wo der Alarm entsteht — im
Subscriber, direkt nach dem Commit. Dagegen sprechen zwei Dinge:

1. ``mailer.send_mail`` ist **synchron** (SMTP). Im Subscriber laeuft es
   im Event-Loop, der die Uplinks aller Geraete annimmt; ein Mailserver,
   der zehn Sekunden braucht, haelt in dieser Zeit die ganze Anlage auf.
2. ``emit_relay_protection_alert`` sagt in seinem eigenen Docstring,
   warum es nur protokolliert: „Der Logeintrag darf nie ausfallen, weil
   eine Mail nicht zugestellt werden konnte."

Also wie bei jedem anderen Melder des Hauses: ein Beat-Task liest den
**Zustand** und verschickt. Der Umweg kostet hoechstens die Taktlaenge
und macht den Uplink-Pfad nicht von einem Mailserver abhaengig.

Was „einmal je Ereignis" hier heisst
------------------------------------

Das Ereignis ist der **Zeitpunkt** der Ausloesung, nicht die Dauer der
Sperre: ``device.protection_tripped_at``. Eine stehende Sperre wird von
einer erneuten Meldung nicht ueberschrieben (``relay_uplink``), der
Zeitpunkt ist also stabil, solange die Sperre steht. Verglichen wird er
mit dem Zeitpunkt im juengsten Audit-Eintrag dieses Geraets: gleich
heisst „schon gemeldet", verschieden heisst „neues Ereignis". Damit
bekommt auch ein Geraet, das nach dem Entsperren gleich wieder ausloest,
seine zweite Mail — und ein Geraet, dessen Sperre eine Woche steht,
genau eine.

**Keine Entwarnung.** Die Sperre hebt ein Administrator von Hand auf; wer
sie aufhebt, weiss es. Eine Mail darueber waere eine Mitteilung ueber die
eigene Handlung (Paragraph 5.79: jeder Melder muss sich seine
Aufmerksamkeit verdienen).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.device import Device
from heizung.models.enums import DeviceKind
from heizung.models.heating_zone import HeatingZone
from heizung.models.relay_reading import RelayReading
from heizung.models.room import Room

#: Die vier Schutzarten in Klartext. Die Marken sind die des Codec
#: (``mclimate-16aspm.js``, ``data.protection``) und landen ueber
#: ``relay_uplink`` unveraendert in ``device.protection_kind``.
#:
#: **Eine unbekannte Art ist kein Fehler**: sie sperrt genauso (siehe
#: ``relay_uplink`` — „Lieber eine Sperre zu viel"), und die Mail nennt
#: dann die Marke selbst. Diese Liste ist Uebersetzung, nicht Zulassung —
#: sonst waere ein neuer Firmware-Wert eine Mail, die nicht hinausgeht.
SCHUTZARTEN = {
    "overheating": "Ueberhitzung",
    "overvoltage": "Ueberspannung",
    "overcurrent": "Ueberstrom",
    "overpower": "Ueberlast",
}


@dataclass(frozen=True, slots=True)
class SchutzBefund:
    """Ein Relais mit stehender Schutz-Sperre."""

    device_id: int
    dev_eui: str
    label: str | None
    #: Zimmernummer bzw. Bereichsname. ``None``, wenn das Relais an
    #: keinem Zimmer haengt.
    ort: str | None
    zone_name: str | None
    #: Die Marke aus der Firmware. ``None`` heisst: die Sperre steht, aber
    #: das Geraet hat keine Art mitgeschickt.
    art: str | None
    #: Der Zeitpunkt der Ausloesung — **das Ereignis**. Nie ``None``: wer
    #: keine Sperre hat, kommt nicht in die Liste.
    ausgeloest_am: datetime
    #: Die juengste gemeldete Gehaeusetemperatur, als Zusammenhang.
    #:
    #: **Nicht die Temperatur der Ausloesung.** Die steht im Ereignis
    #: (``0x60`` Byte 2), und die Steuerung speichert sie nicht — sie
    #: steht nur im Protokoll. Die Mail sagt deshalb ausdruecklich
    #: „juengste Meldung" und behauptet keinen Messwert zum Vorfall
    #: (Paragraph 5.68).
    gehaeuse_wert: int | None
    gehaeuse_gemeldet_am: datetime | None

    @property
    def name(self) -> str:
        """Wie das Geraet in der Mail heisst."""
        return self.label or self.dev_eui

    @property
    def art_klartext(self) -> str:
        """Die Schutzart als Wort, oder die Marke selbst."""
        if self.art is None:
            return "unbekannt (das Geraet hat keine Art gemeldet)"
        return SCHUTZARTEN.get(self.art, self.art)


async def lies_schutzsperren(session: AsyncSession) -> list[SchutzBefund]:
    """Alle Relais mit stehender Schutz-Sperre.

    Gefiltert wird nur der Lebenszyklus (Paragraph 5.58): Relais, nicht
    ausgemustert. **Nicht** ``commissioned_at`` und **nicht**
    ``darf_schalten`` — ein Geraet, das sich abgeschaltet hat, ist ein
    Vorfall, auch wenn es noch nicht in Betrieb genommen wurde. Beim
    Eingangstest ist es sogar der wichtigere Fall.
    """
    zeilen = (
        await session.execute(
            select(
                Device.id,
                Device.dev_eui,
                Device.label,
                Device.protection_kind,
                Device.protection_tripped_at,
                HeatingZone.name,
                Room.number,
            )
            .select_from(Device)
            .outerjoin(HeatingZone, HeatingZone.id == Device.heating_zone_id)
            .outerjoin(Room, Room.id == HeatingZone.room_id)
            .where(
                Device.kind == DeviceKind.RELAY,
                Device.retired_at.is_(None),
                Device.protection_tripped_at.is_not(None),
            )
            .order_by(Device.id)
        )
    ).all()

    befunde: list[SchutzBefund] = []
    for device_id, dev_eui, label, art, ausgeloest_am, zone_name, room_number in zeilen:
        messung = (
            await session.execute(
                select(RelayReading.internal_temperature_raw, RelayReading.time)
                .where(
                    RelayReading.device_id == device_id,
                    RelayReading.internal_temperature_raw.is_not(None),
                )
                .order_by(RelayReading.time.desc())
                .limit(1)
            )
        ).first()
        befunde.append(
            SchutzBefund(
                device_id=device_id,
                dev_eui=dev_eui,
                label=label,
                ort=room_number,
                zone_name=zone_name,
                art=art,
                ausgeloest_am=ausgeloest_am,
                gehaeuse_wert=int(messung[0]) if messung else None,
                gehaeuse_gemeldet_am=messung[1] if messung else None,
            )
        )
    return befunde


def _ortsname(befund: SchutzBefund) -> str:
    """„Zone (Ort)", soweit vorhanden. Namen statt Ids."""
    teile = [t for t in (befund.zone_name, befund.ort) if t]
    if not teile:
        return "ohne Zone"
    if len(teile) == 1:
        return teile[0]
    return f"{teile[0]} ({teile[1]})"


def _zeit(wann: datetime | None, *, zeitzone: str) -> str:
    """Ortszeit, denn die Mail liest ein Mensch (Paragraph 5.65)."""
    if wann is None:
        return "unbekannt"
    return wann.astimezone(ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")


def betreff_alarm(befund: SchutzBefund) -> str:
    return f"Heizung Sonnblick: Relais {befund.name} hat sich abgeschaltet ({befund.art_klartext})"


def nachricht_alarm(befund: SchutzBefund, *, zeitzone: str) -> str:
    """Die Folge zuerst, die Zahlen danach, der Handgriff zuletzt."""
    gehaeuse = (
        "keine Meldung"
        if befund.gehaeuse_wert is None
        else (
            f"{befund.gehaeuse_wert} "
            f"(juengste Meldung, {_zeit(befund.gehaeuse_gemeldet_am, zeitzone=zeitzone)})"
        )
    )
    return (
        f"Das Relais {befund.name} ({_ortsname(befund)}) hat seinen "
        f"eigenen Schutz ausgeloest und abgeschaltet.\n\n"
        f"WAS DAS BEDEUTET\n"
        f"Der Bereich heizt nicht mehr. Die Steuerung hat das Relais "
        f"gesperrt, und die Sperre haelt, bis ein Administrator sie auf "
        f"der Geraeteseite aufhebt — auch dann, wenn sich das Geraet "
        f"laengst erholt hat. Das ist Absicht (S4): ohne Sperre waere der "
        f"Vorfall nach einer Minute unsichtbar.\n\n"
        f"DER STAND\n"
        f"Schutzart:        {befund.art_klartext}\n"
        f"Ausgeloest:       {_zeit(befund.ausgeloest_am, zeitzone=zeitzone)}\n"
        f"Gehaeusetemperatur: {gehaeuse}\n\n"
        f"WAS ZU TUN IST — in dieser Reihenfolge\n"
        f"1. Ursache suchen, nicht die Sperre aufheben. Bei Ueberhitzung "
        f"ist es der Einbauort (RUNBOOK Paragraph 10aj Schritt 0: nicht "
        f"neben oder ueber dem Panel, senkrecht einbauen), bei Ueberstrom "
        f"oder Ueberlast die angeschlossene Last.\n"
        f"2. Erst danach auf der Geraeteseite die Sperre aufheben. Vorher "
        f"schaltet der Regler in dieselbe Lage zurueck.\n"
        f"3. Loest es erneut aus, bleibt die Sicherung aus, bis der "
        f"Elektriker da war.\n\n"
        f"WAS DIESE MELDUNG NICHT IST\n"
        f"Keine Vermutung ueber die Temperatur im Augenblick der "
        f"Ausloesung. Die meldet das Geraet im Ereignis selbst, und die "
        f"Steuerung speichert sie nicht — die Zahl oben ist die juengste "
        f"regulaere Meldung.\n"
    )
