"""Die Listen der Override-Quellen sagen dasselbe.

**Warum es diesen Test gibt.** ``OverrideSource`` hat sechs Werte, und sie
stehen an **fuenf** Stellen in zwei Sprachen:

| Stelle | Form | Wird geprueft von |
|---|---|---|
| ``models/enums.py`` | Enum | — (die Quelle) |
| ``override_service.py::_QUELLEN_RANG`` | ``dict`` | ``test_override_service.py`` |
| ``override_service.py::compute_expires_at`` | ``if``-Kette | hier |
| ``schemas/manual_override.py::FrontendOverrideSource`` | ``Literal`` | hier |
| ``types.ts::OverrideSource`` | TS-Union | hier |
| ``types.ts::FrontendOverrideSource`` | TS-Union | hier |
| ``manual-override-panel.tsx::FRONTEND_SOURCES`` | TS-Array | hier |

Der Rang-Tisch wird in ``test_override_service.py`` geprueft
(``test_quellen_rang_kennt_jede_override_quelle``) und nicht hier — er stand
schon im Hotfix, und sein Test gehoert neben die uebrigen Rang-Tests.

Am 20.10.2026 hat Fix A einen Wert (``frontend_24h``) eingefuehrt und zwei
dieser Listen nicht nachgezogen — den ``Literal`` im Create-Schema und den
Rang-Tisch. Die Folge war im Haus sichtbar: die **Vorauswahl** der Dauer
liess sich nicht abschicken. Gefunden hat es niemand, weil keine der Listen
gegen eine andere geprueft wurde.

**Was die Sprachen unterschiedlich gut koennen.** Die drei
``Record<OverrideSource, string>``-Maps im Frontend (``SOURCE_LABEL``,
``SOURCE_ICON``, ``OVERRIDE_SOURCE_LABEL``) sind von ``tsc`` erschoepfend
geprueft — ein fehlender Schluessel ist ein Typfehler, gemessen am
22.10.2026:

    src/lib/overrides-display.ts(19,14): error TS2741: Property
    'frontend_4h' is missing in type '{...}' but required in type
    'Record<OverrideSource, string>'.

Fuer sie braucht es hier **nichts**; ``npm run type-check`` ist der Spiegel
und ist Pflicht-Check. Aber dieser Schutz haengt daran, dass die **Union**
selbst stimmt: eine vollstaendige Map ueber eine veraltete Union ist
typsicher und trotzdem falsch (§5.63). Genau diese Naht prueft dieser Test.
Python kennt gar keine Erschoepfungspruefung — dort ist jede Liste von Hand
zu pflegen, und deshalb stehen die Backend-Pruefungen hier.

**Warum die Parser fehlschlagen, wenn sie nichts finden.** Ein Spiegel-Test,
der eine umbenannte Deklaration als leere Menge liest, ist gruen und
wertlos — dasselbe Fehlerbild wie §5.55. Jeder Helfer hier ruft deshalb
``pytest.fail``, wenn er seine Deklaration nicht findet.
"""

from __future__ import annotations

import pathlib
import re
import typing
from datetime import UTC, datetime, timedelta

import pytest

from heizung.models.enums import DeviceKind, OverrideSource
from heizung.schemas.manual_override import FrontendOverrideSource
from heizung.services import override_service

REPO = pathlib.Path(__file__).resolve().parents[2]
TYPES_TS = REPO / "frontend" / "src" / "lib" / "api" / "types.ts"
PANEL_TSX = REPO / "frontend" / "src" / "components" / "patterns" / "manual-override-panel.tsx"


def _ts_union(datei: pathlib.Path, name: str) -> set[str]:
    """String-Literale einer TypeScript-Union, ein- oder mehrzeilig."""
    quelle = datei.read_text(encoding="utf-8")
    treffer = re.search(
        rf"^export type {re.escape(name)}\s*=(.*?);", quelle, re.DOTALL | re.MULTILINE
    )
    if treffer is None:
        pytest.fail(f"Union {name} nicht in {datei.name} gefunden — umbenannt oder verschoben?")
    werte = set(re.findall(r'"([^"]+)"', treffer.group(1)))
    if not werte:
        pytest.fail(f"Union {name} in {datei.name} enthaelt keine String-Literale")
    return werte


def _ts_array(datei: pathlib.Path, name: str) -> list[str]:
    """String-Literale eines TypeScript-Array-Literals, in Reihenfolge."""
    quelle = datei.read_text(encoding="utf-8")
    treffer = re.search(
        rf"^const {re.escape(name)}\s*:[^=]+=\s*\[(.*?)\];", quelle, re.DOTALL | re.MULTILINE
    )
    if treffer is None:
        pytest.fail(f"Array {name} nicht in {datei.name} gefunden — umbenannt oder verschoben?")
    werte = re.findall(r'"([^"]+)"', treffer.group(1))
    if not werte:
        pytest.fail(f"Array {name} in {datei.name} ist leer")
    return werte


