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

## 10a. MQTT-Auth-Setup (Sprint 6.6.4, ab 2026-04-30)

Mosquitto laeuft seit Sprint 6.6.4 mit `allow_anonymous false`, `password_file` und `acl_file`. Drei User: `chirpstack`, `gateway-ug65`, `heizung-api`.

### 10a.1 Erst-Setup pro Server

```bash
# 1. .env aktualisieren (drei Passwoerter, jeweils mind. 32 Zeichen)
cd /opt/heizung-sonnblick
sudo openssl rand -hex 32     # Wert in MQTT_CHIRPSTACK_PASSWORD eintragen
sudo openssl rand -hex 32     # Wert in MQTT_GATEWAY_UG65_PASSWORD eintragen
sudo openssl rand -hex 32     # Wert in MQTT_HEIZUNG_PASSWORD eintragen
sudo nano infra/deploy/.env

# 2. passwd-Datei erzeugen (.env muss vorher gesetzt sein)
set -a; . infra/deploy/.env; set +a
sudo touch infra/mosquitto/config/passwd
sudo docker run --rm -v "$PWD/infra/mosquitto/config:/conf" \
  eclipse-mosquitto:2 \
  mosquitto_passwd -b /conf/passwd chirpstack "$MQTT_CHIRPSTACK_PASSWORD"
sudo docker run --rm -v "$PWD/infra/mosquitto/config:/conf" \
  eclipse-mosquitto:2 \
  mosquitto_passwd -b /conf/passwd gateway-ug65 "$MQTT_GATEWAY_UG65_PASSWORD"
sudo docker run --rm -v "$PWD/infra/mosquitto/config:/conf" \
  eclipse-mosquitto:2 \
  mosquitto_passwd -b /conf/passwd heizung-api "$MQTT_HEIZUNG_PASSWORD"

# 3. Datei-Permissions: nur root + mosquitto-User darf lesen
sudo chmod 0640 infra/mosquitto/config/passwd

# 4. Mosquitto + abhaengige Container neu starten
sudo docker compose -f infra/deploy/docker-compose.prod.yml up -d --force-recreate \
  mosquitto chirpstack chirpstack-gateway-bridge api

# 5. Verifikation: Auth aktiv?
sudo docker compose -f infra/deploy/docker-compose.prod.yml logs mosquitto --tail 20 | grep -i auth
# Erwartung: keine "anonymous client" Eintraege
sudo docker exec deploy-mosquitto-1 \
  mosquitto_sub -h 127.0.0.1 -p 1883 -t '$SYS/#' -C 1 -W 3
# Erwartung: Connection Refused (kein User+Pass) -> Auth funktioniert
sudo docker exec deploy-mosquitto-1 \
  mosquitto_sub -h 127.0.0.1 -p 1883 -u heizung-api -P "$MQTT_HEIZUNG_PASSWORD" -t '$SYS/#' -C 1 -W 3
# Erwartung: ein $SYS-Topic-Wert
```

### 10a.2 UG65-Reconfigure

UG65 Web-UI (LAN-IP) -> Application -> Packet Forwarder -> ID 1 -> Edit:

- User Credentials: **ON**
- Username: `gateway-ug65`
- Password: <Wert aus `MQTT_GATEWAY_UG65_PASSWORD`>
- Save -> System -> Reboot

Verifikation: nach UG65-Reboot in der Mosquitto-Console:
```bash
sudo docker exec deploy-mosquitto-1 \
  mosquitto_sub -h 127.0.0.1 -p 1883 -u heizung-api -P "$MQTT_HEIZUNG_PASSWORD" \
  -t 'eu868/gateway/+/event/stats' -C 1 -W 60
```

### 10a.3 ChirpStack-Pruefung

ChirpStack-UI -> Tenants -> Hotel Sonnblick -> Gateways: UG65 muss als "online" angezeigt werden, "Last seen" < 30 s.

### 10a.4 Rollback

Falls Auth-Setup einen Container blockiert: temporaer auf alte anonymous-Konfig zurueck:

```bash
sudo nano infra/deploy/docker-compose.prod.yml
# Zeile entfernen: command: mosquitto -c /mosquitto/config/mosquitto.prod.conf
sudo docker compose -f infra/deploy/docker-compose.prod.yml up -d --force-recreate mosquitto
```

