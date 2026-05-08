> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprint 4 — Domain-Umschaltung auf hoteltec.at

**Typ:** Infrastruktur / Operations
**Ziel:** Öffentliche URLs beider Server von den nip.io-Übergangs-Hostnamen auf die neu registrierte Domain `hoteltec.at` umstellen. Let's-Encrypt-Zertifikate automatisch über Caddy ziehen. Eigenständige Doku für späteres Re-Doing.
**Branch:** `feat/sprint4-domain-hoteltec` (von `main`)
**Geschätzte Dauer:** 60–90 Min (inkl. DNS-Propagations-Wartezeit)

---

## Feature-Brief (Phase 1)

### Ausgangslage
- Beide Server laufen unter nip.io-Wildcard-DNS (`157-90-30-116.nip.io` / `157-90-17-150.nip.io`) als Übergangslösung. Zertifikate gültig, alles funktioniert, aber nicht teilbar/merkbar.
- Domain `hoteltec.at` ist bei Hetzner registriert. DNS soll in Hetzner DNS Console gehostet werden (Entscheidung 4).
- Keine E-Mail-Nutzung auf dieser Domain (Entscheidung 3B). Keine bestehende Webseite (Entscheidung 5A) — freie Bahn, nur Heizung.
- Caddy-Konfiguration ist bereits per Env-Variable `PUBLIC_HOSTNAME` parametrisiert. Umschaltung erfordert keinen Caddyfile-Fork, nur `.env`-Änderung + Container-Reload.

### Ziel
Nach Sprint 4 gilt:

| Rolle | Hostname | IP |
|---|---|---|
| Main | `heizung.hoteltec.at` | `157.90.30.116` |
| Test | `heizung-test.hoteltec.at` | `157.90.17.150` |

Beide unter gültigem Let's-Encrypt-Zertifikat. nip.io-URLs werden nicht mehr beworben (funktionieren nach Umschaltung nicht mehr sauber, da Caddy für sie kein Cert mehr zieht).

### Akzeptanzkriterien
- [ ] DNS-Zone `hoteltec.at` in Hetzner DNS Console existiert, Nameserver bei Registry korrekt delegiert
- [ ] A-Record `heizung.hoteltec.at` → `157.90.30.116` (TTL 300)
- [ ] A-Record `heizung-test.hoteltec.at` → `157.90.17.150` (TTL 300)
- [ ] `nslookup heizung.hoteltec.at` und `nslookup heizung-test.hoteltec.at` liefern die erwarteten IPs
- [ ] `https://heizung-test.hoteltec.at/` liefert HTTP 200 mit gültigem Let's-Encrypt-Zertifikat
- [ ] `https://heizung.hoteltec.at/` liefert HTTP 200 mit gültigem Let's-Encrypt-Zertifikat
- [ ] `.env.example` im Repo zeigt neue Default-Werte
- [ ] Caddyfile-Kommentare aktualisiert (keine `hotel-sonnblick.at`-Referenzen mehr)
- [ ] STATUS.md hat Sprint-4-Abschnitt mit neuen URLs in der System-Tabelle
- [ ] RUNBOOK §9 (DNS-Umschaltung) auf aktuellen Stand gebracht
- [ ] Tag `v0.1.4-domain-hoteltec` gesetzt

### Abgrenzung — NICHT Teil von Sprint 4
- Keine E-Mail-Infrastruktur (MX-Records) — Entscheidung 3B
- Keine IPv6 / AAAA-Records — Docker-Compose bindet nur IPv4
- Keine Canonical-Redirects von nip.io → hoteltec.at (wäre SEO-relevant, hier irrelevant)
- Kein Multi-Host-Caddy mit nip.io als Parallel-Fallback — verworfen zugunsten Einfachheit, Rollback über `.env`-Revert möglich
- Keine Zertifikats-Monitoring-Alerts (Caddy renewed automatisch, manueller Check genügt zunächst)

### Risiken

1. **Let's-Encrypt-Rate-Limit (5 fehlgeschlagene Validierungen/h pro Account, 50 Certs/Woche/eTLD+1):**
   Falls DNS beim Umschalten noch nicht propagiert ist, versucht Caddy die HTTP-01-Challenge, scheitert, retryt. Bei wiederholten Versuchen → rate-limited für 1 h, im schlimmsten Fall für die ganze Woche.
   **Gegenmaßnahme:** DNS vor `docker compose up -d caddy` per `nslookup` verifizieren. Wenn DNS nicht propagiert → warten, nicht starten.

2. **HSTS-Preload auf Main-Caddyfile:**
   `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` (2 Jahre!) gilt aktuell für die nip.io-URL. Browser, die Main besucht haben, bleiben 2 Jahre an HTTPS-only für nip.io gebunden. Kosmetisch, da wir nip.io nicht mehr nutzen.

3. **nip.io nach Umschaltung:**
   URL zeigt dann SSL-Fehler (Caddy hat kein Cert mehr für diesen Host). Akzeptabel, URLs wurden nicht extern geteilt.

4. **Nameserver-Delegation falsch:**
   Falls Hetzner Registry **nicht** automatisch die Hetzner-DNS-Nameserver gesetzt hat, müssen wir sie manuell setzen. Check in 4.2.

5. **Port-80-Blockade:**
   Let's-Encrypt-HTTP-01-Challenge nutzt Port 80. UFW hat Port 80 offen (Sprint 3), kein Problem. Doppelt verifiziert in 4.4 vor Umschaltung.

### Rollback

Wenn HTTPS-Abruf nach Umschaltung fehlschlägt:

```bash
# In /opt/heizung-sonnblick/infra/deploy/.env:
PUBLIC_HOSTNAME=<alter nip.io-Wert>
docker compose -f docker-compose.prod.yml up -d caddy
```

