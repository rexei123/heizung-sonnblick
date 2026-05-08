> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprint 0 — Baseline: Projekt workflow-ready machen

**Typ:** Intern, einmalig
**Ziel:** Nach Sprint 0 kann Claude autonom gemäß `WORKFLOW.md` Phase 3 arbeiten, ohne an technischen Altlasten zu scheitern.
**Branch:** `chore/sprint0-baseline` (von aktuellem `main` abgezweigt)
**Geschätzte Dauer:** 2–3 h Claude-Arbeit, ca. 10 Min Anwender-Aktion (ganz am Ende)

---

## Feature-Brief (Phase 1 kompakt)

### Ziel
Die vier dokumentierten Blocker (CRLF, kein E2E, Branch-Divergenz, Cleanup-Reste) werden beseitigt. Das neue Arbeitsframework (`SPEC-FRAMEWORK.md` + `WORKFLOW.md`) wird offiziell im Repo verankert.

### Akzeptanzkriterien
- [ ] `git status` nach Checkout zeigt auf einer frischen Umgebung **keine** "modified"-Dateien
- [ ] `.gitattributes` ist vorhanden, erzwingt LF für Shell-/Python-/JS-Quellen, CRLF nur für explizit-Windows-Dateien
- [ ] `npx playwright test` läuft lokal grün mit mindestens 1 Smoke-Test (Startseite antwortet 200)
- [ ] CI-Pipeline `frontend-ci.yml` führt Playwright aus und blockiert Merge bei Rotlauf
- [ ] `develop` und `main` zeigen auf identische Commits (Fast-Forward-Zustand)
- [ ] `fix-ssh.sh`, `fix2.sh`, `setup-ssh.sh`, `erich.pub` sind aus Repo-Root entfernt oder bewusst nach `infra/keys/` verschoben
- [ ] `STATUS.md` ist im Repo committed und faktisch korrekt (shadcn/ui-Diskrepanz geklärt)
- [ ] `docs/SPEC-FRAMEWORK.md` + `docs/WORKFLOW.md` sind auf `main` gemergt
- [ ] GitHub Branch-Protection auf `main` aktiv: PR-Pflicht + CI muss grün sein
- [ ] Git-Tag `v0.1.0-baseline` auf den Abschluss-Commit gesetzt

### Abgrenzung — NICHT Teil von Sprint 0
- Kein neues Feature, keine API-Erweiterung
- Keine UI-Änderungen am bestehenden Frontend
- Keine Migration, keine Datenmodell-Änderung
- Kein Refactoring bestehenden Codes
- Kein PAT-Rotation (separate Aufgabe, ggf. Sprint 1)
- Kein UFW-Re-Aktivierung auf Main (separate Aufgabe)

### Risiken
1. **CRLF-Renormalisierung verändert viele Dateien** → Muss in **einem einzigen** Commit isoliert bleiben, Commit-Message `chore: normalize line endings (baseline)`, sonst Diff-Hölle in nachfolgenden Reviews
2. **Shell-Scripts mit CRLF könnten auf Prod bereits laufen weil Docker sie umbiegt** → Nach Normalisierung Test-Deploy beobachten, ob Container weiter starten
3. **Branch-Sync könnte Commit `64765aa` vernichten** → Vor jedem Reset `git diff main..develop` prüfen; bei Abweichung Merge statt Reset
4. **Playwright in CI kann Build-Zeit deutlich erhöhen** → Mit `--only-changed` und `shard`-Strategie arbeiten; für Sprint 0 reicht 1 minimaler Smoke-Test
5. **Branch-Protection-Regel erfordert Anwender-Aktion in GitHub-Web-UI** → Letzter Schritt, klarer Screen-Guide im Chat

---

## Sprintplan (Phase 2)

### Sprint 0.1 — CRLF-Normalisierung (Baseline clean)

