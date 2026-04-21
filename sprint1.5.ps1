$ErrorActionPreference = 'Stop'

function Assert-ExitCode($what, $code) {
  if ($code -ne 0) {
    Write-Host "FEHLER bei: $what (ExitCode=$code)" -ForegroundColor Red
    exit $code
  }
}

Write-Host "=== Sprint 1.5 - Verifikation Deploy-Timer (test + main) ===" -ForegroundColor Cyan

$keyPath = "$env:USERPROFILE\.ssh\id_ed25519_heizung"
$sshBase = @("-i", $keyPath, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10")

function Invoke-ServerCheck {
  param([string]$Label, [string]$Server)

  Write-Host ""
  Write-Host "--- $Label ($Server) ---" -ForegroundColor Yellow

  Write-Host "[1/4] Timer-Status:" -ForegroundColor DarkCyan
  ssh @sshBase "root@$Server" "systemctl is-active heizung-deploy-pull.timer && systemctl list-timers heizung-deploy-pull.timer --no-pager | head -3"
  Assert-ExitCode "timer status ($Label)" $LASTEXITCODE

  Write-Host "[2/4] Letzter Service-Run:" -ForegroundColor DarkCyan
  ssh @sshBase "root@$Server" "systemctl show heizung-deploy-pull.service --property=ActiveState,Result,ExecMainStatus,ExecMainStartTimestamp"
  Assert-ExitCode "service status ($Label)" $LASTEXITCODE

  Write-Host "[3/4] Manueller Trigger (blockierend):" -ForegroundColor DarkCyan
  ssh @sshBase "root@$Server" "systemctl start heizung-deploy-pull.service && systemctl show heizung-deploy-pull.service --property=Result,ExecMainStatus"
  Assert-ExitCode "service start ($Label)" $LASTEXITCODE

  Write-Host "[4/4] Letzte 20 Log-Zeilen:" -ForegroundColor DarkCyan
  ssh @sshBase "root@$Server" "tail -n 20 /var/log/heizung-deploy.log"
  Assert-ExitCode "deploy-log ($Label)" $LASTEXITCODE
}

Invoke-ServerCheck "heizung-test" "100.82.226.57"
Invoke-ServerCheck "heizung-main" "100.82.254.20"

Write-Host ""
Write-Host "=== Sprint 1.5 FERTIG ===" -ForegroundColor Green
Write-Host "Erwartung: Result=success, ExecMainStatus=0, kein 'Pull fehlgeschlagen' im Log." -ForegroundColor Cyan
Write-Host "Naechster Schritt: .\sprint1.6.ps1 (alten PAT auf GitHub widerrufen)" -ForegroundColor Cyan
