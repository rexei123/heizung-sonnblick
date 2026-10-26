"""Jede Seite der Software hat einen Handbuch-Artikel, jeder Artikel ein Datum.

**Warum es diesen Test gibt.** Das Handbuch liegt als Markdown im Repo und
wandert durch denselben Pull Request wie die Aenderung, die es beschreibt
(Paket 1). Das ist die halbe Loesung — die andere Haelfte ist die Frage, die
niemand von sich aus stellt: *gibt es zu dieser neuen Seite ueberhaupt einen
Artikel?*

Eine Seitenleiste mit 16 Eintraegen und ein Ordner mit 23 Dateien lassen sich
nicht im Kopf gegeneinander halten. Dieser Test tut es bei jedem Lauf, und
zwar in **beide** Richtungen: eine Seite ohne Artikel faellt auf, und ein
Artikel, der auf eine Route zeigt, die es nicht mehr gibt, ebenfalls.

Der zweite Teil ist der unangenehmere. Ein Artikel, der eine verschwundene
Seite beschreibt, liest sich wie eine Anleitung und ist eine Falschaussage —
dieselbe Klasse wie der veraltete "wirkt nicht"-Vermerk aus CLAUDE.md
Paragraph 5.77: er sieht wie ein Befund aus, und genau deshalb prueft ihn
niemand nach.

**Warum der Test im Backend liegt und nicht im Frontend.** Er prueft zwei
Dateibaeume gegeneinander und braucht dafuer weder Node noch einen Browser.
Die Backend-Suite laeuft bei jedem PR (CLAUDE.md Paragraph 5.55, keine
paths-Filter an Pflicht-Checks) — damit greift er auch bei einem PR, der nur
das Frontend anfasst.

**Stand-Datum ist Pflicht.** Ein Artikel ohne Datum ist eine Behauptung ohne
Zeitpunkt. Dass eine Aussage *wann* gegolten hat, ist die Information, die
Paragraph 5.79 teuer bezahlt hat: ein abgeschlossenes Audit ohne Code-Stand
daneben wird spaeter als Garantie gelesen.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
ARTIKEL_ORDNER = REPO / "frontend" / "content" / "handbuch"
APP_SHELL = REPO / "frontend" / "src" / "components" / "patterns" / "app-shell.tsx"
ROUTEN_MODUL = REPO / "frontend" / "src" / "lib" / "handbuch" / "routen.ts"

# Die Zimmer-Detailseite steht nicht in der Seitenleiste (sie wird aus der
# Zimmerliste geoeffnet), braucht aber einen Artikel: dort sitzen
# Betriebszeit, Uebersteuerung und der Engine-Trace.
ZUSAETZLICHE_ROUTEN = {"/zimmer/[id]"}

# Marken fuer lebende Inhalte, die die Anzeige kennt
# (``components/patterns/handbuch-inhalt.tsx``).
BEKANNTE_MARKEN = {"werte", "karte"}


def _artikel() -> dict[str, dict[str, str]]:
    """Slug -> Kopfdaten. Bewusst ein eigener, winziger Parser.

    Der Frontend-Lader (``lib/handbuch/artikel.ts``) liest dieselben
    Kopfdaten, aber in TypeScript. Ihn hier aufzurufen hiesse, Node in die
    Backend-Suite zu holen; ihn zu spiegeln heisst, zwei Parser zu haben.
    Der zweite ist billiger — und weil dieser Test faellt, sobald die
    Kopfdaten nicht mehr lesbar sind, ist der Spiegel selbst bewacht.
    """
    ergebnis: dict[str, dict[str, str]] = {}
    for datei in sorted(ARTIKEL_ORDNER.glob("*.md")):
        roh = datei.read_text(encoding="utf-8")
        if not roh.startswith("---"):
            pytest.fail(f"{datei.name}: keine Kopfdaten (Block zwischen --- fehlt)")
        ende = roh.index("\n---", 3)
        kopf: dict[str, str] = {}
        for zeile in roh[3:ende].splitlines():
            if ":" not in zeile:
                continue
            schluessel, _, wert = zeile.partition(":")
            kopf[schluessel.strip()] = wert.strip()
        ergebnis[datei.stem] = kopf
    return ergebnis


def _seitenleisten_routen() -> set[str]:
    """Die ``href``-Werte aus ``NAV`` in der Seitenleiste.

    Gelesen wird der Quelltext, nicht ein Abbild davon: eine Liste, die
    jemand hier pflegen muesste, waere die zweite Wahrheit, gegen die der
    Test eigentlich schuetzt (Paragraph 5.53).
    """
    quelle = APP_SHELL.read_text(encoding="utf-8")
    beginn = quelle.index("const NAV: NavGroup[]")
    ende = quelle.index("\n];", beginn)
    routen = set(re.findall(r'href:\s*"([^"]+)"', quelle[beginn:ende]))
    assert routen, "keine href-Eintraege in NAV gefunden — Parser passt nicht mehr"
    return routen


def _route_zu_artikel() -> dict[str, str]:
    """Die Zuordnung aus ``lib/handbuch/routen.ts``."""
    quelle = ROUTEN_MODUL.read_text(encoding="utf-8")
    beginn = quelle.index("export const ROUTE_ZU_ARTIKEL")
    ende = quelle.index("\n};", beginn)
    paare = re.findall(r'"([^"]+)":\s*"([^"]+)"', quelle[beginn:ende])
    assert paare, "ROUTE_ZU_ARTIKEL leer oder Parser passt nicht mehr"
    return dict(paare)


def test_jede_seite_der_seitenleiste_hat_einen_artikel() -> None:
    zuordnung = _route_zu_artikel()
    fehlend = sorted(
        route
        for route in _seitenleisten_routen() | ZUSAETZLICHE_ROUTEN
        # Das Handbuch beschreibt sich nicht selbst.
        if route != "/handbuch" and route not in zuordnung
    )
    assert not fehlend, (
        "Seiten ohne Handbuch-Artikel: "
        + ", ".join(fehlend)
        + " — Artikel in frontend/content/handbuch anlegen und in "
        "lib/handbuch/routen.ts eintragen."
    )


def test_jeder_zugeordnete_artikel_existiert_und_nennt_seine_route() -> None:
    artikel = _artikel()
    probleme: list[str] = []
    for route, slug in _route_zu_artikel().items():
        kopf = artikel.get(slug)
        if kopf is None:
            probleme.append(f"{route}: Artikel '{slug}.md' fehlt")
            continue
        if kopf.get("route") != route:
            probleme.append(f"{route}: '{slug}.md' nennt route='{kopf.get('route')}'")
    assert not probleme, "; ".join(probleme)


def test_jede_route_in_den_kopfdaten_steht_in_der_zuordnung() -> None:
    """Die Gegenrichtung: ein Artikel zu einer Seite, die es nicht gibt."""
    zuordnung = _route_zu_artikel()
    probleme = [
        f"{slug}.md: route='{kopf['route']}' steht nicht in ROUTE_ZU_ARTIKEL"
        for slug, kopf in _artikel().items()
        if "route" in kopf and kopf["route"] not in zuordnung
    ]
    assert not probleme, "; ".join(probleme)


def test_jeder_artikel_hat_titel_kategorie_und_stand() -> None:
    probleme: list[str] = []
    for slug, kopf in _artikel().items():
        for feld in ("titel", "kategorie", "stand"):
            if not kopf.get(feld):
                probleme.append(f"{slug}.md: '{feld}' fehlt")
        stand = kopf.get("stand", "")
        if stand:
            try:
                dt.date.fromisoformat(stand)
            except ValueError:
                probleme.append(f"{slug}.md: stand='{stand}' ist kein Datum (JJJJ-MM-TT)")
    assert not probleme, "; ".join(probleme)


def test_rollen_angabe_ist_alle_oder_admin() -> None:
    """``rollen`` kennzeichnet, es sperrt nicht.

    Der Lader macht aus jedem unbekannten Wert stillschweigend ``alle``.
    Das ist die richtige Vorgabe — und genau deshalb faellt ein Tippfehler
    sonst nirgends auf: ein Artikel, der ``admni`` traegt, verliert seine
    Kennzeichnung ohne Fehlermeldung.
    """
    probleme = [
        f"{slug}.md: rollen='{kopf['rollen']}'"
        for slug, kopf in _artikel().items()
        if kopf.get("rollen", "alle") not in {"alle", "admin"}
    ]
    assert not probleme, "; ".join(probleme)


def test_verweise_zwischen_artikeln_zeigen_auf_vorhandene_artikel() -> None:
    """Ein toter Verweis im Handbuch ist eine 404-Seite mit Anlauf."""
    vorhanden = set(_artikel())
    probleme: list[str] = []
    for datei in sorted(ARTIKEL_ORDNER.glob("*.md")):
        text = datei.read_text(encoding="utf-8")
        for ziel in re.findall(r"\]\(/handbuch/([^)#]+)", text):
            if ziel not in vorhanden:
                probleme.append(f"{datei.name} -> /handbuch/{ziel}")
    assert not probleme, "Verweise auf fehlende Artikel: " + ", ".join(probleme)


def test_marken_fuer_lebende_inhalte_sind_bekannt() -> None:
    """Nur ``werte`` und ``karte`` haben Konsumenten, andere nicht.

    Die Anzeige rendert eine unbekannte Marke sichtbar in Rot statt sie zu
    verschlucken — das ist die richtige Entscheidung zur Laufzeit. Dieser
    Test ist die Stelle, an der es **vor** dem Deploy auffaellt.
    """
    probleme: list[str] = []
    for datei in sorted(ARTIKEL_ORDNER.glob("*.md")):
        text = datei.read_text(encoding="utf-8")
        for marke in re.findall(r"^\{\{([a-z-]+)\}\}$", text, re.MULTILINE):
            if marke not in BEKANNTE_MARKEN:
                probleme.append(f"{datei.name}: {marke}")
    assert not probleme, "unbekannte Marken: " + ", ".join(probleme)
