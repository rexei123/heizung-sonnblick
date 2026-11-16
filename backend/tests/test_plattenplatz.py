"""Die Platten-Warnung (14.11.2026).

Zwei Teile, und der erste ist der, an dem sich die Zahl entscheidet:

* **Die Rechenart.** ``df`` rechnet ohne die fuer root reservierten
  Bloecke und rundet auf. Wer ``belegt / gesamt`` nimmt, bekommt bei
  derselben Platte drei Prozentpunkte weniger — und eine Warnung bei
  „85 %" kommt dann erst, wenn ``df`` 88 % zeigt. Dann steht in der Mail
  eine andere Zahl als auf dem Server, und die erste Frage ist nicht
  „was raeumen wir auf", sondern „welche Zahl stimmt" (Paragraph 5.53).
* **Die Episode.** Eine Mail je Vorfall, eine Entwarnung danach, und der
  Zustand in ``business_audit``, damit er den Neustart ueberlebt.

Die gemessenen Zahlen unten sind vom Server, 14.11.2026:

    /dev/sda1  total=80307429376  used=48690868224  free=28293947392
    df sagt 64 %,  belegt/gesamt = 60,6 %,  belegt/(belegt+frei) = 63,2 %

Keine Uhr, keine echte Platte: ``beurteile`` bekommt die Zahlen von
aussen, und der Task-Teil setzt ``lies_plattenstand`` per ``monkeypatch``.
Ein Test gegen das echte Dateisystem waere einer, dessen Ergebnis vom
Rechner abhaengt, auf dem er laeuft.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from heizung.services import plattenplatz
from heizung.tasks import platten_tasks

# Die gemessenen Werte vom Server, 14.11.2026.
GEMESSEN_GESAMT = 80_307_429_376
GEMESSEN_BELEGT = 48_690_868_224
GEMESSEN_FREI = 28_293_947_392

GRENZE = 85


def _stand(*, belegt: int, frei: int, gesamt: int | None = None, grenze: int = GRENZE):
    return plattenplatz.beurteile(
        belegt_b=belegt,
        frei_b=frei,
        gesamt_b=gesamt if gesamt is not None else belegt + frei,
        grenze_prozent=grenze,
    )


# ---------------------------------------------------------------------------
# Die Rechenart — der Kern dieser Datei
# ---------------------------------------------------------------------------


def test_die_prozente_sind_die_von_df() -> None:
    """**Der gemessene Fall vom 14.11.2026.**

    ``df`` sagte 64 %. ``belegt / gesamt`` waere 60,6 % gewesen — mit
    dieser Rechnung haette eine 85-Prozent-Warnung erst bei einem
    ``df``-Stand von 88 % angeschlagen.
    """
    stand = _stand(belegt=GEMESSEN_BELEGT, frei=GEMESSEN_FREI, gesamt=GEMESSEN_GESAMT)

    assert stand.prozent == 64
    assert not stand.warnt


def test_belegt_durch_gesamt_waere_die_falsche_zahl() -> None:
    """Die Gegenprobe, und sie haelt den Unterschied als Zahl fest.

    Wird der Nenner auf ``gesamt_b`` umgestellt, kommt 61 heraus. Dieser
    Test ist die Stelle, an der das auffaellt — die Zahl allein sieht
    naemlich genauso plausibel aus.
    """
    falsch = round(GEMESSEN_BELEGT / GEMESSEN_GESAMT * 100)
    richtig = _stand(belegt=GEMESSEN_BELEGT, frei=GEMESSEN_FREI, gesamt=GEMESSEN_GESAMT).prozent

    assert falsch == 61
    assert richtig == 64
    assert richtig - falsch == 3, "drei Prozentpunkte Unterschied, und sie sind der Grund"


def test_aufgerundet_wie_df() -> None:
    """``df`` rundet auf: 63,2 % zeigt es als 64 an.

    Abrunden waere die naheliegende Wahl und laege eine Stufe unter dem,
    was auf dem Server steht.
    """
    # 63,2 % -> 64
    assert _stand(belegt=632, frei=368).prozent == 64
    # Genau 85,0 % bleibt 85 und warnt damit nicht.
    assert _stand(belegt=850, frei=150).prozent == 85


def test_die_grenze_ist_inklusiv() -> None:
    """„Ueber 85 %" meldet bei 85 noch nicht und bei 86 schon."""
    assert not _stand(belegt=850, frei=150).warnt
    assert _stand(belegt=851, frei=149).warnt


