# Der Stand der Fenstererkennung ist jetzt ablegbar (0x46)

**Stand:** 05.11.2026

## Der Anlass war eine Frage, die niemand beantworten konnte

Der Betreiber hat am 05.11. gemeldet: Zimmer 306, drei Geräte, ein Gast
der sichtbar oft lüftet — Einbrüche um 3–4 °C — und in 30 Tagen bei
13.179 Meldungen **0×** `open_window = true`.

Die Analyse hat die Einbrüche bestätigt (49 Stück ab 1,5 °C, davon 37 mit
öffnendem Ventil, also echtem Wärmeverlust). Sie hat auch die Frage
beantwortet, die darunter lag — und zwar mit einem Befund, der schlimmer
ist als ein Fehler:

**Ob die Fenstererkennung auf den Vickis überhaupt aktiv ist, war im
ganzen System nicht feststellbar.**

| Wo man es vermuten würde | Was dort steht |
|---|---|
| `control_command` | nur Sollwerte (`target_setpoint`, `reason`) |
| `business_audit` | keine passende Aktion unter 27 vorhandenen |
| `sensor_reading` | keine Zeile — `open_window_status_reply` steht in `REPLY_REPORT_TYPES` |
| api-Protokoll | eine grep-bare Zeile, **18 Stunden** Reichweite |

Die Rücklesung über `0x46` war gebaut, der Codec dekodierte sie, und das
Ergebnis ging in eine Protokollzeile. Das war 2026 in Sprint 9.11x.b eine
ausdrückliche S6-Entscheidung: *„Maintenance-Reports sind seltene Events
(~1x pro Bulk-Aktivierung), DB-Audit waere Overkill."*

## Warum die Begründung nicht gehalten hat

Die Häufigkeit war das falsche Maß. Entscheidend ist nicht, wie oft die
**Antwort** kommt, sondern wie oft die **Frage** gestellt wird — und sie
wird bei jeder Änderung an der Fenstererkennung erneut gestellt: vor dem
Einschalten, nach dem Einschalten, beim Abbruchkriterium, bei jedem
Gerätetausch.

Ein Speicher, der vor der nächsten Frage verfällt, verwandelt jede
Antwort in eine Vermutung. Das ist §5.68 im Konfigurationspfad: eine
operative Aussage ohne Befund. Und es ist teurer als es klingt, weil die
Vermutung hier eine **Funkhandlung** nach sich zieht — man muss senden,
um zu wissen.

## Was sich ändert

Drei nullable Spalten auf `sensor_reading` (Migration 0038), gefüllt vom
Subscriber aus der `0x46`-Antwort:

| Spalte | Herkunft |
|---|---|
| `ow_detection_enabled` | `bytes[1] == 0x01` |
| `ow_detection_duration_min` | `bytes[2] * 5` |
| `ow_detection_delta_c` | `bytes[3] / 10` |

Form und Begründung sind der Präzedenzfall `0x15` (Migration 0035,
Sprint 23 T1): eine Meldung des Geräts **mit Zeitpunkt**, keine
Stammdaten. Gelesen wird die jüngste Zeile, **die die Felder führt** —
ein Keepalive ohne Antwort trägt sie nicht und überschreibt nichts.

Die Protokollzeile bleibt zusätzlich bestehen. Sie sagt auch dann etwas,
wenn das Schreiben scheitert.

## Die Verwechslung, die diese Spalten verhindern sollen

`ow_detection_enabled` steht jetzt neben `open_window`, und die beiden
beantworten **verschiedene Fragen**:

* `open_window` — ist **jetzt** ein Fenster offen? (Zustand)
* `ow_detection_enabled` — ist die Erkennung **eingeschaltet**? (Konfiguration)

Ein Gerät mit ausgeschalteter Erkennung meldet `open_window = false`
**immer**, und zwar ohne je gemessen zu haben. Hausweit stehen 604.694
Zeilen `false` und **null** Zeilen `true`. Wer die Spalten verwechselt,
liest daraus „es wurde nie gelüftet" statt „die Erkennung war aus" — und
genau das war am 05.11. offen, mit 49 belegten Einbrüchen in einem
einzigen Zimmer als Gegenbeweis.

