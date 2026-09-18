# ChirpStack — Konfiguration und Hilfsskripte

## Inhalt

| Pfad | Zweck |
|---|---|
| `configuration/` | ChirpStack-Server-Konfiguration (gerendert vom `chirpstack-init`-Sidecar) |
| `codecs/` | Vicki-Payload-Codec. **Kommt nicht automatisch nach ChirpStack** — manueller Re-Paste, RUNBOOK §10c |
| `postgres-init/` | Extensions für die ChirpStack-Datenbank |
| `test-uplinks/` | Beispiel-Uplinks für Pipeline-Tests |
| `provision_devices.py` | Geräte-Provisioning aus der Pairing-CSV (Sprint 17) |
| `requirements-provision.txt` | Gepinnte Abhängigkeiten **nur** für dieses Skript |
| `tests/` | Tests zum Provisioning-Skript, laufen ohne gRPC |

## provision_devices.py

Legt die OTAA-Geräte in ChirpStack v4 an, die der Pairing-Lauf später in der
heizung-DB erwartet. Ohne diesen Schritt joint kein Vicki, ohne Join kein
Uplink, ohne Uplink scheitert der Eingangstest an Schritt 1.

Vollständiger Ablauf mit Befehlen: **RUNBOOK §10h**. Die Begründung der
Architektur steht im Modul-Docstring des Skripts, die Entscheidung in AE-69.

### Warum eigenständig

`chirpstack-api` ist bewusst **keine** Abhängigkeit des API-Images (D3):

- Der Downlink-Pfad der Anwendung läuft über MQTT, nicht gRPC (AE-48,
  CLAUDE.md §5.28). Ein gRPC-Client im API-Image wäre eine zweite
  Steuerleitung zur Hardware.
- Provisioning ist ein einmaliger Vorgang vor der Montage, kein Betriebspfad.

Deshalb läuft das Skript als Einmal-Container im Compose-Netz, nicht im
`api`-Container.

### Was es nicht tut

Tenant, Application, Device-Profile und Codec legt es **nicht** an — die
existieren bereits und werden im ChirpStack-UI gepflegt. Das Skript prüft
nur, dass Application und Device-Profile da sind, und bricht sonst ab.

Ein programmatischer Codec-Deploy (`UpdateDeviceProfile` mit
`payload_codec_script`) bleibt B-9.10c-1. Die gRPC-Anbindung dafür liegt mit
diesem Skript jetzt vor.

### Sicherheitsregeln im Skript

- Der API-Key kommt **nur** aus `CHIRPSTACK_API_KEY`, nie als Argument —
  sonst stünde er in der Shell-History und in `docker inspect`.
- AppKeys erscheinen **nie** in der Ausgabe, auch nicht gekürzt. Die Vorschau
  zeigt `<32 Hex-Zeichen, nicht angezeigt>`.
- Default ist Dry-Run. Geschrieben wird nur mit `--apply`.
- Bestehende Geräte werden nie überschrieben, Abweichungen nur gemeldet.

### Tests

```bash
cd infra/chirpstack
pip install "ruff>=0.3" "mypy>=1.9" "pytest>=8.0"
ruff check . && ruff format --check . && mypy provision_devices.py && pytest -q
```

Die Tests brauchen weder `chirpstack-api` noch einen laufenden ChirpStack —
sie setzen einen Doppelgänger des gRPC-Clients ein. Das beweist nebenbei,
dass der `chirpstack_api`-Import wirklich lazy ist. CI:
`.github/workflows/chirpstack-tools-ci.yml`.
