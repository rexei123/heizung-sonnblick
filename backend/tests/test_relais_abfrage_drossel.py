"""Die Drosselung der Zustandsabfrage ``0xB1`` (14.11.2026).

Reine Mechanik, ohne Datenbank und ohne echtes Redis — der Stand-in
folgt ``test_engine_lock._FakeRedis``, implementiert aber **die TTL
mit**, weil genau sie hier die Fachaussage traegt: nach Ablauf des
Fensters darf wieder gefragt werden.

**Warum diese Datei ueberhaupt existiert.** Seit dem 14.11. fragt der
Waechter auch dann nach dem Zustand, wenn AUS gewuenscht ist — also auch
bei einem Relais, das dauerhaft schweigt. Ohne Bremse waere das ein
Lese-Downlink je Minute und rund 16 Minuten Sendezeit am Tag fuer ein
einziges stummes Geraet. Die Bremse ist damit kein Beiwerk der
Aenderung, sondern ihre Voraussetzung.
"""

from __future__ import annotations

import logging

import pytest
import redis

from heizung.services import redis_client, relais_abfrage

FENSTER_S = 1500


class _FakeRedis:
    """``set(nx, ex)`` mit einer Uhr, die der Test stellt."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[str, float]] = {}
        self.jetzt = 0.0

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        gueltig_bis = self.store.get(key, (None, 0.0))[1]
        lebt = key in self.store and gueltig_bis > self.jetzt
        if nx and lebt:
            return None
        self.store[key] = (value, self.jetzt + (ex if ex is not None else 10**9))
        return True


class _KaputtesRedis:
    def set(self, *args: object, **kwargs: object) -> bool | None:
        raise redis.ConnectionError("Verbindung abgelehnt")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    r = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: r)
    return r


def test_die_erste_frage_im_fenster_darf(fake: _FakeRedis) -> None:
    assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is True


def test_die_zweite_frage_im_fenster_darf_nicht(fake: _FakeRedis) -> None:
    """**Der Kern.** Ein Durchlauf je Minute, eine Abfrage je Fenster."""
    assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is True
    for _ in range(24):
        fake.jetzt += 60
        assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is False


def test_nach_ablauf_des_fensters_darf_wieder_gefragt_werden(fake: _FakeRedis) -> None:
    """Sonst waere die Drosselung eine Stilllegung.

    Ein stummes Relais soll gefragt werden — nur nicht jede Minute. Ohne
    Ablauf bliebe es nach der ersten Abfrage fuer immer unbefragt, und
    der Waechter koennte seinen Zustand nie mehr erfahren.
    """
    assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is True
    fake.jetzt += FENSTER_S + 1
    assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is True


def test_das_fenster_gilt_je_geraet(fake: _FakeRedis) -> None:
    """Zwei Relais bremsen sich nicht gegenseitig.

    Ein gemeinsamer Schluessel waere die bequeme Variante und falsch: in
    einer Zone mit zwei Panels bliebe eines dauerhaft unbefragt.
    """
    assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is True
    assert relais_abfrage.darf_fragen(8, abstand_s=FENSTER_S) is True
    assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is False


def test_die_marke_tragt_das_fenster_als_ablauf(fake: _FakeRedis) -> None:
    """Die TTL ist der uebergebene Abstand, nicht eine Zahl im Modul.

    Steht hier eine eigene Zahl, verstellt das Veraltungs-Fenster die
    Drosselung nicht mehr — und beide Werte sehen plausibel aus (§5.53).
    """
    relais_abfrage.darf_fragen(7, abstand_s=300)
    _, gueltig_bis = fake.store["relais:zustandsabfrage:7"]
    assert gueltig_bis == pytest.approx(300.0)


def test_bei_redis_ausfall_wird_nicht_gefragt(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Die Gegenrichtung zu ``provision_lauf``, mit Begruendung.

    Eine unterbliebene Abfrage haelt ein Relais aus — kalter Raum. Eine
    ungedrosselte Abfrage verbrennt die Funkzeit des ganzen Hauses. Von
    beiden Fehlern ist der erste der billigere.
    """
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _KaputtesRedis())
    with caplog.at_level(logging.WARNING, logger="heizung.services.relais_abfrage"):
        assert relais_abfrage.darf_fragen(7, abstand_s=FENSTER_S) is False


def test_ein_fenster_von_null_oeffnet_keine_schleuse(fake: _FakeRedis) -> None:
    """``ex=0`` waere bei Redis ein Fehler, ``ex=None`` eine Marke ohne Ablauf.

    Beides ist schlechter als ein lautes Nein: ein Fenster von null
    Sekunden hiesse „jede Minute fragen", also genau der Zustand, gegen
    den dieses Modul gebaut ist.
    """
    assert relais_abfrage.darf_fragen(7, abstand_s=0) is False
    assert fake.store == {}, "und es wird auch nichts gemerkt"
