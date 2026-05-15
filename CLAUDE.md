# Claude-Kontext Heizungssteuerung Hotel Sonnblick

Dieses File wird automatisch geladen. Lies es **vor jeder Aktion** im Repo.

## 0. Stabilitätsregeln (oberste Priorität)

Dieses System steuert Heizungen im produktiven Hotelbetrieb.
Instabilität ist nicht akzeptabel. Stabilität schlägt Sprint-
Tempo, Feature-Vollständigkeit, Eleganz und Backlog-Sauberkeit.

### Operative Regeln

- **S1 — Keine Verschiebung scharfer Mängel:** Bekannte Race-
  Conditions, Doku-Drifts oder TODO-Kommentare in der Steuer-
  logik werden gefixt, sobald sie scharf werden — auch wenn
  das einen laufenden Sprint unterbricht. Kein "Hotfix danach"
  wenn der Mangel mit dem aktuellen Sprint produktiv aktiv
  wird.

- **S2 — Determinismus und Idempotenz:** Jede Steuer-
  entscheidung muss deterministisch sein. Mehrfach getriggerte
  Code-Pfade müssen identisch reagieren. Locks, SETNX,
  Idempotenz-Checks sind Pflicht, nicht Optimierung.

- **S3 — Auditierbarkeit:** Jede Setpoint-Änderung wird im
  Engine-Trace geloggt, mit Layer, Reason, Detail, Zeitstempel.
  Keine schnellen Pfade am Trace vorbei. Auch Hotfixes loggen.

- **S4 — Hardware-Schutz:** Keine doppelten Downlinks. Keine
  widersprüchlichen Setpoints in der ChirpStack-Queue. Keine
  Befehle ohne Bestätigungs-Strategie. Battery-Cost und
  Motor-Aktivität sind real.

- **S5 — Defensive bei externen Quellen:** PMS, IoT-Devices,
  Netzwerk dürfen keine Falschzustände erzeugen. Letzter
  bekannter guter Stand mit Zeitstempel schlägt jede Annahme.

- **S6 — Komplexität trägt Beweislast:** Wer ein Feature, eine
  Konfiguration oder einen Spezialpfad einbauen will, muss
  begründen, warum die einfachere Variante nicht reicht. Im
  Zweifel: einfacher.

### Eskalations-Regel

Wenn ein Sprint-Plan, Brief, Pull-Request oder Live-Deploy
gegen S1-S6 verstoßen würde: Strategie-Chat-Stop. Keine Merge-
Entscheidung ohne explizite Freigabe. Auch wenn der Sprint
dadurch länger dauert.

### Was diese Regeln NICHT sind

- Kein Vorwand, Sprints unkontrolliert auszudehnen — die Regeln
  greifen bei konkreten Stabilitätsrisiken, nicht bei "könnte
  man theoretisch schöner machen".
- Kein Schutz vor Bugs in neuem Code — neue Bugs werden gefixt
  wie immer. Die Regeln greifen bei strukturellen Risiken in
  der Steuerlogik.
- Kein Argument gegen YAGNI — S6 ist explizit pro Einfachheit.
  Stabilität bedeutet "wenig, robust", nicht "viel,
  abgesichert".

Querverweise:
- ADR AE-41 (Stabilitätsregeln + Autonomie-Default)
- §0.1 Autonomie-Default für Claude Code
- §5.20 Aspirative Code-Kommentare als Doku-Drift-Risiko
  (konkreter Fall, der zu S1 geführt hat)

## 0.1 Autonomie-Default für Claude Code

Claude Code arbeitet Sprint-Briefe autonom ab und stoppt nur
bei substantiellen Entscheidungen. Stop-Points werden nicht
inflationär gesetzt — der Hotelier prüft an wenigen, klaren
Punkten, nicht bei jedem Code-Edit.

### Pflicht-Stops (immer)

Claude Code stoppt und wartet auf Freigabe bei:

1. Abweichung vom Sprint-Brief (Pfad, Signatur, Migration-
   Nummer, Datenmodell-Erweiterung außerhalb des Plans)
2. Phase-0-Quellcheck-Befund mit Auswirkung auf andere Tasks
3. Race-Condition, Doku-Drift, TODO-Kommentar in Steuerlogik
   entdeckt (S1-Verstoß-Kandidat)
4. Test-Failure, der nicht durch das aktuelle Task entstanden
   ist
5. Mypy/Ruff/ESLint-Errors in fremden Dateien
6. Vor Pull-Request-Erstellung
7. Vor Tag-Vergabe
8. Vor Live-Deploy auf heizung-test oder heizung-main
9. S1-S6-Verstoß-Verdacht (siehe §0)

### Auto-Continue (autonom)

- Code-Edits, die dem Brief 1:1 entsprechen
- Test-Erstellung gemäß Brief
- ruff/mypy/pytest/eslint/next build-Runs
- Doku-Updates gemäß Brief
- Routine-Bash-Commands (git status/diff/add, ls, cd, find,
  grep)
- Datei-Reads

### Berichts-Format

