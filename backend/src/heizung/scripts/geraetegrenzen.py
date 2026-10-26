r"""Die Temperaturgrenzen am Geraet setzen, abfragen, vergleichen (Sprint 23 T1).

Drei Unterbefehle:

    setzen     ``0x08`` mit den Soll-Grenzen der Zone, danach ``0x15``
    abfragen   nur ``0x15``
    vergleich  liest die Datenbank: Soll gegen zuletzt Gemeldetes

**Ein Probelauf ist der Standard.** Ohne ``--ausfuehren`` wird nichts
gesendet, sondern aufgezaehlt, was gesendet wuerde — mit den Bytes, der
Firmware und den **Ausnahmen samt Grund**. Jeder dieser Befehle greift
produktive Hardware an (S4), und ein Werkzeug, das beim ersten Tippfehler
funkt, ist das falsche Werkzeug. Dieselbe Form wie
``scripts/fenstererkennung``; die Zielauswahl kommt aus demselben Modul
(``services/geraete_ziele``), damit es nicht zwei Listen darueber gibt,
welche Geraete Befehle bekommen.

**Die Werte kommen aus dem Raumtyp, nicht von der Kommandozeile.** Ein
``--min``/``--max`` von Hand waere eine zweite Wahrheit neben Layer 5 —
und beim naechsten Grenzen-Wechsel in der Oberflaeche liefe sie
auseinander. Im Haus ergibt das: Zimmer **15/25** (``0x08 0F 19``), Bad
**18/25** (``0x08 12 19``), weil Bad-Zonen der Vorlage folgen.

Aufruf (Prod-Container heisst ``deploy-api-1``):

    docker exec <api> python -m heizung.scripts.geraetegrenzen vergleich

    docker exec <api> python -m heizung.scripts.geraetegrenzen setzen \
        --nur "107 Schlafzimmer"
    docker exec <api> python -m heizung.scripts.geraetegrenzen setzen \
        --nur "107 Schlafzimmer" --ausfuehren

**Der Rollout geht gestaffelt**, nicht in einem Zug: ``--pause`` (Vorgabe
2 s) zwischen den Geraeten. Bei hundert Geraeten sind das rund drei
Minuten; die ChirpStack-Warteschlange nimmt mehr an, die Geraete nicht
(Duty-Cycle, S4).

**Was dieses Werkzeug nicht tut: automatisch senden.** Eine Aenderung der
Grenzen in der Oberflaeche loest heute **keinen** Downlink aus; sie wirkt
am Geraet erst, wenn jemand ``setzen`` laufen laesst. Das ist Absicht und
der offene Rest von T1: ein ``PATCH`` auf einen Raumtyp betrifft alle
Zonen dieses Typs — bei „Bad" sind das alle Baeder im Haus, also bis zu
~45 Downlinks aus einem Klick. Dieser Pfad gehoert hinter den
Pflicht-Stop und nicht davor.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from zoneinfo import ZoneInfo

# Siehe ``activate_open_window_detection``: der Guard trennt den
# CLI-Aufruf vom Import durch die Tests.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

from heizung.db import SessionLocal  # noqa: E402
from heizung.services import downlink_adapter  # noqa: E402
from heizung.services.geraete_ziele import (  # noqa: E402
    Ausnahme,
    Zielgeraet,
    lade_ziele,
    nicht_gefunden,
)
from heizung.services.geraetegrenzen import (  # noqa: E402
    Grenzbefund,
    Grenzen,
    ist_grenzen_je_geraet,
    muss_gesendet_werden,
    soll_grenzen_je_zone,
)

logger = logging.getLogger("geraetegrenzen")

ZONE = "Europe/Vienna"


def _tabelle(kopf: list[str], zeilen: list[list[str]]) -> None:
    if not zeilen:
        print("  (keine)")
        return
    breiten = [max(len(kopf[i]), max(len(z[i]) for z in zeilen)) for i in range(len(kopf))]
    print("  " + " | ".join(kopf[i].ljust(breiten[i]) for i in range(len(kopf))))
    print("  " + "-+-".join("-" * b for b in breiten))
    for z in zeilen:
        print("  " + " | ".join(z[i].ljust(breiten[i]) for i in range(len(kopf))))


def _zeige_ausnahmen(ausnahmen: list[Ausnahme]) -> None:
    print("\n--- Ausgenommen ---")
    _tabelle(
        ["dev_eui", "label", "Grund"],
        [[a.dev_eui, a.label or "", a.grund] for a in ausnahmen],
    )


def _ist_text(befund: Grenzbefund | None) -> str:
    """Was am Geraet steht, mit Zeitpunkt in Ortszeit.

    „nicht bestaetigt" heisst **nicht** „falsch": es heisst, dass noch
    keine Antwort kam. Bei einem Class-A-Geraet ist das normal, solange es
    nicht gesendet hat.
    """
    if befund is None:
        return "nicht bestaetigt"
    wann = befund.gemeldet_um.astimezone(ZoneInfo(ZONE)).strftime("%d.%m. %H:%M")
    return f"{befund.grenzen} (bestaetigt {wann})"


async def _lage(
    nur: list[str],
) -> tuple[list[Zielgeraet], list[Ausnahme], dict[int, Grenzen], dict[int, Grenzbefund | None]]:
    """Ziele, Ausnahmen, Soll je Geraet und zuletzt Gemeldetes."""
    async with SessionLocal() as session:
        ziele, ausnahmen = await lade_ziele(session, nur=nur or None)
        zone_ids = [z.heating_zone_id for z in ziele if z.heating_zone_id is not None]
        soll_je_zone = await soll_grenzen_je_zone(session, zone_ids)
        befunde = await ist_grenzen_je_geraet(session, [z.device_id for z in ziele])

    soll_je_geraet = {
        z.device_id: soll_je_zone[z.heating_zone_id]
        for z in ziele
        if z.heating_zone_id is not None and z.heating_zone_id in soll_je_zone
    }
    return ziele, ausnahmen, soll_je_geraet, befunde


def _zeige_lage(
    ziele: list[Zielgeraet],
    soll: dict[int, Grenzen],
    befunde: dict[int, Grenzbefund | None],
) -> list[Zielgeraet]:
    """Tabelle Soll/Ist je Geraet. Gibt die zurueck, die abweichen."""
    zeilen: list[list[str]] = []
    offen: list[Zielgeraet] = []
    for z in ziele:
        s = soll.get(z.device_id)
        if s is None:
            # Ein Ziel ohne Soll-Grenzen kann es nach ``lade_ziele`` nicht
            # geben (ohne Zone waere es eine Ausnahme). Falls doch, wird
            # es **gezeigt** und nicht uebergangen.
            zeilen.append(
                [z.bezeichnung, z.dev_eui, z.firmware_version or "(NULL)", "?", "?", "ohne Zone?"]
            )
            continue
        b = befunde.get(z.device_id)
        senden = muss_gesendet_werden(s, b)
        if senden:
            offen.append(z)
        zeilen.append(
            [
                z.bezeichnung,
                z.dev_eui,
                z.firmware_version or "(NULL)",
                str(s),
                _ist_text(b),
                "senden" if senden else "stimmt",
            ]
        )
    _tabelle(["Bezeichnung", "dev_eui", "Firmware", "Soll", "Am Geraet", "Urteil"], zeilen)
    return offen


async def _befehl_vergleich(args: argparse.Namespace) -> int:
    ziele, ausnahmen, soll, befunde = await _lage(args.nur)
    print("\n=== Grenzen am Geraet: Soll gegen Gemeldetes ===")
    offen = _zeige_lage(ziele, soll, befunde)
    if ausnahmen:
        _zeige_ausnahmen(ausnahmen)

    ohne_antwort = sum(1 for z in ziele if befunde.get(z.device_id) is None)
    print(
        f"\n{len(ziele)} Geraet(e): {len(ziele) - len(offen)} stimmen, "
        f"{len(offen)} weichen ab oder sind unbestaetigt "
        f"(davon {ohne_antwort} ohne jede Antwort)."
    )
    if ohne_antwort == len(ziele) and ziele:
        print(
            "\nKeines hat geantwortet. Das ist **kein** Befund „alle falsch“ — "
            "entweder wurde nie ``0x15`` gefragt, oder der Codec in ChirpStack "
            "kennt die Antwort noch nicht (Re-Paste, RUNBOOK §10c.1)."
        )
    return 0


async def _senden(
    ziele: list[Zielgeraet],
    soll: dict[int, Grenzen],
    *,
    pause: float,
    nur_abfragen: bool,
) -> int:
    fehler = 0
    for z in ziele:
        s = soll.get(z.device_id)
        try:
            if not nur_abfragen:
                if s is None:
                    print(f"  uebersprungen (kein Soll): {z.bezeichnung}")
                    continue
                await downlink_adapter.set_temperature_range(z.dev_eui, s.min_c, s.max_c)
                await asyncio.sleep(0.5)
            await downlink_adapter.get_temperature_range(z.dev_eui)
            was = "0x15" if nur_abfragen else f"0x08 {s} + 0x15"
            print(f"  gesendet ({was}): {z.bezeichnung} ({z.dev_eui})")
        except Exception as exc:  # noqa: BLE001 — alle Geraete berichten, dann Exit-Code
            fehler += 1
            print(f"  FEHLER: {z.bezeichnung} ({z.dev_eui}) -> {exc}")
        await asyncio.sleep(pause)
    return fehler


async def _befehl_setzen(args: argparse.Namespace, *, nur_abfragen: bool) -> int:
    ziele, ausnahmen, soll, befunde = await _lage(args.nur)

    if args.nur:
        fehlend = nicht_gefunden(args.nur, ziele, ausnahmen)
        if fehlend:
            # Abbruch, nicht Warnung: ein Tippfehler fuehrt sonst zu einem
            # leeren Lauf, und der sieht wie „alles ausgenommen" aus.
            print(f"\nNicht gefunden: {', '.join(fehlend)}")
            print("Abbruch — es wird nichts gesendet. Bezeichnung pruefen.")
            return 2

    was = "Grenzen abfragen (0x15)" if nur_abfragen else "Grenzen setzen (0x08 + 0x15)"
    print(f"\n=== {was} ===")
    offen = _zeige_lage(ziele, soll, befunde)
    if ausnahmen:
        _zeige_ausnahmen(ausnahmen)

    if not ziele:
        print("\nKein Ziel — es wird nichts gesendet.")
        return 0

    # Die Bytes **vor** dem Senden erzeugen, auch im Probelauf: ein
    # ungueltiger Wert scheitert damit hier und nicht am Geraet.
    if not nur_abfragen:
        for z in ziele:
            s = soll.get(z.device_id)
            if s is None:
                continue
            try:
                downlink_adapter.temp_range_bytes(s.min_c, s.max_c)
            except downlink_adapter.DownlinkError as exc:
                print(f"\nUngueltige Grenzen fuer {z.bezeichnung}: {exc}")
                print("Abbruch — es wird nichts gesendet.")
                return 2

    zu_senden = ziele if args.alle else offen
    if not nur_abfragen and not zu_senden:
        print("\nAlle Geraete stimmen. Es wird nichts gesendet (S4).")
        print("Mit --alle trotzdem senden.")
        return 0

    if not args.ausfuehren:
        print(
            f"\nProbelauf: es wurde **nichts** gesendet. {len(zu_senden)} Geraet(e) "
            f"wuerden einen Befehl bekommen.\nMit --ausfuehren wiederholen."
        )
        return 0

    print(f"\nSende an {len(zu_senden)} Geraet(e), Pause {args.pause} s:")
    fehler = await _senden(zu_senden, soll, pause=args.pause, nur_abfragen=nur_abfragen)
    print(f"\nFertig. {len(zu_senden) - fehler} von {len(zu_senden)} gesendet, {fehler} Fehler.")
    print(
        "Die Bestaetigung kommt asynchron mit dem naechsten Keepalive "
        "(bis ~10 min). Danach `vergleich` — er liest die Antwort, nicht "
        "das Gesendete."
    )
    return 1 if fehler else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    unter = parser.add_subparsers(dest="befehl", required=True)

    def _gemeinsam(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--nur",
            action="append",
            default=[],
            metavar="BEZEICHNUNG",
            help="Geraet nach Bezeichnung oder DevEUI waehlen, mehrfach moeglich. "
            'Zum Beispiel --nur "107 Schlafzimmer". Ohne Angabe: alle montierten '
            "Thermostate (ohne nur-messen, ohne Reserve-Pool).",
        )
        p.add_argument(
            "--ausfuehren",
            action="store_true",
            help="Wirklich senden. Ohne diese Angabe ist es ein Probelauf.",
        )
        p.add_argument(
            "--pause",
            type=float,
            default=2.0,
            help="Pause zwischen den Geraeten in Sekunden, Vorgabe 2.0 (Duty-Cycle).",
        )

    p_setzen = unter.add_parser("setzen", help="0x08 mit den Soll-Grenzen, danach 0x15")
    _gemeinsam(p_setzen)
    p_setzen.add_argument(
        "--alle",
        action="store_true",
        help="Auch an Geraete senden, deren gemeldete Grenzen schon stimmen. "
        "Ohne diese Angabe werden sie uebersprungen — der Abgleich soll nicht "
        "funken, wenn nichts zu tun ist (S4).",
    )

    p_abfragen = unter.add_parser("abfragen", help="nur 0x15")
    _gemeinsam(p_abfragen)
    p_abfragen.set_defaults(alle=True)

    p_vergleich = unter.add_parser("vergleich", help="Soll gegen Gemeldetes, ohne zu senden")
    p_vergleich.add_argument(
        "--nur", action="append", default=[], metavar="BEZEICHNUNG", help="wie bei setzen"
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.befehl == "setzen":
        return asyncio.run(_befehl_setzen(args, nur_abfragen=False))
    if args.befehl == "abfragen":
        return asyncio.run(_befehl_setzen(args, nur_abfragen=True))
    return asyncio.run(_befehl_vergleich(args))


if __name__ == "__main__":
    sys.exit(main())
