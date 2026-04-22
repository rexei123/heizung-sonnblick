# RUNBOOK — Heizungssteuerung Hotel Sonnblick

Operations-Handbuch für Test- und Main-Server. Stand: 2026-04-22.

**Regel Nr. 1:** Bei Rescue-Einsatz IMMER den kompletten Fix-Block aus §3 in einem Shot ausführen. Niemals inkrementell fixen.

---

## 1. Server-Übersicht

| Rolle | Hetzner | Public-IP / Hostname | Tailscale | GHCR-Tag | Branch |
|---|---|---|---|---|---|
| Test | CPX22 | `157.90.17.150` / `157-90-17-150.nip.io` | `heizung-test` = `100.82.226.57` | `develop` | `develop` |
| Main | CPX32 | `157.90.30.116` / `157-90-30-116.nip.io` | `heizung-main` = `100.82.254.20` | `main` | `main` |
| Entwickler-Client | — | — | `work02` = `100.78.38.29` | — | — |

**SSH-Key lokal:** `$HOME\.ssh\id_ed25519_heizung` (Pubkey in Hetzner als `ssh-heizung` registriert, gilt auch im Rescue-Modus).

**Deploy-Zyklus:** Merge auf `develop`/`main` → GitHub Actions baut Image → systemd-Timer auf Server zieht innerhalb 5 Min.

---

## 2. SSH-Zugang

**Standard (via Tailscale MagicDNS):**

```powershell
ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-test
ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-main
```

**Notfall (via Public-IP, falls Tailscale down):**

```powershell
ssh -i $HOME\.ssh\id_ed25519_heizung root@157.90.17.150
ssh -i $HOME\.ssh\id_ed25519_heizung root@157.90.30.116
```

---

## 3. Rescue-Mode (Hetzner Cloud) — Pflicht-Ablauf

**NUR betreten mit vollständigem Fix-Block ready im Clipboard. Jeder Extra-Reboot kostet 90 Sek.**

### 3.1 Rescue aktivieren

1. Hetzner Dashboard → Server öffnen → **Rescue** Tab
2. OS: `linux64`, SSH-Key: `ssh-heizung` auswählen
3. **Rescue aktivieren** klicken → Passwort notieren
4. **Power** Tab → **Neu starten** (Reset, NICHT Graceful Shutdown)
5. 60–90 Sek warten

### 3.2 SSH in den Rescue

```powershell
ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-test   # oder heizung-main
# Fingerprint akzeptieren falls anders (Rescue hat eigenen Host-Key)
```

### 3.3 Universal-Fix-Block (copy-paste in einem Rutsch)

Löst: UFW-Lockout + PermitRootLogin=no + fehlender Key + fail2ban-Ban.

```bash
set -e
mount /dev/sda1 /mnt
# UFW abschalten (falls es aussperrt)
sed -i 's/^ENABLED=yes/ENABLED=no/' /mnt/etc/ufw/ufw.conf 2>/dev/null || true
rm -f /mnt/etc/systemd/system/multi-user.target.wants/ufw.service
# root-Login mit Key erlauben, Passwort-Auth bleibt aus
mkdir -p /mnt/etc/ssh/sshd_config.d
echo 'PermitRootLogin prohibit-password' > /mnt/etc/ssh/sshd_config.d/00-root-login.conf
# Eigenen Pubkey dazu-mergen + dedupen
mkdir -p /mnt/root/.ssh && chmod 700 /mnt/root/.ssh
cat /root/.ssh/authorized_keys >> /mnt/root/.ssh/authorized_keys
sort -u /mnt/root/.ssh/authorized_keys -o /mnt/root/.ssh/authorized_keys
chmod 600 /mnt/root/.ssh/authorized_keys
# fail2ban-Bans zurücksetzen
rm -f /mnt/var/lib/fail2ban/fail2ban.sqlite3 2>/dev/null || true
umount /mnt
reboot
```

