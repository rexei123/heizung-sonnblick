# Server-Setup (Hetzner Cloud)

Schritt-für-Schritt-Anleitung für eine frische Ubuntu-24.04-VM (CX22 für Test, CX32 für Main). Die Schritte sind für beide Systeme identisch — nur Hostname und DNS unterscheiden sich.

## 1. VM erstellen

- Hetzner Cloud Console → Project → Add Server
- Image: **Ubuntu 24.04 LTS**
- Type: **CX22** (Test) bzw. **CX32** (Main)
- Location: **Nürnberg** oder **Falkenstein** (DSGVO, niedrige Latenz)
- SSH-Key des Hoteliers anhängen
- Firewall: erstmal nur Ports 22, 80, 443

Nach Erstellung notieren: **Public IPv4** der VM.

## 2. DNS setzen

Beim DNS-Provider von `hotel-sonnblick.at` zwei A-Records anlegen:

```
test.heizung    A    <Test-IP>     TTL 3600
heizung         A    <Main-IP>     TTL 3600
```

DNS-Propagation prüfen mit `dig +short test.heizung.hotel-sonnblick.at`.

## 3. Server-Grundkonfiguration (als root, einmalig)

```bash
# Updates
apt update && apt upgrade -y

# Zeitzone
timedatectl set-timezone Europe/Vienna

# Deploy-User
adduser --gecos "" --disabled-password deploy
usermod -aG sudo deploy
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# SSH absichern (root-Login deaktivieren)
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Fail2ban
apt install -y fail2ban
systemctl enable --now fail2ban
```

## 4. Docker installieren

```bash
# Als deploy-User:
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
# Logout & wieder einloggen, damit die Gruppenmitgliedschaft greift.
docker --version
docker compose version
```

## 5. Repo klonen

```bash
sudo mkdir -p /opt/heizung-sonnblick
sudo chown deploy:deploy /opt/heizung-sonnblick
cd /opt
git clone https://github.com/rexei123/heizung-sonnblick.git
cd heizung-sonnblick
# Test-Server: develop, Main-Server: main
git checkout develop   # oder: git checkout main
```

## 6. .env vorbereiten

```bash
cp infra/deploy/.env.example infra/deploy/.env
nano infra/deploy/.env
```

- `STAGE=test` oder `STAGE=main`
- `PUBLIC_HOSTNAME` entsprechend setzen
- `POSTGRES_PASSWORD` durch ein starkes Passwort ersetzen (`openssl rand -hex 24`)
- `SECRET_KEY` durch ein neues Secret ersetzen (`openssl rand -hex 32`)
- `DATABASE_URL` mit dem Postgres-Passwort konsistent halten

```bash
chmod 600 infra/deploy/.env
```

## 7. Erster Deploy

```bash
./infra/deploy/deploy.sh test     # auf Test-Server
# bzw.
./infra/deploy/deploy.sh main     # auf Main-Server
```

Caddy zieht beim ersten Start automatisch das Let's-Encrypt-Zertifikat — DNS muss vorher zeigen.

## 8. GitHub-Secrets eintragen

Im Repo unter Settings → Secrets and variables → Actions:

| Secret             | Wert                                            |
|--------------------|-------------------------------------------------|
| `DEPLOY_USER`      | `deploy`                                        |
| `DEPLOY_SSH_KEY`   | privater SSH-Schlüssel (Inhalt der `id_ed25519`) |
| `TEST_HOST`        | IP des Test-Servers                             |
| `MAIN_HOST`        | IP des Main-Servers                             |

Dazu unter Settings → Environments:
- `test` — keine Approval-Pflicht
- `main` — Required reviewer = Hotelier (Schutz vor unbeabsichtigtem Prod-Deploy)

## 9. Smoke-Test

```bash
curl -s https://test.heizung.hotel-sonnblick.at/health
# {"status":"ok","version":"...","environment":"production"}
```
