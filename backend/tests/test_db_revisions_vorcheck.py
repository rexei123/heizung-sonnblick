"""H-6 Nachtrag — ein Rueckfall ueber eine Migration hinweg darf starten.

**Der Befund (Hotelier, 09.10.2026).** AE-77 §8 erlaubte Rueckfaelle „ueber
additive Migrationen", weil eine neue leere Spalte den alten Code nicht
stoert. Das stimmt fuer das Schema — und half nichts: Alembic scheitert an
seiner eigenen Buchfuehrung, bevor eine Zeile Schema geprueft wird.

Gemessen mit dem alembic-Baum von ``85125ae`` gegen eine Datenbank auf
``0028``:

    ERROR [alembic.util.messaging] Can't locate revision identified by
    '0028_global_config_pin_seen'
    FAILED: Can't locate revision identified by '0028_global_config_pin_seen'

Der Entrypoint versucht es fuenfmal und beendet sich mit ``exit 1``. Weil
api, celery_worker und celery_beat dasselbe Image mit demselben Entrypoint
fahren und ``restart: always`` gilt, waere das Ergebnis ein
Neustart-Karussell **ohne API und ohne Engine** — im Moment eines
Rueckfalls, also unter Druck. Ohne Vorcheck machte damit **jede**
Migration einen Rueckfall unmoeglich.

Gepinnt ist hier beides:

* **Der Fall wird erkannt** — eine Revision in der DB, die dieses Image
  nicht kennt, fuehrt zu ``UEBERSPRINGEN``.
* **Der Vorcheck wird nie selbst zur Abbruchursache.** Jeder unklare Fall
  ist ``AUSFUEHREN``, und ``main`` faengt auch, was ``pruefen`` nicht faengt.
  Ein Vorcheck, der statt 10 einen Fehler-Code liefert, bringt das
  Karussell zurueck — und zwar still.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from heizung.scripts import db_revision_check as vorcheck

DATABASE_URL = os.environ.get("DATABASE_URL")


# ---------------------------------------------------------------------------
# 1. Die Entscheidung
# ---------------------------------------------------------------------------


def test_db_neuer_als_image_wird_uebersprungen() -> None:
    """Der Fall nach einem Rueckfall: DB kennt 0028, Image nur bis 0027."""
    ergebnis = vorcheck.entscheiden(
        in_db={"0028_global_config_pin_seen"},
        bekannt={"0026_override_device_manual", "0027_device_mounted_conf"},
    )
    assert ergebnis == vorcheck.UEBERSPRINGEN


def test_bekannte_revision_laeuft_normal_durch() -> None:
    """Der Normalfall, bei jedem Deploy: Upgrade wird ausgefuehrt.

    Wichtiger als er aussieht — ein Vorcheck, der zu oft ueberspringt,
    liesse Migrationen liegen, und das faellt erst beim naechsten Feature
    auf, das die Spalte braucht.
    """
    assert (
        vorcheck.entscheiden(
            in_db={"0027_device_mounted_conf"},
            bekannt={"0027_device_mounted_conf", "0028_global_config_pin_seen"},
        )
        == vorcheck.AUSFUEHREN
    )


def test_vorwaerts_deploy_laeuft_normal_durch() -> None:
    """DB hinten, Image vorn: genau das, wofuer das Upgrade da ist."""
    assert (
        vorcheck.entscheiden(
            in_db={"0026_override_device_manual"},
            bekannt={"0026_override_device_manual", "0027_device_mounted_conf"},
        )
        == vorcheck.AUSFUEHREN
    )


@pytest.mark.parametrize(
    ("in_db", "bekannt"),
    [
        (None, {"0027_device_mounted_conf"}),  # DB nicht erreichbar
        ({"0027_device_mounted_conf"}, None),  # alembic.ini nicht lesbar
        (None, None),
        (set(), {"0027_device_mounted_conf"}),  # Tabelle da, aber leer
    ],
)
def test_jeder_unklare_fall_fuehrt_zum_upgrade(
    in_db: set[str] | None, bekannt: set[str] | None
) -> None:
    """Der Vorcheck ist eine Zugabe und darf nichts zusaetzlich kippen.

    Ist die DB nicht erreichbar, verhaelt sich der Entrypoint wie vorher:
    fuenf Versuche, dann sichtbarer Absturz. Das ist ein bekanntes
    Fehlerbild mit einer bekannten Diagnose — ein neues waere schlechter.
    """
    assert vorcheck.entscheiden(in_db, bekannt) == vorcheck.AUSFUEHREN


def test_eine_unbekannte_unter_bekannten_genuegt() -> None:
    """Mehrere Koepfe: eine unbekannte Revision reicht fuer den Abbruch.

    ``alembic_version`` kann mehrere Zeilen haben. Eine davon unbekannt
    heisst, dass ``upgrade head`` an ihr scheitert — der Rest hilft nicht.
    """
    assert (
        vorcheck.entscheiden(
            in_db={"0027_device_mounted_conf", "0099_aus_der_zukunft"},
            bekannt={"0027_device_mounted_conf"},
        )
        == vorcheck.UEBERSPRINGEN
    )


# ---------------------------------------------------------------------------
# 2. Das Fangnetz
# ---------------------------------------------------------------------------


def test_main_faengt_auch_was_pruefen_nicht_faengt(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` gibt AUSFUEHREN zurueck, statt eine Ausnahme nach oben zu lassen.

    Der konkrete Anlass ist ``UnicodeEncodeError``: laeuft der Container
    ohne UTF-8-Locale, wuerde ein ``print`` mit ``§`` werfen — und der
    Entrypoint liest alles ausser 10 als "ausfuehren". Der Vorcheck waere
    damit still wirkungslos. Die Ausgaben sind deshalb ASCII (§5.3); dies
    ist die Ebene darunter.
    """

    def _kracht() -> int:
        raise UnicodeEncodeError("ascii", "§", 0, 1, "kein Platz fuer Paragraphen")

    monkeypatch.setattr(vorcheck, "pruefen", _kracht)

    assert vorcheck.main() == vorcheck.AUSFUEHREN


