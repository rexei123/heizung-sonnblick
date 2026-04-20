# RUNBOOK — Heizungssteuerung Hotel Sonnblick

Operations-Handbuch für Test- und Main-Server. Stand: 2026-04-20.

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

## 6. Git auf Server (HTTPS + PAT)

Remote-URL-Format (verbindlich, KEINE SSH Deploy Keys):

```bash
cd /opt/heizung-sonnblick
git config --global --add safe.directory /opt/heizung-sonnblick
git remote set-url origin https://<PAT>@github.com/rexei123/heizung-sonnblick.git
git fetch origin
git reset --hard origin/main   # bzw. origin/develop auf Test
```

### 6.1 PAT rotieren

1. Alten PAT auf GitHub widerrufen
2. Neuen PAT mit Scope `repo` generieren
3. Auf beiden Servern die `set-url`-Zeile oben mit neuem PAT laufen lassen
4. Auch in `/opt/heizung-sonnblick/infra/deploy/.env` aktualisieren (falls eingetragen für GHCR-Login)

---

## 7. Tailscale-Reconnect

```bash
tailscale status
tailscale up --ssh --accept-routes   # falls down
tailscale ip -4                      # zeigt eigene IP
```

MagicDNS ist aktiv — Hostnames `heizung-test`, `heizung-main`, `work02` sind direkt auflösbar.

---

## 8. UFW-Hardening (Pflicht-Reihenfolge)

**WICHTIG:** Reihenfolge zwingend. Falsche Reihenfolge → Lockout → Rescue.

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0           # 1. Tailscale zuerst
ufw allow 80/tcp                     # 2. Caddy HTTP
ufw allow 443/tcp                    # 3. Caddy HTTPS
# Port 22 bewusst NICHT öffentlich — SSH nur über Tailscale
ufw --force enable                   # 4. Aktivieren
ufw status verbose                   # Kontrolle
```

Falls SSH über Public-IP als Fallback behalten werden soll: zusätzlich `ufw allow 22/tcp` VOR `ufw enable`.

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
- Hetzner Cloud Firewall ist für diesen Account NICHT konfiguriert — Blockaden kommen server-seitig (UFW).
- Rescue-Modus ist nach einem Reboot verbraucht, Server bootet normal zurück.
- `ssh-heizung`-Key in Hetzner gilt sowohl für Rescue-Auth als auch produktiven SSH-Zugang.
