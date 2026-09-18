"""Tests fuer provision_devices.py (Sprint 17 / C1).

Kein gRPC, kein laufender ChirpStack: ``FakeClient`` erfuellt das
``ChirpStackClient``-Protocol und wird ueber ``run(argv, client_factory=…)``
eingesetzt. Damit laufen die Tests ohne ``chirpstack-api`` im Interpreter —
das Paket ist absichtlich keine Abhaengigkeit des API-Images (D3).

Die Faelle folgen dem Brief: neu, vorhanden, Abweichung, falsche App-ID.
Dazu die Key-Feld-Spiegelung und der Nachweis, dass Schluesselwerte nirgends
in der Ausgabe landen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from provision_devices import (  # noqa: E402
    DEFAULT_KEY_FIELD,
    OPTIONAL_COLUMNS,
    REQUIRED_COLUMNS,
    ProvisionError,
    RemoteDevice,
    RemoteKeys,
    read_csv,
    run,
)

APP_ID = "b7d74615-6ea9-4b54-aa05-fd094e3c2cae"
PROFILE_ID = "ca52f5f7-59b3-4376-94dd-ed0c7bf2fa44"
KEY_A = "aabbccddeeff00112233445566778899"
KEY_B = "99887766554433221100ffeeddccbbaa"
EUI_A = "70b3d57ed0001001"
EUI_B = "70b3d57ed0001002"
JOIN_EUI = "70b3d57ed0000000"

HEADER = "stockwerk,zimmer_nummer,zone_label,dev_eui,app_key,hardware_nummer,app_eui"


def write_csv(path: Path, *rows: str) -> Path:
    path.write_text("\n".join((HEADER, *rows)) + "\n", encoding="utf-8")
    return path


class FakeClient:
    """Doppelgaenger fuer ChirpStack. Zeichnet alle Schreibzugriffe auf."""

    def __init__(
        self,
        *,
        devices: dict[str, RemoteDevice] | None = None,
        keys: dict[str, RemoteKeys] | None = None,
        known_apps: tuple[str, ...] = (APP_ID,),
        known_profiles: tuple[str, ...] = (PROFILE_ID,),
        fail_create_for: str | None = None,
    ) -> None:
        self.devices = dict(devices or {})
        self.keys = dict(keys or {})
        self.known_apps = known_apps
        self.known_profiles = known_profiles
        self.fail_create_for = fail_create_for
        self.created: list[dict[str, str]] = []
        self.created_keys: list[dict[str, str]] = []
        self.closed = False

    def application_exists(self, application_id: str) -> bool:
        return application_id in self.known_apps

    def device_profile_exists(self, device_profile_id: str) -> bool:
        return device_profile_id in self.known_profiles

    def get_device(self, dev_eui: str) -> RemoteDevice | None:
        return self.devices.get(dev_eui)

    def get_device_keys(self, dev_eui: str) -> RemoteKeys | None:
        return self.keys.get(dev_eui)

    def create_device(
        self,
        *,
        dev_eui: str,
        name: str,
        application_id: str,
        device_profile_id: str,
        join_eui: str,
    ) -> None:
        if self.fail_create_for == dev_eui:
            raise RuntimeError("simulierter gRPC-Fehler")
        self.created.append(
            {
                "dev_eui": dev_eui,
                "name": name,
                "application_id": application_id,
                "device_profile_id": device_profile_id,
                "join_eui": join_eui,
            }
        )
        self.devices[dev_eui] = RemoteDevice(
            dev_eui=dev_eui,
            name=name,
            application_id=application_id,
            device_profile_id=device_profile_id,
            join_eui=join_eui,
        )

    def create_device_keys(self, *, dev_eui: str, key_field: str, key_value: str) -> None:
        self.created_keys.append(
            {"dev_eui": dev_eui, "key_field": key_field, "key_value": key_value}
        )

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHIRPSTACK_API_KEY", "test-token-not-a-real-key")


def base_args(csv_path: Path, *extra: str) -> list[str]:
    return [
        str(csv_path),
        "--application-id",
        APP_ID,
        "--device-profile-id",
        PROFILE_ID,
        *extra,
    ]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_expected_columns_match_pairing_csv() -> None:
    """Pinnt die Spaltennamen gegen ``csv_row.py`` im Backend.

    Das Skript liest die CSV eigenstaendig (D3: kein heizung-Package im
    Container). Diese Duplikation ist gewollt, darf aber nicht stillschweigend
    auseinanderlaufen — eine Umbenennung im Backend muss hier auffallen.
    """
    assert REQUIRED_COLUMNS == ("dev_eui", "app_key")
    assert OPTIONAL_COLUMNS == ("app_eui", "hardware_nummer")


def test_read_csv_normalises_and_defaults(tmp_path: Path) -> None:
    csv_path = write_csv(
        tmp_path / "p.csv",
        f"1,101,Bad,{EUI_A.upper()},{KEY_A.upper()},001,{JOIN_EUI.upper()}",
        f",,,{EUI_B},{KEY_B},,",
    )
    devices = read_csv(csv_path)
    assert len(devices) == 2
    assert devices[0].dev_eui == EUI_A
    assert devices[0].app_key == KEY_A
    assert devices[0].join_eui == JOIN_EUI
    assert devices[0].name == "001"
    # Ohne hardware_nummer faellt der Name auf die DevEUI zurueck, damit das
    # Geraet im ChirpStack-UI auffindbar bleibt. Ohne AppEUI: Acht-Byte-Null.
    assert devices[1].name == EUI_B
    assert devices[1].join_eui == "0000000000000000"


def test_read_csv_rejects_duplicate_dev_eui(tmp_path: Path) -> None:
    csv_path = write_csv(
        tmp_path / "dup.csv",
        f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}",
        f"1,102,Bad,{EUI_A},{KEY_B},002,{JOIN_EUI}",
    )
    with pytest.raises(ProvisionError, match="mehrfach"):
        read_csv(csv_path)


def test_read_csv_tolerates_headerless_column(tmp_path: Path) -> None:
    """Excel-Leerspalte wie im Pairing-Parser (C2) ignoriert."""
    path = tmp_path / "head.csv"
    path.write_text(
        HEADER + ",,\n" + f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI},,\n",
        encoding="utf-8",
    )
    devices = read_csv(path)
    assert len(devices) == 1
    assert devices[0].name == "001"


def test_read_csv_missing_required_column(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("dev_eui,hardware_nummer\n" + f"{EUI_A},001\n", encoding="utf-8")
    with pytest.raises(ProvisionError, match="app_key"):
        read_csv(path)


# ---------------------------------------------------------------------------
# Fall 1: neues Geraet
# ---------------------------------------------------------------------------


def test_new_device_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient()
    code = run(base_args(csv_path), client_factory=lambda: client)
    assert code == 0
    assert client.created == []
    assert client.created_keys == []
    out = capsys.readouterr().out
    assert "[WUERDE ANLEGEN]" in out
    assert "--apply" in out


def test_new_device_apply_creates_device_and_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient()
    code = run(base_args(csv_path, "--apply"), client_factory=lambda: client)
    assert code == 0
    assert client.created == [
        {
            "dev_eui": EUI_A,
            "name": "001",  # D5: Geraetename = hardware_nummer
            "application_id": APP_ID,
            "device_profile_id": PROFILE_ID,
            "join_eui": JOIN_EUI,
        }
    ]
    # LoRaWAN 1.0.x: AppKey gehoert in nwk_key.
    assert client.created_keys == [
        {"dev_eui": EUI_A, "key_field": DEFAULT_KEY_FIELD, "key_value": KEY_A}
    ]
    assert "[ANGELEGT]" in capsys.readouterr().out
    assert client.closed is True


# ---------------------------------------------------------------------------
# Fall 2: Geraet existiert bereits (Idempotenz)
# ---------------------------------------------------------------------------


def test_existing_device_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(
        devices={
            EUI_A: RemoteDevice(
                dev_eui=EUI_A,
                name="001",
                application_id=APP_ID,
                device_profile_id=PROFILE_ID,
                join_eui=JOIN_EUI,
            )
        }
    )
    code = run(base_args(csv_path, "--apply"), client_factory=lambda: client)
    assert code == 0
    assert client.created == []
    assert "[OK]" in capsys.readouterr().out


def test_second_apply_run_changes_nothing(tmp_path: Path) -> None:
    """Idempotenz: derselbe Lauf zweimal legt genau einmal an."""
    csv_path = write_csv(
        tmp_path / "p.csv",
        f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}",
        f"1,102,Bad,{EUI_B},{KEY_B},002,{JOIN_EUI}",
    )
    client = FakeClient()
    assert run(base_args(csv_path, "--apply"), client_factory=lambda: client) == 0
    assert len(client.created) == 2
    assert run(base_args(csv_path, "--apply"), client_factory=lambda: client) == 0
    assert len(client.created) == 2  # unveraendert
    assert len(client.created_keys) == 2


# ---------------------------------------------------------------------------
# Fall 3: Abweichung
# ---------------------------------------------------------------------------


def test_deviation_is_reported_not_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(
        devices={
            EUI_A: RemoteDevice(
                dev_eui=EUI_A,
                name="Vicki-ALT",
                application_id=APP_ID,
                device_profile_id="11111111-2222-3333-4444-555555555555",
                join_eui=JOIN_EUI,
            )
        }
    )
    code = run(base_args(csv_path, "--apply"), client_factory=lambda: client)
    assert code == 1  # Abweichung verlangt eine Entscheidung
    assert client.created == []
    out = capsys.readouterr().out
    assert "[ABWEICHUNG]" in out
    assert "Vicki-ALT" in out
    assert "device_profile_id" in out
    assert "nichts geaendert" in out


# ---------------------------------------------------------------------------
# Fall 4: falsche Application-ID
# ---------------------------------------------------------------------------


def test_expected_app_id_mismatch_aborts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A-16: die API baut ihre Downlink-Topics aus CHIRPSTACK_APP_ID.

    Weicht die Provisioning-ID ab, wuerden die Geraete angelegt, aber jeder
    Setpoint ginge auf ein Topic, das niemand abonniert.
    """
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient()
    code = run(
        base_args(csv_path, "--apply", "--expected-app-id", "deadbeef-0000-0000-0000-000000000000"),
        client_factory=lambda: client,
    )
    assert code == 1
    assert client.created == []
    assert "Application-ID weicht ab" in capsys.readouterr().err


