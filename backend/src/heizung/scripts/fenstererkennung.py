r"""Die Fenstererkennung im Gerät setzen, abschalten, nachsehen (Sprint 23 T2).

Vier Unterbefehle:

    setzen   0x45 mit Delta und Dauer, danach 0x46 zum Zurücklesen
    aus      0x45 mit enabled=0 — der Rückweg für das Abbruchkriterium
    status   nur 0x46, fragt den aktuellen Stand ab
    befund   liest die Datenbank: hat die Erkennung ausgelöst, und war es
             unsere eigene Absenkung?

**Ein Probelauf ist der Standard.** Ohne ``--ausfuehren`` wird nichts
gesendet, sondern aufgezählt, was gesendet würde — mit den Bytes. Jeder
dieser Befehle greift produktive Hardware an (S4), und ein Werkzeug, das
beim ersten Tippfehler funkt, ist das falsche Werkzeug. Der Probelauf
zeigt außerdem die **Ausnahmen** mit Grund, und das ist der Teil, den man
vor dem Lauf lesen will.

Aufruf (Prod-Container heißt ``deploy-api-1``):

    docker exec <api> python -m heizung.scripts.fenstererkennung setzen \
        --nur "105" --nur "110" --nur "306 Schlafzimmer"
    docker exec <api> python -m heizung.scripts.fenstererkennung setzen \
        --nur "105" --nur "110" --nur "306 Schlafzimmer" --ausfuehren

Die Messung T2.5 — **genau ein Gerät**, Delta 0,2, am Vormittag:

    docker exec <api> python -m heizung.scripts.fenstererkennung setzen \
        --nur "306 Schlafzimmer" --delta 0.2 --ausfuehren

Das Abbruchkriterium vollziehen — **alle** Testgeräte aus:

    docker exec <api> python -m heizung.scripts.fenstererkennung aus \
        --nur "105" --nur "110" --nur "306 Schlafzimmer" --ausfuehren

Der Befund nach zwei Nächten:

    docker exec <api> python -m heizung.scripts.fenstererkennung befund --stunden 72

**Verhältnis zu ``activate_open_window_detection``.** Das alte Skript
bleibt und tut, was sein Name sagt: Bulk-Aktivierung mit FW-Abfrage
davor. Es ist der Weg für „alle Vickis nach einer Neumontage". Dieses
Werkzeug hier ist der Weg für **einzelne** Geräte mit **eigenen**
Parametern, und es ist der einzige, der auch abschalten kann. Die Auswahl
der Ziele und die Ausnahmen kommen in beiden Fällen aus
``services/fenstererkennung`` — eine Liste, eine Stelle.

**Was dieses Werkzeug nicht prüft:** die Firmware. ``0x45`` greift erst
ab FW 4.2; darunter wäre ``0x06`` der Befehl (B-17-5, offen). Das alte
Skript hat dafür das Gate, weil es blind über alle Geräte läuft. Hier
werden Geräte **namentlich** gewählt, und die Firmware steht im
Probelauf-Bericht neben jedem Namen — wer „(NULL)" oder „4.1" dort liest
und trotzdem ausführt, hat es gesehen. Ein zweites Gate hätte den Lauf
bei genau denselben Geräten abgebrochen, über die der Betreiber gerade
entscheidet.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

# Siehe ``activate_open_window_detection``: der Guard trennt den
# CLI-Aufruf vom Import durch die Tests. Ohne ihn hielte ein gesammeltes
# Testmodul die Datenbank fuer konfiguriert.
if __name__ == "__main__":  # pragma: no cover - Einstiegspunkt
    os.environ.setdefault("ENVIRONMENT", "test")
    os.environ.setdefault("ALLOW_DEFAULT_SECRETS", "1")

from sqlalchemy import select  # noqa: E402

from heizung.db import SessionLocal  # noqa: E402
from heizung.models.enums import RuleConfigScope  # noqa: E402
from heizung.models.global_config import GlobalConfig  # noqa: E402
from heizung.models.rule_config import RuleConfig  # noqa: E402
from heizung.services import downlink_adapter  # noqa: E402
from heizung.services.fenstererkennung import (  # noqa: E402
    OW_DAUER_MIN_BETRIEB,
    OW_DELTA_BETRIEB,
    episoden,
    lade_messwerte,
)
from heizung.services.geraete_ziele import (  # noqa: E402
    Ausnahme,
    Zielgeraet,
    lade_ziele,
    nicht_gefunden,
)

logger = logging.getLogger("fenstererkennung")

#: Rueckfall, falls im Haus **keine** Nachtabsenkung konfiguriert ist.
#: Gelesen wird zuerst die Konfiguration (``rule_config``, scope global) —
#: eine Zahl im Code waere eine zweite Wahrheit und beim ersten
#: Nachjustieren falsch (§5.77). Der Rueckfall steht hier, damit der
#: Befund auch ohne Konfiguration eine Aussage macht statt zu schweigen,
#: und er wird im Bericht **als Rueckfall gekennzeichnet**.
NACHT_START_VORGABE = time(20, 0)
NACHT_ENDE_VORGABE = time(6, 0)
ZONE_VORGABE = "Europe/Vienna"


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


def _zeige_ziele(ziele: list[Zielgeraet], bytes_je_geraet: bytes) -> None:
    print("\n--- Ziele ---")
    _tabelle(
        ["Bezeichnung", "dev_eui", "Firmware", "Bytes"],
        [
            [z.bezeichnung, z.dev_eui, z.firmware_version or "(NULL)", bytes_je_geraet.hex()]
            for z in ziele
        ],
    )


async def _nachtfenster() -> tuple[time, time, str, bool]:
    """Nachtfenster und Zeitzone des Hauses.

    Returns ``(start, ende, zone, aus_konfiguration)``. Das letzte Feld
    ist nicht Zierde: ein Befund, der mit dem Rueckfall gerechnet hat,
    sagt womoeglich etwas anderes als das Haus — und das muss im Bericht
    stehen, nicht im Kopf des Lesers.
    """
    async with SessionLocal() as session:
        cfg = (await session.execute(select(GlobalConfig).limit(1))).scalars().first()
        zone = (cfg.timezone if cfg and cfg.timezone else ZONE_VORGABE) or ZONE_VORGABE
        regel = (
            (
                await session.execute(
                    select(RuleConfig)
                    .where(RuleConfig.scope == RuleConfigScope.GLOBAL)
                    .where(RuleConfig.room_id.is_(None))
                    .where(RuleConfig.room_type_id.is_(None))
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
    if regel is not None and regel.night_start is not None and regel.night_end is not None:
        return regel.night_start, regel.night_end, zone, True
    return NACHT_START_VORGABE, NACHT_ENDE_VORGABE, zone, False


async def _senden(
    ziele: list[Zielgeraet],
    *,
    enabled: bool,
    dauer_min: int,
    delta: Decimal,
    auch_abfragen: bool,
) -> int:
    """Sendet je Gerät ``0x45`` und — wenn gewünscht — ``0x46``.

    Sequentiell mit einer halben Sekunde Pause, wie überall im Repo: die
    ChirpStack-Warteschlange nimmt alles an, die Geräte aber nicht
    gleichzeitig.
    """
    fehler = 0
    for z in ziele:
        try:
            await downlink_adapter.set_open_window_detection(
                z.dev_eui, enabled=enabled, duration_min=dauer_min, delta_c=delta
            )
            await asyncio.sleep(0.5)
            if auch_abfragen:
                await downlink_adapter.get_open_window_detection(z.dev_eui)
                await asyncio.sleep(0.5)
            print(f"  gesendet: {z.bezeichnung} ({z.dev_eui})")
        except Exception as exc:  # noqa: BLE001 — alle Geräte berichten, dann Exit-Code
            fehler += 1
            print(f"  FEHLER: {z.bezeichnung} ({z.dev_eui}) -> {exc}")
    return fehler


async def _befehl_setzen(args: argparse.Namespace, *, enabled: bool) -> int:
    delta = args.delta if enabled else OW_DELTA_BETRIEB
    dauer = args.dauer if enabled else OW_DAUER_MIN_BETRIEB

    async with SessionLocal() as session:
        ziele, ausnahmen = await lade_ziele(session, nur=args.nur)

    if args.nur:
        fehlend = nicht_gefunden(args.nur, ziele, ausnahmen)
        if fehlend:
            # **Abbruch, nicht Warnung.** Ein Tippfehler im Namen führt
            # sonst zu einem leeren Lauf, und ein leerer Lauf sieht wie
            # „alles ausgenommen" aus. Wer drei Geräte nennt und zwei
            # beschickt, hat das nicht gewollt.
            print(f"\nNicht gefunden: {', '.join(fehlend)}")
            print("Abbruch — es wird nichts gesendet. Bezeichnung prüfen.")
            return 2

    # Die Bytes werden **vor** dem Senden erzeugt, auch im Probelauf: so
    # scheitert ein ungültiger Wert hier und nicht erst am Gerät.
    try:
        nutzlast = downlink_adapter.ow_set_bytes(enabled, dauer, delta)
    except downlink_adapter.DownlinkError as exc:
        print(f"Ungültige Parameter: {exc}")
        return 2

    was = "einschalten" if enabled else "AUSSCHALTEN"
    print(f"\n=== Fenstererkennung {was} ===")
    if enabled:
        print(f"Delta {delta} °C, Dauer {dauer} min")
    _zeige_ziele(ziele, nutzlast)
    if ausnahmen:
        _zeige_ausnahmen(ausnahmen)

    if not ziele:
        print("\nKein Ziel — es wird nichts gesendet.")
        return 0

    if not args.ausfuehren:
        print(
            f"\nProbelauf: es wurde **nichts** gesendet. {len(ziele)} Gerät(e) würden "
            f"{nutzlast.hex()} bekommen.\nMit --ausfuehren wiederholen."
        )
        return 0

    fehler = await _senden(ziele, enabled=enabled, dauer_min=dauer, delta=delta, auch_abfragen=True)
    print(f"\nFertig. {len(ziele) - fehler} von {len(ziele)} gesendet, {fehler} Fehler.")
    print(
        "Die Bestätigung kommt asynchron mit dem nächsten Keepalive "
        "(bis ~10 min) — danach `status` oder journalctl "
        "(event_type=MAINTENANCE_VICKI_CONFIG_REPORT)."
    )
    return 1 if fehler else 0


async def _befehl_status(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        ziele, ausnahmen = await lade_ziele(session, nur=args.nur)
    print("\n=== Stand abfragen (0x46) ===")
    _zeige_ziele(ziele, bytes([downlink_adapter.VICKI_OW_GET_COMMAND]))
    if ausnahmen:
        _zeige_ausnahmen(ausnahmen)
    if not args.ausfuehren:
        print("\nProbelauf: nichts gesendet. Mit --ausfuehren wiederholen.")
        return 0
    fehler = 0
    for z in ziele:
        try:
            await downlink_adapter.get_open_window_detection(z.dev_eui)
            await asyncio.sleep(0.5)
            print(f"  abgefragt: {z.bezeichnung}")
        except Exception as exc:  # noqa: BLE001
            fehler += 1
            print(f"  FEHLER: {z.bezeichnung} -> {exc}")
    print(
        "\nDie Antwort kommt asynchron. Sie steht im Protokoll des api-Containers:\n"
        "  docker logs deploy-api-1 2>&1 | grep MAINTENANCE_VICKI_CONFIG_REPORT"
    )
    return 1 if fehler else 0


async def _befehl_befund(args: argparse.Namespace) -> int:
    """Der Bericht für die Testwoche.

    Er beantwortet die eine Frage, an der das Abbruchkriterium hängt: hat
    die Erkennung ausgelöst, und lag das in **unserer** Absenkung? Dazu
    den Temperaturabfall der zehn Minuten davor — ohne ihn ist beim
    nächsten Versuch wieder alles offen (Vorgabe des Betreibers).
    """
    bis = datetime.now(tz=UTC)
    von = bis - timedelta(hours=args.stunden)
    nacht_start, nacht_ende, zone, aus_konfiguration = await _nachtfenster()

    async with SessionLocal() as session:
        ziele, _ = await lade_ziele(session, nur=args.nur)
        werte = await lade_messwerte(
            session, device_ids=[z.device_id for z in ziele], von=von, bis=bis
        )

    name_je_id = {z.device_id: z.bezeichnung for z in ziele}
    gefunden = episoden(werte, nacht_start=nacht_start, nacht_ende=nacht_ende, zone=zone)

    print(f"\n=== Befund der letzten {args.stunden} h ===")
    quelle = "aus der Konfiguration" if aus_konfiguration else "RÜCKFALL, nicht konfiguriert"
    print(f"Nachtabsenkung {nacht_start:%H:%M}–{nacht_ende:%H:%M} ({zone}, {quelle})")
    print(f"Geräte: {len(ziele)}, Messwerte: {len(werte)}")

    if not werte:
        # **Keine Messwerte ist kein „alles ruhig".** Ohne diesen Satz
        # liest sich ein leerer Bericht wie ein guter (§5.55).
        print(
            "\nKeine Messwerte im Zeitraum. Das ist **kein** Befund „ruhig“ — "
            "entweder funkt kein Gerät, oder die Auswahl trifft keines."
        )
        return 1

    _tabelle(
        ["Gerät", "Beginn (Ortszeit)", "Dauer", "in Absenkung", "Abfall 10 min"],
        [
            [
                name_je_id.get(e.device_id, str(e.device_id)),
                e.beginn.astimezone(ZoneInfo(zone)).strftime("%d.%m. %H:%M"),
                f"{int((e.ende - e.beginn).total_seconds() // 60)} min",
                "JA" if e.in_absenkung else "nein",
                f"{e.abfall_k} K" if e.abfall_k is not None else "?",
            ]
            for e in gefunden
        ],
    )

    treffer = [e for e in gefunden if e.trifft_abbruchkriterium]
    if treffer:
        print(
            f"\nABBRUCHKRITERIUM GETROFFEN: {len(treffer)} Auslösung(en) in der "
            "eigenen Absenkung.\nVorgabe des Betreibers: Erkennung auf **allen** "
            "Testgeräten abschalten, Befund dokumentieren, in derselben Woche "
            "**nicht** nachjustieren.\n  python -m heizung.scripts.fenstererkennung "
            "aus --nur ... --ausfuehren"
        )
        return 3
    if gefunden:
        print(
            f"\n{len(gefunden)} Auslösung(en), keine in der Absenkung. "
            "Zu prüfen ist jeweils, ob zu dieser Zeit wirklich gelüftet wurde."
        )
    else:
        print("\nKeine Auslösung im Zeitraum.")
    return 0


def _delta(wert: str) -> Decimal:
    try:
        return Decimal(wert)
    except InvalidOperation as exc:  # pragma: no cover - argparse zeigt die Meldung
        raise argparse.ArgumentTypeError(f"{wert!r} ist keine Zahl") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    unter = parser.add_subparsers(dest="befehl", required=True)

    def _gemeinsam(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--nur",
            action="append",
            default=[],
            metavar="BEZEICHNUNG",
            help="Gerät nach Bezeichnung oder DevEUI wählen, mehrfach möglich. "
            'Zum Beispiel --nur "306 Schlafzimmer". Ohne Angabe: alle montierten '
            "Thermostate (ohne „nur messen“, ohne Reserve-Pool).",
        )
        p.add_argument(
            "--ausfuehren",
            action="store_true",
            help="Wirklich senden. Ohne diese Angabe ist es ein Probelauf.",
        )

    p_setzen = unter.add_parser("setzen", help="0x45 einschalten, danach 0x46")
    _gemeinsam(p_setzen)
    p_setzen.add_argument(
        "--delta",
        type=_delta,
        default=OW_DELTA_BETRIEB,
        help=f"Temperatur-Delta in °C. Vorgabe {OW_DELTA_BETRIEB}. "
        "Für die Messung T2.5: 0.2 — und dann nur an EIN Gerät.",
    )
    p_setzen.add_argument(
        "--dauer",
        type=int,
        default=OW_DAUER_MIN_BETRIEB,
        help=f"Schließzeit in Minuten, Vielfaches von 5. Vorgabe {OW_DAUER_MIN_BETRIEB}.",
    )

    p_aus = unter.add_parser("aus", help="0x45 mit enabled=0 — der Rückweg")
    _gemeinsam(p_aus)

    p_status = unter.add_parser("status", help="nur 0x46, Stand abfragen")
    _gemeinsam(p_status)

    p_befund = unter.add_parser("befund", help="Auslösungen aus der Datenbank")
    p_befund.add_argument(
        "--nur", action="append", default=[], metavar="BEZEICHNUNG", help="wie bei setzen"
    )
    p_befund.add_argument("--stunden", type=int, default=72, help="Zeitraum, Vorgabe 72")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.befehl == "setzen":
        return asyncio.run(_befehl_setzen(args, enabled=True))
    if args.befehl == "aus":
        return asyncio.run(_befehl_setzen(args, enabled=False))
    if args.befehl == "status":
        return asyncio.run(_befehl_status(args))
    return asyncio.run(_befehl_befund(args))


if __name__ == "__main__":
    sys.exit(main())