Nach dem Reboot (90 Sek warten) ist der Rescue-Modus verbraucht. Server bootet normal, SSH funktioniert wieder.

---

## 4. SSH-Fehlerbilder — Diagnose-Baum

| Fehlermeldung | Ursache | Soforthilfe |
|---|---|---|
| `Connection timed out` (Port 22) | UFW DROP oder Cloud Firewall blockt | Rescue-Mode → §3.3 |
| `Connection refused` | sshd läuft nicht | Rescue-Mode → `chroot /mnt systemctl enable ssh` |
| `Permission denied (publickey)` + Verbose zeigt `Server accepts key` | `PermitRootLogin=no` | Rescue-Mode → §3.3 (sshd_config.d-Teil) |
| `Permission denied (publickey)` direkt | Key nicht in authorized_keys | Rescue-Mode → §3.3 (authorized_keys-Teil) |
| Abwechselnd Permission denied + Timeout | fail2ban-Ban (10 Min) | warten ODER §3.3 (fail2ban-DB löschen) |

**Port-Check vor Rescue:**

```powershell
Test-NetConnection 157.90.30.116 -Port 22   # SSH
Test-NetConnection 157.90.30.116 -Port 443  # Caddy (HTTPS)
```

Beide offen, aber SSH antwortet nicht → sshd-Problem. Nur 443 offen → UFW. Beide zu → Hetzner Cloud Firewall prüfen (aktuell NICHT konfiguriert für diesen Account).

---

## 5. Deploy-Fehler

### 5.1 Deploy-Timer-Status

```bash
systemctl status heizung-deploy-pull.timer
systemctl list-timers heizung-deploy-pull.timer
journalctl -u heizung-deploy-pull.service --since '1 hour ago'
```

### 5.2 Manueller Deploy

```bash
cd /opt/heizung-sonnblick
./infra/deploy/deploy-pull.sh
```

### 5.3 Container-Status

```bash
cd /opt/heizung-sonnblick/infra/deploy
docker compose ps
docker compose logs -f api --tail 100
```

### 5.4 Image-Pull schlägt fehl

```bash
docker login ghcr.io -u rexei123 --password-stdin   # PAT aus .env
docker pull ghcr.io/rexei123/heizung-api:main       # bzw. :develop
```

### 5.5 Auto-Migration-Logs

```bash
docker compose logs api 2>&1 | grep -E 'alembic|upgrade'
```

---

## 6. Git auf Server (read-only, ohne PAT)

Das Repo ist **public**. Serverseitiger `git fetch` braucht **keinen** Token:

```bash
cd /opt/heizung-sonnblick
git config --global --add safe.directory /opt/heizung-sonnblick
git remote set-url origin https://github.com/rexei123/heizung-sonnblick.git
git fetch origin
git reset --hard origin/main   # bzw. origin/develop auf Test
```

Schreibzugriffe (Push/Merge) passieren **nicht** auf dem Server. Produktiv-Deploy läuft ausschließlich über GHCR-Pull — siehe §5 und §6.1.

### 6.1 GHCR-PAT rotieren (getestetes Verfahren, Sprint 1)

**Zweck:** Der Pull-Deploy-Service `heizung-deploy-pull.service` macht `docker compose pull` und liest Credentials aus `/root/.docker/config.json`. Dieser Eintrag muss einen gültigen GHCR-Token enthalten.

**Wichtig:**
- **Classic PAT** zwingend (Fine-grained PATs unterstützen GHCR nicht).
- **Scope:** ausschließlich `read:packages`.
- **Ablauf:** Name-Konvention `heizung-ghcr-pull-YYYY-MM`, Expiration 90 Tage, ins Kalender-Reminder setzen.

**Rotations-Skripte im Repo-Root (`sprint1.3.ps1`, `sprint1.4.ps1`, `sprint1.5.ps1`) bleiben als Vorlage für zukünftige Rotationen erhalten.**

#### Ablauf