Caddy lädt das alte Zertifikat aus `caddy_data`-Volume (persistent).

---

## Sprintplan (Phase 2)

### Sprint 4.1 — Feature-Brief (dieses Dokument)
User-Gate: freigeben oder ändern.

### Sprint 4.2 — DNS-Zone + A-Records in Hetzner DNS Console
**User-Aktion** (manuelle Webkonsole):
1. Hetzner DNS Console öffnen: https://dns.hetzner.com/
2. Zone `hoteltec.at` anlegen (falls noch nicht vorhanden — prüfen ob schon automatisch beim Registry-Vorgang erzeugt)
3. Zwei A-Records anlegen:

   | Name | Typ | Wert | TTL |
   |---|---|---|---|
   | `heizung` | A | `157.90.30.116` | 300 |
   | `heizung-test` | A | `157.90.17.150` | 300 |

4. (Falls Zone neu) Nameserver bei Registry kontrollieren — Hetzner Registry setzt automatisch die Hetzner DNS-Nameserver, aber verifizieren: `whois hoteltec.at | grep -i nserver` sollte `*.ns.hetzner.com` zeigen

**Dauer:** 10 Min.

### Sprint 4.3 — DNS-Propagation verifizieren
**PowerShell (lokal):**

```powershell
nslookup heizung.hoteltec.at
nslookup heizung-test.hoteltec.at
```

Erwartung: die jeweils konfigurierte Hetzner-IP. Wenn nicht → 5 Min warten, erneut. Alternative globaler Check: https://dnschecker.org/.

**Dauer:** 5-30 Min (Hetzner-DNS meist < 10 Min bei TTL 300).

### Sprint 4.4 — Test-Server umschalten
**SSH (lokal):**

```powershell
ssh -i $HOME\.ssh\id_ed25519_heizung root@heizung-test
```

**Auf dem Server:**

```bash
cd /opt/heizung-sonnblick/infra/deploy
# Port 80 Check
ufw status | grep 80
# .env editieren: PUBLIC_HOSTNAME=heizung-test.hoteltec.at
nano .env
# Caddy neu starten
docker compose -f docker-compose.prod.yml up -d caddy
# Logs verfolgen auf "certificate obtained"
docker compose -f docker-compose.prod.yml logs -f caddy
# (Strg+C wenn Zertifikat geholt wurde)
```

**Verifikation (lokal oder auf Server):**

```bash
curl -I https://heizung-test.hoteltec.at/
# Erwartung: HTTP/2 200, Server: <nicht angegeben>
```

**User-Gate:** Freigabe bevor Main umgeschaltet wird.

**Dauer:** 10 Min.

### Sprint 4.5 — Main-Server umschalten
Analog zu 4.4 mit `PUBLIC_HOSTNAME=heizung.hoteltec.at` auf `heizung-main`.

**Dauer:** 10 Min.

### Sprint 4.6 — Repo-Updates
**Dateien:**
- `infra/deploy/.env.example`: neue Default-Werte + Kommentar-Update
- `infra/caddy/Caddyfile.main`: Kommentar-Block aktualisieren (kein `hotel-sonnblick.at` mehr)
- `infra/caddy/Caddyfile.test`: analog
- `STATUS.md`: Sprint 4 Abschnitt + System-Tabelle aktualisiert (URLs)
- `docs/RUNBOOK.md` §9: aktuelle Werte einsetzen, „wenn externer IT" entfernen

**Dauer:** 15 Min.

### Sprint 4.7 — PR + Merge + Tag
```powershell
cd C:\Users\User\dev\heizung-sonnblick
git checkout -b feat/sprint4-domain-hoteltec
git add docs/features/2026-04-22-sprint4-domain-hoteltec.md infra/deploy/.env.example infra/caddy/Caddyfile.main infra/caddy/Caddyfile.test STATUS.md docs/RUNBOOK.md
git commit -m "feat(sprint4): domain-umschaltung auf hoteltec.at"
git push -u origin feat/sprint4-domain-hoteltec
gh pr create --base main --title "feat(sprint4): Domain-Umschaltung auf hoteltec.at" --body "..."
# nach CI grün:
gh pr merge --squash --delete-branch
git checkout main && git pull
git tag -a v0.1.4-domain-hoteltec -m "Sprint 4: Domain-Umschaltung hoteltec.at"
git push origin v0.1.4-domain-hoteltec
```

**Dauer:** 15 Min.

---

## Offene Fragen / Annahmen

- **[Annahme]** Hetzner Registry hat beim Registrieren die Hetzner DNS-Nameserver automatisch delegiert. Falls nicht, setzen wir sie in 4.2 manuell (Hetzner Registry → Domain → Nameserver).
- **[Annahme]** Die Domain ist tatsächlich schon bei Hetzner — wenn sie über einen anderen Registrar läuft, brauchen wir den zusätzlichen Schritt Nameserver-Delegation bei diesem externen Registrar.
- **[Annahme]** `caddy_data`-Volume existiert persistent auf beiden Servern und enthält das alte Zertifikat für nip.io. Rollback hängt davon ab. Bei `docker compose down -v` wäre das Volume weg — im Standard-Deploy nicht der Fall.

---

## Phase-Gates

- **Gate 1+2 (jetzt):** User liest Feature-Brief + Sprintplan, gibt frei.
- **Gate 3 (nach 4.3):** DNS propagiert, bevor wir Caddy antriggern.
- **Gate 4 (nach 4.4):** Test-Server läuft unter neuer Domain, bevor Main umgeschaltet wird.
- **Gate 5 (nach 4.7):** User bestätigt Tag + beide neuen URLs erreichbar.