- **Auto-Continue:** Eine Zeile pro Task am Ende ("T1 done,
  alle Checks grün, Diff in Branch")
- **Pflicht-Stop:** Voller Bericht mit Diff, Befund, Optionen,
  Empfehlung
- **Sprint-Ende:** Sammelbericht mit allen Diffs, Test-Outputs,
  PR-Vorschlag, Tag-Vorschlag

### Eskalation bei Unsicherheit

Wenn unklar ist, ob ein Befund unter Pflicht-Stop fällt:
**immer stoppen.** Falsch-Positiv ist günstiger als
Falsch-Negativ. Stabilität schlägt Geschwindigkeit (S1+S2).

### Sprint-spezifische Stufen

Der Default ist Stufe 2. Der Sprint-Brief kann eine andere
Stufe explizit setzen:

- **Stufe 1** (volle Stop-Points): Engine-Logik mit
  Concurrency, neue Architektur-Schichten, Hardware-
  Befehlspfade
- **Stufe 2** (Default): Standard-Sprints
- **Stufe 3** (volle Autonomie): reine Markdown-Doku,
  Dependency-Bumps, Lint-Fixes ohne Logik-Änderung

Begründung der Stufe steht im Sprint-Brief, nicht im
Strategie-Chat.

## §0.2 — Source-of-Truth-Hierarchie nach Strategie-Refresh 2026-05-15

Bei Konflikt zwischen Dokumenten gilt diese Reihenfolge (oben schlägt
unten):

1. `docs/STRATEGIE-REFRESH-2026-05-15.md` (neuestes Strategie-Update,
   Phasen-Logik)
2. `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` (Architektur-Master; §7
   Sprint-Plan-Adaption ist durch 1. überholt)
3. `docs/SPRINT-PLAN.md`
4. `STATUS.md` (für laufenden Stand)
5. `CLAUDE.md` (für Stabilitätsregeln + Lessons)
6. `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
7. `docs/STRATEGIE.md`
8. `docs/RUNBOOK.md`
9. `docs/WORKFLOW.md`
10. `Design-Strategie-2_0_1.docx`

Alles in `docs/features/` mit Datum vor 2026-05-07 ist historisch —
gilt nicht mehr für Pläne, gilt für Lessons.

**Trigger-Phrase pro Session** (siehe `docs/SESSION-START.md`):

> „Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."

Vor jeder Code-Änderung: Pflicht-Pre-Read aus SESSION-START.md →
Claude-Code-Rolle abarbeiten.

## 1. Identität & Stand

- **Projekt:** Heizungssteuerung für Hotel Sonnblick (Mandatar: hotelsonnblick@gmail.com)
- **Repo:** https://github.com/rexei123/heizung-sonnblick (public)
- **Lokales Working Copy:** `C:\Users\User\dev\heizung-sonnblick`
- **Aktueller Sprint:** **Sprint 9.10c abgeschlossen** (Vicki-Codec-Decoder-Fix: Cmd-Byte-Routing statt fPort-Routing). Sprint 9.11 Live-Test #2 in Vorbereitung.
- **Letzter Tag:** `v0.1.9-rc3-window-detection` (Sprint 9.10). Sprint 9.10c-Tag-Frage offen (Strategie-Chat).
- **Produktivumgebungen:** `https://heizung.hoteltec.at` (Main), `https://heizung-test.hoteltec.at` (Test)

## 2. Pflicht-Lektüre vor Sprint-Arbeit

In dieser Reihenfolge:

0. CLAUDE.md §0 + §0.1 — Stabilitätsregeln und Autonomie-Default. Nicht überspringbar.
1. `CONTEXT.md` — Boot-Anker, aktueller Stand, nächster Schritt
2. `STATUS.md` — Gesamtstand, alle Sprints, aktuelle URLs, Tags
3. `docs/SPEC-FRAMEWORK.md` — verbindliche Code- und Doku-Regeln
4. `docs/WORKFLOW.md` — 5-Phasen-Feature-Flow mit User-Gates
5. `docs/RUNBOOK.md` — Operations, Rescue, UFW, GHCR-PAT, Domain
6. `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log

## 3. Goldene Regeln

1. **5-Phasen-Workflow:** Brief → Sprintplan → User-Gate → Execution → Tag. Keine Schritte überspringen.
2. **Branch-Naming:** `feat/sprintN-<slug>` für Features, `chore/<slug>` für Wartung, `fix/<slug>` für Bugs.
3. **Tag-Pattern:** `v0.<minor>.<sprint>-<slug>` (z. B. `v0.1.5-lorawan-foundation`).
4. **Commit-Trailer:** `Co-Authored-By: Claude` nur wenn explizit gewünscht. Bei Claude-Code-Commits: `Co-Authored-By: Claude` immer dranhängen.
5. **Doku-Pflicht:** Jeder Sprint hat einen Feature-Brief in `docs/features/YYYY-MM-DD-sprintN-<slug>.md`. STATUS.md wird am Ende jedes Sprints ergänzt.
6. **Sprache:** Deutsch, Sie-Form, sachlich, maximal kurz, hohe Inhaltsdichte, keine Floskeln.
7. **Befehl-Markierung:** Jeden Befehl explizit als **PowerShell (lokal)**, **SSH (Server)** oder **Claude Code (im Repo)** kennzeichnen.
8. **Kritisches Denken:** Bei besseren Alternativen widersprechen. Nicht Ja-Sager sein.
9. **Kein Schreiben in main/develop direkt:** Branch-Protection ist aktiv, immer über PR.
10. **Claude-Code-Workflow:** Datei-Edits, Code-Änderungen und Tests laufen in Claude Code. Lokale git-Operationen (status, diff, add, commit) ebenfalls erlaubt in Claude Code. Branch-Wechsel und git push immer in PowerShell. Bei jedem schreibenden Schritt: Diff reviewen, dann freigeben. Cowork-Mount-Quirks aus §5.2 sind historisch, gelten nicht mehr.

## 3.11 — gh pr create IMMER mit --base develop

GitHub-Default für `gh pr create` ist `main`. Ohne explizites
`--base` landet jeder Feature-PR auf `main` statt `develop`.
Konsequenz: PR überspringt Test-Server-Gate, `build-images.yml`
triggert `:main`-Build, Branch-Modell `feature → develop → main`
ist gebrochen.

Pflicht: jeder `gh pr create`-Aufruf bekommt `--base develop`
explizit. Ausnahme nur bei Sync-PR `develop → main` (dort
`--base main` bewusst).

Bei Zweifel vor Push:

```bash
gh repo view --json defaultBranchRef -q .defaultBranchRef.name
```

Anlass: PR #116 (Sprint 9.11x) wurde irrtümlich auf `main` gemerged.
Frankenstein-`main` blieb durch `safe.directory`-Block auf
heizung-main ohne Live-Schaden, kostete aber 25 Min Aufräum-Zeit
(PR #117 Revert offen, PR #118 saubere v2 auf develop).

## 4. Operations-Highlights

- **SSH-Key:** `$HOME\.ssh\id_ed25519_heizung` (zwingend `-i ...`-Flag, Default-Key passt nicht)
- **Server-Hostnames:** `heizung-test`, `heizung-main` (Tailscale MagicDNS)
- **Container-Stack:** api, web, db (timescaledb), redis, caddy, mosquitto, chirpstack, chirpstack-postgres, chirpstack-gateway-bridge, celery_worker, celery_beat (plus Init-Sidecars `chirpstack-init`, `chirpstack-gateway-bridge-init`) — Compose-File: `infra/deploy/docker-compose.prod.yml` (zwingend `-f`)
- **Deploy:** GHCR Pull über systemd-Timer (5 Min), KEIN Push-Deploy
- **DNS:** Hetzner Online (konsoleH), NS `ns1.your-server.de`/`ns.second-ns.com`/`ns3.second-ns.de` — NICHT Hetzner Cloud DNS
- **UFW:** aktiv auf beiden Servern, Port 22/80/443 + tailscale0 erlaubt
- **PAT-Type:** Classic PAT (Fine-grained unterstützt GHCR nicht)

## 5. Lessons Learned (Pflicht-Lektuere, NICHT ueberspringen)

Diese Punkte sind harte Lehren aus echten Fehlern. Bei jedem Verstoss wiederholen sich Stunden-lange Hotfix-Spiralen.

### 5.1 Iteration vs. Reflexion

- EIN Thema -> EIN PR -> Merge -> Verifikation -> naechstes Thema. Niemals 2 Themen in einen PR. Niemals Folge-PR starten bevor der vorherige sauber durch ist.
- Wenn ein Befehl scheitert: STOP, NACHDENKEN, DIAGNOSE. Nicht reaktiv den naechsten Befehl geben. Wurzel-Ursache klaeren, dann gezielt einen Schritt.
- "Quick Fix" gibt es nicht. Jedes Item, das im Wartemodus zwischendrin "schnell mit reingenommen" wird, frisst 1+ Stunden.
- Im Pairing-/Wartemodus KEINE Architektur-Aenderungen. Nur fertige, getestete, klar abgegrenzte Items.

### 5.2 Cowork-Mount-Sandbox-Quirks (HISTORISCH — gilt nicht mehr seit Umstieg auf Claude Code)

Diese Lesson stammt aus der Cowork-Phase. Seit Umstieg auf Claude Code (Sprint 9.8c) nicht mehr relevant. Aufbewahrt als Wissensspeicher.

Der Cowork-Mount unter `/sessions/.../mnt/heizung-sonnblick/` ist NICHT 1:1 mit dem Windows-Repo synchron. Goldene Regel 10 (alte CLAUDE.md) ist eine Luege.

Tatsaechliches Verhalten:

- `Edit`/`Write`-Tool aus Sandbox kommt MEISTENS bei Windows an, aber NICHT immer. Neu erstellte Dateien werden mehrfach verschluckt. Bestehende Files werden meistens synced, aber manchmal mit eingestreuten Null-Bytes (binary diff statt text diff).
- Sandbox-`git`-Operationen (commit, branch) landen NICHT im Windows-Repo. Sandbox hat eigenen git-Layer.
- `.git/refs/heads/<subdir>/` im Cowork-Mount-FS hat Bugs: leere Sub-Directories werden als "existiert" gemeldet aber Schreiben schlaegt fehl. Branch-Naming `chore/<slug>` funktioniert nicht; Workaround: flacher Name wie `chore-<slug>`.
- `.git/config` und `.git/refs/heads/<branch>` haben oft Null-Byte-Pollution. Symptom: `fatal: bad config line` oder `bad signature 0x00000000`.

Konsequenz fuer Workflow:
1. Alle Datei-Edits via Sandbox `Edit`/`Write`.
2. SOFORT in PowerShell `git diff --stat <file>` verifizieren BEVOR weitere Schritte.
3. Wenn Diff `Bin <X> -> <Y> bytes` zeigt: Null-Byte-Cleanup noetig (PowerShell `Get-Content -Raw` + `-replace ` + `[System.IO.File]::WriteAllText` mit `UTF8Encoding $false`).
4. Branch + Commit + Push macht IMMER PowerShell, nie Sandbox-git.

### 5.3 PowerShell + Bash-Skripte: Encoding-Toedlich

- PS5 `Set-Content -Encoding UTF8` schreibt UTF-8 MIT BOM. Bash-Skripte mit BOM brechen mit `/bin/bash: not found`. PS7 waere OK, aber Standard-Win10/11 hat oft noch PS5.
- PS5 + Edit-Tool double-encoding erzeugt Mojibake.
- Sichere Pfade:
  - Bash-Skripte ASCII-only (keine Umlaute, keine em-dashes, keine Ellipsen)
  - Wenn Sonderzeichen noetig: `[System.IO.File]::WriteAllText((Resolve-Path X).Path, $content, (New-Object System.Text.UTF8Encoding $false))` statt Set-Content
  - Single-quote here-string `@'...'@` statt `@"..."@`, damit PowerShell keine `$VAR` expandiert (wichtig fuer Bash-Skripte mit `$VAR`)

### 5.4 CI + Image-Tagging muss man kennen BEVOR man Pinning-Logik baut

`build-images.yml` taggt mit dem GitHub-push-event-SHA (= Merge-Commit auf der Ziel-Branch). Eine Logik in `deploy-pull.sh`, die `IMAGE_TAG` aus `git log -- backend/...` ableitet, findet aber den Source-Branch-Commit. Bei `gh pr merge --merge` sind das verschiedene SHAs -> Tag-Mismatch -> Pull schlaegt fehl.

Konsequenz: SHA-Pinning (H-6) ist KEIN Quick-Fix. Erfordert sowohl `build-images.yml`-Anpassung (zusaetzlich Source-SHA taggen) als auch `deploy-pull`-Logik. Eigener Sprint, nicht im Pairing-Wartemodus.

### 5.5 PR-Workflow-Reihenfolge

Bei main-PR + Sync nach develop:
1. PR auf main pushen
2. CI durch (`gh pr checks <N> --watch`)
3. Merge (`gh pr merge <N> --merge --delete-branch --admin`)
4. Erst dann lokal `git checkout develop && git pull`
5. Sync-Branch erstellen, mergen, pushen
6. PR auf develop, CI, merge

Wenn Sync-PR vor dem main-Merge erstellt wird: `No commits between` Fehler.

### 5.6 Befehl-Trennung PowerShell vs. SSH

Jeder Code-Block muss EINDEUTIG als PowerShell (lokal) oder SSH (Server) markiert sein. Ein User-Versehen (PowerShell-Befehle im SSH-Terminal) kostet Zeit + erzeugt Folge-Fehler (z.B. `git config user.email` wird auf dem Server gesetzt, `gh: command not found`).

Empfehlung im Chat: jeden Code-Block mit explizitem Header oeffnen, z.B.:
- `**PowerShell (Windows lokal):**`
- `**SSH (heizung-test, root):**`

### 5.7 deploy-pull.sh schweigt bei git-ownership-Fehler (Sprint 8 Lesson)

Der Pull-Timer (`heizung-deploy-pull`) ruft intern `git fetch origin/develop` auf dem Server-Repo auf. Wenn der `/opt/heizung-sonnblick`-Ordner eine UID/GID hat, die nicht zu root passt (z.B. nach OS-Update oder beim Re-Install), wirft Git seit 2.35:

```
fatal: detected dubious ownership in repository at '/opt/heizung-sonnblick'
```

Symptom: Pull-Timer-Logs zeigen 22h+ FEHLER, Server-Code haengt auf altem Stand, Frontend zeigt veraltete UI ohne sichtbaren Hinweis.

**Diagnose:** `journalctl -u heizung-deploy-pull -n 50 --no-pager`

**Fix einmalig pro Server:**
```bash
git config --system --add safe.directory /opt/heizung-sonnblick
```

**Wichtig: `--system`, nicht `--global`.** Der `--global`-Eintrag in `/root/.gitconfig` wird vom `heizung-deploy-pull.service` trotz `User=root` und `HOME=/root` nicht gelesen (vermutlich systemd-Sandbox). `--system` schreibt nach `/etc/gitconfig` und wird zuverlässig gelesen.

Diese Korrektur basiert auf Diagnose vom 2026-05-05 (Sprint 9.8d). Vorherige Empfehlung `--global` war falsch.

**Sprint-Backlog:** `deploy-pull.sh` sollte beim ersten Run diesen Fix selbst setzen (`git config --system --add safe.directory ...`), damit neue Server out-of-the-box klappen. Bis dahin: Server-Setup-Dokumentation muss diesen Schritt explizit nennen.

### 5.8 Frontend AppShell nicht doppelt wrappen (Sprint 8.13a Lesson)

`frontend/src/app/layout.tsx` wrapped alle Pages bereits in `<AppShell>`. Wenn eine neue Page-Komponente nochmal `<AppShell>` aussen rum macht, wird die Sidebar zweimal nebeneinander gerendert (kein Build-/Lint-Fehler, nur kosmetisch im Browser).

**Korrekte Vorlage:** `frontend/src/app/devices/page.tsx` (Sprint 7) — gibt direkt `<div>...</div>` zurueck, kein AppShell-Wrapper.

**Falsch (Sprint 8.9-8.12 initial):** `<AppShell><div>...</div></AppShell>` als Page-Return.

### 5.9 Cowork-Mount verschluckt Konfig-Files unbemerkt (Sprint 8.15 Lesson)

Der Mount-Sync laut §5.2 ist nicht nur bei NEUEN Files unzuverlaessig — auch MODIFY-Edits an Konfig-Dateien koennen verschluckt werden, OHNE dass der Edit-Schritt fehlschlaegt. Sprint-8.15-Beispiel: `frontend/tailwind.config.ts` wurde via Sandbox `Edit` aktualisiert, Sandbox sagte "OK", aber der File ist NICHT im PowerShell-Repo angekommen. Der `git add frontend/src` hat ihn dann nicht erfasst, der PR ging ohne neue Tailwind-Tokens raus, der Build generierte keine `bg-add`/`text-error`/`border-error`-CSS-Klassen — sichtbar wurde es erst im Browser an weissen Buttons.

**Pflicht-Check nach Sandbox-Edits an Konfig-Dateien (`tailwind.config.ts`, `next.config.mjs`, `tsconfig.json`, `pyproject.toml`, `alembic.ini`, `*.toml`, `*.yml`, `Dockerfile`):**

```powershell
# PowerShell (lokal) — VOR jedem `git add`
git diff --stat frontend\tailwind.config.ts <weitere konfig-files>
```

Wenn `0 files changed` obwohl ein Edit gemacht wurde: Datei direkt in PowerShell ueberschreiben (`[System.IO.File]::WriteAllText`).

### 5.10 build-images.yml triggert nach `gh pr merge` nicht zuverlaessig (Sprint 8.15 Lesson)

`build-images.yml` ist konfiguriert mit `on: push: branches: [develop, main]` plus `paths: frontend/**`. Trotzdem hat es bei PR #63 (Sprint 8.15) NICHT auf den merge-Push reagiert — im GHCR blieb das alte `:develop`-Image. Vermutlich Race-Condition mit `concurrency.cancel-in-progress: true` oder `paths`-Matching-Edge-Case.

**Pflicht nach jedem PR-Merge mit Frontend- oder Backend-Aenderungen:**

```powershell
# PowerShell (lokal) — direkt nach `gh pr merge`
gh workflow run build-images.yml --ref develop  # oder --ref main
Start-Sleep -Seconds 5
$runId = (gh run list --workflow=build-images.yml --limit 1 --json databaseId --jq '.[0].databaseId').Trim()
gh run watch $runId --exit-status
```

### 5.11 `docker compose pull web` ist nicht beweisend (Sprint 8.15 Lesson)

Wenn das `:develop`-Tag im GHCR stale ist (siehe §5.10), zieht `docker compose pull` zwar ein Image, aber das ist das alte. Output `✔ Image ... Pulled` sagt NICHTS ueber Aktualitaet. Der Pull-Timer am Server schweigt dann ohne Hinweis stundenlang.

**Pflicht-Check nach `docker compose pull`:**

```bash
# SSH (Server, root)
docker images ghcr.io/rexei123/heizung-web --format '{{.Tag}} {{.CreatedAt}} {{.ID}}' | head -3
```

CreatedAt muss nach dem letzten erwarteten Build liegen, ID muss sich vom vorherigen Stand unterscheiden. Sonst: §5.10-Workflow erneut anstossen.

### 5.12 PowerShell `$ErrorActionPreference = "Stop"` greift NICHT fuer native Tools (Sprint 9 Lesson)

Der PS-Switch fasst nur PowerShell-Cmdlets, NICHT externe `git.exe`/`gh.exe`/`docker.exe` mit non-zero exit. Beobachtet bei Sprint 9.0 + 9.0a: `gh pr merge` returnte exit 1 (BEHIND), Block lief stur weiter bis zum gruenen Write-Host am Ende — User glaubte alles gut, in Wahrheit war kein PR gemerged.

**Pflicht in jedem PowerShell-Block mit `gh`/`git`-Sequenz:**

```powershell
function Test-Exit($msg) { if ($LASTEXITCODE -ne 0) { throw $msg } }
gh pr merge $pr --merge --admin; Test-Exit "merge"
git push -u origin $branch; Test-Exit "push"
```

Alternativ ab PS 7.3: `$PSNativeCommandUseErrorActionPreference = $true`.

### 5.13 ChirpStack v4 verlangt `devEui` im Downlink-Payload (Sprint 9.6a Lesson)

Das Topic-Pattern `application/<APPID>/device/<DEVEUI>/command/down` reicht NICHT. Im JSON-Payload muss zusaetzlich `devEui` (lowercase) drin sein, sonst:

```
WARN chirpstack::integration::mqtt: Processing command error:
  Payload dev_eui  does not match topic dev_eui 70b3d52dd3034de4
```

Der Downlink wird stillschweigend verworfen. **Korrektes Format:**

```json
{
  "devEui": "70b3d52dd3034de4",
  "data": "<base64>",
  "fPort": 1,
  "confirmed": false
}
```

Test-Befehl fuer Diagnose:

```bash
docker logs deploy-chirpstack-1 --since 30s 2>&1 | grep -iE "command|enqueu"
```

`Command received` + `Device queue-item enqueued` = OK. Nur `Processing command error` = Payload-Fehler.

### 5.14 Celery-Worker braucht Engine-Reset pro Forked-Process (Sprint 9.6b Lesson)

asyncpg-Connections sind an einen Event-Loop gebunden. Celery `prefork` startet n Worker-Forks, die den DB-Pool des Master-Process erben. `asyncio.run()` in einer Task baut einen NEUEN Loop auf — alte Pool-Connections crashen mit:

```
RuntimeError: Task got Future <Future pending cb=[BaseProtocol._on_waiter_completed()]>
              attached to a different loop
```

**Fix:** `@worker_process_init.connect` in `celery_app.py` ruft `asyncio.run(engine.dispose())` + `create_async_engine` neu, ersetzt `db_module.engine` und `db_module.SessionLocal`. So bekommt jeder Fork einen eigenen frischen Pool.

Zusaetzlich: `pool_pre_ping=False` in `db.py`, sonst pingt der Pool im falschen Loop.

### 5.15 `event_log` wird beim manuellen Cleanup NICHT mit-cleared (Sprint 9.10 Lesson)

Engine-Decision-Panel zeigt Stale-Trace, wenn nur `control_command` geleert wird:

```sql
DELETE FROM control_command WHERE device_id = X;
-- event_log bleibt unangetastet -> Frontend zeigt alte Layer-Eintraege
```

**Bei Re-Trigger nach Bug-Fix beide Tabellen clearen:**

```sql
DELETE FROM control_command WHERE device_id = X;
DELETE FROM event_log WHERE room_id = Y;
```

UI macht jetzt einen Stale-Hinweis (orange Banner) wenn die juengste Evaluation > 1h zurueck ist — Frueh-Warnung statt Daten-Verwirrung.

### 5.16 Next.js typed-Object-`href` resolved zu Query-String, nicht Path-Param (Sprint 9.6b Lesson)

```tsx
// ❌ FALSCH — produziert /zimmer/[id]?id=1
<Link href={{ pathname: "/zimmer/[id]", query: { id: r.id } } as never}>

// ✅ RICHTIG — produziert /zimmer/1
<Link href={`/zimmer/${r.id}` as never}>
```

Der Object-Form-Cast `as never` umgeht die Typed-Routes-Auflosung von Next.js — das `[id]` bleibt literal in der URL. Template-Literal mit `${id}` ist die einzige zuverlassige Variante.

### 5.17 `docker logs --since Xs` ist nach Container-Restart leer (Sprint 9.6 Lesson)

Beim Re-Deploy via `docker compose up -d --force-recreate` wird der Container neu gestartet. Der vorherige `--since 60s`-Filter sieht das neue Container-Log mit Time-Offset und liefert evtl. NICHTS, obwohl Tasks gerade liefen.

**Pflicht nach Re-Deploy:** mindestens `--tail 30` ohne `--since` verwenden, dann zusaetzlich auf den Worker-Boot-Log (`worker@... ready`) als Marker achten.

### 5.18 Test-Fixtures muessen Schema-Constraints respektieren (Sprint 9.10 Lesson)

`room.number` ist `VARCHAR(20)`, `device.dev_eui` ist `VARCHAR(16)`. Im Sprint 9.10 hat ein zu langer Layer-4-Fixture-Suffix `t9-10-l4-{HHMMSSffffff}` (21 Zeichen) alle 7 DB-Tests auf einen Schlag gekippt — Pure-Function-Tests waren grün, Live-DB-Tests crashten mit `StringDataRightTruncationError`.

**Robuste Suffix-Strategie fuer Test-Fixtures in diesem Repo:**

```python
import uuid
suffix = uuid.uuid4().hex[:8]  # 8 Hex-Zeichen, deterministisch
rt = RoomType(name=f"l4-rt-{suffix}")          # 14 Zeichen, passt in VARCHAR(20)
room = Room(number=f"l4-{suffix}")              # 11 Zeichen
device = Device(dev_eui=f"deadbeef{suffix}")    # 16 Zeichen exakt -> VARCHAR(16) voll
```

8 Hex-Zeichen reichen fuer Test-Eindeutigkeit innerhalb einer Session (Rollback am Ende). Nie `datetime.strftime("%H%M%S%f")` ohne Laengen-Rechnung verwenden.

### 5.19 Live-DB-Verify zwischen DB-erzeugenden und DB-konsumierenden Tasks (Sprint 9.10 Lesson)

T1 (Sprint 9.10) hat `0009_sensor_reading_open_window` geschrieben, T2 hat den darauf bauenden Engine-Code geschrieben. Pre-Push-Routine (`mypy`, `ruff`, lokale `pytest`) war zwischen T1 und T2 grün — die Layer-4-DB-Tests wurden ohne `TEST_DATABASE_URL` skipped, der `String(20)`-Bug fiel nicht auf.

**Pflicht-Zwischenschritt nach Migration + DB-modifizierendem Code, BEVOR Folge-Task startet:**

```powershell
# PowerShell (lokal)
Set-Location "C:\Users\User\dev\heizung-sonnblick"
docker compose up -d db  # TimescaleDB hochfahren

# Bash (im Repo, backend-Verzeichnis)
export DATABASE_URL="postgresql+asyncpg://heizung:heizung_dev@localhost:5432/heizung"
export TEST_DATABASE_URL=$DATABASE_URL
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m pytest tests/test_<neuer_layer>.py -v
```

Die DB-Tests muessen **gegen echtes Postgres** laufen, nicht nur skipped sein. CI deckt das spaeter ab — aber spaet, wenn der Folge-Task schon falsche Annahmen verbaut hat. Aufwand <2 Min, spart 15-30 Min Ruecksetz-Arbeit.

### 5.20 Aspirative Code-Kommentare als Doku-Drift-Risiko (Sprint 9.10 Lesson)

`celery_app.py:60-61` versprach seit Sprint 9.6 einen Redis-SETNX-Lock fuer Engine-Tasks, der nie geliefert wurde. Drei Folgesprints (9.7-9.9) haben Funktionalitaet darauf gestapelt, ohne dass der Lock real war. Erst Sprint 9.10 hat den Befund (`Grep -path src/heizung/tasks "SETNX|lock|acquire"` → leer) und die Race-Condition aktiv.

**Regel:** TODO/FIXME/„kommt in Sprint X"-Kommentare in produktiver Steuer- oder Sicherheitslogik sind kein neutraler Sprint-Plan, sondern aktive Doku-Drift. Pflicht-Stop-Trigger im Brief-Workflow: solche Kommentare im Quellcheck markieren und entweder a) im aktuellen Sprint mit-fixen oder b) explizit in den Backlog mit Ticket-ID.

### 5.21 Hardware-Annahmen defensiv interpretieren — Cmd-Byte > fPort beim Codec-Routing (Sprint 9.10c Lesson)

Sprint 9.0 hatte `fPort=2` als Marker fuer Setpoint-Replies angenommen und den Vicki-Codec entsprechend hartcodiert (`if fPort === 2 -> decodeCommandReply`). Live-Daten am 2026-05-07 zeigten: alle vier Vickis senden ihre Periodic Status Reports auf `fPort=2` (mit `bytes[0]=0x81`). Folge: Codec wuergte Periodics als `unknown_reply` ab, Subscriber persistierte `temperature/setpoint/valve/battery` als NULL — der Engine-Layer-Stack lief vier Tage lang ohne Ist-Daten.

**Regel:** Codec-Routing ueber das Payload-Byte `bytes[0]` ist robuster als ueber Transport-Felder wie fPort. `bytes[0]` ist Payload-immanent und unabhaengig vom Gateway/Netzwerk-Verhalten. fPort darf zur Diagnose mit-geloggt werden, aber NICHT als Routing-Schluessel dienen, solange der Vendor das Mapping nicht garantiert.

**Querverweise:** AE-40-Schwester-Pattern (Lock im Datenpfad statt Sprint-Plan), §5.22 (ChirpStack-Codec-Deploy ist nicht automatisch).

### 5.22 ChirpStack-Codec-Deploy ist NICHT automatisch (Sprint 9.10c Lesson)

Repo-Codec-Update bedeutet **nicht** ChirpStack-Live-Stand. Der Codec im Repo (`infra/chirpstack/codecs/mclimate-vicki.js`) ist Source of Truth — aber ChirpStack zieht ihn nicht selbst, er muss in der ChirpStack-UI je Server (heizung-test, spaeter heizung-main) im Device-Profile-Codec-Tab manuell eingefuegt werden.

Anlass: Sprint 9.10c Phase 0 — der Repo-Codec war seit Sprint 9.0 mit dem fPort-Routing-Bug angelegt; ChirpStack hatte denselben Stand; der Bug fiel erst in der Cowork-Live-QA von Sprint 9.10 auf. Hat zwei Sprints lang Verifikations-Arbeit gekostet, weil das Symptom (Sensor-Felder NULL) wie ein Subscriber-Problem aussah.

**Konsequenz:** Jeder Codec-Touch im Repo erfordert anschliessend
1. manuellen UI-Re-Paste auf jedem ChirpStack-Server, plus
2. Verifikation per **Events-Tab eines aktiven Vickis** — der `object`-Block muss die geaenderten/neuen Felder zeigen.

**Backlog (eigener Hygiene-Sprint):** Programmatisches Bootstrap-Skript via ChirpStack gRPC API, das `device_profile.payload_codec_script` aus dem Repo deployed. Bis dahin ist der manuelle Schritt im RUNBOOK §10c dokumentiert.

### 5.23 Engine-Trace-Konsistenz: alle Layer schreiben immer LayerStep (Sprint 9.10d Lesson)

Jeder Engine-Layer schreibt einen LayerStep — auch im No-Effect-Fall. Variante-B-Konvention: `setpoint_in == setpoint_out` (Pass-Through), `reason = prev_reason` durchgereicht, `detail = snake_case-Token` mit dem Grund warum die Schicht nichts getan hat. Begründung: S3 (Auditierbarkeit). Wenn Layer im inaktiven Pfad keinen Trace-Eintrag schreiben, ist das Engine-Decision-Panel als QA-Tool für genau diese Schicht blind — der Hotelier sieht nicht "Layer 0 hat geprüft und nichts getan", sondern gar nichts. Der Code-Review kann nicht unterscheiden zwischen "Layer war inaktiv" und "Layer wurde gar nicht ausgeführt".

Anlass: Sprint 9.10d Phase 0 — Layer 0 (Sommer) und Layer 2 (Temporal) gaben im inaktiven Fall `None` zurück und tauchten gar nicht im `event_log` auf. Layer 1/3/4/5 waren bereits always-on (Layer 3 explizit aus Sprint 9.9 T3, Layer 4 aus 9.10 T2). Die Inkonsistenz war historisch gewachsen, wurde aber erst beim Variante-B-Frontend-Refactor sichtbar.

**Sonderfall Layer 0 (Sommer):** Erste Schicht der Pipeline, hat keinen Vorgänger. Die Pass-Through-Konvention "setpoint_in == setpoint_out" greift hier nicht — es gibt keinen `setpoint_in`. Lösung: Schema-Erweiterung `LayerStep.setpoint_c: int | None`, wobei `None` ausschliesslich für Layer 0 inactive zugelassen ist und "Layer hat keinen eigenen Setpoint-Beitrag" bedeutet. Alle anderen Layer garantieren weiterhin einen Integer-Wert. Der Helper `_require_setpoint(step) -> int` (engine.py) engt den Typ an Call-Sites ein und raised AssertionError mit Layer-Name, falls die Invariante doch verletzt wird.

**Hysterese ist KEIN Layer.** `hysteresis_decision` produziert kein `LayerStep`, sondern wird in `engine_tasks.py` in jedes Layer-`details`-JSONB eingebettet. Frontend zeigt sie genau einmal pro Evaluation an (Footer unter dem LayerTrace), nicht pro Layer.

**Konsequenz für neue Layer:** Wer in Sprint 11+ einen `guest_override`-Layer oder vergleichbares anflanscht, schreibt von Anfang an always-on mit Pass-Through-LayerStep, snake_case-detail-Token im no-effect-Fall, und `setpoint_c: int` (nicht None — das ist und bleibt Layer 0 vorbehalten).

**Querverweise:** §5.18 Sprint 9.10 Lessons (Schema-Constraints), AE-40 (Engine-Lock), §5.20 (aspirative Code-Kommentare als Doku-Drift). detail-Konvention selbst ist heute heterogen (Layer 4 vorbildlich snake_case, Layer 1/2/3/5 f-string-Freitext) — Backlog B-9.10d-1 für die Vereinheitlichung vor `v0.1.9-engine`.

### 5.24 `ruff check` und `ruff format --check` sind verschiedene Gates (Sprint 9.10d Lesson)

Lokal `ruff check .` allein reicht nicht für CI. Der CI-Job ruft sowohl `ruff check` (Lint) als auch `ruff format --check` (Formatierungs-Drift) auf — beide müssen grün sein, sonst rot.

Symptom: lokal alles grün, CI rot mit Diff-Block in der Action-Log.

**Pflicht vor jedem Push, der Python-Code ändert:**

```powershell
cd backend
ruff check .
ruff format --check .
```

Falls `ruff format --check` rot: `ruff format .` läuft, dann diff reviewen, mit aufnehmen in den Commit. Kein Force-Push, kein Bypass.

Anlass: Sprint 9.10d PR #103 erster Push war wegen `ruff format --check` rot, weil lokal nur `ruff check` lief. Folge-Commit `ea0d53a` reformatierte eine `scalars()`-Kette in `test_engine_trace_consistency.py`. Hat einen zweiten CI-Round-Trip gekostet.

Backlog B-9.10d-6: Pre-Push-Hook oder pyproject-Config erzwingt beides automatisch — Hygiene-Sprint vor `v0.1.9-engine`.

### 5.25 `gh pr checks --watch` zeigt manchmal stale concurrency-cancel'd Runs (Sprint 9.10d Lesson)

Wenn ein Push während eines laufenden CI-Jobs erfolgt, cancelt GitHub-Actions per `concurrency.cancel-in-progress` den älteren Run. `gh pr checks --watch` rendert in dem Moment manchmal noch den canceled "pass in 3s"-Status, obwohl der finale Run für den neuen HEAD parallel läuft.

Symptom: `gh pr merge` failt mit `Required status check "e2e" is in progress`, obwohl `gh pr checks --watch` ein paar Sekunden vorher "all green" gemeldet hat.

**Fix:** zweiter `gh pr checks $prNum --watch` direkt nach Merge-Block. Wartet bis der echte Run für den aktuellen HEAD-Commit grün ist. Dann Merge erneut versuchen.

**Robust-Variante** für PR-Workflows in Skripten:

```powershell
# Vor jedem Merge: Run-ID des LETZTEN Pushes verifizieren
$headSha = gh pr view $prNum --json headRefOid -q .headRefOid
gh run list --commit $headSha --json status,name,conclusion
# Erst mergen, wenn alle conclusion="success" UND status="completed"
```

Anlass: Sprint 9.10d Merge — `gh pr checks --watch` zeigte "pass in 3s" für den e2e-Job, der erste `gh pr merge`-Versuch failte trotzdem mit `Required status check "e2e" is in progress`. Ein zweiter Watch-Durchlauf zeigte den echten Run mit ~1m46s Dauer; danach lief der Merge sauber.

### 5.26 — Strategie und Implementierung sauber trennen
(Architektur-Refresh 2026-05-07 Lesson)

Beim Refresh am 2026-05-07 zeigte sich: das Strategiepapier hatte vieles
korrekt vorgesehen, aber zwischen Strategie und Implementierung war ein
größerer Rückstand entstanden, als der Diff zwischen Strategie und
Referenzsystem (Betterspace).

**Lesson:** Bei jedem zweiten oder dritten Sprint kurz prüfen, ob die
implementierte Realität noch zur Strategie passt. Drift in einer
Richtung (Code holt Strategie ein, oder Strategie holt Realität ein) ist
normal — Drift in beide Richtungen gleichzeitig ist Refresh-Anlass.

**Konkret:**
- STATUS.md §1 alle 5 Sprints aktualisieren (nicht nur §2 anhängen)
- Strategie-Refresh nach Cowork-Inventarisierung oder externer Bestätigung
- Sprint-Plan und Backlog mindestens monatlich konsolidieren

### 5.27 Vicki-Hardware-Realität: Open-Window-Default + Algorithmus-Trägheit (Sprint 9.11 Lesson)

**Befund 2026-05-09 (Sprint 9.11 Live-Test #2 + Hersteller-Doku-Recherche):**

Die MClimate-Vicki sendet `openWindow=true` im Hotelbetrieb NICHT zuverlässig.
Drei Ursachen, alle real:

1. **Open-Window-Detection ist im Default DISABLED.** MClimate liefert die
   Funktion ab Werk ausgeschaltet. Aktivierung nur via Downlink (`0x4501020F`
   für FW >= 4.2, `0x06{...}` für FW < 4.2).
2. **Algorithmus arbeitet auf internem Vicki-Sensor**, der durch HK-Wärme
   dominiert wird. Hersteller-Zitat: „not 100% reliable, can be affected by
   outdoor temperature, position of the device on the radiator, position of
   the radiator in the room and more factors."
3. **Im Sommer / bei Außentemp >= 15 °C physikalisch nicht testbar.**
   Δ-T zu klein und zu langsam für Vicki-Schwellen.

**Konsequenzen für Code-Änderungen:**

- **Engine Layer 4 darf nicht NUR auf `sensor_reading.open_window` hören.**
  Hardware-First mit aktiven Triggern: Vicki-Flag UND `attached_backplate`.
  Backend-Inferenz nur passiv (siehe AE-47).
- **Window-Detection-Tests im Sommer:** Backend-Synthetic-Test in pytest
  (SQL-Inserts mit künstlichem Δ-T). Hardware-Test nur via Kältepack
  (RUNBOOK §10e), nicht in CI.
- **Vicki-Konfiguration vor Heizperiode prüfen:** Bei jedem Vicki-Tausch /
  Neu-Pairing Open-Window via Downlink aktivieren. Nicht annehmen, dass
  die Funktion läuft.
- **`attachedBackplate`-Bit gehört in `sensor_reading`.** Codec liefert es
  seit FW 4.1, ohne Persistenz keine Demontage-Erkennung.

**Quellen:**

- `docs/vendor/mclimate-vicki/` (vollständige Hersteller-Doku-Kopie 2026-05-09)
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` AE-47

**Was diese Lesson für andere Sprints bedeutet:**

- Sprint 9.12 (Frostschutz pro Raumtyp): zurückgestellt 2026-05-11
  (AE-42) — Lesson zur Layer-4-Koexistenz mit drei Trigger-Reasons
  (`open_window`, `device_detached`, später ggf. `inferred_window`)
  bleibt für späteren Reaktivierungs-Sprint relevant.
- BR-16 (Backend-Eigenlogik aktiv): nicht voreilig aktivieren, erst nach
  2 Wochen produktiver Beobachtung in Heizperiode.

### 5.28 ChirpStack-Downlinks: MQTT-Pfad, NICHT gRPC (Sprint 9.11x.b Lesson)

**Befund 2026-05-09 (Recherche für AE-48):**

Repo hat etablierten MQTT-basierten Downlink-Pfad in
`backend/src/heizung/services/downlink_adapter.py` (`send_setpoint` mit
`0x51`, MQTT-Topic `application/{app_id}/device/{dev_eui}/command/down`,
fPort=1, base64-payload). `aiomqtt` als Client-Bibliothek.

`CHIRPSTACK_API_KEY`-Slot in `.env.example` ist Bootstrap-Vorbereitung für
spätere gRPC-Anbindung (Backlog B-9.10c-1: Codec-Bootstrap-Skript), aber
**nicht** für Device-Downlinks. Device-Downlinks laufen über MQTT.

**Konsequenzen für Code-Änderungen:**

- Neue Vicki-Commands erweitern `downlink_adapter.py` via AE-48-Hybrid-
  Helper-Architektur (`send_raw_downlink` + typisierte Wrapper).
- Codec-`encodeDownlink`-Section ist Spiegel, nicht Quelle —
  Drift-Schutz via pytest gegen identische Erwartungs-Bytes.
- gRPC-Pfad NICHT aufmachen für Device-Downlinks.
- `Decimal` als Domain-Eingabe für Temperaturen, Byte-Konvertierung im
  Wrapper.

**Quelle:**

- AE-48 in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
- `backend/src/heizung/services/downlink_adapter.py` (bestehender Pfad)

### 5.29 passlib + bcrypt: unmaintained Wrapper bricht aktuelle Backend-Lib (Sprint 9.17 Lesson)

**Befund 2026-05-14 (Sprint 9.17 T12):**

`passlib 1.7.4` ist seit 2020-10 unmaintained und inkompatibel mit
`bcrypt >= 4.1`. Beim ersten `hash_password()`-Call läuft passlib's
`detect_wrap_bug`-Init durch, der probiert ein > 72-Byte-Secret zu
hashen — bcrypt 4.1+ wirft dafür `ValueError` statt zu truncaten, und
passlib's Backend-Mixin-Initialisierung crasht. Konsequenz wäre in
Production: CLI `hash_password`, `change-password`, `reset-password`
und User-`POST /users` werfen alle 500 beim ersten Aufruf.

Detection: nur möglich, wenn ein Test tatsächlich `hash_password()`
aufruft. Die 285 Bestandstests in Sprint 9.17 deckten den Pfad nicht
ab (Bootstrap-Admin wurde mit Placeholder-Hash inserted), die neuen
`test_api_auth`-Tests trafen ihn beim ersten Run.

**Regel für Auth-/Crypto-Libraries:** Wrapper-Libraries wie passlib,
die nicht aktiv gepflegt werden, sind ein verstecktes
Stabilitätsrisiko (S5: defensive bei externen Quellen — eine
unmaintained Library ist eine externe Quelle in Stasis). Wenn die
darunterliegende Lib (`bcrypt`, `cryptography`) eine direkte und
stabile API hat, ist der Direkt-Call die bessere Wahl: ein
Abhängigkeits-Glied weniger, kein Bug-Backlog bei Upstream-Breaks.

**Pflicht für Sprint-Briefe mit Auth-/Crypto-Stack:** Bei jeder
Wrapper-Library erst prüfen, ob sie überhaupt aktiv ist. Letzter
Release älter als 18 Monate → Risiko, Direkt-Call evaluieren.

**Konkret in 9.17 umgesetzt:**
- `backend/src/heizung/auth/password.py` ruft `bcrypt.hashpw` /
  `bcrypt.checkpw` direkt.
- `backend/pyproject.toml`: `passlib[bcrypt]>=1.7` ersetzt durch
  `bcrypt>=4.2`.
- AE-50 Punkt 1 dokumentiert die Brief-Abweichung.

### 5.30 Auth-Sprints: alle Endpoints absichern, nicht nur mutierende (Sprint 9.17a Lesson)

Sprint 9.17 hat das T6-Briefmandat 1:1 umgesetzt — "alle 21 mutierenden
Endpoints absichern". GET-Endpoints standen nicht im Inventar. Resultat:
nach Cutover lieferten 17 GET-Endpoints in 9 Routern Daten ohne
Auth-Check (Cowork-Befund 2026-05-14, im 9.17a-T1-Inventar bestätigt
— erste Schätzung "~9 in 5 Routern" war zu niedrig).

Brief-Lücke, nicht Implementierungs-Bug. Aber Konsequenz wäre Daten-Leak
sobald die Caddy-Basic-Auth-Schicht wegfällt.

**Regel für Auth-/Permission-Sprints:** Der Brief verlangt ein
vollständiges Endpoint-Inventar als Pflicht-Stop vor der eigentlichen
Absicherung. Inventar muss ALLE Methoden enthalten (GET inklusive), nicht
nur die mutierenden. Mitarbeiter-Lese-Recht ist ein authentifiziertes
Lese-Recht, nicht "darf jeder ohne Cookie sehen".

**Pflicht im Brief:** "T1: Endpoint-Inventar mit Soll-Dependency pro
Methode + Pfad, Pflicht-Stop für User-Review vor Absicherungs-Task".

**Brief-Regel-Abweichung dokumentieren (Sprint 9.17a Beispiel):**
`GET /users` blieb `require_admin` statt der allgemeinen GET→`require_user`-
Regel, weil User-Liste sensible Daten enthält (E-Mails, Rollen,
is_active). Solche Ausnahmen gehören in den T1-Inventar-Stop-Bericht
und in die finale Doku — nicht als stillschweigende Annahme im Code.

**Querverweise:** §5.20 (aspirative Kommentare als Doku-Drift — analog:
unvollständiger Brief als Risiko), AE-50 Punkt 6 (Feature-Flag-Pattern),
§5.29 (Auth-Library-Wahl, Sprint 9.17 Lesson).

### 5.31 FastAPI Response-Parameter vs. explicit Response-Return: zwei verschiedene Objekte (Sprint 9.17b Lesson)

Sprint 9.17 hatte Logout als

```python
async def logout(response: Response) -> Response:
    _clear_auth_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

implementiert. Die `delete_cookie`-Operation auf dem injizierten
`response`-Parameter wurde durch das explizit zurückgegebene neue
Response-Objekt überschrieben. Resultat: Logout liefert 204 ohne
Set-Cookie-Header, Browser behält das JWT-Cookie, Session bleibt
aktiv. B-9.17a-1 (Cowork-Smoke 9.17a). Der Sprint-9.17-Backend-Test
`test_logout_clears_cookie` war false-positive — er hat manuell
`http_client.cookies.clear()` gemacht und dann 401 verifiziert, statt
den Response-Header zu prüfen.

**Regel:** Bei FastAPI-Endpoints, die Cookies oder Header über
`response.set_cookie` / `response.delete_cookie` setzen, NIE
gleichzeitig ein neues Response-Objekt explizit zurückgeben. Entweder:

- Variante A: den injizierten `response`-Parameter mutieren + None
  zurückgeben (FastAPI nimmt dann den Parameter als finale Response).
- Variante B (verbindlich): eigenes Response-Objekt erzeugen UND die
  Header-Operation darauf anwenden, dann dieses zurückgeben:

```python
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookie(response)
    return response
```

Variante B ist die saubere Form, weil Datenfluss-Richtung eindeutig:
ein Objekt, eine Operation, ein Return.

**Pflicht für Auth-/Cookie-Sprints:** jeder Endpoint mit Cookie-
Set/Delete hat einen Backend-Test, der den Response-Header explizit
prüft (z.B. `assert "max-age=0" in resp.headers["set-cookie"].lower()`).
Browser-Smoke-Test allein reicht nicht — dort sieht man nur die
Folge-Symptome.

**Querverweise:** §5.30 (Endpoint-Inventar-Pflicht), AE-50 Punkt 4
(Inaktivitäts-Logout-Pattern — gleicher Stack betroffen).

**Backlog für später:** Server-side JWT-Blacklisting bei Logout.
Heute verlassen wir uns auf Browser-Cookie-Cleanup; ein gestohlener
JWT-Token bleibt 12h gültig. Für Single-Mandant-Hotelbetrieb
akzeptabel, für Multi-Mandant nicht. B-9.17b-1 (info).

### 5.32 Akzeptierter Container-Healthcheck-Drift ohne Engine-Auswirkung (Sprint 10 T3 Lesson)

Nicht jeder unhealthy-State im Container-Stack ist ein Stabilitätsrisiko.
Der celery_beat-Container auf heizung-test ist seit Wochen unhealthy
(435 FailingStreak im Snapshot 2026-05-15), aber Engine-Eval läuft
ungebremst.

**Wurzel des Drifts:** Das geteilte API-Image `heizung-api` bringt im
Dockerfile einen HEALTHCHECK mit
(`curl -f http://localhost:8000/health || exit 1`). Der greift für den
`api`-Container, weil dort uvicorn auf Port 8000 horcht.
`celery_worker` überschreibt im Compose-File diesen HEALTHCHECK auf
`celery -A heizung.celery_app inspect ping -t 5` → healthy.
`celery_beat` hat KEINE Compose-Override → erbt den Dockerfile-HEALTHCHECK
→ curl gegen 8000 schlägt fehl, weil beat keinen uvicorn fährt → unhealthy.

**Warum trotzdem akzeptiert:**

1. **Kein depends_on auf celery_beat-Health.** Kein Service nutzt
   `condition: service_healthy` mit celery_beat. Worker startet
   unabhängig, api startet unabhängig.
2. **Beat schedulet weiter zuverlässig.** Log auf heizung-test zeigt
   `evaluate-due-rooms-every-60s` mit konstanter 60-s-Kadenz, kein
   Tick verloren.
3. **Engine-Eval läuft im Worker, nicht im Beat.** Beat ist nur
   Scheduler — er steckt Tasks in die Redis-Queue. Die werden vom
   gesunden celery_worker ausgeführt.
4. **`restart: always` reagiert auf Crash, nicht auf unhealthy.**
   Docker restartet bei Exit-Code, nicht bei failed HEALTHCHECK
   (außer mit Swarm/Kubernetes-Orchestrierung, die wir nicht haben).
   Unhealthy ohne Crash → kein Restart-Loop.

**Konsequenz für Hotelier-Wahrnehmung:** `docker ps` zeigt
celery_beat als unhealthy, das macht das Status-Dashboard rot —
aber die Steuerung läuft. Hotelier wird informiert, dass dieser
spezifische unhealthy-State akzeptiert ist und nicht alarmiert.

**Regel:** Vor einem unhealthy-Container-Fix erst Diagnose:

- Welcher Process läuft tatsächlich im Container?
- Welcher HEALTHCHECK ist effektiv (Compose ≻ Dockerfile)?
- Hat irgendwas anderes `depends_on` mit `condition: service_healthy`
  drauf?
- Funktioniert die fachliche Aufgabe (hier: Task-Scheduling)?

Wenn (1) keine Engine-Auswirkung + (2) niemand `service_healthy`
verlangt + (3) der Process tut seinen Job: **akzeptierter Drift**,
Backlog-Eintrag mit klarer Status-Beschreibung, KEIN Hotfix.

**Wenn doch fixen:** Compose-Override für celery_beat-Healthcheck
einbauen. Optionen:

- Healthcheck disabled: `healthcheck: disable: true` — am einfachsten,
  aber `docker ps`-Status bleibt `(starting)` ohne State.
- Realistischer Check: `celery -A heizung.celery_app inspect scheduled`
  oder Schedule-File-Mtime-Check
  (`stat /tmp/celerybeat-schedule | grep -q '60 seconds ago'`).
- Status-Dashboard (B-9.11x-4) explizit unhealthy-celery_beat
  ausblenden, weil-Doku im UI.

Bis ein Status-Dashboard die Sicht zentralisiert: Diese Lesson +
B-9.11-4 als „akzeptiert"-Marker reichen.

**Querverweise:** §5.10 (Cosmetic vs. functional Drift bei
build-images.yml), §5.20 (Doku-Drift in Steuerlogik — gegenteilig:
dort produktive Pfade, hier reine Observability), AE-40 (Engine-Lock
isoliert beat von worker), B-9.11-4 (Backlog-Eintrag).

**Backlog für später:** Status-Dashboard (B-9.11x-4) zeigt
celery_beat-„healthy" basierend auf Schedule-Tick-Latenz, nicht
auf Dockerfile-HEALTHCHECK.

---

## 6. Pre-Push-Backend (Win-Host, PowerShell)

Lokale Toolchain auf `C:\Users\User\dev\heizung-sonnblick\backend\.venv` — ersetzt CI-Format-Loops und den ruff-`--diff`-Trick aus Sprint 9.9 T1-T5.

**Einmaliges Setup (bereits durch, falls fehlt erneut):**

```powershell
winget install --id Python.Python.3.12 -e --silent
winget install --id astral-sh.uv -e --silent
# Neue Shell oeffnen, damit PATH greift
cd C:\Users\User\dev\heizung-sonnblick\backend
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

**Vor jedem Backend-Push (Pflicht):**

```powershell
cd C:\Users\User\dev\heizung-sonnblick\backend
.\.venv\Scripts\Activate.ps1
ruff format .
ruff check . --fix
mypy src
pytest -x
```

Erst nach allen vier grün: `git push`. Lokaler Voll-Lauf <10 Sek; ersetzt 1-2 Min CI-Iteration und alle Format-Fix-Cascades aus Sprint 9.9 T1-T5.

**DB-Tests:** skippen lokal (kein `DATABASE_URL`); CI-Pipeline hat den Postgres-Service-Container und führt sie aus.

**Frontend (analog):**

```powershell
cd C:\Users\User\dev\heizung-sonnblick\frontend
npm run type-check
npm run lint
npm run build
```

---

## 7. Aktuelle Backlog-Punkte

- Caddy `fmt --overwrite` (kosmetisch, mit Sprint 6 wenn Caddy-Touch fuer ChirpStack-UI ohnehin)
- `~/.ssh/config`-Eintraege auf work02
- Caddy: `/_health` als oeffentlicher Health-Endpoint trennen vom internen `/api/*`-Routing
- CI-Mirror-Workflow `frontend-ci-skip.yml` aufraeumen, wenn Branch-Protection-Matcher smarter wird
- ChirpStack-Bootstrap-Skript (Tenant + App + DeviceProfile + Codec) fuer reproduzierbares Setup nach `docker compose down -v` (Sprint 6 oder spaeter)
- `.github/CODEOWNERS` einrichten, wenn weitere Mitwirkende dazukommen
- `services/_common.py` (Sprint 9.9-Backlog): konsolidiert duplicates `_task_session` aus `engine_tasks.py`/`override_cleanup_tasks.py`
- `services/event_log`-Wrapper (Sprint 9.9-Backlog): strukturierte Cap-/Revoke-Events ausserhalb der Engine-Pipeline