1. **Neuen Token erstellen:** https://github.com/settings/tokens → Generate new token (classic) → Scope **nur** `read:packages` → Name `heizung-ghcr-pull-YYYY-MM` → Token kopieren.

2. **Token in PowerShell-Session laden (nie auf Disk, nie in Argv):**

   ```powershell
   $secure = Read-Host -AsSecureString "Neuen PAT einfuegen"
   $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
   $env:NEW_PAT = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
   [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
   ```

3. **Rotation auf Test-Server (heizung-test):**

   ```powershell
   .\sprint1.3.ps1
   ```

   Tut intern: `docker login ghcr.io -u rexei123 --password-stdin` via SSH+stdin-Pipe, Test-Pull `heizung-api:develop` + `heizung-web:develop`, Verifikation `/root/.docker/config.json`.

4. **Rotation auf Main-Server (heizung-main):**

   ```powershell
   .\sprint1.4.ps1
   ```

   Identisch, nur Ziel `100.82.254.20` und Tag `:main`.

5. **Verifikation Deploy-Timer beider Server:**

   ```powershell
   .\sprint1.5.ps1
   ```

   Triggert `heizung-deploy-pull.service` manuell und prüft `Result=success`, `ExecMainStatus=0`, Log ohne `Pull fehlgeschlagen`.

6. **Alten Token widerrufen:** https://github.com/settings/tokens → alten Token (vorige Rotation) löschen. Ab jetzt ist die alte Credential überall tot.

7. **Session-Variable aufräumen:**

   ```powershell
   Remove-Item Env:NEW_PAT
   ```

#### Troubleshooting

- **`Host key verification failed`** beim ersten SSH auf einen Server nach Server-Neuaufbau → `ssh-keygen -R <IP>` und Skript nochmal starten. Die Skripte haben `StrictHostKeyChecking=accept-new`, akzeptieren also den neuen Key beim zweiten Versuch.
- **Skript hängt bei `docker login`** → Tailscale nicht verbunden. `tailscale status` in separater Konsole prüfen, ggf. `tailscale up`.
- **`systemctl is-active` liefert `inactive` / ExitCode 4** → Unit-Name falsch. Korrekter Name ist `heizung-deploy-pull.timer` / `heizung-deploy-pull.service` (nicht `heizung-deploy`).
- **PAT in `.env` eintragen?** Nein. Der PAT liegt ausschließlich in `/root/.docker/config.json` nach Login. Die `.env` kennt keinen GHCR-Token.

---

## 7. Tailscale-Reconnect

```bash
tailscale status
tailscale up --ssh --accept-routes   # falls down
tailscale ip -4                      # zeigt eigene IP
```

MagicDNS ist aktiv — Hostnames `heizung-test`, `heizung-main`, `work02` sind direkt auflösbar.

---

## 8. UFW-Hardening

**Stand 2026-04-22:** UFW aktiv auf `heizung-main` und `heizung-test` mit identischem Regelwerk:

```
22/tcp (OpenSSH)      ALLOW IN   Anywhere       # Fallback für Tailscale-Ausfall (Entscheidung B)
80/tcp                ALLOW IN   Anywhere       # Caddy HTTP (ACME)
443/tcp               ALLOW IN   Anywhere       # Caddy HTTPS
Anywhere on tailscale0 ALLOW IN  Anywhere       # Tailscale-Interface
# + v6-Pendants
```

**Entscheidung B (2026-04-22, Sprint 3):** Port 22 bleibt public offen als Fallback. Absicherung: `PermitRootLogin prohibit-password` + Schlüssel `id_ed25519_heizung`. Kein Passwort-Login möglich.

### 8.1 Re-Aktivierungs-Reihenfolge (Pflicht)

