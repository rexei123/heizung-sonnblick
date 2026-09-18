#!/usr/bin/env python3
"""ChirpStack-Geraete-Provisioning aus der Pairing-CSV (Sprint 17 / C1, D3, D5).

Legt die OTAA-Geraete in ChirpStack v4 an, die der Pairing-Lauf spaeter in
der heizung-DB erwartet. Ohne diesen Schritt joint kein Vicki, ohne Join
kommt kein Uplink, ohne Uplink scheitert der Eingangstest an Schritt 1.

Warum eigenstaendig (D3)
------------------------

Das Skript liegt bewusst **nicht** unter ``backend/src`` und ``chirpstack-api``
ist **keine** Abhaengigkeit des API-Images. Begruendung:

- Der Downlink-Pfad der Anwendung laeuft ueber MQTT, nicht gRPC (AE-48,
  CLAUDE.md §5.28). Diese Trennung soll bleiben — ein gRPC-Client im
  API-Image waere eine zweite Steuerleitung zur Hardware.
- Provisioning ist ein einmaliger Vorgang vor der Montage, kein
  Betriebspfad. Es gehoert zum Infrastruktur-Setup, nicht zur Anwendung.

Aufruf deshalb als Einmal-Container im Compose-Netz (RUNBOOK §10h).

Historie: Sprint 13 hat den gRPC-Bootstrap 2026-05-21 verworfen
(SPRINT-PLAN Z. 1092, Z. 1265) mit der Begruendung, der Hotelier mache
einen "Bulk-Import im ChirpStack-UI". Den gibt es in ChirpStack v4 nicht.
Bei 104 Geraeten plus Nachlieferungen ist Handarbeit weder zumutbar noch
reproduzierbar — die Verwerfung ist mit AE-69 revidiert.

Was es tut
----------

Pro CSV-Zeile:

- Geraet existiert bereits -> Abweichungen bei Name und Device-Profile
  **melden**, nichts ueberschreiben.
- Geraet fehlt -> ``Device`` anlegen (``name`` = ``hardware_nummer`` laut
  D5, ``join_eui`` = ``app_eui``) und die OTAA-Keys setzen.

Default ist **Dry-Run**. Geschrieben wird nur mit ``--apply``.

Das Key-Feld wird gespiegelt, nicht geraten
-------------------------------------------

``DeviceKeys`` hat in ChirpStack v4 **zwei** Felder, ``nwk_key`` und
``app_key``. Bei LoRaWAN 1.0.x gehoert der AppKey vom Aufkleber in
``nwk_key`` — ``app_key`` ist dort ungenutzt und erst ab 1.1 belegt. Das
ist leicht zu verwechseln und ein falsch befuelltes Feld faellt erst auf,
wenn 100 Geraete nicht joinen.

Deshalb: ``--key-reference-dev-eui`` nennt ein bereits funktionierendes
Geraet (eines der vier Testgeraete). Der Pre-Flight liest dessen Keys via
``GetKeys`` und prueft, welches Feld dort belegt ist. Weicht das vom
gewaehlten Feld ab, bricht der Lauf ab. Schluesselwerte werden dabei
**nie** ausgegeben — nur "gesetzt"/"leer" und die Laenge.

Aufruf
------

    python provision_devices.py pairings.csv \\
        --application-id <uuid> --device-profile-id <uuid> \\
        --key-reference-dev-eui <eui-eines-testgeraets>

    # danach, wenn die Vorschau stimmt:
    python provision_devices.py pairings.csv ... --apply

``CHIRPSTACK_API_KEY`` kommt aus der Umgebung, nie als Argument — sonst
steht der Token in der Shell-History und in ``docker inspect``.

Exit-Codes: 0 = nichts zu tun oder alles angelegt · 1 = Pre-Flight-Fehler,
Abweichung oder Anlage-Fehler.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import os
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

# Bewusste Duplikation zu ``backend/src/heizung/scripts/pairing/csv_row.py``:
# dieses Skript laeuft in einem eigenen Container ohne das heizung-Package.
# Die Spaltennamen sind deshalb hier nochmal festgeschrieben — und durch
# ``test_expected_columns_match_pairing_csv`` gegen ein stilles Auseinander-
# laufen abgesichert.
COL_DEV_EUI = "dev_eui"
COL_APP_KEY = "app_key"
COL_APP_EUI = "app_eui"
COL_HARDWARE_NUMMER = "hardware_nummer"

REQUIRED_COLUMNS = (COL_DEV_EUI, COL_APP_KEY)
OPTIONAL_COLUMNS = (COL_APP_EUI, COL_HARDWARE_NUMMER)

_HEX16 = re.compile(r"^[0-9a-fA-F]{16}$")
_HEX32 = re.compile(r"^[0-9a-fA-F]{32}$")

# LoRaWAN-Nullwert fuer die JoinEUI. ChirpStack verlangt das Feld; wenn die
# CSV keine AppEUI nennt, ist die Acht-Byte-Null die uebliche Belegung.
ZERO_JOIN_EUI = "0000000000000000"

# Seitengroesse fuer DeviceService.List. 250 deckt die 104 Geraete des
# Hotels in einem Aufruf ab; die Paginierung bleibt trotzdem implementiert,
# weil ChirpStack die Seitengroesse serverseitig deckeln darf.
LIST_PAGE_SIZE = 250


class ProvisionError(Exception):
    """Abbruchgrund, der dem Aufrufer als Klartext praesentiert wird."""


@dataclass(frozen=True, slots=True)
class CsvDevice:
    """Eine Geraete-Zeile, reduziert auf das, was ChirpStack braucht."""

    row_number: int
    dev_eui: str
    app_key: str
    join_eui: str
    name: str

    @property
    def masked_key(self) -> str:
        """Key nur als Laengen-Angabe. Nie den Wert."""
        return f"<{len(self.app_key)} Hex-Zeichen, nicht angezeigt>"


def _normalize_header(raw: str) -> str:
    return raw.strip().lower()


def read_csv(path: Path) -> list[CsvDevice]:
    """Liest die Pairing-CSV und liefert die Geraete-Zeilen.

    Toleriert dieselben Eigenheiten wie der Pairing-Parser: BOM aus dem
    deutschen Excel, Semikolon oder Komma als Trennzeichen, kopflose
    Spalten, Gross-/Kleinschreibung im Header.

    :raises ProvisionError: fehlende Pflichtspalte oder ungueltiger Wert.
    """
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ProvisionError(f"{path} ist leer.")

    try:
        dialect: Any = csv.Sniffer().sniff(text[:4096], delimiters=";,")
    except csv.Error as exc:
        raise ProvisionError(f"Trennzeichen nicht erkennbar: {exc}") from exc

    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if reader.fieldnames is None:
        raise ProvisionError(f"{path} hat keine Kopfzeile.")

    headers = {_normalize_header(h) for h in reader.fieldnames if h}
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise ProvisionError(
            f"Pflichtspalte(n) fehlen: {', '.join(missing)}. Gefunden: {', '.join(sorted(headers))}"
        )

    devices: list[CsvDevice] = []
    errors: list[str] = []
    for line_no, raw in enumerate(reader, start=2):
        cleaned: dict[str, str] = {}
        for raw_key, raw_val in raw.items():
            if raw_key is None:
                continue
            key = _normalize_header(raw_key)
            if not key:
                continue
            cleaned[key] = (raw_val or "").strip()

        dev_eui = cleaned.get(COL_DEV_EUI, "")
        app_key = cleaned.get(COL_APP_KEY, "")
        app_eui = cleaned.get(COL_APP_EUI, "")
        name = cleaned.get(COL_HARDWARE_NUMMER, "")

        if not _HEX16.fullmatch(dev_eui):
            errors.append(f"Zeile {line_no}: dev_eui ist keine 16-stellige Hex-Zahl.")
            continue
        if not _HEX32.fullmatch(app_key):
            errors.append(f"Zeile {line_no}: app_key ist keine 32-stellige Hex-Zahl.")
            continue
        if app_eui and not _HEX16.fullmatch(app_eui):
            errors.append(f"Zeile {line_no}: app_eui ist keine 16-stellige Hex-Zahl.")
            continue

        devices.append(
            CsvDevice(
                row_number=line_no,
                dev_eui=dev_eui.lower(),
                app_key=app_key.lower(),
                join_eui=(app_eui or ZERO_JOIN_EUI).lower(),
                # D5: der ChirpStack-Geraetename ist die Durchnummerierung.
                # Ohne Angabe faellt er auf die DevEUI zurueck, damit das
                # Geraet im ChirpStack-UI ueberhaupt auffindbar bleibt.
                name=name or dev_eui.lower(),
            )
        )

    if errors:
        raise ProvisionError("Ungueltige CSV-Zeilen:\n  " + "\n  ".join(errors))

    seen: dict[str, int] = {}
    for dev in devices:
        if dev.dev_eui in seen:
            raise ProvisionError(
                f"DevEUI {dev.dev_eui} steht mehrfach in der CSV "
                f"(Zeilen {seen[dev.dev_eui]}, {dev.row_number})."
            )
        seen[dev.dev_eui] = dev.row_number
    return devices


# ---------------------------------------------------------------------------
# ChirpStack-Zugriff
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemoteDevice:
    """Der Teil eines ChirpStack-Geraets, den wir vergleichen."""

    dev_eui: str
    name: str
    application_id: str
    device_profile_id: str
    join_eui: str


@dataclass(frozen=True, slots=True)
class RemoteKeys:
    """Welche Key-Felder bei einem Geraet belegt sind. Ohne die Werte."""

    nwk_key_set: bool
    app_key_set: bool


class ChirpStackClient(Protocol):
    """Die Aufrufe, die dieses Skript braucht.

    Als Protocol, damit die Tests einen Doppelgaenger einsetzen koennen und
    weder gRPC noch ein laufender ChirpStack noetig sind.
    """

    def application_exists(self, application_id: str) -> bool: ...

    def device_profile_exists(self, device_profile_id: str) -> bool: ...

    def list_device_euis(self, application_id: str) -> set[str]: ...

    def get_device(self, dev_eui: str) -> RemoteDevice | None: ...

    def get_device_keys(self, dev_eui: str) -> RemoteKeys | None: ...

    def create_device(
        self,
        *,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        join_eui: str,
    ) -> None: ...

    def create_device_keys(self, *, dev_eui: str, key_field: str, key_value: str) -> None: ...


class GrpcChirpStackClient:
    """Echte Anbindung. Importiert ``chirpstack_api`` erst beim Gebrauch,
    damit Tests und ``--help`` ohne installiertes Paket funktionieren."""

    def __init__(self, server: str, api_token: str) -> None:
        import grpc  # noqa: PLC0415 — bewusst lazy
        from chirpstack_api.api import (  # noqa: PLC0415
            application_pb2,
            application_pb2_grpc,
            device_pb2,
            device_pb2_grpc,
            device_profile_pb2,
            device_profile_pb2_grpc,
        )

        self._grpc = grpc
        self._device_pb2 = device_pb2
        self._application_pb2 = application_pb2
        self._device_profile_pb2 = device_profile_pb2
        self._channel = grpc.insecure_channel(server)
        self._devices = device_pb2_grpc.DeviceServiceStub(self._channel)
        self._applications = application_pb2_grpc.ApplicationServiceStub(self._channel)
        self._profiles = device_profile_pb2_grpc.DeviceProfileServiceStub(self._channel)
        # ChirpStack v4 erwartet den API-Key als Bearer-Token in den
        # gRPC-Metadaten.
        self._auth = [("authorization", f"Bearer {api_token}")]

    def close(self) -> None:
        self._channel.close()

    def _is_not_found(self, exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        return callable(code) and code() == self._grpc.StatusCode.NOT_FOUND

    def _is_unauthenticated(self, exc: Exception) -> bool:
        code = getattr(exc, "code", None)
        return callable(code) and code() == self._grpc.StatusCode.UNAUTHENTICATED

    def _probe(self, call: Callable[[], object], *, what: str, ident: str) -> bool:
        """Existenz-Probe per ``Get`` auf ein benanntes Objekt.

        ChirpStack loest die Berechtigung ueber das Objekt auf. Fehlt das
        Objekt, gibt es keinen Tenant, an dem der API-Key haengen koennte —
        die Antwort ist dann ``UNAUTHENTICATED`` und nicht ``NOT_FOUND``.
        Beim Pre-Flight ist noch nicht bewiesen, dass der Key ueberhaupt
        gilt; aus ``UNAUTHENTICATED`` laesst sich hier also nicht auf
        "existiert nicht" schliessen. Statt zu raten nennen wir beide
        Moeglichkeiten.
        """
        try:
            call()
        except Exception as exc:
            if self._is_not_found(exc):
                return False
            if self._is_unauthenticated(exc):
                raise ProvisionError(
                    f"{what} {ident}: ChirpStack antwortet UNAUTHENTICATED. Entweder "
                    f"ist die ID falsch (dann gibt es kein Objekt, ueber das die "
                    f"Berechtigung aufgeloest werden koennte), oder der API-Key gilt "
                    f"nicht fuer diesen Tenant. Beides zuerst im ChirpStack-UI pruefen."
                ) from exc
            raise
        return True

    def application_exists(self, application_id: str) -> bool:
        req = self._application_pb2.GetApplicationRequest(id=application_id)
        return self._probe(
            lambda: self._applications.Get(req, metadata=self._auth),
            what="Application",
            ident=application_id,
        )

    def device_profile_exists(self, device_profile_id: str) -> bool:
        req = self._device_profile_pb2.GetDeviceProfileRequest(id=device_profile_id)
        return self._probe(
            lambda: self._profiles.Get(req, metadata=self._auth),
            what="Device-Profile",
            ident=device_profile_id,
        )

    def list_device_euis(self, application_id: str) -> set[str]:
        """Alle DevEUIs der Application, in so wenig Aufrufen wie moeglich.

        Ersetzt die frueheren 104 Einzel-``Get``-Aufrufe. ``List`` laeuft
        gegen die Application — ein existierendes Objekt, an dem die
        Berechtigung haengt. Damit entfaellt das UNAUTHENTICATED-Problem
        unbekannter DevEUIs vollstaendig.
        """
        found: set[str] = set()
        offset = 0
        while True:
            req = self._device_pb2.ListDevicesRequest(
                limit=LIST_PAGE_SIZE, offset=offset, application_id=application_id
            )
            resp = self._devices.List(req, metadata=self._auth)
            page = [item.dev_eui.lower() for item in resp.result]
            found.update(page)
            offset += len(page)
            # Abbruch auf zwei Wegen, damit eine unerwartete Antwort keine
            # Endlosschleife erzeugt: leere Seite oder total_count erreicht.
            if not page or offset >= resp.total_count:
                return found

    def get_device(self, dev_eui: str) -> RemoteDevice | None:
        req = self._device_pb2.GetDeviceRequest(dev_eui=dev_eui)
        try:
            resp = self._devices.Get(req, metadata=self._auth)
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise
        d = resp.device
        return RemoteDevice(
            dev_eui=d.dev_eui,
            name=d.name,
            application_id=d.application_id,
            device_profile_id=d.device_profile_id,
            join_eui=d.join_eui,
        )

    def get_device_keys(self, dev_eui: str) -> RemoteKeys | None:
        req = self._device_pb2.GetDeviceKeysRequest(dev_eui=dev_eui)
        try:
            resp = self._devices.GetKeys(req, metadata=self._auth)
        except Exception as exc:
            if self._is_not_found(exc):
                return None
            raise
        keys = resp.device_keys
        # Nur die Belegung, nie die Werte.
        return RemoteKeys(
            nwk_key_set=bool(keys.nwk_key.strip("0")),
            app_key_set=bool(keys.app_key.strip("0")),
        )

    def create_device(
        self,
        *,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        join_eui: str,
    ) -> None:
        device = self._device_pb2.Device(
            dev_eui=dev_eui,
            name=name,
            application_id=application_id,
            device_profile_id=device_profile_id,
            join_eui=join_eui,
        )
        self._devices.Create(
            self._device_pb2.CreateDeviceRequest(device=device), metadata=self._auth
        )

    def create_device_keys(self, *, dev_eui: str, key_field: str, key_value: str) -> None:
        keys = self._device_pb2.DeviceKeys(dev_eui=dev_eui, **{key_field: key_value})
        self._devices.CreateKeys(
            self._device_pb2.CreateDeviceKeysRequest(device_keys=keys), metadata=self._auth
        )


# ---------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------

KEY_FIELD_NWK = "nwk_key"
KEY_FIELD_APP = "app_key"

# LoRaWAN 1.0.x (Hotel Sonnblick: MAC 1.0.3, RegParams A): der AppKey vom
# Aufkleber gehoert in ``nwk_key``. ``app_key`` ist erst ab 1.1 belegt.
DEFAULT_KEY_FIELD = KEY_FIELD_NWK


@dataclass
class Report:
    """Zaehlwerk fuer die Schluss-Zusammenfassung."""

    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deviations: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.deviations or self.failures else 0


def verify_key_field(
    client: ChirpStackClient, reference_dev_eui: str, chosen_field: str
) -> list[str]:
    """Spiegelt die Feldbelegung eines bekannten Geraets (C1-Vorgabe).

    Gibt Ausgabezeilen zurueck; wirft bei Widerspruch. Schluesselwerte
    werden nicht gelesen und nicht ausgegeben — nur die Belegung.
    """
    keys = client.get_device_keys(reference_dev_eui)
    if keys is None:
        raise ProvisionError(
            f"Referenzgeraet {reference_dev_eui} hat keine Keys in ChirpStack. "
            "Bitte ein Geraet angeben, das nachweislich joint."
        )
    populated = [
        name
        for name, is_set in ((KEY_FIELD_NWK, keys.nwk_key_set), (KEY_FIELD_APP, keys.app_key_set))
        if is_set
    ]
    lines = [
        f"  Referenz {reference_dev_eui}: "
        f"nwk_key={'gesetzt' if keys.nwk_key_set else 'leer'}, "
        f"app_key={'gesetzt' if keys.app_key_set else 'leer'}"
    ]
    if not populated:
        raise ProvisionError(
            f"Referenzgeraet {reference_dev_eui} hat weder nwk_key noch app_key gesetzt — "
            "daraus laesst sich nichts spiegeln."
        )
    if len(populated) > 1:
        # Beide Felder belegt: daraus laesst sich NICHT ablesen, welches das
        # joinende Geraet tatsaechlich benutzt. Stillschweigend nwk_key zu
        # waehlen waere geraten — und genau das soll die Spiegelung
        # verhindern. Der Hotelier klaert es im ChirpStack-UI und setzt dann
        # --key-field bewusst.
        raise ProvisionError(
            f"Referenzgeraet {reference_dev_eui} hat BEIDE Key-Felder belegt "
            "(nwk_key und app_key). Daraus ist nicht ablesbar, welches beim Join "
            "wirksam ist. Bitte im ChirpStack-UI klaeren und das Feld dann mit "
            "--key-field ausdruecklich setzen — oder ein Referenzgeraet waehlen, "
            "bei dem nur eines belegt ist."
        )
    if chosen_field not in populated:
        raise ProvisionError(
            f"Feld-Spiegelung widerspricht: gewaehlt ist '{chosen_field}', "
            f"belegt ist aber {', '.join(populated)}. "
            "Entweder --key-field korrigieren oder ein anderes Referenzgeraet waehlen."
        )
    lines.append(f"  -> '{chosen_field}' bestaetigt.")
    return lines


def preflight(
    client: ChirpStackClient,
    *,
    application_id: str,
    device_profile_id: str,
    expected_app_id: str | None,
) -> None:
    """Application + DeviceProfile existieren, App-ID passt zur Anwendung.

    ``expected_app_id`` ist der Wert, mit dem die Heizungs-API ihre
    Downlink-Topics baut (``CHIRPSTACK_APP_ID``). Weicht er ab, wuerden die
    Geraete zwar angelegt, aber jeder Setpoint ginge auf ein Topic, das
    niemand abonniert — stiller Totalausfall der Steuerung.
    """
    if expected_app_id and expected_app_id != application_id:
        raise ProvisionError(
            f"Application-ID weicht ab: Provisioning nutzt {application_id}, "
            f"die API erwartet {expected_app_id}. Downlinks wuerden ins Leere gehen."
        )
    if not client.application_exists(application_id):
        raise ProvisionError(f"Application {application_id} existiert nicht in ChirpStack.")
    if not client.device_profile_exists(device_profile_id):
        raise ProvisionError(f"Device-Profile {device_profile_id} existiert nicht in ChirpStack.")


def _compare(dev: CsvDevice, remote: RemoteDevice, device_profile_id: str) -> list[str]:
    """Abweichungen zwischen CSV-Soll und ChirpStack-Ist."""
    diffs: list[str] = []
    if remote.name != dev.name:
        diffs.append(f"name: ChirpStack={remote.name!r} != CSV={dev.name!r}")
    if remote.device_profile_id != device_profile_id:
        diffs.append(
            f"device_profile_id: ChirpStack={remote.device_profile_id} != Soll={device_profile_id}"
        )
    if remote.join_eui and remote.join_eui.lower() != dev.join_eui:
        diffs.append(f"join_eui: ChirpStack={remote.join_eui} != CSV={dev.join_eui}")
    return diffs


def provision(
    client: ChirpStackClient,
    devices: Sequence[CsvDevice],
    *,
    application_id: str,
    device_profile_id: str,
    key_field: str,
    apply: bool,
) -> tuple[Report, list[str]]:
    """Legt fehlende Geraete an, meldet Abweichungen, fasst zusammen.

    Idempotent: ein zweiter Lauf findet alle Geraete vor und aendert nichts.
    """
    report = Report()
    lines: list[str] = []

    # Der Bestand wird EINMAL ueber die Application geholt, nicht pro Zeile
    # per ``Get`` erfragt. Zwei Gruende, der erste ist der zwingende:
    #
    # 1. ``DeviceService.Get`` auf ein **unbekanntes** DevEUI antwortet mit
    #    UNAUTHENTICATED, nicht mit NOT_FOUND: ChirpStack loest die
    #    Berechtigung ueber das Geraet auf den Tenant auf, und ein nicht
    #    existierendes Geraet hat keinen Tenant. Der Probelauf am 18.09. ist
    #    genau daran gescheitert — beim ersten noch nicht angelegten Geraet,
    #    mit gueltigem Key und unmittelbar nach erfolgreichem Pre-Flight.
    # 2. Ein Aufruf statt 104.
    existing = client.list_device_euis(application_id)
    lines.append(
        f"Bestand in der Application: {len(existing)} Geraete — "
        f"Abgleich gegen {len(devices)} CSV-Zeilen."
    )

    for dev in devices:
        # ``Get`` nur fuer Geraete, die laut Bestand existieren: dort ist die
        # Berechtigung aufloesbar, und nur dort gibt es etwas zu vergleichen
        # (``DeviceListItem`` traegt weder application_id noch join_eui).
        # Liefert ``Get`` wider Erwarten nichts, faellt die Zeile auf den
        # Anlage-Pfad durch — das ist der richtige Umgang mit einem Geraet,
        # das zwischen List und Get geloescht wurde.
        remote = client.get_device(dev.dev_eui) if dev.dev_eui in existing else None
        if remote is not None:
            diffs = _compare(dev, remote, device_profile_id)
            if diffs:
                report.deviations.append(dev.dev_eui)
                lines.append(f"[ABWEICHUNG] Zeile {dev.row_number} {dev.dev_eui}:")
                lines.extend(f"    {d}" for d in diffs)
                lines.append("    nichts geaendert — Bestand hat Vorrang.")
            else:
                report.unchanged.append(dev.dev_eui)
                lines.append(
                    f"[OK]         Zeile {dev.row_number} {dev.dev_eui} "
                    f"({dev.name}) — bereits vorhanden."
                )
            continue

        if not apply:
            report.created.append(dev.dev_eui)
            lines.append(
                f"[WUERDE ANLEGEN] Zeile {dev.row_number} {dev.dev_eui} "
                f"name={dev.name} join_eui={dev.join_eui} "
                f"{key_field}={dev.masked_key}"
            )
            continue

        try:
            client.create_device(
                dev_eui=dev.dev_eui,
                name=dev.name,
                application_id=application_id,
                device_profile_id=device_profile_id,
                join_eui=dev.join_eui,
            )
            client.create_device_keys(
                dev_eui=dev.dev_eui, key_field=key_field, key_value=dev.app_key
            )
        except Exception as exc:  # noqa: BLE001 — pro Zeile weiterlaufen
            report.failures.append(dev.dev_eui)
            # Nur Typ + Text der Ausnahme, nie das Payload.
            lines.append(
                f"[FEHLER]     Zeile {dev.row_number} {dev.dev_eui}: {type(exc).__name__}: {exc}"
            )
            continue
        report.created.append(dev.dev_eui)
        lines.append(
            f"[ANGELEGT]   Zeile {dev.row_number} {dev.dev_eui} "
            f"name={dev.name} join_eui={dev.join_eui}"
        )
    return report, lines


def summary_lines(report: Report, *, apply: bool) -> Iterator[str]:
    verb = "angelegt" if apply else "anzulegen"
    yield ""
    yield (
        f"Resultat: {len(report.created)} {verb}, "
        f"{len(report.unchanged)} unveraendert, "
        f"{len(report.deviations)} Abweichungen, "
        f"{len(report.failures)} Fehler."
    )
    if not apply and report.created:
        yield "Dies war eine Vorschau. Zum Schreiben denselben Aufruf mit --apply wiederholen."
    if report.deviations:
        yield (
            "Abweichungen bedeuten: das Geraet steht mit anderen Werten in ChirpStack. "
            "Es wurde nichts ueberschrieben. Entweder die CSV korrigieren oder das "
            "Geraet im ChirpStack-UI bewusst anpassen."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="provision_devices.py",
        description="Legt die Vickis aus der Pairing-CSV in ChirpStack v4 an.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Der API-Key kommt aus der Umgebungsvariable CHIRPSTACK_API_KEY.\n"
            "Er wird bewusst nicht als Argument angenommen — sonst stuende er\n"
            "in der Shell-History und in 'docker inspect'."
        ),
    )
    parser.add_argument("csv", help="Pfad zur Pairing-CSV.")
    parser.add_argument(
        "--server",
        default="chirpstack:8080",
        help="gRPC-Adresse von ChirpStack. Default: chirpstack:8080 (Compose-Netz).",
    )
    parser.add_argument("--application-id", required=True, help="Ziel-Application (UUID).")
    parser.add_argument("--device-profile-id", required=True, help="Device-Profile (UUID).")
    parser.add_argument(
        "--expected-app-id",
        default=None,
        help="CHIRPSTACK_APP_ID der Heizungs-API. Muss mit --application-id "
        "uebereinstimmen, sonst Abbruch (Downlink-Topic-Schutz).",
    )
    parser.add_argument(
        "--key-reference-dev-eui",
        default=None,
        help="DevEUI eines bereits funktionierenden Geraets. Der Pre-Flight "
        "spiegelt dessen Key-Feldbelegung, statt sie zu raten.",
    )
    parser.add_argument(
        "--key-field",
        choices=(KEY_FIELD_NWK, KEY_FIELD_APP),
        default=DEFAULT_KEY_FIELD,
        help=f"Zielfeld fuer den AppKey. Default {DEFAULT_KEY_FIELD} (LoRaWAN 1.0.x).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Schreiben. Ohne dieses Flag laeuft nur die Vorschau.",
    )
    return parser


def _force_line_buffering() -> None:
    """stdout zeilenweise leeren, damit der Ablauf lesbar bleibt.

    Ohne das puffert Python stdout in Bloecken, sobald die Ausgabe nicht
    an ein Terminal geht — und im ``docker run``-Aufruf ist das der
    Normalfall. stderr ist ungepuffert. Folge im Probelauf am 18.09.:
    die Pre-Flight-Zeilen erschienen erst beim Prozess-Ende und landeten
    optisch mitten im Traceback. Der Ablauf am 26.09. muss von oben nach
    unten lesbar sein.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            # Umgelenkte Streams (pytest-capsys, Pipes ohne fileno) koennen
            # das ablehnen. Kein Grund, den Lauf abzubrechen.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(line_buffering=True)


