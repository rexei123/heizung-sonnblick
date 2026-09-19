"""Sprint 18 — Wiederholungsbremse und Engine-Dead-Man-Ping.

Reine Funktionstests, keine DB. Redis wird durch einen In-Memory-Stand-in
ersetzt; das Muster stammt aus ``test_engine_lock.py``.

Der Schwerpunkt liegt auf dem **Verhalten bei Redis-Ausfall**. Es ist hier
bewusst anders als bei ``resync_flag``: dort heisst "Redis weg" defensiv
``False`` (lieber kein Downlink), hier ``True`` (lieber eine Mail zu viel
als eine zu wenig). Wer das spaeter vereinheitlichen will, soll an diesen
Tests merken, dass der Unterschied Absicht war.
"""

from __future__ import annotations

from typing import Any

import pytest
import redis

from heizung.services import alert_throttle, redis_client


class _FakeRedis:
    """In-Memory-Stand-in. Kennt ``set(nx=, ex=)`` und ``delete``.

    Die TTL wird nicht simuliert — ein Test, der den Ablauf braucht, ruft
    ``reset`` statt zu warten.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.last_ttl: int | None = None

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        self.last_ttl = ex
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


class _BrokenRedis:
    """Wirft bei jedem Zugriff — steht fuer "Redis ist weg"."""

    def set(self, *args: Any, **kwargs: Any) -> None:
        raise redis.ConnectionError("simulierter Ausfall")

    def delete(self, *args: Any, **kwargs: Any) -> None:
        raise redis.ConnectionError("simulierter Ausfall")


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: fake)
    return fake


@pytest.fixture
def broken_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: _BrokenRedis())


# ---------------------------------------------------------------------------
# Bremse
# ---------------------------------------------------------------------------


def test_erster_alarm_geht_raus(fake_redis: _FakeRedis) -> None:
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is True


def test_zweiter_alarm_wird_gebremst(fake_redis: _FakeRedis) -> None:
    alert_throttle.should_send("device_silent", "aabb", ttl_s=100)
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is False


def test_verschiedene_geraete_bremsen_sich_nicht_gegenseitig(fake_redis: _FakeRedis) -> None:
    """Die Bremse gilt je Gegenstand, nicht global — sonst wuerde das erste
    stumme Geraet alle anderen verdecken."""
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is True
    assert alert_throttle.should_send("device_silent", "ccdd", ttl_s=100) is True


def test_verschiedene_gattungen_bremsen_sich_nicht_gegenseitig(fake_redis: _FakeRedis) -> None:
    assert alert_throttle.should_send("device_silent", "x", ttl_s=100) is True
    assert alert_throttle.should_send("import_stale", "x", ttl_s=100) is True


def test_gross_und_kleinschreibung_ist_derselbe_gegenstand(fake_redis: _FakeRedis) -> None:
    """DevEUIs tauchen mal in Gross-, mal in Kleinschreibung auf. Zwei
    Schreibweisen duerfen nicht zwei Mails erzeugen."""
    assert alert_throttle.should_send("device_silent", "AABB", ttl_s=100) is True
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is False


def test_reset_oeffnet_die_bremse_wieder(fake_redis: _FakeRedis) -> None:
    alert_throttle.should_send("device_silent", "aabb", ttl_s=100)
    alert_throttle.reset("device_silent", "aabb")
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is True


def test_ttl_wird_durchgereicht(fake_redis: _FakeRedis) -> None:
    alert_throttle.should_send("device_silent", "aabb", ttl_s=1234)
    assert fake_redis.last_ttl == 1234


def test_bei_redis_ausfall_wird_zugestellt(broken_redis: None) -> None:
    """Der bewusste Unterschied zu ``resync_flag.consume``.

    Faellt Redis aus, darf die Bremse den Alarm nicht mit abschalten. Eine
    verpasste Alarm-Mail ist teurer als eine doppelte.
    """
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is True
    assert alert_throttle.should_send("device_silent", "aabb", ttl_s=100) is True


def test_reset_bei_redis_ausfall_wirft_nicht(broken_redis: None) -> None:
    alert_throttle.reset("device_silent", "aabb")


# ---------------------------------------------------------------------------
# Engine-Dead-Man-Ping
# ---------------------------------------------------------------------------


def test_ping_ohne_url_macht_nichts(
    fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leere URL = Check aus. Es darf dann auch kein Redis-Schluessel
    entstehen, sonst blockierte ein deaktivierter Check spaeter den
    aktivierten."""
    from heizung.tasks import engine_tasks

    monkeypatch.setattr(engine_tasks, "get_settings", lambda: _settings(url=""))
    engine_tasks._ping_engine_healthcheck()

    assert fake_redis.store == {}