Zurueck-Schalten ohne Skript-Lauf: einmalig manuell. Nicht committen — der naechste deploy-pull bringt die Auth-Konfig zurueck.

---

## 10b. Basic-Auth fuer Heizung-API (Sprint 8a, K-1)

Seit Sprint 8a sind `/api/*`, `/openapi.json`, `/docs` und `/redoc` auf `heizung.hoteltec.at` und `heizung-test.hoteltec.at` per HTTP-Basic-Auth geschuetzt. **Ein** Hotel-User: `hotel`. `/health` (Backend-Liveness) und `/healthz` (Frontend) bleiben public fuer Uptime-Monitoring.

Browser cached Credentials nach erstem Login. TanStack-Query-Calls vom Frontend funktionieren ohne Code-Aenderung weil der Browser den `Authorization`-Header automatisch dranhaengt.

### 10b.1 Hash erzeugen + .env setzen

```bash
# bcrypt-Hash erzeugen
docker run --rm caddy:2 caddy hash-password --plaintext "<starkes-passwort>"
# Output sieht so aus: $2a$14$xxxxxxxxxxxxxxxxxxxxxx...

# In .env eintragen — JEDES $ verdoppeln (Compose-Interpolation):
# HOTEL_BASIC_AUTH_HASH=$$2a$$14$$xxxxxxxxxxxxxxxxxxxxxx...
sudo nano /opt/heizung-sonnblick/infra/deploy/.env
```

### 10b.2 Caddy neu starten

```bash
cd /opt/heizung-sonnblick
sudo docker compose -f infra/deploy/docker-compose.prod.yml up -d --force-recreate caddy
sudo docker compose -f infra/deploy/docker-compose.prod.yml logs caddy --tail 10
```

### 10b.3 Verifikation

```bash
# Ohne Auth: 401
curl -I https://heizung-test.hoteltec.at/api/v1/devices
# HTTP/2 401

# Mit Auth: 200
curl -u hotel:<starkes-passwort> https://heizung-test.hoteltec.at/api/v1/devices

# /health bleibt public
curl https://heizung-test.hoteltec.at/health
# {"status":"ok",...}
```

### 10b.4 Limitierung (Sprint 9-Backlog)

Single-User, kein Logout, kein Audit-Trail. Browser-Native-Auth-Dialog ist UX-maessig nicht ideal. Sprint 9 oder spaeter: echte Session-Auth (NextAuth oder FastAPI-Users) mit User-Tabelle + Login-Form + Logout + Audit-Log.

### 10b.5 Passwort-Rotation

```bash
# 1. Neues Hash erzeugen + in .env eintragen (siehe 10b.1)
# 2. Caddy neu starten (siehe 10b.2)
# 3. Browser-Cache loeschen (sonst nimmt der das alte Passwort)
```

---

## 10c. Codec-Deploy auf ChirpStack (Sprint 9.10c)

**Hintergrund.** Repo-Codec (`infra/chirpstack/codecs/mclimate-vicki.js`) ist Source of Truth, ChirpStack zieht ihn aber nicht selbst. Jeder Repo-Codec-Touch erfordert anschliessend einen manuellen Re-Paste in der ChirpStack-UI je Server. Siehe CLAUDE.md §5.22.

**Zielserver:** `heizung-test` zuerst, `heizung-main` nachgezogen, sobald Production-Migration ansteht.

### 10c.1 UI-Re-Paste

1. Browser → `https://heizung-test.hoteltec.at/chirpstack/`
2. Login mit dem ChirpStack-Admin-User (separat von der Heizung-API).
3. **Tenants → Hotel Sonnblick → Device Profiles → Heizung**.
4. Tab **Codec** öffnen.
5. Bestehenden JS-Code komplett markieren und löschen.
6. Inhalt von `infra/chirpstack/codecs/mclimate-vicki.js` (aktueller Repo-Stand auf `develop` bzw. dem zu deployenden Branch) einfügen.
7. **Update Device Profile** klicken.

Kein Container-Restart nötig — ChirpStack lädt Codec-Änderungen für jedes neue Event neu.

### 10c.2 Verifikation

Nach 1–2 Minuten muss ein neues Vicki-Event mit dem geänderten Codec laufen:

1. Im ChirpStack-UI: **Devices → Vicki-001 → LoRaWAN frames** (oder Events) → letztes Event aufklappen.
2. Decoded-`object`-Block muss die geänderten/neuen Felder enthalten. Beispiel-Erwartung nach Sprint 9.10c (Cmd-Byte-Routing):
   ```
   { "report_type": "periodic",
     "command": 129,
     "temperature": 22.71,
     "target_temperature": 18,
     "valve_openness": 0,
     "battery_voltage": 3.4,
     "openWindow": false, ... }
   ```
   (vorher: `{ "command": 129, "report_type": "unknown_reply" }` ohne Sensor-Felder.)

3. Subscriber-Side per SSH gegenchecken:
   ```bash
   # SSH (heizung-test, root)
   docker logs deploy-api-1 --since 5m 2>&1 | grep "uplink persistiert" | tail -5
   ```
   Erwartung: Log-Zeilen mit `temp=...` und `setpoint=...`, NICHT `temp=None`.

### 10c.3 Backlog: Bootstrap-Skript

UI-Re-Paste je Server ist fehleranfällig (Copy-Paste-Verlust, ungetesteter Stand). Eigener Hygiene-Sprint via ChirpStack gRPC-API (`UpdateDeviceProfile`-RPC mit `payload_codec_script`-Feld) macht Repo → ChirpStack reproduzierbar. Siehe STATUS.md §6 Backlog-Eintrag „ChirpStack-Codec-Bootstrap-Skript".

**Production-Hinweis:** Sobald heizung-main Live-Vickis bekommt, muss dieser Codec-Deploy-Schritt dort wiederholt werden. Backlog: B-9.10c-2.

---

## 10d. Geräte-Zuordnung via API (Sprint 9.11a)

Vicki-Thermostate werden produktiv via REST-API einer Heizzone
zugewiesen. Bis zur UI-Pairing-Lösung in Sprint 9.13 ist dies der
einzige unterstützte Weg. Direkter DB-Edit ist NICHT mehr nötig.

### 10d.1 Voraussetzungen

- Device existiert (via ChirpStack-Pairing aus §10) und ist in der
  `device`-Tabelle persistiert.
- Heizzone existiert (`heating_zone`-Tabelle, ID via UI oder
  `GET /api/v1/rooms/{room_id}/heating-zones`).
- Basic-Auth-Credentials für heizung-test (siehe §10b).

### 10d.2 Gerät einer Heizzone zuweisen

```bash
curl -X PUT \
  -u "<user>:<pass>" \
  -H "Content-Type: application/json" \
  -d '{"heating_zone_id": 42}' \
  https://heizung-test.hoteltec.at/api/v1/devices/2/heating-zone
```

Erwartete Response (200):

```json
{
  "device_id": 2,
  "dev_eui": "70b3d52dd3034de4",
  "heating_zone_id": 42,
  "label": "Vicki-002",
  "updated_at": "2026-05-08T14:23:11.482Z"
}
```

### 10d.3 Re-Assign (Hardware-Tausch)

Identisch zu §10d.2 — die API behandelt Re-Assign idempotent. Der
neue Wert überschreibt den alten ohne 409-Konflikt.

### 10d.4 Gerät von Heizzone trennen (Detach)

```bash
curl -X DELETE \
  -u "<user>:<pass>" \
  https://heizung-test.hoteltec.at/api/v1/devices/2/heating-zone
```

Response (200): `heating_zone_id` ist `null`.

### 10d.5 Verifikation via DB

```bash
docker exec -it deploy-db-1 psql -U heizung -d heizung -c \
  "SELECT id, dev_eui, label, heating_zone_id FROM device ORDER BY id;"
```

Erwartet nach Sprint 9.11a Live-Setup: alle 4 Vickis mit
`heating_zone_id IS NOT NULL`.

### 10d.6 Fehlerbilder

| HTTP | Detail | Bedeutung |
|---|---|---|
| 404 | `device_not_found` | Device-ID existiert nicht |
| 404 | `heating_zone_not_found` | Zone-ID existiert nicht |
| 422 | Pydantic-Default | Body fehlt, `heating_zone_id <= 0`, oder Extra-Feld |

### 10d.7 Verwandte API-Endpunkte (Sprint 9.11 verifiziert)

#### Manual-Override anlegen