def run(argv: Sequence[str] | None, client_factory: Any = None) -> int:
    _force_line_buffering()
    args = build_parser().parse_args(argv)

    api_token = os.environ.get("CHIRPSTACK_API_KEY", "").strip()
    if not api_token:
        print(
            "[ABBRUCH] CHIRPSTACK_API_KEY ist nicht gesetzt. Der Token wird "
            "ausschliesslich ueber die Umgebung uebergeben.",
            file=sys.stderr,
        )
        return 1

    try:
        devices = read_csv(Path(args.csv))
    except ProvisionError as exc:
        print(f"[ABBRUCH] {exc}", file=sys.stderr)
        return 1

    factory = client_factory or (lambda: GrpcChirpStackClient(args.server, api_token))
    client = factory()
    try:
        try:
            preflight(
                client,
                application_id=args.application_id,
                device_profile_id=args.device_profile_id,
                expected_app_id=args.expected_app_id,
            )
            print(f"Pre-Flight: Application + Device-Profile vorhanden, {len(devices)} CSV-Zeilen.")
            if args.key_reference_dev_eui:
                for line in verify_key_field(client, args.key_reference_dev_eui, args.key_field):
                    print(line)
            else:
                print(
                    f"  [HINWEIS] Kein --key-reference-dev-eui angegeben. Das Key-Feld "
                    f"'{args.key_field}' ist damit gesetzt, aber nicht gegen ein "
                    "funktionierendes Geraet gespiegelt.",
                    file=sys.stderr,
                )
        except ProvisionError as exc:
            print(f"[ABBRUCH] {exc}", file=sys.stderr)
            return 1

        report, lines = provision(
            client,
            devices,
            application_id=args.application_id,
            device_profile_id=args.device_profile_id,
            key_field=args.key_field,
            apply=args.apply,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    for line in lines:
        print(line)
    for line in summary_lines(report, apply=args.apply):
        print(line)
    return report.exit_code


def main() -> int:
    return run(None)


if __name__ == "__main__":
    sys.exit(main())
