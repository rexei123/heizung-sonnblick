"""Jedes ``Decimal``-Feld einer API-Antwort muss als **Zahl** ankommen.

**Der Vorfall, 07.10.2026 15:00.** ``/devices`` war nach dem Deploy von
Sprint 20e T7/T10 nicht mehr benutzbar:

    Application error: a client-side exception
    TypeError: a.toFixed is not a function

Ursache: ``DeviceRead.valve_delta_k`` ist ``Decimal | None`` und stand nicht
im ``field_serializer``. Pydantic serialisiert ein ``Decimal`` ohne Eintrag
als JSON-**String** (``"5.40"``), der TypeScript-Spiegel sagt aber
``number | null``, und das Frontend ruft ``.toFixed()`` darauf.

Gemessen, nicht vermutet:

    valve_delta_k          -> '5.40'   (String)
    battery_voltage_median -> 3.1      (Zahl)

**Warum die Tests das nicht gefangen haben.** Die Backend-Tests pruefen
Objekte, nicht JSON. Die e2e-Mocks trugen Zahlen — also meine Annahme
darueber, was das Backend sendet, statt dessen tatsaechlicher Ausgabe. Das
ist §5.79 Teil zwei: ein Erwartungswert, der nicht aus der Spezifikation
kommt, prueft nur, dass sich nichts geaendert hat.

**Deshalb prueft diese Datei die Modelle gegen sich selbst.** Sie liest die
Feld-Annotationen und verlangt fuer jedes ``Decimal``-Feld, dass
``model_dump(mode="json")`` eine Zahl liefert. Ein neues ``Decimal``-Feld
ohne Serializer macht damit einen Test rot und nicht die Produktion.

Der Weg ueber die Annotationen ist der Punkt: eine handgepflegte Liste der
zu pruefenden Felder waere dieselbe Falle eine Ebene hoeher — man muesste
sie beim Hinzufuegen eines Felds anfassen, und genau das ist hier
unterblieben.
"""

from __future__ import annotations

import typing
from decimal import Decimal

import pytest
from pydantic import BaseModel

from heizung.schemas.dashboard import DashboardKpiRead
from heizung.schemas.device import (
    DeviceActiveOverrideRead,
    DeviceLatestReadingRead,
    DeviceRead,
)
from heizung.schemas.sensor_reading import SensorReadingRead

# Die Antwort-Modelle, deren Zahlen im Frontend gerechnet oder formatiert
# werden. Wer ein weiteres Modell mit ``Decimal``-Feldern an die Oberflaeche
# haengt, traegt es hier ein — und bekommt die Pruefung dann geschenkt.
MODELLE: list[type[BaseModel]] = [
    DeviceRead,
    DeviceLatestReadingRead,
    DeviceActiveOverrideRead,
    SensorReadingRead,
    DashboardKpiRead,
]


def _ist_decimal_feld(annotation: object) -> bool:
    """``Decimal`` oder ``Decimal | None``, egal wie geschrieben."""
    if annotation is Decimal:
        return True
    return Decimal in typing.get_args(annotation)


def _decimal_felder(modell: type[BaseModel]) -> list[str]:
    return [
        name for name, feld in modell.model_fields.items() if _ist_decimal_feld(feld.annotation)
    ]


def test_mindestens_ein_decimal_feld_wird_gefunden() -> None:
    """Gegenprobe gegen einen Test, der nichts prueft.

    Ohne diese Zeile waere die ganze Datei gruen, wenn ``_ist_decimal_feld``
    kaputtgeht oder die Modelle umbenannt werden — und das ist die Sorte
    Test, die man fuer Sicherheit haelt und die nichts tut (§5.55 ist die
    Schwester: ein gruener Lauf, der nichts geprueft hat).
    """
    gefunden = {m.__name__: _decimal_felder(m) for m in MODELLE}
    assert gefunden["DeviceRead"], gefunden
    assert "valve_delta_k" in gefunden["DeviceRead"], (
        "Das Feld aus dem Vorfall vom 07.10. muss von der Pruefung erfasst sein."
    )


# Die zu pruefenden Paare werden beim Sammeln gebildet, nicht im Test
# uebersprungen.
#
# Die erste Fassung parametrisierte ueber die Modelle und rief
# ``pytest.skip`` fuer eines ohne ``Decimal``-Felder. Das war bequem und hat
# den Merge-Anker beschaedigt: "``collected`` = ``passed`` + ``xfailed``, und
# ``skipped`` = 0" ist nach §5.81 der Beleg, dass eine Suite wirklich
# gelaufen ist. Ein absichtlicher Skip macht genau diese Null unbrauchbar —
# ein echter Skip, etwa weil die Datenbank fehlt, wuerde darin nicht mehr
# auffallen.
#
# Also keine Ausnahme im Anker, sondern eine Parametrisierung ohne leere
# Faelle. Dass es mindestens ein Paar gibt, sichert
# ``test_mindestens_ein_decimal_feld_wird_gefunden``.
DECIMAL_PAARE: list[tuple[type[BaseModel], str]] = [
    (modell, feld) for modell in MODELLE for feld in _decimal_felder(modell)
]

OPTIONALE_PAARE: list[tuple[type[BaseModel], str]] = [
    (modell, feld)
    for modell, feld in DECIMAL_PAARE
    if type(None) in typing.get_args(modell.model_fields[feld].annotation)
]


def _id(paar: tuple[type[BaseModel], str]) -> str:
    return f"{paar[0].__name__}.{paar[1]}"


@pytest.mark.parametrize("paar", DECIMAL_PAARE, ids=_id)
def test_decimal_feld_serialisiert_als_zahl(paar: tuple[type[BaseModel], str]) -> None:
    """**Der Wachposten.** Kein ``Decimal`` darf als String nach draussen.

    ``model_construct`` statt des Konstruktors: es umgeht die Validierung
    und laesst damit ein Teilmodell zu. Hier wird die **Serialisierung**
    geprueft, nicht die Eingabe — und ein vollstaendiges ``DeviceRead`` mit
    allen Pflichtfeldern aufzubauen waere Arbeit, die mit jedem neuen Feld
    erneut anfaellt.
    """
    modell, name = paar
    # Ein Wert, der als String auffaellt: zwei Nachkommastellen, wie
    # ``Numeric(5,2)`` ihn aus der Datenbank liefert.
    objekt = modell.model_construct(**{name: Decimal("5.40")})
    wert = objekt.model_dump(mode="json")[name]

    assert isinstance(wert, int | float), (
        f"{modell.__name__}.{name} serialisiert als {type(wert).__name__} "
        f"({wert!r}). Das Frontend rechnet damit und stuerzt ab. "
        f"Feld in den field_serializer des Modells aufnehmen."
    )
    assert wert == pytest.approx(5.4)


@pytest.mark.parametrize("paar", OPTIONALE_PAARE, ids=_id)
def test_none_bleibt_none(paar: tuple[type[BaseModel], str]) -> None:
    """``None`` darf nicht zu ``0.0`` werden.

    Bei den Ventil-Hinweisen traegt das Bedeutung: ``valve_delta_k`` ist
    ``None``, wenn es nichts zu melden gibt (``ok``/``unbekannt``). Eine 0
    waere dort die Aussage "Abstand genau null" — und die Oberflaeche
    schreibt sie in den Hinweistext.
    """
    modell, name = paar
    objekt = modell.model_construct(**{name: None})

    assert objekt.model_dump(mode="json")[name] is None, f"{modell.__name__}.{name}"
