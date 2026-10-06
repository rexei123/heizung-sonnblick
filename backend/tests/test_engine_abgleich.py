"""Sprint 20f (T3) — Drosselung und Zaehler des Engine-Abgleichs.

**Der Befund.** Die Hysterese vergleicht den neuen Sollwert mit dem **letzten
selbst gesendeten**, nicht mit dem, den das Geraet meldet
(``rules/engine.py:795-827``). Hat die Engine zuletzt 18 geschickt und will
wieder 18, ist ``delta = 0`` und sie schweigt — unabhaengig davon, was am
Geraet steht. Die Geraete **048** und **057** standen deshalb am 05.10.2026
nach einer Montage-Drehung auf 20 °C, waehrend der Engine-Soll 18 °C war und
kein Override existierte.

Der Abgleich sendet in so einem Fall nach. Diese Datei prueft die **Grenzen**,
und die sind kein Beiwerk: jeder Downlink ist eine Motorbewegung (§0 S4). Ein
Geraet an der Funkgrenze bestaetigt womoeglich nie — ohne Grenze wuerde es bei
jedem Tick angefunkt, also jede Minute, bis die Batterie leer ist. Die teure
Richtung des Fehlers ist hier nicht "sendet zu wenig", sondern "sendet
endlos".

Reine Logik mit einem Redis-Doppelgaenger, keine Datenbank — deshalb laufen
diese Tests auch lokal (B-18-5).
"""

from __future__ import annotations

from typing import Any

import pytest

from heizung.services import engine_abgleich

DEV = "70b3d52dd3033393"


