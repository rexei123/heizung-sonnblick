"""Sprint 20a — Tests fuer ``services/deploy_lock.py``.

Ohne DB und ohne echten Redis: ein In-Memory-Stand-in ersetzt
``redis_client.get_redis_client``. Geprueft wird die Mechanik, auf die sich
``deploy-pull.sh`` verlaesst — vor allem die beiden Faelle, in denen eine
Sperre schadet statt zu schuetzen:

* Sie bleibt liegen, obwohl der Lauf vorbei ist -> jeder Deploy blockiert.
* Sie steht nicht, obwohl der Lauf laeuft -> der Deploy bricht ihn ab.
"""

from __future__ import annotations

from typing import Any

import pytest
import redis

from heizung.services import deploy_lock, redis_client


class _FakeRedis:
    """In-Memory-Stand-in. Nur ``set``/``delete``/``ttl``/``get``.

    TTL wird als Zahl mitgeschrieben, nicht abgelaufen — die Tests pruefen,
    **welche** TTL gesetzt wurde, nicht ob Redis sie durchsetzt.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.set_calls: list[tuple[str, int | None]] = []

    def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        self.set_calls.append((key, ex))
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> int:
        self.ttls.pop(key, None)
        return 1 if self.store.pop(key, None) is not None else 0

    def ttl(self, key: str) -> int:
        if key not in self.store:
            return -2  # redis-py: Key fehlt
        return self.ttls.get(key, -1)  # -1: Key ohne TTL


class _KaputterRedis(_FakeRedis):
    """Wirft bei jeder Operation — Redis nicht erreichbar."""

    def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        raise redis.ConnectionError("kein Redis")

    def delete(self, key: str) -> int:
        raise redis.ConnectionError("kein Redis")

    def ttl(self, key: str) -> int:
        raise redis.ConnectionError("kein Redis")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    r = _FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: r)
    return r


@pytest.fixture
def kaputt(monkeypatch: pytest.MonkeyPatch) -> _KaputterRedis:
    r = _KaputterRedis()
    monkeypatch.setattr(redis_client, "get_redis_client", lambda: r)
    return r


def test_key_name_ist_verbindlich() -> None:
    """``deploy-pull.sh`` fragt diesen String ab — er ist Schnittstelle.

    Wer ihn hier aendert, muss das Skript mitaendern. Der Test ist die
    Stelle, an der das auffaellt; im Skript steht der Name als Literal und
    kein Import kann ihn pruefen.
    """
    assert deploy_lock.DEPLOY_LOCK_KEY == "heizung:lock:inbound_test"


def test_acquire_setzt_key_mit_ttl(fake: _FakeRedis) -> None:
    assert deploy_lock.acquire(ttl_s=900) is True
    assert deploy_lock.DEPLOY_LOCK_KEY in fake.store
    assert fake.ttls[deploy_lock.DEPLOY_LOCK_KEY] == 900


def test_acquire_setzt_immer_eine_ttl(fake: _FakeRedis) -> None:
    """Eine Sperre ohne TTL waere der schlimmere Fehler.

    Ohne Ablauf blockiert ein abgestuerzter Testlauf jeden Deploy, bis
    jemand den Key von Hand loescht — und niemand weiss, dass er das muesste.
    """
    deploy_lock.acquire(ttl_s=60)
    assert all(ex is not None for _, ex in fake.set_calls)


def test_refresh_verlaengert_und_stellt_wieder_her(fake: _FakeRedis) -> None:
    """``refresh`` nutzt ``set``, nicht ``expire`` — mit Absicht.

    Ist der Key zwischendurch weg (Redis-Neustart, TTL knapp verpasst),
    legt ``set`` ihn wieder an. ``expire`` wuerde auf einen fehlenden Key
    scheitern, und der Lauf liefe ungeschuetzt weiter, ohne dass es jemand
    merkt.
    """
    deploy_lock.acquire(ttl_s=100)
    fake.store.clear()
    fake.ttls.clear()

    assert deploy_lock.refresh(ttl_s=300) is True
    assert fake.store[deploy_lock.DEPLOY_LOCK_KEY]
    assert fake.ttls[deploy_lock.DEPLOY_LOCK_KEY] == 300


def test_release_loescht(fake: _FakeRedis) -> None:
    deploy_lock.acquire(ttl_s=100)
    assert deploy_lock.release() is True
    assert deploy_lock.DEPLOY_LOCK_KEY not in fake.store


def test_release_ohne_bestehende_sperre_ist_erfolg(fake: _FakeRedis) -> None:
    """Der gewuenschte Endzustand ist erreicht — das ist kein Fehler.

    Ein ``False`` hier waere eine Falschmeldung im Abschlussbericht: der
    Lauf haette „Sperre konnte nicht freigegeben werden" gemeldet, obwohl
    sie weg ist.
    """
    assert deploy_lock.release() is True


def test_held_until_nennt_den_ablauf(fake: _FakeRedis) -> None:
    deploy_lock.acquire(ttl_s=600)
    bis = deploy_lock.held_until()
    assert bis is not None
    # 600 s in der Zukunft, mit Toleranz fuer die Testlaufzeit.
    from datetime import UTC, datetime

    rest = (bis - datetime.now(tz=UTC)).total_seconds()
    assert 590 < rest <= 600


def test_held_until_ohne_sperre_ist_none(fake: _FakeRedis) -> None:
    assert deploy_lock.held_until() is None


def test_held_until_bei_key_ohne_ttl_ist_none(fake: _FakeRedis) -> None:
    """``ttl`` = -1 heisst „Key da, aber ohne Ablauf" — kein Ablaufzeitpunkt."""
    fake.store[deploy_lock.DEPLOY_LOCK_KEY] = "x"
    assert deploy_lock.held_until() is None


