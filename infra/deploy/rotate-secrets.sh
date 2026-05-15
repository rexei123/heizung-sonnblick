#!/usr/bin/env bash
# Secrets-Rotation fuer heizung-test / heizung-main
# (Sprint 10 T6, B-9.17-S1).
#
# One-Shot-Tool. Werte werden auf dem Server generiert
# (openssl rand -hex 32). Es wird NICHTS exposed; weder im
# Strategie-Chat noch in der Shell-History (ALTER USER laeuft
# via STDIN-Heredoc, kein -c "...'$PWD'").
#
# Lauf:
#   scp -i $HOME/.ssh/id_ed25519_heizung \
#       infra/deploy/rotate-secrets.sh \
#       root@heizung-test:/tmp/rotate-secrets.sh
#   ssh -i $HOME/.ssh/id_ed25519_heizung root@heizung-test \
#       'bash /tmp/rotate-secrets.sh'
#
# Verifikation siehe RUNBOOK §10g.
# Backup-Aufbewahrung: 7 Tage, dann manuell loeschen
# (`rm /opt/heizung-sonnblick/infra/deploy/.env.bak-pre-rotation-*`).
#
# Rollback bei Verify-Fail (Login bricht): in derselben SSH-Session
# das Backup zurueckspielen + ALTER USER mit OLD_PWD wieder setzen
# (siehe RUNBOOK §10g Rollback-Block).

set -e
cd /opt/heizung-sonnblick/infra/deploy

# [1/8] Backup
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP=".env.bak-pre-rotation-${TS}"
cp -p .env "$BACKUP"
chmod 600 "$BACKUP"
echo "BACKUP: $BACKUP"

# [2/8] OLD-Wert aus Backup capturen (fuer Rollback-Verify)
OLD_POSTGRES_PWD=$(grep '^POSTGRES_PASSWORD=' "$BACKUP" | cut -d= -f2-)
[ -n "$OLD_POSTGRES_PWD" ] || { echo "FAIL OLD empty"; exit 1; }

# [3/8] Neue Werte generieren
NEW_POSTGRES_PWD=$(openssl rand -hex 32)
NEW_SECRET=$(openssl rand -hex 32)

# [4/8] ALTER USER via STDIN-Heredoc (kein -c, kein ps-Exposure)
docker exec -i deploy-db-1 psql -U heizung -d postgres <<SQL
ALTER USER heizung WITH PASSWORD '$NEW_POSTGRES_PWD';
SQL

# [5/8] .env updaten: POSTGRES_PASSWORD, SECRET_KEY, DATABASE_URL-embed
sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${NEW_POSTGRES_PWD}|" .env
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=${NEW_SECRET}|" .env
sed -i "s|://heizung:[^@]*@|://heizung:${NEW_POSTGRES_PWD}@|" .env

# [6/8] Verify: altes Passwort nicht mehr in .env
if grep -q "$OLD_POSTGRES_PWD" .env; then echo "FAIL old still in .env"; exit 1; fi

# [7/8] Stack neu starten
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d
sleep 20

# [8/8] Container-Status berichten
docker ps --format '{{.Names}}\t{{.Status}}' | grep deploy- | sort