def test_die_grenze_kommt_von_aussen() -> None:
    """Mit einer anderen Einstellung verschiebt sich die Kante mit.

    Haengt die Zahl im Modul fest, verstellt die Einstellung nichts — und
    das faellt niemandem auf, weil beide Werte plausibel aussehen.
    """
    assert _stand(belegt=700, frei=300, grenze=65).warnt
    assert not _stand(belegt=700, frei=300, grenze=75).warnt


def test_ein_leeres_dateisystem_stuerzt_nicht_ab() -> None:
    """Null Bytes nutzbar: 0 %, keine Warnung, keine Division.

    Der Fall kann nur bei einem Messfehler entstehen — und eine Division
    waere dann ein Absturz im Dashboard-Endpunkt, also auf der Seite, die
    den Zustand zeigen soll.
    """
    stand = _stand(belegt=0, frei=0, gesamt=0)
    assert stand.prozent == 0
    assert not stand.warnt


def test_frei_gb_ist_fuer_menschen_gerundet() -> None:
    stand = _stand(belegt=GEMESSEN_BELEGT, frei=GEMESSEN_FREI, gesamt=GEMESSEN_GESAMT)
    assert stand.frei_gb == 28.3


def test_lies_plattenstand_misst_einen_echten_pfad(tmp_path: Any) -> None:
    """Der Lesepfad selbst, gegen ein Verzeichnis, das es gibt.

    Geprueft wird **nicht** die Belegung dieses Rechners — die haengt vom
    Rechner ab. Geprueft wird, dass die drei Zahlen plausibel
    zusammenpassen und dass die Grenze durchgereicht wird.
    """
    stand = plattenplatz.lies_plattenstand(grenze_prozent=GRENZE, pfad=str(tmp_path))

    assert stand.gesamt_b > 0
    assert 0 <= stand.prozent <= 100
    assert stand.warnt == (stand.prozent > GRENZE)


# ---------------------------------------------------------------------------
# Die Texte
# ---------------------------------------------------------------------------


def test_der_betreff_nennt_prozent_und_gigabyte() -> None:
    """Prozent allein sagt nicht, wie dringend es ist.

    85 % von 75 GB sind 11 GB frei, 85 % von 500 GB waeren 75 GB.
    """
    betreff = plattenplatz.betreff_alarm(_stand(belegt=90, frei=10, gesamt=100))
    assert "90 %" in betreff
    assert "GB frei" in betreff


def test_der_alarmtext_sagt_zuerst_die_folge() -> None:
    """Wer die Mail nachts liest, braucht die Folge, nicht die Diagnose."""
    text = plattenplatz.nachricht_alarm(
        _stand(belegt=90, frei=10, gesamt=100), grenze_prozent=GRENZE
    )
    kopf = text.split("\n", 1)[0]

    assert "90 %" in kopf
    assert "Postgres" in text, "die Folge muss benannt sein, nicht nur die Zahl"
    assert "10az" in text, "und der Handgriff muss auffindbar sein"


def test_der_alarmtext_nennt_das_automatische_aufraeumen() -> None:
    """Sonst raeumt jemand von Hand auf, was schon automatisch laeuft.

    Und die Mail sagt, was es bedeutet, wenn sie **trotz** des Aufraeumens
    kommt: dann sind es nicht die Images.
    """
    text = plattenplatz.nachricht_alarm(
        _stand(belegt=90, frei=10, gesamt=100), grenze_prozent=GRENZE
    )
    assert "nach jedem Deploy" in text
    assert "sind es nicht die Images" in text


# ---------------------------------------------------------------------------
# Die Episode — mit Datenbank
# ---------------------------------------------------------------------------

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
SKIP_REASON = "TEST_DATABASE_URL nicht gesetzt - DB-Tests brauchen Postgres"

db = pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)