def frontend_waehlbare_dauern() -> list[str]:
    """Die Dauern, die die Rezeption im Dialog waehlen kann.

    Gelesen aus ``FRONTEND_SOURCES`` im Panel — **nicht** hier nochmals
    aufgezaehlt. Eine vierte Kopie derselben Liste waere genau die
    Drift-Quelle, die dieser Test verhindern soll.

    ``test_api_overrides.py`` legt fuer jeden dieser Werte einen Override
    ueber den echten Endpoint an. Das ist der Weg, der am 20.10. gefehlt
    hat: eine Liste zu spiegeln beweist noch nicht, dass der Weg traegt.
    """
    return _ts_array(PANEL_TSX, "FRONTEND_SOURCES")


# ---------------------------------------------------------------------------
# Naht 1: Frontend-Union gegen den Python-Enum
# ---------------------------------------------------------------------------


def test_frontend_union_spiegelt_den_enum() -> None:
    """``types.ts`` kennt genau die Werte, die der Enum hat.

    Fehlt hier einer, ist die Folge **nicht** ein Typfehler, sondern ein
    leeres Feld in der Oberflaeche: ``SOURCE_LABEL[source]`` liefert
    ``undefined``, und Badge wie Historie zeigen nichts. Genau das ist mit
    ``device_manual`` in Sprint 20f passiert (§5.63).
    """
    ts = _ts_union(TYPES_TS, "OverrideSource")
    py = {q.value for q in OverrideSource}

    assert ts == py, (
        f"nur im Enum: {sorted(py - ts)} | nur in types.ts: {sorted(ts - py)} — "
        "ein Wert ohne Union-Eintrag erscheint in der Oberflaeche als leeres Feld"
    )


# ---------------------------------------------------------------------------
# Naht 2: waehlbare Dauern gegen das Create-Schema
# ---------------------------------------------------------------------------


def _pydantic_literal_werte() -> set[str]:
    return set(typing.get_args(FrontendOverrideSource))


def test_create_schema_akzeptiert_jede_waehlbare_dauer() -> None:
    """**Die Naht, an der Fix A gerissen ist.**

    Das Panel schickt, was in ``FRONTEND_SOURCES`` steht. Das Schema nimmt,
    was im ``Literal`` steht. Steht ein Wert nur links, weist Pydantic die
    Anfrage mit 422 ab — bevor irgendein Service sie sieht, und mit einer
    Fehlermeldung, die die erlaubten Werte aufzaehlt und damit wie ein
    Bedienfehler aussieht.
    """
    waehlbar = set(frontend_waehlbare_dauern())
    erlaubt = _pydantic_literal_werte()

    assert waehlbar <= erlaubt, (
        f"waehlbar, aber im Create-Schema nicht erlaubt: {sorted(waehlbar - erlaubt)} — "
        "die Rezeption bekaeme darauf 422"
    )


def test_create_schema_nennt_nur_echte_enum_werte() -> None:
    """Umgekehrte Richtung: kein Tippfehler im ``Literal``.

    Das Schema ist ein ``Literal`` aus Strings, der Enum eine eigene Klasse —
    niemand prueft sie gegeneinander. Ein Buchstabendreher waere ein Wert,
    den die API annimmt und ``OverrideSource(...)`` in ``overrides.py``
    danach mit ``ValueError`` verwirft.
    """
    erlaubt = _pydantic_literal_werte()
    py = {q.value for q in OverrideSource}

    assert erlaubt <= py, f"im Literal, aber kein Enum-Wert: {sorted(erlaubt - py)}"


#: Quellen, die die Union fuehrt, ohne im Dauer-Array des Panels zu stehen —
#: mit dem Grund, warum sie dort nicht hingehoeren.
#:
#: ``frontend_bereich`` (Sprint 24d) ist **keine Dauer-Auswahl**: in einem
#: Allgemeinbereich waehlt die Rezeption Minuten, und die Quelle folgt aus
#: dem Raumtyp. Sie steht deshalb im Code des Formulars und nicht in
#: ``FRONTEND_SOURCES``.
#:
#: Die Liste ist eine **Ausnahmeliste und kein Schlupfloch**: wer hier einen
#: Wert eintraegt, nimmt ihn aus der Pruefung unten heraus, und das soll
#: wehtun. Jeder Eintrag braucht den Satz, warum die Rezeption ihn nicht
#: auswaehlt.
NICHT_IN_DER_DAUER_AUSWAHL = {"frontend_bereich"}


def test_waehlbare_dauern_sind_frontend_quellen() -> None:
    """Das Array im Panel passt zu seiner eigenen Union.

    Ein Array ist in TypeScript **nicht** erschoepfend geprueft — anders als
    die ``Record``-Maps. Waechst ``FrontendOverrideSource`` um einen Wert,
    sagt ``tsc`` nichts, und die neue Dauer fehlt still im Dialog.
    """
    waehlbar = set(frontend_waehlbare_dauern())
    union = _ts_union(TYPES_TS, "FrontendOverrideSource")
    erwartet = union - NICHT_IN_DER_DAUER_AUSWAHL

    assert waehlbar == erwartet, (
        f"nur in der Union: {sorted(erwartet - waehlbar)} | "
        f"nur im Array: {sorted(waehlbar - erwartet)}"
    )


