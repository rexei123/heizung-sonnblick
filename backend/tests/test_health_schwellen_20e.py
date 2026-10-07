"""Sprint 20e T6 — die Health-Altersschwellen stehen in den Settings.

**Was sich fachlich aendert.** Der Funkstille-Alarm haengt am Uebergang nach
``silent`` (``health_alerts.handle_silent_transitions``). Die Grenze stand
auf **24 h** — bei einem Keep-alive alle zehn Minuten sind das rund 144
verpasste Meldungen, bevor jemand eine Mail bekommt. In der Heizperiode ist
ein Zimmer, dessen Vicki seit dem Vormittag schweigt, ein Zimmer, das
niemand regelt. Die Vorgabe ist jetzt **3 h**.

**Was sich technisch aendert.** Die beiden Grenzen sind keine Konstanten
mehr, sondern Settings (Muster AE-73), und ``_basis_state_from_age`` nimmt
sie als Pflicht-Argument.

Reine Funktionstests, keine Datenbank — sie laufen auch lokal (B-18-5 ist
inzwischen ohnehin ueberholt, Docker laeuft wieder).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from heizung.config import Settings, get_settings
from heizung.tasks.health_tasks import (
    HealthSchwellen,
    _basis_state_from_age,
    health_schwellen,
)

NOW = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)
SCHWELLEN = HealthSchwellen(healthy_max_age=timedelta(hours=2), degraded_max_age=timedelta(hours=3))


def _alter(**kwargs: float) -> datetime:
    return NOW - timedelta(**kwargs)


# ---------------------------------------------------------------------------
# 1. Das Mapping an seinen Grenzen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("alter", "erwartet", "warum"),
    [
        ({"minutes": 1}, "healthy", "frisch"),
        ({"hours": 2}, "healthy", "genau auf der Grenze — ``<=``, also noch healthy"),
        ({"hours": 2, "seconds": 1}, "degraded", "eine Sekunde darueber"),
        ({"hours": 3}, "degraded", "genau auf der zweiten Grenze"),
        ({"hours": 3, "seconds": 1}, "silent", "eine Sekunde darueber — hier feuert der Alarm"),
        ({"hours": 25}, "silent", "weit darueber"),
    ],
)
async def test_mapping_an_den_grenzen(alter: dict[str, float], erwartet: str, warum: str) -> None:
    """Beide Grenzen sind **inklusiv** auf ihrer Seite.

    Die Sekunden-Schritte sind der eigentliche Test: ein Vergleich mit ``<``
    statt ``<=`` waere mit runden Altersangaben allein nicht zu
    unterscheiden, und er verschoebe den Alarm um ein ganzes Fenster.
    """
    assert _basis_state_from_age(_alter(**alter), NOW, SCHWELLEN) == erwartet, warum


async def test_kein_reading_ist_silent() -> None:
    """Ein Geraet ohne jedes Reading ist stumm, nicht unbekannt.

    Das ist die Entscheidung aus AE-53 und bleibt: ein neu angelegtes
    Geraet, das noch nie gefunkt hat, gehoert in denselben Alarm wie eines,
    das aufgehoert hat.
    """
    assert _basis_state_from_age(None, NOW, SCHWELLEN) == "silent"


# ---------------------------------------------------------------------------
# 2. Die Schwellen kommen aus den Settings
# ---------------------------------------------------------------------------


async def test_vorgabe_ist_drei_stunden_nicht_vierundzwanzig(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Der Wachposten fuer den Zweck von T6.**

    Ohne diesen Test waere ein Rueckfall auf 24 h — etwa durch einen
    kopierten ``.env``-Block von einem alten Stand — nicht zu bemerken: die
    Suite blieb gruen, und der Alarm kaeme wieder einen Tag zu spaet. Ein
    Alarm, der zu spaet kommt, ist von einem fehlenden Alarm nicht zu
    unterscheiden.
    """
    monkeypatch.delenv("HEALTH_DEGRADED_MAX_AGE_H", raising=False)
    monkeypatch.delenv("HEALTH_HEALTHY_MAX_AGE_H", raising=False)
    get_settings.cache_clear()

    s = health_schwellen()
    assert s.degraded_max_age == timedelta(hours=3)
    assert s.healthy_max_age == timedelta(hours=2)

    get_settings.cache_clear()


async def test_schwellen_folgen_der_umgebung(monkeypatch: pytest.MonkeyPatch) -> None:
    """Der Sinn der Umstellung: nachjustieren ohne Code-Aenderung.

    Die richtige Zahl haengt davon ab, wie oft im Haus Funkloecher
    auftreten, und das weiss man erst nach ein paar Wochen Betrieb.
    """
    monkeypatch.setenv("HEALTH_HEALTHY_MAX_AGE_H", "1")
    monkeypatch.setenv("HEALTH_DEGRADED_MAX_AGE_H", "6")
    get_settings.cache_clear()

    s = health_schwellen()
    assert s.healthy_max_age == timedelta(hours=1)
    assert s.degraded_max_age == timedelta(hours=6)
    # Und sie wirken auch: 90 Minuten sind mit dieser Konfiguration
    # ``degraded``, mit der Vorgabe waeren sie ``healthy``.
    assert _basis_state_from_age(_alter(minutes=90), NOW, s) == "degraded"

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 3. Der Start-Validator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("healthy", "degraded", "warum"),
    [
        (3, 3, "gleich: die Stufe degraded verschwindet, healthy wird zuerst geprueft"),
        (4, 3, "vertauscht: degraded liegt vor healthy"),
        (0, 3, "healthy unter 1 h"),
    ],
)
async def test_unsinnige_schwellen_verhindern_den_start(
    healthy: int, degraded: int, warum: str
) -> None:
    """**Start-Fehler, nicht Warnung.**

    Bei ``degraded <= healthy`` verschwindet die mittlere Stufe, und der
    Funkstille-Alarm feuerte bereits an der ``healthy``-Grenze — bei der
    Vorgabe also fuer jedes Geraet, das zwei Stunden in einem Funkloch
    steht. Nach einer Woche liest die Mails niemand mehr (§5.79).

    Ein Haus, dessen Alarm nach einem Tippfehler in der ``.env`` stumm das
    Falsche tut, ist schlechter bedient als eines, dessen API nicht
    startet. Der Fehler steht beim Hochfahren im Container-Log.
    """
    with pytest.raises(ValidationError) as exc:
        Settings(
            environment="test",
            health_healthy_max_age_h=healthy,
            health_degraded_max_age_h=degraded,
        )
    text = str(exc.value)
    assert "HEALTH_" in text, warum


async def test_gueltige_schwellen_werden_angenommen() -> None:
    """Gegenprobe: ohne sie waere ein Validator, der alles ablehnt, gruen."""
    s = Settings(
        environment="test",
        health_healthy_max_age_h=1,
        health_degraded_max_age_h=2,
    )
    assert s.health_healthy_max_age_h == 1
    assert s.health_degraded_max_age_h == 2