@pytest_asyncio.fixture
async def maker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """Session-Fabrik plus ``_task_session``-Umleitung.

    Der Task oeffnet seine Session selbst (§5.14, eigene Engine je Lauf).
    Damit der Test dieselbe Datenbank sieht, wird ``_task_session``
    umgeleitet — und ``DATABASE_URL`` auf die Testdatenbank gepinnt
    (§5.48).
    """
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    from heizung.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine(TEST_DB_URL, poolclass=None)
    fabrik = async_sessionmaker(engine, expire_on_commit=False)

    import contextlib

    @contextlib.asynccontextmanager
    async def _session() -> AsyncIterator[Any]:
        async with fabrik() as session:
            yield session

    monkeypatch.setattr(platten_tasks, "_task_session", _session)
    yield fabrik
    await engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def kein_mailversand(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Faengt die Mails ab. Der Betreff landet in der Liste."""
    betreffe: list[str] = []

    def _send(*, recipient: str | None, subject: str, body: str) -> Any:  # noqa: ARG001
        betreffe.append(subject)

        class _R:
            sent = True
            reason = None
            kind = "platte"

        return _R()

    monkeypatch.setattr(platten_tasks.mailer, "send_mail", _send)

    async def _record(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(platten_tasks.mail_status, "record_attempt", _record)
    return betreffe


def _setze_stand(monkeypatch: pytest.MonkeyPatch, *, prozent: int) -> None:
    """Laesst ``lies_plattenstand`` einen gewuenschten Stand liefern."""

    def _lies(*, grenze_prozent: int, pfad: str = "/") -> plattenplatz.PlattenStand:  # noqa: ARG001
        return plattenplatz.beurteile(
            belegt_b=prozent,
            frei_b=100 - prozent,
            gesamt_b=100,
            grenze_prozent=grenze_prozent,
        )

    monkeypatch.setattr(platten_tasks.plattenplatz, "lies_plattenstand", _lies)


async def _aktionen(maker: Any) -> list[str]:
    async with maker() as session:
        zeilen = (
            await session.execute(
                text(
                    "SELECT action FROM business_audit WHERE target_type = 'server' ORDER BY ts, id"
                )
            )
        ).all()
    return [z[0] for z in zeilen]


async def _raeum_auf(maker: Any) -> None:
    async with maker() as session:
        await session.execute(text("DELETE FROM business_audit WHERE target_type = 'server'"))
        await session.commit()


@db
async def test_unter_der_grenze_passiert_nichts(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=64)
    try:
        ergebnis = await platten_tasks._run_plattenplatz()

        assert ergebnis["warnt"] is False
        assert ergebnis["aktion"] is None
        assert kein_mailversand == []
        assert await _aktionen(maker) == []
    finally:
        await _raeum_auf(maker)


@db
async def test_ueber_der_grenze_kommt_eine_mail_und_eine_zeile(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=90)
    try:
        ergebnis = await platten_tasks._run_plattenplatz()

        assert ergebnis["aktion"] == platten_tasks.AUDIT_PLATTE_VOLL
        assert ergebnis["gemailt"] == 1
        assert len(kein_mailversand) == 1
        assert "90 %" in kein_mailversand[0]
        assert await _aktionen(maker) == [platten_tasks.AUDIT_PLATTE_VOLL]
    finally:
        await _raeum_auf(maker)


@db
async def test_die_episode_meldet_einmal_und_bremst_dann(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Eine Mail je Vorfall.** Stuendlich pruefen heisst nicht stuendlich mailen.

    Ohne die Bremse kaemen 24 Mails am Tag fuer einen Zustand, der sich
    nicht aendert — und nach dem zweiten Tag liest sie niemand mehr
    (Paragraph 5.79).
    """
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=90)
    try:
        await platten_tasks._run_plattenplatz()
        zweit = await platten_tasks._run_plattenplatz()

        assert len(kein_mailversand) == 1, f"zweite Mail trotz Bremse: {kein_mailversand}"
        assert zweit["aktion"] is None
        assert await _aktionen(maker) == [platten_tasks.AUDIT_PLATTE_VOLL]
    finally:
        await _raeum_auf(maker)


@db
async def test_nach_dem_aufraeumen_kommt_die_entwarnung(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ein Alarm ohne Entwarnung laesst den Empfaenger im Ungewissen."""
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=90)
    try:
        await platten_tasks._run_plattenplatz()
        _setze_stand(monkeypatch, prozent=64)
        ergebnis = await platten_tasks._run_plattenplatz()

        assert ergebnis["aktion"] == platten_tasks.AUDIT_PLATTE_VOLL_ENDE
        assert len(kein_mailversand) == 2
        assert "wieder unter der Grenze" in kein_mailversand[1]
        assert await _aktionen(maker) == [
            platten_tasks.AUDIT_PLATTE_VOLL,
            platten_tasks.AUDIT_PLATTE_VOLL_ENDE,
        ]
    finally:
        await _raeum_auf(maker)


@db
async def test_ohne_vorherigen_alarm_keine_entwarnung(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eine Entwarnung ohne Alarm waere eine Mail ueber nichts."""
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=64)
    try:
        for _ in range(3):
            await platten_tasks._run_plattenplatz()

        assert kein_mailversand == []
        assert await _aktionen(maker) == []
    finally:
        await _raeum_auf(maker)


