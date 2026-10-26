"""Die Fenstererkennung im Gerät: Ziele, Parameter, Befund (Sprint 23 T2).

**Was es schon gab und was fehlte.** Der Befehl ``0x45`` und die Abfrage
``0x46`` sind seit Sprint 9.11x.b gebaut, der Codec dekodiert die Antwort,
und ``scripts/activate_open_window_detection`` schaltet sie im Bulk ein.
Für die Testwoche aus dem Brief reichte das nicht, und zwar an vier
Stellen:

1. **Die Parameter standen fest** (1,5 °C / 10 min, hart im Skript). Der
   Brief verlangt 1,0 °C — und für die Messung T2.5 **0,2 °C auf genau
   einem Gerät**.
2. **Es gab keinen Weg, ein einzelnes Gerät zu adressieren.** Der
   Testplan nennt drei (105, 110, 306 Schlafzimmer), die Messung genau
   eines.
3. **Es gab keinen Weg, die Erkennung wieder auszuschalten.** Das
   Abbruchkriterium des Betreibers lautet: löst sie *einmal* durch unsere
   eigene Absenkung aus, wird sie auf **allen** Testgeräten abgeschaltet.
   Ohne Werkzeug war dieses Kriterium nicht ausführbar — ein
   Abbruchkriterium, das man nicht vollziehen kann, ist keines.
4. **Geräte auf „nur messen" waren nicht ausgenommen.** Die Auswahl war
   „Thermostat mit Zone"; die Vickis 027 und 056 liegen als Fühler im
   Raum und bekommen bewusst keine Befehle (S7, Sprint 24c). Ergänzung 2
   des Auftrags verlangt die Ausnahme ausdrücklich, **mit Test** — der
   steht in ``tests/test_fenstererkennung.py``.

**Warum ein Dienst und nicht nur ein Skript.** Die Auswahl der Ziele und
die Einordnung eines Fenster-Befundes sind prüfbare Entscheidungen; in
einem CLI-Modul wären sie nur über den CLI prüfbar. Der Dienst hier ist
ohne Downlink, ohne Netz und ohne Datenbank testbar, wo es geht.

**Die Parameter-Vorgabe ist bewusst nicht der empfindlichste Wert.** Der
Vicki-Sensor sitzt **am Heizkörper**: was er misst, folgt dem Ventil
stärker als dem Raum. Jede Absenkung, die *wir* schicken — Nacht,
Check-out, Fenster-Sicherheit — schließt das Ventil, der Heizkörper kühlt
ab, und der Sensor sieht einen schnellen Abfall. Bei einem kleinen Delta
hätten wir gute Aussichten, unsere **eigene** Nachtabsenkung als offenes
Fenster erkannt zu bekommen. Das ist §5.84 in anderer Gestalt: ein
Melder, dessen Messgröße von etwas anderem bewegt wird — hier nicht vom
Wetter, sondern von unserer eigenen Steuerhandlung.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)

#: Betriebswert aus dem Brief: 1,0 °C Delta, 10 Minuten Schließzeit.
#: **Nicht** der empfindlichste Wert — Begründung im Modul-Kopf.
OW_DELTA_BETRIEB: Decimal = Decimal("1.0")
OW_DAUER_MIN_BETRIEB: int = 10

#: Der Messwert für T2.5: das Minimum der Hersteller-Spanne. Er wird mit
#: Fehlalarmen antworten — das ist der Zweck, und er bleibt **nicht**
#: stehen. Die Messung beantwortet, gegen welchen Vorwert das Gerät
#: vergleicht; die Hersteller-Doku lässt das offen (Stand 22.10.2026).
OW_DELTA_MESSUNG: Decimal = Decimal("0.2")

#: Die drei Geräte des Testplans, als Bezeichnung. Absichtlich **keine**
#: DevEUIs im Code: die hängen an der Montage und ändern sich beim Tausch,
#: und eine DevEUI im Repo wäre eine Zusicherung über die Anlage (§5.68).
TESTPLAN_GERAETE: tuple[str, ...] = ("105", "110", "306 Schlafzimmer")


# ---------------------------------------------------------------------------
# Befund: hat die Erkennung ausgeloest, und war es unsere eigene Absenkung?
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Episode:
    """Ein Zeitraum, in dem ein Gerät ``open_window = true`` gemeldet hat."""

    device_id: int
    beginn: datetime
    ende: datetime
    #: Lag der **Beginn** in der Nachtabsenkung (Ortszeit)?
    in_absenkung: bool
    #: Temperatur am Beginn und zehn Minuten davor, wenn vorhanden.
    temp_beginn: Decimal | None
    temp_davor: Decimal | None

    @property
    def abfall_k(self) -> Decimal | None:
        """Wie viel es in den zehn Minuten davor kühler wurde."""
        if self.temp_beginn is None or self.temp_davor is None:
            return None
        return self.temp_davor - self.temp_beginn

    @property
    def trifft_abbruchkriterium(self) -> bool:
        """Ein Auslösen in der eigenen Absenkung beendet die Testwoche.

        Vorgabe des Betreibers (22.10.2026), und sie ist strenger als sie
        klingt: ein Fehlalarm heißt, dass Layer 4 ein Zimmer auf den
        Sicherheitswert zieht, während niemand ein Fenster geöffnet hat —
        bei einem belegten Zimmer in der Nacht. Eine Erkennung, die das
        kann, ist schlechter als keine.
        """
        return self.in_absenkung


def in_nachtfenster(zeitpunkt: datetime, *, start: time, ende: time, zone: str) -> bool:
    """Liegt der Zeitpunkt im Nachtfenster? **Ortszeit, nicht UTC.**

    Die Steuerung rechnet in Weltzeit, die Konfiguration ist Wanduhrzeit
    des Hauses. Wer ``zeitpunkt.time()`` direkt vergleicht, vergleicht
    UTC-Wanduhr gegen Ortszeit und liegt ein bis zwei Stunden daneben —
    genau §5.65, und hier wäre der Fehler besonders teuer: er würde
    Fehlalarme in der Absenkung als „außerhalb" einordnen und damit das
    Abbruchkriterium aushebeln.
    """
    lokal = zeitpunkt.astimezone(ZoneInfo(zone)).time()
    if start <= ende:
        return start <= lokal < ende
    # Über Mitternacht: 20:00–06:00 ist zwei Teilfenster.
    return lokal >= start or lokal < ende


def episoden(
    messwerte: Sequence[SensorReading],
    *,
    nacht_start: time,
    nacht_ende: time,
    zone: str,
    vorlauf: timedelta = timedelta(minutes=10),
) -> list[Episode]:
    """Fasst aufeinanderfolgende ``open_window = true`` zu Episoden zusammen.

    Erwartet die Messwerte **je Gerät aufsteigend nach Zeit**. Zeilen ohne
    das Feld (``None``) beenden eine Episode **nicht**: eine reine
    Befehlsantwort sagt nichts über das Fenster, und sie als „zu"
    auszulegen würde eine Episode in zwei zerlegen. Dieselbe Regel wie
    bei der Kindersicherung und beim Backplate-Zustand (24c).

    ``temp_davor`` ist der jüngste Messwert, der mindestens ``vorlauf``
    vor dem Beginn liegt — die Zahl, die den Fehlalarm erklärt. Ohne sie
    ist beim nächsten Versuch wieder alles offen (Vorgabe des Betreibers:
    „dokumentiert wird, bei welcher Gelegenheit es auslöste … nicht nur
    die Tatsache").
    """
    ergebnis: list[Episode] = []
    offen: dict[int, tuple[datetime, datetime]] = {}
    verlauf: dict[int, list[tuple[datetime, Decimal | None]]] = {}

    def _abschliessen(device_id: int) -> None:
        beginn, ende = offen.pop(device_id)
        reihe = verlauf.get(device_id, [])
        temp_beginn = next((t for z, t in reversed(reihe) if z <= beginn), None)
        temp_davor = next(
            (t for z, t in reversed(reihe) if z <= beginn - vorlauf),
            None,
        )
        ergebnis.append(
            Episode(
                device_id=device_id,
                beginn=beginn,
                ende=ende,
                in_absenkung=in_nachtfenster(beginn, start=nacht_start, ende=nacht_ende, zone=zone),
                temp_beginn=temp_beginn,
                temp_davor=temp_davor,
            )
        )

    for m in messwerte:
        verlauf.setdefault(m.device_id, []).append((m.time, m.temperature))
        if m.open_window is None:
            continue
        if m.open_window:
            if m.device_id in offen:
                beginn, _ = offen[m.device_id]
                offen[m.device_id] = (beginn, m.time)
            else:
                offen[m.device_id] = (m.time, m.time)
        elif m.device_id in offen:
            _abschliessen(m.device_id)

    # Was am Ende des Zeitraums noch offen ist, ist eine Episode ohne
    # Ende — sie wird gezeigt und nicht verschwiegen: ein gerade
    # laufender Fehlalarm ist der dringendere Fall.
    for device_id in list(offen):
        _abschliessen(device_id)

    ergebnis.sort(key=lambda e: (e.beginn, e.device_id))
    return ergebnis


async def lade_messwerte(
    session: AsyncSession,
    *,
    device_ids: Sequence[int],
    von: datetime,
    bis: datetime,
) -> list[SensorReading]:
    """Die Messwerte des Zeitraums, aufsteigend nach Gerät und Zeit."""
    if not device_ids:
        return []
    stmt = (
        select(SensorReading)
        .where(SensorReading.device_id.in_(list(device_ids)))
        .where(SensorReading.time >= von)
        .where(SensorReading.time <= bis)
        .order_by(SensorReading.device_id, SensorReading.time)
    )
    return list((await session.execute(stmt)).scalars().all())


def heute_text(tag: date) -> str:
    """Kalendertag als Text, ohne Zeitzonen-Rechnung (§5.74)."""
    return f"{tag.day:02d}.{tag.month:02d}.{tag.year}"
