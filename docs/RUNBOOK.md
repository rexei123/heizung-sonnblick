# RUNBOOK — Heizungssteuerung Hotel Sonnblick

Operations-Handbuch für Test- und Main-Server. Stand: 2026-04-28.

**Regel Nr. 1:** Bei Rescue-Einsatz IMMER den kompletten Fix-Block aus §3 in einem Shot ausführen. Niemals inkrementell fixen.

---

## 1. Server-Übersicht

| Rolle | Hetzner | Public-IP / Hostname | Tailscale | GHCR-Tag | Branch |
|---|---|---|---|---|---|
| Test (= **Prod** seit 2026-06-09) | CPX22 | `157.90.17.150` / **`heizung.hoteltec.at`** (Prod, develop-Stand; `heizung-test.hoteltec.at` nicht mehr bedient) | `heizung-test` = `100.82.226.57` | `develop` | `develop` |
| Main (**alter Live-Prod-Server**) | CPX32 | `157.90.30.116` / — (bediente `heizung.hoteltec.at` bis zum Promote; jetzt Rollback-Reserve, Stilllegung C1 offen) | `heizung-main` = `100.82.254.20` | `main` | `main` |
| Entwickler-Client | — | — | `work02` = `100.78.38.29` | — | — |

**Stand 2026-06-09 (Sprint 15g / AE-67):** Single-Server-Prod — heizung-test
ist die Produktion unter `heizung.hoteltec.at`, `STAGE` bleibt bewusst `test`
(kein main-Strang, develop=Prod). heizung-main ist der alte Live-Prod-Server
(Rollback-Reserve, DNS-Schwenk zurück → `157.90.30.116`); Stilllegung (nur
Stop) ist C1 und noch offen.

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
**Update 2026-06-09 (Sprint 15g / AE-67):** `heizung.hoteltec.at` zeigt seit dem
Prod-Domain-Promote auf **`157.90.17.150`** (heizung-test). Der alte Server
`157.90.30.116` bedient die Prod-Domain nicht mehr (Rollback-Reserve, C1 offen).

| Rolle | Hostname | IP |
|---|---|---|
| **Prod** (heizung-test) | `heizung.hoteltec.at` | `157.90.17.150` |
| Zweitname (nicht mehr bedient) | `heizung-test.hoteltec.at` | `157.90.17.150` |
| alter Live-Prod (heizung-main) | — (kein aktiver Prod-Hostname; Rollback-Reserve) | `157.90.30.116` |

**DNS-Hosting:** Hetzner Online / konsoleH (NICHT Hetzner Cloud DNS).
Admin-Konsole: https://console.hetzner.com/ → Domain `hoteltec.at` → DNS-Records.
Nameserver: `ns1.your-server.de`, `ns.second-ns.com`, `ns3.second-ns.de`.

A-Records (TTL 300):

| Name | Wert |
|---|---|
| `heizung` | `157.90.17.150` (seit 2026-06-09, Sprint 15g; vorher `157.90.30.116`) |
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

**Zielserver:** `heizung-test` (= **Prod**, `heizung.hoteltec.at` seit AE-67). Der frühere Zusatz „`heizung-main` nachgezogen, sobald Production-Migration ansteht" **entfällt** — kein main-Strang, heizung-main wird stillgelegt (AE-67 / Sprint 15g).

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

**Production-Hinweis:** Die Live-Vickis laufen auf **heizung-test = Prod** (AE-67); jeder Repo-Codec-Touch erfordert dort den UI-Re-Paste. Der frühere Verweis auf einen separaten heizung-main-Prod **entfällt** (kein main-Strang). Backlog: B-9.10c-2 (programmatisches Bootstrap).

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
| — | (Stub) | Device-Health-Status per API abrufbar — siehe Sprint 11 (AE-53). Endpoint folgt mit Health-State-Modell. |

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

`setpoint` muss ganzzahlig sein (Vicki-Hardware-Constraint, Dezimalstellen werden mit 422 abgelehnt).

**Sprint 12 (AE-52):** Bei mindestens einer HeatingZone des Raums mit aktivem `open_window=True`-Reading (frisch, healthy Device) wird der POST mit HTTP 409 abgelehnt. Body:

```json
{
  "detail": {
    "error": "override_rejected_window_open",
    "zones": [{"zone_id": 42, "reading_at": "2026-05-19T09:18:12.123456+00:00"}]
  }
}
```

Kein DB-Insert in `manual_override`, kein `business_audit`-Eintrag, kein Engine-Trigger. Fenster schliessen, dann erneut versuchen. Symmetrie-Caveat: Helper filtert auf `Device.health_state='healthy'` — bei All-Unhealthy-Cluster geht der Override durch, obwohl physisch ein Fenster offen sein koennte (Sprint-12a-Frontend-Hinweis dazu kommt).

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

#### Wartung/Renovierung via fiktive Belegung (Sprint 12a, AE-58)

Sprint 12a hat das Override-Modell konsolidiert (AE-58): Override existiert nur in OCCUPIED-Zimmern. Wartungs-Szenarien (Renovierungs-Setpoint 12 °C über mehrere Tage, Wartungs-Aufheizung vor Handwerker-Termin, technische Trocknung nach Wasserschaden) laufen NICHT mehr ueber `manual_setpoint_event` (AE-29 abgeloest), sondern ueber eine **fiktive Belegung**:

**Schritt-Anweisung:**

