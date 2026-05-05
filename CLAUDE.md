# Claude-Kontext Heizungssteuerung Hotel Sonnblick

Dieses File wird automatisch geladen. Lies es **vor jeder Aktion** im Repo.

## 1. Identität & Stand

- **Projekt:** Heizungssteuerung für Hotel Sonnblick (Mandatar: hotelsonnblick@gmail.com)
- **Repo:** https://github.com/rexei123/heizung-sonnblick (public)
- **Lokales Working Copy:** `C:\Users\User\dev\heizung-sonnblick`
- **Aktueller Sprint:** **Sprint 9.8 abgeschlossen**, Sprint 9.8c (Hygiene) in Vorbereitung.
- **Letzter Tag:** `v0.1.9-rc1-walking-skeleton`
- **Produktivumgebungen:** `https://heizung.hoteltec.at` (Main), `https://heizung-test.hoteltec.at` (Test)

## 2. Pflicht-Lektüre vor Sprint-Arbeit

In dieser Reihenfolge:

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
git config --global --add safe.directory /opt/heizung-sonnblick
```

**Sprint-Backlog:** `deploy-pull.sh` sollte beim ersten Run diesen Fix selbst setzen, damit neue Server out-of-the-box klappen.

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

---

## 6. Aktuelle Backlog-Punkte

- Caddy `fmt --overwrite` (kosmetisch, mit Sprint 6 wenn Caddy-Touch fuer ChirpStack-UI ohnehin)
- `~/.ssh/config`-Eintraege auf work02
- Caddy: `/_health` als oeffentlicher Health-Endpoint trennen vom internen `/api/*`-Routing
- CI-Mirror-Workflow `frontend-ci-skip.yml` aufraeumen, wenn Branch-Protection-Matcher smarter wird
- ChirpStack-Bootstrap-Skript (Tenant + App + DeviceProfile + Codec) fuer reproduzierbares Setup nach `docker compose down -v` (Sprint 6 oder spaeter)
- `.github/CODEOWNERS` einrichten, wenn weitere Mitwirkende dazukommen