def test_ausgaben_sind_ascii() -> None:
    """Keine Nicht-ASCII-Zeichen in den ausgegebenen Zeichenketten.

    Geprueft an der Quelle und nicht am Lauf, weil der Fehler nur in einer
    Umgebung auftritt, die CI nicht hat (POSIX-Locale ohne UTF-8). §5.3
    ist dieselbe Familie: eine Datei, die lokal richtig aussieht und
    woanders bricht.
    """
    quelle = Path(vorcheck.__file__).read_text(encoding="utf-8")
    verdaechtig = [
        zeile
        for zeile in quelle.splitlines()
        if "print(" in zeile and any(ord(z) > 127 for z in zeile)
    ]
    assert verdaechtig == []


# ---------------------------------------------------------------------------
# 3. Gegen die echte Datenbank
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL nicht gesetzt")
def test_gegen_echte_db_ist_der_stand_bekannt() -> None:
    """Der eigene Stand muss ``AUSFUEHREN`` ergeben — sonst ist der Vorcheck falsch.

    Dieser Test liest nur und schreibt nichts: ein Test, der
    ``alembic_version`` in der gemeinsamen Test-Datenbank verbiegt und beim
    Abbruch nicht zurueckstellt, legt jede folgende Testdatei lahm. Der
    gefaehrliche Fall ist darum oben rein geprueft.

    Er belegt die drei Teile, die der reine Test nicht sieht: dass
    ``alembic.ini`` gefunden wird, dass die Revisionen daraus lesbar sind
    und dass die DB-Abfrage laeuft.
    """
    assert vorcheck.pruefen() == vorcheck.AUSFUEHREN
