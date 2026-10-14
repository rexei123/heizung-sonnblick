"""Sprint 21 T3 (B-20f-2) — eine Belegung ohne Zeitzone wird abgewiesen.

**Der Befund.** ``check_in``/``check_out`` waren als „timezone-aware"
**beschrieben**, aber nichts hat es geprueft. Ein ``curl`` mit
``"2026-10-05T14:00:00"`` ohne ``Z`` wurde angenommen, und was der Wert
dann bedeutet, entschied die Zeitzone der **Datenbanksitzung** — bei
UTC-Session zwei Stunden daneben.

Die Oberflaeche war nie betroffen (``toISOString()`` schreibt ``Z``).
Betroffen war der Weg ueber ``curl``, und **genau den nutzen die
RUNBOOK-Handgriffe**.

Das ist dieselbe Klasse wie der Import-Befund vom 26.09.2026 (§5.79): dort
war ein Zeitwert falsch **ausgelegt**, hier war er gar nicht **festgelegt**.
Und das eigentliche Problem ist die Beschreibung, die eine Eigenschaft
behauptet, die der Code nicht prueft — sie wird gelesen wie eine
Zusicherung (§5.20-Familie).

Diese Datei braucht keine Datenbank: geprueft wird das Schema, und zwar an
der Stelle, an der die Eingabe ankommt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from heizung.schemas.occupancy import OccupancyCreate

WIEN_SOMMER = timezone(timedelta(hours=2))


def test_naiver_check_in_wird_abgewiesen() -> None:
    """Ohne Zeitzone: 422 statt stiller Auslegung.

    Der Wert im Test ist der aus dem Backlog-Eintrag — die Zeichenkette,
    die vorher angenommen wurde.
    """
    with pytest.raises(ValidationError) as fehler:
        OccupancyCreate(
            room_id=1,
            check_in="2026-10-05T14:00:00",  # type: ignore[arg-type]
            check_out="2026-10-07T11:00:00Z",  # type: ignore[arg-type]
        )
    assert "check_in" in str(fehler.value)


def test_naiver_check_out_wird_abgewiesen() -> None:
    """Auch das zweite Feld, und einzeln geprueft.

    Ein Test, der beide Felder gleichzeitig naiv setzt, wuerde nicht
    zeigen, dass **jedes** von ihnen prueft — es genuegte, wenn eines
    anschlaegt.
    """
    with pytest.raises(ValidationError) as fehler:
        OccupancyCreate(
            room_id=1,
            check_in="2026-10-05T14:00:00Z",  # type: ignore[arg-type]
            check_out="2026-10-07T11:00:00",  # type: ignore[arg-type]
        )
    assert "check_out" in str(fehler.value)


def test_mit_z_wird_angenommen_und_behaelt_den_augenblick() -> None:
    """``Z`` ist der Normalfall der Oberflaeche und der RUNBOOK-Beispiele."""
    eingabe = OccupancyCreate(
        room_id=1,
        check_in="2026-10-15T07:00:00Z",  # type: ignore[arg-type]
        check_out="2026-10-18T16:00:00Z",  # type: ignore[arg-type]
    )
    assert eingabe.check_in == datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
    assert eingabe.check_out == datetime(2026, 10, 18, 16, 0, tzinfo=UTC)


def test_mit_versatz_bleibt_derselbe_augenblick() -> None:
    """``+02:00`` ist genauso gueltig wie ``Z`` — und meint dasselbe.

    Das ist der Punkt der Pruefung: nicht die Schreibweise ist gefordert,
    sondern dass der Augenblick eindeutig ist. ``14:00+02:00`` ist
    ``12:00Z``, und die Datenbank speichert in beiden Faellen denselben
    Zeitpunkt.
    """
    eingabe = OccupancyCreate(
        room_id=1,
        check_in="2026-07-15T14:00:00+02:00",  # type: ignore[arg-type]
        check_out="2026-07-18T10:00:00+02:00",  # type: ignore[arg-type]
    )
    assert eingabe.check_in == datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    assert eingabe.check_in.tzinfo is not None
    assert eingabe.check_in.utcoffset() == timedelta(hours=2), "der Versatz bleibt erhalten"


def test_reihenfolge_wird_weiterhin_geprueft() -> None:
    """Die Pruefung von T3 ersetzt die bestehende nicht.

    ``check_in >= check_out`` muss auch bei zwei gueltigen,
    zeitzonen-behafteten Werten abgewiesen werden — und zwar **nach** der
    Feldpruefung, sonst stuende im Fehler die Reihenfolge statt der
    fehlenden Zeitzone.
    """
    with pytest.raises(ValidationError) as fehler:
        OccupancyCreate(
            room_id=1,
            check_in=datetime(2026, 10, 7, 11, 0, tzinfo=WIEN_SOMMER),
            check_out=datetime(2026, 10, 5, 14, 0, tzinfo=WIEN_SOMMER),
        )
    assert "check_in muss vor check_out liegen" in str(fehler.value)