1. Fiktive Belegung anlegen via Belegungs-API (oder Frontend „Belegungen → Neu"):

   ```bash
   curl -u "<user>:<pass>" -X POST -H "Content-Type: application/json" \
     -d '{"room_id": 42, "check_in": "2026-10-15T07:00:00Z", "check_out": "2026-10-18T16:00:00Z", "source": "manual"}' \
     https://heizung-test.hoteltec.at/api/v1/occupancies
   ```

   `source="manual"` markiert die Belegung als manuell angelegt (nicht PMS-synchronisiert). `check_in`/`check_out`-Zeitfenster deckt die Wartungs-Phase ab.

2. Mitarbeiter-Override „bis Check-out" setzen (Renovierungs-Setpoint 12 °C, Aufheiz-Setpoint 21 °C usw.):

   ```bash
   curl -u "<user>:<pass>" -X POST -H "Content-Type: application/json" \
     -d '{"setpoint": "12", "source": "frontend_checkout", "reason": "Renovierung"}' \
     https://heizung-test.hoteltec.at/api/v1/rooms/42/overrides
   ```

   Override bekommt `expires_at = check_out` der fiktiven Belegung (Hard-Cap 7 Tage greift defensiv). `reason` ist Audit-Klartext.

3. Wartung läuft, Engine hält den Setpoint.

4. Am Ende der Wartung Belegung beenden (PATCH cancel oder check_out vorzeitig stornieren):

   ```bash
   curl -u "<user>:<pass>" -X PATCH -H "Content-Type: application/json" \
     -d '{"cancel": true}' \
     https://heizung-test.hoteltec.at/api/v1/occupancies/<id>
   ```

   `sync_room_status` wechselt automatisch `OCCUPIED → VACANT`. Wenn kein Folge-Checkin innerhalb 4 h ansteht, triggert `auto_revoke_on_checkout` (`revoke_all_active_overrides`) — der Wartungs-Override wird sauber revokiert, Audit-Spur bleibt. Raum laeuft anschliessend auf globalen Einstellungen.

**Begruendung:** Eine Override-Quelle weniger (AE-29 entfaellt), eine konsistente Lifecycle-Logik (Override + Belegung sind gekoppelt), saubere Audit-Spur in `occupancy` + `manual_override` + `business_audit` statt eines parallelen `manual_setpoint_event`-Pfads. Referenz: `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` AE-58.

### 10d.8 Health-Status-Compute-Task (Sprint 11 T5, AE-53)

Periodische Health-State-Berechnung laeuft via Celery-Beat alle
5 Minuten in `tasks/health_tasks.py::compute_health_state`. Pure-
Function-Helper `_compute_health_state_async` ist separat importier-
bar fuer Tests und Ad-hoc-Trigger.

**Beat-Schedule-Verifikation:**

```bash
# Im Container (heizung-test oder heizung-main)
celery -A heizung.celery_app inspect scheduled
# Erwarteter Eintrag: compute-health-state-every-5min, schedule=300.0s,
# queue=heizung_default
```

**Manueller Trigger (Debug/Diagnose):**

```bash
# SSH auf heizung-test
docker exec -it heizung-worker python -c \
  "from heizung.tasks.health_tasks import compute_health_state; print(compute_health_state.delay())"
# Async-Result-ID wird ausgegeben; Status via celery inspect oder
# direkten Aufruf des Pure-Function-Helpers fuer sync-Debug:
docker exec -it heizung-worker python -c \
  "import asyncio; from heizung.tasks.health_tasks import _compute_health_state_async; print(asyncio.run(_compute_health_state_async()))"
```

**Container-Log-Filter:**

```bash
# Live-Tail aller Health-Alerts (Stufe 2 + 3)
journalctl -u heizung-worker -f | grep health_alert

# Letzte 100 Health-Alerts retrospektiv
journalctl -u heizung-worker -n 1000 | grep health_alert | tail -100
```

**Erwarteter Output bei Stufe-2-Alarm (offline > 24h):**

```
WARNING ... heizung.services.health_alerts ... health_alert
  [level=2, device_id=42, dev_eui="58a0cb..", reason="offline_24h"]
```

**Erwarteter Output bei Stufe-3-Alarm (implausible Readings >= 10):**

```
WARNING ... heizung.services.health_alerts ... health_alert
  [level=3, device_id=17, dev_eui="58a0cb..", reason="implausible_readings_24h"]
```

**Implausible-Counter im Redis pruefen:**

```bash
docker exec -it heizung-redis redis-cli
> KEYS implausible:*
> GET implausible:58a0cb1234567890
> TTL implausible:58a0cb1234567890   # Sekunden bis 86400-TTL ablaeuft
```

**Troubleshooting:**

- Compute-Task laeuft nicht: `celery inspect active` pruefen, ob Worker
  ueberhaupt aktiv ist. Beat-Process kann via `ps aux | grep celery.*beat`
  gefunden werden (oder `-B`-Flag im Worker bei Embedded-Beat-Deployment).
- Keine `health_alert`-Logs trotz Compute-Task-Laufs: vermutlich kein
  Device im `silent_transitions`-Pfad (Devices, die zwar silent sind,
  aber schon vorher silent waren, loesen KEINEN Alarm aus — Idempotenz).
- Falsche `health_state`-Werte: `_compute_health_state_async` ist pure-
  function-tauglich, kann lokal gegen Test-DB laufen (siehe
  `tests/test_health_compute.py`).

### 10d.9 Belegungs-Import-Webhook (Sprint 15e, AE-66)

**Bezug:** AE-66, Endpoints in `api/v1/integrations.py`, Service
`services/occupancy_import_service.py`. Mail-Surrogat für Casablanca
(mailparser.io → Webhook), bis FIAS (Sprint 16a) kommt.

**Secret setzen (je Server, einmalig):** in
`/opt/heizung-sonnblick/infra/deploy/.env`:

```
OCCUPANCY_IMPORT_TOKEN=<openssl rand -hex 32>
OCCUPANCY_IMPORT_EXPECTED_BY_LOCAL=09:00
```

Leeres/fehlendes Token = der Endpoint lehnt **jede** Anfrage mit 401 ab
(fail-closed). In mailparser.io denselben Wert als Custom-Header
`X-Webhook-Token` hinterlegen.

**Endpoint A — Import (Webhook):**

```
POST /api/v1/integrations/occupancy-import
Header: X-Webhook-Token: <secret>
Content-Type: application/json
```

Body (mailparser „Nested - array of objects", „One request per email"):

```json
{
  "id": "a149d8a3-...",
  "received_at": "2026-06-06 07:14:15",
  "liste": [
    { "Zimmer": "103", "Anreise": "04.06.", "Abreise": "06.06.2026", "Aufenthaltstyp": "Abreise" },
    { "Zimmer": "52\n⇒ 101", "Anreise": "05.06.", "Abreise": "07.06.2026", "Aufenthaltstyp": "Zimmerwechsel" }
  ]
}
```

- **Datumsformat (Sprint 15e-1):** `Anreise` kommt real OHNE Jahr (`TT.MM.`),
  `Abreise` MIT Jahr (`TT.MM.JJJJ`). Der Server leitet das Anreise-Jahr aus der
  Abreise ab — Jahreswechsel inklusive (Anreise `29.12.` + Abreise `02.01.2027`
  → Anreise 29.12.2026). Beide Formen werden defensiv akzeptiert.
- `received_at`-Datumsteil = `list_date` (Europe/Vienna). `id` = Idempotenz
  (gleiche `id` + `list_date` zweimal → `{"status":"already_processed"}`).
- Zimmerwechsel (`⇒`): nur das Zielzimmer zählt.
- Unbekannte Zimmernummer → **422, nichts geschrieben** (atomar).
- Leere `liste` → alle aktiven pms-Belegungen des Tages werden geschlossen.

```bash
# SSH (heizung-test) — Smoke-Test gegen das webhook.site-Beispiel
curl -sS -X POST https://heizung-test.hoteltec.at/api/v1/integrations/occupancy-import \
  -H "X-Webhook-Token: $OCCUPANCY_IMPORT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"smoke-1","received_at":"2026-06-06 07:14:15","liste":[{"Zimmer":"103","Anreise":"04.06.","Abreise":"06.06.2026","Aufenthaltstyp":"Abreise"}]}'
# -> {"status":"applied","rooms_occupied":1,"rooms_closed":0,"conflicts":0}
# Zweiter identischer POST -> {"status":"already_processed"}
```

**Endpoint B — Status/Log (Login-Session, NICHT das Webhook-Token):**

```
GET /api/v1/integrations/occupancy-import/log
```

Liefert `status` (green/yellow/red, Backend-berechnet), `last_success_at`
(UTC), `expected_by_local`, `today_received`, `imports` (letzte 30, neueste
zuerst). Quelle ist `business_audit` — kein eigenes Log-Modell.

**Watchdog:** `heizung.check_occupancy_import_freshness` (Celery-Beat
täglich 08:15 UTC). Kein Import bis `expected_by_local` → Audit
`OCCUPANCY_IMPORT_STALE`. Gibt **keine** Zimmer frei (letzter Stand bleibt
eingefroren). Diagnose:

```bash
docker logs deploy-celery_beat-1 --since 24h 2>&1 | grep -i occupancy
# business_audit nach STALE/APPLIED fragen (DB):
#   SELECT ts, action, new_value FROM business_audit
#   WHERE action LIKE 'OCCUPANCY_IMPORT%' ORDER BY ts DESC LIMIT 10;
```

Email-Alarm bei STALE ist NICHT aktiv (an B-15b-1 gekoppelt).

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

## 10f. Pre-commit-Hook (Sprint 10 T8, B-9.10d-6)

Lokaler Hook, der vor jedem Commit `ruff check` und
`ruff format --check` auf `backend/(src|tests)/` ausfuehrt. Konfig:
`.pre-commit-config.yaml` im Repo-Root.

Zweck: §5.24-Wiederholungsfehler (lokal vergessen `ruff format`, CI
bricht) blockieren, bevor der Commit raus geht.

### Setup pro Klon (einmalig)

```powershell
# PowerShell (Windows lokal), Working-Tree muss heizung-sonnblick sein
pip install pre-commit
pre-commit install
```

`pip` ist hier das System-Python oder eine globale venv — der Hook
laeuft NICHT durch die `backend/.venv`, sondern via `pre-commit`'s
isolierte Tool-Envs.

### Versionspflege

`.pre-commit-config.yaml` pinnt `ruff-pre-commit` auf eine konkrete
Version (heute `v0.15.12`). Diese MUSS zur ruff-Version in
`backend/pyproject.toml [project.optional-dependencies] dev` und zum
CI-Workflow `.github/workflows/backend-ci.yml` passen — sonst entsteht
Format-Drift (lokal greener als CI oder umgekehrt).

Update-Workflow:

```powershell
pre-commit autoupdate          # zieht neueste ruff-pre-commit rev
# anschliessend backend/pyproject.toml `ruff>=...` Pflicht-Bump
```

### Manueller Lauf ueber alle Files

```powershell
pre-commit run --all-files
```

Praktisch nach `pre-commit install` einmal anstossen, damit alle Files
durch sind und nicht beim ersten Commit eine grosse Diff aufpoppt.

### Hook umgehen

`git commit --no-verify` umgeht den Hook. CLAUDE.md erlaubt das nur
nach expliziter User-Anweisung. Bei Hook-Fail: Format-Fix einarbeiten,
neu commiten.

---

## 10g. Secrets-Rotation auf heizung-test / heizung-main (Sprint 10 T6, B-9.17-S1)

`POSTGRES_PASSWORD` + `SECRET_KEY` rotieren ohne die Werte ueber den
Strategie-Chat oder shell-history zu leaken. Werkzeug:
`infra/deploy/rotate-secrets.sh` — One-Shot-Tool, generiert die neuen
Werte direkt auf dem Server (`openssl rand -hex 32`), wechselt das
Postgres-Userpasswort via `ALTER USER ... STDIN-Heredoc`, aktualisiert
`.env` per `sed -i` (POSTGRES_PASSWORD, SECRET_KEY, DATABASE_URL-embed),
restartet den Stack.

### Pflicht-Stop vor Lauf

Strategie-Chat-Freigabe einholen mit:

- Aktueller `.env`-Pfad (`/opt/heizung-sonnblick/infra/deploy/.env`).
- Geplante Backup-Konvention: `.env.bak-pre-rotation-<UTC-ISO-Compact>`
  (z.B. `.env.bak-pre-rotation-20260515T135700Z`).
- Test-Login-Credential bereit (operativer Admin, z.B.
  `kaprun@hotel-sonnblick.at`).
- Rollback-Plan dokumentiert (siehe unten).

### Lauf

```powershell
# PowerShell (Windows lokal), aus Repo-Root
scp -i $HOME\.ssh\id_ed25519_heizung `
    infra/deploy/rotate-secrets.sh `
    root@heizung-test:/tmp/rotate-secrets.sh

ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-test `
    "cat -n /tmp/rotate-secrets.sh"
# Sichtpruefung aller Zeilen, dann:

ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-test `
    "bash /tmp/rotate-secrets.sh"
```

Erwarteter Output (Schritte [1/8] bis [8/8]):

- `BACKUP: .env.bak-pre-rotation-<TS>`
- `ALTER ROLE`
- compose-Restart-Block, am Ende Container-Status-Tabelle.

### Verify (Login-Roundtrip, lokal)

```bash
# Bash (Git Bash auf Windows oder Linux-Shell). Passwort versteckt.
read -rsp "kaprun@hotel-sonnblick.at PW: " P; echo
curl -s -o /tmp/lv.body -D /tmp/lv.headers -w "status=%{http_code}\n" \
  -X POST https://heizung-test.hoteltec.at/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"kaprun@hotel-sonnblick.at\",\"password\":\"$P\"}"
unset P
grep -i "set-cookie" /tmp/lv.headers || echo "NO COOKIE"
rm -f /tmp/lv.body /tmp/lv.headers
```

Erwartung: `status=200`, `Set-Cookie: heizung_session=...` Zeile. Plus
Browser-Smoke auf `https://<host>/zimmer` (Sidebar zeigt Glyphen,
Inhalte laden).

### Cleanup (7 Tage nach Rotation)

```bash
# SSH (heizung-test, root)
cd /opt/heizung-sonnblick/infra/deploy
ls -la .env.bak-pre-rotation-*
# Manuell loeschen, sobald 7 Tage verstrichen sind und Rotation
# als stabil bestaetigt wurde:
rm .env.bak-pre-rotation-<TS>
```

7-Tage-Retention deckt: Verzoegerte Fehler (z.B. JWT-Ablauf nach 12h
sichtbar erst beim naechsten Login-Versuch), Rollback-Reaktion auf
Hotelier-Beschwerden, externe Service-Drifts. Laenger als 7 Tage ist
Risiko (gestohlene Server-FS-Snapshots koennten den OLD-Wert
zurueckziehen).

### Rollback bei Verify-Fail

Wenn Login-Verify rot oder Container nicht hochkommen:

```bash
# SSH (Server, root)
cd /opt/heizung-sonnblick/infra/deploy

BACKUP=$(ls -t .env.bak-pre-rotation-* | head -1)
[ -n "$BACKUP" ] || { echo "no backup"; exit 1; }
echo "rolling back from: $BACKUP"

OLD_PWD=$(grep '^POSTGRES_PASSWORD=' "$BACKUP" | cut -d= -f2-)

docker exec -i deploy-db-1 psql -U heizung -d postgres <<SQL
ALTER USER heizung WITH PASSWORD '$OLD_PWD';
SQL

cp -p "$BACKUP" .env
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
```

Nach Rollback: Strategie-Chat-Stop, kein zweiter Rotation-Versuch
ohne Diagnose der Failure-Ursache.

### Was nicht ueber dieses Skript laeuft

- `MQTT_*_PASSWORD`, `CHIRPSTACK_*` Secrets: nicht in Sprint-10-T6-
  Scope. Eigene Rotation, weil sie zusaetzlich Mosquitto-passwd-Datei
  + ChirpStack-DB-User-Update brauchen (RUNBOOK §10a fuer MQTT-Setup,
  spaetere Sprint-Backlog fuer reguläre Rotation).
- GHCR-PAT: RUNBOOK §6.1.
- Caddy-Basic-Auth-Hash (`HOTEL_BASIC_AUTH_HASH`,
  `CHIRPSTACK_BASIC_AUTH_HASH`): RUNBOOK §10b.

---

## 10h. Pre-Pairing-Workflow September 2026 (Stub)

> **Status (2026-05-15):** Stub. Vollständige Anleitung folgt aus
> Sprint 13 (Pairing-Wizard inkl. Mass-Pairing-CSV) und Sprint 17
> (Pre-Pairing September, Phase 4b). Dieser Abschnitt existiert,
> damit der Hotelier später weiß, wo gesucht werden muss.
>
> Bezug: STRATEGIE-THERMOSTAT-ZUORDNUNG.md §15 (Migrations-Plan),
> SPRINT-PLAN.md Sprint 13 + Sprint 17.

### 10h.0 Zimmer-Seed vor Pairing (Stammdaten)

**Pflicht VOR dem Pairing:** Die echten Zimmer + Zonen müssen in der DB
stehen, bevor Vickis Zonen zugeordnet werden. Das Skript
`heizung.scripts.seed_rooms` ersetzt die fiktiven Test-Zimmer durch die
echte Zimmerliste (**45 Zimmer / 103 Zonen**) aus `Zimmerliste_seed.csv`.

**Reiner Stammdaten-Seed** — kein device-Bezug, kein MQTT-Downlink, keine
Migration, kein Enum-Touch, keine neue Spalte (Weg A, Mapping auf das
Bestandsschema). Mapping:
`Zimmer_Kategorie → room.room_type_id` (RoomType Doppelzimmer/Suite),
`Room_Type → heating_zone.kind` (Schlafzimmer/Kinderzimmer → bedroom,
Badezimmer → bathroom), `Zone_Label → heating_zone.name`. PMS_Mapping wird
ignoriert (== Zimmernummer, kein Konsument).

Die CSV ist als **Package-Data** ins Image eingebettet
(`heizung/scripts/seed_data/Zimmerliste_seed.csv`) → **Lauf ohne scp**.
Ein optionaler Positionsparameter überschreibt den Pfad.

**Blockierende Vorstufe:** Hängt an einer bestehenden `heating_zone` ein
Device, **bricht `import` ab** (kein Wipe, keine Vicki-Orphans) und nennt
die betroffenen Devices. Wipe nur bei null Pairings — daher Zimmer-Seed
**vor** dem Pairing ausführen.

**Container-Name nicht hart annehmen** (Prod-Pattern `deploy-api-1`,
heizung-test ggf. anders — via `docker ps` prüfen):

```bash
# 1) Schema-Pre-Flight (kein Side-Effekt, keine DB):
docker exec <api-container> python -m heizung.scripts.seed_rooms validate

# 2) Trockenlauf (Wipe+Reseed, danach Rollback — zeigt Step-0 + Counts):
docker exec <api-container> python -m heizung.scripts.seed_rooms import --dry-run

# 3) Scharf (in EINER Transaktion: room+heating_zone löschen, neu anlegen):
docker exec <api-container> python -m heizung.scripts.seed_rooms import
```

**Schritt 0 (automatisch):** fehlt RoomType `Doppelzimmer`/`Suite`, legt
das Skript sie mit Default-Setpoints an (21/18/19 °C). Zonentyp-RoomTypes
(Schlafzimmer/Bad/Kind) werden **nicht** angelegt — das ist Absicht.

**Erwartetes Resultat:** `45 room + 103 heating_zone`, jedes Zimmer genau 1
`bathroom`-Zone, 9 Zonen `name="Kinderzimmer"` (alle `bedroom`) an den
Zimmern 107/115/207/215/302/303/306/310/401.

**Achtung Daten-Wipe:** `import` löscht **alle** `room` + `heating_zone`;
per FK-Cascade auch raumbezogene `occupancy`/`manual_override`/`event_log`/
room-scope-`rule_config`. Globale + Raumtyp-Configs (room_id NULL) bleiben.
Auf produktiven Daten nur bewusst und nach `--dry-run`-Sichtung.

### 10h.1 Vicki-Eingangstest (5 Schritte pro Gerät)

Pro Vicki vor der Montage auf dem Tisch im Hotel-Office:

1. **Vicki einschalten + pairen.** Pairing-Wizard durchlaufen
   (ChirpStack-Stufe + Zimmer/Zone/Label). Erster Uplink
   erwartet innerhalb von 2 Min.
2. **Temperatur lesen.** Plausi 15-30 °C im Lagerraum (sonst
   AE-53 Plausi-Filter [-20 °C, 60 °C] greift; Werte ausserhalb
   sind Hardware-/Sensor-Befund).
3. **Setpoint 25 °C senden.** Downlink-Bestätigung im
   ChirpStack-Event-Tab abwarten, Ventil hörbar auf.
4. **Setpoint 10 °C senden.** Downlink-Bestätigung, Ventil
   hörbar zu.
5. **Backplate-Bit prüfen.** `attachedBackplate=false` ist
   erwartet, weil Vicki nicht montiert ist. Falls `true`:
   Backplate sitzt am Tisch fest oder Codec-Befund (siehe
   CLAUDE.md §5.21 fPort-Routing).

Bestandene Geräte werden als „eingangsgetestet" markiert und
wandern in den Montage-Pool für Sprint 17 / Phase 6.

### 10h.2 Pre-Pairing-Skript-Anwendung (Sprint 13a)

Skript: `python -m heizung.scripts.pair_devices`.

Aufrufkontext: Hotelier oder Mitarbeiter sitzt am Office-Laptop, hat
SSH-Zugang auf den Server. Skript laeuft im Backend-Container via
`docker exec`. CSV liegt auf dem Server unter `/tmp/`.

**Voraussetzungen vor Pairing-Lauf:**

1. ChirpStack-Bulk-Import von Tenants + Application + DeviceProfile +
   alle DevEUIs ist bereits einmal vor September im ChirpStack-Web-UI
   gemacht (Hotelier-Hand, nicht Skript-Aufgabe).
2. CSV ist vorbereitet aus der Master-Vorlage
   `docs/inventar/Zimmer_Geraete_Liste.xlsx`. Spalten:

   stockwerk; zimmer_nummer; zimmer_typ; zone_label; dev_eui; app_key

   - Encoding utf-8 oder utf-8-mit-BOM (Excel-Default Windows).
   - Trennzeichen Semikolon oder Komma (auto-erkannt).
   - dev_eui: 16-Hex-Zeichen vom Vicki-Aufkleber.
   - app_key: 32-Hex-Zeichen vom Vicki-Aufkleber. WICHTIG: app_key
     wird NICHT in heizung-DB persistiert — er gehoert zur
     ChirpStack-Registrierung. Spalte ist Cross-Reference-Notiz fuer
     den Hotelier.
   - Reserve-Geraete: Spalten `stockwerk`, `zimmer_nummer`,
     `zimmer_typ`, `zone_label` leer lassen. Skript erkennt das als
     Pool-Device, legt `heating_zone_id = NULL` an.

3. Zimmer + Heating-Zones sind in heizung-DB vorhanden. Falls nicht
   (heizung-test = Prod beim Live-Lauf im September; AE-67 — kein
   separater heizung-main-Server mehr), vorher Zimmer-Seed-Sprint
   ausfuehren.

**Workflow Schritt fuer Schritt:**

A. CSV auf den Server kopieren (PowerShell auf Laptop):

   ```powershell
   scp pairings.csv server:/tmp/
   ```

B. Pre-Flight-Validierung (kein Side-Effekt):

   ```bash
   ssh server "docker exec deploy-api-1 python -m heizung.scripts.pair_devices \
       validate /tmp/pairings.csv"
   ```

   Erwartung: `[OK] N CSV-Rows validiert. Bereit fuer import.`
   Bei Fehlern: jede Zeile bekommt eine eigene Fehlerzeile, Skript
   exit-codet 1. Hotelier korrigiert CSV, lokal speichern, scp neu,
   nochmal validate.

C. Smoke-Test gegen heizung-test (NUR vor Live-Lauf September,
   Sprint 13a-Verifikation):

   ```bash
   ssh server "docker exec deploy-api-1 python -m heizung.scripts.pair_devices \
       import /tmp/pairings.csv --dry-run"
   ```

   ACHTUNG: `--dry-run` rollt die DB-Aenderungen zurueck, sendet
   aber trotzdem MQTT-Downlinks an die in der CSV gelisteten Vickis.
   Seit dem Promote (AE-67) laufen auf heizung-test (= Prod) die 4
   **produktiven** Vickis — der dry-run sendet also auch hier echte
   Downlinks an echte Hardware (S4). Entsprechend bewusst einsetzen;
   nur DevEUIs in der CSV listen, deren Konfiguration gewollt ist.

D. Live-Lauf:

   ```bash
   ssh server "docker exec deploy-api-1 python -m heizung.scripts.pair_devices \
       import /tmp/pairings.csv --user-email hotelier@hotel-sonnblick.at"
   ```

   Pro Row: `[OK] Zeile N: DevEUI ... -> paired (device_id=X)` oder
   `[SKIP] Zeile N: DEV_EUI_EXISTS` oder `[FAIL] Zeile N: <Fehler>`.
   Am Ende: Summary mit Counts.

E. Pro Vicki am Tisch: 6-Schritt-Eingangstest (RUNBOOK §10h.1 plus
   idempotenter Open-Window-Resend als Schritt 0):

   ```bash
   ssh server "docker exec -it deploy-api-1 python -m heizung.scripts.pair_devices \
       test <device_id-oder-dev_eui>"
   ```

   Argument-Flexibilitaet: entweder `device.id` aus dem Import-Output
   oder `dev_eui` vom Vicki-Aufkleber. Skript erkennt das automatisch.
   `-it` ist wichtig fuer die Setpoint-Schritte (User-Prompt
   "Ventil geoeffnet? [j/n]").

   Erwartung pro Vicki: alle 6 Schritte `[OK]`,
   `overall_status=passed`. Bei `[FAIL]`: Konsolen-Output nennt den
   Defekt-Schritt, Mitarbeiter dokumentiert Hardware-Problem manuell,
   Vicki wird physisch zurueck in den Karton.

F. Nach Eingangstest pro Vicki: physische Markierung am Vicki-Gehaeuse
   (Aufkleber mit Soll-Zimmer + Soll-Zone). Beispiel:
   "207-Bad / device_id=47".

**Reserve-Pool-Workflow:**

Reserve-Vickis durchlaufen identisch B-D-E (Pre-Flight, Import als
Pool, Eingangstest). In Schritt E ist KEIN Soll-Zimmer-Aufkleber noetig
— Vicki kommt ins Lager mit Markierung "Reserve / device_id=X". Bei
spaeterem Bedarf wird Reserve via Sprint-13b-Tausch-Dialog einem Zimmer
zugewiesen.

Pool-Status abfragen jederzeit:

```bash
ssh server "docker exec deploy-api-1 python -m heizung.scripts.pair_devices list-pool"
```

Ausgabe: Tabelle aller Pool-Devices mit `device_id`, `dev_eui`,
`model`, `created_at`, `label`.

**Stoerungsfaelle:**

- `DEV_EUI_EXISTS`: DevEUI ist schon in heizung-DB. Doppelt importiert,
  oder Vicki von vorigem Hotel-Lauf uebrig. Pruefen via list-pool oder
  DB-Query.
- Eingangstest `heartbeat`-failed: Vicki sendet keinen Uplink. Pruefen
  ob Batterie eingelegt, ob ChirpStack-Application aktiv ist, ob die
  Funkstrecke im Office-Raum funktioniert.
- Eingangstest `temp_plausi`-failed: Temperatur ausserhalb 15-30 °C.
  Vicki im Tiefkuehl oder am Heizkoerper — warten bis Raumtemperatur.
- Eingangstest `backplate`-failed: Vicki erkennt nicht, dass er auf
  einer Backplate sitzt. Hardware-Defekt oder Backplate falsch
  zugeschoben.
- Eingangstest `setpoint_25`/`setpoint_10` mit Status `user_aborted`:
  Mitarbeiter hat Ventil-Bewegung nicht gehoert. Hardware-Defekt —
  Vicki tauschen.
- Eingangstest `resend_open_window`-failed (non-blocking): MQTT zu
  ChirpStack hatte Hiccups beim OW-Resend. Test laeuft trotzdem
  weiter — Vicki bleibt OW-aktiv aus dem urspruenglichen
  Import-Downlink. Bei wiederholtem Resend-Fail: ChirpStack-Container-
  Health pruefen.

**Verwandt:**

- §10h.1 (Eingangstest-Spec)
- AE-57 (Device-Lifecycle, Pool-Status abgeleitet)
- AE-48 (Downlink-Adapter, MQTT-Pfad)
- AE-32 (Vicki-1.0-°C-Setpoint-Quantisierung)

### 10h.3 Zimmer-Zuordnungs-Workflow ohne Montage (TBD, Sprint 17)

Workflow zum Pre-Zuordnen aller ~100 Vickis zu Zimmern/Zonen
ohne physische Montage. Spezifikation folgt aus Sprint 17 +
Hotelier-Schulung (Pilot-Zimmer-Auswahl B-11prep-4). Bis
dahin: vorläufig in „Pre-Pairing-Pool" parken, finale Zimmer-
Zuordnung in Sprint 17.

---

## 10i. Lokale Test-DB starten (Sprint 12 T7-Hotfix)

Pflicht vor Push bei neuen DB-Tests (siehe CLAUDE.md §5.50). Patternfolgt
exakt der CI-Konfiguration aus `.github/workflows/backend-ci.yml`
(timescaledb-Image, Port-Mapping, User/Passwort/DB-Name) — damit lokal
und CI dieselben Schema-Constraints + Migration-Pfade sehen.

> Hinweis Numerierung: Brief der T7-Hotfix-Sektion bezog sich auf
> „§10e", aber §10e ist seit Sprint 9.11x.b durch
> Vicki-Konfiguration-via-Downlink belegt — und §10f/§10g/§10h
> ebenfalls. Erste freie Sektion ist §10i.

### 10i.1 Container starten (einmalig pro Session)

```bash
docker run -d --name heizung-test-db --rm \
  -e POSTGRES_USER=heizung \
  -e POSTGRES_PASSWORD=heizung_test \
  -e POSTGRES_DB=heizung_test \
  -p 5433:5432 \
  timescale/timescaledb:latest-pg16
```

Port-Mapping `5433:5432` lokal — vermeidet Konflikt mit
`docker-compose.yml`-Dev-DB auf `5432`. Volumen ist nicht gemountet,
DB ist nicht-persistent: nach `docker stop` weg, naechste Session
hat frische DB.

### 10i.2 Container bereit verifizieren

```bash
docker exec heizung-test-db pg_isready -U heizung -d heizung_test
```

Erwartung: `/var/run/postgresql:5432 - accepting connections`.

### 10i.3 Tests gegen Container laufen (Backend-Dir)

Linux/Mac/Git-Bash:

```bash
cd backend
export TEST_DATABASE_URL=postgresql+asyncpg://heizung:heizung_test@localhost:5433/heizung_test
export DATABASE_URL=$TEST_DATABASE_URL
export ENVIRONMENT=test
export ALLOW_DEFAULT_SECRETS=1
.venv/Scripts/pytest -q
```

PowerShell (Windows):

```powershell
cd backend
$env:TEST_DATABASE_URL = "postgresql+asyncpg://heizung:heizung_test@localhost:5433/heizung_test"
$env:DATABASE_URL = $env:TEST_DATABASE_URL
$env:ENVIRONMENT = "test"
$env:ALLOW_DEFAULT_SECRETS = "1"
.venv\Scripts\pytest -q
```

Beim ersten Aufruf migriert `conftest._ensure_test_admin` automatisch
auf `head` (alembic upgrade) und legt einen Test-Admin-User an.
Idempotent — folgende Test-Runs ueberspringen das.

Erwartete Test-Counts mit gestartetem Container (Stand Sprint 12 T7):
- ohne Container:  ~189 passed, ~197 skipped (DB-Tests skip)
- mit Container:   ~370-390 passed, ~10-20 skipped (nur reine
  PMS-Stubs / Test-API-Skip-Faelle bleiben skipped)

### 10i.4 Container stoppen (nach Session)

```bash
docker stop heizung-test-db
```

Container hat `--rm`-Flag, wird beim Stop automatisch entfernt.
Daten sind nicht-persistent — Re-Start liefert frische DB.

### 10i.5 Troubleshooting

- **Port 5433 belegt**: anderer Container/Service nutzt 5433. Entweder
  diesen Container auf anderen Port mappen
  (`-p 5434:5432` und `TEST_DATABASE_URL` entsprechend), oder den
  bestehenden Belegungs-Prozess identifizieren
  (`netstat -an | grep 5433` / `ss -tlnp | grep 5433`).
- **`asyncpg.exceptions.InvalidCatalogNameError: database "heizung_test"
  does not exist`**: Container wurde mit anderen ENV-Vars gestartet —
  `docker stop heizung-test-db && docker run …` erneut mit korrekten
  Env-Vars.
- **Test-Failures nach Code-Push, lokal grun**: nicht alle Tests
  gegen Container gefahren — vor Push die Test-Counts mit/ohne
  Container vergleichen (siehe §10i.3).

---

## 10j. Vicki-Tausch via API (Sprint 13b.1, AE-57)

Operative Anleitung fuer den Hardware-Tausch eines defekten Vickis
gegen einen Reserve-Pool-Vicki. Drei API-Endpoints unter
`/api/v1/devices/...`, alle `require_admin` fuer Mutationen und
`require_user` fuer den Pool-Read.

**Voraussetzungen:**

- Defekter Vicki ist im System bekannt (eingebucht, in Zone, evtl.
  bereits silent/inactive). Wir nennen ihn ``OLD_ID``.
- Reserve-Vicki ist im Pool (``heating_zone_id IS NULL``,
  ``retired_at IS NULL``). Pre-Pairing im Hotel-Office wurde
  durchlaufen (Sprint 13a §10h.2). Wir nennen ihn ``POOL_ID``.
- Admin-Cookie im Browser oder als ``-b ...``-Header in curl.

### 10j.1 Pool-Liste anzeigen

```bash
curl -s -b "${COOKIE}" https://heizung-test.hoteltec.at/api/v1/devices/pool
```

Liefert die aktiven Reserve-Vickis sortiert ``created_at DESC``
(neueste zuerst). Wenn die Liste leer ist: Hotelier muss zuerst
einen Pool-Vicki anlegen (§10h.2 Pre-Pairing).

### 10j.2 Tausch alt -> Pool-Vicki

```bash
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -b "${COOKIE}" \
  -d '{"new_pool_device_id": ${POOL_ID}}' \
  https://heizung-test.hoteltec.at/api/v1/devices/${OLD_ID}/replace/from-pool
```

Atomarer Pool-Reassign-Tausch:

- ``OLD`` bekommt ``retired_at=NOW``, ``retired_reason='replaced_by_pool'``,
  ``replaced_by_device_id=POOL_ID``, ``heating_zone_id=NULL``.
- ``POOL`` uebernimmt die Zone des alten Vickis.
- ``DEVICE_REPLACED``-BusinessAudit-Row in derselben Transaktion
  (target_id=OLD_ID).
- Engine-Tick auf der Zone-Room triggert automatisch nach Commit
  (Pattern HF-9.13a-2) — Layer 4 + Engine-Decision-Panel zeigen den
  neuen Stand innerhalb 5-10 Sek.

**Status-Codes:**

- 200 — Tausch ok, Response-Body ist der retired ``OLD``-Device-Row.
- 404 — ``OLD_ID`` oder ``POOL_ID`` existiert nicht.
- 409 — ``OLD`` bereits retired, ``OLD`` ohne Zone (Pool-zu-Pool
  Tausch nicht erlaubt), ``POOL`` nicht im Pool, Selbst-Tausch.
- 401 — fehlende/falsche Auth.

**Race-Schutz:** Bei zwei parallelen Tausch-Versuchen auf
denselben ``POOL_ID`` (zwei Hotelier-Sessions gleichzeitig) gewinnt
einer mit 200, der zweite bekommt 409 mit ``UPDATE-Rowcount=0``-
Detail. Postgres-Default-Isolation READ COMMITTED reicht — der
``UPDATE``-WHERE-Block ist die Wachposten-Stelle.

### 10j.3 Stilllegung ohne Ersatz

```bash
curl -s -X POST \
  -H 'Content-Type: application/json' \
  -b "${COOKIE}" \
  -d '{"reason": "battery_dead"}' \
  https://heizung-test.hoteltec.at/api/v1/devices/${OLD_ID}/retire
```

Setzt ``retired_at`` + ``retired_reason``. ``heating_zone_id``
BLEIBT (Historie-Anker fuer sensor_reading-FK, AE-57 Konsequenz).
``DEVICE_RETIRED``-BusinessAudit + Engine-Tick analog.

### 10j.4 Audit-Trail verifizieren

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "
SELECT id, action, target_id, created_at,
       (new_value->>'new_device_id')::int AS new_dev,
       new_value->>'reason' AS reason
FROM business_audit
WHERE action IN ('DEVICE_REPLACED','DEVICE_RETIRED')
ORDER BY created_at DESC
LIMIT 10;
"
```

### 10j.5 Backup vor Tausch (Pre-Production)

Vor groesseren Tausch-Aktionen (z.B. >1 Vicki gleichzeitig) ein
data-only Backup von ``device`` + ``business_audit`` anlegen:

```bash
# SSH (heizung-test/main, root)
TS=$(date -u +%Y%m%d-%H%M%S)
mkdir -p /opt/heizung-sonnblick/backups
docker exec deploy-db-1 pg_dump -U heizung -d heizung \
    -t device --data-only \
    > /opt/heizung-sonnblick/backups/sprint13b1-device-${TS}.sql
docker exec deploy-db-1 pg_dump -U heizung -d heizung \
    -t business_audit --data-only \
    > /opt/heizung-sonnblick/backups/sprint13b1-audit-${TS}.sql
```

**Achtung pg_dump-Warnung:** ``device`` hat eine zirkulaere
self-referenzielle FK (``fk_device_replaced_by`` zeigt auf
``device.id``). ``pg_dump --data-only`` warnt darum mit
``WARNING: there are circular foreign-key constraints on this
table``. Das ist OK — das Backup ist trotzdem konsistent.

**Restore-Verfahren** falls Rollback noetig:

```bash
# Option A (empfohlen): psql mit deferrable FKs aus -- Restore
# in einer Transaktion mit ALTER CONSTRAINT DEFERRED.
docker exec -i deploy-db-1 psql -U heizung -d heizung <<'SQL'
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
\COPY device FROM '/opt/heizung-sonnblick/backups/sprint13b1-device-<TS>.sql';
COMMIT;
SQL

# Option B: pg_restore mit --disable-triggers (umgeht FK-Checks
# fuer den Restore, FKs sind danach wieder aktiv).
docker exec -i deploy-db-1 pg_restore --disable-triggers \
    -U heizung -d heizung \
    < /opt/heizung-sonnblick/backups/sprint13b1-device-<TS>.sql

# Option C (sicherste): vollen Schema+Data-Dump zurueckspielen.
# Voraussetzung: keine konkurrierenden Schreiber.
```

Wenn Backup nur als Forensik-Reserve liegen soll und nicht
restored wird: pg_dump-Warnung folgenlos.

### 10j.6 Frontend-Dialog (Sprint 13b.2, 2026-05-24)

Hotelier-Workflow auf `/zimmer/{id}` Geraete-Tab — kein CLI noetig
fuer Tausch im laufenden Betrieb.

**Vicki tauschen (defektes/leeres Geraet gegen Reserve aus dem
Lager):**

1. Hotelier oeffnet `/zimmer/{id}`, klickt Tab "Geraete".
2. Neben dem defekten Vicki: Klick auf `swap_horiz Tauschen`.
3. Dialog "Thermostat tauschen" oeffnet. Pool-Dropdown zeigt alle
   Reserve-Vickis aus dem Lager (Label oder DevEUI). DevEUI als
   Hover-Tooltip.
4. Reserve waehlen, "Tauschen" klicken.
5. Toast oben-rechts: "Thermostat getauscht — Engine uebernimmt in
   ≤ 60 s." Geraete-Liste refetcht automatisch; alter Vicki
   verschwindet (Backend-Default-Filter blendet `retired_at !=
   NULL` aus), neuer Vicki erscheint mit derselben Zone.
6. Engine-Tick laeuft in 5-6 Sek nach API-Call (Pattern HF-9.13a-2,
   Worker-Pickup-Latenz, B-9.13a-hf2-2). Layer 4 sieht den neuen
   Vicki sofort.

**Vicki stilllegen (ohne Ersatz, z.B. Zone wird aus Betrieb
genommen oder Vicki wird zur Reparatur eingeschickt):**

1. Klick `power_off Stilllegen` neben dem Vicki.
2. Dialog "Thermostat stilllegen". Bei letztem aktiven Vicki der
   Zone: Warning-Box "Heizung in dieser Zone wird nach Stilllegung
   inaktiv, bis ein neuer Thermostat zugewiesen wird."
3. Grund waehlen: Defekt / Batterie leer / Verlust / Wartung.
4. "Stilllegen" klicken (Destruktiv-Variante in rot).
5. Toast: "Thermostat stillgelegt." Vicki verschwindet aus der
   Liste; Stilllegung dauerhaft (kein Re-Activate-Pfad, neuer
   Vicki via Pre-Pairing-Skript §10h einbringen + Tausch §10j.2
   gegen den retired Row).

**Pool-Race-Verhalten:** Wenn zwei Hotelier-Sessions parallel
denselben Reserve-Vicki waehlen, gewinnt der schnellere; der
zweite sieht Toast "Reserve bereits vergeben. Bitte Auswahl erneut
treffen." und der Dropdown laedt sofort neu (jetzt ohne den
vergebenen Eintrag). Backend-Race-Schutz via UPDATE-WHERE-Clause
(CLAUDE.md §5.60).

**CLI-Pfad (§10h.2) bleibt fuer Operator:** Pool-Refill nach
Defekten (Mass-Import neuer Vickis via CSV), Forensik-Lookup
(`list-pool`-Subcommand), Bulk-Eingangstest neuer Vickis.
Frontend-Tausch + CLI-Bulk-Import komplementaer.

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