def test_jede_ausnahme_steht_in_der_union() -> None:
    """Die Ausnahmeliste altert nicht unbemerkt.

    Verschwindet ``frontend_bereich`` eines Tages aus der Union, bleibt
    hier ein Eintrag stehen, der eine Pruefung lockert, die er nicht mehr
    lockern muss — ein Vermerk, der einmal richtig war und dann nicht mehr
    (§5.77).
    """
    union = _ts_union(TYPES_TS, "FrontendOverrideSource")
    assert union >= NICHT_IN_DER_DAUER_AUSWAHL, (
        f"Ausnahme ohne Union-Wert: {sorted(NICHT_IN_DER_DAUER_AUSWAHL - union)}"
    )


# ---------------------------------------------------------------------------
# Naht 3: compute_expires_at
# ---------------------------------------------------------------------------


def test_compute_expires_at_kennt_jede_quelle() -> None:
    """Jede Quelle bekommt eine Frist, keine faellt in den ``else``-Zweig.

    Hier ist der Fehlerfall **laut** — der ``else``-Zweig wirft
    ``ValueError``, und das wird in ``overrides.py`` zu einem 422 mit
    Begruendung. Das ist richtig so und trotzdem zu pruefen: ein neuer Wert
    soll die Entscheidung „welche Frist?" erzwingen, und zwar hier und nicht
    im Betrieb.

    ``frontend_checkout`` braucht ``next_checkout_at`` — ohne den ist
    ``ValueError`` das **gewollte** Verhalten (AE-58, das OCCUPIED-Gate
    garantiert den Wert). Deshalb wird er mitgegeben.

    ``frontend_bereich`` braucht aus demselben Grund ``dauer_minuten``
    (Sprint 24d): dort steckt die Frist in der Anfrage und nicht im Namen
    der Quelle. Beide Pflicht-Angaben werden hier mitgegeben, damit der
    Test die Frage „hat jede Quelle eine Frist?" beantwortet und nicht die
    Frage „sind die Pflicht-Angaben gesetzt?" — die steht eigens unten.
    """
    now = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    checkout = now + timedelta(days=1)

    for quelle in OverrideSource:
        frist = override_service.compute_expires_at(
            quelle, now, next_checkout_at=checkout, dauer_minuten=120
        )
        assert frist > now, f"{quelle.value}: Frist liegt nicht in der Zukunft ({quelle}: {frist})"


def test_dauer_gilt_nur_fuer_die_bereichs_quelle() -> None:
    """``dauer_minuten`` darf keine andere Quelle verbiegen.

    Der Test oben gibt die Dauer **allen** Quellen mit, damit er nur die
    Frist prueft. Genau das koennte eine Aenderung verdecken, die
    ``dauer_minuten`` versehentlich auf jede Quelle anwendet — dann waere
    die 24-Stunden-Wahl der Rezeption ploetzlich zwei Stunden lang.
    """
    now = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    mit = override_service.compute_expires_at(OverrideSource.FRONTEND_24H, now, dauer_minuten=120)
    ohne = override_service.compute_expires_at(OverrideSource.FRONTEND_24H, now)
    assert mit == ohne == now + timedelta(hours=24)


# ---------------------------------------------------------------------------
# Naht 4: DeviceKind (Sprint 24b)
# ---------------------------------------------------------------------------


def test_device_kind_union_spiegelt_den_enum() -> None:
    """``types.ts::DeviceKind`` kennt genau die Werte des Enums.

    **Der Anlass ist ein Beinahe-Treffer.** ``relay`` kam mit Sprint 24
    in den Python-Enum und fehlte in der TS-Union. Aufgefallen ist es
    erst in Sprint 24b, als die Relais-Karte gegen ``"relay"`` verglich
    und ``tsc`` „types have no overlap" meldete — also durch einen
    Zufall, nicht durch eine Pruefung. Haette niemand verglichen, waere
    die Luecke geblieben, und ein Relais haette auf der Geraeteseite die
    Vicki-Kacheln gezeigt, die bei ihm alle leer sind.

    Dasselbe Muster wie bei ``OverrideSource`` oben, und derselbe Grund:
    die ``Record``-Maps sind typsicher, aber nur gegen **die Union**.
    Eine veraltete Union ist in sich geschlossen und trotzdem falsch
    (§5.63).
    """
    ts = _ts_union(TYPES_TS, "DeviceKind")
    py = {a.value for a in DeviceKind}

    assert ts == py, f"nur im Enum: {sorted(py - ts)} | nur in types.ts: {sorted(ts - py)}"