```bash
curl -u "<user>:<pass>" -X POST -H "Content-Type: application/json" \
  -d '{"setpoint": "23", "source": "frontend_4h", "reason": "Test"}' \
  https://heizung-test.hoteltec.at/api/v1/rooms/{room_id}/overrides
```

Erlaubte `source`-Werte:

- `device` — vom System bei Auto-Detect (siehe AE-45) — manuell nicht setzen
- `frontend_4h` — Standard-Frontend-Override, 4 h Gültigkeit
- `frontend_midnight` — gültig bis 00:00
- `frontend_checkout` — gültig bis Check-out der aktiven Belegung

`setpoint` muss ganzzahlig sein (Vicki-Hardware-Constraint, Dezimalstellen werden mit 400 abgelehnt).

#### Manual-Override revoken

```bash
curl -u "<user>:<pass>" -X DELETE \
  https://heizung-test.hoteltec.at/api/v1/overrides/{override_id}
```

#### Belegung anlegen

```bash
curl -u "<user>:<pass>" -X POST -H "Content-Type: application/json" \
  -d '{"room_id": 2, "check_in": "2026-05-09T06:00:00Z", "check_out": "2026-05-11T11:00:00Z", "source": "manual"}' \
  https://heizung-test.hoteltec.at/api/v1/occupancies
```

#### Belegung stornieren

DELETE ist nicht erlaubt. Stornierung via PATCH:

```bash
curl -u "<user>:<pass>" -X PATCH -H "Content-Type: application/json" \
  -d '{"cancel": true}' \
  https://heizung-test.hoteltec.at/api/v1/occupancies/{id}
```

Begründung: Belegungen sind audit- und PMS-Sync-relevant, dürfen nicht gelöscht werden.

---

## 10e. Vicki-Konfiguration via Downlink (Sprint 9.11x.b)

**Status:** Implementiert ab Sprint 9.11x.b (mergeCommit folgt).
**Bezug:** AE-48 (Downlink-Helper-Architektur), AE-47 (Window-Detection-Hybrid),
Vendor-Doku `docs/vendor/mclimate-vicki/`.

Drei Konfigurations-Downlinks via MQTT-Pfad (`downlink_adapter.py`,
`aiomqtt`, fPort=1, `confirmed=False`). Vicki antwortet asynchron mit
dem nächsten Keepalive (~10 Min Periodic-Cycle) — kein blockierendes
Warten im Helper.

### 10e.1 Vendor-Byte-Layouts

| Command | Bytes | Antwort | Subscriber-Handler |
|---|---|---|---|
| FW-Query | `0x04` | `0x04 {HW_maj} {HW_min} {FW_maj} {FW_min}` (5 Bytes) | `_handle_firmware_version_report` → `device.firmware_version` |
| OW-Set (FW≥4.2) | `0x45 {enable} {duration_min/5} {delta_c×10}` | (kein expliziter Reply, nur GET-Verify) | — |
| OW-Get | `0x46` | `0x46 {enabled} {duration_byte} {delta_byte}` (4 Bytes) | `_handle_open_window_status_report` → `journalctl` |

**Vendor-Beispiele** (aus `docs/vendor/mclimate-vicki/04-commands-cheat-sheet.md`):

- `0x4501020F` — enable, `0x02 × 5 = 10` Min, `0x0F / 10 = 1.5 °C` Delta
- `0x4501060D` — enable, `0x06 × 5 = 30` Min, `0x0D / 10 = 1.3 °C` Delta
- `0x4501020A` — enable, 10 Min, 1.0 °C (aggressive Variante, mehr Falsch-Positive)

### 10e.2 Bulk-Aktivierung der 4 Hotel-Vickis

**SSH (heizung-test, root):**

```bash
docker exec deploy-api-1 python scripts/activate_open_window_detection.py
# Empfohlen für realistische Wartezeit (4 Vickis × 10 Min Periodic):
docker exec deploy-api-1 python scripts/activate_open_window_detection.py --wait-secs 600
```

3-Phasen-Logik:

1. **Phase 1**: `0x04` an alle Devices mit `kind=thermostat AND heating_zone_id IS NOT NULL` (sequentiell, 0.5 s Pause).
2. **Wait**: `--wait-secs N` (default 60). Vickis antworten beim
   nächsten Periodic-Report. Default 60 ist best-effort — bei 4 Vickis
   mit 10-Min-Cycle realistisch nur 0-1 Antworten. Empfohlen: 600-1200.