Die Warnung steht deshalb dreifach: im Modell, in der Migration und im
RUNBOOK neben der Abfrage. Eine Spalte, deren Name zur Verwechslung
einlädt, braucht den Hinweis dort, wo sie gelesen wird.

## Was dieser PR nicht tut

* **Er sendet nichts.** Kein `0x45`, kein `0x46`. Die Abfrage an die drei
  Geräte (85, 87, 24) ist freigegeben, aber ein eigener Schritt nach dem
  Deploy.
* **Er schaltet nichts scharf.** Die Fenstererkennung bleibt, wo sie ist.
* **Er zeigt nichts in der Oberfläche.** Der Leser ist bis auf Weiteres
  die Abfrage im RUNBOOK und das Werkzeug `fenstererkennung status`. Eine
  Anzeige auf der Geräteseite — wie sie `0x15` hat — gehört in den
  Schritt-2-PR, zusammen mit dem, was dort ohnehin an der
  Fenstererkennung geändert wird.
* **Er behebt die 0x15-Schwester nicht:** der angehängte Keepalive geht
  in einer Befehlsantwort verloren, weil `REPLY_REPORT_TYPES` den
  regulären Reading-Insert überspringt. Das ist Bestandsverhalten und
  gehört zusammen mit der `0x15`-Seite angesehen, nicht einseitig.

## Ein Fund beim Testen, der die nächste Datei betrifft

Der zweite schreibende Test in derselben Datei fiel mit „die
0x46-Antwort hat keine Zeile erzeugt" — **ohne Fehlermeldung**. Ursache:
`RuntimeError: Event loop is closed`. Der Handler schreibt über den
globalen Pool, `pytest-asyncio` gibt jedem Test einen eigenen
Event-Loop, und asyncpg-Verbindungen hängen am Loop ihrer Entstehung
(§5.14). Der defensive `except Exception` des Schreibpfads hat den
Fehler verschluckt, und die Protokollzeile war unsichtbar, weil die
`heizung.*`-Logger im Testlauf nicht propagieren (§5.37).

**Warum das im Präzedenzfall nicht aufgefallen ist:**
`test_geraetegrenzen_ende_zu_ende` hat 16 Tests, aber nur **einer**
erreicht den DB-Schreibpfad — die übrigen steigen vorher aus. Die Falle
braucht **zwei** schreibende Tests in einer Datei, und diese Datei ist
die erste, die das tut.

Behoben testseitig, mit einer autouse-Fixture, die den globalen Pool vor
jedem Test leert. **Backlog:** das gehört als Helfer in
`tests/conftest.py`, damit die nächste Datei es nicht neu lernt — hier
bewusst lokal gelassen, weil ein gemeinsamer Helfer alle DB-Tests
berührt und nicht in diesen PR gehört (§5.1).

## Prüfung

* Volle Backend-Suite gegen echtes Postgres: **1841 passed, 45 skipped,
  1 xfailed** (§5.50 — nicht als Skip gelaufen).
* `ruff check`, `ruff format --check`, `mypy src`: grün.
* `infra/chirpstack` Codec-Tests: 6 passed, darunter der neue
  Durchlauf-Test für `0x46` mit angehängtem Keepalive.
* **Die Testeingabe ist Ausgabe des echten Codecs**, nicht ein Literal
  aus dem Kopf: `node` über `mclimate-vicki.js` mit den Bytes
  `46 01 02 0F | 81 12 9B 7C D9 D9 11 F0 30`. Das ist die Lehre aus
  `0x15`, wo `15` statt `15.0` im Test stand und die Anlage die Antwort
  trotz grünem Test verwarf.
* **Mutationsproben**, drei, alle beißen: `_als_ganze_zahl` gegen ein
  `isinstance(..., int)`-Gate → zwei Tests fallen; Delta-Spannenprüfung
  entfernt → einer fällt; `ow_detection_enabled=True` hart verdrahtet →
  einer fällt.

**Nicht geprüft:** ob ein echtes Gerät antwortet. Das kann dieser PR
nicht zeigen — es ist in diesem Haus noch nie eine `0x46`-Antwort
eingegangen, und die Bytes im Test sind deshalb konstruiert. Der Beweis
ist die Abfrage an 85, 87 und 24 nach dem Deploy.
