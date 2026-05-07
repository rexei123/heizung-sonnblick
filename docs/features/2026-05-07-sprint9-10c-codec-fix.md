# Sprint 9.10c — Vicki-Codec-Decoder-Fix (Cmd-Byte-Routing)

**Datum:** 2026-05-07
**Branch:** `fix/sprint9.10c-vicki-codec-decoder`
**PR:** TBD
**Tag:** offen — Vorschlag `v0.1.9-rc4-codec-fix` (Strategie-Chat entscheidet).

## Anlass
Cowork-QA von Sprint 9.10 hat aufgedeckt: Auf heizung-test persistierte `sensor_reading` seit dem Sprint-9.0-Codec-Refactor nur `fcnt/rssi/snr`. Alle aus dem Codec-`object` gelesenen Felder (`temperature/setpoint/valve_position/battery_percent/open_window`) waren NULL für alle vier Vickis. Engine-Layer 1 hatte keine Ist-Temperatur, Layer 4 sah keinen open_window-Trigger. Sprint 9.11 (Live-Test #2) wäre damit blockiert.

S1+S5 greifen — Hotfix vor 9.11, kein Backlog-Eintrag, eigener Sub-Sprint.

## Phase-0-Befund (H4: Codec-Routing-Bug)
Live-Capture per `mosquitto_sub` auf heizung-test (2026-05-07T10:00:04Z, dev_eui `70b3d52dd3034de4`, fCnt 895):
```json
{ "fPort": 2, "data": "gRKdYZmZEeAw",
  "object": { "command": 129.0, "report_type": "unknown_reply" } }
```
- `bytes[0] = 0x81` = Periodic Status Report v2 (laut Codec-Spec).
- Aber: Codec routete `fPort === 2 -> decodeCommandReply`, der nur `cmd=0x52` versteht. Periodic-bytes wurden als `unknown_reply` abgewürgt.
- ChirpStack-Codec-DB-Eintrag = Repo-Codec (nicht Drift). Subscriber-Mapping (snake_case + `openWindow` camelCase) korrekt.

**Hypothese H4:** Sprint 9.0 nahm `fPort=2` als Setpoint-Reply-Marker an. Live-Verhalten der Vickis: Periodic-Reports kommen ebenfalls auf `fPort=2`. Annahme war falsch. Robust ist Cmd-Byte-Routing über `bytes[0]` — Payload-immanent statt Transport-Schicht-abhängig.

## Tasks

| Task | Beschreibung | Status |
|---|---|---|
| T1a | Codec `decodeUplink` auf Cmd-Byte-Routing (`0x52 -> Reply`, sonst Periodic). 4 neue Tests (Periodic v2 fPort 2, Periodic v1 fPort 1, Reply fPort 2, Reply ohne fPort), Test 12 angepasst. 19/19 grün. | erledigt |
| T1b | Subscriber-Kommentar (`mqtt_subscriber.py`): „fPort 2 = Reply" → `report_type == 'setpoint_reply'`. §5.20-Anwendung. Funktional unverändert. | erledigt |
| T1c | ChirpStack-UI-Re-Paste auf heizung-test: Codec-Tab im Device-Profile „Heizung" durch 9.10c-Stand ersetzt (manueller Schritt, dokumentiert in RUNBOOK §10). | erledigt |
| T1d | Backend-Pytest `test_map_to_reading_live_codec_output_fport2_periodic` mit vollem Live-Codec-Output. 141 passed, 62 skipped. | erledigt |
| T2 | Live-Smoke heizung-test: Subscriber-Logs Vorher/Nachher, Postgres-Readings, Engine-Trace. | erledigt |
| T3 | STATUS, CLAUDE.md §1 + §5.21/§5.22, dieser Brief, RUNBOOK §10, Backlog-Update. | erledigt |

## Verifikation auf heizung-test (T2)

Subscriber-Log-Übergang (vor/nach UI-Re-Paste):
```
10:55:57 e53 fcnt=870  temp=None  setpoint=None        ← vor T1c
11:00:18 de4 fcnt=901  temp=22.71 setpoint=18.0        ← nach T1c
11:00:28 de5 fcnt=874  temp=20.24 setpoint=21.0
11:01:32 d7b fcnt=873  temp=20.41 setpoint=21.0
11:05:59 e53 fcnt=871  temp=19.88 setpoint=21.0
```

Postgres `sensor_reading` (jüngste 4 Readings): alle Felder befüllt, `open_window=false`, Battery 33–42 %.

Engine-Trace Room 1 (11:05:53Z): Layer 4 `window_safety` → `detail=no_open_window` (= frische Readings, alle `open_window=false`, no-op). Beweis dass Layer 4 jetzt mit echten Daten arbeitet.

## Verwandte Lessons / ADRs

- **CLAUDE.md §5.21** (neu) — Hardware-Annahmen defensiv: Cmd-Byte > fPort beim Codec-Routing. Anlass: dieser Sprint.
- **CLAUDE.md §5.22** (neu) — ChirpStack-Codec-Deploy ist nicht automatisch. Repo-Update ≠ Live-Stand. Manueller UI-Re-Paste oder Bootstrap-Skript Pflicht.
- **CLAUDE.md §5.20** — aspirative Code-Kommentare als Doku-Drift; angewandt auf den Subscriber-Kommentar in T1b.
- **AE-40 / §0 (S1+S5)** — scharfe Mängel im Datenpfad sofort fixen, nicht in Backlog verschieben.

## Backlog (B-9.10c-1..2)

- **B-9.10c-1:** Codec-Bootstrap-Skript via ChirpStack gRPC. Repo-Stand → ChirpStack reproduzierbar deployen, statt UI-Klickerei je Server. Eigener Hygiene-Sprint.
- **B-9.10c-2:** Codec auf `heizung-main` re-paste, sobald Production-Migration ansteht (heizung-main hat aktuell den 9.0-Stand mit dem gleichen Bug). Aktuell unkritisch, weil heizung-main noch ohne Live-Vickis.

## Nicht in Scope

- Engine-Trace-Konsistenz für Layer 0/2/Hysterese (B-9.10-7, eigener Mini-Sprint).
- Bootstrap-Skript selbst (B-9.10c-1, eigener Sprint).
- Codec-Erweiterungen jenseits der Routing-Korrektur.
- snake_case-Alias-Migration im Codec.