- **Ziel:** Repo normalisiert, `git status` auf frischem Checkout ist sauber
- **Dateien:** neu `.gitattributes`; renormalisiert: alle Quelldateien
- **Vorgehen:**
  1. `.gitattributes` anlegen mit Regeln:
     - `* text=auto eol=lf`
     - `*.sh text eol=lf`
     - `*.py text eol=lf`
     - `*.ts text eol=lf`
     - `*.tsx text eol=lf`
     - `*.js text eol=lf`
     - `*.yml text eol=lf`
     - `*.md text eol=lf`
     - `*.bat text eol=crlf`
     - `*.ps1 text eol=crlf`
     - Binärdateien explizit markieren
  2. `git add --renormalize .`
  3. Ein Commit: `chore: normalize line endings (baseline)`
- **Test:**
  - `git status` nach dem Commit leer
  - `file backend/docker-entrypoint.sh` zeigt "ASCII text" ohne "with CRLF"
- **DoD:** grün, Commit gepusht, CI-Pipeline ausgelöst (darf aber noch rot sein wegen Zwischenstand)
- **Rollback:** `git reset --hard <vorheriger-commit>`
- **Dauer:** ca. 15 Min

### Sprint 0.2 — Branch-Sync `develop` ↔ `main`

- **Ziel:** `develop` und `main` zeigen auf denselben Commit
- **Vorgehen:**
  1. `git diff main..develop` inspizieren — wenn leer, Fast-Forward möglich
  2. Bei Gleichheit: `git checkout develop && git reset --hard main && git push --force-with-lease origin develop`
  3. Bei Unterschied: Analyse + Merge-Commit erstellen, Anwender einbeziehen
- **Test:** `git log --oneline main..develop` und `git log --oneline develop..main` sind beide leer
- **DoD:** Beide Branches synchron auf Remote sichtbar
- **Rollback:** Der alte develop-Head ist in reflog, rückholbar
- **Dauer:** ca. 10 Min

### Sprint 0.3 — Cleanup Repo-Root

- **Ziel:** Keine Schrott-Dateien mehr, Rescue-Überreste beseitigt
- **Vorgehen:**
  1. `fix-ssh.sh`, `fix2.sh`, `setup-ssh.sh` löschen (unversioniert bzw. aus Repo entfernen)
  2. `erich.pub` nach `infra/keys/erich.pub` verschieben + README dort erklärt Zweck, oder — Empfehlung — aus Repo raus (ist Pubkey, gehört in Tailscale/Hetzner-Config, nicht ins Code-Repo)
  3. `.gitignore` ergänzen um `*.pub` (falls nicht vorhanden) und weitere Debris-Patterns
- **Test:** `ls /repo-root` zeigt nur erwartete Einträge
- **DoD:** Commit `chore: remove rescue leftovers, move ssh pubkey out of repo`
- **Dauer:** ca. 10 Min

### Sprint 0.4 — Playwright einrichten + CI-Integration

- **Ziel:** E2E-Test-Framework lauffähig, 1 Smoke-Test grün, CI blockiert bei Rot
- **Dateien:** neu `frontend/playwright.config.ts`, `frontend/tests/e2e/smoke.spec.ts`; erweitert `frontend/package.json`, `.github/workflows/frontend-ci.yml`
- **Vorgehen:**
  1. `npm i -D @playwright/test` im `frontend/`
  2. `npx playwright install --with-deps chromium` (lokal und in CI)
  3. `playwright.config.ts` mit Base-URL aus ENV, Retries=2 in CI, Reporter=html+github
  4. Smoke-Test: `smoke.spec.ts` besucht `/`, erwartet HTTP 200 + Präsenz `<main>`
  5. `package.json` Scripts: `"test:e2e": "playwright test"`, `"test:e2e:ui": "playwright test --ui"`
  6. `frontend-ci.yml` erweitern: neuer Job `e2e`, abhängig von `lint-and-build`, startet Next.js im Hintergrund, führt Playwright, uploaded Report-Artifact
- **Test:**
  - Lokal: `cd frontend && npm run test:e2e` grün
  - CI: Pipeline grün, E2E-Job sichtbar
