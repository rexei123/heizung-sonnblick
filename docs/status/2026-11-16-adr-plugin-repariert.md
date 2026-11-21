---
datum: 2026-11-16
thema: Das ADR-Plugin als ES-Modul — und ein Test in der echten Engine
pr: offen
---

# Das Plugin lädt, und diesmal ist es gemessen

**Keine Migration. Keine Server-Änderung in diesem PR.** Der
`adr_plugins`-Eintrag steht wieder in `chirpstack.toml`, wirkt aber erst
mit dem Deploy — und das Zuweisen des Profils ist ein eigener Handgriff
(Phase 3 des großen Durchgangs).

## Was falsch war

Die Datei hatte Funktionen auf oberster Ebene, ohne `export`. ChirpStack
4.17 deklariert sie als **ES-Modul** (`rquickjs::Module::declare`) und
holt die drei Funktionen am Modul-Objekt (`m.get("id")`). Ohne `export`
ist das `undefined`, und der Dienst bricht beim Start ab.

Der Docstring der Datei behauptete das Gegenteil — *„ChirpStack führt die
Datei als Skript aus, keine export-Anweisungen"* — und der Test lud sie
per `eval`, also genau so. Die beiden Anforderungen schließen sich aus,
und der Test hat die falsche festgenagelt. **54 grüne Tests, sieben
Minuten Ausfall.**

## Was jetzt geprüft wird, in zwei Stufen

### Stufe 1 — der Vertrag, bei jedem Lauf, ~1 Sekunde

Die Datei wird unter Node als **ES-Modul importiert** und die drei
benannten Exporte werden einzeln geprüft, bevor gerufen wird. Das ist
derselbe Vertrag, den `m.get("id")` prüft.

### Stufe 2 — die echte Engine, im echten Image, ~17 Sekunden

`chirpstack/chirpstack:4` — **die Fassung aus der Produktions-Compose**,
nicht eine hier genannte — läuft gegen eine Wegwerf-Datenbank und lädt
unsere echte `chirpstack.toml`. Zwei Zusicherungen:

1. Das Protokoll nennt `Setting up ADR plugin`, **und der Dienst läuft
   danach weiter**. Letzteres ist der eigentliche Nachweis: ein
   Plugin-Fehler beendet ChirpStack mit Exit-Code 1. Der Unterschied
   zwischen „lädt" und „lädt nicht" steht nicht in einer Textzeile, er
   steht im Zustand des Dienstes.
2. **Die Fassung vom 15.11. ohne `export` bricht ab**, mit genau der
   damaligen Meldung, Exit-Code 1. Ohne diese zweite Zusicherung wäre
   Stufe 2 ein Test, der nicht zeigen kann, dass er etwas prüft — und
   das war am 15.11. der Fall, nur umgekehrt.

Das Image wird **aus `docker-compose.prod.yml` gelesen**, nicht hier
genannt. Eine zweite Nennung wäre eine zweite Wahrheit (§5.53): der Test
würde irgendwann eine andere Fassung prüfen als der Server fährt, und das
wäre genau die Lücke, die am 15.11. offen war. Seit #424 steht dort auch
der Digest — der Test prüft damit nachweislich dasselbe Image.

## Drei Dinge, die beim Bauen gemessen wurden

**ChirpStack braucht die Datenbank, bevor es Plugins lädt.** Der frühere
Vorschlag war, den Container ohne Postgres laufen zu lassen und nur das
Protokoll zu lesen. Das geht nicht: die Reihenfolge ist
`Setting up PostgreSQL connection pool` → `Applying schema migrations` →
`Setting up regions` → `Setting up adr algorithms` → `Setting up ADR
plugin`. Ohne Datenbank kommt der Lauf nie bis zum Plugin. Der Test
bringt deshalb Postgres und Redis selbst mit, auf einem eigenen Netz,
**ohne einen Port zu veröffentlichen** — er kommt niemandem in die Quere,
der auf diesem Rechner sonst lauscht, und muss nichts fremdes beenden.

**Der Behälter läuft als Nicht-Root.** `mkdir /etc/chirpstack` scheitert
mit `Permission denied`; die Konfiguration liegt deshalb unter
`/tmp/cfg`, und der Plugin-Pfad wird mitgebogen. Der Test **sichert den
Treffer zu** (`assert n_pfad == 1`): ohne diese Zusicherung würde ein
umbenanntes Verzeichnis dazu führen, dass gar kein Plugin geladen wird —
und der Lauf sähe grün aus.

**Die Konfiguration wird hineinkopiert, nicht eingebunden.** Ein
Bind-Mount verhält sich hier auf Windows anders als auf Linux, und ein
Test, der je Betriebssystem etwas anderes prüft, ist genau das Problem,
gegen das dieser Test gebaut ist.

## Mutationsproben

Fünf, alle rot:

| Probe | was rot wird |
|---|---|
| `export` entfernt (die Fassung vom 15.11.) | **8 Tests**, darunter der Engine-Test und die Selbstprobe |
| `adr_plugins`-Eintrag entfernt | Verdrahtung **und** Engine-Test |
| Zieldatenrate zurück auf DR3 | die DR1-Zusicherung |
| Plugin-Verzeichnis im Pfad umbenannt | beide Engine-Tests |
| `txPowerIndex` durchgereicht statt festgenagelt | die Leistungs-Zusicherung |

Die erste und die vierte sind die wichtigen: sie belegen, dass der
Engine-Test zubeißt und nicht nur mitläuft.

## Was der Test kostet

Der CI-Lauf `chirpstack-lint-and-test` dauerte rund 15 Sekunden. Die zwei
Engine-Tests brauchen lokal **17 Sekunden** bei vorhandenen Images; in CI
kommen die Pulls von `chirpstack/chirpstack:4`, `postgres:16-alpine` und
`redis:7-alpine` dazu, grob **eine Minute**.

Das ist bewusst **nicht** hinter einer Marke versteckt: `-m slow` gibt es
zum Abwählen beim Entwickeln, nicht zum Fernhalten aus der CI. Ein Test,
der sich im Zweifel selbst überspringt, hätte den Ausfall vom 15.11. auch
nicht verhindert (§5.81).

## Wofür das Plugin da ist — mit der Zahl von heute

108 wurde am **16.11.** vom Standard-Algorithmus auf **DR5** hochgezogen.
Vier `LinkADRReq acknowledged` im Protokoll, bei `installation_margin =
20` und `tx_power_index = 0`:

```
15.11. 08:27:25Z   dr=5  nb_trans=2  tx_power_index=0
15.11. 08:37:27Z   dr=5  nb_trans=1
16.11. 06:37:16Z   dr=5  nb_trans=2
16.11. 06:47:15Z   dr=5  nb_trans=1
```

Die Reserve hat gewirkt — nur auf der Leistungsachse. Die Datenrate kann
sie nicht zurückholen: der Standard-Algorithmus **senkt sie nie**. Das
ist der ganze Grund für dieses Plugin, und es ist jetzt keine Vermutung
mehr, sondern steht im Protokoll.

**Querverweise:** RUNBOOK §10av (Laufliste, Warnkasten erneuert), §10bb
(die Notreparatur), §5.55 (54 grüne Tests in der falschen Umgebung),
§5.53 (eine Wahrheit), §5.81 (ein Test, der sich still überspringt),
§5.68 (Anspruch gegen Befund),
`docs/status/2026-11-15-adr-plugin-format-befund.md` (der Befund am
Quelltext, jetzt gemessen),
`docs/status/2026-11-16-grosser-durchgang.md` (Phase 3).
