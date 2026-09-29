"""CLI-Schalter von ``pair_devices`` — reine Argument-Pruefung, ohne Datenbank.

Bewusst ein eigenes Modul neben ``test_pair_devices_cli.py``: dort haengen
alle Tests an einer modulweiten Fixture, die Migrationen fahrt und ein
Admin-Konto anlegt. Reine Parser-Tests brauchen das nicht — und sie sollen
auch dann laufen, wenn lokal kein Postgres steht (B-18-5). Genau dieser
Unterschied hat in Sprint 19 Arbeit gekostet: ein Test, der nur in CI laeuft,
meldet seinen Befund eine Viertelstunde spaeter.

**Warum die Importe in den Testfunktionen stehen:** ``pair_devices`` setzt
beim Import ``os.environ.setdefault("DATABASE_URL", ...)`` auf einen
Entwicklungs-Wert (pair_devices.py, Kopf des Moduls). Das ist fuer den
Hotelier-Aufruf gedacht, hat aber eine Nebenwirkung auf die Testumgebung:
danach glaubt ``conftest._ensure_test_admin``, es sei eine Datenbank
konfiguriert, und versucht zu migrieren. Mit Importen **innerhalb** der Tests
bleibt ``os.environ`` bis zum Fixture-Setup unberuehrt, und dieses Modul
laeuft allein aufgerufen auch ohne Postgres:

    pytest tests/test_pair_devices_flags.py

Im vollen Lauf greift der Trick nicht, weil ein anderes Modul
``pair_devices`` schon beim Sammeln importiert. Dort liefert CI die
Datenbank.

Gegenstand ist die Reihenfolge ``parse -> Widerspruch abweisen -> Handler``
in ``main_async``. Der Abbruch muss fallen, **bevor** ein Downlink rausgeht.
"""

from __future__ import annotations

import asyncio

import pytest

_WIDERSPRUCH = ["inbound-test", "--all-pool", "--no-valve-check", "--require-motor"]


def test_no_valve_check_and_require_motor_abort_at_start() -> None:
    """Widersprechende Schalter brechen beim Start ab, Exit 2.

    ``--no-valve-check`` schaltet das Ventilkriterium ab, ``--require-motor``
    verlangt es. Zusammen gibt es keine Lesart, die der Aufrufer gemeint
    haben kann.

    Geprueft wird ``main_async`` und nicht nur der Parser, weil die
    Reihenfolge der eigentliche Gegenstand ist: der Abbruch faellt vor dem
    Handler und damit vor dem ersten Downlink. Ein Lauf ueber 104 Geraete
    dauert ueber eine Stunde und kostet Batterie; ein Widerspruch, der erst
    am Ergebnis auffaellt, ist teuer.
    """
    from heizung.scripts.pair_devices import main_async

    with pytest.raises(SystemExit) as exc:
        asyncio.run(main_async(_WIDERSPRUCH))
    # argparse-Konvention: 2 fuer einen Aufruf-Fehler. 1 ist der Exit-Code
    # fuer einen *Befund* (FAIL/TIMEOUT) und darf hier nicht kommen — sonst
    # liest ein Skript den Widerspruch als Geraete-Problem.
    assert exc.value.code == 2


def test_contradicting_flags_message_names_both(capsys: pytest.CaptureFixture[str]) -> None:
    """Die Meldung nennt beide Schalter und was zu tun ist."""
    from heizung.scripts.pair_devices import main_async

    with pytest.raises(SystemExit):
        asyncio.run(main_async(_WIDERSPRUCH))
    fehler = capsys.readouterr().err
    assert "Flags widersprechen sich" in fehler
    assert "--no-valve-check" in fehler
    assert "--require-motor" in fehler
    assert "Genau einen von beiden" in fehler


def test_each_flag_alone_is_accepted() -> None:
    """Der Widerspruch ist die Kombination, nicht der einzelne Schalter.

    Gegenprobe zum Abbruch oben: beide Schalter muessen einzeln durchgehen,
    sonst haette die Pruefung einen funktionierenden Aufruf mitgenommen.
    """
    from heizung.scripts.pair_devices import _build_parser, _reject_contradicting_flags

    parser = _build_parser()
    for flag in ("--no-valve-check", "--require-motor"):
        args = parser.parse_args(["inbound-test", "--all-pool", flag])
        _reject_contradicting_flags(parser, args)

    _reject_contradicting_flags(parser, parser.parse_args(["inbound-test", "--all-pool"]))


def test_other_subcommands_are_not_affected() -> None:
    """Die Pruefung greift nur, wo es die Schalter gibt.

    ``getattr(..., False)`` statt ``args.no_valve_check``: andere
    Unterbefehle tragen die Attribute nicht, und ein ``AttributeError`` im
    Start-Pfad waere ein Absturz statt einer Meldung.
    """
    from heizung.scripts.pair_devices import _build_parser, _reject_contradicting_flags

    parser = _build_parser()
    _reject_contradicting_flags(parser, parser.parse_args(["list-pool"]))
    _reject_contradicting_flags(parser, parser.parse_args(["validate", "/tmp/x.csv"]))


def test_require_motor_defaults_to_off() -> None:
    """Ohne Angabe bleibt der Motortest optional.

    Der Montage-Lauf setzt das Flag bewusst (RUNBOOK 10h.4). Der Tischlauf
    darf es nicht erben, sonst faellt dort jedes Geraet durch — ohne
    Backplate ist ``motorRange 0`` der erwartete Zustand.
    """
    from heizung.scripts.pair_devices import _build_parser

    args = _build_parser().parse_args(["inbound-test", "--all-pool"])
    assert args.require_motor is False
    assert args.no_valve_check is False
