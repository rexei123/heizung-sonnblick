"""Waechter fuer die Funkqualitaet des Hauses (Sprint 25 T6).

**Der Anlass, 04./05.11.2026.** Nach der Stromtrennung am UG65 (RUNBOOK
§10ay) kam das Gateway zurueck — und zwar **4 dB schlechter im RSSI und
2,3 dB im SNR**, hausweit. 38 von 103 Geraeten verloren ueber 3 dB, und
die drei mit der geringsten Reserve rutschten unter den Rauschboden:
Geraet 021 (Zimmer 107 Kinderzimmer) ging von 144 Uplinks am Tag bei SNR
+6,3 auf **6 am Tag** bei −9,7.

**Niemand hat es gemeldet.** Die Geraete waren ``health_state = healthy``,
weil sie ja noch sendeten; die Batterien waren in Ordnung; die
Uplink-Menge fiel hausweit nur von 605 auf 580 je Stunde. Gefunden wurde
es **einen Tag spaeter und zufaellig**, bei der Pruefung einer anderen
Hypothese. Das ist §5.76 woertlich: jeder Mechanismus war gruen, und die
Wirkung war es nicht.

Dieser Waechter ueberwacht die **Wirkung** — wie gut das Haus empfangen
wird — und nicht den Mechanismus.

Warum die Grundlinie nachlaeuft, und warum das der Kern ist
-----------------------------------------------------------

Der naheliegende Entwurf vergleicht die letzte Stunde mit einem
gleitenden Mehrtagesmittel. **Das funktioniert nicht**, und es ist beim
Entwerfen der Abfrage aufgefallen: ein Mittel, das die Stoerung schon
enthaelt, **verduennt sich selbst**. Gegen das 7-Tage-Mittel gerechnet
sagte der Befund vom 04.11. einen Tag spaeter „im Rahmen" bei −1,8 dB,
weil die 25 Stunden Stoerung im Mittel steckten. Ein Melder, der nach
zwei Tagen von selbst verstummt, ueberwacht nichts (§5.79).

Die Grundlinie **endet deshalb 24 Stunden vor jetzt**: die Stoerung
wandert erst nach ``grundlinie_tage`` hinein, der Melder haelt also eine
Woche statt einen Tag. Das ist eine Verschiebung des Problems, keine
Loesung — und sie steht in ``GRENZE`` unten ausdruecklich.

Warum ueber die Schnittmenge der Geraete
----------------------------------------

Das Hausmittel ueber **alle** Geraete waere manipulierbar durch den
Bestand: kommen fuenf Geraete in gut versorgten Zimmern dazu, **steigt**
das Mittel und verdeckt eine Verschlechterung. Gerechnet wird deshalb
nur ueber Geraete, die in **beiden** Fenstern vorkommen.

Und es ist das Mittel der **Geraete-Mittel**, nicht der Zeilen: ein
Geraet, das oefter sendet, soll nicht schwerer zaehlen. Sonst verschiebt
ein stilles Geraet — also genau das Symptom — das Ergebnis in die falsche
Richtung.

Was er nicht tut
----------------

* **Kein Eingriff in die Steuerung.** Rein lesend, kein Downlink, kein
  Sollwert, kein Setzen von Zustaenden am Geraet.
* **Keine Alarme je Geraet.** 107 einzelne Melder waeren Laerm, und ein
  einzelnes schwaches Geraet ist kein Vorfall. Das Hausmittel ist die
  richtige Ebene; die Aufschluesselung ist der Befehl in RUNBOOK §10ay
  Schritt 6.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from heizung.models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)

#: Abstand zwischen dem Ende der Grundlinie und *jetzt*.
#:
#: **Keine Einstellung, sondern eine Eigenschaft des Entwurfs.** Der
#: Abstand muss groesser sein als das Messfenster, sonst steckt die
#: Stoerung sofort in ihrer eigenen Vergleichsgroesse und der Melder
#: schweigt von der ersten Stunde an. 24 Stunden deckt zusaetzlich den
#: Tagesrhythmus ab: verglichen wird gegen ganze Tage, nicht gegen die
#: Nacht.
GRUNDLINIE_ABSTAND_H: int = 24

Stufe = Literal["warnung", "im_rahmen", "unbekannt"]

#: Gruende als snake_case-Marken — dieselbe Konvention wie die
#: ``detail``-Token der Engine-Schichten (§5.23).
GRUND_ZU_WENIG_DATEN = "zu_wenig_daten"
GRUND_KEINE_GRUNDLINIE = "keine_grundlinie"
GRUND_UNTER_SCHWELLE = "unter_schwelle"
GRUND_IM_RAHMEN = "im_rahmen"


@dataclass(frozen=True, slots=True)
class Kennzahlen:
    """Das Mittel der Geraete-Mittel in einem Zeitfenster."""

    snr_db: Decimal | None
    rssi_dbm: Decimal | None
    #: Summe der Meldungen aller beteiligten Geraete.
    meldungen: int
    #: Zahl der Geraete, die in **beiden** Fenstern vorkommen.
    geraete: int


@dataclass(frozen=True, slots=True)
class Schwellen:
    """Die Grenzen, gegen die beurteilt wird — Pflicht-Argument.

    **Kein Default.** Ein Default waere eine zweite Wahrheit neben den
    Settings und liefe beim ersten Nachjustieren stumm auseinander
    (§5.73, dieselbe Entscheidung wie bei den Batterie-Stufen).
    """

    warn_delta_db: Decimal
    min_meldungen: int
    min_geraete: int


@dataclass(frozen=True, slots=True)
class Befund:
    stufe: Stufe
    grund: str
    delta_snr_db: Decimal | None
    delta_rssi_db: Decimal | None
    fenster: Kennzahlen
    grundlinie: Kennzahlen

    @property
    def ist_warnung(self) -> bool:
        return self.stufe == "warnung"


def beurteile(fenster: Kennzahlen, grundlinie: Kennzahlen, schwellen: Schwellen) -> Befund:
    """Urteil aus zwei Fenstern — ohne Datenbank, ohne Netz, ohne Uhr.

    Reihenfolge der Pruefungen ist verbindlich:

    1. **zu wenig Daten** — vor allem anderen. Nach einem Gateway-Ausfall
       ist das Messfenster duenn, und ein Mittel aus zehn Meldungen ist
       Rauschen. Dann ``unbekannt``, **nicht** ``warnung``: ein Melder,
       der beim Ausfall des Messwegs Alarm schlaegt, meldet seinen
       eigenen Ausfall und verliert Gewicht (§5.79). Dieselbe Haltung wie
       ``BATTERY_MIN_SAMPLES`` (§5.73).
    2. **keine Grundlinie** — ein frisch aufgesetztes Haus hat keine
       sieben Tage Vergangenheit. Auch ``unbekannt``.
    3. **unter der Schwelle** — erst hier ``warnung``.
    """
    if (
        fenster.snr_db is None
        or fenster.meldungen < schwellen.min_meldungen
        or fenster.geraete < schwellen.min_geraete
    ):
        return Befund(
            stufe="unbekannt",
            grund=GRUND_ZU_WENIG_DATEN,
            delta_snr_db=None,
            delta_rssi_db=None,
            fenster=fenster,
            grundlinie=grundlinie,
        )

    if grundlinie.snr_db is None or grundlinie.geraete < schwellen.min_geraete:
        return Befund(
            stufe="unbekannt",
            grund=GRUND_KEINE_GRUNDLINIE,
            delta_snr_db=None,
            delta_rssi_db=None,
            fenster=fenster,
            grundlinie=grundlinie,
        )

    delta_snr = fenster.snr_db - grundlinie.snr_db
    delta_rssi = (
        fenster.rssi_dbm - grundlinie.rssi_dbm
        if fenster.rssi_dbm is not None and grundlinie.rssi_dbm is not None
        else None
    )

    # ``<= -schwelle``: die Schwelle selbst zaehlt als Befund. Bei 2,0 dB
    # Vorgabe und einem gemessenen Abstand von genau −2,0 dB soll gemeldet
    # werden — am 04.11. lagen die Stundenwerte bei −2,0 bis −2,4.
    if delta_snr <= -schwellen.warn_delta_db:
        return Befund(
            stufe="warnung",
            grund=GRUND_UNTER_SCHWELLE,
            delta_snr_db=delta_snr,
            delta_rssi_db=delta_rssi,
            fenster=fenster,
            grundlinie=grundlinie,
        )

    return Befund(
        stufe="im_rahmen",
        grund=GRUND_IM_RAHMEN,
        delta_snr_db=delta_snr,
        delta_rssi_db=delta_rssi,
        fenster=fenster,
        grundlinie=grundlinie,
    )


def _je_geraet(von: datetime, bis: datetime) -> Select[tuple[int, Decimal, Decimal, int]]:
    """Mittel je Geraet im Zeitraum ``[von, bis)``, nur Zeilen mit SNR."""
    return (
        select(
            SensorReading.device_id.label("device_id"),
            func.avg(SensorReading.snr_db).label("snr"),
            func.avg(SensorReading.rssi_dbm).label("rssi"),
            func.count().label("n"),
        )
        .where(SensorReading.time >= von)
        .where(SensorReading.time < bis)
        .where(SensorReading.snr_db.is_not(None))
        .group_by(SensorReading.device_id)
    )


async def lade_kennzahlen(
    session: AsyncSession,
    *,
    now: datetime,
    fenster_stunden: int,
    grundlinie_tage: int,
) -> tuple[Kennzahlen, Kennzahlen]:
    """Messfenster und Grundlinie, gerechnet ueber die **Schnittmenge**.

    Ein ``JOIN`` der beiden Aggregate je Geraet ist die Schnittmenge —
    Geraete, die nur in einem der Fenster vorkommen, fallen heraus. Das
    ist der Punkt (siehe Modul-Kopf) und nicht Zierde.
    """
    grundlinie_ende = now - timedelta(hours=GRUNDLINIE_ABSTAND_H)
    grundlinie_beginn = grundlinie_ende - timedelta(days=grundlinie_tage)

    f = _je_geraet(now - timedelta(hours=fenster_stunden), now).cte("fenster")
    g = _je_geraet(grundlinie_beginn, grundlinie_ende).cte("grundlinie")

    stmt = select(
        func.avg(f.c.snr),
        func.avg(f.c.rssi),
        func.coalesce(func.sum(f.c.n), 0),
        func.count(),
        func.avg(g.c.snr),
        func.avg(g.c.rssi),
        func.coalesce(func.sum(g.c.n), 0),
    ).select_from(f.join(g, f.c.device_id == g.c.device_id))

    zeile = (await session.execute(stmt)).one()
    f_snr, f_rssi, f_n, anzahl, g_snr, g_rssi, g_n = zeile

    fenster = Kennzahlen(
        snr_db=_als_decimal(f_snr),
        rssi_dbm=_als_decimal(f_rssi),
        meldungen=int(f_n or 0),
        geraete=int(anzahl or 0),
    )
    grundlinie = Kennzahlen(
        snr_db=_als_decimal(g_snr),
        rssi_dbm=_als_decimal(g_rssi),
        meldungen=int(g_n or 0),
        geraete=int(anzahl or 0),
    )
    return fenster, grundlinie


def _als_decimal(wert: object) -> Decimal | None:
    """``avg()`` liefert je Dialekt ``Decimal`` oder ``float``.

    Gerechnet wird in ``Decimal``, weil der Vergleich genau auf der
    Schwelle laeuft — dieselbe Begruendung wie bei den Batterie-Stufen
    (§5.73): 2.0 hat in IEEE-754 keine exakte Darstellung, und ein
    Abstand von genau −2,0 dB soll melden.
    """
    if wert is None:
        return None
    if isinstance(wert, Decimal):
        return wert
    return Decimal(str(wert))


async def pruefe_funkqualitaet(
    session: AsyncSession,
    schwellen: Schwellen,
    *,
    fenster_stunden: int,
    grundlinie_tage: int,
    now: datetime | None = None,
) -> Befund:
    """Laedt die beiden Fenster und beurteilt sie. **Schreibt nichts.**

    Der Versand und das Protokollieren liegen beim Aufrufer — dieselbe
    Trennung wie bei ``mailer`` neben ``mail_status`` und
    ``alert_throttle``: der Melder soll nichts versenden, und der Versand
    soll nichts messen.
    """
    jetzt = now or datetime.now(tz=UTC)
    fenster, grundlinie = await lade_kennzahlen(
        session,
        now=jetzt,
        fenster_stunden=fenster_stunden,
        grundlinie_tage=grundlinie_tage,
    )
    befund = beurteile(fenster, grundlinie, schwellen)
    logger.info(
        "funk_waechter stufe=%s grund=%s delta_snr=%s delta_rssi=%s "
        "fenster_snr=%s grundlinie_snr=%s meldungen=%s geraete=%s",
        befund.stufe,
        befund.grund,
        befund.delta_snr_db,
        befund.delta_rssi_db,
        fenster.snr_db,
        grundlinie.snr_db,
        fenster.meldungen,
        fenster.geraete,
    )
    return befund


# ---------------------------------------------------------------------------
# Mailtext
# ---------------------------------------------------------------------------


def betreff(befund: Befund) -> str:
    delta = befund.delta_snr_db
    zahl = f"{delta:.1f}" if delta is not None else "?"
    return f"Heizung Sonnblick: Funkqualitaet um {zahl} dB gefallen"


def nachricht(befund: Befund, *, zeitzone: str) -> str:
    """Der Text sagt, was zu tun ist — nicht nur, dass etwas ist.

    Die Handlungsanweisung steht bewusst **vor** den Zahlen: wer nachts
    geweckt wird, soll in der ersten Zeile lesen, wohin er gehen muss.
    """
    from zoneinfo import ZoneInfo

    jetzt = datetime.now(tz=ZoneInfo(zeitzone)).strftime("%d.%m.%Y %H:%M")
    delta = befund.delta_snr_db
    delta_txt = f"{delta:.1f} dB" if delta is not None else "unbekannt"
    rssi_delta = befund.delta_rssi_db
    rssi_txt = f"{rssi_delta:.1f} dB" if rssi_delta is not None else "unbekannt"

    return (
        f"Die Funkqualitaet im Haus ist gefallen: SNR {delta_txt} unter dem "
        f"Mittel der Vorwoche.\n\n"
        f"WAS ZU TUN IST\n"
        f"Der Verdacht geht zuerst an das Gateway, nicht an die Geraete. "
        f"Ein einzelnes schwaches Geraet erzeugt diese Meldung nicht — "
        f"gerechnet wird ueber das ganze Haus.\n"
        f"Die Schritte stehen in RUNBOOK Paragraph 10ay, Schritt 6: "
        f"Funkqualitaet pruefen, dann Antenne ansehen. "
        f"Den Antennenstecker nie loesen, solange das Gateway Strom hat.\n\n"
        f"DIE ZAHLEN ({jetzt})\n"
        f"SNR jetzt:        {befund.fenster.snr_db}\n"
        f"SNR Vorwoche:     {befund.grundlinie.snr_db}\n"
        f"Abstand SNR:      {delta_txt}\n"
        f"Abstand RSSI:     {rssi_txt}\n"
        f"Meldungen:        {befund.fenster.meldungen} von "
        f"{befund.fenster.geraete} Geraeten\n\n"
        f"WAS DIESE MELDUNG NICHT SAGT\n"
        f"Sie sagt nicht, dass Meldungen ausfallen. Am 04.11.2026 fiel die "
        f"Menge hausweit nur von 605 auf 580 Meldungen je Stunde — die "
        f"Verbindung stand, sie hatte nur 4 dB weniger Reserve. Ausgefallen "
        f"sind dabei die Geraete mit dem laengsten Weg.\n"
    )