# ---------------------------------------------------------------------------
# Redis nicht erreichbar
# ---------------------------------------------------------------------------


def test_redis_fehler_wird_gemeldet_nicht_verschluckt(kaputt: _KaputterRedis) -> None:
    """Alle Funktionen geben ``False``/``None`` zurueck statt zu werfen.

    Der Aufrufer entscheidet, was ein fehlender Redis bedeutet — fuer den
    Eingangstest ist es ein Abbruchgrund, fuer eine Statusabfrage nicht.
    """
    assert deploy_lock.acquire(ttl_s=100) is False
    assert deploy_lock.refresh(ttl_s=100) is False
    assert deploy_lock.release() is False
    assert deploy_lock.held_until() is None


def test_held_bricht_ab_wenn_die_sperre_nicht_gesetzt_werden_kann(
    kaputt: _KaputterRedis,
) -> None:
    """Der wichtigste Test dieser Datei.

    Ein Lauf ohne Sperre ist genau das Risiko, das dieses Modul
    ausschliessen soll. Er darf nicht stillschweigend stattfinden — sonst
    haette die Sperre den schlechtesten aller Zustaende: sie existiert, man
    verlaesst sich auf sie, und im entscheidenden Moment stand sie nicht.
    """
    with (
        pytest.raises(RuntimeError, match="Deploy-Sperre konnte nicht gesetzt"),
        deploy_lock.held(ttl_s=100),
    ):
        pytest.fail("Der Block darf nicht ausgefuehrt werden")


def test_held_ohne_pflicht_laeuft_trotzdem(kaputt: _KaputterRedis) -> None:
    """``pflicht=False`` ist der Weg fuer ``--no-deploy-lock``-artige Faelle."""
    gelaufen = False
    with deploy_lock.held(ttl_s=100, pflicht=False):
        gelaufen = True
    assert gelaufen


# ---------------------------------------------------------------------------
# held() als Kontextmanager
# ---------------------------------------------------------------------------


def test_held_gibt_am_ende_frei(fake: _FakeRedis) -> None:
    with deploy_lock.held(ttl_s=100):
        assert deploy_lock.DEPLOY_LOCK_KEY in fake.store
    assert deploy_lock.DEPLOY_LOCK_KEY not in fake.store


def test_held_gibt_auch_bei_ausnahme_frei(fake: _FakeRedis) -> None:
    with pytest.raises(ValueError, match="mitten im Lauf"), deploy_lock.held(ttl_s=100):
        raise ValueError("mitten im Lauf")
    assert deploy_lock.DEPLOY_LOCK_KEY not in fake.store


def test_held_gibt_bei_strg_c_frei(fake: _FakeRedis) -> None:
    """Strg-C loest ``KeyboardInterrupt`` aus — ``finally`` laeuft.

    Das ist der haeufigste Abbruch: ein Lauf ueber 104 Geraete dauert
    Stunden, und irgendwann bricht ihn jemand ab.
    """
    with pytest.raises(KeyboardInterrupt), deploy_lock.held(ttl_s=100):
        raise KeyboardInterrupt
    assert deploy_lock.DEPLOY_LOCK_KEY not in fake.store


def test_held_gibt_bei_sigterm_frei(fake: _FakeRedis) -> None:
    """SIGTERM wird von der CLI in ``SystemExit`` gewandelt — ``finally`` laeuft.

    Ohne die Wandlung (``pair_devices._sigterm_als_ausnahme``) beendet der
    Default-Handler den Prozess ohne Stack-Unwinding, die Sperre bliebe
    liegen und der Deploy waere bis zum Ablauf der TTL blockiert. Genau
    dieses Signal schickt ``docker compose up -d``.
    """
    with pytest.raises(SystemExit), deploy_lock.held(ttl_s=100):
        raise SystemExit(143)
    assert deploy_lock.DEPLOY_LOCK_KEY not in fake.store


def test_acquire_ueberschreibt_bestehende_sperre(fake: _FakeRedis) -> None:
    """Kein ``nx``: zwei Laeufe wollen dieselbe Sperre, nicht konkurrieren.

    Mit ``nx`` wuerde der zweite Lauf **ohne** Sperre weiterfahren — das
    Gegenteil des Gewuenschten. Ueberschneidungsfreiheit zweier Laeufe ist
    eine andere Zusicherung und nicht Aufgabe dieses Moduls.
    """
    deploy_lock.acquire(ttl_s=100)
    erste = fake.store[deploy_lock.DEPLOY_LOCK_KEY]
    assert deploy_lock.acquire(ttl_s=7200) is True
    assert fake.ttls[deploy_lock.DEPLOY_LOCK_KEY] == 7200
    # Der Wert ist der Setz-Zeitpunkt; er wurde neu geschrieben.
    assert isinstance(erste, str)


def test_margin_konstante(fake: Any) -> None:
    """15 min Reserve oberhalb des laengsten Warte-Fensters (Vorgabe 30.09.)."""
    assert deploy_lock.LOCK_TTL_MARGIN_S == 15 * 60
