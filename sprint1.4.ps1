$ErrorActionPreference = 'Stop'

function Assert-ExitCode($what, $code) {
  if ($code -ne 0) {
    Write-Host "FEHLER bei: $what (ExitCode=$code)" -ForegroundColor Red
    exit $code
  }
}

Write-Host "=== Sprint 1.4 - PAT-Rotation auf heizung-main ===" -ForegroundColor Cyan

if (-not $env:NEW_PAT -or -not $env:NEW_PAT.StartsWith("ghp_")) {
  Write-Host "FEHLER: `$env:NEW_PAT nicht gesetzt oder falsches Format." -ForegroundColor Red
  exit 1
}

$keyPath   = "$env:USERPROFILE\.ssh\id_ed25519_heizung"
$sshTarget = "root@100.82.254.20"
$sshBase   = @("-i", $keyPath, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10")

function Invoke-SshStdin {
  param([string]$RemoteCmd, [string]$StdinData)
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "ssh"
  $psi.Arguments = "-i `"$keyPath`" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 $sshTarget `"$RemoteCmd`""
  $psi.RedirectStandardInput  = $true
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError  = $true
  $psi.UseShellExecute = $false
  $p = [System.Diagnostics.Process]::Start($psi)
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  $bytes = $utf8NoBom.GetBytes($StdinData)
  $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
  $p.StandardInput.BaseStream.Flush()
  $p.StandardInput.Close()
  $o = $p.StandardOutput.ReadToEnd()
  $e = $p.StandardError.ReadToEnd()
  $p.WaitForExit()
  if ($o) { Write-Host $o.Trim() }
  if ($e) { Write-Host $e.Trim() -ForegroundColor DarkYellow }
  return $p.ExitCode
}

Write-Host "--- docker login ghcr.io (neuer PAT via stdin) ---" -ForegroundColor Yellow
$code = Invoke-SshStdin "docker login ghcr.io -u rexei123 --password-stdin" $env:NEW_PAT
Assert-ExitCode "docker login" $code

Write-Host "--- Test-Pull heizung-api:main ---" -ForegroundColor Yellow
ssh @sshBase $sshTarget "docker pull ghcr.io/rexei123/heizung-api:main"
Assert-ExitCode "docker pull heizung-api" $LASTEXITCODE

Write-Host "--- Test-Pull heizung-web:main ---" -ForegroundColor Yellow
ssh @sshBase $sshTarget "docker pull ghcr.io/rexei123/heizung-web:main"
Assert-ExitCode "docker pull heizung-web" $LASTEXITCODE

Write-Host "--- Verifikation: ~/.docker/config.json enthaelt ghcr.io ---" -ForegroundColor Yellow
$cfgRaw = ssh @sshBase $sshTarget "test -f /root/.docker/config.json && grep -c 'ghcr.io' /root/.docker/config.json || echo 0"
$cfgCount = [int]($cfgRaw | Select-Object -First 1)
if ($cfgCount -gt 0) {
  Write-Host "OK: Docker-Credential-Store enthaelt ghcr.io ($cfgCount Eintraege)." -ForegroundColor Green
} else {
  Write-Host "WARNUNG: ~/.docker/config.json enthaelt kein ghcr.io" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Sprint 1.4 FERTIG ===" -ForegroundColor Green
Write-Host "Naechster Schritt: .\sprint1.5.ps1 (Verifikation Deploy-Timer)" -ForegroundColor Cyan