@db
async def test_nach_der_entwarnung_beginnt_die_naechste_episode_neu(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sonst waere der zweite Vorfall stumm.

    Die Bremse haengt an der juengsten Marke. Ist das eine Entwarnung,
    laeuft keine Episode — und der naechste Alarm muss sofort hinaus,
    nicht erst nach dem Wiederholungs-Abstand.
    """
    await _raeum_auf(maker)
    try:
        _setze_stand(monkeypatch, prozent=90)
        await platten_tasks._run_plattenplatz()
        _setze_stand(monkeypatch, prozent=64)
        await platten_tasks._run_plattenplatz()
        _setze_stand(monkeypatch, prozent=91)
        await platten_tasks._run_plattenplatz()

        assert len(kein_mailversand) == 3, kein_mailversand
        assert await _aktionen(maker) == [
            platten_tasks.AUDIT_PLATTE_VOLL,
            platten_tasks.AUDIT_PLATTE_VOLL_ENDE,
            platten_tasks.AUDIT_PLATTE_VOLL,
        ]
    finally:
        await _raeum_auf(maker)


@db
async def test_ohne_alarmadresse_entsteht_die_zeile_trotzdem(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Die Luecke, die Mutationsprobe M7 gefunden hat.**

    Der Audit-Eintrag **ist** der Zustand der Episode. Haengt er an der
    Mail-Adresse, beginnt die Episode bei jedem Lauf von vorn — und sobald
    jemand eine Adresse eintraegt, kommt eine Entwarnung fuer einen Alarm,
    den niemand erhalten hat. Oder, schlimmer, 24 Alarm-Mails am Tag.
    """
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=90)
    async with maker() as session:
        vorher = (
            await session.execute(text("SELECT alert_email FROM global_config WHERE id = 1"))
        ).scalar_one_or_none()
        await session.execute(text("UPDATE global_config SET alert_email = NULL WHERE id = 1"))
        await session.commit()
    try:
        ergebnis = await platten_tasks._run_plattenplatz()

        assert ergebnis["aktion"] == platten_tasks.AUDIT_PLATTE_VOLL
        assert ergebnis["gemailt"] == 0, "ohne Adresse geht keine Mail hinaus"
        assert kein_mailversand == []
        assert await _aktionen(maker) == [platten_tasks.AUDIT_PLATTE_VOLL], (
            "die Episode muss trotzdem begonnen haben"
        )

        # Und der zweite Lauf bremst — die Episode laeuft.
        await platten_tasks._run_plattenplatz()
        assert await _aktionen(maker) == [platten_tasks.AUDIT_PLATTE_VOLL]
    finally:
        async with maker() as session:
            await session.execute(
                text("UPDATE global_config SET alert_email = :a WHERE id = 1"),
                {"a": vorher},
            )
            await session.commit()
        await _raeum_auf(maker)


@db
async def test_die_zeile_haelt_die_zahlen_fest(
    maker: Any, kein_mailversand: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne Zahlen ist der Eintrag eine Behauptung (Paragraph 5.68).

    Wer in einem halben Jahr nachliest, muss sehen, **wie voll** sie war —
    sonst steht dort nur, dass gewarnt wurde.
    """
    await _raeum_auf(maker)
    _setze_stand(monkeypatch, prozent=90)
    try:
        await platten_tasks._run_plattenplatz()
        async with maker() as session:
            zeile = (
                await session.execute(
                    text(
                        "SELECT new_value FROM business_audit "
                        "WHERE target_type = 'server' ORDER BY ts DESC, id DESC LIMIT 1"
                    )
                )
            ).scalar_one()
        assert zeile["prozent"] == 90
        assert zeile["belegt_b"] == 90
        assert zeile["frei_b"] == 10
        assert zeile["gesamt_b"] == 100
    finally:
        await _raeum_auf(maker)
