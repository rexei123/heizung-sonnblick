# RUNBOOK — Heizungssteuerung Hotel Sonnblick

Operations-Handbuch für Test- und Main-Server. Stand: 2026-04-28.

**Regel Nr. 1:** Bei Rescue-Einsatz IMMER den kompletten Fix-Block aus §3 in einem Shot ausführen. Niemals inkrementell fixen.

---

## 1. Server-Übersicht

| Rolle | Hetzner | Public-IP / Hostname | Tailscale | GHCR-Tag | Branch |
|---|---|---|---|---|---|
| Test | CPX22 | `157.90.17.150` / `heizung-test.hoteltec.at` | `heizung-test` = `100.82.226.57` | `develop` | `develop` |
| Main | CPX32 | `157.90.30.116` / `heizung.hoteltec.at` | `heizung-main` = `100.82.254.20` | `main` | `main` |
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

### 5.6 Deploy-Pull-Skript: Phasen + Sync-Branch

Seit Sprint 6.6.2 macht `infra/deploy/deploy-pull.sh` drei Phasen:

1. **Working-Tree-Sync** — `git fetch + checkout + reset --hard` auf den passenden Branch (Mapping: `STAGE=test → develop`, `STAGE=main → main`, override via `DEPLOY_BRANCH` in `.env`). Holt damit Compose-, Caddy-, Mosquitto- und ChirpStack-Konfig vom Repo.
2. **Image-Pull** — `docker compose pull api web` aus GHCR.
3. **Container-Up** — `docker compose up -d --remove-orphans` ohne `--no-deps`. Recreate erfolgt nur bei Config- oder Image-Drift, sonst keine Down-Time.

**Sicherheitsnetz:** Lokale Aenderungen am tracked Content (z.B. Hand-Hotfix per `vim` auf Server) brechen das Skript ab — kein silentes `reset --hard`. Untracked Files (`.env`) sind ok.

**Wichtig fuer Hand-Hotfixes:** Wenn Sie auf einem Server temporaer am Working-Tree etwas anpassen muessen, danach `git stash` ODER systemd-Timer disablen, sonst macht der naechste Pull-Run einen Deploy-Abbruch und schickt die fehlende Aenderung nie aus.

