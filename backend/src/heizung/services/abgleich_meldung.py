"""Betreff und Text fuer die Meldung „Geraet nimmt Befehle nicht an" (Sprint 25, T3).

**Warum ein eigenes Modul und nicht zwei f-Strings im Task.** Der Text ist
das Einzige, was der Hotelier von diesem Befund je zu sehen bekommt — die
Audit-Zeile liest niemand freiwillig. Er gehoert damit geprueft, und im
Task waere er nur ueber den Task pruefbar (dieselbe Begruendung wie bei
``funk_waechter.betreff`` / ``nachricht``).

Die Handlungsanweisung steht **vor** den Zahlen. Wer eine Mail ueber eine
Heizung liest, will zuerst wissen, ob er jetzt aufstehen muss.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class Befund:
    """Eine erschoepfte Abgleich-Lage, wie sie der Engine-Tick sieht."""

    #: Technische Kennung, fuer die Suche in ChirpStack.
    dev_eui: str
    #: Die Nummer auf dem Gehaeuse, falls vergeben — das ist, was am Geraet steht.
    hardware_nummer: str | None
    #: Zimmer und Zone als Text, wie die Oberflaeche sie nennt.
    zimmer: str | None
    zone: str | None
    #: Was das Geraet meldet, und was ihm zuletzt gesendet wurde.
    gemeldet_c: int
    gesendet_c: int
    #: Wunsch der Engine **jetzt**. Kann von ``gesendet_c`` abweichen — genau
    #: diese Abweichung war der Grund, dass der Befund frueher verschwand.
    engine_soll_c: int
    versuche: int
    #: Beginn der Episode (UTC).
    seit: datetime


def betreff(befund: Befund) -> str:
    wo = befund.hardware_nummer or befund.dev_eui
    ort = f" in {befund.zimmer}" if befund.zimmer else ""
    return f"Heizung Sonnblick: Geraet {wo}{ort} nimmt keine Befehle an"


def nachricht(befund: Befund, *, zeitzone: str) -> str:
    """Der Text sagt, was der Befund bedeutet — und was er **nicht** bedeutet."""
    tz = ZoneInfo(zeitzone)
    seit_txt = befund.seit.astimezone(tz).strftime("%d.%m.%Y %H:%M")
    jetzt_txt = datetime.now(tz=tz).strftime("%d.%m.%Y %H:%M")
    wo = befund.hardware_nummer or befund.dev_eui
    ort = " / ".join(t for t in (befund.zimmer, befund.zone) if t) or "ohne Zone"
    # Nur nennen, wenn er abweicht. Sonst stehen zwei gleiche Zahlen
    # untereinander und der Leser sucht den Unterschied.
    wunsch_zeile = (
        f"Wunsch der Engine jetzt: {befund.engine_soll_c} C\n"
        if befund.engine_soll_c != befund.gesendet_c
        else ""
    )

    return (
        f"Das Geraet {wo} ({ort}) uebernimmt den gesendeten Sollwert nicht. "
        f"Nach {befund.versuche} Versuchen wird nicht weiter gesendet.\n\n"
        f"WAS ZU TUN IST\n"
        f"Am Geraet nachsehen: sitzt der Kopf fest auf dem Ventil, ist die "
        f"Batterie frisch, blinkt es. Danach Funk pruefen (RUNBOOK "
        f"Paragraph 10ay). Ein Eingriff an der Heizung ist nicht noetig — "
        f"nach der Behebung regelt der Abgleich von selbst nach, es muss "
        f"nichts von Hand gesetzt werden.\n\n"
        f"DIE ZAHLEN (Stand {jetzt_txt})\n"
        f"Geraet meldet:           {befund.gemeldet_c} C\n"
        f"Zuletzt gesendet:        {befund.gesendet_c} C\n"
        f"{wunsch_zeile}"
        f"Erfolglose Versuche:     {befund.versuche}\n"
        f"Lage besteht seit:       {seit_txt}\n\n"
        f"WARUM DIESE MELDUNG NUR EINMAL KOMMT\n"
        f"Sie kommt einmal je Episode. Eine neue Episode beginnt erst, wenn "
        f"das Geraet einen gesendeten Sollwert **bestaetigt** hat, also einen "
        f"Uplink mit genau diesem Wert meldet. Dass die Engine inzwischen "
        f"etwas anderes will, beendet die Lage nicht.\n\n"
        f"WAS DIESE MELDUNG NICHT SAGT\n"
        f"Sie sagt nicht, dass das Zimmer kalt ist. Das Geraet heizt — nur "
        f"nach seinem eigenen Wert, nicht nach dem der Steuerung. Liegt "
        f"dieser Wert hoeher, ist das Zimmer zu warm statt zu kalt.\n"
    )