- **DoD:** Commit `feat(frontend): add playwright e2e with smoke test`; CI-Lauf grün dokumentiert
- **Rollback:** Revert des Commits; lokal `npm uninstall`
- **Dauer:** ca. 60–90 Min

### Sprint 0.5 — STATUS.md korrigieren + Framework committen

- **Ziel:** Framework-Dokumente und aktualisierter Status im Repo
- **Vorgehen:**
  1. `STATUS.md` prüfen und korrigieren:
     - shadcn/ui-Behauptung entfernen oder einbauen (aktuell: nicht installiert)
     - "Zuletzt erledigt"-Abschnitt um Sprint 0 ergänzen
     - Abschnitt "Cleanup" entsprechend reduzieren (Punkte erledigt)
  2. `STATUS.md`, `docs/SPEC-FRAMEWORK.md`, `docs/WORKFLOW.md`, `docs/features/2026-04-21-sprint0-baseline.md` staged
  3. Commit `docs: introduce workflow framework (spec + workflow + sprint0 plan)`
- **Test:** Dokumente in `main`-Branch sichtbar nach Merge
- **DoD:** Commit auf Feature-Branch, bereit für finalen PR
- **Dauer:** ca. 20 Min

### Sprint 0.6 — Merge, Tag, Branch-Protection (Anwender-Gate)

- **Ziel:** Sprint-0-Ergebnis produktiv
- **Vorgehen Claude:**
  1. Feature-Branch `chore/sprint0-baseline` pushen
  2. PR gegen `develop` öffnen mit vollständiger Zusammenfassung
  3. CI grün abwarten
  4. Merge nach `develop` (Fast-Forward)
  5. Test-Deploy auf Test-Server abwarten (5-Min-Timer) — Health-Check
  6. Merge `develop` → `main`, Main-Deploy abwarten — Health-Check
  7. Tag `v0.1.0-baseline` auf Main-HEAD, pushen
  8. Feature-Branch lokal + remote löschen
- **Vorgehen Anwender (einmalig, ca. 10 Min):**
  1. GitHub → Settings → Branches → Branch-Protection-Regel für `main`:
     - Require pull request before merging
     - Require status checks to pass: `backend-ci`, `frontend-ci` inkl. E2E
     - Require branches to be up to date
     - Do not allow force pushes
  2. Bestätigung im Chat: "Protection aktiv"
- **Test:** Versuch, direkt auf `main` zu pushen, wird abgelehnt
- **DoD:** Tag sichtbar, Branch-Protection aktiv, Sprint 0 abgeschlossen
- **Dauer Claude:** 15 Min; **Dauer Anwender:** ca. 10 Min

---

## Offene Fragen / Annahmen

- **[Annahme]** Nach CRLF-Normalisierung in Sprint 0.1 starten alle Docker-Container weiter. Ich prüfe das durch Test-Deploy nach Sprint 0.1.
- **[Annahme]** `erich.pub` wird aus dem Repo entfernt. Falls Sie argumentieren, der Key gehört ins Repo (z. B. für automatisiertes Key-Provisioning), verschiebe ich nach `infra/keys/` statt löschen. Bitte kurz sagen, sonst gehe ich mit "löschen".
- **[Annahme]** Playwright läuft im CI gegen eine lokal im Job gestartete Next.js-Instanz (`next start`), nicht gegen Test-Server. Das ist schneller und unabhängig von Server-Zustand.
- **[Annahme]** shadcn/ui wird in Sprint 0 nicht installiert — wenn Design-Strategie es braucht, wird das Feature-Sprint in Sprint 1+.

---

## Phase-Gates

- **Gate 1 (Phase 1, jetzt):** Anwender liest Feature-Brief. Freigabe oder Änderung.
- **Gate 2 (Phase 2, jetzt im selben Dokument):** Anwender liest Sprintplan. Freigabe oder Umschnitt.
- **Gate 4 (nach Sprint 0.5):** Anwender prüft Pull-Request und Test-Server-Deploy, bevor Merge nach `main`.