```bash
# Hotfix-Workflow (Notfall)
sudo systemctl stop heizung-deploy-pull.timer
# ... Aenderung am Working-Tree ...
# Spaeter: Aenderung in Repo bringen, dann
sudo systemctl start heizung-deploy-pull.timer
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

## 9. Domain & DNS (hoteltec.at)

**Stand 2026-04-22 (Sprint 4):** Produktiv unter `hoteltec.at`, LE-Zertifikate laufen.

| Rolle | Hostname | IP |
|---|---|---|
| Main | `heizung.hoteltec.at` | `157.90.30.116` |
| Test | `heizung-test.hoteltec.at` | `157.90.17.150` |

**DNS-Hosting:** Hetzner Online / konsoleH (NICHT Hetzner Cloud DNS).
Admin-Konsole: https://console.hetzner.com/ → Domain `hoteltec.at` → DNS-Records.
Nameserver: `ns1.your-server.de`, `ns.second-ns.com`, `ns3.second-ns.de`.

A-Records (TTL 300):

| Name | Wert |
|---|---|
| `heizung` | `157.90.30.116` |
| `heizung-test` | `157.90.17.150` |

### 9.1 Neue Subdomain hinzufügen / Server umschalten

1. **DNS setzen** in konsoleH (Link oben), A-Record anlegen, TTL 300.
2. **Propagation verifizieren** (lokal):
   ```powershell
   nslookup neue-subdomain.hoteltec.at
   ```
   Erst wenn die richtige IP kommt, weiter — sonst Let's-Encrypt-Rate-Limit-Risiko.
3. **Port 80 offen?** (für ACME HTTP-01):
   ```bash
   ufw status | grep 80
   ```
4. **`.env` auf dem Server anpassen:**
   ```bash
   cd /opt/heizung-sonnblick/infra/deploy
   nano .env                          # PUBLIC_HOSTNAME=...
   docker compose -f docker-compose.prod.yml up -d caddy
   docker compose -f docker-compose.prod.yml logs -f caddy
   ```
   Warten auf `certificate obtained successfully` (typisch 10–30 Sek).
5. **Verifikation (lokal):**
   ```powershell
   (Invoke-WebRequest https://neue-subdomain.hoteltec.at/ -Method Head -UseBasicParsing).StatusCode
   # erwartet 200
   ```

### 9.2 Rollback bei Cert-Fehler

```bash
cd /opt/heizung-sonnblick/infra/deploy
# .env: alten PUBLIC_HOSTNAME wiederherstellen
nano .env
docker compose -f docker-compose.prod.yml up -d caddy
```

Das `caddy_data`-Volume ist persistent — das alte Zertifikat wird reused, kein erneuter ACME-Call nötig.

### 9.3 Frontend-API-Aufrufe

Frontend ruft **immer relativ** (`/api/...`), nie absolut. Grund: `NEXT_PUBLIC_*`-Env-Vars werden zur Build-Zeit in den Client-Bundle gebacken — ein Hostname-Wechsel würde sonst einen Rebuild erfordern. Caddy routet `/api/*` intern an den FastAPI-Container.

### 9.4 Let's-Encrypt-Rate-Limits (Merkposten)

- 5 fehlgeschlagene Validierungen/h pro Account
- 50 Certs/Woche pro eTLD+1 (hier `hoteltec.at`)

Bei wiederholten Versuchen ohne propagiertes DNS → rate-limited. Deshalb: **immer erst `nslookup`, dann Caddy starten.**

---

## 10. LoRaWAN-Pipeline (lokale Entwicklung)

**Stand 2026-04-28 (Sprint 5):** ChirpStack v4 + Mosquitto + FastAPI-MQTT-Subscriber lauffaehig auf `work02`. Test-/Main-Server haben den Stack noch NICHT - das ist Sprint 6 zusammen mit Hotel-LAN + echter Hardware.

### 10.1 Stack-Topologie lokal

```
[mosquitto_pub / Mock-Uplink]
          |
          v MQTT (127.0.0.1:1883, anonymous)
[mosquitto] ---- [chirpstack v4] -- [chirpstack-postgres]
          |            |
          |            +-- Web-UI: http://localhost:8080  (admin/admin)
          |
          v Subscribe application/+/device/+/event/up
[FastAPI api] -- aiomqtt -- _persist_uplink() -- INSERT sensor_reading
          |
          v REST: GET /api/v1/devices/{id}/sensor-readings
```

### 10.2 Stack hochfahren (Erstinstallation)

```powershell
cd C:\Users\User\dev\heizung-sonnblick
cp .env.example .env   # Falls noch nicht vorhanden
# Mosquitto-Auth ist lokal anonymous; .env-Variablen MQTT_*_PASSWORD koennen leer bleiben.
docker compose up -d
# Nach ~30 Sek alle Services ready
docker compose ps
```

ChirpStack-Initialisierung (einmalig, in der Web-UI):
- Tenant „Hotel Sonnblick" (Default umbenennen oder neu)
- Application „heizung"
- DeviceProfile „MClimate Vicki" mit Codec aus `infra/chirpstack/codecs/mclimate-vicki.js`
- Gateway + Device anlegen, Application Key vergeben

(Wiederholbar: Bootstrap-Skript noch nicht implementiert - Sprint 6 oder spaeter.)

### 10.3 Mock-Uplink senden (Pipeline testen)

```powershell
docker run --rm --network heizung-sonnblick_default -v "${PWD}/infra/chirpstack/test-uplinks:/data:ro" eclipse-mosquitto:2 mosquitto_pub -h mosquitto -p 1883 -t "application/<app-id>/device/<dev-eui>/event/up" -f /data/vicki-status-001.json
```

Verifikation:
```powershell
docker compose exec db psql -U heizung -d heizung -c "SELECT time, device_id, fcnt, temperature, setpoint FROM sensor_reading ORDER BY time DESC LIMIT 5;"
(Invoke-WebRequest -UseBasicParsing http://localhost:8000/api/v1/devices/1/sensor-readings).Content
```

### 10.4 MQTT live mitlauschen

```powershell
docker compose exec mosquitto mosquitto_sub -h localhost -p 1883 -t 'application/#' -v
```

### 10.5 Subscriber-Logs

```powershell
docker compose logs -f api | Select-String -Pattern "uplink|MQTT"
```

### 10.6 Troubleshooting

- **„relation 'user' does not exist" beim ChirpStack-Login:** `pg_trgm`-Extension fehlt. Fix:
  ```powershell
  docker compose exec chirpstack-postgres psql -U chirpstack -d chirpstack -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
  docker compose exec chirpstack-postgres psql -U chirpstack -d chirpstack -c "DROP TABLE IF EXISTS __diesel_schema_migrations;"
  docker compose restart chirpstack
  ```
  Bei frischer Installation greift jetzt `infra/chirpstack/postgres-init/01-extensions.sql` automatisch.
- **Mosquitto „Unable to open pwfile":** auf Windows-Bind-Mount sind die Permissions fuer Container-User `mosquitto` unzugaenglich. Dev-Loesung: `allow_anonymous true` in `infra/mosquitto/config/mosquitto.conf` (bereits aktiv).
- **„exec docker-entrypoint.sh: no such file":** Linenden im Backend-Entrypoint sind CRLF. Fix:
  ```powershell
  docker compose run --rm api sed -i 's/\r$//' /app/docker-entrypoint.sh
  ```
  Plus: nicht mit Editoren bearbeiten, die die `.gitattributes`-Regel ignorieren.
- **API-Routes erscheinen nach Code-Aenderung nicht:** Image wurde mit `pip install .` (non-editable) gebaut, Code-Mount greift nicht. Seit Sprint 5 ist Dockerfile auf `pip install -e ".[dev]"` umgestellt → `docker compose restart api` reicht.

### 10.7 Pipeline auf Test-/Main-Server (Sprint 6, geplant)

- `docker-compose.prod.yml` um `mosquitto`, `chirpstack-postgres`, `chirpstack` erweitern
- ACL + Passwd-File aktiv (Linux-Bind-Mount = keine Permission-Pannen)
- Mosquitto/ChirpStack NUR via Tailscale-Interface erreichbar (kein Public-Listener)
- Caddy-Routing fuer ChirpStack-UI nur intern oder als separate Subdomain mit Basic-Auth

---

## 11. Notfall-Links

- Hetzner Cloud Console: https://console.hetzner.cloud
- Tailscale Admin: https://login.tailscale.com/admin/machines
- GitHub Repo: https://github.com/rexei123/heizung-sonnblick
- GHCR Packages: https://github.com/rexei123?tab=packages

**SSH-Key Pfad lokal:** `$HOME\.ssh\id_ed25519_heizung`

---

## Anhang: Lessons Learned 2026-04-20

- Hetzner Web Console (noVNC) hat US-Keyboard-Mapping → `|`, `:`, `"` werden zerlegt. Nur für kurze Single-Word-Commands nutzen.
- Hetzner Cloud Firewall ist für diesen Accoun