def test_expected_app_id_match_passes(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient()
    code = run(
        base_args(csv_path, "--apply", "--expected-app-id", APP_ID),
        client_factory=lambda: client,
    )
    assert code == 0
    assert len(client.created) == 1


def test_unknown_application_aborts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(known_apps=())
    assert run(base_args(csv_path, "--apply"), client_factory=lambda: client) == 1
    assert "existiert nicht" in capsys.readouterr().err
    assert client.created == []


def test_unknown_device_profile_aborts(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(known_profiles=())
    assert run(base_args(csv_path, "--apply"), client_factory=lambda: client) == 1
    assert client.created == []


# ---------------------------------------------------------------------------
# Key-Feld-Spiegelung
# ---------------------------------------------------------------------------


def test_key_reference_confirms_nwk_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(keys={EUI_B: RemoteKeys(nwk_key_set=True, app_key_set=False)})
    code = run(
        base_args(csv_path, "--apply", "--key-reference-dev-eui", EUI_B),
        client_factory=lambda: client,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "nwk_key=gesetzt" in out
    assert "app_key=leer" in out
    assert "'nwk_key' bestaetigt" in out


def test_key_reference_mismatch_aborts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Referenz hat app_key belegt, gewaehlt ist nwk_key -> Abbruch.

    Genau der Fall, den die Spiegelung verhindern soll: 100 Geraete mit
    dem Schluessel im falschen Feld joinen nicht, und man sieht es erst
    beim Einschalten.
    """
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(keys={EUI_B: RemoteKeys(nwk_key_set=False, app_key_set=True)})
    code = run(
        base_args(csv_path, "--apply", "--key-reference-dev-eui", EUI_B),
        client_factory=lambda: client,
    )
    assert code == 1
    assert client.created == []
    assert "Feld-Spiegelung widerspricht" in capsys.readouterr().err


def test_key_reference_unknown_device_aborts(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(keys={})
    code = run(
        base_args(csv_path, "--apply", "--key-reference-dev-eui", EUI_B),
        client_factory=lambda: client,
    )
    assert code == 1
    assert client.created == []


def test_key_field_override_is_honoured(tmp_path: Path) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(keys={EUI_B: RemoteKeys(nwk_key_set=False, app_key_set=True)})
    code = run(
        base_args(csv_path, "--apply", "--key-field", "app_key", "--key-reference-dev-eui", EUI_B),
        client_factory=lambda: client,
    )
    assert code == 0
    assert client.created_keys[0]["key_field"] == "app_key"


def test_missing_reference_warns_but_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient()
    assert run(base_args(csv_path, "--apply"), client_factory=lambda: client) == 0
    assert "nicht gegen ein funktionierendes Geraet gespiegelt" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Schluesselwerte + Fehlerpfade
# ---------------------------------------------------------------------------


def test_key_value_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Weder Vorschau noch Schreiblauf duerfen einen Schluessel ausgeben."""
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")

    client = FakeClient()
    run(base_args(csv_path), client_factory=lambda: client)
    dry = capsys.readouterr()
    assert KEY_A not in dry.out + dry.err
    assert "32 Hex-Zeichen, nicht angezeigt" in dry.out

    client2 = FakeClient()
    run(base_args(csv_path, "--apply"), client_factory=lambda: client2)
    wet = capsys.readouterr()
    assert KEY_A not in wet.out + wet.err


def test_missing_api_key_aborts_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CHIRPSTACK_API_KEY", raising=False)
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient()
    assert run(base_args(csv_path, "--apply"), client_factory=lambda: client) == 1
    assert client.created == []
    assert "CHIRPSTACK_API_KEY" in capsys.readouterr().err


def test_create_failure_continues_and_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ein Fehler bei einem Geraet stoppt die uebrigen 103 nicht."""
    csv_path = write_csv(
        tmp_path / "p.csv",
        f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}",
        f"1,102,Bad,{EUI_B},{KEY_B},002,{JOIN_EUI}",
    )
    client = FakeClient(fail_create_for=EUI_A)
    code = run(base_args(csv_path, "--apply"), client_factory=lambda: client)
    assert code == 1
    assert [c["dev_eui"] for c in client.created] == [EUI_B]
    out = capsys.readouterr().out
    assert "[FEHLER]" in out
    assert "[ANGELEGT]" in out


def test_key_reference_with_both_fields_set_aborts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Beide Key-Felder belegt -> Abbruch, kein stilles nwk_key.

    Aus einer doppelten Belegung laesst sich nicht ablesen, welches Feld beim
    Join wirksam ist. Sich fuer nwk_key zu entscheiden waere geraten — und
    genau das soll die Spiegelung verhindern.
    """
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(keys={EUI_B: RemoteKeys(nwk_key_set=True, app_key_set=True)})
    code = run(
        base_args(csv_path, "--apply", "--key-reference-dev-eui", EUI_B),
        client_factory=lambda: client,
    )
    assert code == 1
    assert client.created == []
    err = capsys.readouterr().err
    assert "BEIDE Key-Felder belegt" in err
    assert "--key-field" in err


def test_key_field_override_wins_over_ambiguous_reference(tmp_path: Path) -> None:
    """Auch mit --key-field bleibt die doppelte Belegung ein Abbruch.

    Der Override sagt, WELCHES Feld geschrieben wird — er beantwortet nicht
    die Frage, warum beim Referenzgeraet beide gesetzt sind. Das ist ein
    Datenbefund, der geklaert gehoert.
    """
    csv_path = write_csv(tmp_path / "p.csv", f"1,101,Bad,{EUI_A},{KEY_A},001,{JOIN_EUI}")
    client = FakeClient(keys={EUI_B: RemoteKeys(nwk_key_set=True, app_key_set=True)})
    code = run(
        base_args(csv_path, "--apply", "--key-field", "nwk_key", "--key-reference-dev-eui", EUI_B),
        client_factory=lambda: client,
    )
    assert code == 1
    assert client.created == []