def test_ping_ruft_die_url_auf(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    from heizung.tasks import engine_tasks

    gerufen: list[str] = []
    monkeypatch.setattr(
        engine_tasks, "get_settings", lambda: _settings(url="http://monitor.test/abc")
    )
    monkeypatch.setattr(engine_tasks.httpx, "Client", _FakeClient(gerufen))

    engine_tasks._ping_engine_healthcheck()

    assert gerufen == ["http://monitor.test/abc"]


def test_ping_ist_gedrosselt(fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    """Der Beat feuert jede Minute, der Monitor erwartet alle 5 Minuten.
    Zwei Ticks hintereinander duerfen nur einen Ping erzeugen."""
    from heizung.tasks import engine_tasks

    gerufen: list[str] = []
    monkeypatch.setattr(
        engine_tasks, "get_settings", lambda: _settings(url="http://monitor.test/abc")
    )
    monkeypatch.setattr(engine_tasks.httpx, "Client", _FakeClient(gerufen))

    engine_tasks._ping_engine_healthcheck()
    engine_tasks._ping_engine_healthcheck()
    engine_tasks._ping_engine_healthcheck()

    assert len(gerufen) == 1


def test_ping_fehler_kippt_den_tick_nicht(
    fake_redis: _FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Der Monitor ist nicht erreichbar — der Engine-Takt muss trotzdem
    weiterlaufen. Ein Ueberwachungswerkzeug darf nie das kaputtmachen, was
    es ueberwacht."""
    from heizung.tasks import engine_tasks

    monkeypatch.setattr(
        engine_tasks, "get_settings", lambda: _settings(url="http://monitor.test/abc")
    )
    monkeypatch.setattr(engine_tasks.httpx, "Client", _ExplodingClient)

    engine_tasks._ping_engine_healthcheck()  # wirft nicht


def test_ping_bei_redis_ausfall_pingt_jedes_mal(
    broken_redis: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Redis greift die Drosselung nicht. Das ist hingenommen: der
    Monitor zaehlt nur, ob ueberhaupt etwas ankommt."""
    from heizung.tasks import engine_tasks

    gerufen: list[str] = []
    monkeypatch.setattr(
        engine_tasks, "get_settings", lambda: _settings(url="http://monitor.test/abc")
    )
    monkeypatch.setattr(engine_tasks.httpx, "Client", _FakeClient(gerufen))

    engine_tasks._ping_engine_healthcheck()
    engine_tasks._ping_engine_healthcheck()

    assert len(gerufen) == 2


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


class _Settings:
    def __init__(self, url: str) -> None:
        self.healthcheck_engine_url = url


def _settings(*, url: str) -> _Settings:
    return _Settings(url)


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Callable, die sich wie ``httpx.Client`` benutzen laesst und die
    aufgerufenen URLs mitschreibt."""

    def __init__(self, sink: list[str]) -> None:
        self.sink = sink

    def __call__(self, *args: Any, **kwargs: Any) -> _FakeClient:
        return self

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        self.sink.append(url)
        return _FakeResponse()


class _ExplodingClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _ExplodingClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def get(self, url: str) -> None:
        raise OSError("Monitor nicht erreichbar")
