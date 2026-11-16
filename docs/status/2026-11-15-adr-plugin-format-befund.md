---
datum: 2026-11-15
thema: Warum ChirpStack 4.17 unser ADR-Plugin nicht laden konnte — Befund am Quelltext
pr: —
---

# Der Test verlangte das Gegenteil von dem, was ChirpStack verlangt

## Die Frage

Beim Rollout am 15.11.2026 brach ChirpStack beim Start ab:

```
Setting up ADR plugin file_path=/etc/chirpstack/adr-plugins/relais-feste-datenrate.js
Error: Get id function: JS error: Error converting from js 'undefined' into type 'function'
```

Sieben Minuten Ausfall. 54 Tests waren grün. Die Frage ist nicht „welcher
Tippfehler", sondern **in welcher Form ChirpStack die Funktionen erwartet**
— und warum die Tests eine andere Form geprüft haben.

## Die Belegstelle

`chirpstack/src/adr/plugin.rs` im Hauptzweig von ChirpStack. Drei Dinge
stehen dort:

**1. Die Engine ist `rquickjs`** — die Rust-Bindung an QuickJS. Kein
Node, kein Deno. `rquickjs::Runtime` und `rquickjs::Context::full`.

**2. Die Datei wird als ES-Modul deklariert und ausgewertet:**

```rust
let m = rquickjs::Module::declare(ctx.clone(), "script", script.clone())
let (m, m_promise) = m.eval()
```

**3. `id`, `name` und `handle` werden am Modul-Objekt geholt**, nicht im
globalen Namensraum:

```rust
let id_func: rquickjs::Function = m.get("id")
let name_func: rquickjs::Function = m.get("name")
```

Erwartet werden damit **benannte ES-Modul-Exporte**:

```javascript
export function id() { ... }
export function name() { ... }
export function handle(req) { ... }
```

`m.get("id")` liefert `undefined`, wenn die Datei keinen solchen Export
hat — und `undefined` in eine `rquickjs::Function` zu wandeln ergibt genau
die Meldung, die im Log stand: **„Get id function: JS error: Error
converting from js 'undefined' into type 'function'"**. Die Fehlermeldung
ist also nicht unklar; sie ist präzise, wenn man weiß, wo sie entsteht.

## Was unsere Datei tut, und was der Test verlangt hat

`infra/chirpstack/configuration/adr-plugins/relais-feste-datenrate.js`
hat **Funktionen auf oberster Ebene, ohne `export`**:

```javascript
function name() { ... }
function id() { ... }
function handle(req) { ... }
```

Und der Test lädt sie so:

```python
"const fs=require('fs');"
f"eval(fs.readFileSync({str(plugin)!r},'utf8'));"
f"process.stdout.write(JSON.stringify({funktion}({argument})));"
```

Mit dem Docstring: *„``eval`` statt ``require``: genau so lädt ChirpStack
die Datei, und ein ``export`` darin würde hier scheitern — wie dort."*

**Dieser Satz ist genau verkehrt.** `eval` in Node verlangt Funktionen
**ohne** `export` (ein `export` ist dort ein Syntaxfehler). ChirpStack
verlangt sie **mit**. Die beiden Anforderungen schließen sich aus, und der
Test hat die falsche von beiden festgenagelt — in einem Docstring, der die
Behauptung als geprüft darstellt.

**Das ist §5.68 in seiner teuersten Form:** eine Aussage über das
Verhalten eines fremden Systems, ohne Beleg hingeschrieben, in einen Test
gegossen, und damit nicht nur falsch, sondern *bewacht*. Die 54 grünen
Läufe haben nicht versagt — sie haben zuverlässig das Gegenteil
sichergestellt.

## Vorschlag für den Test, ohne den kein zweiter Rollout

**Zwei Stufen, und beide braucht es.**

### Stufe 1 — der Vertrag, in CI

Node kann ES-Module laden. Ein Test, der die Datei per `import()` lädt und
die **benannten Exporte** liest, prüft denselben Vertrag, den
`m.get("id")` prüft:

```python
skript = (
    f"const m = await import({plugin.as_uri()!r});"
    "if (typeof m.id !== 'function') throw new Error('id fehlt als Export');"
    "if (typeof m.name !== 'function') throw new Error('name fehlt als Export');"
    "if (typeof m.handle !== 'function') throw new Error('handle fehlt als Export');"
    f"process.stdout.write(JSON.stringify(m.{funktion}({argument})));"
)
subprocess.run([node, "--input-type=module", "-e", skript], ...)
```

Die Datei bekommt dafür `export` vor die drei Funktionen. Die
**Dateiendung bleibt `.js`** — ChirpStack interessiert sie nicht, es liest
den Inhalt; für Node braucht es `--input-type=module` und ein `file://`-URI
im `import()`.

Das ist ein kleiner Schritt und deckt den Fehler vom 15.11. vollständig
ab. Was es **nicht** deckt: Unterschiede zwischen QuickJS und V8 im
Sprachumfang. QuickJS ist ES2023-vollständig, unsere Datei benutzt
Arithmetik, `Math.min/max` und Objektliterale — dort ist kein Risiko. Aber
„kein Risiko, soweit ich sehe" ist keine Messung, und deshalb:

### Stufe 2 — der Lauf in der echten Engine, einmal, vor dem Rollout

**Lokal, nicht auf dem Server.** Das Entwicklungs-Compose im Repo bringt
einen ChirpStack-Container mit. Der Ablauf:

1. Plugin-Datei und `adr_plugins`-Eintrag in die **lokale** Konfiguration.
2. `docker compose up chirpstack` (ohne `-d`, damit man das Log sieht).
3. Im Log muss **`Setting up ADR plugin`** stehen und **kein** `Error`.
4. Danach in der lokalen Oberfläche: Device profile → ADR algorithm → der
   Eintrag muss in der Auswahl stehen.

Schritt 4 ist der eigentliche Beweis. Das ist derselbe Nachweis wie in
§10av Schritt 3 — nur in einer Umgebung, in der ein Fehlschlag nichts
kostet.

**Warum nicht in CI:** ein ChirpStack-Container in der CI-Pipeline
bräuchte Postgres und Mosquitto dazu, also den halben Stack, für einen
Test, der bei jedem PR läuft und einmal im Jahr etwas findet. Stufe 1
deckt die Klasse ab, die uns getroffen hat; Stufe 2 ist ein Handgriff vor
dem Rollout und gehört als Schritt **0** in §10av.

## Was das für die Lesson bedeutet

Die drei Funde dieses Wochenendes — der Aufräum-Test mit einem „laufenden"
Tag, der mein eigener Fehler war; die Relais-Zone ohne Fühler; und dieser
hier — haben dieselbe Form: **ein Testaufbau, der eine andere Lage prüft
als die, die vorkommt.** Bei den ersten beiden war die Lage im Haus
anders als im Test. Hier war die **Umgebung** anders: Node gegen QuickJS,
Skript gegen Modul.

Die Frage, die alle drei gefunden hätte, ist in §5.55 schon notiert und
bekommt mit diesem Fall eine zweite Hälfte:

> Gibt es diese Lage im Haus — und **läuft der Test dort, wo der Code
> laufen muss?**

**Quelle:** [chirpstack/src/adr/plugin.rs](https://raw.githubusercontent.com/chirpstack/chirpstack/master/chirpstack/src/adr/plugin.rs)
(abgerufen 15.11.2026).
