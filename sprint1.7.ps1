$ErrorActionPreference = 'Stop'

function Assert-ExitCode($what, $code) {
  if ($code -ne 0) {
    Write-Host "FEHLER bei: $what (ExitCode=$code)" -ForegroundColor Red
    exit $code
  }
}

Write-Host "=== Sprint 1.7 - Doku-Update via Feature-Branch + PR ===" -ForegroundColor Cyan

$branch = "chore/sprint1-pat-rotation"
$base   = "main"
$files  = @(
  "docs/RUNBOOK.md",
  "docs/features/2026-04-21-sprint1-pat-rotation.md",
  "STATUS.md",
  "sprint1.3.ps1",
  "sprint1.4.ps1",
  "sprint1.5.ps1",
  "sprint1.7.ps1"
)

Write-Host "--- [1/8] Pre-checks ---" -ForegroundColor Yellow
git rev-parse --is-inside-work-tree > $null
Assert-ExitCode "nicht in git-Repo" $LASTEXITCODE

$current = git rev-parse --abbrev-ref HEAD
if ($current -ne $base) {
  Write-Host "Aktueller Branch: $current — wechsle zu $base und pull..." -ForegroundColor DarkYellow
  git checkout $base
  Assert-ExitCode "git checkout $base" $LASTEXITCODE
}
git pull --ff-only origin $base
Assert-ExitCode "git pull $base" $LASTEXITCODE

Write-Host "--- [2/8] Feature-Branch $branch ---" -ForegroundColor Yellow
$existing = git branch --list $branch
if ($existing) {
  git checkout $branch
} else {
  git checkout -b $branch
}
Assert-ExitCode "branch checkout" $LASTEXITCODE

Write-Host "--- [3/8] Status prüfen ---" -ForegroundColor Yellow
git status --short

Write-Host "--- [4/8] Stage gezielt ---" -ForegroundColor Yellow
foreach ($f in $files) {
  if (Test-Path $f) {
    git add -- $f
    Assert-ExitCode "git add $f" $LASTEXITCODE
  } else {
    Write-Host "  (übersprungen, existiert nicht: $f)" -ForegroundColor DarkGray
  }
}

$staged = git diff --cached --name-only
if (-not $staged) {
  Write-Host "Nichts zu committen. Vermutlich schon commited. Ueberspringe Commit." -ForegroundColor DarkYellow
} else {
  Write-Host "Staged:" -ForegroundColor DarkCyan
  $staged | ForEach-Object { Write-Host "  $_" }

  Write-Host "--- [5/8] Commit ---" -ForegroundColor Yellow
  $msg = @"
docs(sprint1): document GHCR PAT rotation procedure

- Rewrite RUNBOOK §6 for public-repo git fetch (no token needed)
- New RUNBOOK §6.1: tested GHCR PAT rotation procedure
  (classic PAT with read:packages, SecureString input,
   sprint1.3/1.4/1.5 scripts as canonical steps)
- Feature brief docs/features/2026-04-21-sprint1-pat-rotation.md
- STATUS: close Sprint 0 + Sprint 1, remove PAT warning,
  add lessons learned, update next steps
- Keep rotation scripts (sprint1.3-1.5, 1.7) as templates

Refs: Sprint 1.1-1.7, first pass through branch protection.
"@
  git commit -m $msg
  Assert-ExitCode "git commit" $LASTEXITCODE
}

Write-Host "--- [6/8] Push ---" -ForegroundColor Yellow
git push -u origin $branch
Assert-ExitCode "git push" $LASTEXITCODE

Write-Host "--- [7/8] Pull Request ---" -ForegroundColor Yellow
$prExists = gh pr view $branch --json number --jq .number 2>$null
if ($prExists) {
  Write-Host "PR existiert bereits (#$prExists). Ueberspringe PR-Anlage." -ForegroundColor DarkYellow
} else {
  $prBody = @"
## Zusammenfassung
Abschluss Sprint 1 (GHCR-PAT-Rotation). Rein Doku — kein Code, keine CI-relevanten Änderungen.

## Was drin ist
- ``docs/RUNBOOK.md`` §6/§6.1 komplett umgeschrieben (alte Version beschrieb falsches Verfahren)
- ``docs/features/2026-04-21-sprint1-pat-rotation.md`` — Feature-Brief inkl. Sprintplan 1.1–1.7
- ``STATUS.md`` — Sprint 0 und 1 als abgeschlossen markiert, PAT-Warnung entfernt, Lessons Learned ergänzt
- ``sprint1.3.ps1`` / ``sprint1.4.ps1`` / ``sprint1.5.ps1`` / ``sprint1.7.ps1`` — Rotations-Skripte bleiben als Vorlage

## Test Plan
- [x] Rotation manuell auf beiden Servern durchgeführt (Sprint 1.3–1.5)
- [x] ``heizung-deploy-pull.service`` auf beiden Servern Result=success
- [x] Alter PAT ``claude-sprint2-push`` auf GitHub gelöscht (Sprint 1.6)
- [ ] CI grün (frontend-ci, backend-ci, e2e) — erwartet trivial, da nur Doku
- [ ] Merge nach ``main`` (erster Durchgang durch Branch-Protection)
"@
  gh pr create --base $base --head $branch --title "docs(sprint1): GHCR PAT rotation + RUNBOOK §6.1" --body $prBody
  Assert-ExitCode "gh pr create" $LASTEXITCODE
}

Write-Host "--- [8/8] Abschluss ---" -ForegroundColor Yellow
$prNumber = gh pr view $branch --json number --jq .number
Write-Host ""
Write-Host "=== Sprint 1.7 push + PR FERTIG ===" -ForegroundColor Green
Write-Host "PR #$prNumber geoeffnet gegen $base." -ForegroundColor Cyan
Write-Host ""
Write-Host "Naechster Schritt (User):" -ForegroundColor Cyan
Write-Host "  1. CI-Grün abwarten:  gh pr checks $prNumber --watch" -ForegroundColor Cyan
Write-Host "  2. PR reviewen:       gh pr view $prNumber --web" -ForegroundColor Cyan
Write-Host "  3. Merge:             gh pr merge $prNumber --squash --delete-branch" -ForegroundColor Cyan
