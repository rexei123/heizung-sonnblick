"""Die drei Versions-Strings des Repos sagen dasselbe.

**Warum es diesen Test gibt.** Seit 15.10.2026 zeigt die Fussleiste der
Oberflaeche die Version (vorher stand dort ``v0.1.x · Test-Stage`` — eine
Zahl, die seit Sprint 9 nicht nachgezogen war, und ein Wort, das das
Personal als "nicht das echte System" gelesen hat).

Die Oberflaeche liest ihre Zahl aus ``frontend/package.json``
(``next.config.mjs`` setzt sie beim Build in ``NEXT_PUBLIC_APP_VERSION``).
Das Backend hat seine eigene in ``heizung.__version__`` — und die steht im
``/health``-Endpoint, also an der Stelle, an der ein Mensch unter Druck
nachsieht, welche Version laeuft.

**Zwei Zahlen, die dasselbe behaupten, laufen beim ersten Versionssprung
auseinander** (CLAUDE.md §5.53), und zwar stumm: niemand prueft eine
Fussleiste gegen einen Health-Endpoint. Dieser Test ist der Ersatz fuer
diese Pruefung. Er ist billiger als eine einzige Fehlsuche, bei der die
Oberflaeche eine andere Version nennt als der Server.

**Was er nicht tut:** er sagt nichts darueber, welcher Commit **deployed**
ist. Die Version ist eine Absicht im Repo, kein Server-Zustand (§5.68) —
was laeuft, beantwortet ``git rev-parse HEAD`` auf dem Server (RUNBOOK
§10aa Schritt 0).
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from heizung import __version__

REPO = pathlib.Path(__file__).resolve().parents[2]


def _package_json_version() -> str:
    datei = REPO / "frontend" / "package.json"
    return str(json.loads(datei.read_text(encoding="utf-8"))["version"])


def _pyproject_version() -> str:
    datei = REPO / "backend" / "pyproject.toml"
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        treffer = re.fullmatch(r'version\s*=\s*"([^"]+)"', zeile.strip())
        if treffer:
            return treffer.group(1)
    pytest.fail(f"keine version-Zeile in {datei}")


def test_frontend_und_backend_nennen_dieselbe_version() -> None:
    assert _package_json_version() == __version__, (
        "frontend/package.json und heizung.__version__ weichen ab — die "
        "Fussleiste wuerde eine andere Version zeigen als /health meldet"
    )


def test_pyproject_und_dunder_version_stimmen() -> None:
    assert _pyproject_version() == __version__


def test_version_ist_semver_ohne_praefix() -> None:
    # Der Tag heisst ``v0.3.0-heizperiode``, die Zahl hier nicht: das ``v``
    # setzt die Fussleiste selbst, der Suffix gehoert zum Tag.
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__