class _FakeRedis:
    """In-Memory-Ersatz fuer ``redis.Redis``.

    Nur die Operationen, die ``engine_abgleich`` nutzt: ``set`` (mit
    ``nx``/``ex``), ``get``, ``incr``, ``expire``, ``delete``. TTL wird
    **nicht** nachgebildet — Ablauf wird im Test durch Loeschen simuliert, und
    was sonst zu pruefen bliebe, waere Redis selbst.

    ``expire`` zaehlt mit, weil ein Test genau darauf zielt: der Zaehler darf
    seine Frist nur **einmal** gesetzt bekommen, sonst wandert sie mit jedem
    Versuch nach hinten und laeuft nie ab.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expire_calls: list[tuple[str, int]] = []

    def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,  # noqa: ARG002
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def incr(self, key: str) -> int:
        neu = int(self.store.get(key, "0")) + 1
        self.store[key] = str(neu)
        return neu

    def expire(self, key: str, ttl: int) -> bool:
        self.expire_calls.append((key, ttl))
        return True

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: client)
    return client


# ---------------------------------------------------------------------------
# 1. Die Drosselung
# ---------------------------------------------------------------------------


def test_erster_abgleich_darf_senden(fake_redis: _FakeRedis) -> None:
    """Ohne Vorgeschichte wird gesendet — sonst wirkte der Fix nie."""
    assert engine_abgleich.darf_senden(DEV) is True


def test_zweiter_abgleich_im_fenster_darf_nicht(fake_redis: _FakeRedis) -> None:
    """Hoechstens **eine** Nachsendung je Geraet je 30 Minuten.

    Das ist die Grenze, die aus einem Fix keine Batterie-Falle macht. Der
    Engine-Tick laeuft jede Minute; ohne diese Zeile waere der Abgleich ein
    Downlink pro Minute, solange das Geraet nicht folgt.
    """
    assert engine_abgleich.darf_senden(DEV) is True

    assert engine_abgleich.darf_senden(DEV) is False
    assert engine_abgleich.darf_senden(DEV) is False


def test_nach_ablauf_der_sperre_darf_wieder(fake_redis: _FakeRedis) -> None:
    """Abgelaufene Sperre heisst: der naechste Versuch ist erlaubt.

    Der Ablauf wird hier durch Loeschen des Schluessels nachgebildet — den
    TTL selbst prueft Redis.
    """
    assert engine_abgleich.darf_senden(DEV) is True
    fake_redis.store.pop(engine_abgleich._drossel_key(DEV))

    assert engine_abgleich.darf_senden(DEV) is True


def test_drosselung_gilt_je_geraet(fake_redis: _FakeRedis) -> None:
    """Zwei Geraete sperren sich nicht gegenseitig.

    Bei 104 Vickis waere eine gemeinsame Sperre gleichbedeutend mit "der
    Abgleich wirkt fuer eines pro halbe Stunde" — also praktisch nie.
    """
    assert engine_abgleich.darf_senden(DEV) is True

    assert engine_abgleich.darf_senden("70b3d52dd3034de4") is True


def test_dev_eui_gross_klein_ist_derselbe_schluessel(fake_redis: _FakeRedis) -> None:
    """Gross- und Kleinschreibung der DevEUI darf die Sperre nicht umgehen.

    Die DevEUI kommt an verschiedenen Stellen unterschiedlich geschrieben
    (ChirpStack liefert sie klein, ``device.dev_eui`` ist klein, Handgriffe im
    RUNBOOK sind gemischt). Ein Schluessel, der beides unterscheidet, waere
    eine Drosselung, die man durch Tippen aushebelt.
    """
    assert engine_abgleich.darf_senden(DEV.upper()) is True

    assert engine_abgleich.darf_senden(DEV.lower()) is False


# ---------------------------------------------------------------------------
# 2. Der Zaehler
# ---------------------------------------------------------------------------


def test_nach_drei_versuchen_wird_nicht_mehr_gesendet(fake_redis: _FakeRedis) -> None:
    """Die zweite Grenze: nach ``MAX_VERSUCHE`` ist Schluss.

    Ohne sie wuerde ein Geraet an der Funkgrenze alle 30 Minuten dauerhaft
    angefunkt — langsamer als ohne Drosselung, aber ohne Ende.
    """
    for _ in range(engine_abgleich.MAX_VERSUCHE):
        engine_abgleich.versuch_gezaehlt(DEV)
    # Sperre ablaufen lassen, damit allein der Zaehler entscheidet.
    fake_redis.store.pop(engine_abgleich._drossel_key(DEV), None)

    assert engine_abgleich.versuche(DEV) == engine_abgleich.MAX_VERSUCHE
    assert engine_abgleich.darf_senden(DEV) is False


def test_erschoepfter_zaehler_verschiebt_das_zeitfenster_nicht(
    fake_redis: _FakeRedis,
) -> None:
    """Ein abgelehnter Aufruf setzt die Sperre **nicht**.

    Sonst haette jeder Tick, der ohnehin nicht senden darf, das Fenster des
    naechsten erlaubten Versuchs nach hinten geschoben — die Sperre waere
    dann dauerhaft gesetzt und der Zaehler koennte nach einer Behebung nie
    wieder zum Zug kommen.
    """
    for _ in range(engine_abgleich.MAX_VERSUCHE):
        engine_abgleich.versuch_gezaehlt(DEV)
    fake_redis.store.pop(engine_abgleich._drossel_key(DEV), None)

    assert engine_abgleich.darf_senden(DEV) is False

    assert engine_abgleich._drossel_key(DEV) not in fake_redis.store


def test_erfolg_setzt_den_zaehler_zurueck(fake_redis: _FakeRedis) -> None:
    """Meldet das Geraet den Soll, beginnt die Zaehlung von vorn.

    Das ist der Aufraeum-Pfad. Ohne ihn haette ein Geraet, das einmal drei
    Versuche gebraucht hat, fuer den Rest des Zaehler-Fensters keine mehr —
    auch nach einer behobenen Funkstoerung.
    """
    engine_abgleich.versuch_gezaehlt(DEV)
    engine_abgleich.versuch_gezaehlt(DEV)
    assert engine_abgleich.versuche(DEV) == 2

    engine_abgleich.erfolg_gemeldet(DEV)

    assert engine_abgleich.versuche(DEV) == 0


def test_zaehler_frist_wird_nur_einmal_gesetzt(fake_redis: _FakeRedis) -> None:
    """``expire`` nur beim ersten Hochzaehlen.

    Bei jedem Versuch gesetzt, wanderte die Frist mit — der Zaehler liefe nie
    ab, und ein Geraet waere nach drei Versuchen dauerhaft gesperrt, auch
    Tage spaeter.
    """
    engine_abgleich.versuch_gezaehlt(DEV)
    engine_abgleich.versuch_gezaehlt(DEV)
    engine_abgleich.versuch_gezaehlt(DEV)

    gesetzte = [k for k, _ in fake_redis.expire_calls]
    assert gesetzte == [engine_abgleich._zaehler_key(DEV)]


def test_zaehler_gilt_je_geraet(fake_redis: _FakeRedis) -> None:
    """Verbrauchte Versuche eines Geraets sperren kein anderes."""
    for _ in range(engine_abgleich.MAX_VERSUCHE):
        engine_abgleich.versuch_gezaehlt(DEV)

    assert engine_abgleich.versuche("70b3d52dd3034de4") == 0


# ---------------------------------------------------------------------------
# 3. Redis nicht erreichbar — hier wird NICHT gesendet
# ---------------------------------------------------------------------------


class _KaputtesRedis:
    """Wirft bei jeder Operation, wie ein nicht erreichbarer Redis."""

    def _boom(self, *_args: Any, **_kwargs: Any) -> None:
        import redis

        raise redis.ConnectionError("Redis nicht erreichbar (Test)")

    set = get = incr = expire = delete = _boom


@pytest.fixture
def kaputtes_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_abgleich.redis_client, "get_redis_client", lambda: _KaputtesRedis())


def test_ohne_redis_wird_nicht_gesendet(kaputtes_redis: None) -> None:
    """**Die Gegenrichtung zu ``alert_throttle``, und das ist Absicht.**

    Dort fuehrt ein Redis-Ausfall zu "lieber doppelt zustellen" — eine Mail
    doppelt kostet Aufmerksamkeit. Hier kostet ein Downlink ohne
    funktionierende Drosselung Batterie und Motorbewegungen, und zwar bei
    jedem Tick (§0 S4).

    Der Abgleich ist eine Nachbesserung, kein Sicherheitsmelder. Er darf
    warten, bis die Drosselung nachweisbar steht.
    """
    assert engine_abgleich.darf_senden(DEV) is False


def test_ohne_redis_bleiben_die_anderen_aufrufe_stumm(kaputtes_redis: None) -> None:
    """Kein Aufruf darf den Engine-Tick abbrechen.

    Der Abgleich laeuft mitten im Downlink-Pfad. Eine Ausnahme von hier
    wuerde die Zonen-Schleife verlassen und die Geraete der uebrigen Zonen
    ungeregelt lassen — dieselbe Begruendung wie bei der Zonen-Isolation in
    AE-54.
    """
    assert engine_abgleich.versuche(DEV) == 0
    assert engine_abgleich.versuch_gezaehlt(DEV) == 0
    engine_abgleich.erfolg_gemeldet(DEV)


# ---------------------------------------------------------------------------
# 4. Die Redis-Rueckgabe, versionsunabhaengig gedeutet (§5.80)
# ---------------------------------------------------------------------------
#
# Der Typ-Stub von redis-py sagt je nach Fassung ``int`` oder
# ``Awaitable[Any] | Any`` — derselbe synchrone Client, zwei Signaturen. Die
# erste Fassung dieses Moduls hatte deshalb eine Typ-Zusicherung, die lokal
# **notwendig** und in CI **redundant** war; mypy meldet beides als Fehler.
# Lokal gruen, CI rot, ohne eine Zeile Unterschied — genau §5.80.
#
# ``_zu_int`` nimmt ``object`` und entscheidet zur Laufzeit. Diese Tests
# halten die Laufzeit-Faelle fest, damit die Funktion nicht spaeter
# "vereinfacht" wird und dabei einen davon verliert.


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        (3, 3),
        ("3", 3),
        (b"3", 3),
        (0, 0),
        (True, 1),
    ],
)
def test_zu_int_deutet_alle_laufzeit_formen(roh: object, erwartet: int) -> None:
    """``int``, ``str`` und ``bytes`` — je nach ``decode_responses``."""
    assert engine_abgleich._zu_int(roh) == erwartet


@pytest.mark.parametrize("roh", ["", "x", b"", b"x", None, object()])
def test_zu_int_faellt_auf_den_standard_zurueck(roh: object) -> None:
    """Unlesbares darf die Engine nicht anhalten.

    Ein Zaehlerstand, der sich nicht deuten laesst, wirkt wie "noch kein
    Versuch". Das ist die vorsichtige Richtung: ob gesendet wird, entscheidet
    ``darf_senden``, und die prueft zusaetzlich die Sperre.
    """
    assert engine_abgleich._zu_int(roh) == 0


def test_zu_int_nimmt_einen_eigenen_standard() -> None:
    assert engine_abgleich._zu_int("keine zahl", standard=7) == 7