3. **Phase 3**: pro Device `device.firmware_version` aus DB lesen,
   parsen (`"4.5"` → `(4, 5)`), Vergleich gegen `(4, 2)`:
   - **FW ≥ 4.2**: `0x45` (mit Vendor-Defaults `enabled=True, 10 Min, 1.5 °C`) + `0x46` senden.
   - **FW < 4.2**: skip + Hinweis auf B-9.11x.b-2 (0x06-Fallback).
   - **FW NULL**: skip + Hinweis "Vicki hat nicht geantwortet".

**Erwarteter Tabellen-Output** (Phase 4):

```
=== Ergebnis ===
  dev_eui          | label    | fw_version | action          | result
  -----------------+----------+------------+-----------------+----------------------------------
  70b3d52dd3034de4 | Vicki-001| 4.5        | 0x45+0x46 sent  | verify-pending (siehe journalctl)
  70b3d52dd3034dxx | Vicki-002| 4.5        | 0x45+0x46 sent  | verify-pending (siehe journalctl)
  70b3d52dd3034dyy | Vicki-003| (NULL)     | skip            | no FW (Vicki hat nicht geantwortet)
  70b3d52dd3034dzz | Vicki-004| 4.1        | skip            | FW<4.2 (B-9.11x.b-2: 0x06-Fallback)

Total: 4  aktiviert: 2  geskippt: 2  fehlgeschlagen: 0
```

Exit-Code 0 (kein Failure), 1 (mind. ein Failure).

### 10e.3 Failure-Patterns

| Symptom | Ursache | Fix |
|---|---|---|
| Alle Devices `fw_version=(NULL)` nach Phase 3 | `--wait-secs` zu kurz, Vickis hatten noch keinen Periodic-Cycle | Re-Run mit `--wait-secs 1200` |
| Exception in Phase 3 | MQTT-Connect-Fehler oder ChirpStack down | `docker compose ps` + `journalctl -u deploy-api` |
| `device.firmware_version` bleibt NULL trotz Wait | Codec emittiert `firmware_version` nicht (alter Codec-Stand) | RUNBOOK §10c Codec-Re-Paste |
| Validation-Error `duration_min muss 5..1275 in 5-Min-Schritten sein` | Aufrufer-Bug: nicht-durch-5-teilbar | Wert korrigieren (Skript hat Defaults, sonst CLI prüfen) |
| Validation-Error `delta_c muss Decimal sein, ist float` | Aufrufer-Bug: Float statt Decimal | `Decimal("1.5")` statt `1.5` |

### 10e.4 ROUND_HALF_UP-Charakteristik (delta_c-Encoding)

Backend-Encoder `_encode_ow_set_payload` rundet `delta_c` mit
`Decimal.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)` auf
0.1 °C — **NICHT** Banker's Rounding. Tests in
`backend/tests/test_downlink_adapter.py::test_ow_set_delta_c_round_half_up_matrix`
verriegeln das Verhalten:

| `delta_c` Input | `delta_byte` (hex) | Hardware-Wirkung |
|---|---|---|
| `Decimal("1.0")` | `0x0A` (10) | 1.0 °C |
| `Decimal("1.5")` | `0x0F` (15) | 1.5 °C |
| `Decimal("1.54")` | `0x0F` (15) | 1.5 °C (quantize abrunden) |
| `Decimal("1.55")` | `0x10` (16) | 1.6 °C (Half-Up, NICHT 1.5!) |
| `Decimal("1.56")` | `0x10` (16) | 1.6 °C |
| `Decimal("2.0")` | `0x14` (20) | 2.0 °C |

Codec-Spiegel (`mclimate-vicki.js encodeDownlink`) nutzt JS
`Math.round(deltaC * 10)` — verhalten-gleich für positive Floats
(was hier alles ist, da `delta_c ∈ [0.1, 6.4]`). Spiegel-Test
`backend/tests/test_codec_mirror.py` verriegelt Vendor-Bytes.

### 10e.5 FW < 4.2 Fallback (Backlog B-9.11x.b-2)

Vendor unterstützt für FW < 4.2 die alte 1.0 °C-Variante:
**Command** `0x06 {enable} {duration_min/5} {motor_pos+delta}` — eigene
Encoder-Funktion, eigene Payload-Struktur (5 Bytes statt 4). In
9.11x.b NICHT implementiert. Bulk-Skript skipped Devices mit FW<4.2
und gibt einen Hinweis im Output. Bei Bedarf manuell:

**SSH (heizung-test, root):**

```bash
# Beispiel: enable, 20 Min, motor-pos 540, delta 3.0 °C
docker exec deploy-api-1 python -c "
import asyncio, base64
from heizung.services.downlink_adapter import send_raw_downlink
asyncio.run(send_raw_downlink(
    'aabbccdd11223344',
    bytes([0x06, 0x01, 0x04, 0x1C, 0x23]),
))
"
```

(`0x0601041C23` aus Vendor-Cheat-Sheet, FW < 4.2.)

### 10e.6 Hardware-Kältepack-Test (T1 aus Sprint 9.11)

Verifiziert Vicki-Open-Window-Algorithmus physikalisch — nur sinnvoll
nach erfolgreicher 0x45-Aktivierung und außerhalb der Heizperiode
(im Sommer ist der Δ-T sonst zu klein).

**Vor Ort am Vicki:**

1. Vicki demontieren oder im Raum nahe Sensor positionieren.
2. **Kältepack** (z.B. Tiefkühlfach 5+ Min) direkt an die Vicki-Front
   halten (interner Sensor sitzt im Display-Bereich).
3. 1-2 Min Kontakt halten — interner Sensor soll von ~18 °C auf
   ~4 °C fallen.
4. Vicki sollte innerhalb 60-120 s `openWindow=true` melden (via
   nächstem Periodic-Report sichtbar).
5. Nach Test: Kältepack entfernen, 5 Min warten, dann sollte
   `openWindow=false` zurückkommen.

**SSH (heizung-test, root):** Live-Beobachtung:

```bash
docker exec heizung-postgres psql -U heizung -d heizung -c \
  "SELECT time, temperature, open_window
   FROM sensor_reading sr JOIN device d ON sr.device_id = d.id
   WHERE d.dev_eui = '70b3d52dd3034de4'
   ORDER BY time DESC LIMIT 5;"
```

### 10e.7 Audit-Log-Patterns

**SSH (heizung-test, root):** alle Vicki-Konfig-Reports zeigen:

```bash
journalctl -u deploy-api --since "1 hour ago" | grep "MAINTENANCE_VICKI_CONFIG_REPORT"
# Beispiel-Output:
# event_type=MAINTENANCE_VICKI_CONFIG_REPORT dev_eui=70b3d52dd3034de4 enabled=True duration_min=10 delta_c=1.5
```

FW-Persist-Events:

```bash
journalctl -u deploy-api --since "1 hour ago" | grep "firmware_version persistiert"
# Beispiel-Output:
# firmware_version persistiert dev_eui=70b3d52dd3034de4 fw=4.5
```

Downlink-Send-Events (alle Commands):

```bash
journalctl -u deploy-api --since "5 minutes ago" | grep "downlink gesendet"
# Beispiel-Output:
# downlink gesendet dev_eui=70b3d52dd3034de4 cmd=0x04 topic=application/...
# downlink gesendet dev_eui=70b3d52dd3034de4 cmd=0x45 topic=application/...
# downlink gesendet dev_eui=70b3d52dd3034de4 cmd=0x46 topic=application/...
```

### 10e.8 Re-Run-Idempotenz

Bulk-Skript ist idempotent:

- `0x04`: stateless, Vicki antwortet jedes Mal mit aktueller FW.
- `0x45`: setzt OW-Konfig (überschreibt, kein additives Verhalten).
  Re-Run mit gleichen Parametern → identische Hardware-Konfig, kein
  Schaden.
- `0x46`: read-only, keine Hardware-Aktion.

Re-Run-Indikation:

- Nach Codec-Re-Paste (RUNBOOK §10c) — alle Devices haben evtl. neue
  FW-Strings.
- Nach Hardware-Tausch eines Vickis.
- Nach Sprint-Update mit geänderten OW-Defaults.

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
- Hetzner Cloud Firewall ist für diesen Account NICHT konfiguriert — Blockaden kommen server-seitig (UFW).
- Rescue-Modus ist nach einem Reboot verbraucht, Server bootet normal zurück.
- `ssh-heizung`-Key in Hetzner gilt sowohl für Rescue-Auth als auch produktiven SSH-Zugang.