**WICHTIG:** Reihenfolge zwingend. Falsche Reihenfolge → Lockout → Rescue-Mode (§3). **Immer mit `at`-Watchdog** aus 8.2 arbeiten, sobald der `ufw --force enable`-Schritt beteiligt ist.

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0           # 1. Tailscale zuerst
ufw allow 22/tcp                     # 2. SSH-Fallback (Entscheidung B)
ufw allow 80/tcp                     # 3. Caddy HTTP
ufw allow 443/tcp                    # 4. Caddy HTTPS
ufw --force enable                   # 5. Aktivieren
ufw status verbose                   # Kontrolle
```

### 8.2 `at`-Watchdog bei UFW-Enable über Remote-SSH

Vor jedem `ufw --force enable` setzen. Bei Fehlkonfiguration wird UFW nach 5 Min automatisch deaktiviert, bevor die Session hängen bleibt.

```bash
# Watchdog setzen
echo 'ufw --force disable' | at now + 5 minutes
atq                                  # Kontrolle: Job-ID registriert

# … UFW-Regeln setzen + enable …

# Watchdog wieder entfernen nach erfolgreicher Verifikation
for j in $(atq | awk '{print $1}'); do atrm $j; done
atq                                  # sollte leer sein
```

Falls UFW zwischendurch hängt und der Watchdog zuschlägt: Verbindung bleibt, UFW ist dann `inactive`. Regeln prüfen, korrigieren, neuen Watchdog setzen, erneut aktivieren.

### 8.3 Verifikation nach Enable

```powershell
# 1. SSH via Tailscale (Primär-Pfad)
ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-main "uptime"

# 2. Caddy HTTPS öffentlich erreichbar
(Invoke-WebRequest https://heizung.<domain>/ -Method Head -UseBasicParsing).StatusCode   # erwartet 200

# 3. Port 22 public (Fallback-Zugang)
Test-NetConnection <public-ip> -Port 22   # erwartet TcpTestSucceeded = True
```

### 8.4 Rein additive Änderungen (ohne Watchdog)

Für `ufw allow …`-Ergänzungen oder `ufw delete …` an **bereits aktiven** Regelwerken ohne `enable`-Toggle ist **kein** Watchdog nötig — kein Cutoff-Risiko:

```bash
ufw allow in on tailscale0           # Beispiel: fehlende Regel nachziehen
ufw status verbose
```

### 8.5 SSH-Key-Pfad-Hinweis

Der Default-Key `~/.ssh/id_ed25519` funktioniert **nicht** mit den Heizungs-Servern. Immer explizit `-i $HOME\.ssh\id_ed25519_heizung` angeben (oder `~/.ssh/config`-Eintrag setzen).

---

## 9. DNS-Umschaltung auf echte Domain

Wenn externer IT die DNS-Records gesetzt hat:

- Test: `test.heizung.hotel-sonnblick.at` → `157.90.17.150`
- Main: `heizung.hotel-sonnblick.at` → `157.90.30.116`

Auf beiden Servern:

```bash
cd /opt/heizung-sonnblick/infra/deploy
# .env bearbeiten: PUBLIC_HOSTNAME=test.heizung.hotel-sonnblick.at (bzw. heizung...)
nano .env
docker compose up -d caddy
docker compose logs -f caddy         # auf „certificate obtained" warten
```

Caddy holt automatisch Let's Encrypt-Zertifikat via HTTP-01.

---

## 10. Notfall-Links

- Hetzner Cloud Console: https://console.hetzner.cloud
- Tailscale Admin: https://login.tailscale.com/admin/machines
- GitHub Repo: https://github.com/rexei123/heizung-sonnblick
- GHCR Packages: https://github.com/rexei123?tab=packages

**SSH-Key Pfad lokal:** `$HOME\.ssh\id_ed25519_heizung`

---

## Anhang: Lessons Learned 2026-04-20

- Hetzner Web Console (noVNC) hat US-Keyboard-Mapping → `|`, `:`, `"` werden zerlegt. Nur für kurze Single-Word-Commands nutzen.
- Hetzner Cloud Firewall ist für diesen Accoun