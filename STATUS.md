# Status-Bericht Heizungssteuerung Hotel Sonnblick

**Stand:** 2026-05-24. Sprints 0-12 + 12a + 12b + 12c + 12c.a + Hygiene-Mini-Sprint + 13a + 13b.1 + 13b.2 abgeschlossen. Sprint 13b.2 Tag `v0.1.18b2-device-replacement-frontend` wird in Stop 6 nach PR-Merge gesetzt; vorletzter Tag `v0.1.18b1-device-replacement-backend` (Sprint 13b.1, Squash-Commit `55a91fa`, gemerged 2026-05-23, Live-Verify auf heizung-test 2026-05-23, siehe §2au).

---

## 1. Aktueller Stand

**Stichtag:** 2026-06-02
**Letzter Tag:** `v0.1.19f-fcnt-reboot-drift` (Sprint 15c, develop-HEAD `45e7f6e` = PR #204 squash-Merge, gesetzt 2026-06-02 nach Live-Verify, §2be). Davor: `v0.1.19e-hygiene-rest` (Sprint 14e, `112b827`, §2bd), `v0.1.19d-override-sichtbarkeit` (Sprint 14d, `34ee75c`, §2bc), `v0.1.19c-cross-sicht-dashboard` (Sprint 14c, `278c2e7`, §2bb), `v0.1.19b-cross-sicht-zimmer-detail` (Sprint 14b, `a59b7aa`, §2ba), `v0.1.19a.1-cross-sicht-hotfix` (§2az), `v0.1.19a-cross-sicht-devices` (§2ay).
**Aktueller Sprint:** Sprint 15b Batterie-Skala-Fix (§2bf) — Code-Stand 2026-06-02, Branch `feature/15b-batterie-skala`, PR pending (NACH Merge: Live-Verify + Tag-Vorschlag `v0.1.19g-batterie-skala`, Name beim Tag-Schritt festziehen). Sprint 15c fcnt-Reboot-Drift-Fix davor abgeschlossen 2026-06-02 (§2be).
**Architektur-Refresh:** 2026-05-07 (`docs/ARCHITEKTUR-REFRESH-2026-05-07.md`)
**Strategie-Refresh:** 2026-05-15 (`docs/STRATEGIE-REFRESH-2026-05-15.md`,
Phasen 1-7 verbindlich, AE-51..AE-54)

### Server heizung-test

- **IP:** `157.90.17.150` (Hetzner)
- **App** (Frontend + API): https://heizung-test.hoteltec.at
  - [Annahme] FastAPI ist auf derselben Domain unter `/api/v1`
    erreichbar (Caddy-Reverse-Proxy). Falls API auf eigener Subdomain:
    Brief korrigieren.
- **ChirpStack** (LoRaWAN-Network-Server): https://cs-test.hoteltec.at
- **LoRaWAN-Gateway** (LAN-only, nicht öffentlich): siehe `RUNBOOK.md` §10a.2
- **DB-Zugang** (PostgreSQL/TimescaleDB via SSH-Tunnel): RUNBOOK-Sektion fehlt, siehe Backlog OP-5

### Server heizung-main

Noch nicht produktiv. Bootstrap in Sprint 12 (siehe `docs/SPRINT-PLAN.md`).

---

## 2. Was heute (2026-04-20) erledigt wurde

- **#17** Auto-Migration im Backend-Entrypoint (alembic upgrade head vor uvicorn)
- **#18** GHCR: GitHub Actions baut Docker-Images bei jedem Push
- **#19** Pull-basierter Deploy auf Test-Server (systemd-Timer statt SSH-Push)
- **#20** Main-Server auf gleichen Stand gebracht (Tailscale + GHCR Pull-Deploy + Auto-Migration)
- **#21** RUNBOOK.md für Troubleshooting im Repo (`docs/RUNBOOK.md`)

**Letzter Commit auf `main`:** `b5438d4` — docs: add RUNBOOK with Hetzner rescue procedures

---

## 2a. Sprint 0 Baseline (2026-04-21, abgeschlossen)

Ziel: Arbeits-Framework einführen und technische Blocker für den neuen 5-Phasen-Workflow beseitigen. Branch: `chore/sprint0-baseline`.

- ✅ **0.1 Line-Endings:** `.gitattributes` mit LF/CRLF-Regeln eingeführt — Commit `71e54b0`
- ✅ **0.2 Branch-Sync:** `develop` auf Stand `main` gezogen (content-equal, Force-Push)
- ✅ **0.3 Repo-Cleanup:** Rescue-Leftovers entfernt, `.gitignore` gehärtet — Commit `89457a2`
- ✅ **0.4 Playwright E2E:** `@playwright/test` 1.48.2, `playwright.config.ts`, 2 Smoke-Tests, neuer CI-Job `e2e` — Commit `d1a36e6`
- ✅ **0.5 STATUS-Update + Framework:** Commit `44d8110`
- ✅ **0.6 Merge & Tag:** PR `chore/sprint0-baseline → main`, CI grün, Merge, Tag `v0.1.0-baseline`, Branch-Protection auf `main` + `develop` aktiv (klassische Regeln, Repo public)

**Parallel eingeführt:**
- `docs/SPEC-FRAMEWORK.md` — verbindliche Regeln (Code, Security, DoD, Doku-Pflicht)
- `docs/WORKFLOW.md` — 5-Phasen-Feature-Flow mit expliziten User-Gates
- `docs/features/2026-04-21-sprint0-baseline.md` — Feature-Brief Sprint 0

## 2b. Sprint 1 GHCR-PAT-Rotation (2026-04-21, abgeschlossen)

Ziel: exponierten PAT ersetzen, Scope minimieren, Rotations-Verfahren reproduzierbar machen. Branch: `chore/sprint1-pat-rotation`.

- ✅ **1.1 Plan & Freigabe**
- ✅ **1.2 Neuen Classic PAT erstellt** (Scope nur `read:packages`; Fine-grained nicht möglich, da GHCR kein Packages-Scope für Fine-grained anbietet)
- ✅ **1.3 Rotation `heizung-test`** via `sprint1.3.ps1` (docker-login via SSH+stdin, Test-Pull `:develop` ok)
- ✅ **1.4 Rotation `heizung-main`** via `sprint1.4.ps1` (Test-Pull `:main` ok)
- ✅ **1.5 Verifikation Deploy-Timer** via `sprint1.5.ps1` (beide Server: `Result=success`)
- ✅ **1.6 Alter PAT `claude-sprint2-push` gelöscht** auf GitHub
- 🔄 **1.7 Doku-Update + CI-Deadlock-Fix:** RUNBOOK §6.1 neu geschrieben, dieser Status-Eintrag, Feature-Brief `docs/features/2026-04-21-sprint1-pat-rotation.md`, neuer Spiegel-Workflow `.github/workflows/frontend-ci-skip.yml` gegen Required-Check-Deadlock — **erster Durchlauf durch Branch-Protection nach Sprint 0**

**Lessons Learned:**
- Fine-grained PATs unterstützen GHCR nicht → Classic PAT zwingend, Scope minimal halten.
- PS 5.1 hat kein `ConvertFrom-SecureString -AsPlainText` → BSTR-Marshalling für Session-Env-Variable.
- PS 5.1 auf .NET Framework 4.x hat kein `ProcessStartInfo.StandardInputEncoding` → UTF-8-Bytes direkt auf `StandardInput.BaseStream` schreiben.
- Tailscale-Disconnect lässt SSH mit `BatchMode=yes` wortlos hängen → vor Rotation Tailscale-Status prüfen.
- Unit-Name auf Servern ist `heizung-deploy-pull`, nicht `heizung-deploy`.
- **Branch-Protection + Path-Filter = Deadlock:** Required Status Checks (`lint-and-build`, `e2e`) erwarten Reports, die bei `paths: frontend/**` nie kommen, wenn der PR außerhalb von `frontend/` spielt. Lösung: Spiegel-Workflow mit gleichem `name`/Job-Namen und `paths-ignore` meldet Success für alle Nicht-Frontend-PRs. Bei Frontend-PRs läuft weiterhin die echte CI.

## 2c. Sprint 1.8 Abschluss (2026-04-21, abgeschlossen)

- ✅ PR `#2` `chore/sprint1-pat-rotation → main` gemerged
- ✅ Tag `v0.1.1-pat-rotation` gesetzt
- ✅ Feature-Branch entfernt

## 2d. Sprint 2 Web-Container-Healthcheck (2026-04-22, abgeschlossen)

Ziel: `(unhealthy)`-Anzeige des `web`-Containers beheben. Branch: `fix/web-healthcheck-sprint2`.

- ✅ **2.1 Feature-Brief** `docs/features/2026-04-22-web-healthcheck.md`
- ✅ **2.2 `/api/health`-Route** in Next.js App Router (`frontend/src/app/api/health/route.ts`) — liefert JSON `{ ok, service: "web", ts }` mit `Cache-Control: no-store`
- ✅ **2.3 Dockerfile-HEALTHCHECK** umgestellt auf `node -e "fetch(...)"` (kein `wget`/`curl` im Image nötig)
- ✅ **2.4 Playwright-Smoke** für `/api/health` ergänzt (Status 200 + JSON-Shape + parsebarer ISO-Timestamp)
- ✅ **2.5 PR #3 gemerged**, Deploy auf Main — `web`-Container nach 6 Min `(healthy)`
- ✅ **2.6 Sync-PR #4** main → develop → Test-Server — `(healthy)` nach 19 h, Tag `v0.1.2-web-healthcheck`

**Lessons Learned:**
- Test-Server zieht `:develop`, Main `:main` — Fix auf `main` wirkt auf Test erst nach Sync-PR `main → develop`.
- Sync-PRs `main → develop` bewusst als **Merge-Commit** (nicht Squash), damit die Commit-Historie erhalten bleibt.
- HEALTHCHECK mit `node -e "fetch(...)"` statt `wget`/`curl` spart System-Deps im Image.

## 2e. Sprint 3 UFW-Reaktivierung (2026-04-22, abgeschlossen)

Ziel: UFW auf `heizung-main` wieder aktivieren, Test-Server konsistent bringen. Kein Branch — reine Server-Ops nach RUNBOOK §8.

- ✅ **3.1 Feature-Brief** `docs/features/2026-04-22-ufw-reactivation.md`
- ✅ **3.2 Ist-Zustand:** Main UFW inaktiv; Test UFW aktiv, aber `tailscale0`-Regel fehlte
- ✅ **3.3 Main aktiviert** mit `at`-Watchdog (5 Min Auto-Disable): Reihenfolge nach RUNBOOK §8 → `ufw --force enable`
- ✅ **3.4 Verifikation Main:** SSH via Tailscale ok, Caddy HTTPS `/` → 200, Port 22 public offen (Fallback, Entscheidung B)
- ✅ **3.5 Watchdog entfernt** (`atq` geleert, UFW bleibt aktiv bestätigt)
- ✅ **3.6 Test-Server gegengeprüft:** `ufw allow in on tailscale0` nachgezogen, damit Regelwerk identisch zu Main

**Entscheidung B (2026-04-22):** Port 22 bleibt auf beiden Servern **öffentlich offen** als Fallback für Tailscale-Ausfall. Absicherung über `PermitRootLogin prohibit-password` + `id_ed25519_heizung`.

**Stand beide Server nach Sprint 3:**
- UFW aktiv, default deny incoming / allow outgoing
- Ports 22, 80, 443 offen (v4+v6)
- `tailscale0`-Interface: allow in (v4+v6)

**Lessons Learned:**
- `at`-Watchdog (`echo 'ufw --force disable' | at now + 5 minutes`) ist bei `ufw enable` über Remote-SSH zwingend. Ohne Watchdog = potenzieller Rescue-Einsatz.
- Bei rein additiven Änderungen (`ufw allow …` ohne `enable`-Toggle) ist Watchdog verzichtbar.
- `systemctl is-active tailscaled` kann `inactive` liefern, obwohl Tailscale läuft — `tailscale status` ist die verlässliche Quelle.

## 2f. Sprint 4 Domain-Umschaltung auf hoteltec.at (2026-04-22, abgeschlossen)

Ziel: nip.io-Übergangshostnamen durch eigene Hetzner-Domain ersetzen. Branch: `feat/sprint4-domain-hoteltec`.

- ✅ **4.1 Feature-Brief** `docs/features/2026-04-22-sprint4-domain-hoteltec.md`
- ✅ **4.2 DNS-Records** in Hetzner konsoleH (Zone `hoteltec.at`, bestehend auf Robot-Nameservern `ns1.your-server.de` / `ns.second-ns.com` / `ns3.second-ns.de`):
  - `heizung.hoteltec.at` A `157.90.30.116` TTL 300
  - `heizung-test.hoteltec.at` A `157.90.17.150` TTL 300
- ✅ **4.3 DNS-Propagation** via `nslookup … 8.8.8.8` (sofortig verfügbar)
- ✅ **4.4 Test-Server umgeschaltet:** `.env PUBLIC_HOSTNAME=heizung-test.hoteltec.at`, Caddy neu, Let's-Encrypt-Cert über HTTP-01 geholt, HTTPS 200
- ✅ **4.5 Main-Server umgeschaltet:** analog mit `heizung.hoteltec.at`, HTTPS 200
- ✅ **4.6 Repo-Updates:** `.env.example` neue Defaults, Caddyfile-Kommentare aktualisiert, STATUS + RUNBOOK §9 neu geschrieben
- ✅ **4.7 PR + Merge + Tag** `v0.1.4-domain-hoteltec`

**Neuer DNS-Stand:**
- DNS-Hosting: Hetzner Online / konsoleH (URL `https://console.hetzner.com/projects/<id>/dns/<zone-id>/records`)
- Auth-NS: `helium.ns.hetzner.de`, `robotns3.second-ns.com`, `ns3.second-ns.de`
- Zertifikate: Let's Encrypt via Caddy HTTP-01, Auto-Renewal beim Container-Lifecycle
- Haupt-Domain (`@`): unberührt, zeigt auf Hetzner Webspace-Default `88.198.219.246`

**Lessons Learned:**
- Hetzner hat zwei DNS-Welten: Hetzner Cloud DNS (`dns.hetzner.com`, Nameserver `hydrogen/helium/oxygen.ns.hetzner.com`) und Hetzner Online / konsoleH (über `console.hetzner.com/projects/<id>/dns`, Nameserver `ns1.your-server.de` + `ns.second-ns.com` + `ns3.second-ns.de`). Die Domain lag schon auf konsoleH — dort weiterpflegen spart 24-48 h NS-Propagation.
- `NEXT_PUBLIC_API_BASE_URL` wird zur Build-Zeit in den Client-Bundle gemixt. Regel: **API-Calls im Frontend immer relativ** (`/api/...`), dann ist Hostname-Umschaltung unkritisch.
- Caddy-Recreate über `docker compose up -d caddy` bei geänderter `.env` startet auch dependente Services neu (web, api) — kurzer Container-Zyklus, akzeptabel.
- HTTP-01-Challenge braucht Port 80 frei — UFW-Regel aus Sprint 3 hat das bereits abgedeckt.

## 2g. Sprint 5 LoRaWAN-Foundation (2026-04-27/28, abgeschlossen)

Ziel: Komplette LoRaWAN-Datenpipeline lokal lauffaehig — ChirpStack v4 + Mosquitto + Mock-Uplink + FastAPI-MQTT-Subscriber + TimescaleDB-Persistenz + REST-API. Hardware-unabhaengig, vorbereitet fuer Sprint 6 (Hotel-LAN + echtes Pairing). Branch: `feat/sprint5-lorawan-foundation`.

- ✅ **5.1 Feature-Brief** `docs/features/2026-04-27-sprint5-lorawan-foundation.md`
- ✅ **5.2 ADR** AE-13 bis AE-18 (ChirpStack-Container, Mosquitto, Vicki-JS-Codec, MQTT-Lifespan-Subscriber, JSONB-Hypertable-Verwendung von `sensor_reading`)
- ✅ **5.3 Compose-Stack** um `mosquitto`, `chirpstack-postgres`, `chirpstack` erweitert. Konfig in `infra/mosquitto/`, `infra/chirpstack/`. Postgres-Init mit `pg_trgm`-Extension. Anonymous-Mode lokal (Bind 127.0.0.1), ACL bleibt fuer Test-Server-Sprint
- ✅ **5.4 ChirpStack initialisiert** (UI-Schritte): Tenant „Hotel Sonnblick", Application „heizung", DeviceProfile „MClimate Vicki" mit JS-Codec aus `infra/chirpstack/codecs/mclimate-vicki.js`, Gateway `simulator-gw-1`, Device `vicki-sim-001` (DevEUI `0011223344556677`)
- ✅ **5.5 Mock-Uplink** ueber `mosquitto_pub` aufs Application-Topic statt voller LoRaWAN-Frame-Simulation (chirpstack-simulator-Tool ist in v4 nicht mehr gepflegt). Test-Payload `infra/chirpstack/test-uplinks/vicki-status-001.json`
- ✅ **5.6 FastAPI MQTT-Subscriber** `heizung.services.mqtt_subscriber` als Lifespan-Background-Task. `aiomqtt` 2.x, Reconnect-Loop mit Exponential Backoff, Pydantic-Validierung, Persist via `INSERT ... ON CONFLICT (time, device_id) DO NOTHING`
- ✅ **5.7 Datenmodell**: bestehende `sensor_reading`-Hypertable um `fcnt`-Spalte erweitert (Migration 0002). KEINE neue `uplinks`-Tabelle - vorhandenes Schema deckt LoRaWAN-Telemetrie ab
- ✅ **5.8 REST-API** `GET /api/v1/devices/{device_id}/sensor-readings?from=&to=&limit=` (max 1000, time DESC), neuer Router-Aggregator unter `heizung.api.v1`
- ✅ **5.9 Unit-Tests** fuer Subscriber-Helpers + Pydantic-Schema (17 neue Tests, 27 total grün)
- ✅ **5.10 PR + Merge + Tag** `v0.1.5-lorawan-foundation`

**Gates erreicht:**
- Gate 3 (5.5): Mock-Uplink in Mosquitto sichtbar
- Gate 4 (5.6+5.7): Reading in TimescaleDB persistiert (`SELECT FROM sensor_reading` zeigt korrekte Werte)
- Gate 5 (5.10): Tag gesetzt, lokales `docker compose up` fuehrt zum sauberen Stand

**Lessons Learned:**
- ChirpStack v4 verlangt `pg_trgm`-Postgres-Extension, sonst stoppt Migration ohne Crash. Loesung: `infra/chirpstack/postgres-init/01-extensions.sql` als Init-Skript im Postgres-Container.
- Region-Config in v4: `regions.gateway.backend` ist Struct (`enabled = "mqtt"`), nicht String.
- Mosquitto auf Windows-Bind-Mount: passwd-File-Permissions sind klassisches Problem. Lokal mit `allow_anonymous true` + Bind nur 127.0.0.1 umgangen; Test-Server bekommt ACL via Linux-Bind-Mount sauber hin.
- Linenden in `backend/docker-entrypoint.sh` waren CRLF (Windows-Editor) - `exec` im Linux-Container scheiterte. `.gitattributes` greift nur bei git-Operationen, lokales Editieren kann Format brechen. Fix: `sed -i 's/\r$//'` plus Hinweis im Backlog.
- ChirpStack v4 hat den offiziellen `chirpstack-simulator` faktisch eingestellt. Pragmatik: direktes `mosquitto_pub` aufs Application-Topic mit dem bereits decoded JSON. ChirpStack ist fuer den Mock-Test Bystander; End-to-End mit Codec + Gateway-Frames kommt mit echter Hardware in Sprint 6.
- Dockerfile war auf `pip install .` (non-editable) - neue Submodules wie `api/v1/` brauchten Image-Rebuild. Auf `pip install -e ".[dev]"` umgestellt; jetzt reicht `docker compose restart api` fuer Code-Aenderungen, `build` nur bei Dependency-Aenderungen.
- Stdlib-Logging in FastAPI/Uvicorn: ohne expliziten `logging.basicConfig()` werden `logger.info()`-Aufrufe verschluckt. In `heizung.main` jetzt gesetzt.
- TimescaleDB-Constraint: jeder UNIQUE-Index muss die Partition-Spalte (`time`) enthalten. Idempotenz wird ueber den bestehenden Composite-PK `(time, device_id)` plus `ON CONFLICT DO NOTHING` erreicht; kein zusaetzliches partial-UNIQUE noetig.

**Lokale Stack-Erweiterung:**

| Service | Port (lokal) | Zweck |
|---|---|---|
| `mosquitto` | 127.0.0.1:1883 | MQTT-Broker fuer ChirpStack ↔ FastAPI |
| `chirpstack-postgres` | intern | Eigenes DB-Volume `chirpstack_db`, getrennt von Heizung-DB |
| `chirpstack` | 8080, 8081 | LoRaWAN-NS, Web-UI auf `http://localhost:8080` (admin/admin) |

**Deployment-Status:** lokal auf `work02` lauffaehig. **NICHT** auf heizung-test/main deployed - das ist Sprint 6 zusammen mit Hotel-LAN-Setup und echter Hardware.

## 2h. Sprint 6 Hardware-Pairing (in Arbeit, 2026-04-28/30)

Ziel: Milesight UG65 Gateway im Hotel-LAN, ChirpStack-Stack auf `heizung-test` deployt, erstes echtes MClimate-Vicki-Pairing mit dekodierten Werten in der TimescaleDB.

- ✅ **6.1 Feature-Brief** `docs/features/2026-04-28-sprint6-hardware-pairing.md`
- ✅ **6.2 DNS** `cs-test.hoteltec.at` → `157.90.17.150` in Hetzner konsoleH
- ✅ **6.3 Compose-Erweiterung** auf Test-Server: `mosquitto`, `chirpstack-postgres`, `chirpstack`, `chirpstack-gateway-bridge`, plus `chirpstack-init`/`chirpstack-gateway-bridge-init`-Sidecars (envsubst rendert TOMLs zur Container-Start-Zeit)
- ✅ **6.4 Caddy** `cs-test.hoteltec.at` mit Let's-Encrypt + Reverse-Proxy auf chirpstack:8080. Plus Basic-Station-WebSocket-Routen `/router*` + `/api/gateway*` zum gateway-bridge:3001
- ✅ **6.5 Test-Server-Deploy** + ChirpStack-Init (Tenant „Hotel Sonnblick", Application „heizung", DeviceProfile „MClimate Vicki" mit Codec, Admin-Passwort gesetzt). End-to-End-Mock-Pipeline per `mosquitto_pub` validiert.
- ✅ **6.6 UG65 Gateway-Konfiguration** (2026-04-30): Basic-Station-Modus crashte (`lora_pkt_fwd::instance1` crash loop trotz korrekter Caddy-WSS-Termination). Umstieg auf ChirpStack-v4-Modus — direkter MQTT vom Gateway zum Mosquitto auf Port 1883. Gateway EUI `c0ba1ffffe025b6c`, in ChirpStack-UI registriert als „UG65 Hotel Sonnblick". Stats laufen alle 30 s sauber durch.
- ✅ **6.6.1 Mosquitto Port 1883 public** (PR #13): Compose-Public-Port-Mapping + UFW-Regel auf `heizung-test`. Mosquitto laeuft anonymous, MQTT-Auth-Hardening (passwd+ACL) als Backlog M-14 fuer Sprint 8.
- ✅ **6.6.2 deploy-pull-Skript Hardening** (PRs #14, #18, #24, #26): Drei-Phasen-Logik (git-Sync + Image-Pull + Container-Up), ASCII-only, Branch-Mapping aus STAGE in `.env`. **H-6 SHA-Pinning revertiert** wegen strukturellem Tag-Mismatch zwischen CI-Build-SHA und git-log-SHA — eigener Sprint, der `build-images.yml` und `deploy-pull` synchron anpasst.
- ✅ **6.6.3 H-3 Healthz-Trennung**: Frontend-Healthcheck auf `/healthz` (K8s-Konvention, ausserhalb Caddy-`@api`-Matcher). `/health` bleibt Backend-Liveness. Beide extern erreichbar.
- ✅ **6.10 Devices-CRUD-API** `POST/GET/PATCH /api/v1/devices` mit Pydantic-Validierung (DevEUI-Hex-Check + Lowercase-Normalisierung), 17 neue Schema-Tests
- ✅ **6.7 Vicki-Pairing** (2026-05-01): Vier MClimate Vicki TRV gepaired und liefern Telemetrie. Pipeline End-to-End verifiziert (Vicki -> UG65 -> Mosquitto -> ChirpStack -> Codec -> MQTT-Subscriber -> TimescaleDB -> API -> Frontend).
  - `Vicki-001` DevEUI `70b3d52dd3034de4` (Serial MDC5419731K6UF), Setpoint 20°C, RSSI -95 dBm
  - `Vicki-002` DevEUI `70b3d52dd3034de5` (Serial DJAM419732JL7E), Setpoint 21°C, RSSI -114 dBm (grenzwertig, naeher zum UG65 stellen)
  - `Vicki-003` DevEUI `70b3d52dd3034d7b` (Serial VK5H419626LETG), Setpoint 21°C, RSSI -108 dBm
  - `Vicki-004` DevEUI `70b3d52dd3034e53` (Serial N3TA419842RE3N), Setpoint 21°C, RSSI -96 dBm
- ✅ **6.8 Codec-Validierung gegen Realdaten** (2026-05-01): Sprint-5-Foundation-Codec passte nicht. Iterationen:
  - PR #38: offizieller MClimate-GitHub-Decoder uebernommen — scheiterte an strict-mode (globale Variablen ohne `var` -> ReferenceError in ChirpStack-Goja)
  - PR #40: minimale strict-konforme Eigen-Implementierung fuer Periodic Reporting v1/v2 (Command 0x01/0x81). Verifiziert mit echtem Vicki-Frame (20°C Display matches Setpoint). snake_case-Aliase fuer FastAPI-Subscriber.
- ✅ **6.9 PR + Merge + Tag** `v0.1.6-hardware-pairing`

**Backlog (separat):**
- WT101 Milesight-Thermostat (DevEUI `24E124714F493493`) ist im Hotel verfuegbar, aber Codec fehlt. Eigener Sprint nach v0.1.6.

**Lessons Learned (bisher):**
- ChirpStack v4 macht KEINE `${VAR}`-Substitution in TOML, auch nicht via `CHIRPSTACK__SECTION__FIELD`-Env-Vars (in unserer Konstellation nicht). Fix: Init-Sidecar mit `envsubst` rendert die TOML in ein Named Volume, das ChirpStack read-only mountet.
- Permission-Issue: ChirpStack-Container-User kann standardmäßig die Bind-Mount-Configs auf Linux-Host nicht lesen. Fix: Container als `user: "0:0"` (nur Test-Stage, kein Public-Port).
- Caddy-Basic-Auth + ChirpStack-React-Frontend kollidiert wegen `crossorigin`-Asset-Loading: Browser sendet bei XHR-Fetch keinen Auth-Header, Assets bleiben 401. Fix: Basic-Auth weg, Auth via ChirpStack-eigenes Login-Formular mit gesetztem Admin-Passwort.
- `develop`-Branch hing 4 Commits hinter `main`: Sprint-3/4/5-Fixes waren auf Test-Server-Image (`:develop`) nicht enthalten. Sync-PR `main → develop` (Merge-Commit, kein Squash) bringt Sprint-Tags auf `develop`.
- Obsoleter SSH-Push-Workflow (`deploy-test.yml`, `deploy-main.yml`) entfernt — Pull-Deploy via systemd-Timer ist seit Sprint 1.x der einzige Pfad.
- UG65-Basic-Station-Modus war fuer unsere Caddy-Konstellation instabil. ChirpStack-v4-Modus mit direktem MQTT zum Mosquitto ist einfacher und stabiler — Trade-off: Mosquitto-Port oeffentlich, Auth aktuell anonymous (Backlog M-14).
- `deploy-pull.sh` Pre-Sprint-6.6.2 zog nur App-Images, ignorierte Compose-/Caddy-/Mosquitto-Aenderungen → Server-Drift gegenueber Repo. Fix: git-Sync als Phase 1, dann Pull, dann `up -d --remove-orphans` fuer alle Services.
- 2 h Hotfix-Spirale 30.04 nach H-6 SHA-Pinning-Versuch: CI taggt mit Push-Event-SHA (Merge-Commit), `git log -- backend/...` findet Source-Branch-Commit. Verschiedene SHAs bei `gh pr merge --merge` → Tag-Mismatch → Pull schlaegt fehl. Konkrete Lehren in `CLAUDE.md §5`.

## 2j. QA-Audit-Sofort-Fixes (2026-04-29, vor Pairing)

QA-Audit `docs/working/qa-audit-2026-04-29.md` hat sechs kritische Befunde aufgedeckt. Vor dem Pairing-Termin folgende Sofort-Fixes umgesetzt:

- ✅ **K-2 — Path-Validation + Exception-Handler**: `device_id` mit `Path(gt=0, le=2_147_483_647)` auf allen Routes, plus globaler Handler fuer `sqlalchemy.exc.DBAPIError → 422`. Vorher: `GET /api/v1/devices/9999999999999999999/...` lieferte 500. Jetzt: 422 mit JSON-Detail.
- ✅ **K-3 — Secrets-Validator gehaertet**: Default-`SECRET_KEY` blockiert in JEDEM ENVIRONMENT. Lokal-Backdoor via `ALLOW_DEFAULT_SECRETS=1` (im Lokal-Compose gesetzt, im Prod-Compose bewusst nicht). Tests entsprechend angepasst.
- ✅ **K-6 — Frostschutz-Konstante**: `backend/src/heizung/rules/constants.py` mit `FROST_PROTECTION_C=Decimal("10.0")`, `MIN/MAX_GUEST_OVERRIDE_C`. Regression-Tests stellen sicher, dass die Werte nicht still geaendert werden. Wichtig: solange die Cloud-Regel-Engine leer ist, garantiert nur der lokal im Vicki gesetzte Default-Setpoint Frostschutz — beim Pairing **manuell auf >= 10 °C konfigurieren**.

**NICHT mit drin (kommen als eigene Hotfix-/Sprint-Tickets):**
- K-1 API-Auth (NextAuth oder API-Key) — zu invasiv vor Pairing, eigener Sprint
- K-4 ChirpStack-Container ohne root — Defense-in-Depth, Sprint 9
- K-5 CSP-Header — Sprint 8 zusammen mit Auth
- H-4 API-Integration-Tests — Sprint 8 als Test-Foundation
- H-6 SHA-Pinning fuer GHCR-Tags — Sprint 8
- H-8 Backup-Strategie — Sprint 9
- M-Liste — rollend
- N-Liste — Polish

Test-Stand nach Sofort-Fixes: 42 Backend-Pytests gruen (vorher 32 + 7 neue + 3 angepasste).

---

## 2i. Sprint 7 Frontend-Dashboard (in Arbeit, 2026-04-28)

Ziel: Hotelier sieht auf einen Blick die LoRaWAN-Geräte mit aktuellen Reading-Werten und 24h-Verlauf. Branch: derzeit `feat/sprint6-hardware-pairing` (gemeinsamer Branch mit 6.x).

- ✅ **7.1 Feature-Brief** `docs/features/2026-04-28-sprint7-frontend-dashboard.md`
- ⏸ **7.2 shadcn/ui** bewusst verschoben — Theme-Merge mit Sprint-0-Custom-Theme (Tokens) braucht eigene Session, Init-CLI verlangt Online-Custom-Preset-UI. Stattdessen: Plain Tailwind mit unseren Custom-Tokens.
- ✅ **7.3 API-Client + TS-Typen** unter `frontend/src/lib/api/`: Device, SensorReading, DeviceCreate/Update; Fetch-Wrapper mit Timeout + Error-Handling.
- ✅ **7.4 TanStack Query** v5: QueryClientProvider in app/layout.tsx; Custom Hooks `useDevices`, `useDevice`, `useSensorReadings`, `useCreateDevice`, `useUpdateDevice`. Refetch-Intervall 30 s.
- ✅ **7.5 Geräteliste-Seite** `/devices`: Tabelle mit Label, DevEUI, Vendor, Status, Last seen. Loading-Skeleton, Empty-State, Refresh-Button.
- ✅ **7.6 Detail-View** `/devices/[id]`: Header-Card, KPI-Karten (Temperatur, Sollwert, Battery, RSSI/SNR), Recharts-LineChart 24 h Verlauf, Tabelle der letzten 20 Einzelmessungen.
- ✅ **7.7 Playwright-Smoke** 4 Tests grün: Geräteliste, Empty-State, Detail-View KPIs+Chart, 404.
- ✅ **Bonus: Design-System konsolidiert** (P1 + P2)
  - Tailwind-Token-Mapping flach gemacht: `bg-surface`, `bg-surface-alt`, `border-border` etc. funktionieren wie erwartet (vorher nested → Hover-States griffen nicht)
  - Schriftgrößen-Skala als CSS-Variable: `--font-size-xs/sm/base/lg/xl/2xl/3xl`. Body nutzt `var(--font-size-base)` → ganze App skaliert proportional bei einer Variable-Änderung.
- ✅ **7.8 Doku + PR + Tag** `v0.1.7-frontend-dashboard` (2026-05-01) — gemeinsam mit `v0.1.6-hardware-pairing` auf demselben Merge-Commit gesetzt. Frontend zeigt vier Vicki-Devices live mit KPI-Karten + Recharts-Verlauf + 30s-Refresh.

**Architektur-Entscheidungen (in ADR-Log nachzutragen):**
- AE-21: shadcn/ui-Foundation aufgeschoben, Plain Tailwind reicht für Sprint 7
- AE-22: TanStack Query v5 mit Refetch-Intervall 30 s als Standard für Server-Daten
- AE-23: Recharts für Charts (LineChart in `sensor-readings-chart.tsx` als „use client"-Komponente)
- AE-24: Next.js-Rewrite `/api/v1/*` → `http://api:8000/api/v1/*` für Server-Side-Proxy. Production-Caddy macht das gleiche extern.
- AE-25: Design-Token-System (CSS-Variables in `globals.css` + Tailwind-Mapping) als Fundament für Theme-Wechsel später (Light/Dark, Schriftgrößen-Skalierung)

**Test-Stand:**
- Backend: 27 Pytest-Tests grün (Schema, Subscriber-Helpers, Health, Models, Config) — Sprint 5/6.10
- Frontend: 4 Playwright-Tests grün (Sprint 7.7) plus 3 bestehende Smoke-Tests aus Sprint 0/2

---

## 2k. Sprint 8 Stammdaten + Belegung (2026-05-02/03, abgeschlossen)

Ziel: Vollständige CRUD-Schicht für Raumtypen / Zimmer / Heizzonen / Belegungen / Hotel-Stammdaten als Voraussetzung für die Regel-Engine in Sprint 9.

**Backend (8.1–8.7):**
- 6 neue Models: `season`, `scenario`, `scenario_assignment`, `global_config` (Singleton mit `CHECK id=1`), `manual_setpoint_event`, `event_log` (TimescaleDB Hypertable mit 7-Tage-Chunks). Erweiterungen an `room_type` (`max_temp_celsius`, `min_temp_celsius`, `treat_unoccupied_as_vacant_after_hours`) und `rule_config` (`season_id`).
- Migrationen `0003a_stammdaten_schema.py` + `0003b_event_log_hypertable.py` mit Singleton-Insert.
- 5 neue API-Module: `room_types.py`, `rooms.py`, `heating_zones.py`, `occupancies.py`, `global_config.py` — Pydantic-v2-Schemas, Zod-äquivalente Validierung, EmailStr für Alert-Adresse.
- `OccupancyService` mit `has_overlap`, `sync_room_status`, `derive_room_status` für Auto-Status-Update bei Check-in/out.
- 8 System-Szenarien als Seed (`standard_setpoint`, `preheat_checkin`, `night_setback`, etc.).

**Frontend (8.9–8.13):**
- 5 neue Routen: `/raumtypen` (Master-Detail), `/zimmer` + `/zimmer/[id]` (Liste + Tabs Stammdaten/Heizzonen/Geräte), `/belegungen` (Liste mit Range-Filter), `/einstellungen/hotel` (Singleton-Form).
- TanStack-Query-Hooks pro Domain (`hooks-room-types.ts`, `hooks-rooms.ts`, `hooks-occupancies.ts`, `hooks-global-config.ts`).
- Form-Patterns: `room-type-form`, `room-form`, `heating-zone-list`, `occupancy-form`.
- AppShell-Sidebar erweitert um 6. Eintrag (`/einstellungen/hotel`).
- 4 neue Playwright-Smokes (Sprint 8.13).

**Sprint 8.13a Hotfix:** AppShell-Doppel-Render entfernt (5 Pages wrappten zusätzlich `<AppShell>` obwohl `layout.tsx` das schon macht).

**Sprint 8.15 Hotfix Design-Konformität (2026-05-03):**
- 3 Bugs vom Hotelier nach Sprint-8-Test gemeldet: ASCII-Workaround-Umlaute, Submit-Buttons in Rosé statt Grün, Schriftgröße zu klein. Alle 3 belegt durch Design-Strategie 2.0.1 §3.2 + §6.1.
- Token-Layer korrigiert (`globals.css` + `tailwind.config.ts`): Schriftgrößen 12/14/16/18/20/24/30/36 statt 11/13/14, neue `--color-add` (#16A34A), Semantik-Farben auf Strategie-Werte.
- Neue UI-Komponenten: `Button` mit Variants `primary`/`add`/`secondary`/`destructive`/`ghost`, `ConfirmDialog` mit Fokus-Trap-Light + ESC-Close + Backdrop-Klick.
- Alle 5 Pages + 4 Form-Patterns auf neue Buttons umgebaut: „Anlegen" → grün Add, „Aktualisieren"/„Speichern" → Rosé Primary, „Löschen"/„Stornieren" → rot Destructive Outline mit Pflicht-ConfirmDialog.
- ASCII-Workarounds in allen UI-Strings durch echte Umlaute ersetzt.
- Browser-Verifikation auf `heizung-test` via Claude-in-Chrome bestätigt alle 3 Bugs gefixt.

**Schmerzpunkte (in CLAUDE.md §5.9–5.11 dokumentiert):**
- §5.9: Cowork-Mount-Sync hat `tailwind.config.ts` verschluckt — der erste 8.15-Build war ohne neue Tokens, Klassen wurden nicht generiert. Nachgereicht in PR #64.
- §5.10: `build-images.yml` reagierte auf `gh pr merge`-Push nicht zuverlässig — manueller `gh workflow run` als Sicherheits-Trigger nötig.
- §5.11: `docker compose pull` zog stale `:develop`-Tag, ohne Hinweis. Image-ID-Check nach Pull als Pflicht.

**Test-Stand nach Sprint 8:**
- Backend: 27 Pytest-Tests + 4 neue Sprint-8-Tests (Modelle, Schemas)
- Frontend: 4 Sprint-7 + 4 Sprint-8.13 Playwright-Smokes
- TypeScript strict + ESLint + `next build` grün

**Tag:** `v0.1.8-stammdaten` (2026-05-03), auf `main` gemerged via PR #65, Image gebaut + auf beide Server gepullt.

**Backlog erzeugt:**
- ConfirmDialog-Playwright-Coverage (mit Sprint 11)
- Codec-Bug Vicki `valve_position > 100%` (Task #86)
- Codec-Erweiterung fPort 2 Setpoint-Reply 0x52 (Task #87, wird in Sprint 9 ohnehin gebraucht)

---

## 2l. Sprint 9 Engine + Downlink (2026-05-03/04, in Arbeit — Walking-Skeleton fertig)

Ziel: Heizung steuert sich selbst. Belegung POST → Regel-Engine → Downlink an Vicki. Killer-Feature aus Master-Plan.

**Sub-Sprint-Stand:**

- ✅ **9.0** Codec mclimate-vicki.js fPort 1+2 + Encode 0x51 + valveOpenness-Clamp (15 Tests, ChirpStack-UI deployed)
- ✅ **9.0a** Subscriber liest valve_openness statt motor_position + skip setpoint_reply
- ✅ **9.1** Celery + Redis Worker-Container (Compose-Service celery_worker, concurrency=2, healthcheck `inspect ping`)
- ✅ **9.2** Downlink-Adapter (build_downlink_message + send_setpoint via aiomqtt, Topic application/{APP_ID}/device/{DevEUI}/command/down)
- ✅ **9.3** Engine-Skeleton: LayerStep + RuleResult + layer_base_target + layer_clamp + hysteresis_decision (23 Tests)
- ✅ **9.4-5** evaluate_room-Task mit echter Logik (statt Stub) + Trigger in occupancies POST/Cancel + GET /rooms/{id}/engine-trace + EventLogRead-Schema
- ✅ **9.6** Live-Test BESTANDEN: Vicki-001 zeigte 18°C nach Engine-Trigger (validiert mit Vicki-Display und ChirpStack-Queue-Eintrag)
- ✅ **9.6a** Hotfix devEui im Downlink-Payload (ChirpStack v4 Pflicht — sonst stilles Discard)
- ✅ **9.6b** Bug-Cleanup: Frontend-Link-Bug, Hard-Clamp-Reason durchreichen, pool_pre_ping=False + Worker-Engine-Reset, UI-Stale-Hinweis
- ✅ **9.10** Frontend EngineDecisionPanel: Tab "Engine" im Zimmer-Detail mit Schicht-Trace + Vorherige Evaluationen + Refetch 30s
- ⏸ **9.7** Sommermodus (Layer 0) + Celery-Beat-Scheduler (60s autonomes Re-Eval)
- ⏸ **9.8** Layer 2 Temporal (Vorheizen 60min vor Check-in + Nachtabsenkung)
- ⏸ **9.9** Layer 3+4 Manual + Window
- ⏸ **9.11** Live-Test #2 mit allen Layern
- ⏸ **9.12** Doku + PR develop→main + Tag v0.1.9-engine

**Architektur-Bestaetigungen (Live-Test 2026-05-03):**
- AE-32 (Hysterese 1 °C statt 0.5 °C) durch Vicki-Spike + Live-Run validiert
- Engine-Decision-Panel zeigt korrekte Layer-Trace mit setpoint_in/setpoint_out + reason + detail-JSON
- ChirpStack-App-ID `b7d74615-6ea9-4b54-aa05-fd094e3c2cae` in heizung-test/.env, in Codec auch eingetragen
- Vicki-001 (DevEUI 70b3d52dd3034de4) in Heizzone "Schlafzimmer" id=91 von Zimmer 101

**Lessons in CLAUDE.md §5.12-5.17 dokumentiert:**
- §5.12 PowerShell `$ErrorActionPreference` greift nicht fuer native CLI-Tools
- §5.13 ChirpStack v4 verlangt devEui im Payload
- §5.14 Celery-Worker braucht Engine-Reset pro Forked-Process
- §5.15 event_log wird bei manueller Cleanup nicht mitcleared
- §5.16 Next.js Object-href cast resolved nicht zu Path-Param
- §5.17 docker logs --since nach Container-Restart leer

**Tag (geplant):** `v0.1.9-rc1-walking-skeleton` auf develop nach Sprint 9.6b. Final-Tag `v0.1.9-engine` auf main erst nach 9.7-9.12.

**Test-Stand nach Sprint 9.6b:**
- Backend: 27 + 4 + 4 (downlink) + 23 (engine) + 3 (celery) = 61 Pytest-Tests
- Codec: 15 Node-Tests
- Frontend: keine neuen Playwright-Smokes — Engine-Panel nur live-getestet (Sprint 11 Backlog)

**Backlog erzeugt:**
- Engine-Trace-API: stale event_log nach Bug-Fix-Roundtrip (manuelle DB-Clean noetig)
- ChirpStack-Bootstrap-Skript fuer reproduzierbares Codec-Setup (war im Sprint 6 Backlog, bestaetigt)
- pool_pre_ping=False als Workaround — sauberer Fix wenn asyncpg + celery besser integriert werden (Sprint 14+)
- Mosquitto-Reconnect-Spam bei heizung-api-Subscriber (kosmetisch, nicht-blockierend)

---

## 2m. Sprint 9.8c Hygiene-Sprint (2026-05-05, abgeschlossen)

Ziel: Repo-Hygiene zwischen Sprint 9.8 und Sprint 9.9. Veraltete Doku, Windows-Build-Bug, Lint-Warnings, fehlende Backlog-Notiz.

**Tasks:**

- ✅ **T0a CLAUDE.md auf Sprint 9.8 ziehen** — Mojibake bereinigt, §1 Stand auf 9.8c gezogen, §3 Goldene Regeln 4/6/7 erweitert, §3 Regel 10 ersetzt durch Claude-Code-Workflow, §4 Container-Stack vollständig (13 Services + 2 Init-Sidecars), §5.2 als HISTORISCH markiert. PR #84.
- ✅ **T0b STATUS.md auf Sprint 9.8 ziehen** — Header-Datum 2026-05-05, §4 Architektur-Stand mit Versionen + 14 Modellen + Engine-Status, §5 neue Routen-Übersicht (Frontend-Pages + Backend `/api/v1/...`), §5a alte Doku-Sektion umbenannt, §6 Pipeline-Modell, §9 Tag-Tabelle vollständig (10 Tags). PR #85.
- ✅ **T1 Windows-Build-Reparatur** — `frontend/src/app/icon.tsx` (next/og ImageResponse, brach Windows-Build mit „Invalid URL") durch statisches `icon.png` ersetzt (512×512, Brand-Rosé `#DD3C71`, Roboto Bold „H" via System.Drawing). PR #86.
- ✅ **T2 Backlog-Notiz e2e-Smoketests** — STATUS.md §6 ergänzt um Mini-Sprint-Notiz für Sprint-8-Routen-e2e-Coverage (Architektur-Entscheidung Mocking vs. Container in CI offen). Commit `57be5af` auf chore-Branch.
- ✅ **T5 ESLint-Warnings beheben** — Material-Symbols-Outlined selbst gehostet (Static-Cut v332, 309 KB woff2, Apache 2.0), `<head>`-Block aus `layout.tsx` entfernt. Beide Warnings (`google-font-display`, `no-page-custom-font`) weg, DSGVO-Vorteil (keine Direktladung von fonts.googleapis.com). PR #87.
- ✅ **T6 README + Abschluss-Doku** — README-Status, Stack-Sektion mit Versionen + Engine + DSGVO-Hinweis, ADR-Range AE-38, Tag-Tabelle bis v0.1.9-rc1. STATUS.md §2m + §6 finalisiert.

**Tag-Vergabe:** Keiner. Hygiene-Sprint ohne Funktions-Änderung.

**Lessons Learned:**
- Render-Wrap-Artefakt bei langen PowerShell-Skript-Zeilen — Lösung: Type-Aliase + Backtick-Continuation, alle Zeilen <80 Zeichen halten.
- curl-WD-Bug: relative Pfade im curl `-o`-Argument hängen WD-Prefix dran; Bash-Tool persistiert WD zwischen Calls nicht zuverlässig. Lehre: absolute Pfade oder `cd` zum Repo-Root vor curl.
- Material-Symbols Variable-Font ist 3.74 MB, Static-Cut 309 KB. Subset auf tatsächlich genutzte Glyphen scheitert am dynamischen `{children}`-Pattern in Icon-Components.
- `npm run build` validiert URL-References in CSS NICHT zur Build-Zeit — Asset-Existenz wird erst zur Runtime im Browser geprüft. Lokaler Build kann grün sein trotz fehlender Asset.

---

## 2n. Sprint 9.8d shadcn/ui-Migration (2026-05-05/06, abgeschlossen)

Ziel: shadcn/ui als Foundation für Frontend-Komponenten einführen, bestehende Komponenten schrittweise migrieren. Brand-Identität (Design-Strategie 2.0.1) bleibt erhalten.

**Tasks:**

- ✅ **T1 shadcn-Foundation** (PR #89, Commit `513fb84`): shadcn 2.1.8 (Tailwind-v3-kompatibel) initialisiert. `components.json` mit `style: default`, `baseColor: slate`, `iconLibrary: lucide`. `tailwind.config.ts` erweitert um `darkMode: ["class"]`, 11 shadcn-Color-Slots (`background`, `foreground`, `card`, `popover`, `secondary`, `muted`, `accent`, `destructive`, `input`, `ring`), `plugins: tailwindcss-animate`. `globals.css` um 19 HSL-Tokens in `@layer base { :root }` erweitert, `--primary` und `--ring` auf Brand-Rosé `#DD3C71` (HSL `340.3 70.3% 55.1%`). Bestehende Custom-Tokens (`--color-*`, `borderRadius`, `fontFamily.sans`) byteweise erhalten. Neue Dependencies: `class-variance-authority ^0.7.1`, `lucide-react ^1.14.0`, `tailwindcss-animate ^1.0.7`. Build grün, 12 Routes.
- ✅ **T2 Button-Migration** (PR #90, Commit `4956ae3`): `button.tsx` auf cva-Pattern umgestellt. 5 Variants erhalten (`primary`, `add`, `secondary`, `destructive`, `ghost`), 3 Sizes erhalten (`sm`, `md`, `lg`), Custom Props erhalten (`icon`, `iconSize`, `loading`). `asChild`-Prop ergänzt via `@radix-ui/react-slot ^1.2.4` (shadcn-Standard). `secondary` und `destructive` bewusst Outline statt shadcn-Default-solid (Design-Strategie 2.0.1 §6.1). API abwärtskompatibel — alle 10 importierenden Files (5 Pages + 4 Patterns + ConfirmDialog) compilieren ohne Änderung. Visuelle Cowork-QA gegen heizung-test bestätigt: alle Variants spec-konform, B-1 (Focus-Ring) nach Live-Deploy WCAG 2.4.7 erfüllt.
- ✅ **T3 ConfirmDialog-Migration** (PR #92, Commit `b49cd7e` Initial-Migration; Hotfix PR #94, Commit `54ad897` Button-Stil + ESC-Safety-Net; Final-Hotfix PR #95, Commit `ee3d51a` Radix-natives `onEscapeKeyDown`): `ConfirmDialog` rendert intern Radix `AlertDialog`, externe Props-API unverändert, alle 4 Call-Sites kompilieren ohne Touch. Cowork-QA: alle DOM-Marker bestätigt (`role="alertdialog"`, `data-state`, `aria-describedby`, Fokus-Trap, Initial-Fokus auf Cancel), Button-Stil nach Spec (destructive-Outline), ESC schließt, Outside-Click blockiert.
- ✅ **T4 Vorrats-Komponenten** (PR #93, Squash-Merge `3067df01`): `dialog.tsx` (122 Z.), `select.tsx` (160 Z.), `input.tsx` (22 Z.) via `npx shadcn@2.1.8 add dialog select input`. Keine Call-Sites, reine Vorratshaltung. Dependencies: `@radix-ui/react-dialog ^1.1.15`, `@radix-ui/react-select ^2.2.6`.

**Tag-Vergabe:** Keiner. Final-Tag `v0.1.9-engine` kommt nach Sprint 9.9–9.12 wie geplant.

**Lessons Learned:**
- shadcn 2.1.8 schreibt **OKLCH** in `globals.css`, aber `hsl(var(--xxx))`-Wrapper in `tailwind.config.ts` — interne Inkonsistenz, kaputte Farben zur Laufzeit. Workaround: tailwind-config + globals.css revertieren, manuell **HSL** in beiden konsistent setzen.
- shadcn 2.1.8 verweigert Init bei existierender `components.json` ("To start over, remove the components.json file"). Pre-write + Init scheitert. Pfad: `rm components.json` → `init --defaults` → manuell überschreiben.
- Auto-Init in `tailwind.config.ts` zerstört bestehende Custom-Tokens (`colors.primary` mit hover/active/soft, `colors.border`, `borderRadius.sm/md/lg`). **Revert + hand-crafted Merge** ist der einzige sichere Weg.
- cva-Base-Klasse: `focus-visible:outline-none` ohne Ersatz-Ring ist A11y-Bug (WCAG 2.4.7). **Pflicht:** explizit `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ring-offset-background` anhängen.
- Material Symbols Variable-Font ist 3.74 MB, Static-Cut 309 KB — Subset-Refactor scheitert am dynamischen `{children}`-Pattern in Icon-Components (T1-Backlog).
- `heizung-test` deploy-pull-Service braucht `git config --system --add safe.directory ...`. **`--global` greift im systemd-Service-Kontext nicht** trotz `User=root` und `HOME=/root` (vermutlich systemd-Sandbox). Siehe CLAUDE.md §5.7 Korrektur.
- shadcn-Generate referenzieren teils `buttonVariants({variant:"outline"})`. T2-Button hat kein `outline` → TS-Strict-Bruch. Anpassung auf `"secondary"` in `alert-dialog.tsx` nötig. Bei `dialog`/`select`/`input` nicht aufgetreten.
- shadcn-`AlertDialogAction`/`AlertDialogCancel` rendern per Default `buttonVariants()` im Wrapper-Element. Mit `asChild` + T2-Button als Child gewinnt der Wrapper-Default die Tailwind-Cascade gegen die Child-Variante → Button rendert solid statt Outline. Fix: `buttonVariants` aus `alert-dialog.tsx` entfernen, `asChild` greift dann sauber durch.
- Radix-`AlertDialog` nutzt `useEscapeKeydown` auf document-Level. Ein React-`onKeyDown` auf `AlertDialogContent` feuert nicht — Radix fängt das Event davor ab. Korrektur: Radix-native Prop `onEscapeKeyDown` direkt auf `AlertDialogContent` setzen, mit `if (loading) event.preventDefault()` als einziger Override.
- "Build grün + API-kompatibel" ist KEIN Migrationsnachweis bei Komponenten-Migrationen. Pflicht-Akzeptanzkriterium ab jetzt: DOM-Marker-Check im laufenden Browser (z.B. `document.querySelector('[role="alertdialog"]')`).
- Live-QA von Feature-Branches setzt Merge nach `develop` voraus (heizung-test pullt `:develop`-Tag). Reihenfolge ab jetzt: Phase 2 → CI → Merge → Deploy → QA. T3.4/T3.5-Trennung obsolet.
- PowerShell `;` ist nicht `&&` — `Set-Location`-Fehler bricht nicht ab, nachfolgendes `npx` läuft trotzdem. Vor `shadcn add` immer `Get-Location` verifizieren.
- Browser-Cache nach Frontend-Deploy: Hard-Reload (Strg+Shift+R) ist Pflicht-Schritt vor jeder Live-QA. Sonst falsche Befunde am alten Bundle.

## 2o. Sprint 9.9 Manual-Override / Engine Layer 3 (2026-05-06, abgeschlossen)

Ziel: Engine berücksichtigt manuelle Setpoint-Übersteuerungen aus Vicki-Drehknopf und Frontend-Rezeption mit definierten Ablaufzeiten und Sicherheitsnetzen. Quelle und Hardware via Adapter-Pattern abstrahiert (siehe AE-39).

**Tasks:**

- ✅ **T1 Datenmodell + Migration** (`2ba7693`): `manual_override`-Tabelle, `OverrideSource`-Enum, Pydantic-Schemas, Alembic `0008_manual_override`. INTEGER-PK/FK statt UUID (Repo-Konvention), Index ohne `NOW()` im Predicate.
- ✅ **T2 `override_service` Domain-Logik** (`d1bb99e`): 7 Funktionen (`compute_expires_at`, `create`, `get_active`, `get_history`, `revoke`, `revoke_device_overrides`, `cleanup_expired`). Decimal-Hygiene + 7-Tage-Hard-Cap für alle Quellen.
- ✅ **T3 Engine Layer 3** (`bdb2af7` + `2 fixes`): `layer_manual_override` in `rules/engine.py` zwischen Layer 2 und Layer 5. Läuft IMMER (auch no-op) für Trace-Sichtbarkeit. `LayerStep.extras: dict | None` additive Erweiterung; `engine_tasks` merged ins `event_log.details`-JSONB.
- ✅ **T4 REST-API** (`534d708` + 5 fixes): `GET/POST /api/v1/rooms/{id}/overrides`, `DELETE /api/v1/overrides/{id}`. `X-User-Email`-Header → `created_by`. `frontend_checkout` ohne Belegung → 422.
- ✅ **T5 Vicki Device-Adapter** (`a3e32aa` + 2 fixes): Diff-Detection gegen letzten ControlCommand mit Toleranz-Modi (`0.6` für fPort 1, `0.1` für fPort 2) und 60s-Acknowledgment-Window. Hook im `mqtt_subscriber` für beide Pfade. `next_active_checkout` in `services/occupancy_service` konsolidiert.
- ✅ **T6 PMS-Auto-Revoke** (`cc09a34`): Hook `auto_revoke_on_checkout` in `services/override_pms_hook`. `OCCUPIED → VACANT` ohne Folgegast in 4 h → revokt nur `device`-Overrides, Frontend bleibt. Lazy-Import in `sync_room_status` gegen Circular.
- ✅ **T7 Daily-Cleanup-Job** (`d3274d7`): celery_beat-Task `heizung.cleanup_expired_overrides` `crontab(hour=3, minute=0)`. Eigene Engine pro Run (Pool-Pollution-Fix Sprint 9.7a).
- ✅ **T8 Frontend Override-UI** (`e5aed26`): 5. Tab „Übersteuerung" auf `/zimmer/[id]`. Aktiv/Anlage-Card + Historie-Tabelle. T4-Vorrats-Komponenten (Input, Select) genutzt. Decimal als String durchgängig.
- ✅ **T9 Engine-Decision-Panel-Erweiterung** (Teil von T9-Commit): Layer-3-Detail mit Source-Badge + `expires_at` + Restzeit-Countdown. Helper `useRemainingTime` + Source-Mappings nach `lib/overrides-display.ts` extrahiert.
- ✅ **T10 Doku** (Merge-Commit): AE-39 in `ARCHITEKTUR-ENTSCHEIDUNGEN.md`, Feature-Brief in `docs/features/`, STATUS.md §2o, CLAUDE.md §6 Pre-Push-Routine.

**Tag-Vergabe:** Keiner. Final-Tag `v0.1.9-engine` kommt nach Sprint 9.10–9.12.

**Lessons Learned:**
- `ruff format` kollabiert Single-Line-Funktionssignaturen unter 100 Zeichen — multi-line nur wenn echt zu lang. T1–T5 haben das in 5 Format-Iterationen gelernt.
- Ruff-isort-Default klassifiziert `alembic` (Top-Level) als first-party (wegen `backend/alembic/`-Verzeichnis), `alembic.config` als third-party. Imports landen in unterschiedlichen Sections — kontraintuitiv, aber linter-erzwungen.
- `room.number` ist `VARCHAR(20)` — Test-Suffixe vorab gegen Schema-Limits prüfen.
- API-Tests mit DB: `httpx.AsyncClient` + `ASGITransport` + `app.dependency_overrides[get_session]` für Pool-Sharing zwischen Setup und App. `alembic upgrade head` als `pytest_asyncio.fixture(scope="module", autouse=True)` mit `asyncio.to_thread` (alembic env.py macht intern `asyncio.run` und kollidiert sonst mit pytest-asyncio-Loop).
- `LayerStep`-Erweiterung um optional `extras: dict[str, Any]`: additive Änderung, JSONB-flexibel, kein Schema-Update am Engine-Trace-Endpoint nötig.
- Lazy-Import bei Service↔Service-Circular-Risiko (z.B. `override_pms_hook` ↔ `occupancy_service`). Backlog-Item: `services/_common.py` für plattformneutrale Helpers.
- **Pre-Push-Toolchain** (CLAUDE.md §6) spart 1–2 Min pro Task gegenüber CI-only-Workflow. T6–T8 hatten CI-grün auf Anhieb; T1–T5 hatten zusammen ca. 15 Min Format-Iteration.
- `next_active_checkout`/`next_active_checkin` in `services/occupancy_service` zentral konsolidiert — von API, Engine, PMS-Hook und Device-Adapter geteilt. `rules/engine._load_room_context` behält die Inline-Query (anderer Lifecycle).

---

## 2p. Sprint 9.10 Window-Detection / Engine Layer 4 (2026-05-07, abgeschlossen)

Ziel: Engine reagiert auf Vicki-Fenster-offen-Sensor und senkt den Setpoint auf System-Frostschutz, solange ein frisches Reading `open_window=true` meldet. Race-Condition aus dem MQTT-Reading-Trigger gleich mit-gefixt (T3.5 vorgezogen).

**Tasks:**

- ✅ **T1 Persistenz-Fix `sensor_reading.open_window`**: Migration `0009_sensor_reading_open_window` (Boolean NULL), Modell + `SensorReadingRead`-Schema erweitert, MQTT-Subscriber liest `obj.openWindow` (camelCase wie vom Codec geliefert). NULL = Feld fehlte im Payload, NICHT False. 3 neue Pytests (true / false / missing→None).
- ✅ **T2 Engine Layer 4 Window-Detection**: `layer_window_open` in `rules/engine.py` zwischen Layer 3 (Manual) und Layer 5 (Clamp). DISTINCT-ON-Query `SensorReading → Device → HeatingZone.room_id`, Filter `now - 30min`. Aktiv → `MIN_SETPOINT_C=10` + `reason=WINDOW_OPEN` + extras `{open_zones, occupancy_state}`. Passthrough mit Detail-Diagnose `no_readings | stale_reading | no_open_window`. Signatur erweitert um `room_status`/`now` für Test-Determinismus. 7 DB-Tests, alle gegen echte TimescaleDB grün.
- ✅ **T3 Re-Eval-Trigger im MQTT-Subscriber**: `_persist_uplink` ruft nach `commit()` `evaluate_room.delay(room_id)` über Device→HeatingZone-Join. Edge-Case `device.heating_zone_id IS NULL` → Warning-Log, kein Trigger. 2 neue Pytests (mocked `SessionLocal` + `evaluate_room.delay`).
- ✅ **T3.5 Engine-Task-Lock via Redis-SETNX (vorgezogen aus 9.10a)**: `services/engine_lock.py` mit `try_acquire(room_id, ttl_s=30)` / `release(room_id)`. `evaluate_room` umrahmt: SETNX-Acquire → bei Konflikt `apply_async(countdown=5)` (kein Drop, Re-Trigger), sonst `try/finally` mit `release`. ADR **AE-40** dokumentiert die Entscheidung. Aspirativer celery_app.py-Kommentar aus Sprint 9.6 ersetzt durch Verweis auf AE-40. 8 Pytests (FakeRedis-Mock × 4 + Task-Wrapper × 4) plus Live-Smoke gegen Compose-Stack: 10 Threads gegen denselben Lock → genau 1 gewinnt; 5×`evaluate_room.delay` → alle 5 `lock_busy_retriggered`, danach Re-Trigger-Generationen konvergieren in `skipped_no_room`. Bonus: 1631 Null-Bytes im ADR-File mit-bereinigt (CLAUDE.md §5.2-Pollution).
- ✅ **T4 Frontend Window-Indikator im Engine-Panel**: `WindowOpenIndicator` + `extractWindowOpenSince` in eigener Datei `engine-window-indicator.tsx` (kein TanStack-Query-Plumbing für Proof-Script). Material-Symbol-Glyph **`window`** als Static-Cut-Fallback (`sensor_window_open` per fonttools-Inspektion NICHT im 317-KB-Subset enthalten — Backlog B-9.10-3). Brand-Rosé `text-primary`, Tooltip `Fenster offen seit HH:MM` (de-AT), DOM-Marker `data-testid="window-open-indicator"`. Mock-Render-Beweis via `scripts/dom-marker-proof.tsx` (`renderToString`): positiver Pfad rendert Marker, 3 negative Pfade (leer / kein window_safety / fehlendes Feld) rendern keinen.
- ✅ **T5 Sprint-Doku + Backlog**: dieser STATUS.md-Eintrag, CLAUDE.md §1 + neue Lessons §5.18 / §5.19, AE-40 in `ARCHITEKTUR-ENTSCHEIDUNGEN.md`.

**Engine-Pipeline-Stand:** Layer 0 / 1 / 2 / 3 / **4 (NEU)** / 5 + Hysterese — alle aktiv. Layer 4 überschreibt auch Manual-Override → Sicherheit > Komfort.

**Test-Stand:** 190 passed (vorher 182 + 7 Layer-4-DB-Tests + 8 Lock-Tests + 2 T3-Trigger-Tests + 3 open_window-Mapping-Tests). Pre-existing psycopg2-Failures in `test_manual_override_model.py` (7 Errors) + `test_migrations_roundtrip.py` (3 Failures) sind unverändert — kein 9.10-Bezug, Backlog für nächsten Hygiene-Sprint.

**Worker-Setup-Hinweis:** Dev-Compose hat keinen `celery_worker`-Service. Lokaler Worker-Aufruf für T3.5-Smoke unter Windows:

```powershell
celery -A heizung.celery_app worker --concurrency=2 --pool=threads `
       --without-heartbeat --without-gossip --without-mingle -Q heizung_default
```

`--pool=threads` statt prefork (Windows-Limitation). Die Compose-Erweiterung um einen `celery_worker`-Container wäre eigener Mini-Sprint.

**Ad-hoc-Frage „evaluate_room für nicht-existente room_id":** sauber abgefangen. `engine_tasks.py:127-132` returnt `{status: "skipped_no_room"}` mit `WARNING`-Log und ohne State-Mutation, wenn `_engine_evaluate_room` `None` liefert. Im T3.5-Live-Smoke gegen Room=99999 wurde dieser Pfad ~10x durchlaufen — keine Side-Effects, keine Exceptions.

**Tag-Vergabe:** Vorschlag `v0.1.9-rc3-window-detection` nach Sprint-Merge. Final-Tag `v0.1.9-engine` weiterhin nach 9.11/9.12.

**Lessons Learned:**
- **Test-Fixtures müssen Schema-Constraints respektieren**: `room.number` ist `VARCHAR(20)`, `device.dev_eui` ist `VARCHAR(16)`. Mein erster Layer-4-Fixture-Suffix `t9-10-l4-{HHMMSSffffff}` (21 Zeichen) hat alle 7 Tests gleichzeitig gekippt. Robuste Suffix-Strategie: `uuid.uuid4().hex[:8]` + kurzer Präfix (3-5 Zeichen) — passt in alle bekannten String-Limits dieses Repos.
- **Live-DB-Verify ist Pflicht-Schritt zwischen DB-erzeugenden und DB-konsumierenden Tasks**: T1 hat `0009_sensor_reading_open_window` geschrieben, T2 hat darauf gebauten Engine-Code geschrieben. Erst der explizite Zwischen-Schritt — Compose-Stack hochfahren, `alembic upgrade head` gegen echte TimescaleDB, `pytest mit TEST_DATABASE_URL` — hat den `String(20)`-Bug aufgedeckt. Pure-Function-Tests laufen lokal grün, aber blind. Ergänzung zur Pre-Push-Routine in §6 angedacht für nächsten Hygiene-Sprint.
- **Aspirative Code-Kommentare sind Doku-Drift**: `celery_app.py:60-61` versprach seit Sprint 9.6 einen Redis-SETNX-Lock, der nie geliefert wurde. Drei Folgesprints haben Tasks darauf gestapelt, ohne dass der Lock real war. Pflicht-Stop-Trigger: TODO/FIXME/„kommt in Sprint X" in produktiver Steuer- oder Sicherheitslogik gehört in den Sprint-Plan, nicht als Kommentar im Code.
- **Static-Cut-Fonts brauchen Glyph-Inventarisierung vor UI-Design**: `fontTools.ttLib.TTFont('...woff2').getBestCmap()` listet alle ~4300 enthaltenen Glyphen. `sensor_window_open` (vom Brief gewünscht) ist NICHT enthalten, `window` (Brief-Fallback) ist enthalten. Static-Cut-Erweiterung erfordert eigenen Mini-Sprint mit Re-Generation des Subset-Fonts → Backlog B-9.10-3.
- **`tsx`-Runner mit Path-Aliases + JSX**: bei `package.json` ohne `"type": "module"` transpilieren `.tsx`-Dateien zu CJS — named imports aus `.mjs`-Entry sehen nur `default` + `module.exports`. Saubere Lösung: Proof-Script selbst als `.tsx`, plus einmal `import * as React from "react"` im Helper (Tree-Shaking macht das im Next.js-Build wieder weg).

---

## 2q. Sprint 9.10b Stabilitätsregeln-Verankerung (2026-05-07, abgeschlossen)

Ziel: Stabilität als oberste Systemregel und Autonomie-Default für Claude Code formal im Repo verankern. Reine Governance-Doku, kein Code-Pfad, kein CI-Risiko. Anlass: Race-Condition aus Sprint 9.10 (siehe §5.20 / AE-40) hat gezeigt, dass Stabilitätsprinzipien explizit gemacht werden müssen, statt implizit auf Sprint-Ebene auszuhandeln.

**Tasks:**

- ✅ **T1 CLAUDE.md §0 — Stabilitätsregeln S1-S6** (oberste Priorität, vor §1) inkl. Eskalations-Regel und expliziten Nicht-Zielen. Bestehende §-Nummerierung unverändert.
- ✅ **T2 CLAUDE.md §0.1 — Autonomie-Default Stufe 2** (Pflicht-Stops 1-9, Auto-Continue-Liste, Berichts-Format, Eskalation bei Unsicherheit, Sprint-spezifische Stufen 1/2/3).
- ✅ **T3 CLAUDE.md §2 Pflicht-Lektüre** um Punkt 0 (Verweis auf §0 + §0.1) erweitert; Punkte 1-6 unverändert.
- ✅ **T4 ADR AE-41** in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` angelegt — Format konsistent zu AE-40 (Status / Kontext / Entscheidung / Konsequenzen / Querverweise).
- ✅ **T5 README.md** um Abschnitt „Stabilitätsregeln" zwischen Dokumentation und Stack ergänzt — kein Vollabdruck, nur Verweis auf CLAUDE.md §0 + §0.1.
- ✅ **T6 Sprint-Brief** `docs/features/2026-05-07-sprint9-10b-stability-rules.md` + dieser STATUS-Eintrag.

**Tag-Vergabe:** Keiner — Governance-Sprint, kein Feature.

**Verweise:** CLAUDE.md §0, §0.1, §2 (Pflicht-Lektüre Punkt 0), ADR AE-41.

**Test-Stand:** unverändert (kein Code-Pfad).

---

## 2r. Sprint 9.10c Vicki-Codec-Decoder-Fix (2026-05-07, abgeschlossen)

Ziel: Cowork-QA aus Sprint 9.10 hatte aufgedeckt, dass `sensor_reading` nur `fcnt/rssi/snr` befüllt, alle aus dem Codec-`object` gelesenen Felder (`temperature/setpoint/valve_position/battery_percent/open_window`) seit dem Sprint-9.0-Codec-Refactor durchgängig NULL. Engine-Layer 1/4 hatten dadurch keine Ist-Daten — Sprint 9.11 (Live-Test #2) wäre blockiert.

**Phase-0-Befund (H4, neu):** Codec-Routing-Bug. Die Vickis senden Periodic Status Reports auf **fPort=2** (cmd-Byte `0x81`). Der Codec routete `fPort===2` jedoch hartcodiert in `decodeCommandReply`, der nur `cmd=0x52` versteht — Periodics wurden als `unknown_reply` abgewürgt, kein Sensor-Feld im `object`. Live-Beleg per `mosquitto_sub` auf heizung-test (2026-05-07T10:00:04Z, dev_eui 70b3d52dd3034de4, fcnt 895): `{"fPort":2, "data":"gRKdYZmZEeAw", "object":{"command":129, "report_type":"unknown_reply"}}`.

**Lösung:** Cmd-Byte-Routing über `bytes[0]` statt fPort. fPort wird redundant für das Routing.

**Tasks:**

- ✅ **T1a Codec-Fix** `infra/chirpstack/codecs/mclimate-vicki.js`: `decodeUplink` routet jetzt `cmd === 0x52 -> decodeCommandReply`, sonst `decodePeriodicReport`. Header-Kommentar um Sprint-9.10c-Eintrag erweitert. 4 neue Regression-Tests in `test-mclimate-vicki.js` (Periodic v2 auf fPort 2, Periodic v1 auf fPort 1, Setpoint-Reply auf fPort 2, Setpoint-Reply ohne fPort), Test 12 angepasst (vorheriges fPort-2-unknown-reply-Verhalten war ein Bug-Symptom). **19/19 Tests grün.**
- ✅ **T1b Subscriber-Kommentar-Update** `services/mqtt_subscriber.py`: Sprint-9.0-Kommentar zu „fPort 2 = Reply" präzisiert auf `report_type == 'setpoint_reply'`. §5.20-Anwendung. Funktional unverändert.
- ✅ **T1c ChirpStack-UI-Re-Paste** auf heizung-test: Codec im ChirpStack-Device-Profile „Heizung" durch Sprint-9.10c-Stand ersetzt (manueller UI-Schritt). Ab Strategie-Chat-Zeitstempel `2026-05-07 ~10:58` greift der neue Codec.
- ✅ **T1d Backend-Pytest** `test_mqtt_subscriber.py`: neuer Test `test_map_to_reading_live_codec_output_fport2_periodic` mit vollem Live-Codec-Output-Fixture (fPort=2, cmd=0x81, alle Sensor-Felder). **141 passed, 62 skipped (lokal ohne TEST_DATABASE_URL).**
- ✅ **T2 Live-Smoke heizung-test:**
  - **Subscriber-Logs Vorher/Nachher:** bis 10:55:57 alle Vickis `temp=None setpoint=None`; ab 11:00:18 Vicki-001 (de4) `temp=22.71 setpoint=18.0`, gefolgt von de5/d7b/e53 mit jeweils echten Werten.
  - **Postgres `sensor_reading`:** 4 frische Readings, alle Sensor-Felder befüllt, `open_window` jetzt explizit `false` statt NULL, Battery-Werte 33–42 % plausibel.
  - **Engine-Trace Room 1** (evaluation `09007b00…`, 11:05:53Z): Layer 4 `window_safety` → `detail=no_open_window`, `open_zones=[]`, `occupancy_state=vacant` (Beweis: Layer 4 sieht **frische** Readings, alle `open_window=false` → no-op). Layer 3/1/5 konsistent.
- ✅ **T3 Sprint-Doku:** dieser STATUS-Eintrag, CLAUDE.md §1 + §5.21 + §5.22, Sprint-Brief `docs/features/2026-05-07-sprint9-10c-codec-fix.md`, RUNBOOK §10 „Codec-Deploy auf ChirpStack" neu.

**Test-Stand:** Codec-Tests 19/19 grün, Backend 141 passed + 62 skipped. **Live-Pipeline auf heizung-test wieder vollständig — alle 4 Vickis liefern befüllte Readings.**

**Hinweis:** Codec-Deploy nach ChirpStack ist manueller UI-Schritt, kein Repo-Push-Effekt. Bootstrap-Skript via gRPC bleibt Backlog.

**Lessons Learned:** CLAUDE.md §5.21 (Cmd-Byte > fPort beim Codec-Routing), §5.22 (ChirpStack-Codec-Deploy ist nicht automatisch).

**Tag-Vergabe:** Strategie-Chat-Entscheidung. Vorschlag `v0.1.9-rc4-codec-fix`, weil sichtbare Zustandsänderung (Vickis liefern jetzt erst korrekt persistierte Werte). Final-Tag `v0.1.9-engine` weiterhin nach 9.11/9.12.

---

## 2s. Sprint 9.10d Engine-Trace-Konsistenz (2026-05-07, abgeschlossen)

Ziel: Trace-Lücke in Layer 0 (Sommer) und Layer 2 (Temporal) schließen — bisher liefern beide Layer im No-Effect-Fall `None` zurück und tauchen damit gar nicht im `event_log` auf. Ergebnis: das Engine-Decision-Panel war als QA-Tool blind für diese Schichten. Zusätzlich Hysterese-Info im Frontend sichtbar machen, die heute zwar in `event_log.details.hysteresis_decision` persistiert wird, aber nirgends gerendert ist.

**Phase-0-Befund:** Layer 0 und Layer 2 sind heute conditional (return None bei No-Effect), Layer 1/3/4/5 sind always-on. detail-Konvention heterogen: Layer 4 nutzt snake_case-Tokens (vorbildlich), Layer 1/2/3/5 nutzen f-string-Freitext. Hysterese ist kein eigener Layer, sondern wird in jedes LayerStep-`details`-JSONB gemerged (engine_tasks.py:188).

**Architektur-Entscheidung:** `LayerStep.setpoint_c` von `int` auf `int | None` erweitert. None bedeutet "Layer hat keinen eigenen Setpoint-Beitrag" und ist ausschließlich für Layer 0 inactive zugelassen — Layer 0 hat als erste Schicht keinen Vorgänger, daher greift die "setpoint_in == setpoint_out"-Pass-Through-Konvention dort nicht. Alle anderen Layer garantieren weiterhin einen Integer-Wert.

**Tasks:**

- ✅ **T1 Layer 0 always-on** `backend/src/heizung/rules/engine.py:144`: `layer_summer_mode` liefert immer einen LayerStep. Active unverändert (`detail="summer_mode_active=true"`). Inactive: `setpoint_c=None`, `detail="summer_mode_inactive"`. Fast-Path-Gate in `evaluate_room` von `if summer is not None` auf `if ctx.summer_mode_active` umgestellt.
- ✅ **T2 Layer 2 always-on** `backend/src/heizung/rules/engine.py:229`: `layer_temporal` liefert immer einen LayerStep. Aktive Pfade unverändert. Inactive: passthrough `base.setpoint_c` + `base.reason`, snake_case-Token-detail (`no_upcoming_arrival` / `outside_preheat_window` / `outside_night_setback` / `temporal_inactive`). Caller-Aufräumen: alle `if step is not None`-Branches in `evaluate_room` entfallen, Trace-Tupel ist nun unconditional `(summer, base, temporal, manual, window, clamp)`.
- ✅ **T2.5 Schema + None-Sentinel** `engine.py` + `engine_tasks.py`: `LayerStep.setpoint_c: int | None`. Helper `_require_setpoint(step) -> int` für die fünf Stellen in `evaluate_room`, an denen Layer-1+-Setpoints typed an Folge-Schichten weitergegeben werden — Helper raised AssertionError mit Layer-Name, falls die Invariante verletzt wird (S3 Auditierbarkeit). `engine_tasks.py:184` Decimal-Wrap auf `setpoint_out` None-safe gemacht (Layer 0 inactive sonst TypeError). Frontend ist bereits null-aware (Type `string | null`, JSX rendert "—") — keine Änderung nötig.
- ✅ **T3 Trace-Konsistenz-Tests** `backend/tests/test_engine_trace_consistency.py` (neu, 3 Tests, DB-Skip wie test_engine_layer3/4): 6-Layer-Trace bei Sommer inactive verifiziert (Layer 0 None, restliche fünf passthrough oder aktiv). Sommer-active xfail dokumentiert die Brief-Erwartung "auch im Fast-Path 6 Layer" gegenüber dem aktuellen 2-Layer-Verhalten — Engine-Refactor liegt out-of-scope. Dritter Test ruft `_evaluate_room_async` und queried `event_log` auf gemeinsame `evaluation_id` aller sechs Persistenz-Rows.
- ✅ **T4 Frontend Hysterese-Footer** `frontend/src/components/patterns/engine-decision-panel.tsx`: Neue `HysteresisFooter`-Komponente unter `LayerTrace`, vor `HistoryList`. Liest `details.hysteresis_decision` vom ersten LayerStep (alle Steps tragen denselben Wert gemerged). reason-Mapping mit Regex-Patterns für die vier Backend-Strings, Roh-Fallback bei unbekanntem Format (kein Crash). Icons `send` (gesendet) bzw. `block` (unterdrückt).
- ✅ **T5 Sprint-Doku:** dieser STATUS-Eintrag, CLAUDE.md §5.23.

**Test-Stand:** Backend 142 passed + 65 skipped (3 neue DB-Skips bei T3 ohne TEST_DATABASE_URL). ruff clean, mypy `src` clean (Test-Dateien-Vorlast unverändert), tsc + next lint clean. Live-Verify wurde aus 9.10d herausgezogen und verbleibt für Sprint 9.11 (Live-Test #2 sowieso geplant).

**Backlog (vor `v0.1.9-engine` aufzuräumen):**

- **B-9.10d-1 detail-Konvention vereinheitlichen:** snake_case-Tokens für alle Layer (heute heterogen, Layer 4 als Vorbild). Vor allem Layer 1/2/3/5 betroffen. Frontend kann erst sinnvoll übersetzen, wenn Tokens konsistent sind.
- **B-9.10d-2 mypy-Vorlast:** 71 pre-existing Errors in `tests/` (`test_manual_override_schema`, `test_device_schema`, `test_engine_skeleton`-SimpleNamespace, `test_mqtt_subscriber`, `test_api_overrides`). Sprint 9.10d-Diff bringt 0 neue Errors. Aufräumen vor `v0.1.9-engine`.
- **B-9.10d-3 Type-Inkonsistenz Engine vs. EventLog:** `LayerStep.setpoint_c: int` (heute `int | None`), `EventLog.setpoint_out: Decimal | None`. Hygiene-Sprint, weil int↔Decimal-Konvertierung an mehreren Stellen passiert.
- **B-9.10d-4 Sommer-aktiv-Fast-Path auf 6-Layer-Vollständigkeit:** Heute liefert die Engine bei `summer_mode_active=True` nur `(summer, clamp)` — die Variante-B-Konvention sagt aber: alle 6 Layer schreiben immer LayerStep, auch im Fast-Path. Heute Auditierbarkeitslücke (S3) für den Sommer-Fall: keine Spur, dass Layer 1-4 überhaupt evaluiert wurden. Test `test_evaluate_room_emits_six_layer_steps_when_summer_active` ist `pytest.xfail` und dokumentiert die Lücke. Eigener Sprint vor `v0.1.9-engine` — Engine-Refactor (Layer 1-4 müssen Setpoint-Override durch SUMMER_MODE durchreichen).
- **B-9.10d-5 engine_tasks DB-Session per Dependency-Injection:** Heute öffnet `_evaluate_room_async` die DB-Engine über `settings.database_url` (engine_tasks.py:69). Test `test_evaluate_room_layers_share_engine_evaluation_id` braucht deshalb `monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)` + `get_settings.cache_clear()`-Workaround, weil Test-Session und Task-Session sonst auf unterschiedliche DBs zeigen können. Saubere Lösung: Session-Factory per Parameter injizieren, Tests reichen die Test-Session direkt durch. Hygiene-Sprint.

**Tag-Vergabe (geplant nach Merge):** `v0.1.9-rc5-trace-consistency`. Sprint 9.11 Live-Test #2 schließt sich an, Final-Tag `v0.1.9-engine` weiterhin nach 9.11/9.12.

## 2t. Architektur-Refresh 2026-05-07 (abgeschlossen)

**Anlass:** Cowork-Inventarisierung Betterspace zeigt drei Korrekturen
am ursprünglichen Strategiepapier sowie eine Reihe von im Plan
vorgesehenen, aber nicht implementierten Bausteinen.

**Ergebnis:**
- Neues Master-Dokument `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`
- Neuer Sprint-Plan `docs/SPRINT-PLAN.md` (Sprint 9.11 bis 14
  Go-Live)
- Pflicht-Pre-Read pro Session `docs/SESSION-START.md`
- Rollen-Definition `docs/AI-ROLES.md`
- STRATEGIE.md auf Version 1.1
- Drei neue ADRs: AE-42 (Frostschutz zweistufig), AE-43
  (Geräte-Lifecycle), AE-44 (Stabilitätsregeln S1-S6 als ADR)

**Trigger-Phrase ab heute für jede neue Session:**
> „Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."

**Tag:** `v0.2.0-architektur-refresh` (nach Merge)

## 2u. Sprint 9.11a Geräte-Zuordnungs-API (2026-05-08, abgeschlossen)

**Ziel:** Minimal-Backend-API für Vicki-Heizzonen-Zuordnung als Voraussetzung für Sprint 9.11 Live-Test #2. Kein UI, kein Tag (Sub-Sprint per SPRINT-PLAN.md §9.11a-Vorgabe). Bezug AE-43.

**Implementierung:**

- **API:** `PUT /api/v1/devices/{id}/heating-zone` (assign / re-assign, idempotent ohne commit bei gleichem Wert) + `DELETE /api/v1/devices/{id}/heating-zone` (detach, idempotent bei `None`). 404-Codes snake_case (`device_not_found`, `heating_zone_not_found`) per Lesson §5.23. Logger-Events `device_zone_changed` / `device_zone_detached` mit `device_id`/`dev_eui` im `extra`. Schemata in `backend/src/heizung/schemas/device.py`: `DeviceAssignZoneRequest` (gt=0, extra=forbid), `DeviceAssignZoneResponse` (validation_alias `id` → `device_id`, weil ORM-Feld nur `id` heisst).
- **Tests:** `backend/tests/test_api_device_zone.py` (10 Pytests) gegen echtes Postgres. Setup-Fixture mit `uuid.uuid4().hex[:8]`-Suffix (Lesson §5.18, `dev_eui` exakt 16 Zeichen). Cleanup räumt Devices über DevEUI-Pattern auf (FK `ondelete=SET NULL` würde sonst Orphans hinterlassen). Test-Matrix deckt assign/idempotent/reassign/detach/422-Pydantic/404-Device/404-Zone ab.
- **RUNBOOK §10d** zwischen §10c und §11 mit curl-Befehlen für assign/reassign/detach + Verifikations-SQL + Fehlerbild-Tabelle. Bonus: 3 abgeschnittene Anhang-Bullets aus Commit `b5438d4` rekonstruiert + 1016 Null-Bytes Trailing-Padding entfernt (eingecheckt seit `4dda449` bzw. `fe0f2b9`, beide vor Cowork-Mount-Lessons §5.2/§5.9). Datei jetzt 29151 Bytes, 0 Null-Bytes.

**Pre-existing-Failures-Disclaimer:** Voller pytest-Lauf zeigt 206 passed, 1 xfailed, 3 failed + 7 errors — alle 10 Failures/Errors sind `ModuleNotFoundError: No module named 'psycopg2'` in `tests/test_migrations_roundtrip.py` und `tests/test_manual_override_model.py`. Bekanntes Backlog-Item B-9.10-6, kein Sprint-9.11a-Bezug. Sprint-9.11a-Tests (10 neue): grün.

**Tag-Vergabe:** keiner. Sub-Sprint per SPRINT-PLAN.md-Vorgabe.

**Offen für Live-Verify nach Merge** (B-9.11a-2): Vicki-002/003/004 produktiv den Heating-Zones der Zimmer 102/103/104 (Schlafzimmer) zuweisen. Plan vom Strategie-Chat, Ausführung durch Hotelier — nicht im Code-Sprint.

## 2v. Sprint 9.11 Live-Test #2 — Teilweise abgeschlossen (2026-05-09)

**Ziel:** 6-Layer-Engine + Hysterese auf heizung-test mit echter Hardware verifizieren.

**Ergebnis:** 3 von 4 effektiv getesteten Layern Pass, 1 Layer nicht testbar (Hardware), plus 4 strukturelle Befunde.

**Test-Matrix (verschlankt vor Beginn — T4 Nacht in 9.15, T6 Bad-Clamp in 9.12, T7 Hysterese gestrichen weil bereits in Pytests abgedeckt):**

| Test | Layer | Ergebnis |
|---|---|---|
| T1 | 4 (Window) | ❌ nicht testbar — Vicki-001 meldet `open_window=false` trotz Abnehmen vom HK |
| T2 | 2 (Vorheizen) | ✅ Pass — Belegung +30min triggert temporal_override mit reason `preheat` |
| T3 | 1 (Base) + 2 (Nacht) | ✅ Pass — occupied erkannt, Layer 2 Nacht-Override greift korrekt darüber |
| T5 | 3 (Manual) | ✅ Pass — Override 23 °C via API `frontend_4h`, Layer 3 reason `manual` |
| T8 | UI Engine-Decision-Panel | ⚠️ Teilweise Pass — siehe Befunde |

**Befunde (4):**

1. **Vicki-001 Window-Sensor liefert kein `open_window=true`** trotz physischem Abnehmen vom HK. Layer 4 ist auf Code-Ebene grün (Pytests Sprint 9.10), aber Hardware-Trigger fehlt. → Sprint 9.11x.
2. **Auto-Detect-Override-Mechanismus** existiert (siehe AE-45) — automatische Erstellung eines `manual_override` mit `source=device` und 7-Tage-Expiry, wenn Vicki einen Setpoint zurückmeldet, der nicht zur Engine-Erwartung passt. War nicht im Strategie-Chat-Kontext bekannt.
3. **UI Engine-Decision-Panel zeigt nur einen Setpoint pro Zeile** statt `setpoint_in` und `setpoint_out` separat. Designentscheidung vs. Brief-Erwartung unklar. → Backlog B-9.11-1.
4. **„Vorherige Evaluationen" zeigt historisch `base_target`-Reason** statt finalem Layer-Reason. Vermuteter Backend-Befund. → Backlog B-9.11-2.

**API-Schema-Korrekturen für RUNBOOK §10d (in T-D3 erfasst):**

- `POST /rooms/{id}/overrides`: `source` muss aus `device | frontend_4h | frontend_midnight | frontend_checkout` sein (`manual`/`manual_test` wird mit 422 abgelehnt).
- `POST /rooms/{id}/overrides`: `setpoint` muss ganzzahlig sein (Vicki-Hardware-Constraint, Dezimalstellen werden abgelehnt).
- `DELETE /occupancies/{id}`: nicht erlaubt, Belegungen werden via PATCH mit Body `{"cancel": true}` storniert (Audit/PMS-Sync).

**Tag-Vergabe:** keiner. Sprint 9.11 bleibt offen bis T1 in 9.11x abgeschlossen ist.

**Live-Verify B-9.11a-2:** Erfolgreich abgeschlossen am 2026-05-09 vor Test-Beginn — alle 4 Vickis korrekt zugeordnet:

- Vicki-001 → Zone 91 Schlafzimmer (Zimmer 101) — bestand bereits
- Vicki-002 → Zone 3 Schlafbereich (Zimmer 102)
- Vicki-003 → Zone 5 Schlafbereich (Zimmer 103)
- Vicki-004 → Zone 7 Schlafbereich (Zimmer 104)

### Update 2026-05-09 — Root Cause T1 identifiziert

Cowork-Diagnose + Hersteller-Doku-Recherche (`docs/vendor/mclimate-vicki/`) ergeben:

- Codec liefert `openWindow` korrekt — Codec-Pfad eliminiert
- Backend persistiert `sensor_reading` 1:1 — Backend-Pfad eliminiert
- Engine Layer 4 verarbeitet `open_window=false` korrekt — Engine-Pfad eliminiert
- **Root Cause:** Vicki-Open-Window-Detection ist im Default DISABLED (Hersteller-Setting), und der Algorithmus ist laut MClimate „not 100% reliable" wegen HK-Wärme-Dominanz am internen Sensor
- A/B-Test mit Vicki-003 (passiv neben Vicki-001 gelegt) bei Außentemp ~18 °C bestätigt: Sturz zu klein und zu langsam für Vicki-Schwellen, Hardware-Pfad im Sommer physikalisch nicht testbar

**Konsequenzen:**

- AE-47 dokumentiert die Hybrid-Strategie (Hardware-First + passiver Logger)
- Sprint 9.11x aktiviert die Vicki-Konfiguration + persistiert Backplate-Bit
- Sprint 9.11y baut Backend-Synthetic-Test + passiven Logger
- Tag `v0.1.9-rc6-live-test-2` erst nach 9.11y Abschluss

---

## 2w. Sprint 9.11x Backplate-Persistenz + Layer-4-Detached-Trigger (2026-05-10, abgeschlossen)

**Ziel:** `attachedBackplate` aus dem Vicki-Codec ins Backend persistieren und Engine Layer 4 um den zweiten Frostschutz-Trigger `device_detached` mit AND-Semantik über alle Devices einer Heizzone erweitern. Bereitet die Demontage-Erkennung für Live-Test #2 (9.11y) vor.

**Ergebnis:** Backend + Frontend-Sync gemerged auf develop, 10 Pytests grün, CI grün auf finalem PR. Pre-Merge-Codec-Verify entfällt (raw_payload ist Base64-LoRaWAN, nicht JSONB — Codec-Emission durch AE-47 + Session-Header bestätigt). Post-Deploy-Verify gegen `sensor_reading.attached_backplate` direkt nach 5-Min-Pull.

**Diff-Stats:** 12 Files, 736 insertions, 24 deletions. Migration 0010 + neuer Test-File + 10 Code-Edits.

**Architektur — AND-Semantik:** Anders als Layer 4 Window (OR — ein offenes Fenster reicht): **alle** Zone-Devices müssen frisch und übereinstimmend `attached_backplate=False` melden. Pro Device: letzte 2 frische (>= now-30min) Frames mit `attached_backplate IS NOT NULL`. Trigger nur wenn ALLE Devices "detached" UND mindestens ein Device existiert. Begründung: ein einzelnes False ist nicht eindeutig (Housekeeping-Pause, Sensor-Klemmer, Defekt); ein offline-Device darf die Zone nicht in Frostschutz kippen wegen altem False-History eines anderen Devices.

**Reason-Prioritäts-Schutz (§5.23):** Wenn `prev_reason == WINDOW_OPEN` und `all_detached=True` → Pass-Through (`setpoint_c=prev_setpoint_c`, `reason=WINDOW_OPEN`, `detail="superseded_by_window"`). Beide Trigger meinen Frostschutz, aber Audit-Trail bleibt eindeutig.

**Test-Matrix (10/10 grün):**

| # | Setup | Frames | Erwartung |
|---|---|---|---|
| 1 | Single | T,T | kein Trigger (attached) |
| 2 | Single | F,T | kein Trigger (Hysterese) |
| 3 | Single | F,F | Trigger |
| 4 | Single | NULL,NULL | kein Trigger (Backwards-Compat) |
| 5 | Multi | A:F,F / B:T,T | kein Trigger (B attached) |
| 6 | Multi | A:F,F / B:offline | kein Trigger (B unklar) |
| 7 | Multi | A:F,F / B:F,F | Trigger, beide gelistet |
| 8 | Multi | A:F,F / B:F,T | kein Trigger (B Hysterese) |
| 9 | Single + open_window | F,F + ow=T | superseded_by_window |
| 10 | Single | F,F,NULL (jüngster NULL) | Trigger (NULL gefiltert) |

Tests 5/6/8 sind die AND-Wachposten. Test 9 wächt AE-47. Test 10 verriegelt den Frische-Filter `attached_backplate IS NOT NULL`.

**Brief-Drifts vorab freigegeben (alle dokumentiert in PR #116/#118):**

1. `recorded_at` → `time` (Code-Source-of-Truth, Spalte heißt `time` seit Migration 0001)
2. `tests/rules/` → `tests/` (bestehende flache Konvention)
3. `now`-Param → `age_min`-Pattern (analog Window-Tests)
4. Enum-Erweiterung in T2 mitgenommen (`CommandReason.DEVICE_DETACHED`, `EventLogLayer.DEVICE_DETACHED`, beide `VARCHAR(30) native_enum=False` — kein Schema-Drift)
5. `applied=False` → §5.23 Pass-Through (LayerStep-Schema bleibt unverändert)
6. T6 von 9 auf 10 Tests erweitert (Test 10 NULL-Glitch-Robustheit auf User-Add)

**Migration-Name gekürzt:** Brief-Originalname (67 Zeichen) sprengt `alembic_version.version_num VARCHAR(32)`. Gekürzt auf `0010_attached_backplate_and_fw` (30 Zeichen).

**Scope-Erweiterung Frontend (begründet):** Sprint 9.11x ursprünglich Backend-only. 4 Frontend-Edits in 2 Files (`types.ts`, `engine-decision-panel.tsx`) durch Cross-Repo-Schema-Drift gerechtfertigt — `Record<EventLogLayer, string>` und `Record<CommandReason, string>` sind exhaustive. Ohne Frontend-Anpassung wäre der `device_detached`-Layer im Decision-Panel unsichtbar (S3-Verstoß für Live-Test #2 in 9.11y). Labels: `LAYER_LABEL.device_detached = "Geraet-Sicherheit"` (analog "Fenster-Sicherheit"), `REASON_LABEL.device_detached = "Geraet abgenommen"` (analog "Fenster offen").

**PR-Reihenfolge — Workflow-Befund:**

- **PR #116** wurde irrtümlich gegen `main` statt `develop` gemerged (`gh pr create` ohne `--base develop` — GitHub-Default ist `main`). main war 83 Commits hinter develop (Sprint-9.8a-Stand). Squash hat Frankenstein-Konstellation produziert: Files im Branch geändert haben jetzt Sprint-9.10d-Stand, andere behalten Sprint-9.8a-Stand. Engine-Pipeline auf main potenziell defekt. CI war grün, weil GitHub Actions die merge-base testet, nicht main-after-merge.
- **PR #117** revertiert main (`git revert -m 1 bc8e3dd`). CI rot wegen Pre-Existing Sprint-9.8b-`_quantize`-Bug auf altem main-Stand (kein Bezug zu 9.11x). Bleibt offen — heizung-main-Saneirung als eigener Sprint (B-9.11x-2), Pull-Service ist eh durch safe.directory blockiert (CLAUDE.md §5.7), kein Production-Risiko.
- **PR #118** (Branch v2 von develop, 12 Files via `git checkout bc8e3dd -- ...` übernommen, identisches Diff zu #116) sauber auf develop gemerged (`mergeCommit aaa6585`). Codec-Emission verifiziert durch AE-47 + Session-Header — kein SSH-Pre-Merge nötig.

**Workflow-Lesson:** `gh pr create` ohne `--base develop` ist bei Standard-Gitflow-Repos eine Falle. CLAUDE.md §3 Goldene Regel #2 wird in einer Folge-Doku-PR um diesen Punkt erweitert (vor Sprint 9.11y).

**manual_override-Cleanup 2026-05-10 (9.11y-Vorbereitung):** IDs 3/4/5 wurden via API revoked. Hintergrund: vor 9.11y-Live-Synthetic-Test alte Test-Overrides wegräumen, sodass die Engine wieder auf Layer-1/2/4-Pfaden läuft und nicht durch alte Layer-3-Overrides maskiert ist.

**Pre-Push-Toolchain:** Backend grün (`ruff format/check`, `mypy strict`, `pytest -x` mit zwei psycopg2-Ignores — siehe B-9.11x-1). Frontend grün (`type-check`, `lint`, `build`).

**Tag-Vergabe:** keiner. Sprint 9.11x bleibt im Block 9.11y. Tag `v0.1.9-rc6-live-test-2` erst nach 9.11y-Abschluss.

**Backlog-Items aus diesem Sprint:** B-9.11x-1 bis B-9.11x-4 — siehe §6.2.

---

## 2x. Sprint 9.11x.b Vicki-Downlink-Helper + Open-Window-Aktivierung (2026-05-11, abgeschlossen)

**Ziel:** AE-48 (Hybrid-Helper-Architektur) implementieren, drei neue Vicki-Commands (0x04 FW-Query, 0x45 OW-Set, 0x46 OW-Get) via MQTT-Pfad, Bulk-Aktivierung Open-Window-Detection auf den 4 Hotel-Sonnblick-Vickis. Vorbereitet Live-Test #2 (9.11y).

**Ergebnis:** Sprint inhaltlich abgeschlossen — alle 4 Vickis haben Open-Window-Detection aktiviert (`enabled=True, duration_min=10, delta_c=1.5`, Vendor-Bytes `0x4501020F`). Verifiziert via `MAINTENANCE_VICKI_CONFIG_REPORT`-Logs auf heizung-test. Zwei Bugs aufgedeckt (B-9.11x.b-5/6), nicht Sprint-blockierend.

**Diff-Stats:** 7 Files, 1036 insertions, 37 deletions (PR #123). Plus 1 File, 3 insertions (PR #124, Dockerfile-Fix).

**Architektur (AE-48):**

```
send_raw_downlink(dev_eui, payload_bytes, *, fport=1, confirmed=False) -> str   # generisch
query_firmware_version(dev_eui) -> str       # 0x04
set_open_window_detection(dev_eui, enabled, duration_min, delta_c: Decimal) -> str  # 0x45
get_open_window_detection(dev_eui) -> str    # 0x46
send_setpoint(dev_eui, setpoint_c) -> str    # 0x51 (refactored, verhalten-treu)
```

`delta_c` ist Decimal-Pflicht (CLAUDE.md §6). `duration_min ∈ {5, 10, ..., 1275}`, `delta_c ∈ [0.1, 6.4]` °C. ROUND_HALF_UP-Rundung mit 6er-Matrix-Test verriegelt.

**Vendor-Konformität (verriegelt durch 9 Codec-Mirror-Tests):**

| Input | Bytes | Vendor-Hex |
|---|---|---|
| `set_open_window_detection(True, 10, Decimal("1.5"))` | `[0x45, 0x01, 0x02, 0x0F]` | `0x4501020F` |
| `set_open_window_detection(True, 30, Decimal("1.3"))` | `[0x45, 0x01, 0x06, 0x0D]` | `0x4501060D` |

**Subscriber-Erweiterung:**
- `_handle_firmware_version_report` → `device.firmware_version` UPDATE (defensive Parse)
- `_handle_open_window_status_report` → strukturierter `logger.info` mit `event_type=MAINTENANCE_VICKI_CONFIG_REPORT` (S6-Option B, kein Schema-Drift)
- `REPLY_REPORT_TYPES`-frozenset filtert alle Reply-Typen sauber (verhindert NULL-Garbage-Inserts in `sensor_reading`)

**Bulk-Aktivierungs-Skript** `backend/scripts/activate_open_window_detection.py`:
- 3-Phasen (FW-Query → Wait → FW-Check + 0x45+0x46)
- `--wait-secs N` CLI-Arg (default 60, empfohlen 600-1200)
- Tabellen-Output, idempotent

**Tests:** 246 passed + 1 xfailed lokal (mit B-9.11x-1 psycopg2-Ignores). Davon 23 neue Wrapper-/Validation-Tests + 9 Codec-Mirror-Tests + 26 Subscriber-Regression-Tests.

**Brief-Drifts (vorab freigegeben):**

| # | Brief | Auflösung |
|---|---|---|
| 1 | `tests/services/test_*.py` | flacher Pfad `tests/test_*.py` |
| 2 | `send_raw_downlink → None` | AE-48: `→ str` |
| 3 | Wrapper `def` (sync) | AE-48: `async def` |
| 4 | `duration_byte = duration_min` | **Vendor-Doku-Korrektur**: `duration_min // 5` (Brief-Code-Bug — 10 Min wäre als 50 Min gesendet worden, S4-Hardware-Risiko) |
| 5 | `event_log MAINTENANCE-Eintrag` | Option B: Logger-only |
| 6 | `60s warten` | Brief-treu mit `--wait-secs N` CLI-Override |
| 7 | FW-String "4.5.1" | Codec emittiert `firmware_version: "FW_maj.FW_min"` (Vendor: 4 Bytes), `hw_version` separat |

T5-Reopening: `REPLY_REPORT_TYPES`-Erweiterung als Konsequenz aus T6 Codec-Output — User-bestätigt, S5-konform (Defensive-by-default).

**PR-Reihenfolge (saubere `--base develop`-Anwendung von §3.11):**

- **PR #123** (Code): Sprint 9.11x.b Hauptmerge, mergeCommit `7774768`, CI grün.
- **PR #124** (Dockerfile-Fix): `scripts/` ins API-Image kopieren, mergeCommit `8a0bcc4`, CI grün. Befund nach #123-Merge: Bulk-Skript fehlte im Container, weil Dockerfile `scripts/` nicht kopierte.

**Live-Aktivierung auf heizung-test (2026-05-11):**
- Codec-Re-Paste in ChirpStack-UI durch User
- Periodic-Verify Vicki-001 (kein Regress)
- `docker exec deploy-api-1 python scripts/activate_open_window_detection.py --wait-secs 1200`
- Ergebnis: alle 4 Vickis OW-Detection aktiv (`enabled=True, duration_min=10.0, delta_c=1.5`), `MAINTENANCE_VICKI_CONFIG_REPORT`-Logs vorhanden.

**Live aufgedeckte Bugs (Backlog, nicht Sprint-blockierend):**

- **B-9.11x.b-5**: 0x04-Decoder im `mclimate-vicki.js` liefert falsche FW-Strings. `device.firmware_version` zeigt `"129.20", "129.10", "129.18", "129.10"` — Vicki-FW ist im 4.x-Bereich. Wahrscheinlich Byte-Offset-Bug: Codec interpretiert Reply-Command-Byte (0x81 = 129 decimal) als FW-Major statt Byte 3. Vendor-Spec: `[Reply-Cmd, HW_maj, HW_min, FW_maj, FW_min]` — Codec liest vermutlich Index 0/1 statt 3/4. Fix in 9.11x.c: Codec-Patch + Re-Run FW-Query (Sub-Modus `--fw-only` damit OW nicht erneut angestoßen wird).
- **B-9.11x.b-6**: Subscriber-Log `firmware_version persistiert` feuert nicht, obwohl DB-Write läuft. T4-Implementierung in `_handle_firmware_version_report` weicht von Brief-Spec ab. Trivial-Fix, in 9.11x.c mit B-9.11x.b-5 zusammen.

Encoder ist von beiden Bugs nicht betroffen — Vendor-Bytes `0x4501020F` korrekt, OW-Aktivierung erfolgreich. Encoder-Seite verriegelt durch Codec-Mirror-Tests. Decoder-Seite hat keinen Mirror-Test (siehe B-9.11x.b-1 — JS-Runtime-Variante würde Decoder mitschützen).

**Pre-Push-Toolchain:** Backend grün (`ruff format/check`, `mypy strict`, `pytest -x` mit B-9.11x-1-Ignores). Frontend `type-check` grün (kein Touch erwartet).

**Tag-Vergabe:** keiner. Tag `v0.1.9-rc6-live-test-2` in 9.11y nach Live-Synthetic-Test.

**Backlog-Items aus diesem Sprint:** B-9.11x.b-1 bis B-9.11x.b-6 — siehe §6.2.

---

## 2y. Sprint 9.11x.c FW-Decoder-Fix + FW-Persist-Logger-Fix (2026-05-11, abgeschlossen)

**Ziel:** Mini-Hotfix für die beiden 9.11x.b-Live-Befunde B-9.11x.b-5 (0x04-Decoder Byte-Offset-Bug) und B-9.11x.b-6 (FW-Persist-Logger feuert nicht). Re-Run FW-Query auf den 4 produktiven Vickis, korrekte FW-Versionen in DB.

**Ergebnis:** Sprint inhaltlich abgeschlossen, beide Bugs verifiziert gefixt. Live-Verify auf heizung-test grün — alle 4 Hotel-Sonnblick-Vickis zeigen jetzt `firmware_version=4.4` in der DB, FW-Persist-Logger feuert mit `rows=1`-Diagnose-Info.

**Diff-Stats:** 6 Files, 356 insertions, 26 deletions (PR #126, mergeCommit `2a0cc0c`).

**Root-Cause B-9.11x.b-5** (mit Live-Bytes-Beleg):

Vendor-Doku-Spec `0x04{HW_major}{HW_minor}{FW_major}{FW_minor}` meinte **Nibbles**, nicht **Bytes**. Echte Vicki sendet 3 Bytes plus optional einen eingebetteten Keep-alive im selben Uplink-Frame.

Bytes Vicki-001 (2026-05-11): `04 26 44 81 14 97 62 a2 a2 11 e0 30`
- `0x26` → HW 2.6, `0x44` → FW 4.4 (Reply-Anteil, 3 Bytes)
- Rest `81 14 ...` → Keep-alive Cmd 0x81 mit `target_temperature=20°C`

Vorher-Bug: `bytes[3]=0x81=129` wurde als FW-Major gelesen → DB zeigte "129.20".

**Fix-Strategie:**

| Bereich | Fix |
|---|---|
| Codec `mclimate-vicki.js` | 3-Byte-Nibble-Decoder + Frame-Merge mit Reply-Priorität (`report_type`, `command` bleiben) |
| Subscriber `mqtt_subscriber.py` | `logger.info` AUSSERHALB des `async-with`-Blocks + `rowcount`-Diagnose + WARNING bei UPDATE matched 0 rows |
| Vendor-Doku `04-commands-cheat-sheet.md` | §1 korrigiert mit echtem 3-Byte-Nibble-Layout + Roh-Bytes-Beleg |
| Bulk-Skript `activate_open_window_detection.py` | `--fw-only`-Flag für Re-Run nach Decoder-Fix |

**Tests (7 neu, alle grün):**

- 4 Codec-Mirror-Decode-Tests (`test_codec_mirror.py`): pure 3-Byte Reply, kombinierter Frame (Live-Sample, 12 Bytes), Nibble-Reihenfolge-Wachposten HW vor FW, Bytes < 3 Error-Path
- 3 Subscriber-caplog-Tests (`test_mqtt_subscriber.py`): persists + INFO-Log mit rowcount, unknown dev_eui → WARNING-Log (Defensive), `firmware_version=None` → silent skip

Plus Test-Order-Defensive: explizit `propagate=True` + `caplog.set_level` mit logger-Argument, damit andere Test-Module die Subscriber-Logger-Propagation nicht killen können.

**Pre-Push-Toolchain:** Backend grün (`ruff format/check`, `mypy src`, `pytest -x`: **253 passed, 1 xfailed** mit B-9.11x-1-Ignores). Frontend `type-check` grün (kein Touch).

**Live-Aktivierung auf heizung-test (2026-05-11):**

Vor dem Re-Run hat User den Codec in der ChirpStack-UI re-pasted (RUNBOOK §10c). Periodic-Verify Vicki-001 zeigt sauberes Object (`temperature=21.82`, `target_temperature=20`, `openWindow=false`, `attachedBackplate=true`, `battery_voltage=3.4`, 24 Keys, keine NULLs) — **kein Regress durch den Codec-Re-Paste**.

Anschließend `--fw-only`-Run:

```
docker exec deploy-api-1 python scripts/activate_open_window_detection.py --fw-only
```

**DB-Verify nach ~15 Min:**

| Label | dev_eui | firmware_version |
|---|---|---|
| Vicki-001 (Pairing-Test) | 70b3d52dd3034de4 | 4.4 |
| Vicki-002 | 70b3d52dd3034de5 | 4.4 |
| Vicki-003 | 70b3d52dd3034d7b | 4.4 |
| Vicki-004 | 70b3d52dd3034e53 | 4.4 |

**Logger-Verify** (`docker logs deploy-api-1 | grep "firmware_version persistiert"`, 08:07–08:12 UTC):
- 4× `firmware_version persistiert ... fw=4.4 rows=1`

Beide Bugs **B-9.11x.b-5** und **B-9.11x.b-6** ✅ geschlossen.

**Tag-Vergabe:** keiner. Tag `v0.1.9-rc6-live-test-2` in 9.11y nach Live-Synthetic-Test.

---

## 2z. Sprint 9.11y Synthetic-Tests + Inferred-Window-Logger + Hardware-Verify (2026-05-11, abgeschlossen, **Tag `v0.1.9-rc6-live-test-2`**)

**Ziel:** Layer-4-Pipeline End-to-End ohne Hardware-Abhängigkeit testbar machen (AE-47-Strategie für Heizungs-Aus-Periode), passiven Inferred-Window-Detector als dritten Trigger im event_log einbauen, Hardware-Kältepack-Verify auf heizung-test als Akzeptanz-Schritt.

**Ergebnis:** Sprint inhaltlich abgeschlossen, **Tag gesetzt**. Synthetic-Tests grün (6/6). Hardware-Verify lieferte AE-47-Hardware-First-Bestätigung (Vicki-Trägheit live demonstriert) plus AE-45-Live-Demonstration (Auto-Override-Erkennung). Inferred-Logger deployed und funktional, aber durch synchronen Drehrad-Override während Kältepack-Test nicht observierbar — die korrekte Spec-Konformität (Pre-Window-Baseline-Block bei Setpoint-Wechsel) hat in diesem Live-Setup den Trigger verhindert.

**Diff-Stats:** 6 Files, 119 insertions (PR #128, mergeCommit `2e9f833`).

**Architektur (AE-47 §Passiver Trigger):**

```
detect_inferred_window(session, room_id, now) -> InferredWindowResult | None
log_inferred_window_event(session, result)  # event_log Off-Pipeline-Audit
```

- Lookback **10 Min**, Δ-T-Schwelle **0.5 °C** (`oldest - newest`, fallend)
- Stehender Setpoint geprüft über **Pre-Window-Baseline + Window-Set** zusammen — naive "nur in_window prüfen"-Variante hätte Boundary-Wechsel verpasst
- OR-Semantik über Devices der Zone (analog Window-Trigger)
- Off-Pipeline: keine Setpoint-Aktion, nur event_log mit `layer=INFERRED_WINDOW_OBSERVATION`, `reason=INFERRED_WINDOW`, `setpoint_in == setpoint_out`

**Integration `engine_tasks.py`:** Detect-Aufruf nach Engine-Pipeline + ControlCommand-Insert, vor `session.commit()` — atomar in derselben Transaction. Defensive try/except: Detector-Failure blockiert regulären Eval-Commit nie.

**Synthetic-Test-Matrix (6/6 grün):**

| # | Setup | Erwartung |
|---|---|---|
| 1 | Engine: `open_window=True` | MIN_SETPOINT_C, reason=WINDOW_OPEN |
| 2 | Engine: `attached=False,False` | MIN_SETPOINT_C, reason=DEVICE_DETACHED |
| 3 | Inferred: Falling 21→20.5→20, SP stehend | delta_c=1.0, setpoint_c=20 |
| 4 | Inferred: Stabile 21.0 | None |
| 5 | Inferred: SP-Wechsel 20→18 Boundary | None (Wachposten) |
| 6 | Inferred: nur Pre-Window-Baseline | setpoint_c=20 (Baseline) |

Plus 2 Log-Format-Mirror-Tests (S3-Audit-Trail-Drift-Schutz).

**Wichtiger Detector-Fix während T4 (User-gefangen, Test 5 als Wachposten):** Naive Implementierung "nur `issued_at >= threshold` prüfen" hätte den Boundary-Wechsel verpasst (20→18 mit 20.0-CC vor 30 Min, 18.0-CC vor 1 Min → Window enthält nur `{18.0}` → naiv kein Block). Fix: `all_setpoints = in_window_setpoints ∪ {pre_window_sp}`, bei `len > 1` Return `None`. Test 5 + Test 6 verriegeln beide Richtungen.

**Brief-Drifts (vorab freigegeben):**

| # | Brief | Auflösung |
|---|---|---|
| 1 | `services/event_log.py` "vorhanden, erweitern" | neu angelegt (bisherige Inserts in `engine_tasks.py`) |
| 2 | Detect-Aufruf "danach" | vor `session.commit()`, atomar (semantisch unabhängig vom frisch erzeugten CC) |
| 3 | Defensive try/except | Detector-Failure blockiert Eval nicht (S2) |
| 4 | (User-Befund) | Pre-Window-Baseline-Check für stehender-Setpoint-Bedingung |

**Pre-Push-Toolchain:** Backend grün (`ruff`, `mypy src`, `pytest`: **261 passed, 1 xfailed** mit B-9.11x-1-Ignores). Frontend `type-check` grün (kein Touch).

**Hardware-Kältepack-Verify auf heizung-test (2026-05-11):**

Vicki-001 wurde mit Kältepack belastet (T-Sturz 22.0 → 14.4 °C im internen Sensor). Drei Befunde:

1. **Vicki-Hardware-Trigger NICHT ausgelöst** trotz 7.6 °C T-Sturz → **AE-47 §Algorithmus-Trägheit live bestätigt**. Vendor-Doku "not 100% reliable, can be affected by outdoor temperature, position of the device on the radiator..." erfüllt sich in der Praxis.
2. **Auto-Override-Erkennung AE-45 live demonstriert** während Kältepack-Hantierung — zwei Vicki-Drehrad-Sprünge erkannt:
   - 09:57 UTC: 20 → 26 → `manual_override id=12 source=device`
   - 10:28 UTC: 26 → 29 → `manual_override id=13 source=device`
   Engine-Pipeline reagierte korrekt, Override-Schutz greift.
3. **Inferred-Window-Logger deployed und im evaluate_room-Pfad bestätigt aktiv** (minütlich pro Raum laut Logs), aber **nicht getriggert** — die Setpoint-Sprünge unter Punkt 2 haben den Pre-Window-Baseline-Block ausgelöst (Test 5-Pattern: `len(all_setpoints) > 1 → return None`). **Korrektes Verhalten nach Spec.**

**Konsequenz für Sprint-Bewertung:** Hardware-Verify-Pfad A (Vicki-Trigger) und Pfad B (Inferred-Logger) sind beide durch die Live-Bedingungen nicht in der ursprünglich antizipierten Form observierbar geworden. Aber:
- Pfad A: **bestätigt** AE-47-Hypothese der Hardware-Trägheit (Hauptbegründung für AE-47 lebt).
- Pfad B: Logger ist deployed, im Hot-Path eingehängt, Spec-konform geblockt durch echten Setpoint-Wechsel — das ist exakt das Verhalten, das Test 5 verriegelt. AE-45-Erkennung läuft parallel und macht den Detector im Hotelbetrieb häufiger inaktiv als ursprünglich angenommen.

→ **Backlog B-9.11y-1**: Inferred-Logger Live-Verify in der Heizperiode mit einem Test-Szenario ohne Drehrad-Hantieren (echtes Fenster-Öffnen, niemand fasst den Vicki an, Setpoint bleibt stehend) — dann kann der Detector seinen Trigger zeigen.

**Tag-Vergabe:** `v0.1.9-rc6-live-test-2` gesetzt 2026-05-11, AE-47-Begründung gemäß Brief-Fail-Safe (Tag wird in beiden Hardware-Fällen gesetzt). Sprint-9.11-Familie offiziell geschlossen.

**Backlog-Items aus diesem Sprint:** B-9.11y-1, B-9.11y-2 — siehe §6.2.

---

## 2aa. Sprint 9.12 zurückgestellt (2026-05-11)

Strategie-Chat-Review entschied: Frostschutz pro Raumtyp ist Feature
ohne realen Schmerz. Hotel Sonnblick meldet keine Frostschäden, kein
Hotelier-Bedarf. AE-42 auf „zurückgestellt" gesetzt, STRATEGIE.md §6.2
R8 auf globale Konstante zurückgedreht, SPRINT-PLAN.md 9.12-Eintrag
entfernt, ARCHITEKTUR-REFRESH §2.1 / §3 / §4 / §7 mit Update-Box
ergänzt.

Engine-Code bleibt unverändert — Layer 0, 4, 5 lesen die Konstante
direkt, kein Helper, keine Migration nötig.

Migrations-Pfad für spätere Aktivierung steht in AE-42 als additive
5-Schritt-Liste.

Nächster Sprint: 9.13 Geräte-Pairing-UI + Sidebar-Migration.

---

## 2ab. Sprint 9.13 abgeschlossen (2026-05-12)

Geräte-Pairing-Wizard + Sidebar-Migration in vier PRs vollendet plus
zwei Hotfixes und eine Doku-Folge:

- #133 `feat(sprint9.13a)` Pairing-Wizard + Detach + Inline-Label-Edit
- #134 `fix(sprint9.13a)` Input-Hardening (autoComplete) + B-LT-1 als
  nicht-reproducible reklassifiziert
- #135 `fix(sprint9.13a)` Engine-Trigger nach Re-Attach (B-LT-2)
- #136 `chore(hf-9.13a-2-doku)` Live-Verifikations-BEFUND
- #137 `feat(sprint9.13b)` Sidebar-Migration + 8 Empty-State-Stubs +
  Mobile-Sheet

Tag `v0.1.11-device-pairing` am 2026-05-12 gesetzt, deckt Bündel A und
Bündel B zusammen.

Cowork-Live-Test 2026-05-12 (BEFUND in
`cowork-output/sprint9-13b-live-test/BEFUND.md`): alle 5
Pflicht-Prüfungen erfolgreich, Sidebar mit 14 Einträgen in 5 Gruppen
live, 8 Stubs rendern korrekt, Mobile-Sheet ohne A11y-Errors, keine
Regression auf bestehenden Pages.

AE-47 Hardware-First-Semantik unverändert. B-LT-2-followup-1
(Hardware-Status-Badge) kommt als nächster Sprint, schließt die
UX-Lücke „Hotelier sieht 10-Grad-Klemmung ohne Erklärung".

Neuer Befund Cache-Busting nach Deploys (B-9.13b-1) als Backlog-Item
dokumentiert.

---

## 2ac. Sprint 9.13c abgeschlossen (2026-05-12)

Hardware-Status-Badge (B-LT-2-followup-1) in zwei PRs abgeschlossen:

- #139 `feat(sprint9.13c)` Backend-Endpoint
  `/api/v1/devices/{id}/hardware-status` + `HardwareStatusBadge`-
  Komponente + 3 Integrationsstellen (`/devices`, `/devices/[id]`,
  `/zimmer/[id]`)
- #140 `fix(sprint9.13c)` Wording-Korrektur: Spalte „Status" wurde
  „Eingerichtet" (ja/nein mit `check_circle`/`cancel`), Spalte
  „Hardware-Status" wurde „Status" (Hardware-Badge bleibt). Folge
  der Aktiv-Doppelung-Beobachtung im Cowork-Visual-Review.

Cowork-Live-Test 2026-05-12 (BEFUND in
`cowork-output/sprint9-13c-live-test/BEFUND.md`): 5/5
Pflicht-Prüfungen erfolgreich. Vicki-002-Edge-Case visuell
bestätigt: „Status: Inaktiv, noch nie" + „Eingerichtet: ja" —
Hardware antwortet nicht, App-Flag ist gesetzt, genau der Use-Case
der UX-Lücke.

B-LT-2-Story komplett abgeschlossen: Engine-Trigger (#135) +
Hardware-Status-Anzeige (#139/#140). AE-47 Hardware-First-Semantik
unverändert.

Kleine 30-Min-Konstante `WINDOW_STALE_THRESHOLD_MIN` aus `engine.py`
nach `rules/constants.py` extrahiert — geteilte Quelle zwischen
Layer-4 und Hardware-Status-Endpoint.

Nächster Sprint: 9.14 Temperaturen & Zeiten.

---

## 2ad. Sprint 9.14 abgeschlossen (2026-05-14)

Globale Temperaturen + Zeiten UI für die 6 Engine-gelesenen
`rule_config`-Felder. AE-46 verankert die Settings-Editor-Architektur.

**Backend:**
- Migration `0011_config_audit` legt neue Tabelle an (id, ts,
  user_id?, source, table_name, scope_qualifier?, column_name,
  old_value JSONB, new_value JSONB, request_ip? INET).
- Model `ConfigAudit`, Pydantic `ConfigAuditRead`, Service
  `record_config_change` (atomar pro Feld in derselben Transaktion).
- Neuer Router `api/v1/rule_configs.py`:
  - `GET /api/v1/rule-configs/global` — 6 Engine-Felder + Timestamps
  - `PATCH /api/v1/rule-configs/global` — partielle Updates mit
    Range-Validierung (16–26 / 10–22 / 14–22 / 0–240) und
    Nachtfenster-Konsistenz; pro geändertem Feld config_audit
- Bestehender `PATCH /api/v1/global-config` um config_audit-Hook
  erweitert (analog).
- `# AUTH_TODO_9_17`-Marker an beiden PATCH-Handlern; bis NextAuth
  steht, wird `request.client.host` als `request_ip` getrackt.

**Frontend:**
- Generische Komponente `components/inline-edit-cell.tsx` mit
  Klick → Edit → Tab/Blur → Validate → Save (AE-3 Auto-Save-on-Blur).
  `LabelCell` in `/devices` bleibt unangetastet.
- shadcn Tabs (`components/ui/tabs.tsx`, neue Deps `zod` +
  `@radix-ui/react-tabs`).
- `/einstellungen/temperaturen-zeiten` mit 2 Tabs:
  „Globale Zeiten" (night_start, night_end,
  preheat_minutes_before_checkin) und „Globale Temperaturen"
  (t_occupied, t_vacant, t_night).
- Toast „Gespeichert — Engine übernimmt in ≤ 60 s" nach jedem Save;
  Error-Toast bei Save-Fehler, Inline-Error bei Validate-Fehler.

**Tests:**
- 5 Backend-Tests (`tests/test_api_rule_configs.py`): Range,
  config_audit pro Feld, Decimal-Praezision (kein Float),
  Nachtfenster, Engine-liest-neuen-Wert-nach-PATCH.
- 1 Playwright-Test (`tests/e2e/temperaturen-zeiten.spec.ts`):
  Tabs, Inline-Edit, Out-of-Range-Block, Save → Toast → Reload-
  Persistenz.

**Out of Scope (Brief-konform):**
- Klima-Tab gestrichen.
- Sommermodus-Toggle (kommt mit 9.16).
- Auth/NextAuth (kommt mit 9.17).
- UI für config_audit-History.
- Die 8 nicht-Engine-gelesenen rule_config-Felder bleiben in der
  DB außerhalb der API-Domain (YAGNI / S6).

**Tag-Vorschlag:** `v0.1.12-global-config-ui` (Strategie-Chat-
Freigabe nach Cowork-Visual-Review abwarten).

**Doku-Naming-Hinweis:** Brief sagte „STATUS.md §2v"; §2v ist
bereits Sprint 9.11 Live-Test #2. Pragmatisch §2ad genommen
(nächster freier Buchstabe nach §2ac).

Nächster Sprint: 9.15 Profile (Wochentag-Schedule).

---

## 2ae. Sprint 9.16 abgeschlossen (2026-05-14)

Szenario-Engine aktiviert: Sommermodus ist das erste Szenario, gesteuert
über `scenario_assignment(code='summer_mode', scope='global')` statt
`global_config.summer_mode_active` (Boolean-Spalte gedroppt). AE-31 als
historisch markiert, AE-49 dokumentiert die heute laufende Engine-
Pipeline.

**Backend:**
- Migration `0012_summer_mode_scenario`: atomarer Daten-Erhalt
  (`scenario` seeden, `global_config.summer_mode_active=true` ⇒
  `scenario_assignment(global, is_active=true)`, dann Spalte droppen).
  Lokaler Auf-Ab-Auf-Zyklus mit Daten-Erhalt verifiziert vor T2.
- `GlobalConfig`-Model + Pydantic-Schemas ohne
  `summer_mode_active` (Sommermodus-Datumsfelder bleiben informativ).
- `rules/scenarios.py` mit `is_summer_mode_active(session)` als
  Layer-0-Quelle.
- Engine Layer 0 nutzt neuen Helper; Reason wechselt auf
  `CommandReason.SCENARIO_SUMMER_MODE`, `SUMMER_MODE` bleibt
  deprecated im Enum (historische `event_log`-Einträge).
- Neuer Router `api/v1/scenarios.py`: `GET /api/v1/scenarios`,
  `POST /api/v1/scenarios/{code}/activate`, `POST /api/v1/scenarios/{code}/deactivate`.
  Heute nur `scope=global`; `room_type`/`room` ⇒ 422 (Pydantic-Literal).
- `config_audit`-Eintrag pro (De-)Aktivierung; `# AUTH_TODO_9_17` an
  beiden POST-Handlern, `request.client.host` als `request_ip`.

**Frontend:**
- `components/ui/{tabs (9.14), switch (9.16), card (9.16)}.tsx` —
  Switch + Card neu (radix-react-switch installiert).
- `components/scenario-card.tsx`: Card mit Switch + ConfirmDialog;
  Aktivieren = `destructive`-Intent, Deaktivieren = `primary`.
- `/szenarien` (Stub aus 9.13b ersetzt) — responsive Grid, heute
  eine Card (Sommermodus). Toast „aktiviert/deaktiviert — Engine
  übernimmt in ≤ 60 s".
- Warn-Banner auf `/einstellungen/temperaturen-zeiten` (gelber
  `bg-warning-soft`-Stil, Material-Symbol `warning`) bei aktivem
  Sommermodus + Link „Verwalten → /szenarien".

**Tests:**
- Backend: 7 API-Tests in `test_api_scenarios.py` (Liste, Activate,
  Idempotenz, Audit, Deactivate-Audit, Scope-Reject, 404).
  Layer-0-Tests in `test_engine_skeleton.py` + `test_engine_trace_consistency.py`
  auf neue Reason + scenario_assignment-Quelle umgestellt.
- Frontend Playwright: `szenarien.spec.ts` (Switch → AlertDialog →
  Toast → Status-Wechsel), `temperaturen-zeiten-warn-banner.spec.ts`
  (Banner an/aus). `sidebar.spec.ts`-Stub-Liste um `/szenarien`
  reduziert, da Page nun echt ist.

**Out of Scope (Brief-konform):**
- Auth/NextAuth (kommt mit 9.17).
- Weitere Szenarien + volle Szenario-Auflösung in Layer 2 (kommt
  mit zurückgestelltem 9.16b, „nach erstem Winter mit Live-Daten").
- Saison-UI (ebenfalls 9.16b).
- Engine-Refactor Layer 2/3/4 (Drift wird nur via AE-49 dokumentiert).

**Tag-Vorschlag:** `v0.1.13-szenario-engine` (Strategie-Chat-Freigabe
nach Cowork-Visual-Review abwarten).

**Doku-Naming-Hinweise:**
- Brief sagte „STATUS.md §2af"; nächster freier nach §2ad ist §2ae —
  pragmatisch übernommen.
- Brief sagte „ADR AE-48"; AE-48 ist bereits Vicki-Downlink-Helper
  (CLAUDE.md §5.28). Neuer ADR wurde als **AE-49** angelegt, AE-31
  verweist darauf.

Nächster Sprint: 9.17 NextAuth + User-UI (Pflicht-Verschluss aller
`AUTH_TODO_9_17`-Marker) oder 9.15 Profile (Wochentag-Schedule) je
nach Strategie-Chat-Reihenfolge.

**Sprint 9.16a Hotfix (2026-05-14):** Umlaut-Drift im
Sommermodus-Seed (`uebernimmt`/`Raeume` statt `übernimmt`/`Räume` in
`scenario.description`) via Migration `0013_fix_summer_mode_encoding`
auf der Live-DB behoben, Migration `0012_summer_mode_scenario`
nachträglich korrigiert (UTF-8 ohne BOM). Encoding-Regression-Test
in `backend/tests/test_seed_scenarios.py` sichert ab. Lokaler
Auf-Ab-Auf-Test mit Mojibake-Reset bestätigt: 0013 greift wenn
Live-DB im alten Mojibake-Stand ist; idempotent. Audit-Befund:
weitere Mojibake-Stellen im Backend existieren nur in Docstrings /
Inline-Kommentaren (0003b/0004/0011 + `engine.py`, `engine_tasks.py`,
`room_types.py`, `global_config.py`, `manual_setpoint_event.py`) —
nicht persistiert, kein User-sichtbarer Effekt, **out of scope** für
diesen Hotfix.

---

## 2af. Sprint 9.17 — Code gemerged, Cutover blockiert (2026-05-14)

**Status:**
- **Code:** auf `develop` gemerged via PR #148 squash, Commit
  `d879fd6` (2026-05-14). GHCR-Build-Images `:develop`-Tag
  aktualisiert (workflow run `25873310750`, beide Images grün).
- **Tag:** noch NICHT vergeben (`v0.1.14-auth` als Vorschlag,
  vergibt der Strategie-Chat NACH Cutover-Freigabe).
- **Cutover (`AUTH_ENABLED=false` → `true` auf heizung-test):**
  blockiert. Zwei harte Cutover-Blocker aus der Cutover-Episode
  vom 2026-05-14 (siehe Backlog §6.2):
  - **B-9.17-4** 🔴 — ~9 GET-Endpoints in `devices`, `rooms`,
    `heating_zones`, `room_types`, `occupancies` ungeschuetzt
    (Brief-T6-Luecke, MUSS in 9.17a vor Cutover).
  - **B-9.17-10** 🔴 — `get_current_user`-System-User-Fallback
    macht `/change-password` unter `AUTH_ENABLED=false`
    unbenutzbar; Forced-Change-Flow gebrochen. MUSS abgefangen
    werden (503/409 statt Fallback).
  Plus 7 weitere 🟡/🟢-Items aus derselben Episode (B-9.17-3,
  -5..-9, -S1) als Sprint-9.17a- bzw. Sprint-10-Kandidaten.
  Bis dahin laeuft heizung-test mit `AUTH_ENABLED=false`.

Authentifizierung implementiert. FastAPI-native JWT-Cookie-Auth statt
NextAuth, 2 Rollen (`admin` / `mitarbeiter`), `business_audit` als
zweite Audit-Domain neben `config_audit`. AE-50 verankert die acht
Entscheidungen. SPRINT-PLAN-9.17-Eintrag korrigiert (T0): vorher
„NextAuth + 5 Rollen", jetzt „Auth + 2-Rollen + business_audit".

**Backend:**
- Migration `0014_auth_and_business_audit`: `user`-Tabelle (id, email,
  password_hash, role, is_active, must_change_password, timestamps,
  last_login_at), `business_audit`-Tabelle (user_id FK,
  action/target_type/target_id, JSONB-Werte, INET-IP),
  `config_audit.user_id` FK auf `user.id`. Bootstrap-Admin via ENV
  `INITIAL_ADMIN_EMAIL` + `INITIAL_ADMIN_PASSWORD_HASH` bei leerer
  `user`-Tabelle. Auf-Ab-Auf-Test gegen Live-Postgres bestanden.
- Auth-Modul `heizung.auth`: JWT (HS256, 12h, `python-jose`), bcrypt
  (work-factor 12, direktes `bcrypt`-Package — Brief sah passlib vor,
  ist aber unmaintained und inkompatibel mit `bcrypt>=4.1`, siehe
  CLAUDE.md §5.29 / AE-50 AE-1), Dependencies `get_current_user` /
  `require_admin` / `require_mitarbeiter`, Rate-Limit-Singleton
  (`slowapi`, 5/Minute pro IP auf `/auth/login`).
- Settings erweitert: `auth_enabled` (Default `false`),
  `jwt_secret_key` (Fallback auf `secret_key`), `jwt_algorithm`,
  `access_token_expire_hours`, `auth_cookie_name`,
  `auth_cookie_secure`, `auth_login_rate_limit`,
  `initial_admin_email`/`initial_admin_password_hash`.
- CLI `python -m heizung.cli.hash_password '<klartext>'` erzeugt
  bcrypt-Hash für ENV-Setting.
- Neue Router:
  - `/api/v1/auth/{login,logout,me,change-password}` mit
    Rate-Limit auf login, generische Fehlermeldung (kein
    User-Enumeration), business_audit-Hook bei change-password.
  - `/api/v1/users/*` admin-only mit Liste, Create, Patch
    (Rolle/is_active), Reset-Password (business_audit), Delete.
    Bricked-System-Schutz: Admin darf eigene Rolle nicht
    aendern; letzter aktiver Admin nicht deaktivierbar /
    loeschbar.
- Bestehende Endpoints (T1-Inventar): 21 mutierende Routen mit
  `require_admin` / `require_mitarbeiter` ausgestattet.
  Belegungs- und Override-Endpoints schreiben `business_audit`
  (OCCUPANCY_CREATE, OCCUPANCY_CANCEL, MANUAL_OVERRIDE_SET,
  MANUAL_OVERRIDE_CLEAR). Stammdaten- und Konfigurations-Audits
  bekommen jetzt `user_id`. **`X-User-Email`-Header in
  `overrides.py` entfernt** (AE-50 AE-8); `user.email` ist
  `created_by` in `manual_override`.
- Alle 7 `# AUTH_TODO_9_17`-Marker aus 9.14/9.16 ersetzt durch
  echte Dependencies.

**Frontend:**
- `AuthContext` mit `useAuth`-Hook (`/me` beim Mount, Login,
  Logout, refresh). `useInactivityLogout` (15 Min, keydown/click/
  touchstart, BroadcastChannel `heizung-auth` für Multi-Tab,
  Hard-Cut ohne Modal — AE-50 AE-4).
- `/login`, `/auth/change-password`,
  `/einstellungen/benutzer` (ersetzt Stub aus 9.13b).
  Mitarbeiter-Liste mit Inline-Rolle-Toggle, Aktionen-Buttons
  (Passwort, Aktivieren/Deaktivieren, Loeschen) plus
  ConfirmDialog für destruktive Aktionen.
- Sidebar-Footer: User-Email + Rolle + Logout-Button.
- Stub-Cleanup (T10): Sprint-Nummer-Badges raus,
  EmptyState zeigt „In Vorbereitung" wenn `plannedSprint`
  nicht gesetzt. Saison, Profile, API, Gateway,
  Temperaturverlauf entsprechend angepasst.
- shadcn `Label` neu (Pure-CSS, kein neuer Radix-Dep).

**Tests:**
- Backend pytest gegen Live-Postgres: 308 passed + 1 xfailed
  (23 neu in T12). `test_api_auth.py` (Login success/fail/
  inactive, generische Fehler, Rate-Limit 5/min, Logout,
  /me-Cookie-Pfad, change-password mit business_audit-Hook).
  `test_api_users.py` (admin-only, mitarbeiter→403, duplicate-
  email 409, PATCH-Rolle, eigene-Rolle-Schutz, letzter-Admin-
  Schutz, reset-password mit business_audit, DELETE).
- Frontend Playwright: 32/32 green (24 alt + 8 neu in
  `auth.spec.ts`). Login-Formular, falsche Credentials
  Inline-Fehler, Login-Redirect Dashboard,
  must_change_password-Redirect, /einstellungen/benutzer Guard
  (Mitarbeiter→/, Admin sieht Liste, Dialog), Sidebar-Footer
  zeigt User+Logout.
- T12-Pflicht-Stop: passlib 1.7.4 + bcrypt 5.0 inkompatibel
  (passlib unmaintained seit 2020-10, `detect_wrap_bug`-Init
  triggert ValueError fuer >72-Byte-Test-Secrets, jeder erste
  `hash_password()`-Call crasht). `password.py` auf direktes
  `bcrypt` umgestellt, `passlib[bcrypt]` aus `pyproject.toml`
  entfernt. Brief-Abweichung in AE-50 Punkt 1, Lesson in
  CLAUDE.md §5.29.

**Tag-Vorschlag:** `v0.1.14-auth` — **noch NICHT vergeben**.
Vergabe erst nach Cutover-Freigabe (Strategie-Chat) und Cowork-
Visual-Review.

**Out of Scope (Brief-konform):**
- Self-Service-Passwort-Reset via E-Mail (B-9.17-1)
- E-Mail-Versand-Infrastruktur generell
- Audit-UI im Frontend (B-9.17-2)
- OAuth-Provider, Magic-Link-Login, 2FA
- Multi-Mandanten-Tenant-Trennung (kommt mit 11+)
- Owner-Rolle, Hotelier/Techniker/Reception-Differenzierung

**Aktivierungs-Hinweis fuer heizung-test (gesperrt bis Backlog-
B-9.17-Liste abgearbeitet + Strategie-Chat-Freigabe):**
Sprint mergt mit `AUTH_ENABLED=false`. Reihenfolge zum Aktivieren:
1. ENV setzen: `INITIAL_ADMIN_EMAIL=admin@…`,
   `INITIAL_ADMIN_PASSWORD_HASH=<bcrypt>` (via
   `python -m heizung.cli.hash_password`),
   optional `JWT_SECRET_KEY=<openssl rand -hex 32>`.
2. Pull-Deploy laeuft, Migration 0014 legt Bootstrap-Admin an.
3. Test-Login auf `/login` mit Initial-Passwort. Bei Erfolg:
   `must_change_password=true` ⇒ Wechsel-Page.
4. ENV `AUTH_ENABLED=true` setzen + Container neu starten.
   Ab jetzt schuetzt Backend alle mutierenden Endpoints scharf.

Nächster Sprint: offen — Strategie-Chat entscheidet (Kandidaten:
9.15 Profile, 9.18 Dashboard, 9.16b Saison + weitere Szenarien).

---

## 2ag. Sprint 9.17a Auth-Cutover-Hotfix (2026-05-15, abgeschlossen)

**Status:**
- **Code:** auf `develop` gemerged, siehe PR. Cutover-Blocker beseitigt,
  `AUTH_ENABLED=true` auf heizung-test übertragbar.
- **Tag:** noch NICHT vergeben (`v0.1.14-auth` Strategie-Chat
  vergibt nach erfolgreichem Live-Cutover, **nicht** aus 9.17a heraus).
- **Pflicht-Stops:** T1 (Endpoint-Inventar) und T3 (Identitäts-Pattern)
  beide vom User am 2026-05-15 freigegeben.

Schließt zwei harte Cutover-Blocker (B-9.17-4, B-9.17-10) plus fünf
UX-Defekte (B-9.17-5, -6, -7, -8, -9) aus der Cutover-Episode 2026-05-14.

**Backend:**
- T1 Endpoint-Inventar (`docs/features/2026-05-15-sprint-9-17a-endpoint-inventar.md`):
  48 Endpoints in 11 Routern; 17 GET-Endpoints in 9 Routern
  unauthentifiziert. Lesson §5.30-Schätzung "~9 GETs in 5 Routern" war
  zu niedrig.
- T2 Coverage: neue Dependency `require_user` (Admin+Mitarbeiter,
  semantisch für lesendes Recht; technisch heute identisch zu
  `require_mitarbeiter`, eigener Name für zukunftssichere
  Rollen-Erweiterung). 17 GET-Endpoints abgesichert, plus
  `DELETE /occupancies/{id}` (immer-405-Stub) mit
  `require_mitarbeiter` vor 405. GET `/users` bleibt
  `require_admin` (sensible User-Daten — Brief-Regel-Abweichung
  in §5.30 dokumentiert).
- T3 Identitäts-Pattern: neue Dependency `require_real_user` (kein
  System-User-Fallback). `/auth/me` und `/auth/change-password`
  liefern unter `AUTH_ENABLED=false` 503 statt falscher Identität
  (B-9.17-10 Fix). `/auth/login` und `/auth/logout` unverändert.

**Frontend:**
- T4 Wording 401/429/503 (B-9.17-5): Login + Change-Password mit
  differenzierten Fehlertexten. 429 → "Zu viele Versuche. Bitte
  60 Sekunden warten." 503 → "Anmeldung gerade nicht möglich.
  Bitte später erneut versuchen oder die Verwaltung kontaktieren."
- T5 Mojibake (B-9.17-7): "Passwoerter ueberein" → "Passwörter
  überein" in change-password. Audit Plus: aria-label "Passwort
  zuruecksetzen" → "Passwort zurücksetzen" + Doku-Kommentar in
  benutzer/page.tsx.
- T6 Password-Sichtbarkeits-Toggle (B-9.17-8): neue
  `<PasswordInput>`-Komponente mit visibility/visibility_off-
  Toggle und dynamischem aria-label. Eingebaut: Login,
  Change-Password (3 Felder), Admin-Reset-Dialog.
- T7 Inline-Fehler Forced-Change (B-9.17-9): pro Feld eigener
  Inline-Fehler (`current_password`, `new_password`,
  `repeat`). Generischer Block bleibt nur für 429/503/500-
  Server-Fallback.
- T8 Saison-Stub (B-9.17-6): Custom-Page mit Link zu
  `/szenarien` (Sommermodus-Soforttoggle).

**Tests:**
- Backend pytest: erwartet ≥ 320 passed + 1 xfailed
  (Vor-Sprint 308 + 12+ neu in `test_api_read_endpoints_auth.py`
  + `test_api_auth.py`-Erweiterungen).
  - Neues File `test_api_read_endpoints_auth.py`: 17 GET-Endpoints
    × 3 Cases (no-cookie/mitarbeiter/admin) + DELETE-occupancy
    × 3 Cases (gebündelt in 6 Tests via Listen-Iteration).
  - `test_api_auth.py` erweitert: 4 neue T3-Tests (AUTH=false→503
    für /me und /change-password, AUTH=false /logout läuft,
    AUTH=true ohne Cookie /change-password→401).
- Frontend Playwright: erwartet ≥ 41 passed (32 alt + 9 neu).
  - 4 Tests Wording-Differenzierung 429/503
  - 3 Tests Inline-Fehler Forced-Change
  - 1 Test Mojibake-Audit
  - 1 Test Password-Toggle

**Brief-Abweichungen (dokumentiert):**
- Neues Test-File `test_api_read_endpoints_auth.py` angelegt.
  Brief sagte "keine neuen Test-Files anlegen, bestehende
  test_api_*.py erweitern". Für 5 betroffene Domains (rooms,
  heating_zones, occupancies, room_types, global_config)
  existierten keine test_api_<domain>.py-Files — wörtliche
  Brief-Erfüllung unmöglich. Pragmatik: ein einziges Sammel-
  File statt fünf neue.

**Backlog-Abhakung:**
- ✅ B-9.17-4 (GET-Endpoint-Coverage)
- ✅ B-9.17-5 (Wording 401/429/503)
- ✅ B-9.17-6 (Saison-Stub-Verweis)
- ✅ B-9.17-7 (Mojibake Forced-Change)
- ✅ B-9.17-8 (Password-Toggle)
- ✅ B-9.17-9 (Forced-Change Inline-Fehler)
- ✅ B-9.17-10 (Identitäts-Fallback-Fix)

**Offen für Sprint 10 / separate Sprints:**
- B-9.17-1 (Self-Service-Reset via E-Mail)
- B-9.17-2 (Audit-UI Frontend)
- B-9.17-3 (`celery_beat` unhealthy)
- B-9.17-S1 (Secret-Rotation)

**Doku:**
- CLAUDE.md §5.30 neue Lesson "Auth-/Permission-Sprints: alle
  Endpoints absichern, nicht nur mutierende".
- AE-50 Querverweis ergänzt: Cutover-Befund 2026-05-14 + Hotfix
  9.17a, Inventar-Pflicht für Auth-Sprints jetzt Standard.
- SPRINT-PLAN.md 9.17a-Block direkt nach 9.17.
- Endpoint-Inventar als Feature-Doku.

---

## 2ah. Sprint 9.17b Logout-Cookie-Fix + Rate-Limit-Verifikation (2026-05-15, abgeschlossen)

**Status:**
- **Code:** auf `develop` gemerged via PR.
- **Tag:** noch NICHT vergeben (`v0.1.14-auth` Strategie-Chat
  vergibt NACH zweitem erfolgreichem Cowork-Smoke / TC6-Re-Run).
- **Cutover:** `AUTH_ENABLED=true` bleibt aktiv. Kein Re-Flip nötig.

Schließt zwei Befunde aus dem Post-Cutover-Smoke-Test 9.17a:
- **B-9.17a-1** 🔴 Logout-Cookie wurde nicht invalidiert
  (FastAPI Response-Parameter-Bug, Session blieb aktiv).
- **B-9.17a-2** 🟡 Rate-Limit-Wording-Pfad verifiziert.

**Backend:**
- T1 Fix `backend/src/heizung/api/v1/auth.py`: Logout-Handler nutzt
  Variante B (eigenes `Response`-Objekt erzeugen, `_clear_auth_cookie`
  darauf anwenden, dieses zurückgeben). 3-Zeilen-Änderung +
  Kommentar mit Lesson-Querverweis §5.31.
- T2 Backend-Test `test_logout_response_carries_cookie_deletion_header`
  in `test_api_auth.py`: prüft Status 204, `set-cookie`-Header
  vorhanden, Header enthält `Max-Age=0` oder `Expires=Thu, 01 Jan 1970`
  (Cookie-Lösch-Indikator). Schliesst die false-positive-Lücke des
  alten `test_logout_clears_cookie`-Tests, der manuell den Cookie-
  Jar geleert hatte.
- T3 Rate-Limit-Test: bestehender
  `test_login_rate_limit_blocks_after_5_attempts_per_ip` aus
  Sprint 9.17 erweitert um Body-Assertion (slowapi-Detail-Feld muss
  gesetzt sein, sonst kein Mapping zum Frontend-Wording möglich).

**Frontend:**
- T4 429-Wording: bestehende Sprint-9.17a-Tests ("Login: 429 zeigt
  Wartezeit-Hinweis", "Change-Password: 429 zeigt Wartezeit-Hinweis")
  decken den Pfad bereits ab. Verifiziert grün, keine Code-Änderung.

**Tests:**
- Backend pytest: erwartet **321 passed + 1 xfailed** (320 alt + 1
  neu T2). Soll-Zahl ≥ 322 Brief: nicht erreicht, weil T3 als
  Body-Erweiterung in bestehendem Test landete statt als neuer Test.
  Die Soll-Zahlen-Differenz dokumentiert.
- Frontend Playwright: **41 passed** (unverändert; T4 deckte schon ab).

**Backlog-Abhakung:**
- ✅ B-9.17a-1 (Logout-Cookie-Invalidierung)
- ✅ B-9.17a-2 (Rate-Limit-Wording-Pfad verifiziert)

**Neuer Backlog-Eintrag:**
- B-9.17b-1 (info): Server-side JWT-Blacklisting bei Logout —
  Single-Mandant-akzeptabel, für Multi-Mandant nötig.

**Doku:**
- CLAUDE.md §5.31 neue Lesson "FastAPI Response-Parameter vs.
  explicit Response-Return: zwei verschiedene Objekte".
- AE-50 Nachtrag erweitert.
- SPRINT-PLAN.md 9.17b-Block.

**Tag-Vergabe:** `v0.1.14-auth` auf Commit `41a8dcf` am 2026-05-15
12:09 CEST gesetzt. Annotated Tag mit Auth-Track-Zusammenfassung
(9.17 Foundation + 9.17a Cutover-Coverage + 9.17b Logout-Fix).
URL: https://github.com/rexei123/heizung-sonnblick/releases/tag/v0.1.14-auth

**Live-Verifikation 2026-05-15:**
- Cookie-Lösch-Header per Browser-Devtools dokumentiert:
  `Set-Cookie: heizung_session=""; expires=<jetzt>; HttpOnly; Max-Age=0;
  Path=/; SameSite=Lax; Secure` (alle Schutz-Attribute korrekt).
- Browser-Cookie-Jar nach Logout-Klick leer.
- Direktzugriff auf `/zimmer` ohne Auth → HTTP 401 (Caddy-Schicht
  davor greift schneller als Backend; beide Schichten korrekt
  geschützt).
- Cowork-Smoke-Test 9.17a (7 TC) + manueller Re-Smoke 9.17b
  (4 Beweisschritte) bestätigen Funktion.

**Backlog-Abhakung:**
- B-9.17a-1 (Logout-Cookie-Invalidation) ✅
- B-9.17a-2 (Rate-Limit-Wording) ✅ (via Backend-Body-Assertion in
  bestehendem Test, Frontend-Wording-Pfad bereits in 9.17a T4 fertig)

**Cutover-Status:**
- `AUTH_ENABLED=true` auf heizung-test seit 2026-05-15 10:18 UTC
  stabil.
- Caddy-Basic-Auth-Schicht (HOTEL_BASIC_AUTH_HASH) bleibt aktiv
  als äußere Hülle bis Tailscale-Hardening (Sprint 12+).
- heizung-main noch nicht migriert. Wartet auf produktive
  Bestätigung auf heizung-test über 1-2 Wochen, dann separater
  Cutover-Sprint.

**Auth-Track 9.17/9.17a/9.17b abgeschlossen.** FastAPI-native JWT-
Cookie-Auth ist live. Architektur-Entscheidung AE-50 vollständig
implementiert.

---

## 2ai. Sprint 10-Doku Strategie-Refresh (2026-05-15, abgeschlossen)

Strategie-Re-Priorisierung nach Auth-Cutover-Erfolg. Hotelier-
Statement: „System extrem stabil laufen bevor weitere Features dazu
kommen. Casablanca im Extremfall umgehbar, weil Belegung auch
manuell pflegbar."

**Phasen-Logik neu (verbindlich ab 2026-05-15):**

- Phase 1 Stabilisierung (Sprint 10/10a/10b/10c, Mai-Juni)
- Phase 2 Live-Beobachtung heizung-test (Juni-Juli)
- Phase 3 Frostschutz-Reaktivierung (Sprint 11, Juli)
- Phase 4 heizung-main-Migration (Sprint 12, Juli-August)
- Phase 5 PMS-Casablanca (Sprint 13, August)
- Phase 6 Go-Live + Tag v1.0.0 (Sprint 14, September)
- Phase 7 Features (Sprint 15+, Winter und danach)

**Heizperiode-Start:** 1. Oktober 2026, Hotel Sonnblick Kaprun.

**Sprint-Renumerierung:** Alte Feature-Sprints 9.18-9.21 in Phase 7
verschoben. Alter Sprint 10 (Hygiene) bleibt Sprint 10. Alter
Sprint 11 (PMS) wird Sprint 13. Alter Sprint 12 (Backup) wird
Sprint 12 (heizung-main-Migration, jetzt umfassender). Alter
Sprint 13 (Wetterdaten) in Phase 7 verschoben. Neuer Sprint 11
= Frostschutz-Reaktivierung. Sprint 14 = Go-Live bleibt.

**Geänderte Dokumente:**
- `docs/STRATEGIE-REFRESH-2026-05-15.md` neu angelegt
- `docs/SPRINT-PLAN.md` umstrukturiert nach Phasen-Logik
- `docs/ARCHITEKTUR-REFRESH-2026-05-07.md` §7 als überholt markiert
- `CLAUDE.md` §0.2 Source-of-Truth-Hierarchie um Strategie-Refresh
  ergänzt

**Querverweise:** STRATEGIE-REFRESH-2026-05-15.md, SPRINT-PLAN.md
neu strukturiert. ARCHITEKTUR-REFRESH-2026-05-07.md bleibt
Vorgänger-Dokument, nicht ersetzt.

**Tag-Vergabe:** keiner — Doku-Sprint.

---

## 2aj. Sprint 10 CI-Hygiene + Test-Coverage (2026-05-15, abgeschlossen)

Erster Stabilisierungs-Sprint der neuen Phasen-Logik (§2ai). Hygiene-
Sprint ohne Engine-Touch. Autonomiestufe 2 mit zwei Pflicht-Stops:
T6-Secrets-Rotation (Strategie-Chat-Freigabe vor Execute), PR-Erstellung
(Sprint-Bericht-Review).

**Task-Status:**

| Task | Inhalt | Status |
|---|---|---|
| T1 | `psycopg2-binary` in `backend/pyproject.toml [dev]`-extras (B-9.10-6, B-9.11x-1). | ✅ Pass — lokal `pytest tests/test_migrations_roundtrip.py tests/test_manual_override_model.py -x`: 12 skipped (kein psycopg2-Import-Fehler mehr). |
| T2 | Roundtrip-Tests fuer Migration 0012 (B-9.16-2). Plus env.py-Fix: `TEST_DATABASE_URL` hat Vorrang vor `settings.database_url` (Bug, der test_migrations_roundtrip gegen die Dev-/Prod-DB laufen liess statt gegen die Test-DB). CI-Workflow legt `heizung_migration_test` mit TimescaleDB-Extension an. | ✅ Pass — 8/8 Tests gegen lokale `heizung_migration_test` gruen. |
| T3 | celery_beat-Healthcheck-Diagnose + Backlog-Konsolidierung (B-9.11-4 Master, B-9.11x-3 + B-9.17-3 Duplikate). | ✅ Pass — Diagnose 2026-05-15 auf heizung-test bestaetigt: kein depends_on-Service-Healthy auf celery_beat, beat schedulet mit konstanter 60-s-Kadenz, Engine-Eval laeuft im healthy celery_worker. Akzeptanz-Lesson CLAUDE.md §5.32. |
| T4 | mypy strict in `backend/tests/` reduzieren (B-9.10d-2). | ✅ Pass — Sprint-Start war bereits 32 Errors (9.17a/b/c hatte zwischenzeitlich reduziert vom 71-Brief-Stand), Final-Stand 0. AsyncIterator-, dict-Type-Args und unused `# type: ignore[...]` adressiert. |
| T5 | AppShell-Sidebar auf `/login` + `/auth/*` ausblenden (B-9.17b-2). | ✅ Pass — `app-shell.tsx` prueft `usePathname()`. Playwright-Test `sidebar.spec.ts` deckt Regression ab; lokal via `npm run dev` + curl-HTML-Snapshot verifiziert. |
| T6 | Secrets-Rotation auf heizung-test (B-9.17-S1, Pflicht-Stop). | ✅ Pass — `/tmp/rotate-secrets.sh` (Backup, ALTER USER via STDIN-Heredoc, sed-Inplace), Browser-Verify durch Strategie-Chat: Login `kaprun@hotel-sonnblick.at` funktional, Sidebar zeigt Glyphen, `/zimmer` laedt Daten. Backup `.env.bak-pre-rotation-20260515T135700Z` bleibt 7 Tage auf Server. |
| T7 | Backlog-Konsolidierung in STATUS.md §6.2. | ✅ Pass — Duplikate B-9.11x-3 + B-9.17-3 auf B-9.11-4 zusammengefuehrt. ✅-Markierungen fuer alle Sprint-10-Items. Material-Symbols-Aspekt aus B-9.13b-1 (✅ via PR #154) abgespalten von Cache-Busting-Aspekt (neu B-10-5 fuer Frontend-Polish-Sprint). |
| T8 | pre-commit-Hook fuer `ruff format --check` + `ruff check` (B-9.10d-6). | ✅ Pass — `.pre-commit-config.yaml` mit ruff-pre-commit `v0.15.12` (matched backend/pyproject.toml + CI-Workflow). RUNBOOK §10f Setup + Versionspflege. Lokal verifiziert via absichtlichem Format-Fehler (Hook blockt + reformatiert). |

**Pre-Push-Toolchain-Status (lokal, vor Final-Commit):**

- Backend: `ruff check` clean, `ruff format --check` clean, `mypy src` Success no issues, `pytest` 181 passed + 154 skipped (Test-DB-Skip ohne TEST_DATABASE_URL).
- Frontend: `npm run type-check` clean, `npm run lint` no ESLint warnings/errors, `npm run build` erfolgreich.

**Backlog-Konsolidierungs-Bilanz (§6.2):**

- Erledigt durch Sprint 10: B-9.10-6, B-9.10d-2, B-9.10d-6, B-9.11x-1, B-9.16-2, B-9.17-S1, B-9.17b-2, B-9.13b-1 (Material-Symbols-Aspekt).
- Konsolidiert: B-9.11x-3 + B-9.17-3 als ✅ Duplikat von B-9.11-4.
- Umformuliert: B-9.11-4 als „akzeptierter Healthcheck-Drift ohne Engine-Auswirkung" mit Verweis CLAUDE.md §5.32.
- Neu: B-10-5 Cache-Busting nach Frontend-Deploys (abgespalten aus B-9.13b-1, eigener Frontend-Polish-Scope).

**Neue Lessons:** CLAUDE.md §5.32 Akzeptierter Container-Healthcheck-Drift
ohne Engine-Auswirkung (Diagnose-Checkliste vor Fix-Versuchen).

**Tag-Vergabe:** keiner — Hygiene-Sprint, kein Feature, kein Release-Marker.

**Out of Scope (Bestaetigung):** Hardware-Diagnose Vicki (Sprint 10a), asyncpg-Umstellung (nicht im Sprint-10-Scope; pyproject-Variante in T1 gewaehlt), celery_beat-Healthcheck-Code-Fix (per §5.32-Doku-Akzeptanz erspart), Frostschutz-Reaktivierung (Sprint 11), fail2ban-Konfig (B-10-3 in 10c oder Security-Hardening-Sprint), DST-Phase-0-Diagnose (B-10-4 in 10a oder eigener Sprint), Caddy-Touch (B-10-2 bereits via PR #154 erledigt).

**Querverweise:** SPRINT-PLAN.md Sprint 10, STRATEGIE-REFRESH-2026-05-15.md
Phase 1, CLAUDE.md §5.32, AE-50 (Auth + JWT_SECRET_KEY-Fallback).

---

## 2ak. Sprint 11-Prep Doku-Konsolidierung Zuordnungs-Architektur (2026-05-15..2026-05-16, abgeschlossen)

Doku-only-Sprint zur Konsolidierung der Brainstorming-Ergebnisse
aus Strategie-Chat 2026-05-15. Master-Quelle:
`docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md`. Vier neue ADRs
(AE-51..AE-54). Vorbedingung für Sprint 11.

**Autonomiestufe:** 2 (reine Doku, keine Code-/Server-Berührung).

**Task-Status (Stand 2026-05-15, T1-T5 abgeschlossen):**

| Task | Inhalt | Status |
|---|---|---|
| T1 | `docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md` als Master-Quelle anlegen. | ✅ Commit `64ad4ec`. |
| T2 | AE-51..AE-54 in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` ergänzen. | ✅ Commit `34523f4`. |
| T3 | `docs/STRATEGIE.md` §6.2 R5 belegungs-abhängig + neuer §6.5 Health-Monitoring + §7.1 Begriffs-Konsolidierung. | ✅ Commit `96e13b7`. |
| T4 | `docs/STRATEGIE-REFRESH-2026-05-15.md` Phasen 1-7 konkretisiert (Phase 4b Pre-Pairing neu, Phase 6 zeit-definiert), §5 Migrations-Tabelle, §6 Sprint-Renumerierung. | ✅ Commit `dc0d95d`. |
| T5 | `docs/SPRINT-PLAN.md` Sprint 11..17 + 14b arc42-Konsolidierung, Sprint 10b annotiert „verschoben"; Mini-Patch STRATEGIE-REFRESH §3/§5/§6 für Sprint 16a (PMS conditional). | ✅ Commit `b167702`. |
| T6 | `STATUS.md` §2ak + §6.2 B-11prep-1..8. | ✅ Commit `1f3602c`. |
| T7 | `CLAUDE.md` §5.33 + §5.34 (Lessons knapp, 3-5 Zeilen, Zeiger auf Master-Quelle; §5.32 durch Sprint 10 belegt, Numerierung +1). | ✅ Commit `2713240`. |
| T8 | `docs/SESSION-START.md` Pre-Read für Sprint 11-17 (plus Doku-Drift-Fix aus Sprint 10: STRATEGIE-REFRESH-2026-05-15.md ergänzt). | ✅ Commit `45067c1`. |
| T9 | `docs/CHANGELOG-Design-Strategie.md` Eintrag 2026-05-15. | ↪ entfallen — S6 Doppel-Doku-Vermeidung; Info bereits in T1/T2/T6/T7 verankert, CHANGELOG-Design-Strategie ist auf Design-System (Tokens/Icons/Komponenten) fokussiert, Architektur-Strategie passt thematisch nicht. |
| T10 | `docs/RUNBOOK.md` §10h Pre-Pairing-Workflow-Stub + §10d.6 Health-Status-Stub (§10f durch Sprint 10 T8 / §10g durch Sprint 10 T6 belegt, Numerierung +2). | ✅ Commit `4432f41`. |
| T11 | `docs/AI-ROLES.md` Check. | ✅ no-op gesichtet, keine Anpassung nötig; optionale Mini-Erweiterung der Fehlerbilder-Tabelle in T14-Cleanup. |
| T12 | Cross-Referenz-Check über alle angepassten Dateien. | ✅ no-op alle Patterns grün (AE-51..54-Range-Verweise konsistent, Master-Quelle in 9 Dateien vernetzt, 5/5 T1-T5-Commit-Hashes match). |
| T13 | Markdown-Lint via Grep-Spot-Check (Code-Fence-Parität, Broken-Links, Tabellen-Pipe-Konsistenz). | ✅ no-op alle kritischen Patterns grün; §6.2-Spalten-Drift pre-existing, Tooling-Setup als Backlog-Idee für Sprint 14b notiert. |
| T14 | Sprint-Abschluss-Bericht + Cleanup-Commit + Bitte um Push-/Tag-Freigabe. | ✅ Cleanup-Commit `931c546` (STATUS.md + AI-ROLES.md kosmetisch), PR #157 gemerged 2026-05-16 auf `c0d931e`. |

**Geänderte Dokumente bisher (T1-T5):**

- `docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md` (neu, Master-Quelle 314 Zeilen)
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` (+AE-51..54, +215 Zeilen)
- `docs/STRATEGIE.md` (+§6.5 Health-Monitoring, +Begriffs-Box §7.1, R5 belegungs-abhängig)
- `docs/STRATEGIE-REFRESH-2026-05-15.md` (Phasen 1-7 konkretisiert, Phase 4b/6 neu, §5 Migrations-Tabelle, §6 Sprint-Renumerierung)
- `docs/SPRINT-PLAN.md` (Sprint 11-Prep, 11, 12, 13, 14, 14b, 15, 16, 16a, 17 als Outlines; Sprint 10b annotiert)

**Tag-Vergabe:** `v0.1.15-zuordnungs-architektur-doku` nach T14 +
expliziter Push-Freigabe durch Strategie-Chat (entgegen
Autonomie-Default — Doku-Sprint mit Stop-Disziplin, jeder Task
hat Pflicht-Stop für Strategie-Chat-Review).
Vergeben am 2026-05-16 10:20 +0200 auf Merge-Commit `c0d931e`.

**Querverweise:** SPRINT-PLAN.md Sprint 11-Prep,
STRATEGIE-THERMOSTAT-ZUORDNUNG.md (Master-Quelle),
ARCHITEKTUR-ENTSCHEIDUNGEN.md AE-51..54,
STRATEGIE-REFRESH-2026-05-15.md (Phasen-Modell + Migrations-Plan).

## 2al. Sprint 11 Health-State + Plausi + Zone-Isolation + Aggregat-Lesen (2026-05-17..2026-05-18, abgeschlossen)

**Ziel:** AE-51 §4.1 (Aggregat-Lesen ueber healthy Vickis), AE-53 (Health-State-Modell + Plausi-Filter + 3-Stufen-Alarm) und AE-54 (Engine-Zone-Isolation) implementieren. Mehrfach-Vicki-Zonen lesen Ist-Temp als Mittelwert ueber `healthy`-Devices, Fenster-OR; Crashes in einer Zone reissen nicht den Engine-Worker.

**Branch:** `feature/sprint-11-health-aggregat` (9 Commits ahead develop nach T6).

**Task-Reihenfolge:**

| Task | Commit | Inhalt |
|------|--------|--------|
| T0a | `9b78b81` | chore: T13/T14 Doku-Loose-Ends |
| T0b | `dfbeeba` | chore: STATUS.md §1 Header zu Sprint 11 state |
| T1 | `bf5573a` | feat: `health_state`-Spalten + Migration `0015_health_state` |
| T2 | `f738179` | feat: Plausi-Filter [-20°C, 60°C] in mqtt_subscriber |
| T3 | `024bba0` | feat: Zone-Aggregat-Helper + healthy-Filter Layer 4 (AE-51 §4.1) |
| T4 | `17ba2ca` | feat: Room-Eval Failure-Hardening + zone=degraded on crash (AE-54) |
| T5-prep | `e16c408` | chore: Redis-Client-Helper aus engine_lock extrahiert |
| T5 | `3115cde` | feat: Health-State Compute-Task (5min-Beat) + Implausible-Counter (AE-53) |
| T6 | `7b12ff9` | feat: Health-Alert Logger-Stub fuer silent transitions (AE-53) |

**Test-Counts:** 261+1 (vor Sprint 11) → 360+1 (nach T6), +99 neue Tests verteilt auf 4 neue Test-Dateien (`test_engine_aggregate.py`, `test_engine_isolation.py`, `test_health_compute.py`, `test_health_alerts.py`).

**Sprint-Drifts (alle dokumentiert in Commit-Messages + Strategie-Chat 2026-05-17..2026-05-18):**

1. T1 Migration-Nummer 0011 → 0015 (Phase-0-Befund: 0011-0014 belegt)
2. T3 Brief-Annahme `_load_room_context` laedt Readings — Code-Realitaet anders, Option-B-Refactor verworfen, Aggregat-Helper als Pure-Function in `rules/aggregation.py` verankert
3. T4 Brief-Wortlaut `evaluate_all_zones` existiert nicht, Engine ist Room-zentrisch — Room-Iteration mit Zone-Health-Mutation fuer alle Zonen des Raums; HeatingZone-granulare Iteration kommt Sprint 12
4. T4 Brief-Wortlaut `_evaluate_room_async -> None` — bestehender Code returnt Dict, Brief-Patch Option B (Status-Dict-Return sanktioniert)
5. T4 §5.1-Verletzung in Diagnose-Phase (Eigen-Reparatur ohne Stop) — als Lesson §5.40 verankert
6. T5 Brief-Annahme async-Redis-Client — bestehender Code nutzt sync via engine_lock-Helper, Variante b (asyncio.to_thread) gewaehlt + Helper extrahiert (T5-prep)
7. T5 Zone-State-Regel-Erweiterung Mischung silent+healthy → degraded (Brief-Sanktion 2026-05-18)
8. T6 caplog-Quirk nicht async-spezifisch — Logger-Asserts gestrichen, Smoke-Tests genuegen; Audit via Code-Review + journalctl

**Folge-Sprint-Backlog (7 T7-Vormerke):** siehe `SPRINT-PLAN.md` Sprint-11-Sektion ## Folge-Sprint-Backlog.

**Querverweise:** AE-51 §4.1 + §4.2, AE-53, AE-54 (alle in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`), Strategie-Chat-Logs 2026-05-17 + 2026-05-18, CLAUDE.md §5.35-§5.41 (7 neue Lessons).

---

## 2am. Sprint 12 Multi-Vicki-Schreibpfad + Fenster belegungs-abhaengig + Override-Reject (2026-05-19, abgeschlossen)

**Ziel:** AE-51 P3 (Multi-Vicki-Dispatch symmetrisch) + AE-52 (Layer 4 occupancy-aware + Override-Reject 409). Schreib-Pfad iteriert pro Zone, healthy-Filter, parallele Submission, per-Vicki-Hysterese. Layer 4 differenziert VACANT (Frostschutz 10 degC) vs OCCUPIED (`default_t_vacant` Setback). Override-Service rejected mit HTTP 409 + JSONB-Body bei offenem Fenster, kein DB-Insert.

**Tag:** `v0.1.17-multivicki-fenster` (annotated, gesetzt 2026-05-19 auf Squash-Commit `c9f58d1`; Tag-Objekt `ac45305`).

**PR:** [#160](https://github.com/rexei123/heizung-sonnblick/pull/160) squash-merged 2026-05-19T13:38:48Z (Squash-Commit `c9f58d1`).

**Branch:** `feat/sprint-12-multivicki-fenster` (6 Commits T2-T7 ueber develop@`93b1305`, nach Merge geloescht).

**Commit-Range im Feature-Branch:** `168e2b2..18275ba` (T2..T7), squash-merged als Single-Commit `c9f58d1` auf develop. Stat-Summary pro Original-Commit:

| Commit | Subject | Stat |
|--------|---------|------|
| `168e2b2` (T2) | feat(sprint-12-t2): multi-vicki schreib-pfad symmetrisch (STRATEGIE §4.2, AE-51 P3) | 3 files, +822/-74 |
| `2ee8a96` (T3) | feat(engine): layer 4 room_status output-determinant (AE-52) | 2 files, +211/-13 |
| `cd96952` (T4) | feat(override): reject creation when window open (AE-52, 409) | 7 files, +491/-39 |
| `5da9f1b` (T5) | test(sprint12): e2e verbund-szenarien fuer multivicki + fenster + override-reject | 1 file, +746 |
| `83f19b9` (T6) | docs(sprint-12): status, lessons, adrs, sprint-plan + sprint-12a block | 5 files, +478/-24 |
| `18275ba` (T7) | fix(sprint-12-t7): test-fixture varchar-constraint + eventlog details-key + lokal-db-runbook + claude-lessons §5.49 §5.50 | 4 files, +182/-19 |

**Total Squash-Merge `c9f58d1` (15 files):** **+2910 insertions / -149 deletions** (gemaess PR-Merge-Output). Neues Modul `rules/window_state.py`. **+25 neue Tests** (T2: +7 Schreib-Pfad, T3: +3 Layer-4-room_status + Test-6-Enhancement, T4: +8 Helper/Service/API, T5: +7 E2E-Verbund). T7-Hotfix: 0 neue Tests, behoben 9 bestehende Fixture-Bugs.

**Kern-Liefergegenstaende:**

- `_dispatch_downlinks_per_zone(...)` in `tasks/engine_tasks.py` — per-Zone-Iteration, `asyncio.gather` mit `return_exceptions=True`, individuelles try/except pro Vicki, kein Rollback bei Teil-Erfolg.
- `_last_command_for_device` in `rules/engine.py` (Per-Vicki-Hysterese). `_last_command_for_room` als deprecated markiert, bleibt fuer `EventLog.setpoint_in`-Audit.
- `detect_open_window_zones(session, room_id, now)` als geteilter Helper in neuem `rules/window_state.py`-Modul.
- `layer_window_open` jetzt belegungs-abhaengig + Override-Maskierungs-Marker (`extras["override_overridden_by_window_open"] = True` + `detail`-Prefix).
- `OverrideRejectedWindowOpenError` in `services/override_service.py`, API-409-Mapping in `api/v1/overrides.py`.
- `tests/test_sprint12_e2e.py` mit Szenarien A-G (Engine-Tick A-E, HTTP F-G).

**Drift-Befunde (in CLAUDE.md §5.42-§5.48 verankert):**

- **D7** (§5.44) — EventLog-PK zwingt JSONB-Sub-Trace statt eigener Rows pro Vicki (`details["downlink_per_device"]` + `["downlink_zone_status"]` im HARD_CLAMP-Layer-Row).
- **D8** (§5.45) — `CommandReason`-Enum-Length-30-DB-CHECK zwingt Detail-Differenzierung (Reason bleibt `WINDOW_OPEN`, Variante via `detail`-Prefix + `extras["setpoint_source"]`).
- **D11** — Pass-Through-Pfad in Layer 4 macht jetzt 2 Queries (Helper + Diagnostic). Akzeptabel, Optimierungs-Backlog in SPRINT-PLAN §Backlog.
- **D12** (§5.46) — Helper in eigenem `rules/window_state.py`-Modul, vermeidet zirk. Import zwischen `engine.py` und `services/override_service.py`.
- **D14** — Override-Reject filtert auf healthy-Devices (Symmetrie zu Layer 4). UX-Konsequenz: bei All-Unhealthy-Cluster geht Override durch trotz physisch offenem Fenster. In E2E-Test G verankert. Frontend-Hinweis kommt in Sprint 12a.
- **D15** — `purge_test_data_by_prefix` (T0-Helper) räumt Devices nicht auf — Orphan via FK `SET NULL`. Lokaler `_purge_orphan_devices`-Helper in `test_sprint12_e2e.py` ergänzt. Backlog: T0-Helper erweitern.
- **D16** — `TEST_DATABASE_URL` vs `DATABASE_URL`-Konvention im Bestand inkonsistent. Sprint-12-E2E pinnt `TEST_DATABASE_URL`. Konsolidierung als Hygiene-Backlog (§5.48).

**Nicht-Ziele eingehalten:**

- Engine-Decision-Iteration bleibt room-zentrisch (AE-54-Klarstellung aktualisiert) — zone-granular kommt erst mit pro-Zone-differenzierender Decision-Logik.
- Override-DB-Migration auf `zone_id` verschoben → Sprint 12a.
- Frontend Override-Panel pro Zone + Fenster-Vorpruefung verschoben → Sprint 12a.
- Handtuchtrockner-Spezial-Logik weiterhin nicht implementiert (US2 in Brief revidiert entfernt, D1-Befund aus T1).

**Querverweise:** AE-52 (Wortlaut-Praezisierung Sprint 12), AE-54-Klarstellung (Schreib-Pfad zonen-iteriert), AE-55 (JSONB-Sub-Trace-Pattern, D7), AE-56 (Window-State-Modul, D12), CLAUDE.md §5.42-§5.48 (7 neue Lessons aus Sprint 12).

---

## 2an. Sprint 12a Override-Zone-Scope + AE-58 Konsolidierung (Backend-only, 2026-05-20, abgeschlossen)

**Ziel:** Override-Modell konsolidieren auf strategie-konformen Zustand (AE-58). Zone-scoped Overrides (`manual_override.heating_zone_id`), OCCUPIED-Gate (Override nur fuer belegte Zimmer), AE-29 + AE-45 abgeloest, Mitarbeiter > Gast Prioritaet, Window-Open trumpft alle Quellen, Auto-Revoke bei Check-out fuer alle Quellen (`revoke_all_active_overrides` ersetzt `revoke_device_overrides`). Engine Layer 3 zone-aware via `RuleResult.zone_overrides` (Option G), Layer 4/5 + Dispatch mit Pass-Through.

**Tag:** `v0.1.17a-override-zone-scope-backend` (annotated, gesetzt 2026-05-20 auf Squash-Commit `0a6e5ae`).

**PR:** [#162](https://github.com/rexei123/heizung-sonnblick/pull/162) squash-merged 2026-05-20T12:26:04Z (Squash-Commit `0a6e5ae`).

**Branch:** `feat/sprint12a-override-zone-scope` (7 Commits T1-T7 ueber develop, nach Merge geloescht via `--delete-branch`; T0 Phase-0-Quellcheck ohne Commit).

**Commits:**

| Commit | Subject | Stat |
|--------|---------|------|
| `eabd7be` (T1) | feat(sprint12a): T1 migration 0016 manual_override.heating_zone_id | 2 files, +247 |
| `a352e8b` (T2) | feat(sprint12a): T2 override_service Zone-Scope + OCCUPIED-Gate + Priority-Sort | 7 files, +524/-54 |
| `f52c07f` (T3) | feat(sprint12a): T3 API Zone-Scope + 409 room_not_occupied + 404 invalid_zone | 4 files, +329/-11 |
| `aec8866` (T4) | feat(sprint12a): T4 device_adapter Zone-Scope + OCCUPIED/Window-Gates + Audit | 3 files, +368/-6 |
| `c8cf477` (T5) | feat(sprint12a): T5 Engine Layer 3 zone-aware (Option G) | 3 files, +470/-13 |
| `91e78d8` (T6) | test(sprint12a): T6 PMS-Hook Verifikation revoke_all_active_overrides | 1 file, +91 |
| T7 (dieser Commit) | docs(sprint12a): T7 AE-58 + AE-29/45/52/54-Marker + STRATEGIE + RUNBOOK + STATUS + SPRINT-PLAN + CLAUDE | mehrere Doku-Files |

**Total (T1-T6):** **+2029 insertions / -84 deletions**, +25 neue Tests netto (+27 neue, -2 entfernte obsolete `compute_expires_at`-Fallback-Tests). Test-Suite 388 → 413 (+25). Brief-Erwartung 10-14 h, Realdauer ~12-13 h ueber 7 Tasks.

**Kern-Liefergegenstaende:**

- Migration `0016_manual_override_zone_id.py` mit `heating_zone_id INTEGER NULL`, FK `ON DELETE SET NULL`, Partial Index `ix_manual_override_active_zone`.
- `models/manual_override.py`: `heating_zone_id: Mapped[int | None]`.
- `services/override_service.py`: `RoomNotOccupiedError` neu, `create()` mit OCCUPIED-Gate + Window-Gate + `heating_zone_id`-Param, `get_active()` Zone>Room + FRONTEND>DEVICE Priority-Sort, `compute_expires_at()` Fallback `now+7d` entfernt, `revoke_device_overrides` → `revoke_all_active_overrides` (kein source-Filter).
- `api/v1/overrides.py`: POST mit `heating_zone_id` Body-Param + FK-404-Check + 409 `room_not_occupied`, GET mit `zone_id` Query-Param + Zone>Room-Sort, AE-58 Sprint-12c-Anker-Kommentar fuer `room_blocked`-Slot.
- `services/device_adapter.py`: `_device_zone_id` Helper + `_write_blocked_event_log` Helper + Gate-Stack (OCCUPIED → Window → Zone-Lookup → create), silent skip + Audit fuer Vicki-Drehring in VACANT/Window.
- `services/override_pms_hook.py`: Aufruf auf `revoke_all_active_overrides` (T2-Vorgriff per Brief).
- `models/enums.py`: `EventLogLayer.MANUAL_OVERRIDE_BLOCKED`, `CommandReason.DEVICE_BLOCKED_VACANT` + `DEVICE_BLOCKED_WINDOW`.
- `rules/engine.py`: `RuleResult.zone_overrides: dict[int, int]`, `layer_manual_override` mit `heating_zone_id`-Param + `heating_zone_id`-Feld in extras, Zone-Eval-Schleife nach Layer 2 in `evaluate_room`, Layer 4 verwirft `zone_overrides` bei `WINDOW_OPEN`, Layer 5 clampt Zone-Werte, AE-55-Trace via `extras["zone_overrides_trace"]` in HARD_CLAMP-Row.
- `tasks/engine_tasks.py`: `_dispatch_downlinks_per_zone` mit `zone_overrides`-Param, pro Zone `target = zone_overrides.get(zone.id, default)`.
- `schemas/manual_override.py`: `ManualOverrideCreate` mit optionalem `heating_zone_id`, `ManualOverrideResponse` mit `heating_zone_id: int | None`.

**Brief-Drifts (vorab durch Strategie-Chat freigegeben):**

- **T1:** AE-29-Cleanup nicht im Bundle-DROP, separates B-12a-1 (Phase-0-Befund: aktive ORM-Relationships, DROP wuerde Room-Lazy-Load brechen).
- **T2:** Backward-Compat-Konflikt zwischen OCCUPIED-Gate und Bestandstests → Variante A (Fixture-Anpassung in test_api_overrides.py + test_engine_layer3.py + test_sprint12_e2e.py, ~30 Min Mechanik, keine Test-Assertion-Aenderung). 13 Bestandstests rot vor Fixture-Update, 0 nach Update.
- **T5:** Option G statt Option F. RuleResult-Erweiterung um `zone_overrides`-Dict, Engine-Decision-Iteration teilweise zone-aware (Layer 3), Layer 4/5/Dispatch Pass-Through. AE-54-Klarstellung in T7 revidiert.
- **T5 Fixture-Drift:** Engine Layer 1 liest `ctx.room.status`, T2-Fixtures setzen nur Occupancy → derive_room_status. Helper `_force_room_status_occupied` in 2 T5-Tests. B-12a-4 Backlog: Engine soll `derive_room_status` nutzen.
- **T7:** Doku-Run pflegt AE-58 + Markierungen + STRATEGIE + RUNBOOK + STATUS + SPRINT-PLAN + CLAUDE-Lessons.

**Tests-Bilanz:** 388 (Sprint-12-Stand vor 12a) → 413 (+25 netto = +27 neue T1-T6-Tests minus 2 entfernte obsolete `compute_expires_at`-Fallback-Tests). 1 xfailed unveraendert (Sprint-11-Bestand).

**Nicht-Ziele eingehalten:**

- Kein Frontend-Touch (Sprint 12b: Zone-Override-Panels, Window-Pre-Check, `room_blocked`-Slot-Stub).
- Kein `room.guest_override_blocked`-Feld (Sprint 12c).
- AE-29 `manual_setpoint_event`-Cleanup (DROP TABLE + Modell + Schema + Relationships) verschoben in B-12a-1.

**Querverweise:** AE-58 (Master-ADR fuer Override-Modell), AE-29 (abgeloest), AE-45 (abgeloest), AE-52 (Praezisierung Device-Pfad silent skip), AE-54-Klarstellung (Layer 3 zone-aware), CLAUDE.md §5.51-§5.53 (3 neue Lessons aus Sprint 12a).

### Live-Verify-Befund heizung-test (2026-05-20)

- Commit `0a6e5ae` auf Server (Auto-Pull-Timer hat gezogen).
- Migration `0016_manual_override_zone_id` angewendet, `alembic current` → `0016_manual_override_zone_id (head)`.
- `manual_override`-Schema verifiziert: `heating_zone_id integer NULL`, FK `fk_manual_override_heating_zone ON DELETE SET NULL`, Partial Index `ix_manual_override_active_zone (room_id, heating_zone_id, created_at DESC) WHERE revoked_at IS NULL`; Bestands-Constraints (`ck_manual_override_setpoint_range`, `ck_manual_override_source`) unveraendert.
- API gesund: Container-Stack Up. Override-Lifecycle End-to-End sauber durchgefuehrt — Raum 201 Frontend-Override anlegen (201 Created mit `heating_zone_id: null` Backward-Compat-Pfad), Revoke via DELETE.
- Engine-Tick laeuft sauber (MQTT-Uplinks persistiert, `evaluate_room` geschedult).
- Sommermodus auf heizung-test aktiv (Layer 0 Fast-Path → Layers 1-5 geskippt) — T3/T4 Zone-Override-Wirkung in Real-Hardware-Pfad strukturell nicht beobachtbar bis Heizperiode 2026/27. CI-Coverage 413 Tests ist die harte Verifikations-Anker (analog Sprint 12 STATUS §2am R3, Window-Detection).
- Keine Drifts beobachtet, keine 500/Stack-Trace im API-Container-Log.

---

## 2ap. Sprint 12b Frontend Zone-Override-Panels + Window-Pre-Check (Frontend-only, 2026-05-20, abgeschlossen)

**Ziel:** Frontend-UX an das Sprint-12a-Backend-Override-Modell (AE-58) anpassen — Pro-Zone-Override-Cards (statt einer Room-weiten Card), Window-Pre-Check vor POST (Engine-Trace als Datenquelle, kein neuer Backend-Endpoint), typisierter Error-Helper fuer 409/404/422-Differenzierung, Engine-Decision-Panel um `zone_overrides_trace`-Block + neue Layer/Reason-Werte (Sprint 12a T4) erweitert.

**Tag-Vorschlag:** `v0.1.17b-override-zone-scope-frontend` nach Merge.

**Branch:** `feature/sprint-12b-override-zone-scope-frontend`, 6 Commits T1-T6.

**Architektur-Entscheidungen aus Strategie-Chat-Brief (verbindlich):**

- **E1** Window-Pre-Check liest Engine-Trace (Pattern aus `engine-window-indicator.tsx`), KEIN neuer Backend-Endpoint. Bis-90s-Latenz akzeptiert; UI zeigt „Stand: vor Xs"-Hinweis.
- **E2** Pro-Zone-Card-Layout immer aktiv, auch bei N=1 Zone (ein UI-Pfad, Zone-Label sichtbar).
- **E3** room_blocked-UI-Stub NICHT sichtbar in 12b. Nur Code-Anker im Backend (api/v1/overrides.py-Sprint-12c-Marker aus T3).
- **E4** Backward-Compat-Room-Scope-Overrides (`heating_zone_id IS NULL`) als zusaetzliche Read-only-Card „Raum (alle Zonen)" am Listen-Anfang, nur wenn so ein Override aktiv ist.
- **E5** Engine-Decision-Panel-Erweiterung minimal-invasiv: nur LayerTrace-Block, kein SummaryCard-Block.
- **E6** Wording-Trennung strikt: „Zimmer gesperrt" = `RoomStatus.BLOCKED` (Bestand); „Übersteuerung gesperrt" = `guest_override_blocked` (Sprint 12c, NICHT in 12b verwendet).

**Tasks (umgesetzt):**

- **T1** Type + API-Layer-Sync (~1 h): `ManualOverride` + `ManualOverrideCreate` + `ManualOverrideListQuery` um `heating_zone_id` / `zone_id` erweitert; Hook-Keys mit Zone-Achse; neuer `useZoneOverride(roomId, zoneId)`-Convenience-Hook.
- **T2** Panel-Refactor (~3-4 h): Container `manual-override-panel-list.tsx` neu, `manual-override-panel.tsx` refactoriert zu Sub-Komponenten (`ManualOverrideZoneCard`, `ManualOverrideRoomCard`, `HistoryCard` mit Bereich-Spalte), Window-Pre-Check via `useEngineTrace` + `extractWindowState`-Helper, `app/zimmer/[id]/page.tsx` auf neue Container-Komponente umgestellt. Material-Symbols statt Emoji durchgehend.
- **T3** Error-Toast-Differenzierung (~30 min): typisierter `mapOverrideError`-Helper in `lib/api/override-errors.ts` mappt 409 `room_not_occupied`, 409 `override_rejected_window_open`, 404 `invalid_zone`, 422 (Setpoint-Half-Step / FRONTEND_CHECKOUT-ohne-Belegung / ValueError) auf deutsche User-Texte ohne ID-Leak.
- **T4** Engine-Decision-Panel-Erweiterung (~1 h): `EventLogLayer`-Union um `manual_override_blocked`; `CommandReason`-Union um `device_blocked_vacant` + `device_blocked_window`; LAYER_ORDER + LAYER_LABEL + REASON_LABEL um neue Werte; `LayerTrace` rendert `ZoneOverridesBlock` unter der Tabelle wenn HARD_CLAMP-`details.zone_overrides_trace` Zone-Match-Records enthaelt (Zonen-Namen via `useHeatingZones`-Lookup).
- **T5** Playwright E2E (~1-2 h): `tests/e2e/manual-override-zone.spec.ts` mit 5 Cases (Happy, Window-Blocked, Room-not-occupied, Invalid-Zone, Engine-Panel-Pro-Zone), alle gruen lokal.
- **T6** Doku (dieser Commit): STATUS §1 + §2ap + §9, SPRINT-PLAN.md Sprint-12b abgeschlossen-Block, CLAUDE.md §5.54 (Playwright route() glob vs. regex bei URLs mit Query-String — Sprint-12b-Footgun).

**Diff-Stats (T1-T5 vor T6-Commit):** ~6 Files src/, 1 File tests/, +~900 LoC netto (Container neu, Panel refactoriert, Helper neu, types.ts erweitert, Engine-Decision-Panel erweitert, E2E-Spec neu). 5 neue Playwright-Cases.

**Toolchain:** TypeScript strict gruen, ESLint gruen, Playwright 5/5 gruen lokal. Backend-Tests unveraendert (kein Backend-Code-Touch): 413 passed, 1 xfailed.

**Brief-Risiken — Status:**

- **R1** Engine-Trace-90s-Latenz: UI rendert „Stand: vor Xs"-Hinweis transparent unter dem Disabled-Button (E1-Akzeptanz, dokumentiert in CLAUDE.md §5.54 nicht — stattdessen als bewusste UX-Entscheidung im Brief).
- **R2** Backward-Compat-Room-Card moeglicherweise nie sichtbar in Praxis: Code bleibt als Sicherheits-Netz drin. Akzeptiert.
- **R3** Zone-Label-Anzeige bei N=1 Zone: einheitlicher Pfad, kein Sonderfall. Akzeptiert.
- **R4** Type-Update-Konsumenten-Check via grep vor T2: nur `lib/api/types.ts`, `lib/api/overrides.ts`, `lib/api/hooks-overrides.ts`, `components/patterns/manual-override-panel.tsx` — keine versteckten Konsumenten. T2 ohne Stopp durchgefuehrt.

**Nicht-Ziele eingehalten:**

- Kein Backend-Code-Touch (`backend/src/` unveraendert in Sprint 12b).
- Kein `room.guest_override_blocked`-Stub im Frontend (E3, Sprint 12c).
- Kein neuer Backend-Endpoint fuer Window-State (E1, Engine-Trace ausreichend).

### Live-Verify auf heizung-test (2026-05-20 18:15 CEST)

Squash-Commit `3587b47` auf Server, Auto-Pull-Deploy via `deploy-pull.sh` erfolgreich (api healthy, web healthy nach 60s, celery_beat unhealthy pre-existing aus 12a-Stand, kein 12b-Bezug).

Sicht-Verify Cowork (Raum 201 / DB-ID 16, 2 Zonen; Raum 202 / DB-ID 17, 1 Zone):

- **A** Raum 201 Override-Tab: 2 Cards „Schlafbereich" (Symbol `bed`) + „Bad" (Symbol `shower`), Historie-Card mit 1 aufgehobenem Eintrag, keine aktive „Raum (alle Zonen)"-Card (kein Altbestand).
- **B** Raum 202 Override-Tab: 1 Card „Schlafbereich", Zone-Label auch bei N=1 Zone sichtbar (E2 verifiziert).
- **C** Window-Pre-Check: alle 3 Cards Anwenden-Button aktiv, kein Window-Open-Hinweis (Sommermodus aktiv).
- **D** Raum 201 Engine-Tab: Layer „Sommermodus" (`summer_mode_active=true`) → „Sicherheits-Limit" (`within [10,30]`), 10 °C. Kein „Übersteuerung blockiert"-Layer, kein `ZoneOverridesBlock` (erwartet bei Sommer-Fast-Path, kein Fehler).
- **E** Console: keine App-Errors/Warnings, nur ignorierter Chrome-Extension-Noise.
- **F** Network: 3 GETs (`heating-zones`, `engine-trace?limit=50`, `overrides?include_expired=true`), alle 200; URLs nutzen DB-ID 16, nicht Zimmer-Nummer 201.

Sommermodus-bedingt nicht real beobachtbar (durch 47 CI-Tests abgesichert):

- Window-Pre-Check Disabled-State bei realem offenem Fenster
- Engine-Decision-Panel `ZoneOverridesBlock` bei aktivem Zone-Override
- 409 `override_rejected_window_open` Toast-Differenzierung

Real-Hardware-Verifikation kommt automatisch in Heizperiode 2026/27 (analog Sprint 12 STATUS §2am R3).

Tag `v0.1.17b-override-zone-scope-frontend` annotated auf `3587b47` gesetzt und gepusht.

**Querverweise:** AE-58 (Master-ADR Sprint 12a), AE-52-Praezisierung (Window-Open trumpft alles), AE-54-Klarstellung (Engine Layer 3 zone-aware), Sprint-12a STATUS §2an, Sprint-12-T5 zone_overrides_trace-Pattern (AE-55), CLAUDE.md §5.54 (Playwright route()-Footgun), CLAUDE.md §5.55 (Skip-Spiegel-Workflow-Pattern verfaelscht gh pr checks).

---

## 2aq. Sprint 12c Room Override Block (Voll-Sprint, 2026-05-20, abgeschlossen)

**Ziel:** Uebersteuerungs-Sperre pro Zimmer (`room.guest_override_blocked`) als Mitarbeiter-Toggle. Single-Source-of-Truth im `override_service.create`, Device-Adapter spiegelt das Gate vor dem OCCUPIED-Check. Toggle-On revoked alle aktiven Overrides des Raums (source-agnostic) mit `revoked_reason="room_override_blocked"`, BusinessAudit-Action `ROOM_OVERRIDE_BLOCK_TOGGLED` mit Revoked-Count. Engine bleibt unangetastet (kein neuer Layer).

**Tag-Vorschlag:** `v0.1.17c-room-override-blocked` nach Merge.

**Branch:** `feat/sprint12c-room-override-blocked`, T1-T9 abgeschlossen.

**Brief-Vor-Entscheidungen (verbindlich):**

- Block-Gate liegt im `override_service.create()` als Single-Source-of-Truth. Device-Adapter prueft zusaetzlich vorab + schreibt EventLog beim Skip.
- Gate-Reihenfolge im Adapter: BLOCKED → OCCUPIED → Window → Zone → Create.
- Auto-Revoke bei Toggle-On: `override_service.revoke_all_active_overrides(reason="room_override_blocked")`, source-agnostic (DEVICE + FRONTEND_*).
- Audit pro Toggle: 1 BusinessAudit-Eintrag mit `new_value.revoked_overrides_count`. Override-IDs NICHT im Audit — rekonstruierbar via `revoked_reason`-Filter.
- Engine bleibt unangetastet (kein neuer Layer, kein Layer-3-Filter).
- `auto_revoke_on_checkout`-Audit-Luecke nicht in 12c saniert (Backlog).

**Tasks (umgesetzt):**

- **T1** Migration + Model + Schema (~1 h): `0017_room_guest_override_blocked.py` (add_column NOT NULL server_default=false, dann alter_column server_default=None — Default lebt im ORM-Modell), `models/room.py` Boolean-Mapped-Column, `schemas/room.py` `RoomRead.guest_override_blocked` + neue Klasse `RoomOverrideBlockUpdate(blocked: bool, extra="forbid")`. Alembic-Roundtrip 0016↔0017 gegen heizung-test-db lokal verifiziert (§5.50).
- **T2** Service-Layer Block-Check (~30 min): `RoomOverrideBlockedError(room_id)` neue Exception, Block-Gate in `override_service.create()` VOR OCCUPIED-Check eingehaengt. Docstring + Raises aktualisiert.
- **T3** API PATCH-Endpoint + Audit + Marker-Cleanup (~1 h): `PATCH /rooms/{id}/override-block-state` mit `require_mitarbeiter`-Auth, Idempotenz-Pfad (old==new -> kein Audit), Auto-Revoke bei Toggle-On, BusinessAudit-Schreibung in derselben Transaktion. `api/v1/overrides.py` neuer 409-Handler fuer `RoomOverrideBlockedError` VOR `RoomNotOccupiedError`-Handler. Sprint-12c-Markerkommentar (overrides.py:201) entfernt.
- **T4** Device-Adapter Block-Gate + CommandReason (~30 min): `CommandReason.DEVICE_BLOCKED_ROOM_BLOCKED` neu (27 chars, paßt in VARCHAR(30) §5.45), Pre-A-Gate in `handle_uplink_for_override` schreibt off-pipeline EventLog (§5.52-Pattern). Docstring + Gate-Numerierung (pre-a/a/b/c/d) aktualisiert.
- **T5** Backend-Tests (~2 h, Pflicht-Stop nach Lauf): 3 Service-Tests (`test_override_service.py` inkl. §5.51-Domain-Invariante-Docstring), 5 API-Tests in neuer Datei `test_api_rooms.py` (Toggle-On revokes + Audit, Toggle-Off no-op, Idempotenz, `require_mitarbeiter`-Dependency-Wiring via `app.dependency_overrides`, 404), 2 API-Tests in `test_api_overrides.py` (409 `room_override_blocked` + Block-Praezedenz vor `room_not_occupied`), 3 Adapter-Tests in `test_device_adapter.py` (DEVICE_BLOCKED_ROOM_BLOCKED, Praezedenz vor VACANT, Praezedenz vor Window). §5.49-Fixture-Anpassungen: 4 von 6 Raw-SQL-Room-INSERTs (2 in test_manual_override_model.py + 2 in test_migrations_roundtrip.py am HEAD) um `guest_override_blocked, false` erweitert; 2 INSERTs unangetastet (downgrade-Pfade vor 0017). Voller Lauf: 426 passed, 1 xfailed, 0 failed, 0 errors.
- **T6** Frontend Type + Hook + Toggle-Komponente (~1 h): `Room.guest_override_blocked: boolean` + `RoomOverrideBlockUpdate`-Type, `roomsApi.patchOverrideBlockState`, `useSetRoomOverrideBlockState`-Hook mit Cache-Invalidation (Room + Overrides), neue Komponente `RoomOverrideBlockToggle` mit Lock/Lock-Open-Symbol, Confirm-Dialog nur wenn `activeOverridesCount > 0`, inline Toast-Feedback. Integration in `app/zimmer/[id]/page.tsx` Header.
- **T7** PanelList-Banner + Engine-Decision-Label (~30 min): `manual-override-panel-list.tsx` liest `useRoom` (Cache-Hit), rendert Sperr-Banner + propagiert `overrideBlocked` an Zone-/Room-Cards. Zone-Card mit `overrideBlocked` blendet CreateForm aus, Active-Display read-only. Engine-Decision-Panel `REASON_LABEL.device_blocked_room_blocked` ergaenzt. TypeScript exhaustive `CommandReason`-Union erweitert.
- **T8** Playwright-E2E (~1 h): 4 Cases in `tests/e2e/sprint12c-room-override-blocked.spec.ts` (§5.54-konform RegExp + `(\?.*)?$`): Confirm-Dialog bei aktiven Overrides, Toggle-On hide Create-Form, blocked-Banner sichtbar, Toggle-Off restore Create-Form. Voller E2E-Lauf 51/51 gruen.
- **T9** Doku (dieser Commit): STATUS §2aq + §9, SPRINT-PLAN, AE-58-Ergaenzung Sprint-12c-Slot.

**Diff-Stats:** Backend +1 Migration, +1 Test-Datei (`test_api_rooms.py`), 8 Source-Dateien geaendert. Frontend +1 Component, +1 E2E-Spec, 7 Source-Dateien geaendert.

**Toolchain:** ruff format + ruff check + mypy strict + pytest -x (426 passed) auf Backend; tsc + eslint + next build + Playwright (51 passed) auf Frontend. Migration-Roundtrip 0016↔0017 lokal verifiziert (§5.50).

**Brief-Risiken — Status:**

- **R-§5.49** Raw-SQL-Test-Fixtures: nachgeholt in 2 Test-Files, 4 INSERTs aktualisiert, 2 INSERTs (downgrade-Pfade) bewusst unveraendert mit Hinweis-Kommentar. Modul-Docstrings ergaenzt.
- **R-§5.47** Helper-Extraktion verhaltensneutral: Block-Gate ist neuer Gate VOR bestehenden Gates, kein Refactor bestehender Logik.
- **R-Auth-Test** `require_mitarbeiter`-403 nicht real testbar unter `AUTH_ENABLED=false` (System-Admin-Fallback). Test ueber `app.dependency_overrides[require_mitarbeiter]` validiert Dependency-Wiring.

**Out of Scope (Backlog):**

- B-12c-AuditGap: `auto_revoke_on_checkout` schreibt weiterhin kein Audit (Sprint-12c-Scope-Verzicht laut Brief). ✅ erledigt 2026-05-22 im Hygiene-Sprint T2 (Commit `3934d33`).
- B-12c-1: Vicki-Hardware-Child-Lock via Downlink `0x07` (separater Sprint).
- Zimmer-Liste-Indikator (Schloss-Symbol in Tabelle).
- AE-57-Luecken-Klaerung (Doku-Hygiene-Backlog). ✅ vergeben 2026-05-21 im Hygiene-Sprint T1 (Commits `9e17455` + `4ace2a9`).

### Live-Verify auf heizung-test (2026-05-20 18:10 CEST)

- Squash-Commit `e9b18af` via `deploy-pull.service` deployt (HEAD-Sync 18:08:03 + Restart 18:10:07).
- Alle relevanten Container healthy nach Restart (api/web/celery_worker healthy, celery_beat unhealthy per §5.32 akzeptiert, db/redis/caddy/mosquitto/chirpstack-* healthy).
- Migration 0017 auf head bestaetigt: `docker exec deploy-api-1 alembic current` → `0017_room_guest_override_blocked (head)`.
- `/health` → 200 mit JSON ok.

Cowork-Sicht-Verify (Hotelier-gefuehrt):

- **Block 1** (Toggle-Sichtbarkeit): bestaetigt — Header-Button „Uebersteuerung sperren", Symbol `lock_open`.
- **Block 2** (Toggle OFF→ON ohne aktive Overrides): bestaetigt — kein Confirm-Dialog, Symbol `lock`, Banner „Uebersteuerung gesperrt" in beiden Zonen-Cards, Create-Forms ausgeblendet. `PATCH /rooms/16/override-block-state` → 200. Roundtrip Toggle ON→OFF ebenfalls 200.
- **Block 3** (Wording-Trennung): bestaetigt — Raum 101 manuell auf `RoomStatus.BLOCKED` gesetzt, Status-Pill „Gesperrt" rot in Liste, Stammdaten-Dropdown „Gesperrt". Override-Toggle weiterhin separat sichtbar mit Wording „Uebersteuerung sperren", keine Vermischung mit RoomStatus-Begriff. §5.20-Drift-Risiko entschaerft.
- **Block 4** (Engine-Decision-Panel REASON_LABEL `device_blocked_room_blocked`): in Sommer-Sicht nicht beobachtbar (Brief-konform), Real-Hardware-Verify in Heizperiode 2026/27 nachgezogen.

**Befund Wording-Inkonsistenz:** Header-Button-Strings waren ASCII („Uebersteuerung"), Tab/Panel mit Umlaut („Übersteuerung"). UI-Strings unterliegen NICHT der CLAUDE-ae/ue/oe-Regel (gilt nur fuer Code + Commits). Hotfix in selbem Doku-Nachzug-PR umgesetzt (Toggle-Button + Banner-Text + Confirm-Dialog + Engine-Decision-Panel-REASON_LABEL + Playwright-Assertions). Folge-Anpassung in `manual-override-zone.spec.ts`: 4 Tab-Locator auf `{ name: "Übersteuerung", exact: true }`, weil der Toggle-Button nach Wording-Fix Substring-Kollision mit dem Tab erzeugte (§5.47-Spirit, verhaltensneutrale Konsumenten-Anpassung).

**Folge-Sprint:** 12c.a (Zimmer-Liste-Indikator) ist Frontend-only-Mini-Sprint, Phase-0 abgeschlossen, Implementierungs-Brief liegt vor. Tag `v0.1.17d-room-block-list-indicator` nach Merge.

**Querverweise:** AE-58 (Master-ADR + Sprint-12c-Ergaenzung), §5.20 (Doku-Drift), §5.47 (verhaltensneutrale Konsumenten-Anpassung in Tests), §5.51 (Domain-Invariante in Tests verankert), §5.52 (Off-Pipeline-Audit-Pattern fuer Pre-A-Gate-EventLog), §5.54 (RegExp-Routes in E2E), §5.55 (CI-Verify via `gh run list` statt `gh pr checks`).

---

## 2ar. Sprint 12c.a Zimmer-Liste-Block-Indikator (Frontend-only, 2026-05-20, abgeschlossen)

**Ziel:** Schloss-Symbol in Zimmer-Uebersicht-Tabelle bei `room.guest_override_blocked === true`. Backend bereits seit Sprint 12c (PR #166) liefernd, keine Backend-Aenderung noetig.

**Tag-Vorschlag:** `v0.1.17d-room-block-list-indicator` nach Merge.

**Branch:** `feat/sprint12ca-room-block-list-indicator`, 3 Commits T1-T3 (Basis develop @ `78e24a6`).

**Tasks:**

- **T1** (~30 min): `frontend/src/app/zimmer/page.tsx` RoomTable um Block-Indikator-Spalte erweitert. Header leer (Symbol traegt Semantik via aria-label + title), Direkt-Span-Pattern aus app-shell/empty-state (kein Button-Wrapper, da nicht klickbar). Material-Symbol `lock` wenn `guest_override_blocked === true`, sonst leere Zelle. Wording „Übersteuerung gesperrt" (Umlaut, Endkunden-sichtbar, NICHT CLAUDE-ae/ue/oe-Regel).
- **T2** (~30 min): `frontend/tests/e2e/sprint12ca-room-block-list-indicator.spec.ts` neu, 2 Cases (§5.54 RegExp-Routes): (A) Mock 101 blocked + 102 nicht → genau 1 Symbol in Zeile 101, kein Symbol in 102, korrekter `title`/`aria-label`/Text „lock"; (B) alle Zimmer unblocked → kein Symbol in keiner Zeile.
- **T3** (Doku): STATUS §1 + §2ar + §9, SPRINT-PLAN-Block-Update. AE-58 nicht touchiert (kein Architektur-Bezug). CLAUDE.md nicht touchiert (keine neue Lesson).

**Wording-Trennung (§5.20 entschaerft in 12c live verifiziert):** „Übersteuerung gesperrt" (12c/12c.a) ≠ „Zimmer gesperrt" (`RoomStatus.BLOCKED`). Indikator-Spalte ist getrennt von der Status-Pill (kein Merge in `STATUS_COLOR`-Map).

**Toolchain:** `tsc --noEmit` + ESLint + `next build` + Playwright (53 passed: 51 Bestand + 2 neu) lokal gruen.

**Out of Scope (Backlog):**

- Tooltip-Komponente in `components/ui/` extrahieren
- Status-Pill-Komponente extrahieren
- Filter „Nur gesperrte"
- Lock-Symbol im Zimmer-Detail-Header (Doppelung mit Toggle-Button)

### Live-Verify auf heizung-test (2026-05-21 07:24 CEST)

- Squash-Commit `81ed3dc` via `deploy-pull.service` deployt (Sync 07:23:45 + Restart 07:26:17).
- Alle relevanten Container healthy nach Restart (api/web/celery_worker healthy, celery_beat unhealthy per §5.32 akzeptiert).
- `/health` → 200 mit JSON ok.
- Sicht-Verify Hotelier (Raum 101 manuell auf `guest_override_blocked=true` gesetzt): Schloss-Symbol in der neuen Spalte sichtbar in Zimmer-Uebersicht. Tooltip erscheint beim Hover („Übersteuerung gesperrt"). Wording-Trennung zu `RoomStatus.BLOCKED` bleibt scharf.

**Befund Header-Drift:** Erste Live-Sicht zeigte fehlenden Spalten-Header (Brief-Entscheidung „Header leer, Tooltip traegt Semantik"). Realer Nutzer-Befund: ohne Header ist die Spalte semantisch blind, weil Tooltip nur beim Hover greift. Hotfix in selbem Doku-Nachzug-PR (T1): Header-Text „Übersteuerung" ergaenzt, `aria-hidden` entfernt. UI-Strings mit Umlaut (Endkunden-sichtbar, NICHT CLAUDE-ae/ue/oe-Regel).

**Querverweise:** Sprint 12c (PR #166, AE-58, Tag `v0.1.17c`), §5.20 (Doku-Drift/Wording-Trennung), §5.54 (RegExp-Routes), §5.55 (CI-Verify Real-Run).

---

## 2as. Hygiene-Mini-Sprint vor Sprint 13 (2026-05-21/22, abgeschlossen)

**Ziel:** Drei Backlog-Altlasten + Test-Infrastruktur-Flake schliessen, bevor Sprint 13a-Brief geschrieben wird. Stufe 3 + ein Stufe-2-Block (freezegun-Patch). Kein Tag.

**Branch:** `chore/sprint13-hygiene`, 7 Commits auf develop @ `bb267ec`.

**Tasks erledigt:**

- **T1 (~45 min, 2 Commits `9e17455` + `4ace2a9`):** AE-57 vergeben — „Device-Lifecycle: Retire + Pair-New, Zone als stabiler Historie-Anker". Schliesst die ADR-Nummer-Luecke zwischen AE-56 und AE-58. Entscheidung (1) mit Partial-Unique-Index `WHERE retired_at IS NULL` (DevEUI-Wiederverwendung nach Werksreset erlaubt, Performance-Index-Variante verworfen mit S6-Begruendung). Entscheidung (2) mit `is_active`-Uebergangs-Klausel bis Sprint-13b-Merge. AE-43 + AE-58 Querverweise nachgezogen.
- **T2 (~45 min, Commit `3934d33`):** B-12c-AuditGap geschlossen. `auto_revoke_on_checkout` in `services/override_pms_hook.py` schreibt jetzt `OVERRIDES_AUTO_REVOKED_ON_CHECKOUT`-BusinessAudit in derselben Transaktion wie der Revoke. Idempotenz-Pfad unveraendert. Neue Konstante `REVOKE_REASON_CHECKOUT="auto_revoke_on_checkout"` als Single-Source-of-Truth fuer `revoked_reason` und `new_value.reason`. 3 neue Tests, 3 bestehende Assertions aktualisiert.
- **T3 (~1 h, 2 Commits `2663a7e` + `e970edb`):** B-12a-1 manual_setpoint_event-Cleanup. AE-29 abgeloest durch AE-58 (Sprint 12a), tote Tabelle + Modell + Schema + Relationships + `ManualOverrideScope`-Enum entfernt. Migration 0019 mit 1:1-Roundtrip-Reproduktion aus 0003a, lokal gegen heizung-test-db verifiziert (upgrade → downgrade → upgrade). AE-29-Status-Header mit Commit-Hash-Backfill in eigenem Doku-Commit.
- **T3.5 (~30 min, Commit `d2d5311`):** B-FlakyTime-1 — freezegun-Decorator auf 2 Layer-1-Pipeline-Tests (`test_engine_zone_override_wirkt_nur_auf_zone`, `test_layer4_closed_occupied_passthrough`). Beide asserten Layer-1-Output ohne Layer-2-Setback-Maskierung und failten zwischen 00:00-06:00 UTC reproduzierbar. `freezegun>=1.5` als Dev-Dep. Kein prophylaktischer Patch auf andere 32 `evaluate_room`-Tests (YAGNI). Aufgedeckt waehrend T3-pytest-Lauf um 05:01 UTC.
- **T4 (~15 min, Commit `9a949f8`):** CLAUDE.md §5.58 Lesson „Device-Queries brauchen Lifecycle-Filter" als Pflicht-Pattern fuer Sprint 13b. Uebergangs-Klausel + Zielzustand + Anti-Pattern + Pflicht-Stellen-Liste aus Phase-0 §L.

**Backend-Tests:** 428 passed, 1 xfailed (Baseline 426 +3 −1 fuer geloeschten `manual_setpoint_event`-Test).

**Diff-Summe:** 14 files geaendert, +~280 / −240, 1 neue Migration, 2 geloeschte Files, 1 neue Dev-Dependency.

**Out of Scope (Sprint 13b):** Migration 0018 (Device-Lifecycle-Felder + `is_active`-Drop), Helper `get_active_devices_for_zone()`, Umstellung der 5 Pflicht-Filter-Stellen.

**Neue Backlog-Punkte (in §6.2 unten erfasst):**

- **B-HygieneFollowup-1:** `override_service` vs. `override_pms_hook` Modul-Grenzen-Audit nach Sprint 13b. 🟢
- **B-HygieneFollowup-2:** Default-Reason-Param in `revoke_all_active_overrides` pruefen ob noch Aufrufer existieren nach Sprint 13b. 🟢
- **B-FlakyTime-1:** abgeschlossen in diesem Sprint, hier nur als Verweis. ✅

**Querverweise:** AE-29 (historisch), AE-57 (neu vergeben), AE-58, Phase-0-Bericht `docs/features/2026-05-21-sprint13-phase0-quellcheck.md`, CLAUDE.md §5.58.

---

## 2at. Sprint 13a Pre-Pairing-Skript (2026-05-22/23, abgeschlossen)

**Ziel:** Backend-CLI fuer das Einmal-Pairing aller 110 Vickis im
September 2026 (105 verbaut + 5 Reserve-Pool). Kein Wizard, kein
Frontend — fokussiertes Mitarbeiter-Werkzeug am Office-Laptop.

**Branch:** `feat/sprint13a-pre-pairing-skript`, 8 Commits auf develop @ `8f3554b` (PR-Erstellung steht in T9.9 aus).

**Tag (geplant nach Merge):** `v0.1.18a-pre-pairing-skript`

**Tasks erledigt:**

- **T1 (~15 min, Commit `d4f7681`):** Master-Inventar-Format-Doku als
  `docs/inventar/README.md`. XLSX-Datei selbst NICHT im Repo (S4/S5 —
  Office-Dateien sind `.gitignore`-blockiert wegen AppKey-Hijack-
  Risiko). Hotelier pflegt XLSX am Office-Laptop, Repo dokumentiert
  nur das Format. 45 Zimmer / 105 verbaute + 5 Reserve-Geraete.
- **T2 (~30 min, Commit `e46cb8e`):** `PairingCsvRow` Pydantic-Modell
  mit Pool-Konsistenz-Validator. `is_pool_device` als
  `computed_field`.
- **T3 (~1 h, Commit `2818eac`):** CSV-Parser mit `utf-8-sig` +
  Sniffer-Auto-Detect, `validate_against_db`,
  `check_dev_eui_duplicates`.
- **T4 (~1.5 h, Commit `ade2c07`):** Pairing-Service mit Gate-Stack
  (Existenz-Check -> Zone-Lookup -> Device-Row -> Audit -> Downlink),
  Pro-Row-Savepoint-Isolation, `DEVICE_PAIRED`-Audit.
- **T5 (~1 h, Commit `066c860`):** Eingangstest-Modul mit RUNBOOK-
  §10h.1-konformen 6 Schritten (inkl. non-blocking Schritt 0 als
  OW-Re-Send).
- **T6 (~45 min, Commit `cb657e0`):** CLI-Entrypoint mit 4
  Subcommands (`validate` / `import` / `test` / `list-pool`).
  `test`-Subcommand mit Auto-Detect `device.id` ODER `dev_eui`.
- **T7 (Commit `cc27388`):** RUNBOOK §10h.2 Pre-Pairing-Skript-
  Anwendung (Workflow A-F + Reserve-Pool + Stoerungsfaelle).
- **T9 (dieser Doku-Commit):** STATUS §2at + STATUS §1 + STATUS §6.2
  Backlog + SPRINT-PLAN Sprint-13-Cut.

**Backend-Tests:** 240 passed, 239 skipped (DB-Tests, kein
`TEST_DATABASE_URL` lokal — CI deckt sie ab). 48 neue Test-Cases in
5 neuen Test-Files (`test_pair_devices_cli.py`,
`test_pairing_csv_parser.py`, `test_pairing_csv_row.py`,
`test_pairing_inbound_test.py`, `test_pairing_service.py`).

**Diff-Summe (T2-T7):** 14 files geaendert, +3336 / −4. 8 neue
Backend-Files (`heizung.scripts/__init__.py`, `pair_devices.py`, plus
6 Files unter `heizung.scripts.pairing/`), 5 neue Test-Files,
RUNBOOK §10h.2 ergaenzt.

**T8 Live-Verify (2026-05-23):** Dry-Run + echter Lauf gegen lokale
heizung-test-DB (Container `heizung-test-db`, RUNBOOK §10i) mit
unreachable MQTT-Host (`MQTT_HOST=localhost`, `MQTT_PORT=1`). Drei
Pool-Devices durchlaufen Pairing-Pfad sauber: validate Exit 0,
dry-run [FAIL]-DOWNLINK_FAILED mit Rollback (DB-Count 0 nach Lauf),
echter Lauf [FAIL]-DOWNLINK_FAILED ohne Rollback (3 Device-Rows + 3
`DEVICE_PAIRED`-Audit-Rows persistent in DB, `list-pool` zeigt die 3
Devices). T4-Design bestaetigt: `status=error` rollt Device-Row +
Audit NICHT zurueck.

**Out of Scope (Sprint 13b):**

- Tausch-Endpoint + Frontend-Dialog
- Migration 0018 (`retired_at` + `is_active`-Drop)
- Helper `get_active_devices_for_zone()`
- Umstellung der 5 Pflicht-Filter-Stellen (Phase-0 §L)

**Out of Scope (Sprint 17):**

- Live-Lauf gegen heizung-main im September
- Echte Eingangstest-Saekula mit 110 Vickis
- ChirpStack-Bulk-Import durch Hotelier (manuell vor September)

**Neue Backlog-Punkte (in §6.2 unten erfasst):**

- **B-Sprint13a-1** 🟢: `activate_open_window_detection.py` von
  `backend/scripts/` ins neue Sub-Package `heizung.scripts/`
  migrieren (Konsistenz, nicht-dringend).
- **B-Sprint13a-2** 🟢: Pydantic-Feld `zimmer_nummer` von
  `int | None` auf `str | None` aendern (entspricht DB-`VARCHAR(20)`,
  erlaubt Zimmer wie `"DG"`). Vor Sprint 17 klaeren.
- **B-Sprint13a-3** 🟢: Test-Case fuer Float-String-Coercion in CSV
  (`"52.0"` -> 52).
- **B-Sprint13a-4** ✅ erledigt T7: RUNBOOK-Hinweis zu `app_key` als
  Cross-Reference-Only dokumentiert.
- **B-Sprint13a-5** 🟡: Migration 0018 in Sprint 13b fuehrt
  `pairing_status`-Feld ein (Default `active`), um Variante-B fuer
  Downlink-Failure-Recovery nachzureichen.
- **B-Sprint13a-6** ✅ erledigt 2026-05-24 (Sprint 13b.2): Frontend-
  Sicht der Pool/Aktiv-Devices ist via T6 Reserve-Badge in der
  `/devices`-Liste plus T8 Playwright-Coverage gegeben. Kein
  separater `list-all`-Subcommand mehr noetig.
- **B-Sprint13a-7** 🟢: RUNBOOK §10h.2 Stoerungsfall-Eintrag fuer
  `resend_open_window-failed`: explizite Anleitung was der Hotelier
  tun soll (manuell re-senden oder ignorieren weil naechster
  Eingangstest erneut sendet).
- **B-Sprint13a-8** ✅ erledigt 2026-05-24 (Sprint 13b.2 T7,
  Commit `bad4a26`): Resultat-Output erweitert um DOWNLINK_FAILED-
  Disambiguation in Klammer ("X errors (Y mit Device-Row in DB,
  OW-Downlink fehlgeschlagen)"); Mixed-Case + Reine-Pairing-Fails-
  Case differenziert.
- **B-Sprint13a-9** ✅ erledigt 2026-05-24 (Sprint 13b.2 T7,
  Commit `bad4a26`): Dry-Run-Schluss-Message auf
  "ChirpStack-Downlinks wurden versucht (Ergebnisse siehe oben)"
  umgestellt.
- **B-Sprint13a-10** 🟢: Falls in Sprint 16/17 sich herausstellt,
  dass das Master-Inventar verbindlich versionierbar sein muss
  (z.B. fuer Bootstrap-Reproduzierbarkeit): Format auf Pure-CSV
  oder Markdown-Tabelle umstellen (keine Secrets-Vektoren), dann
  ist `.gitignore`-Ausnahme vertretbar.

**Querverweise:** AE-32, AE-48, AE-57, AE-58, RUNBOOK §10h.1 +
§10h.2, STATUS §2as, `docs/inventar/README.md`.

---

## 2au. Sprint 13b.1 Backend Device-Lifecycle + Pool-Reassign-Tausch (2026-05-23, abgeschlossen inkl. Live-Verify)

**Ziel:** Implementation der AE-57-Architektur im Backend: Migration
0018 (`retired_at`/`retired_reason`/`replaced_by_device_id` +
Partial-Unique-Index + `is_active`-Drop), Service-Layer fuer
atomaren Pool-Reassign-Tausch + Stilllegung, API-Endpoints fuer
Frontend (Sprint 13b.2). Race-Schutz via UPDATE-WHERE-Clause in der
Pool-Reservierung (READ-COMMITTED-tauglich).

**Branch:** `feature/sprint-13b1-device-lifecycle`, 7 Commits auf
develop @ `1275511` (PR-Erstellung steht in T8b aus).

**Tag (geplant nach Merge):** `v0.1.18b1-device-replacement-backend`

**Tasks erledigt:**

- **T1 (Commit `6d244b8`):** Migration `0018_device_lifecycle.py` —
  3 nullable Spalten + selbst-referenzielle FK + Partial-Unique-Index
  `ix_device_dev_eui_active_unique WHERE retired_at IS NULL` +
  `is_active`-Drop. 3 Roundtrip-Tests (atomar_auf_ab_auf,
  downgrade_backfills_is_active, partial_unique_allows_retired_
  duplicates). §5.56-Test-Fix `test_migration_0015_check_constraint_
  rejects_invalid` (is_active aus INSERT entfernt).
- **T2 (Commit `16711bc`):** `models/device.py` + `schemas/device.py`
  auf Lifecycle-Felder umgestellt. 5 Test-Fixtures (`is_active=True`
  aus `Device(...)` entfernt: layer3, api_overrides, multivicki,
  override_service, sprint12_e2e). `noqa A003` auf
  `remote_side=[id]` (SQLAlchemy-Standard).
- **T3 (Commit `d699447`):** Neue Datei
  `services/device_service.py` mit `get_active_devices_for_zone` +
  `get_pool_devices`. 6 Tests in
  `tests/services/test_device_service.py`.
- **T4 (Commit `ed9712b`):** §L-Umstellung 6 Stellen — T4.1
  `_get_zone_devices` via Helper + Health-Filter; T4.2/T4.3/T4.4
  inline `retired_at IS NULL` (JOIN-basiert, Helper-Signatur passt
  nicht); T4.5 `_device_room_id`/`_device_zone_id` inline; T4.6
  `_cmd_list_pool` via `get_pool_devices`. 6 §L-Tests in
  `test_sprint13b1_lifecycle_filters.py`. T2-Followup-Fixes
  (test_device_schema, test_sprint12_e2e._make_device).
  `csv_parser.py:205` + `pairing_service.py:135` bleiben bewusst
  ungefiltert (Phase-0-Update §L), Docstrings auf 13b.1-Stand.
- **T5 (Commit `3497f74`):** `replace_device` + `retire_device` in
  `device_service.py`. Race-Schutz: UPDATE-WHERE-Clause
  (`heating_zone_id IS NULL AND retired_at IS NULL`) auf Pool-
  Reservierung, `rowcount`-Check liefert `PoolDeviceUnavailable`
  bei race-Konflikt. Drei Exceptions
  (`DeviceNotFound`/`DeviceStateError`/`PoolDeviceUnavailable`).
  `BusinessAudit DEVICE_REPLACED` + `DEVICE_RETIRED` atomar.
  13 Tests inkl. Race-Test (2 Sessions via `asyncio.gather`).
- **T6 (Commit `da4b921`):** Drei API-Endpoints in `api/v1/devices.py`
  — `GET /devices/pool`, `POST /{id}/replace/from-pool`,
  `POST /{id}/retire`. `require_admin` fuer Mutationen,
  `require_user` fuer Pool-Read. Engine-Tick-Trigger nach commit
  (Pattern HF-9.13a-2). Route-Order-Fix: `/pool` vor `/{device_id}`
  (FastAPI-Path-Matching). 12 API-Tests in
  `test_api_devices_lifecycle.py`. **Brief-Annahme
  `/rooms/{id}/devices` + `/heating-zones/{id}/devices` existiert
  nicht** — Frontend nutzt `useDevices()` global (Phase-0-Update
  Audit 3).
- **T7 (User-Ausgefuehrt):** Live-Verify auf heizung-test nach Merge.
  Befund-Platzhalter siehe unten.
- **T8a (dieser Doku-Commit):** STATUS §2au + SPRINT-PLAN-Update +
  AE-57-Implementiert-Marker + RUNBOOK §10j + CLAUDE.md §5.60 Lesson
  (Race-Schutz im UPDATE-WHERE-Clause).

**Backend-Tests:** **518 passed**, 1 xfailed (Baseline 476 vor
13b.1: +3 T1, +6 T3, +6 T4, +13 T5, +12 T6, +2 Zwischenstand-Sprung
= 518). ruff format/check + mypy strict gruen.

**Diff-Summe (T1-T6):** 13 Code-Files, +1837 Insertions / −98
Deletions. 5 neue Test-Files (3 Migration-Roundtrip-Tests im
existierenden File, 6 Helper-Tests, 6 §L-Tests, 13 Service-Tests,
12 API-Tests).

**T7 Live-Verify auf heizung-test (2026-05-23, abgeschlossen):**

- **Schritt 0-2 (Deploy + Migration):** Auto-Pull-Timer hat Squash-
  Commit `55a91fa` gezogen, `alembic current` bestaetigt
  `0018_device_lifecycle (head)`. Kein manueller Pull-Trigger noetig.
- **Schritt 3 (Schema-Verify):** `\d device` zeigt drei neue Spalten
  (`retired_at TIMESTAMPTZ`, `retired_reason VARCHAR(255)`,
  `replaced_by_device_id INTEGER`), KEIN `is_active`. Partial-
  Unique-Index `ix_device_dev_eui_active_unique` mit `WHERE
  (retired_at IS NULL)` aktiv. FK `fk_device_replaced_by` self-ref
  mit ON DELETE SET NULL.
- **Schritt 4 (Pre-State + Backup):** 4 Vickis am Hotel — `id=2`
  (Vicki-001, `heating_zone_id=91`), `id=3` (Vicki-002, hz=3),
  `id=4` (Vicki-003, hz=5), `id=5` (Vicki-004, hz=7). Alle
  `retired_at IS NULL`. Backups unter
  `/opt/heizung-sonnblick/backups/sprint13b1-{device,audit}-
  20260523-095006.sql` (7-Tage-Rollback-Reserve).
- **Schritt 6 (`get_pool_devices`):** Service-Call mit
  `asyncio.run()` + `async with SessionLocal()` Wrapper. Pool-
  Simulation auf `id=5` lieferte korrekt `pool_count=1 ids=[5]`.
- **Schritt 7 (`retire_device`):** `retire_device(id=2,
  reason="sprint-13b1-live-verify")` -> `retired_at` gesetzt,
  `DEVICE_RETIRED`-BusinessAudit-Row mit `new_value` JSONB
  (`reason`, `retired_at_iso`, `heating_zone_id=91`).
- **Schritt 8 (`replace_device`):** `replace_device(old=3,
  new_pool=5)` -> `id=3` wird `retired_at` + `replaced_by_id=5` +
  `heating_zone_id=NULL`, `id=5` uebernimmt `heating_zone_id=3` aus
  alter Zone. `DEVICE_REPLACED`-Audit mit `new_value` JSONB
  (`new_device_id=5`, `heating_zone_id=3`, `replaced_at_iso`).
- **Schritt 9 (Datenkonsistenz):** alle 4 Vickis im erwarteten
  State, Cross-Reference Alt -> Neu via `replaced_by_device_id`
  korrekt.
- **Schritt 10 (Race-Test):** zweiter `replace_device(old=2,
  new_pool=5)` mit bereits retired `id=2` -> `DeviceStateError`:
  `"old_device_id=2 ist bereits retired ... Re-Replace nicht
  erlaubt"`. Gate-Stack greift sauber.
- **Schritt 11 (Engine-Tick post-replace):** `evaluate_room` fuer
  die aktive Zone 3 mit Vicki-003-Uplink wurde geschedult (Pattern
  HF-9.13a-2). Fuer retired `id=3` ein graceful skip + Warning
  "device_id=3 ohne heating_zone -> kein Re-Eval" — Layer 4 / Engine
  sehen retired Devices nicht mehr. Keine ControlCommand-Rows fuer
  retired.
- **Schritt 12 (API-Smoke):** `GET /api/v1/devices/pool` ohne
  Auth -> 401 (Auth-Wall steht, AUTH_ENABLED=true greift).
- **Schritt 13 (Cleanup):** alle 4 Vickis auf Pre-Test-State
  zurueckgerollt (drei separate UPDATEs nach Heredoc-Drift in
  PowerShell-SSH-Paste, siehe §5.62 Lesson). BusinessAudit-Rows
  persistent als Audit-Trail (kein Cleanup-Delete — Sprint 13b.1
  T7-Run dokumentiert).
- **Schritt 14 (Final-Verify):** Engine-Tick laeuft normal, alle 4
  Vickis wieder in Reads sichtbar.

Live-Verify-Lessons (s.u. CLAUDE.md §5.61 + §5.62):

- Live-Verify-Service-Wrapper braucht `await session.commit()`
  explizit (Services committen bewusst nicht — FastAPI-Endpoint-
  Pattern).
- BusinessAudit-Schema heisst `new_value` JSONB + `old_value` JSONB
  (nicht `details`). DB-Schema gegen Brief-Annahme verifizieren
  bevor Tests + Doku festgelegt werden.
- `pg_dump --data-only` auf `device`-Tabelle warnt wegen
  zirkulaerer FK `fk_device_replaced_by`. Restore via
  `pg_restore --disable-triggers` oder Full-Dump (RUNBOOK §10j
  ergaenzt).
- PowerShell-Paste schluckt Heredoc + sleep-Pausen. SSH-Befehle als
  separate Einzelzeilen einklopfen, kein `<<SQL...SQL`-Heredoc.

**Out of Scope (Sprint 13b.2):**

- Frontend-Dialog "Vicki ersetzen" auf `/zimmer/[id]` (shadcn Dialog
  + Pool-Dropdown-Select via `GET /devices/pool`)
- shadcn `badge`-Komponente fuer Reserve-Tag falls visuell gewuenscht
- E2E-Playwright-Test Tausch-Flow

**Out of Scope (spaeter):**

- B-Sprint13a-5 (`pairing_status`-Feld fuer Downlink-Failure-
  Recovery-Variante-B) — Strategie-Entscheidung 2026-05-23: nicht in
  0018, eigener Sprint nach erster Heizperiode-Auswertung.
- Open-Window-Detection-Re-Send an new device beim Tausch (B-13b-2)
  — Pool-Device hat OW-Config aus Pre-Pairing-Eingangstest.
- DEV_EUI-Wiederverwendung nach Retire im CSV-Bulk-Pairing
  (B-13b-1) — Pre-Flight ist absichtlich strenger als DB-Constraint;
  Re-Pair via Tausch-Endpoint, nicht CSV.

**Neue Backlog-Punkte:**

- **B-Sprint13b1-1** 🟢: BusinessAudit-Tests mit `user_id != None`
  brauchen User-Fixture-Setup. Heute weichen Service-Tests via
  `user_id=None` aus (System-Trigger-Pattern). API-Tests (TestClient)
  testen den User-Pfad live (via `require_admin`-Dependency). Voll-
  Coverage-Run mit echtem User-FK kommt in 13b.2-Tests mit, wenn
  Frontend-User-Cookie via dependency_override testbar wird.
- **B-Sprint13b1-2** 🟢: Engine-Tick-Trigger-Latenz beim
  Tausch-Endpoint dokumentieren (Pattern HF-9.13a-2). Heute folgt
  `evaluate_room.delay()` direkt nach commit; Worker-Pickup ~5-6 Sek
  (B-9.13a-hf2-2). Falls Frontend-UX im 13b.2-Tausch-Dialog ein
  "Loading"-Indikator brauchen wuerde: hier verlinken.

**Querverweise:** AE-57 (Master-ADR), Phase-0-Bericht
`docs/features/2026-05-21-sprint13-phase0-quellcheck.md`,
Phase-0-Update `docs/features/2026-05-23-sprint13b-phase0-update.md`,
RUNBOOK §10j, CLAUDE.md §5.58 + §5.60 + §5.61 + §5.62 + §5.63,
STATUS §2at + §2av.

---

## 2av. Sprint 13b.2 Frontend Pool-Reassign-Tausch + Stilllegen (2026-05-24, abgeschlossen, PR pending)

**Ziel:** Frontend-Komplettierung von AE-57: Hotelier-UI fuer Vicki-
Tausch (Pool-Reassign) + Stilllegung ohne Ersatz auf `/zimmer/[id]`
Geraete-Tab. Reserve-Pool-Identifikation in `/devices`-Liste. Sitzt
auf den drei 13b.1-Endpoints (`GET /devices/pool`,
`POST /{id}/replace/from-pool`, `POST /{id}/retire`).

**Branch:** `feature/sprint-13b2-device-replacement-frontend`,
**13 Commits** auf develop @ `72a6e16`. PR pending (Stop 5).

**Tag (geplant nach Merge):** `v0.1.18b2-device-replacement-frontend`

**Tasks erledigt (Brief T1-T8 + 4 Brief-Plus-Adds + T9 Doku):**

- **T1.d (`40354e0`):** `components/ui/form-dialog.tsx` — neue
  Primitive analog ConfirmDialog, aber mit `children`-Body-Slot fuer
  Form-Inhalte. Drift-4-Resolution (ConfirmDialog Confirm-only
  reicht nicht fuer Pool/Reason-Dropdown).
- **T1.c-prep (`e2cb807`):** Lifecycle-Type-Drift schliessen.
  `types.ts`: `is_active` aus `Device`/`Create`/`Update`/`ListQuery`
  entfernt, `retired_at`/`retired_reason`/`replaced_by_device_id`
  als Required-Felder ergaenzt. 3 Konsumenten umgestellt
  (`/devices`-Liste Sortier + Spalte "Eingerichtet"→"Aktiv",
  `/devices/[id]`-Detail-Header). 3 e2e-Device-Mocks angepasst.
  Live-UX-Bug-Fix (Devices zeigten "Eingerichtet: nein" weil
  `is_active` weg). Brief-Luecken-Klasse — neue Lesson §5.63.
- **T1.c (`c0923d7`):** `lib/api/devices.ts` — 3 typisierte Client-
  Funktionen `getPool`, `replaceFromPool`, `retireDevice` plus 2
  Request-Types in `types.ts`.
- **T1.b (`7953ccb`):** `lib/api/hooks-devices-lifecycle.ts` (neu)
  — `useDevicePool` (staleTime 10s, Race-relevant),
  `useReplaceFromPool`/`useRetireDevice` (Mutations mit optionalem
  `roomId`-Param fuer zone-spezifische Invalidation).
- **T2 (`93fd973`):** `components/ui/badge.tsx` (neu) — shadcn-
  Standard, 4 Varianten (`default`/`secondary`/`destructive`/
  `outline`), Token-Konvention konsistent zu dialog.tsx +
  select.tsx (`--primary`/`--secondary`/`--destructive`-HSL-CSS-
  Variables in globals.css).
- **T3 (`d400176`):** DevicesInRoom-Erweiterung in
  `/zimmer/[id]/page.tsx` — 2 Action-Buttons pro Device-Row
  (`swap_horiz Tauschen`, `power_off Stilllegen`) neben `Trennen`,
  State-Anker `openReplaceDialog`/`openRetireDialog`.
- **T0.6 (`6d59c63`):** sonner Toast-Library + `lib/toast.ts`-
  Wrapper (`showSuccessToast`/`showErrorToast`/`showWarningToast`).
  `<Toaster position="top-right" richColors closeButton />` in
  `layout.tsx`. Drift-5-Resolution (Toast-Lib war nicht im Repo).
- **T4 (`f510cc9`):** `components/patterns/replace-device-dialog.tsx`
  — Pool-Dropdown via shadcn Select, Empty-State-Hinweis,
  409-Subtype-String-Match (RE_POOL_UNAVAILABLE +
  RE_DEVICE_STATE_ERROR), Toast-Wiring, Pool-Refetch via
  `qc.invalidateQueries` bei Race.
- **T5 (`058e464`):** `components/patterns/retire-device-dialog.tsx`
  — Reason-Dropdown (4 feste Optionen Defekt/Batterie leer/Verlust/
  Wartung), Last-Active-Warning-Box bei 1-Vicki-Zone (orange
  `bg-warning-soft`), destructive Confirm-Button.
- **T6 (`89605f2`):** Reserve-Badge in `/devices`-Liste
  (`LabelCell`) bei `heating_zone_id === null &&
  retired_at === null` — `variant="secondary"` + Hover-Tooltip.
- **T7-prep (`355baa7`):** Fixture-Suffix-Patch in
  `test_pair_devices_cli.py::test_cmd_import_real_with_user_email`
  (numerischer uuid-hash-Suffix wegen Pydantic-int-Validator auf
  CSV-zimmer_nummer). §5.18-Konformitaet, Pre-existing 13a-Test-
  Hygiene-Bug.
- **T7 (`bad4a26`):** CLI-Wording-Fixes in `scripts/pair_devices.py`
  — B-Sprint13a-9 (Dry-Run-Message "trotzdem gesendet" →
  "versucht (Ergebnisse siehe oben)") + B-Sprint13a-8 (Resultat-
  Output mit DOWNLINK_FAILED-Disambiguation in Klammer). Cross-
  Sprint-Backend-Touch.
- **T8 (`27a28e6`):** `frontend/tests/e2e/sprint13b2-device-
  replacement.spec.ts` — 5 Playwright-Cases (Replace Happy /
  Pool-leer / Pool-Race-409 / Retire Happy / Retire Last-Active-
  Warning). page.route-Mocks analog Sprint-12b-T5-Pattern, §5.54-
  Regex-URLs.
- **T9 (dieser Commit):** STATUS §2av + SPRINT-PLAN-Update + AE-57-
  Status komplett + RUNBOOK §10j.6 Hotelier-Workflow + CLAUDE.md
  §5.63 Lesson + Backlog-Abschluesse.

**Tests (Stop 4 Voll-Suite):**

- Frontend `tsc --noEmit`: gruen
- Frontend `next lint`: gruen, 0 warnings
- Frontend Playwright voll-suite: **58 passed (43.5s, 0 retries)**,
  davon 5 neu in T8. Alle 9.x + 12.x Bestands-Tests weiter gruen
  (T1.c-prep Device-Mock-Patches in 3 e2e-Files haben nichts
  gebrochen).
- Backend ruff format/check + mypy strict + pytest **240 passed /
  279 skipped / 0 failed** post-T7-prep (Skip-Vorbehalt: ohne
  `TEST_DATABASE_URL`; CI deckt die 279 DB-Tests).

**Diff-Summe (T1-T9):** 20 Files, **+1283 Insertions / −17
Deletions** in 14 Commits (13 Code/Test/Fix + 1 Doku).

**Live-Verify (Cowork, 2026-05-24, abgeschlossen mit Vorbehalt):**

Auftrag durchgelaufen direkt nach Tag-Push. Verifikation gegen
heizung-test (Auto-Pull-Timer hat Squash-Commit `c82af70` deployed).

| Workflow | Status | Notiz |
|---|---|---|
| 1 — Tausch-Dialog-Only (Pool leer → Submit disabled) | ✔ verifiziert | Modal-Pattern `role="dialog"` korrekt, Empty-State-Hinweis sichtbar, Submit-Button via `[aria-disabled="true"]` blockiert |
| 2 — Empty-State-Text mit RUNBOOK-§10h-Verweis | ✔ verifiziert | Wortlaut deckungsgleich mit Code (`replace-device-dialog.tsx`) |
| 3 — Replace 409-Race | ⏭ skipped | Single-Session-Cowork, kein realistischer Race-Trigger erzeugbar — Playwright-T8-Case-3 deckt das ab |
| 4 — Retire Happy-Path (echter POST `/retire` 200, 4 Reason-Optionen) | ✔ verifiziert mit Drift | Vicki-002 (`device.id=3`) wurde live retired; 4 Reason-Optionen sichtbar; KEINE Warning-Box (Zone hatte mehrere aktive Vickis) |
| 5 — Last-Active-Warning auf Zone mit nur einem Vicki | ✔ verifiziert | Orange Box (`bg-warning-soft` + `text-warning`) erscheint korrekt; Cowork hat `Abbrechen` geklickt — keine destruktive Aktion |

**Pool-leer-Blocker (5 Punkte nicht verifizierbar):**

heizung-test hatte zum Verify-Zeitpunkt **kein Reserve-Device im
Pool** (alle 4 Vickis aktiv bzw. retired). Damit nicht prueft:

- Befuellter Pool-Dropdown (>= 1 Reserve-Item)
- Replace-Happy-Submit (POST `/replace/from-pool` 200)
- Success-Toast nach Replace ("Thermostat getauscht …")
- Reserve-Badge auf `/devices`-Liste (T6, Konsument von `badge.tsx`)
- Visueller Smoke-Test der Pool-Liste in der Dropdown-Reihenfolge

Pre-Pairing eines Test-Vickis vor naechstem Cowork-Re-Test
notwendig — eigener Backlog-Eintrag **B-Sprint13b2-6**.

**Test-State-Drift nach Workflow 4:**

Workflow 4 hat `Vicki-002` (`device.id=3`) live retired, was die
Vicki-Geraete-Liste der Zone reduziert haette. Cleanup analog T7-
Live-Verify-Pattern (siehe STATUS §2au Schritt 13): direkter
`UPDATE device SET retired_at = NULL, retired_reason = NULL,
replaced_by_device_id = NULL WHERE id = 3` gegen `deploy-db-1`.
BusinessAudit-Row (`action=DEVICE_RETIRED`, `target_id=3`,
`user_id=<cowork-admin>`, `new_value` JSONB mit Test-Marker)
bleibt persistent als Forensik-Spur (kein Cleanup-DELETE, S3-
Auditierbarkeit aus CLAUDE.md §0).

**Cowork-Tooling-Beobachtung:**

`save_to_disk` nicht verfuegbar in der Cowork-Sandbox dieser
Session — Screens wurden als Text-Beobachtung dokumentiert (Modal-
Titel, Button-Labels, Toast-Inhalte als Strings im Bericht). Kein
PNG-Output, keine Anhaenge. Wird in kuenftigen Cowork-Sessions
durch andere Tooling-Variante geloest oder explizit als
Cowork-Limitierung akzeptiert.

**Funktional-Beobachtung — Dialog-Self-Close bei Hintergrund-Refetch:**

Cowork hat beobachtet, dass das Stilllegen-Modal nach laengerer
Wartephase selbsttaetig schliesst. Vermutete Ursache: TanStack-
Query Background-Refetch triggert Parent-Re-Render von
`DevicesInRoom`, der State-Anker `openRetireDialog` (lokal in
`DevicesInRoom`) wird durch den Re-Render verloren bzw. die
Komponenten-Identitaet bricht. Im Hotelier-Tempo (max. ein paar
Sekunden zwischen Click und Submit) unkritisch, im
Sit-Down-Test-Pattern aber irritierend. Eigener Backlog-Eintrag
**B-Sprint13b2-5** mit Fix-Optionen.

Vermutlich gleicher Effekt im ReplaceDeviceDialog (Pool-Refetch
nach `staleTime: 10_000`). Heute nicht direkt beobachtet, aber
strukturell identisch.

**Live-Verify-Fazit:** 4 von 9 geplanten Pruefpunkten verifiziert,
1 skipped (Race nur per Playwright-Mock testbar), 5 blockiert durch
Pool-leer-State. Frontend-Implementierung korrekt fuer die
verifizierten Pfade; Pool-Pfad-Reverify-Auftrag steht
(B-Sprint13b2-6) nach Pool-Refill.

**Drift-Resolutionen (Brief-Plus-Adds):**

| Drift | Resolution | Commit |
|---|---|---|
| 1+2 Hook-Pfad/Naming | `lib/api/hooks-devices-lifecycle.ts` analog `hooks-overrides.ts` | `7953ccb` |
| 3 Komponenten-Pfad | `components/patterns/` (Repo-Konvention) | `f510cc9` + `058e464` |
| 4 Dialog-Wrapper-Pattern | neue `FormDialog`-Primitive mit `children`-Slot | `40354e0` |
| 5 Toast-Library fehlt | sonner-Installation + `lib/toast.ts`-Wrapper | `6d59c63` |

Plus Schema-Drift-Discovery T1.c-prep (Lifecycle-Type-Spiegel) als
neue Brief-Luecken-Klasse §5.63.

**Backend-409-Distinktion ohne exception_class-Diskriminator:**

Verifiziert in `backend/src/heizung/api/v1/devices.py:474-481` +
`services/device_service.py:39-179`: Backend liefert beide 409
(PoolDeviceUnavailable + DeviceStateError) nur als
`{detail: <string>}`. Frontend nutzt String-Pattern-Match
(`RE_POOL_UNAVAILABLE = /Pool|parallel vergeben/i` +
`RE_DEVICE_STATE = /retired|nicht zugewiesen|Re-Replace/i`).
Fragil gegen Backend-Wording-Refactor — Backlog-Item
**B-Sprint13b2-4** fordert `exception_class`-Feld in 409-Response
fuer robustes Frontend-Match. Vor Heizperiode 2026/27.

**Out of Scope 13b.2 (in spaeteren Sprints):**

- Frontend-Tabelle fuer retired Devices (Brief: B-Sprint13a-6 als
  sortierbare Liste — durch Backend-Default-Filter blendet sich
  retired heute aus der `/devices`-Liste aus; eigener Audit-Sprint
  in 14+).
- Filter "Nur Reserve anzeigen" in `/devices`-Liste (YAGNI).
- Server-Side-`include_retired=true`-Sicht im Frontend (Audit-UI
  Sprint 14+).
- Migration der 8 Bestands-Inline-Error-Stellen auf Toast (Phase-7-
  Polish, B-Sprint13b2-3).

**Neue Backlog-Punkte:**

- **B-Sprint13b2-1** 🟢: 8 weitere CLI-Tests in
  `tests/test_pair_devices_cli.py` (Tests fuer Subcommands
  validate, import-pre-flight, test) nutzen Hardcoded-Room-Numbers
  (7101/7102/99999) ohne uuid-Suffix. Gleiche Klasse §5.18-Verstoss
  wie T7-prep, heute zufaellig nicht kollidiert. ~15 Min Hygiene-
  Sprint.
- **B-Sprint13b2-2** 🟢: CLI-Tests brauchen autouse-Cleanup-Fixture
  mit Prefix-Filter analog §5.39 — conftest-Patch verhindert dass
  failed-Test-Leftovers nachfolgende Runs killen. Vor naechstem
  CLI-Test-Sprint.
- **B-Sprint13b2-3** 🟢: sonner-Migration der 8 Bestands-Inline-
  Error-Stellen (ManualOverridePanel, Login-Form, etc.). Heute
  zwei Feedback-Patterns parallel — Strategie-Setzung 2026-05-23
  akzeptiert. Phase-7-Polish-Sprint.
- **B-Sprint13b2-4** ✅ erledigt 2026-05-24: 409-Subtype-Diskriminator
  via `error_code`-Feld implementiert. Backend ``LifecycleError``-
  Hierarchie + app-weiter FastAPI-Handler, Frontend ``error-codes.ts``
  + Type-Guard, beide Dialoge migriert weg von String-Regex.
  Voll-Coverage-Matrix in AE-59. Tatsaechlicher Aufwand 2-3 h wie
  Brief, +1 T4-Discovery (client.ts-Fetch-Wrapper-Extraction). Siehe
  §2aw + AE-59 + CLAUDE.md §5.64.
- **B-Sprint13b2-5** ✅ erledigt 2026-05-25: Dialog-Open-State
  (`openReplaceDialog`/`openRetireDialog`) von `DevicesInRoom` auf
  `ZimmerDetailPage`-Root gehoben, Dialog-Renders ans Page-Ende
  verschoben. Variante (a) aus dem Backlog-Eintrag. Background-
  Refetch von `useDevices()` re-rendert weiterhin die Geraete-Liste
  in `DevicesInRoom`, der Dialog-Subtree haengt jetzt ausserhalb
  und ist von dem Re-Render entkoppelt. Implementation in
  `feature/b-sprint13b2-5-dialog-self-close`, Diff +72/-52 in
  `frontend/src/app/zimmer/[id]/page.tsx`. Type-check + Lint +
  Playwright-Voll-Suite (60 Cases) gruen. Manueller UI-Verify lokal
  bestaetigt: Dialog bleibt 60 s offen bei manuellem
  `queryClient.invalidateQueries({ queryKey: ["devices"] })` in den
  DevTools. KEIN neuer Playwright-Test (Timing-abhaengig, schwer
  reproduzierbar). KEIN eigener Tag — geht mit dem
  `v0.1.18c-hygiene-minisprint`-Sammel-Tag nach allen drei Hygiene-
  Items.
- **B-Sprint13b2-6** 🟡 (vor naechstem Cowork-Re-Test): Pool-Refill
  auf heizung-test. Heute kein Reserve-Geraet im System -> 5
  Cowork-Pruefpunkte (befuellter Pool-Dropdown, Replace-Happy-Submit,
  Replace-Toast, Reserve-Badge T6, Pool-Reihenfolge) blockiert. Pre-
  Pairing-Eingangstest gemaess RUNBOOK §10h fuer ein Test-Vicki
  (z.B. ein bisher nicht-eingespieltes Geraet aus dem Lager),
  anschliessend Folge-Cowork-Auftrag fuer die offenen 5 Punkte.

**Querverweise:** AE-57 (Master-ADR, jetzt komplett),
RUNBOOK §10j.6 (Hotelier-Workflow), CLAUDE.md §5.30 + §5.43 +
§5.58 + §5.63 + §5.64, SPRINT-PLAN Sprint 13b.2, STATUS §2au +
§2at + §2aw.

---

## 2aw. B-Sprint13b2-4 error_code-Diskriminator (2026-05-24, abgeschlossen, PR pending)

**Ziel:** 409-Subtype-Diskriminator via `error_code`-Feld im Response-
Body. Frontend-Migration weg von String-Regex auf ``detail``. Belegt
durch Phase-0-Audit (PR #180, gemerged ``c67c4ce``). Strategie-
Setzung 2026-05-24: Top-Level-Sibling-Schema + 4 Codes + ``Lifecycle-
Error``-Basisklasse + app-weiter FastAPI-Handler.

**Branch:** `feature/b-sprint13b2-4-error-code-discriminator`,
**5 Commits** auf develop @ `c67c4ce`. PR pending (Stop 5).

**Tag (geplant nach Merge):** `v0.1.18b3-error-code-discriminator`

**Tasks erledigt (T1-T7):**

- **T1+T2+T3 (`5c3a34d`):** Backend-Refactor in einem atomaren
  Commit, weil Exception-Hierarchie + App-Handler + Tests
  voneinander abhaengen.
  - Neue Datei `backend/src/heizung/services/exceptions.py` mit
    `LifecycleError`-Basisklasse (ClassVar[str] error_code) + 4
    Subklassen (`DeviceNotFound`, `DeviceStateError`,
    `PoolDeviceUnavailable`, `SelfReplacementError`).
    N818-noqa analog Pre-13b.1-Konvention.
  - `device_service.py`: alte 3 Klassen entfernt, Import aus
    exceptions.py (noqa F401, Backwards-Compat-Re-Export), inline
    `ValueError("Selbst-Tausch...")` -> `SelfReplacementError(...)`.
  - `main.py`: `@app.exception_handler(LifecycleError)` rendert
    `{detail, error_code}` mit 404 fuer DeviceNotFound, sonst 409.
  - `api/v1/devices.py`: 4+2 try/except-Branches in
    replace/retire-Endpoints entfernt; LifecycleError-Imports raus.
  - `tests/test_api_devices_lifecycle.py`: 4 Bestandstests um
    error_code-Assertion erweitert + 2 neue Tests
    (`test_replace_from_pool_409_self_replacement_forbidden`,
    `test_replace_from_pool_409_pool_unavailable_direct`).
- **T4 (`aaa3388`):** Frontend `lib/api/error-codes.ts` (neu) mit
  ERROR_CODES + ErrorCode-Type + ApiErrorBody-Interface +
  getErrorCode-Type-Guard. Plus `types.ts` ApiError um
  optional `error_code?: string` erweitert. Plus `client.ts` Fetch-
  Wrapper reicht `body.error_code` durch (Discovery — ohne diesen
  Patch waere der Diskriminator nie im Dialog-Catch angekommen).
- **T5 (`49ebbea`):** Beide Dialoge migriert weg von String-Regex:
  - `replace-device-dialog.tsx`: 2 Modul-Konstanten entfernt,
    switch ueber 4 ERROR_CODES, Toast-Wortlaut unveraendert,
    2 neue UX-Pfade (SELF_REPLACEMENT_FORBIDDEN defensiv +
    DEVICE_NOT_FOUND mit Refetch).
  - `retire-device-dialog.tsx`: inline `/retired/i` entfernt,
    `useQueryClient` hinzu (vorher kein Cache-Invalidate bei 409),
    switch ueber 2 relevante Codes + default.
- **T6 (`9ef6651`):** Playwright Case 3 (Pool-Race) Mock-Body um
  `error_code: "POOL_DEVICE_UNAVAILABLE"` erweitert. Plus Cases 6+7
  neu (DEVICE_STATE_ERROR Replace + DEVICE_NOT_FOUND Retire). Voll-
  Suite 60 passed (vorher 58, +2 neue).
- **T7 (dieser Commit):** AE-59 (ARCHITEKTUR-ENTSCHEIDUNGEN.md) +
  CLAUDE.md §5.64 + STATUS §2av-Marker + dieser §2aw-Block +
  Backlog-Updates B-Sprint13b2-4 ✅ + B-Sprint13b2-7 + B-Sprint13b2-8
  neu.

**Tests (Stop 4 Voll-Suite):**

- Backend ruff format/check + mypy strict (98 source files, +1
  exceptions.py) + pytest **240 passed / 281 skipped / 0 failed**
  lokal (CI-Projection 518 + 2 = **520 passed**).
- Lifecycle-Test-Suite mit DATABASE_URL gesetzt: **14 passed** (vorher
  12, +2 neue).
- Frontend tsc + lint + Playwright voll-suite **60 passed (45.7s, 0
  retries)** — 58 alt + 2 neu (Cases 6+7).

**Diff-Summe (T1-T7):** 5 Commits, **12 Files, +600+ Insertions / −110
Deletions** (T1-T6: 11 Files +534/−109, T7-Doku: +5 Files Append).

**Live-Verify:** ausstehend. Backend-Schema-Change ist transparent
fuer alle Bestands-Konsumenten (`detail` bleibt String, `error_code`
ist additive). Cowork-Re-Test fuer Frontend-Dialoge nach naechstem
Pool-Refill (B-Sprint13b2-6 immer noch offen — siehe §2av).

**Discoveries:**

- **T4-Discovery:** `frontend/src/lib/api/client.ts` Fetch-Wrapper
  verwarf `body.error_code` (extrahierte nur `body.detail`). Ohne
  Anpassung waere der Diskriminator NIE im Dialog-Catch angekommen.
  Pflicht-Vorsichts-Punkt fuer kuenftige Schema-Erweiterungen (siehe
  CLAUDE.md §5.64).
- **T5-Beifang:** RetireDeviceDialog hatte pre-T5 keinen Cache-
  Invalidate-Pfad bei 409 (`/retired/i` matchte und Toast + Close,
  aber keine devices-Refetch). Mit DEVICE_STATE_ERROR + DEVICE_NOT_FOUND
  ist Invalidate jetzt konsistent.
- **Bundle /zimmer/[id]:** first-load von 160 kB auf 171 kB (+11 kB).
  Verursacher: error-codes.ts + Switch-Statements + 4 Toast-Texte je
  Dialog. Akzeptabel, aber Backlog-Item B-Sprint13b2-8 fuer Phase-7-
  Bundle-Audit.

**Test-Coverage-Matrix:**

| error_code | Backend pytest | Frontend Playwright |
|---|---|---|
| POOL_DEVICE_UNAVAILABLE | ✔ test_replace_from_pool_409_pool_unavailable_direct | ✔ Case 3 |
| DEVICE_STATE_ERROR | ✔ test_replace_from_pool_409_new_not_in_pool + test_retire_409_already_retired | ✔ Case 6 (Replace) |
| SELF_REPLACEMENT_FORBIDDEN | ✔ test_replace_from_pool_409_self_replacement_forbidden | ❌ UI nicht triggerbar (Dropdown blockiert) |
| DEVICE_NOT_FOUND | ✔ test_replace_from_pool_404_unknown_old + test_retire_404_unknown | ✔ Case 7 (Retire) |

**Out of Scope (in spaeteren Sprints):**

- overrides.py-Konvention-Drift (Sprint 12c `error_code`-Key vs 12a
  `error`-Key). AE-59 ist jetzt die kanonische Konvention; B-Sprint13b2-7
  konvergiert die zwei Bestandscases sobald jemand sie ohnehin touched.
- Andere Endpoint-Familien (auth, users, etc.) — kein `error_code`
  heute, weil keine Subtype-Diskriminierung im Frontend noetig ist.

**Neue Backlog-Punkte:**

- **B-Sprint13b2-7** ✅ erledigt 2026-05-25: overrides.py +
  Sprint-12a-error-Key auf AE-59 konvergiert.
  ``OverrideError``-Basisklasse + 4 Subklassen (InvalidZoneError,
  RoomNotOccupiedError, RoomOverrideBlockedError,
  OverrideRejectedWindowOpenError) mit ``error_code``/
  ``http_status``-ClassVars + ``response_extras()``-Hook in
  ``override_service.py``. App-weiter
  ``@app.exception_handler(OverrideError)`` in ``main.py``. 3
  except-Branches + 1 inline HTTPException in ``api/v1/overrides.py``
  entrümpelt — alles laeuft jetzt durch den Handler. Frontend:
  ``ERROR_CODES`` um die 4 Override-Codes erweitert,
  ``override-errors.ts`` auf ``getErrorCode`` umgestellt
  (extractErrorCode entfernt). 6 Backend-Asserts + 2 Playwright-Mocks
  auf SCREAMING_SNAKE_CASE + Top-Level-Schema migriert. AE-59
  Scope-Grenze erweitert auf „alle API-Endpoints mit Mehrfach-
  Subtypen pro HTTP-Status". Branch
  ``refactor/b-sprint13b2-7-error-code-convergence``. KEIN eigener
  Tag — geht mit ``v0.1.18c-hygiene-minisprint``-Sammel-Tag.
- **B-Sprint13b2-8** 🟢 (Phase-7-Bundle-Audit): `/zimmer/[id]` first-
  load von 160 kB auf 171 kB gewachsen durch error-codes.ts + Switch-
  Logik + 4+2 Toast-Texte je Dialog. Pruefen ob Tree-Shaking
  vollstaendig greift (ERROR_CODES wird als const-object exportiert,
  sollte tree-shake-bar sein) oder ob der Switch in zwei Dialog-
  Files dedupliziert werden kann. Backlog-Item, kein Pflicht-Touch.

**Querverweise:** AE-59 (ADR + Schema), AE-57 (Master-Lifecycle —
nun komplett mit error_code-Schicht), Phase-0-Audit PR #180,
CLAUDE.md §5.64 (Lesson), STATUS §2av (Sprint 13b.2 als
direkter Vorgaenger).

---

## 2ax. Hygiene-Mini-Sprint v0.1.18c (2026-05-25, abgeschlossen)

**Ziel:** Vier Hygiene-/Fix-Items zwischen Sprint 13b.2 und Sprint 14
bündeln, bevor Phase 3 (Cross-Sicht-UI) startet. Sammel-Tag
`v0.1.18c-hygiene-minisprint` nach Voll-Abschluss.

**Items:**

| Item | PR | Commit | Inhalt |
|---|---|---|---|
| B-Sprint13b2-5 | #182 | `0323d4e` | Dialog-Self-Close bei Background-Refetch — Open-State von `DevicesInRoom` auf `ZimmerDetailPage`-Root gehoben (Variante a aus dem Backlog-Eintrag). Type-check + Lint + Playwright (60 cases) grün. |
| B-Sprint13b2-7 + B-FlakyTime-3 | #183 | `1e3d23a` | `OverrideError`-Basisklasse + 4 Subklassen mit `error_code`/`http_status` ClassVars, App-Handler in `main.py`, Frontend `ERROR_CODES`-Erweiterung. Plus Hotfix für 8 time-bombed Tests in `test_engine_layer3.py` (`@freeze_time(FROZEN_NOW)` ergänzt). Voll-Suite 520+8 grün. |
| B-10-4 Phase-0-Audit | #184 | `7bfa892` | 6-Audit-Read-Only-Bericht zur DST-Robustheit der Engine. 1× 🔴 KRITISCH (Layer 2 Nachtabsenkung UTC-vs-Local), alles übrige 🟢. Hotelier-Bestätigung 2026-05-25: heutige Werte sind Lokal-Intent. |
| B-10-4-Fix | #185 (dieser PR) | pending | `_RoomContext.timezone`-Feld aus `global_config.timezone`, `layer_temporal` konvertiert UTC-now via `ZoneInfo` zu Lokal-Zeit vor `.time()`-Vergleich. 3 neue Tests (Sommer CEST, Winter CET, DST-Wechsel 28.10.2026), 10 Bestand-Layer-2-Tests grün ohne Anpassung. AE-60 + CLAUDE.md §5.65. |

**Tests (post-B-10-4-Fix):**

- Backend `ruff format + ruff check + mypy strict`: grün
- Backend Voll-Suite gegen Postgres: **526 passed, 1 xfailed** (520
  Stand pre-Fix + 3 neue Layer-2 + ggf. 3 Nebeneffekt-Auto-Discovery)
- Frontend `type-check + lint + Playwright`: grün (unverändert seit
  PR #183)

**Architektur-Touch:** AE-60 (TZ-Handling Engine: UTC intern, Lokal-
Zeit für Hotelier-Konfigurationen) — Master-ADR für künftige
Hotelier-konfigurierbare Zeit-Felder. CLAUDE.md §5.65 als Lesson
zur Pflicht-Pattern.

**Out of Scope (bleibt Backlog):** B-Sprint13b2-1 (CLI-Tests-uuid-
Suffix), B-Sprint13b2-3 (sonner-Migration Inline-Errors) — beide
geringer Aufwand, kein Heizperiode-Bezug. Verbleiben als Phase-7-
Polish im nächsten Hygiene-Bundle.

**Tag:** `v0.1.18c-hygiene-minisprint` nach B-10-4-Fix-Merge
(Sammel-Tag, vom Hotelier ausgelöst).

**Querverweise:** AE-60, §5.59 (Time-Logic-Klasse), §5.64 +
§5.65 (Lessons), B-10-4 Phase-0-Audit
(`docs/features/2026-05-25-b-10-4-dst-phase0-audit.md`).

---

## 2ay. Sprint 14a Cross-Sicht-UI Geräte-Liste + Detail + Hardware-Nummer (2026-05-26, abgeschlossen, PR pending)

**Ziel:** Erste Cross-Sicht-UI-Strecke (Phase 3): Geräte-Liste auf drei
Spalten verschlankt, Geräte-Detail um Zuordnung/Identifikation + Diagnose-
Kacheln erweitert, hersteller-übergreifende Hardware-Nummer eingeführt,
ZoneHealthBadge neu (Co-Existenz mit HardwareStatusBadge). Geräte-Seiten
sind read-only Diagnose (AE-61), Steuerung bleibt auf Zimmer-Seiten.

**Hinweis Slot/Nummer:** Phase-0 hatte §2ax + AE-60 reserviert — beide
wurden parallel vom Hygiene-Mini-Sprint (§2ax) bzw. B-10-4 (AE-60) belegt.
Dieser Eintrag läuft daher als §2ay, der ADR als AE-61 (Drift-Resolution
Strategie-Chat 2026-05-26).

**Commits (Branch `feature/sprint-14a-cross-sicht-devices`):**

| Task | Commit | Inhalt |
|---|---|---|
| T2 | `5e2f333` | Migration `0020_device_hardware_number`: `device.hardware_number VARCHAR(64) NULL` + Partial-Unique-Index (`WHERE hardware_number IS NOT NULL`, analog DevEUI/0018). Model-Feld + 3 Roundtrip-Tests. |
| T3 | `20392ea` | Backend enriched `DeviceRead` (additiv): Nested `heating_zone{name, health_state, room{number, room_type{name}}}`, `hardware_number`, `active_override` (read-only, AE-61), `latest_reading`. Eager-Load (selectinload) auf List/Detail/Pool + Mutationen; `DeviceUpdate.hardware_number` + 409. 6 API-Tests. Lifecycle-Filter AE-57 unverändert. |
| T4-T6 | `ad56a37` | Frontend Type-Spiegel (§5.63); 3-Spalten-Liste (Bezeichnung·Zuordnung·Status); Detail mit 2 Karten (Zuordnung/Identifikation) + 7 Kacheln (4 Bestand + Ventilstellung[defensiv]/Fenster+Backplate/Override); Inline-Edit Bezeichnung + Hardware-Nummer; ZoneHealthBadge (4 Zustände). §5.20-Wording (Vicki→Thermostat). |
| T9 | `d20682c` | Playwright-Updates (devices/zone-health-badge/hardware-status-badge), data-testid, defensives Rendering. |
| T8 | (dieser Commit) | AE-61-ADR + STATUS §2ay + SPRINT-PLAN. |

**Tests:**

- Backend `ruff` + `ruff format` + `mypy strict`: grün. Voll-Suite gegen
  Postgres (:5433): **532 passed, 1 xfailed** (keine Regression; +9 ggü.
  pre-14a durch 3 Migration- + 6 Cross-Sicht-Tests).
- Frontend `type-check` + `lint`: grün. Playwright: **69 passed**
  (inkl. neue devices/zone-health-badge; sprint13b.2-Replace/Retire +
  hardware-status-badge + pairing unverändert grün).

**Architektur-Touch:** AE-61 (Geräte-Seiten read-only Diagnose).

**Datenquellen-Hinweis:** Detail-Kacheln Ventilstellung/Fenster/Backplate
lesen aus `device.latest_reading` (enriched), die 4 Bestands-Kacheln aus
`readings[0]` — Konsolidierung als Backlog B-14a-FU-6.

**Neue Backlog-Punkte:**

- **B-14a-FU-3** (info): `sensor_reading.spreading_factor` (LoRaWAN SF) aus
  ChirpStack-rxInfo-Metadaten persistieren — eigener Mini-Sprint, kein
  14a-Scope. Voraussetzung für SF-Diagnose/-Sortierung.
- **B-14a-FU-5** (info): Listen-Endpoint `/devices` Performance-Audit nach
  Sprint 17 Mass-Pairing — Eager-Load von `active_override` +
  `latest_reading` evaluieren (heute bewusster N+1 bei < 200 Geräten, D3).
- **B-14a-FU-6** (info): Datenquellen-Konsolidierung Detail-Kacheln —
  Bestands-Kacheln (Temp/Sollwert/Batterie/Signal) auf
  `device.latest_reading` statt `readings[0]` vereinheitlichen.
- **B-14a-FU-7** (info): SPRINT-PLAN Naming-Kollision auflösen — den
  arc42-Konsolidierungs-Sprint von „14b" umbenennen (Vorschlag:
  `Sprint 15.arc42`), damit Sub-Sprint 14b (Zimmer-Restruktur) eindeutig
  referenzierbar ist. Eigener Doku-PR nach `v0.1.19a`-Merge, nicht
  14a-blockend.

**Tag:** `v0.1.19a-cross-sicht-devices` nach PR-Merge auf develop (T10,
vom Strategie-Chat/Hotelier ausgelöst).

**Querverweise:** AE-61 (read-only Diagnose), AE-51/AE-53 (Zone-Aggregat +
Health-Modell — ZoneHealthBadge-Quelle), AE-57 (Device-Lifecycle), §5.20
(Wording), §5.63 (Frontend-Type-Spiegel), Migration `0020`.

---

## 2az. Sprint 14a.1 Spalten-Split Geräte-Liste — Hotfix (2026-05-27, abgeschlossen, Live-Verify pending)

**Anlass:** Cowork-Befund Status-Spalten-Drift auf `/devices` — die kombinierte
„Status"-Spalte rendert HardwareStatusBadge (inhaltsabhängig breite Subline
„Zuletzt: …") + ZoneHealthBadge in einem geteilten Inline-Flex-Slot; die
variable Hardware-Badge-Breite verschob die Zone-Pille → optische Drift.

**Lösung:** Variante A „Spalten-Split" (verbindlich Strategie-Chat 2026-05-27).
„Status" → zwei Spalten **„Gerät"** (`device-hardware-cell`, HardwareStatusBadge
detailed) + **„Zone"** (`device-zone-cell`, ZoneHealthBadge compact, bei
Pool-Devices Em-Dash + `aria-label`). Wrapper `overflow-hidden` →
`overflow-x-auto` (Mobile-Scroll). Eigene Tabellen-Slots statt Inline-Flow.

**Scope:** reiner Frontend-Hotfix — kein Backend, keine Migration, keine neue
Komponente, kein Detail-Seiten-Touch (`/devices/[id]` bleibt stacked, AE-61).
Diff knapp: 1× `page.tsx` + 2 Playwright-Asserts (`devices.spec.ts` th-Array → 4,
`hardware-status-badge.spec.ts` th-Filter „Gerät").

**Commit/PR:** Squash-Commit `1f6c132`, PR #187 (CI grün: Frontend `lint-and-build`
1m21s + `e2e` 2m22s). Phase-0-Audit-Vorlauf: Commit `254cb16`
(`docs/features/2026-05-27-sprint-14a-1-phase0-status-spalten.md`).

**Tests (unverändert):** Backend 532 passed / 1 xfailed; Frontend type-check +
lint + Playwright **69 passed**.

**Live-Verify:** ✅ bestätigt 2026-05-27 durch Block-A-Diagnose. Server-HEAD =
`57e50c7` auf heizung-test, alle Container healthy seit ~10:40 CEST,
deploy-pull-Timer durchgehend `status=success`. **Der „Block-A-Deploy-Stall"
war ein Phantom** (stale Claude-Code-Annahme, durch journalctl widerlegt —
siehe `docs/operations/2026-05-27-block-a-deploy-stall-diagnose.md`, §5.68).
Rein optische Cowork-Begehung der 4-Spalten-Liste auf
https://heizung-test.hoteltec.at/devices durch Hotelier ausstehend, aber
Code-Stand identisch zur grünen lokalen Cowork-Verifikation 2026-05-27.

**Tag:** `v0.1.19a.1-cross-sicht-hotfix` auf `1f6c132` (2026-05-27).

**Querverweise:** AE-61, §5.66 (Multi-Badge-Cells brauchen feste Slots), §5.67
(Tag mit Deploy-Stall + „Live-Verify pending"-Pflicht), Phase-0-Audit
`254cb16`.

---

## 2ba. Sprint 14b Zimmer-Detail Zone-Karten im Heizzonen-Tab (2026-05-27, abgeschlossen)

**Ziel:** Heizzonen-Tab auf `/zimmer/[id]` von flacher Zonen-Liste auf
**Zone-Karten** umgestellt: pro Zone ZoneHealthBadge + Thermostat-Bubbles
(Ist-Temp + Batterie) + read-only Override-Banner mit **Link-out** auf den
Übersteuerung-Tab. Backend `latest_reading` additiv erweitert.

**Drift-Resolution (Strategie-Chat 2026-05-27):**
- **A/A/B'** (statt A/A/B): Bubbles **ohne** Replace/Retire; Setpoint =
  zone-scoped Override (AE-58/AE-62), kein Setpoint-Endpoint.
- **Link-out** statt Einbettung `ManualOverrideZoneCard`: Kollisionen
  Card-Chrome + AE-52-Window-Safety-Plumbing → CTA-Tab-Wechsel, kein
  Übersteuerung-Tab-Refactor.
- **T9.5:** Override-Banner via `useZoneOverride` (Bestand-Hook) statt
  `device.active_override` — semantisch sauber (gerätelose-Zone-/Mehrfach-
  Vicki-Edge abgedeckt).

**Backend (additiv):** `DeviceLatestReadingRead` + `temperature` +
`battery_percent` (field_serializer Decimal→float) + Builder + Roundtrip-
Assert.

**Frontend:** `zone-card.tsx` (neu), `thermostat-bubble.tsx` (neu),
`heating-zone-list.tsx` (Restruktur, Create-Form bleibt, Delete via ZoneCard),
`page.tsx` (Tab-Wechsel-Callback), `types.ts` (+`HeatingZone.health_state`
§5.63, +`DeviceLatestReading` temperature/battery_percent).

**Commit/PR:** Squash `a59b7aa`, PR #191 (CI real grün: Backend `lint-and-test`
2m35s + Frontend `lint-and-build` 1m21s + `e2e` 2m32s).

**Tests:** Backend **532 passed / 1 xfailed** (Bestand + Roundtrip-Assert);
Frontend Playwright **77 passed** (69 Bestand + 8 neue 14b-Cases; 12b/12c/
13b.2 + Geräte-/Übersteuerung-Smokes grün).

**Live-Verify:** ✅ bestätigt 2026-05-27 via Cowork-Begehung heizung-test
(develop@`a59b7aa`, web-Image 17:01:17 CEST, Containers recreated 17:05:48
CEST). Geprüft A–M, drei Anmerkungen → Backlog, keine Defekte. (Deploy-Pfad
gesund — Block-A war Phantom, §5.68.)

**Tag:** `v0.1.19b-cross-sicht-zimmer-detail` auf `a59b7aa` (2026-05-27).

## 2bb. Sprint 14c Dashboard (KPI-Kacheln + Logger-Payload) (2026-05-28, abgeschlossen)

**Ziel:** Phase-3-Cross-Sicht-Abschluss (3/3 Sub-Sprints). `/`-Page von redirect("/devices") auf echtes Dashboard mit Begrüßung + 6 KPI-Kacheln + 60s-Refresh. Neuer Endpoint GET /api/v1/dashboard/kpi (additives Schema). Logger-Payload emit_health_alert 4→10 Soll-Felder (additiv, keyword-only, AE-53).

**Tag:** v0.1.19c-cross-sicht-dashboard (develop-HEAD 278c2e7, PR #195).

**Phase-0:** PR #193 (read-only Audit, docs/features/2026-05-27-sprint-14c-phase0-dashboard.md).

**Tasks:** T0 Cowork-Snapshot · T1 services/dashboard_aggregates.py (6 async Helper) · T2 Endpoint + DashboardKpiRead · T3 Logger-Payload-Erweiterung · T4 components/patterns/kpi-card.tsx · T5 lib/api/dashboard.ts (Zod) + hooks-dashboard.ts (60s) · T6 app/page.tsx Redirect→Dashboard (use client) · T7 6 Playwright-Cases · T8 Toolchain grün · T9 PR+Merge · T10 Cowork-Begehung · T11 Tag · T12 Doku.

**6 KPI-Kacheln:** Belegte Zimmer (Occupancy+Room.status) · Ø Raumtemperatur (Aggregat healthy-Zonen, Decimal) · Geräte online (health_state IN healthy/degraded, retired_at IS NULL) · Aktive Übersteuerungen (manual_override aktiv) · Fenster offen (sensor_reading.open_window OR-Aggregat) · Letzter Algorithmen-Lauf (event_log layer=HARD_CLAMP MAX(time)).

**Brief-Korrekturen (Phase-0 §5.43):** KPI 5 via sensor_reading.open_window (NICHT heating_zone.is_window_open — Feld existiert nicht). KPI 6 via event_log layer=HARD_CLAMP (engine_tick/room_eval existieren nicht; HARD_CLAMP auch im Sommer-Fast-Path emittiert).

**Test-Counts:** Backend 544 passed / 1 xfailed (532 Bestand + ~12 neu: 8 Aggregat + 4 API + Logger-10-Feld). Frontend 83 Playwright (77 Bestand + 6 neu in sprint-14c-dashboard.spec.ts).

**Live-Verify heizung-test (§5.68):** Server-HEAD 278c2e7, build-images :develop success, Container web/api frisch healthy (07:10 CEST recreated via deploy-pull-Tick), /api/v1/dashboard/kpi 401 (Route live, auth-gated; alt war 404), Frontend / 200, alembic 0020 head. Cowork-Begehung 2026-05-28: 6 Kacheln sichtbar (2 von 45 belegt, Ø-Temp echter Wert, 4 von 4 online, 0 Overrides, 0 Fenster, Tick „vor wenigen Sekunden"), Begrüßung mit User-E-Mail, Mobile 390px sauber, 60s-Refresh im Network-Tab bestätigt.

**Abweichungen:** (1) Kein Component-Test-Runner im Repo → KpiCard via Playwright + tsc abgedeckt (Backlog B-14c-FU-2). (2) User-Type ohne display_name → Greeting zeigt E-Mail/Fallback (Backlog B-14c-FU-3).

**Diff-Stats:** 17 Dateien, +1328 / −15 (PR #195, Squash 278c2e7).

**Neue Backlog-Punkte:**
- **B-14b-FU-1** 🟢 Zone-Aggregat-Ist-Temp im ZoneCard-Header (Ø healthy
  Vickis, AE-51 §4.1).
- **B-14b-FU-2** 🟢 Engine-Setpoint-Anzeige im Header (Pre-T3-Sichtung: heute
  nicht im Heizzonen-Tab).
- **B-14b-FU-3** 🟢 Inline-Edit Zone-Eigenschaften (Name/Kind/Handtuchtrockner).
- **B-14b-FU-4** 🟢 Übersteuerung-Tab evaluieren (Historie vs. Aktions-
  Doppelung; ggf. Chrome-loses-Inner-Refactor von ManualOverrideZoneCard).
- **B-14b-FU-5** 🟢 `HeatingZoneRead.active_override` backendseitig liefern →
  `useZoneOverride`-Roundtrip in ZoneCard entfällt.
- **B-14b-FU-6** 🟢 SourceBadge-Wording „Übersteuerung" → konkreterer Token
  (Rezeption/Hotelier je Source), Heizzonen-Tab + Übersteuerung-Tab gemeinsam.
- **B-14a.1-FU-2** 🟢 Mobile-Pixel-Test (390px) um `/zimmer/[id]` Heizzonen-Tab
  erweitern (bislang nur `/devices`).

**Querverweise:** AE-51, AE-53, AE-57, AE-58, **AE-62** (Zone-Override als
Setpoint-Surrogat), AE-61, §5.20, §5.63, §5.65, §5.66, §5.67, §5.68,
**§5.69** (Bestand-Komponenten-Einbettung), Phase-0-Audit `676ffcf`.

---

## 2bc. Sprint 14d Override-Sichtbarkeit (Block A + FU-4 + FU-6) (2026-05-30, abgeschlossen)

**Ziel:** Aktiv-Override-Indikator in der Zimmer-Liste (R-A/R-B, drei exklusive
Zustände); HeatingZoneRead liefert `active_override` (FU-5, useZoneOverride-
Roundtrip in ZoneCard entfällt); FU-6 SourceBadge-Wording mit Quelle Gast/
Mitarbeiter sichtbar; FU-4 Doku-Eval Übersteuerung-Tab (KEIN UI-Code).

**Tag:** `v0.1.19d-override-sichtbarkeit` (develop-HEAD `34ee75c`, PR #198
gemerged 2026-05-30, Tag gesetzt 2026-05-30 nach Cowork-OK).

**Live-Verify heizung-test (§5.68):** Server-HEAD = develop-HEAD `34ee75c`
nach 93 s SYNC-Loop. Container `deploy-api-1` / `deploy-web-1` /
`deploy-celery_worker-1` healthy nach Recreate; `deploy-celery_beat-1` mit
§5.32-akzeptiertem `health: starting`-Drift; `deploy-db-1` healthy. Alembic
no-op („Migrationen angewendet — Kopf erreicht"). Schema-Sanity im
laufenden API-Container: `RoomRead.has_active_override` + `HeatingZoneRead.
active_override` + `override_service.get_rooms_with_active_override` aus
Container importierbar.

**Cowork-Begehung 2026-05-30 (§5.66):** 5 × ✅. (a) Zimmer 101 mit aktivem
Override → „Aktiv"-Indikator (tune-Icon) sichtbar. (b) gesperrtes Zimmer →
Lock-Symbol sichtbar, KEIN „Aktiv"-Doppel-Render (R-B-Exklusivität). (c)
leeres Zimmer (vacant / occupied ohne Override) → leere Zelle. (d) Listen-
Sanity: kein Zimmer kombiniert Lock + „Aktiv". (e) Hard-Reload Ctrl+Shift+R
vor jedem Check durchgeführt.

---

## 2bd. Sprint 14e Hygiene-Rest (FU-1 + FU-2 + FU-3) (2026-05-30, Code-Stand)

**Ziel:** ZoneCard-Header zeigt Ist-Temp (FU-1) + effektiven Setpoint (FU-2 aus
event_log HARD_CLAMP-Trace) inkl. Override-Vorrang (R1). Zimmer-Detail-
Stammdaten haben Inline-Edit fuer Zone-Name + Room.room_type, gegated nach
Rolle (R5), room_type mit Engine-Wirkungs-Warnung (ConfirmDialog) und
business_audit-Eintrag (R4 bewusste Scope-Eingrenzung). Phase-0 #200 gemerged
2026-05-30 (4596e23) hat den Plan vorbereitet.

**Tag (vorgeschlagen):** `v0.1.19e-hygiene-rest` (NACH Merge + Cowork-Begehung
§5.66 + Live-Verify §5.67).

**Tasks:**
- T1 `services/zone_aggregates.latest_mean_temp_per_zone` (Batch, R-D, §5.58)
  + `HeatingZoneRead.mean_temperature_c`.
- T2 `services/event_log.latest_hard_clamp_setpoint_per_room` (DISTINCT ON,
  1h-Fenster, ix_event_log_room_time, AE-31/S3/AE-55 ohne neues Speicherfeld)
  + `HeatingZoneRead.engine_setpoint_c`.
- T3 types.ts §5.63-Spiegel, ZoneCard zwei Header-Zeilen mit
  Override-Vorrang (R1) + null→„—" (R2).
- T4 PATCH zone.name → `HEATING_ZONE_NAME_CHANGED`, PATCH room.room_type_id
  → `ROOM_TYPE_CHANGED` mit `engine_effect=rule_config_scope_room_type`.
- T5 `ZoneNameInlineEdit` (LabelCell-Pattern, kein Confirm) +
  `RoomTypeInlineEditor` (Select + ConfirmDialog Engine-Warnung).
  Affordance-Gating via `useAuth().user.role === "admin"` (R5).

**Toolchain (lokal grün):** ruff check + format (156 Dateien), mypy strict
src (102 Files), tsc, eslint, 558 Tests collected (`test_sprint14e_hygiene_
rest.py` 10 Tests skippen ohne DATABASE_URL §5.50).

**Backlog-Auflösung:**
- **B-14b-FU-1** (Zone-Ist-Temp) → **erledigt**.
- **B-14b-FU-2** (Engine-Setpoint im Header) → **erledigt** (Trace-Spiegel,
  kein neues Feld).
- **B-14b-FU-3** (Inline-Edit Zone-Eigenschaften) → **erledigt** fuer
  zone.name + room.room_type_id; kind + is_towel_warmer bewusst aus Scope
  (Phase-0 §C, ggf. spaeter).
- **B-14c-FU-3** display_name → **gestrichen** (Strategie-Chat 2026-05-30,
  Phase-0 §D).

**Pflicht-Stops genutzt:** keine substantielle Abweichung im Brief, kein R3-
Reissleine ausgeloest. Stop vor PR fuer CI-Watch + Stop vor Tag fuer Cowork.

**Querverweise:** AE-31, AE-46 (Inline-Edit), AE-50 (Auth/Role), AE-51 §4.1/
§4.2, AE-55 (HARD_CLAMP Final-Setpoint), §5.20 (Wording), §5.43 (grep-Beleg),
§5.58 (retired_at-Filter), §5.63 (Type-Spiegel), §5.66 (Cowork), §5.67 (Live-
Verify), §5.68 (Server-State-Diagnose), §5.70 (PR-Body-Datei). Phase-0:
`docs/features/2026-05-30-sprint-14e-phase0-hygiene-rest.md`.

**Tag:** `v0.1.19e-hygiene-rest` (annotated, Tag-Object `e734751`, zeigt auf
develop-HEAD `112b827` = PR #201 squash-Merge), gesetzt 2026-05-30 nach
Live-Verify + Cowork-Begehung. Tag-Reihe v0.1.19: a/a.1/b/c/d/e.

**Live-Verify (heizung-test):** SYNC auf `112b827` nach 92 s; api/web/
celery_worker healthy (celery_beat health:starting = akzeptierter Drift
§5.32); Alembic no-op (14e additiv, keine Migration). Cowork-Begehung
2026-05-30 ~17:48 CEST: FU-1 Zone-Ist-Temp + FU-2 effektiver Setpoint
(Override-Vorrang, keine konkurrierenden Zahlen) visuell OK; R2-„—"
über 0-Geräte-Zone belegt (echtes silent-Vicki-Sample steht aus, CI-T1b
deckt None ab); FU-3 Admin-Inline-Edit (name ohne / room_type mit
Confirm + Engine-Warnung) OK; Mitarbeiter-Read-Only-Gating via
require_admin CI/T4 abgedeckt (kein Test-Account in Session).
Backlog 14f: Override-Header-Redundanz (Kompakt-Header + 14b-Banner
zeigen denselben Wert doppelt) + Live-Restbeleg R2 bei real
offline-gehendem Vicki.

**Phase-0:** PR #197 (read-only Audit, `docs/features/2026-05-28-sprint-14d-phase0-hygiene.md`), §J FU-4-Eval ergänzt 2026-05-30 (T10).

**Tasks:** T1 `override_service.get_rooms_with_active_override` (EXISTS-Batch,
R-D) · T2 `list_rooms` enrich `has_active_override` (1 Batch-Query, kein N+1)
· T3 `HeatingZoneRead.active_override` + Zone-Endpoint per-Zone-Enrich (FU-5)
· T4 Backend-Tests (EXISTS-Semantik, +1-Query-Beleg, Roundtrip) · T5 Type-
Spiegel `Room.has_active_override` + `HeatingZone.active_override` (§5.63,
Konsumenten-Audit gegen Phase-0 §B/§C ohne Drift) · T6 RoomTable-Zelle (R-B-
Conditional Lock | „Aktiv" | leer) · T7 ZoneCard nutzt `zone.active_override`
direkt (useZoneOverride-Roundtrip entfernt, 14b-Test angepasst) · T8 neuer
Playwright `sprint-14d-room-list-override-indicator.spec.ts` (3 R-B-Fälle) ·
T9 FU-6 SOURCE_LABEL: Quelle in Klammern (Option A) · T10 FU-4 Eval read-only
in §J · T11 STATUS-Eintrag (dieser).

**R-A/R-B-Entscheid (umgesetzt):** Bool-Indikator + Single-Zelle. Gesperrt
schlägt has_active_override (R-B-Exklusivität), kein Zähler/Sub-Zeile/Spalten-
Split. Test `sprint-14d-room-list-override-indicator.spec.ts` belegt die
Exklusivität.

**FU-6 Wording (Option A, vom Hotelier 2026-05-30 ausgewählt):**
- `device` → „Drehknopf (Gast)"
- `frontend_4h` → „4 Stunden (Mitarbeiter)"
- `frontend_midnight` → „Bis Mitternacht (Mitarbeiter)"
- `frontend_checkout` → „Bis Check-out (Mitarbeiter)"

`SOURCE_LABEL` in `lib/overrides-display.ts` (Heizzonen-Tab + Übersteuerung-
Tab + Engine-Decision-Panel teilen). `OVERRIDE_SOURCE_LABEL` auf der Geräte-
Detail-Seite bleibt unverändert (eigener Map, „Rezeption (…)"-Form).

**FU-4 Eval (Option 1, Status Quo, vom Hotelier 2026-05-30 bestätigt):**
Heizzonen-Tab + Übersteuerung-Tab haben Anzeige-Doppelung (kein Bug), keine
Aktions-Doppelung. AE-61-konform. B-14b-FU-4 bleibt Backlog (Strategie-Chat
nach 14d-Cowork-Begehung).

**Toolchain (lokal grün):** ruff check + format (154 Dateien), mypy strict (101
Source-Files), tsc --noEmit, eslint, pytest collection 548 Tests
(`test_sprint14d_override_visibility.py` 3 Tests skip ohne DATABASE_URL, §5.50).

**Backlog-Auflösung:**
- **B-14b-FU-5** (HeatingZoneRead.active_override) → **erledigt** (T3).
- **B-14b-FU-6** (SourceBadge-Wording) → **erledigt** (T9, Option A).
- **B-14b-FU-4** (Übersteuerung-Tab evaluieren) → **Doku-Eval erledigt** (T10,
  §J), UI-Folge offen (Strategie-Chat nach Cowork-Begehung).
- B-14b-FU-1/-2/-3, B-14c-FU-3 bleiben → 14e-Bündel-Vorschlag (Phase-0 §H).

**Out of Scope** (14e): B-14b-FU-1 (Zone-Ist-Temp), -FU-2 (Engine-Setpoint,
M), -FU-3 (Inline-Edit), B-14c-FU-3 (display_name + Migration, M).

**Pflicht-Stops genutzt:** T5 (Konsumenten-Drift — keine Drift gefunden,
weiterlaufen), T9 (Wording — Hotelier-Entscheid Option A), T10 (Eval-Folge —
Hotelier-Entscheid Option 1 Status Quo). PR-Stop + Tag-Stop ausstehend
(Cowork-Begehung + Live-Verify).

**Querverweise:** AE-58, AE-61, §5.63 (Type-Spiegel), §5.65 (UTC→Vienna im
UI), §5.66 (Multi-Badge-Slots — R-B Single-Zelle bewusst gewählt), §5.67
(Live-Verify pending), Phase-0-Brief `2026-05-28-sprint-14d-phase0-hygiene.md`.

## 2be. Sprint 15c fcnt-Reboot-Drift-Fix (2026-06-01/02, abgeschlossen)

**Ziel:** Vicki-Reboot (Batteriewechsel, Power-Cycle) wird nicht mehr als
Drehring-Override adoptiert (Fehlmodus M1 aus Sprint-15a-Diagnose).
Diskriminator: `current_fcnt < prior_fcnt` UND
`current_fcnt < FCNT_REBOOT_THRESHOLD (=10)`. prior_fcnt aus
`sensor_reading.fcnt` (Migration 0002, `ix_sensor_reading_device_time` —
keine neue Spalte, keine Migration). Reboot-Gate in
`device_adapter.handle_uplink_for_override` schreibt `event_log`-Eintrag
(Layer `REBOOT_RESYNC`) + Redis-Re-Sync-Flag `resync_pending:{dev_eui}`
(TTL 1 h). `engine_tasks._dispatch_downlinks_per_zone` konsumiert das
Flag atomar (GETDEL) und überschreibt Hysterese-Skip einmalig auf
`should_send=True` mit `reason=REBOOT_RESYNC`. AE-45-Pfad (echter
Drehring, fcnt monoton) bleibt unangetastet.

**Tag:** `v0.1.19f-fcnt-reboot-drift` (annotated, gesetzt 2026-06-02
NACH Live-Verify §5.67, zeigt auf develop-HEAD `45e7f6e` = PR #204
squash-Merge). Tag-Namens-Korrektur: ursprünglich `v0.1.20-fcnt-reboot-
drift` vorgeschlagen, dann revidiert — `v0.1.20-arc42-konsolidierung`
ist in `docs/SPRINT-PLAN.md:1328,1479` für Sprint 14b reserviert, daher
v0.1.19-Reihe um Suffix `f` fortgesetzt.

**Tasks:**
- T0 Read-only-Belege (A1 fcnt-Breite, A2 Call-Order, A3 einzige
  DEVICE-Override-Stelle) — alle drei Annahmen halten, kein Pflicht-Stop.
- T1 Pure-Funktion `is_reboot_frame` + `_get_prior_fcnt` + Konstante
  `FCNT_REBOOT_THRESHOLD` in `device_adapter.py`.
- T2 Reboot-Gate in `handle_uplink_for_override` (neue Parameter
  `dev_eui`, `current_fcnt`; off-pipeline Audit
  `_write_reboot_resync_event_log` mit synthetischer `evaluation_id`,
  AE-58 §9-Pattern; `mqtt_subscriber` reicht beide Werte durch).
- T3 Re-Sync-Consume in `engine_tasks._dispatch_downlinks_per_zone`
  (`flag_was_set` via atomarem GETDEL, Bypass nur wenn Hysterese
  geskippt hätte, sonst nur Cleanup).
- T4 Tests `tests/test_fcnt_reboot_drift.py`: 8 Pure-Funktion (Threshold-
  Boundary, Out-of-Order, Cold-Boot, Monotonie), 3 resync_flag-Helper,
  3 `_get_prior_fcnt`-DB, 3 Reboot-Gate-Integration, 3 Dispatch-Consume.
- T5 Doku: AE-63, CLAUDE.md §5.71, SESSION-START.md Hardware-Befunde,
  STATUS-Eintrag, B-15a-1 schließen.

**Schema-Änderungen (rein Python):** `CommandReason.REBOOT_RESYNC` +
`EventLogLayer.REBOOT_RESYNC`. Keine Migration (`event_log.reason`/
`layer` + `control_command.reason` sind im 0001-Schema als
`String(30)` ohne `CHECK` angelegt — §5.45 ist überstreng).

**Neues Modul:** `services/resync_flag.py` (Pattern analog
`engine_lock`: synchroner Redis-Client via
`asyncio.to_thread`-Wrapper, `mark_pending` + atomares `consume` via
`GETDEL`).

**Toolchain (lokal grün, 2026-06-01):**
- `ruff check`: 0 Befunde
- `ruff format --check`: 179 Files OK
- `mypy --strict src`: 0 issues in 103 Files
- pytest ohne DB (`ENVIRONMENT=test ALLOW_DEFAULT_SECRETS=1`):
  268 passed, 310 skipped, 0 fail
- pytest mit DB (TimescaleDB via `heizung-sonnblick-db-1` auf 5432):
  **577 passed, 1 xfailed**, neue Datei
  `test_fcnt_reboot_drift.py` 20/20 grün (§5.50 Lokal-DB-Verify-Pflicht
  erfüllt)

**Backlog-Auflösung:**
- **B-15a-1** (Reboot-Drift-Detection per fcnt-Reset) → **erledigt**.
- **B-15a-3** (AE-45-Block-Pfad lückenlos auditieren) bleibt offen
  als separater Sprint — Reboot-Pfad ist jetzt audit-sichtbar
  (`REBOOT_RESYNC`-Layer), aber der ursprüngliche Befund umfasst
  auch frame-innerhalb-Toleranz / im-Ack-Window-Blöcke ohne
  Audit-Spur. Out-of-Scope für 15c.

**Pflicht-Stops genutzt:** keiner. T0-Belege halten alle drei Annahmen,
keine Brief-Abweichung. Merge-Freigabe (PR #204 → develop squash am
2026-06-02) und Tag-Freigabe nach Live-Verify durch Strategie-Chat.

**Branch:** `feature/15c-fcnt-reboot-drift` (gemerged + remote-seitig
gelöscht via `gh pr merge --squash --delete-branch`).

**Live-Verify (heizung-test, 2026-06-02):** Deploy integer, kein
Migrationslauf (15c ist additiv: zwei Python-Enum-Werte, keine
Schema-Änderung). Engine-Beat fehlerfrei, 15c-Symbol (`is_reboot_frame`,
`REBOOT_RESYNC`-Enum-Wert, `services/resync_flag`) in API + Worker live
verifiziert. Cowork-Begehung 5/5 OK. **Hardware-Reboot-Trigger im Sommer
physisch nicht provozierbar** (AE-47-Sommerlücke — Δ-T zu klein für
Vicki-Hardware-Tests, analog zu Open-Window-Detection §5.27); der Pfad
ist durch 20 Tests inkl. Drehring-Regression abgedeckt — Live-Wirkung
des Reboot-Gates wird erst in der Heizperiode 2026/27 beobachtbar (per
Hotelier-Batteriewechsel oder Hotel-Strom-Ereignis).

**Querverweise:** AE-63 (Master), AE-45 (Drehring unverändert), AE-58 §9
(off-pipeline Audit), AE-09/AE-32 (Hysterese — der Bypass-Punkt),
CLAUDE.md §5.71 (Hardware-Lesson), §5.50 (Lokal-DB-Verify-Pflicht),
§5.44 (Per-Entity-Audit ohne PK-Migration — analoge Diät), §5.43
(Phase-0-grep-Belege), §5.45 (Enum-Length-Check, hier durch
nacktes-VARCHAR-Schema entschärft), §5.70 (PR-Body via `--body-file`).

## 2bf. Sprint 15b Batterie-Skala-Fix (2026-06-02, Code-Stand, PR pending)

**Ziel:** Vicki-Batterie-Prozent korrekt aus 2xAA-Alkaline-Geräte-
Spannung ableiten. Alte LiPo-Linear-Skala 3.0-4.2 V hat intakte 2xAA
als 0 % angezeigt (Cowork-Befund Sprint 15a). MClimate-Spec-Anker:
Betriebsspannung 2.7-3.6 VDC, Wechsel < 2.8 V, Power 2x AA Alkaline.

**Tag (vorgeschlagen):** `v0.1.19g-batterie-skala` (NACH Merge + Live-
Verify, §5.67). v0.1.20 bleibt arc42-Konsolidierung vorbehalten
(`docs/SPRINT-PLAN.md:1328`).

**Belege (T0):**
- **A1 hält:** `battery_voltage` aus
  `infra/chirpstack/codecs/mclimate-vicki.js:119-121` ist
  Geräte-Spannung (2xAA in Reihe), `V = 2.0 + nibble * 0.1`,
  Wertebereich 2.0-3.5 V in 0.1-V-Schritten. **Nicht** pro Zelle.
- **A2 hält:** kein realer Konsument auf `battery_percent` in
  `services/`/`tasks/` — `health_alerts.py` reagiert nur auf
  `offline_24h` / `implausible_readings_24h`. Skala-Fix verschiebt
  keine aktiv wirkende Alarm-Schwelle.
- **B0 (Block-Audit-Gap B-15a-3): Pflicht-Stop → Block B gestrichen.**
  Pre-a-Gate (`device_adapter.handle_uplink_for_override` Z.385-399)
  schreibt bereits `MANUAL_OVERRIDE_BLOCKED`-event_log
  (`reason=DEVICE_BLOCKED_ROOM_BLOCKED`) bei echtem Setpoint-Change in
  gesperrtem Raum (Sprint 12c). Frames ohne Setpoint-Change
  (Heartbeats / Toleranz / Ack-Window) erzeugen unter der Brief-
  Bedingung „nur echte Setpoint-Changes auditieren" bewusst keinen
  Audit-Eintrag. Q-D4-Befund („0 Rows trotz Block über Stunden") war
  eine Heartbeat-Phase ohne Drehring-Akte — by-design, kein Bug.
  Strategie-Chat hat Block B gestrichen, B-15a-3 in §6.4 mit
  Erkenntnis-Vermerk geschlossen.

**Tasks:**
- T1 Stützstellen-Kennlinie `BATTERY_CURVE_2XAA = ((2.70, 0), (2.80, 10),
  (2.90, 30), (3.00, 50), (3.20, 80), (3.50, 100))` als benannte
  Konstante in `services/mqtt_subscriber.py`. Lineare Interpolation
  zwischen Anchors, Decimal-Vergleich gegen Float-Drift an
  Wechsel-Schwelle, Clamps außerhalb der Endpunkte. **Live-kalibriert
  2026-06-02** gegen die 4 produktiven Vickis auf heizung-test (3×
  Codec-Sättigung 3.5 V, 1× 3.0 V — Zellbestückung einheitlich
  Alkaline). Initial-Anchors aus dem Brief (2.80 = 0, 3.00 = 100)
  waren ~0.4-0.5 V zu niedrig — schwächste Vicki hätte fälschlich
  100 % gezeigt; nach Verschiebung landet sie korrekt mittig (50 %).
- T2 Tests in `tests/test_mqtt_subscriber.py`-Sektion
  `_battery_pct_from_volts`: Anchor-Werte exakt, Clamps, alle 16
  Codec-Quantisierungen (2.0..3.5 V in 0.1-V-Schritten), Monotonie über
  das gesamte Codec-Raster, Sub-Quantisierungs-Interpolation,
  Schutz-Test gegen Anchor-Drift gegen AE-64, Live-Frame-Regression
  (3.5 V → 100 %, war vorher 42 % unter LiPo).
- T5 Doku: AE-64 (Master), CLAUDE.md §5.72 (Hardware-Lesson),
  SESSION-START.md Hardware-Befund-Verweise + AE-64-Verweis, STATUS
  §2bf + §6.4 B-15a-3 schließen + B-15b-1 NEU
  (`alert_battery_warn_percent` toter Schalter — Folge-Sprint).

**Schema-Änderungen:** keine. Keine Migration, keine neue Spalte.
Modul `services/mqtt_subscriber.py` ergänzt (Konstante + Helper-Logik
in Bestands-Funktion).

**Toolchain (lokal grün, 2026-06-02 nach Live-Kalibrierungs-Refactor):**
- `ruff check`: 0 Befunde
- `ruff format --check`: 179 Files OK
- `mypy --strict src`: 0 issues in 103 Files
- pytest mit DB (TimescaleDB-Container, §5.50 Lokal-DB-Verify-Pflicht):
  **603 passed, 1 xfailed** (26 Battery-Tests gegenüber 15c-Stand, inkl.
  4-Vicki-Live-Fixture als eigentlicher AE-64-Akzeptanztest).

**Backlog-Auflösung:**
- **B-15a-3** (AE-45-Block-Pfad lückenlos auditieren) → **by-design
  geschlossen** (B0-Code-Beleg, kein Fix). Erkenntnis-Vermerk in §6.4.
- **B-15b-1** NEU: `alert_battery_warn_percent` real verdrahten
  (toter Schalter in `global_config`-UI; kein Konsument in `services/`
  oder `tasks/`). Folge-Sprint mit Email-Versand-Scope-Entscheidung.

**Pflicht-Stops genutzt:** B0 hat einen Pflicht-Stop ausgelöst
(B-15a-3-Gap unter Brief-Bedingung nicht erreichbar) → Strategie-Chat-
Entscheid „Block B streichen". A0/A1/A2 alle bestätigt, kein weiterer
Stop. Stop vor PR-Merge + Stop vor Tag (Cowork-Begehung + Live-Verify
auf heizung-test) stehen aus.

**Branch:** `feature/15b-batterie-skala`.

**Querverweise:** AE-64 (Master), AE-53 (Health-Modell — derzeit ohne
Batterie-Trigger; B-15b-1 schließt die Lücke), AE-45 / AE-58
(unangetastet), CLAUDE.md §5.72 (Hardware-Lesson), §5.27 (Vicki-
Hardware-Realität, gleiche Lesson-Familie), §5.21 (Codec-Routing-
Pattern), §5.50 (Lokal-DB-Verify-Pflicht), §5.70 (PR-Body via
`--body-file`).

---

## 3. Offene Punkte (nicht blockierend, nicht kritisch)

### 3.1 Sicherheit / Hardening
- ✅ **PAT-Rotation erledigt** (Sprint 1, 2026-04-21): Neuer Classic PAT mit Scope `read:packages`, alter Token `claude-sprint2-push` widerrufen, Verfahren in RUNBOOK §6.1 dokumentiert.
- ✅ **UFW reaktiviert** (Sprint 3, 2026-04-22): Beide Server aktiv mit identischem Regelwerk, Port 22 per Entscheidung B öffentlich als Fallback.

### 3.2 Operations
- ✅ **`web`-Container-Healthcheck gefixt** (Sprint 2, 2026-04-22): dedizierter `/api/health`-Endpoint + `node -e "fetch(...)"`-Probe.
- ✅ **DNS-Umschaltung erledigt** (Sprint 4, 2026-04-22): Beide Server unter `*.hoteltec.at` mit Let's-Encrypt-Zertifikaten.

### 3.3 Cleanup
- ✅ Rescue-Leftovers entfernt (`fix-ssh.sh`, `fix2.sh`, `setup-ssh.sh`, `erich.pub`) — Sprint 0.3, Commit `89457a2`
- ✅ Cowork-Workspace auf lokales Repo `C:\Users\User\dev\heizung-sonnblick` umgestellt (Google-Drive-Sync-Problematik eliminiert)

---

## 4. Architektur-Stand

### Backend (FastAPI + PostgreSQL/TimescaleDB)
- Python 3.12, FastAPI >=0.110, SQLAlchemy >=2.0, Pydantic >=2.6, Alembic >=1.13
- Celery >=5.3 + Redis >=5.0 (Worker + Beat-Scheduler), aiomqtt >=2.3
- 14 Modelle: device, heating_zone, room, room_type, occupancy, rule_config, global_config, manual_setpoint_event, scenario, scenario_assignment, season, sensor_reading (Hypertable, ab Sprint 9.10 mit `open_window`), event_log (Hypertable), control_command
- Alembic-Migrationen 0001..0015: 0001_initial_domain_model, 0002_audit_event_log, 0003a/b (Hypertable + Index-Fix), 0004_room_eval_timestamps, 0008_manual_override (9.9), 0009_sensor_reading_open_window (9.10), 0010_device_firmware_version_attached_backplate (9.11x), 0011_config_audit (Sprint 9.13), 0012_summer_mode_scenario (Sprint 9.16), 0013_fix_summer_mode_encoding (Sprint 9.16a), 0014_auth_and_business_audit (Sprint 9.17), 0015_health_state (Sprint 11 T1: device.health_state + heating_zone.health_state als VARCHAR(16) mit CHECK-Constraint)
- Engine 6-Layer-Pipeline (`rules/engine.py`, AE-31): Layer 0 Sommermodus, Layer 1 Override, Layer 2 Belegung, Layer 3 Heizprofil, Layer 4 Fenster-Sicherheit + Inferred-Window (Sprint 9.10/9.11x/9.11y), Layer 5 Frostschutz. Sprint 9.10: Reading-Trigger feuert Re-Eval, Race-Condition durch Redis-SETNX-Lock (AE-40). Sprint 9.11x: Layer 4 erweitert um `device_detached`-Trigger (2-Frame-Hysterese auf `attached_backplate=false`). Sprint 9.11x.b: Vicki-Downlink-Helper-Architektur (AE-48) mit `send_raw_downlink` + typisierten Wrappern. Sprint 9.11y: passiver Inferred-Window-Logger (AE-47) off-pipeline ins event_log. Sprint 11 Erweiterungen:
  - **T3 (AE-51 §4.1):** Layer 4 `layer_window_open`-Query filtert auf `device.health_state = 'healthy'` (Mehrfach-Vicki-Zonen aggregieren OR ueber healthy Vickis). Zone-Aggregat-Helper `aggregate_zone_readings` als Pure-Function in `rules/aggregation.py` (Mittelwert + OR, ROUND_HALF_EVEN auf 0.1°C). `_load_room_context` selbst laedt heute KEINE Reading-Daten — Helper-Konsumenten kommen Sprint 12 (Schreib-Pfad) + Sprint 14 (UI-API).
  - **T4 (AE-54):** Top-Level-try/except in `_evaluate_room_async` (`tasks/engine_tasks.py`) als Sicherheitsgurt; Crash setzt alle HeatingZones des Raums auf `health_state='degraded'`. Per-Room-Isolation strukturell ueber Celery-Task-Boundary. Zone-granulare Iteration kommt Sprint 12.
  - **T5 (AE-53):** Periodischer Health-State-Compute-Task (5-min-Beat in `tasks/health_tasks.py`), 5-Phasen-Logik (Basis-State aus `last_uplink_age`, Outlier-Check via Zone-Median, Implausible-Counter aus Redis, Apply mit Idempotenz, Zone-State-Ableitung). Redis-Client extrahiert in `services/redis_client.py` (T5-prep). Implausible-Counter im MQTT-Subscriber (`_increment_implausible_counter` via `asyncio.to_thread`, Pipeline INCR+EXPIRE 86400).
  - **T6 (AE-53):** Health-Alert-Logger-Stub `emit_health_alert` in `services/health_alerts.py`, Aufruf als Phase 6 in `_compute_health_state_async`. Kein SMTP-Versand (Folge-Sprint nach Heizperiode 2026/27).
- ~38 Test-Dateien, 360 Test-Cases + 1 xfailed (Stand Sprint 11 abgeschlossen, 2026-05-18). Sprint-11-Tests: `test_engine_aggregate.py` (6), `test_engine_isolation.py` (4), `test_health_compute.py` (7), `test_health_alerts.py` (2), plus T1 +3 Migrations-Tests, T2 +4 Plausi-Tests, T5 +0 (Mock-Erweiterung der bestehenden T2-Tests).

**Begriffs-Mapping Code ↔ Strategie:** STATUS.md, Code und `docs/STRATEGIE-THERMOSTAT-ZUORDNUNG.md` verwenden teils unterschiedliche Begriffe.

| Code (DB-Modell) | Strategie-Sprache | Beispiel |
|------------------|-------------------|----------|
| `Room` | Unit / Hotel-Zimmer | Zimmer 101 |
| `HeatingZone` | Zone / Heizkreis | Schlafzimmer 101, Bad 101 |
| `Device` | Vicki / Thermostat | konkretes Geraet |

Sprint 11 hat die Code-Granularitaet Room-zentrisch belassen (`_evaluate_room_async` iteriert ueber Raeume, nicht ueber HeatingZones). HeatingZone-granulare Iteration kommt Sprint 12 (AE-51 §4.2). Bis dahin: HeatingZone wird im Code nur als JOIN-Filter genutzt und mit eigenem `health_state` versehen.

### Frontend (Next.js 14.2 App Router + Tailwind)
- Next.js 14.2.15, React 18.3.1, TypeScript 5.6.3 strict
- Tailwind 3.4.14, Design-Strategie 2.0.1 (Rosé `#DD3C71`, Roboto, Material Symbols Outlined)
- TanStack Query 5.100.5 für Server-State, recharts 3.8.1 für Charts
- UI-Komponenten unter `components/ui/`: button, confirm-dialog, alert-dialog, dialog, input, select (shadcn/ui-konform mit `@radix-ui`-Primitives, `components.json` + `lib/utils.ts` `cn`-Helper, migriert in Sprint 9.8d). Pattern-Komponenten unter `components/patterns/`: app-shell, engine-decision-panel, engine-window-indicator, heating-zone-list, manual-override-panel, occupancy-form, room-form, room-type-form, sensor-readings-chart.
- AppShell mit 200 px Sidebar
- Playwright E2E (`smoke.spec.ts`, `devices.spec.ts` unter `frontend/tests/e2e/`) — `sprint8.spec.ts` noch nicht erstellt, siehe Backlog

### Infrastruktur
- Docker Compose: 13 Services (api, web, db/timescaledb, redis, caddy, mosquitto, chirpstack, chirpstack-postgres, chirpstack-gateway-bridge, celery_worker, celery_beat) plus 2 Init-Sidecars (chirpstack-init, chirpstack-gateway-bridge-init)
- Compose-File: `infra/deploy/docker-compose.prod.yml` (zwingend `-f`)
- CI/CD: GitHub Actions baut Images bei Push auf `develop`, published nach GHCR
- Deploy: systemd-Timer auf Server zieht neue Images alle 5 Min (Pull-basiert, kein Push-Deploy)
- SSH-Zugang nur über Tailscale (Public-IP als Fallback via `id_ed25519_heizung`)

---

## 5. Routen-Übersicht

### Frontend-Pages

- `/` — Dashboard-Startseite
- `/zimmer` — Zimmerliste mit Filter
- `/zimmer/[id]` — Zimmer-Detail (Tabs: Stammdaten, Heizzonen, Geräte, Engine, Übersteuerung)
- `/raumtypen` — Raumtypen Master-Detail
- `/belegungen` — Belegungen-Liste + Form
- `/einstellungen/hotel` — Hotel-Stammdaten Singleton
- `/devices` — Geräteliste
- `/devices/[device_id]` — Geräte-Detail mit Reading-Chart
- `/healthz` — Frontend-Healthcheck (Caddy/Compose)

### Backend-API (`/api/v1/...`)

- `/api/v1/devices/*` — CRUD Devices, GET `{device_id}/sensor-readings`
- `/api/v1/devices/{device_id}/heating-zone` — PUT Assign Gerät → Heizzone, DELETE Detach (Sprint 9.11a, AE-43)
- `/api/v1/rooms/*` — CRUD Rooms, GET `{room_id}/engine-trace`
- `/api/v1/room-types/*` — CRUD Raumtypen
- `/api/v1/rooms/{room_id}/heating-zones` — CRUD Heating-Zones (nested unter Rooms)
- `/api/v1/occupancies/*` — CRUD Belegungen
- `/api/v1/global-config` — GET/PATCH Hotel-weite Settings
- `/api/v1/rooms/{room_id}/overrides` — GET/POST Manual-Override-Liste/Anlage (Sprint 9.9)
- `/api/v1/overrides/{override_id}` — DELETE Manual-Override revoken (Sprint 9.9)
- `/healthz` — Backend-Healthcheck

---

## 5a. Wichtige Dokumente im Repo

- `docs/STRATEGIE.md` — Gesamtkonzept, Architektur, Roadmap
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log
- `docs/Design-Strategie-2.0.1.docx` — UI-Richtlinie (verbindlich)
- `docs/RUNBOOK.md` — Troubleshooting, Rescue-Mode, SSH-Fehlerbilder, UFW-Hardening, GHCR-PAT-Rotation

---

## 6. Backlog

Sortierung: Priorität (🔴 blockierend, 🟡 wichtig, 🟢 nice-to-have),
innerhalb der Priorität nach Aufwand.

### 6.1 — Refresh-Aufgaben (BR-1 bis BR-15)

| ID | Inhalt | Sprint |
|---|---|---|
| BR-1 🟢 | Frostschutz pro Raumtyp — zurückgestellt, siehe AE-42 |  |
| BR-2 🔴 | Geräte-Pairing-UI + Sidebar-Migration | 9.13 |
| BR-3 🟡 | Globale Temperaturen+Zeiten-UI | 9.14 |
| BR-4 🟡 | Profile-CRUD + UI | 9.15 |
| BR-5 🟡 | Szenarien-Aktivierung CRUD + UI | 9.16 |
| BR-6 🟡 | Saison-CRUD + UI | 9.16 |
| BR-7 🔴 | NextAuth + User-UI | 9.17 |
| BR-8 🟡 | Dashboard mit 6 KPI-Cards | 9.18 |
| BR-9 🟢 | Temperaturverlauf-Analytics | 9.19 |
| BR-10 🟢 | API-Keys + Webhooks | 9.20 |
| BR-11 🟢 | Gateway-Status-UI | 9.21 |
| BR-12 🟢 | KI-Layer-Hülle in Engine | nach Go-Live |
| BR-13 🔴 | PMS-Casablanca-Connector | 11 |
| BR-14 🟡 | Wetterdaten-Service aktiv | 13 |
| BR-15 🔴 | Backup + Production-Migration | 12 |
| BR-16 🔴 | Backend-Window-Detection-Eigenlogik (Layer 4 Erweiterung, aktiver Trigger nach 2-Wochen-Beobachtung) | 9.11y + späterer Re-Eval |
| B-9.11a-4 🔴 | Basic-Auth-Pass rotieren vor Production-Migration | 12 |
| B-9.11x.b-1 🟢 | Decimal-Rundungs-Charakteristik in RUNBOOK §10e dokumentiert (in 9.11x.b T7) | erledigt mit 9.11x.b |

### 6.2 — Hygiene-Aufgaben (B-9.10*)

Werden im Hygiene-Sprint 10 abgearbeitet.

| ID | Inhalt | Priorität |
|---|---|---|
| B-9.10-1 | Fenster-Indikator in /zimmer-Liste | 🟡 |
| B-9.10-2 | Fehler-Übersicht für Devices (in BR-2 enthalten) | erledigt |
| B-9.10-6 | psycopg2-Failures | ✅ erledigt 2026-05-15 (Sprint 10 T1, PR Sprint-10) — `psycopg2-binary` als dev-extra in `backend/pyproject.toml`. |
| B-9.10c-1 | ChirpStack-Codec-Bootstrap-Skript | 🟡 |
| B-9.10c-2 | Codec-Re-Paste auf heizung-main bei Production-Migration | 🔴 (in 12) |
| B-9.10d-1 | detail-Konvention vereinheitlichen | 🟡 |
| B-9.10d-2 | mypy-Vorlast 71 Errors in tests/ | ✅ erledigt 2026-05-15 (Sprint 10 T4, PR Sprint-10). Stand bei Sprint-Start war bereits 32 Errors (9.17a/b/c hatte zwischenzeitlich reduziert). Final: 0 strict-Errors in `tests/`. |
| B-9.10d-3 | Type-Inkonsistenz Engine `int` vs. EventLog `Decimal` | 🟡 |
| B-9.10d-5 | engine_tasks DB-Session per Dependency-Injection | 🟢 |
| B-9.10d-6 | Pre-Push-Hook für `ruff format --check` | ✅ erledigt 2026-05-15 (Sprint 10 T8, PR Sprint-10). `.pre-commit-config.yaml` im Repo-Root + RUNBOOK §10f Setup-Anleitung. ruff-pre-commit `v0.15.12` gepinnt. |
| B-9.11-1 | Engine-Decision-Panel: `setpoint_in` zusätzlich zu `setpoint_out` anzeigen | 🟡 |
| B-9.11-2 | „Vorherige Evaluationen" zeigt `base_target`-Reason statt finalem Layer-Reason | 🟡 |
| B-9.11-3 | Layer 3 manual_override Sub-Reasons (`manual_frontend` / `manual_device`) im Trace | 🟡 |
| B-9.11-4 | celery_beat-Healthcheck (akzeptierter Drift ohne Engine-Auswirkung) — Dockerfile-HEALTHCHECK greift Port 8000, beat hat keinen uvicorn; Compose-Override fehlt. Per Diagnose Sprint 10 T3 (2026-05-15): kein Service hat celery_beat in `depends_on: condition: service_healthy`, beat schedulet weiterhin verlässlich (60-s-Tick im Log), Engine-Eval läuft in celery_worker (healthy). Akzeptiert per CLAUDE.md §5.32. Fix nur falls Engine-Latenz oder Status-Dashboard-Wunsch. Master-ID für B-9.11x-3 + B-9.17-3. | 🟢 akzeptiert |
| B-9.11x  | Sprint 9.11x — Vicki-001 `open_window`-Hardware-Diagnose | 🔴 |
| B-9.11x-1 | `psycopg2-binary` in `pyproject.toml [dev]`-extras aufnehmen ODER `test_manual_override_model.py` + `test_migrations_roundtrip.py` auf asyncpg umstellen | ✅ erledigt 2026-05-15 (Sprint 10 T1, PR Sprint-10). Pyproject-Variante gewählt, asyncpg-Umstellung als zu invasiv aus dem Sprint-Scope ausgeschlossen. |
| B-9.11x-2 | heizung-main-Sanierung: alter Sprint-9.8a-Stand auf aktuellen develop-Stand bringen, `safe.directory`-Block fixen (CLAUDE.md §5.7), `:main`-Image neu bauen, Migrations 0005-0010 anwenden. Eigener Sprint, vor v0.2.0. | 🔴 |
| B-9.11x-3 | celery_beat unhealthy auf heizung-test | ✅ Duplikat von B-9.11-4 (zusammengeführt Sprint 10 T3, 2026-05-15). |
| B-9.11x-4 | Status-Dashboard: zentrale Sicht auf Pull-Timer + Container-Health + letzte Engine-Eval pro Raum (heizung-test + heizung-main), aktuell verteilt über `journalctl`/`docker ps`/SQL — 9.13+ | 🟡 |
| B-9.11x-5 | Quick-Win: Zimmer-Spalte in Geräte-Liste (`/devices`) und Geräte-Detailseite (`/devices/[id]`). Aktuelle Tabelle zeigt Bezeichnung, DevEUI, Hersteller/Modell, Status, Zuletzt-gesehen — aber nicht die Heizzonen-/Zimmer-Zuordnung. Read-Only-Erweiterung, kein neuer Endpoint nötig (Device-API liefert `heating_zone_id`, Heating-Zone-API liefert `room_id`). 30-60 Min, vor Sprint 9.13. Anlass: Hotelier-Feedback 2026-05-10 | 🟡 |
| B-9.11x.b-1 | JS-Runtime-Codec-Spiegel-Test (`py_mini_racer` / `subprocess+node`) statt hardcoded Vendor-Bytes. Würde auch `decodeUplink` mit-schützen (Bug B-9.11x.b-5 wäre damit gefangen). Hygiene-Sprint | 🟡 |
| B-9.11x.b-2 | 0x06-Fallback-Encoder für FW < 4.2 (alte 1.0 °C-Variante, Vendor-Doku §01). Bulk-Skript skipped FW<4.2-Devices aktuell mit Hinweis auf dieses Item | 🟡 |
| B-9.11x.b-3 | `_consume_loop` Trio-Handler in `post_uplink_hook` konsolidieren (FW + OW-Status + Override-Detection) — DRY für die zwei Aufrufstellen | 🟢 |
| B-9.11x.b-4 | Dockerfile-COPY-Konvention prüfen, dass zukünftige neue Top-Level-Verzeichnisse standardmäßig mit ins Image gehen, oder ein conftest existiert das eine Inventur macht. Anlass: `scripts/` fehlte im Image (PR #124) | 🟡 |
| B-9.11x.b-5 | 0x04-Decoder Byte-Offset-Bug in `mclimate-vicki.js`. Vendor-Doku-Spec war ungenau (Bytes statt Nibbles + Vicki packt Reply + Keep-alive im selben Uplink). Fix in Sprint 9.11x.c via 3-Byte-Nibble-Decoder + Frame-Merge mit Reply-Priorität. Live-Verify: alle 4 Vickis zeigen `firmware_version=4.4` | ✅ erledigt 2026-05-11 (PR #126) |
| B-9.11x.b-6 | Subscriber-Log "firmware_version persistiert" feuert nicht. Fix in Sprint 9.11x.c: `logger.info` AUSSERHALB des `async-with`-Blocks + `rowcount`-Diagnose. Live-Verify: 4× `firmware_version persistiert ... fw=4.4 rows=1` im `docker logs` (08:07–08:12 UTC) | ✅ erledigt 2026-05-11 (PR #126) |
| B-9.11y-1 | Inferred-Window-Logger Live-Verify in Heizperiode mit echtem Fenster-Öffnen ohne Drehrad-Hantieren (Kältepack-Test 2026-05-11 lieferte parallel AE-45-Drehrad-Sprünge, die den Pre-Window-Baseline-Block ausgelöst haben — Detector blieb Spec-konform inaktiv). Test-Szenario: Vicki ungestört lassen, Fenster physikalisch öffnen, Δ-T ≥ 0.5 °C im Lookback erwarten → Trigger im event_log | 🟡 (in Heizperiode) |
| B-9.11y-2 | `manual_override id=12` (20→26, source=device, 2026-05-11 09:57 UTC) und `id=13` (26→29, 2026-05-11 10:28 UTC) auf heizung-test manuell revoken vor Sprint 9.12. UPDATE 2 Zeilen ausgefuehrt 2026-05-11 11:06:48 UTC via Claude Code SSH, `revoked_reason='Sprint-9.11y-Closeout-Cleanup, blocked-after-Kaeltepack-Test'` | ✅ erledigt 2026-05-11 |
| B-9.11a-1 | Audit aller `docs/*.md` auf Null-Byte-Pollution + Trailing-Garbage | 🟡 |
| B-9.11a-2 | Live-Verify Vicki-002/003/004 Zuweisung nach Merge | ✅ erledigt 2026-05-09 |
| B-9.13a-1 | Local-Dev-Onboarding-Checkliste (alte API-Image-Dependencies, Docker-Web-Container vs. `npm run dev` Port-Kollision auf 3000, Next.js Rewrite-Default `http://api:8000` ohne `API_PROXY_TARGET`-Override). Anlass: Cowork-Visual-Review Sprint 9.13a — drei Setup-Hindernisse vor erstem Screenshot, alle nicht-Sprint-bezogen aber dokumentationswürdig. Vorschlag: Block in `RUNBOOK.md` oder `frontend/README.md` | 🟡 |
| B-9.13a-2 | Inline-Edit-Input mit aktuellem Label vorbefüllen (statt leer mit Placeholder) — UX-Verfeinerung. Heutige Implementierung folgt Wizard-Step-4-Konvention („leer lassen, um zu behalten"), wirkt aber auf Listen-Inline-Edit ungewohnt. Cowork-Befund Sprint 9.13a §2/05 | ✅ erledigt 2026-05-12 (HF-9.13a-1). Lösung via beibehaltenes State-Init `useState(d.label ?? "")` plus `autoComplete="off"`-Hardening am Input. User sieht beim Edit-Click den aktuellen Label-Wert und kann editieren statt neu zu tippen; `autoComplete="off"` schließt Browser-Autofill als B-LT-1-Hypothese (b) aus. |
| B-LT-1 | Inline-Label-Edit Render-Verkettung in /devices-Tabelle (z.B. „Vicki-002Vicki-002-Live-Test-2026-05-11"). Cowork-Live-Test 2026-05-11 (`cowork-output/sprint9-13a-live-test/BEFUND.md` §6). **Status nicht-reproducible 2026-05-12 (HF-9.13a-1):** Frontend-Render-Code verifiziert — keine Konkatenation, kein `name`-Feld im Schema, drei Render-Stellen (LabelCell `/devices`, Detail-Header, DevicesInRoom) alle defensive `??`-Ketten, lokal mit Playwright nicht reproducierbar. Vier offene Hypothesen: (a) RSC-503-Race aus BEFUND §5, (b) Browser-Autocomplete im autoFocus-Input, (c) TanStack-Query Cache-Race, (d) visueller Wahrnehmungsfehler. Hardening via HF-9.13a-1 (`autoComplete="off"`) schließt (b) aus. Bei nächstem Live-Auftreten sofort DevTools öffnen und Outer-HTML der Zelle zitieren plus Network-Tab auf RSC-503-Errors prüfen. **Update 2026-05-12 (Bündel B Live-Test):** nach autoComplete-Hardening erneut keine Wiederholung beobachtet (`cowork-output/sprint9-13b-live-test/BEFUND.md`) — Status bleibt nicht-reproducible. | 🟢 nicht-reproducible |
| B-LT-2 | Engine-Layer-4 sieht nach UI-Re-Attach weiterhin detached, klemmt Setpoint auf 10 °C bis nächster 60-s-Beat-Tick. Cowork-Live-Test 2026-05-11 (`cowork-output/sprint9-13a-live-test/BEFUND.md` §3+§6). **Phase-0-Diagnose 2026-05-12:** Wurzel ist nicht ein Cache-Bug (es gibt keinen Cache — Layer-4 berechnet `detached_devices` jedes Mal frisch aus `sensor_reading`-Hypertable), sondern fehlender `evaluate_room.delay`-Trigger im PUT/DELETE-Handler von `/api/v1/devices/{id}/heating-zone`. UI-Aktion war damit für die Engine unsichtbar bis zum nächsten Beat. | ✅ erledigt 2026-05-12 (HF-9.13a-2, PR #135), live-verifiziert 2026-05-12 durch Cowork auf heizung-test (Tick-Latenz 5–6 Sek nach API-Call beobachtet, AE-47-Semantik hält wie geplant, BEFUND in `cowork-output/sprint9-13a-hf2-live-test/BEFUND.md`). PUT- und DELETE-Handler triggern nach Commit `evaluate_room.delay(zone.room_id)`. AE-47 Hardware-First bleibt unverändert: Engine sieht weiter `sensor_reading.attached_backplate`-Historie, aber wenigstens auf neuestem Stand. |
| B-LT-2-followup-1 | Hardware-Status-Badge + UI-Banner im Frontend: „Wartet auf Hardware-Bestätigung" / „Aktiv" / „Keine Bestätigung" plus Banner „Letzter Frame meldet detached — Backplate-Recovery erforderlich" wenn Layer 4 nach Re-Attach noch detached zeigt. Basierend auf `sensor_reading.attached_backplate`-Historie der letzten 30 Min (Datenquelle existiert bereits). Frontend-Komponente und ggf. neuer API-Endpoint `/api/v1/devices/{id}/hardware-status` nötig. Macht AE-47 Hardware-First-Latenz nach Re-Attach für den Hotelier transparent — Cowork-Live-Test HF-9.13a-2 hat genau diesen Fall reproduziert (Vicki-002 nach Re-Attach klemmt auf 10 °C bis Hardware `attachedBackplate=true` meldet). Kommt in Bündel B oder eigener Sprint. | ✅ erledigt 2026-05-12 (Sprint 9.13c, PR #139 + PR #140). Backend-Endpoint `GET /api/v1/devices/{id}/hardware-status` (30-Min-Fenster auf `sensor_reading.attached_backplate`, 6 DB-Tests). Frontend `HardwareStatusBadge` (compact/detailed) integriert an drei Stellen: `/devices`-Liste (neue Spalten-Semantik nach Wording-Fix #140: „Eingerichtet" mit ja/nein + `check_circle`/`cancel`-Icons für `is_active`, „Status" für Hardware-Badge mit `last_seen`), `/devices/[id]`-Detail-Header (Label „Status" oben, „Eingerichtet: ja/nein" als kleine Zeile darunter), `/zimmer/[id]`-Geräte-Tab (compact-Badge neben Bezeichnung). 30-Min-Konstante `WINDOW_STALE_THRESHOLD_MIN` nach `rules/constants.py` extrahiert, geteilte Quelle mit Layer 4. Live-verifiziert 2026-05-12 durch Cowork auf heizung-test (Vicki-002 zeigt „Status: Inaktiv, noch nie" + „Eingerichtet: ja" — exakt der UX-Use-Case, BEFUND in `cowork-output/sprint9-13c-live-test/BEFUND.md`). Separater UI-Banner-Aspekt entfällt — der Badge zeigt den Hardware-Status klar genug, zusätzlicher Banner wäre Doppelung. |
| B-9.13a-3 | Frontend-Cache-Reset-Pattern dokumentieren (Playwright `webServer.reuseExistingServer` + `.next/`-Stale-Cache). Anlass: Sprint 9.13a TA5-Test-Lauf — alter dev-Server auf Port 3000 zeigte Pre-Branch-Code, Tests rot. Fix: `Stop-Process node` + `Remove-Item .next` + neuer Test-Run. Frontend-Equivalent zu CLAUDE.md §5.11 (`docker compose pull` ist nicht beweisend). Vorschlag: neue Lesson §5.29 in CLAUDE.md | 🟡 |
| B-9.13a-hf2-1 | `/api/v1/_meta`-Endpoint für Server-Side-Build-SHA-Verifikation. Cowork hatte im Live-Test 2026-05-12 keinen zuverlässigen Weg, den Deploy-Stand direkt zu prüfen — musste Build-Stand indirekt über das beobachtbare Engine-Tick-Verhalten verifizieren (`cowork-output/sprint9-13a-hf2-live-test/BEFUND.md` §0). Endpoint-Vorschlag: `{"sha": "<git-sha>", "build_ts": "<iso>", "version": "<app>"}`. Hilft bei künftigen Live-Tests und Deploy-Verifikation. | 🟢 |
| B-9.13a-hf2-2 | Engine-Tick-Trigger-Latenz-SLA dokumentieren. Beobachtet im Live-Test HF-9.13a-2 auf heizung-test 2026-05-12: 5–6 Sek von API-Call bis sichtbarem Engine-Tick (Celery-Queue-Pickup + DB-Commit + Engine-Pipeline). Doku-Eintrag in CLAUDE.md §6 oder STATUS.md §5 als verbindliche Erwartung („innerhalb 5–10 Sek nach API-Call"). Bei Abweichung > 30 Sek ist Performance-Investigation nötig (Worker-Backpressure, Redis-Lock-Hold-Time, DB-Connection-Pool). | 🟢 |
| B-9.13b-1 | Material-Symbols-Font-Race auf Frontend. | ✅ erledigt 2026-05-15 durch PR #154 (Sprint-10-Prep Caddy-Hotfix). Browser-Test nach Sprint-10-T6-Rotation bestaetigt: Sidebar zeigt Glyphen sauber, kein Code-Name-Fallback. Cache-Busting-Aspekt (Hard-Reload-Pflicht nach Pull-Deploy aus Cowork-Live-Test 2026-05-12) ist davon unberuehrt und bleibt als separates Frontend-Polish-Item offen → siehe B-10-5 (neu). |
| B-10-5 🟢 | **Cache-Busting nach Frontend-Deploys.** Hotelier braucht nach Pull-Deploy einen Hard-Reload, um neue UI zu sehen (Live-Test 2026-05-12, `cowork-output/sprint9-13b-live-test/BEFUND.md`). Loesungs-Optionen: Service-Worker mit Skip-Waiting, Build-Hash in HTML-Meta, Cache-Control-Header fuer `index.html` auf `no-cache`. Nicht produktionskritisch, eigener Frontend-Polish-Sprint. Vorher in B-9.13b-1 mit-gefuehrt; bei Sprint-10-Konsolidierung ausgelagert, weil Material-Symbols-Race und Cache-Busting separate Themen sind. |
| B-9.13c-1 | Skalierungs-Limit Hardware-Status-Badge: 1 Refetch alle 30 s pro Badge bedeutet bei N Devices in `/devices`-Liste N parallele Calls/30 s. Heute 4 Vickis irrelevant, bei 100+ Devices Optimierung über Batch-Endpoint `/api/v1/devices/hardware-status?ids=...` oder zentralen Polling-Hook (eine Query → Map deviceId → Status). Anlass: Sprint 9.13c Pre-Push-Beobachtung — Polling-Konstante hardcoded auf 30 s pro Hook-Instanz. | 🟢 |
| B-9.13c-2 | `cancel`-Icon für „Eingerichtet: nein" nicht visuell demonstrierbar mangels Test-Daten (alle Vickis auf heizung-test sind `is_active=true`). Schema ist implementiert, Code-Pfad funktioniert per Test-Mock. Bei nächstem geeigneten Vicki-Test-Pairing oder Deaktivierungs-Vorgang: Screenshot des „Eingerichtet: nein"-Zustands machen, als BEFUND-Anhang sichern. Anlass: Sprint 9.13c Cowork-Live-Test 2026-05-12. | 🟢 |
| B-9.13c-3 | Wording-Audit auf weiteren Pages (Pairing-Wizard, Belegungen, Raumtypen-Detail, sonstige `aktiv`/`inaktiv`-Stellen). Cowork hat im Live-Test 9.13c noch nicht alle Pages durchgeklickt — der Wording-Fix #140 wurde gezielt für `/devices`-Liste und `/devices/[id]`-Detail-Header gebaut. Andere Stellen, die `is_active`/Activity-Status anzeigen, könnten mit derselben „Eingerichtet"-Semantik konsistenter werden. Bundling mit anderen Polish-Items möglich. | 🟢 |
| B-9.16-1 | Sprint 9.16b — weitere System-Szenarien (Tagabsenkung, Wartung, Schließzeit, Renovierung) plus volle Szenario-Auflösung in Engine Layer 2 (ROOM > ROOM_TYPE > GLOBAL Hierarchie analog `rule_config`). Plus Saison-UI auf `/einstellungen/saison` mit Tag-Monat-Range und saisonaler `rule_config` über `season_id`-FK (SPRINT-PLAN.md 9.16 T3-T5). Bewusst aufgeschoben „nach erstem Winter mit Live-Daten" (Brief 9.16 AE-3) — heute fehlt der Erfahrungsschatz, welche Szenarien realer Hotelier-Bedarf sind. | 🟢 (in 9.16b) |
| B-9.16-2 | Migration `0012_summer_mode_scenario` manuell Auf-Ab-Auf gegen Live-Postgres verifiziert, kein automatisierter Roundtrip-Test in CI. | ✅ erledigt 2026-05-15 (Sprint 10 T2, PR Sprint-10). Drei neue Tests in `test_migrations_roundtrip.py`: `test_migration_0012_atomar_auf_ab_auf`, `test_migration_0012_preserves_summer_mode_active`, `test_migration_0012_preserves_inactive_state`. Plus `env.py`-Fix (TEST_DATABASE_URL hat Vorrang vor `settings.database_url`). CI-Workflow legt `heizung_migration_test`-DB an. |
| B-9.16-3 🟢 (info) | Doppel-GET auf `/api/v1/scenarios` im Dev-Mode (vermutlich React-StrictMode-Artefakt, analog B-9.14-5). Nicht produktionskritisch, beobachtet im Cowork-Visual-Review Sprint 9.16. |
| B-9.16-4 🟢 (info) | axe-DevTools-Lighthouse-A11y-Score nicht formal verifiziert für `/szenarien` (Cowork-Tooling-Limitation, kein funktionaler Befund). Stichprobe via Tab-Reihenfolge + aria-label hat keinen Verstoss ergeben. |
| B-9.16-5 🟡 | Sprint 9.16a Hotfix-Anlass: Audit-Befund zeigt deutsche Umlaute in Backend-Docstrings (`engine.py`, `engine_tasks.py`, `room_types.py`, `global_config.py`, `manual_setpoint_event.py`, Migrations 0003b/0004/0011) durchgehend als ASCII-Replacement (`ue`/`ae`/`oe`) gepflegt — Repo-Konvention, nicht User-sichtbar. Einheitlichkeit-Audit oder ASCII-only-Policy für Backend-Docstrings in einem Hygiene-Sprint klären; bis dahin: User-sichtbare DB-Strings müssen UTF-8 sein (CLAUDE.md-Lesson kandidat). |
| B-9.17-1 🟢 (info) | Self-Service-Passwort-Reset via E-Mail. Heute kann nur Admin Passwoerter zuruecksetzen (AE-50 AE-7). Sobald E-Mail-Infrastruktur entschieden ist (SMTP-Setup oder Provider), eigener Sprint: `/auth/forgot-password` → Token → `/auth/reset-password?token=…`. Bis dahin: Admin-Reset reicht fuer den Single-Mandant-Betrieb. |
| B-9.17-2 🟢 (info) | Audit-UI im Frontend fuer `config_audit` und `business_audit`. Heute sind beide Tabellen reine Backend-Tabellen — kein UI-Endpoint, keine Anzeige. Separater Sprint nach erstem Hotelier-Feedback („was passierte am Mittwoch um 14:00?"). Spaeter ggf. mit Filter nach `user_id` / `target_type` / Zeitraum. |
| B-9.17-3 | `celery_beat`-Container unhealthy seit mehreren Deploy-Cycles. Pre-existing, NICHT 9.17-bezogen. | ✅ Duplikat von B-9.11-4 (zusammengeführt Sprint 10 T3, 2026-05-15). |
| B-9.17-4 🔴 **Cutover-Blocker** | GET-Endpoints in Routern `devices`, `rooms`, `heating_zones`, `room_types`, `occupancies` sind ungeschuetzt. Sprint-9.17-Brief T6 hatte nur mutierende Endpoints spezifiziert — Brief-Luecke, nicht Implementierungs-Bug. ~9 GET-Endpoints betroffen. **MUSS in 9.17a behoben werden vor `AUTH_ENABLED=true`** (Tag `v0.1.14-auth` haengt daran). |
| B-9.17-5 🟡 | Frontend-Wording bei 429 (slowapi Rate-Limit) und 503 ist identisch zu 401 („E-Mail oder Passwort falsch"). Differenzieren auf „Zu viele Versuche, bitte 60 Sekunden warten." bzw. eine 503-spezifische Meldung. Login-Page + Forced-Change-Page. |
| B-9.17-6 🟡 | `/einstellungen/saison`-Stub fehlt Verweis auf `/szenarien`. Beschreibung erweitern um Sommermodus-Hinweis: „Sommermodus-Soforttoggle bereits unter Szenarien verfuegbar." |
| B-9.17-7 🟡 | Mojibake in Forced-Change-Page-Fehlermeldung. „Die beiden Passwoerter stimmen nicht ueberein" sollte „Passwoerter" → „Passwörter" und „ueberein" → „überein" sein. Analog zu B-9.16-1 (Sommermodus-Seed Sprint 9.16a). |
| B-9.17-8 🟡 | Password-Felder brauchen Sichtbarkeits-Toggle (Auge-Icon). Bei 12-Zeichen-Mindestlaenge zu fehleranfaellig ohne visuelles Feedback. Drei Stellen: Login-Page, Forced-Change-Page, Admin-Reset-Dialog. |
| B-9.17-9 🟡 | Forced-Change-Page kann nicht zwischen „Aktuelles Passwort falsch" und „Neue Passwoerter stimmen nicht ueberein" unterscheiden — beides generischer roter Text unter dem Formular. UX-Konfusion bei Mehrfachfehler. |
| B-9.17-10 🔴 **Cutover-Blocker** | Bei `AUTH_ENABLED=false` liefert `get_current_user` den System-User-Fallback (verwaltung, id=1) unabhaengig vom tatsaechlich eingeloggten User. `/change-password` vergleicht `current_password` gegen System-User-Hash statt gegen echten User-Hash. Konsequenz: Forced-Change unter `AUTH_ENABLED=false` unmoeglich — 400 „Aktuelles Passwort falsch" trotz korrekter Eingabe. **Fix:** User-Identitaets-kritische Endpoints (`/change-password`, `/auth/me` als User-spezifisch) muessen bei `AUTH_ENABLED=false` einen 503/409 mit klarer Meldung liefern statt das System-User-Fallback-Verhalten zu nutzen. |
| B-9.17-S1 | Secret-Rotation auf heizung-test (`POSTGRES_PASSWORD` + `SECRET_KEY` waehrend Cutover-Diagnose 2026-05-14 im Strategie-Chat exposed). | ✅ erledigt 2026-05-15 (Sprint 10 T6, PR Sprint-10). Beide Werte rotiert via `/tmp/rotate-secrets.sh` (openssl rand -hex 32, ALTER USER via STDIN-Heredoc, sed-Inplace fuer POSTGRES_PASSWORD + SECRET_KEY + DATABASE_URL-embed). Backup `.env.bak-pre-rotation-20260515T135700Z` auf Server fuer 7 Tage. Verify: Browser-Login `kaprun@hotel-sonnblick.at` mit neuem JWT-Cookie funktional, /zimmer laedt Daten, Sidebar zeigt Glyphen. Exposed-Werte aus Strategie-Chat 2026-05-14 invalidiert. |
| B-9.17b-4 🟠 (vor Heizperiode) | **Vicki-002 und Vicki-004 senden seit Pairing keinen Heartbeat.** Status "Inaktiv, noch nie" in Geräte-Detail-Page. Vicki-003 als Kontrollgruppe (gepaired, aktiv, ohne Backplate) sendet sauber. Hypothesen: (1) Pairing in ChirpStack unvollständig, (2) Codec-Routing-Bug analog §5.21, (3) Firmware-Backplate-Flag-Verhalten. Vor Produktiv-Einsatz an Heizkörpern klären — sonst keine Heizungssteuerung in diesen Zimmern. |
| B-9.17b-3 🟡 | **Batterie-Wert-Plausibilität Vicki-001/-002/-003/-004.** Werte zeigen 33-42% trotz neuer Batterien, auf Vicki-001 seit Tagen konstant 33% ohne Variabilität. Hypothesen: (1) Codec-Decoder-Bug (Batterie-Byte-Position/Skalierung falsch), (2) veralteter Wert wird gehalten weil nicht jeder Status-Report Batterie sendet. Querverweise §5.21, §5.27. Diagnose-Sprint nach 9.17b-4-Klärung. |
| B-9.17b-2 | **Sidebar-Sichtbarkeit auf /login.** | ✅ erledigt 2026-05-15 (Sprint 10 T5, PR Sprint-10). AppShell prüft `usePathname()`, blendet Sidebar auf `/login` + `/auth/*` aus. Playwright-Test in `sidebar.spec.ts` deckt Regression ab; lokal via `npm run dev` + curl-HTML-Snapshot verifiziert (0 Hauptnavigation-Marker auf Pre-Login-Routen, 1 auf `/devices`). |
| B-9.17b-5 🟢 | **Klarstellung Vicki-Hardware-Stand heizung-test.** heizung-test hat aktuell: 1 produktiv montierte Vicki (-001 in Zimmer 101), 1 Test-Gerät funktechnisch aktiv aber unmontiert (-003, früherer Verifikations-Doppelgänger zu -001), 2 nie produktiv eingebuchte Geräte (-002, -004). Sommermodus-Beobachtungsphase 14.5.-15.5. basiert auf 1 Gerät, nicht auf 4. Diese Klarstellung in STATUS-Doku spätestens beim ersten heizung-main-Touch nachziehen, damit später keine Drift entsteht. |
| B-9.17b-6 🟢 (info) | **Cookie-Namen-Konsistenz.** Frontend zeigt `heizung_session`-Cookie, Backend setzt es ebenfalls als `heizung_session`. An einer Stelle in Doku oder Code-Kommentaren tauchte `access_token` als generischer Name auf — bei nächstem Auth-Modul-Touch konsistent prüfen. |
| B-9.17b-1 🟢 (info, Sprint 11+) | **Server-side JWT-Blacklisting bei Logout.** Heute: Browser-Cookie-Cleanup, gestohlener JWT-Token bleibt 12h gültig. Akzeptabel für Single-Mandant-Hotelbetrieb. Bei Multi-Mandant-Schritt (Sprint 11+) nötig. Realisierungs-Optionen: Redis-Blacklist mit JWT-Jti, oder Datenbank-Token-Tabelle mit Revoke-Spalte. Querverweis CLAUDE.md §5.31. |
| B-10-2 ✅ | **Caddy-Basic-Auth-Konflikt mit Backend-Auth.** Nach Sprint-9.17a/b-Cutover liefen zwei parallele Auth-Schichten — Site-weite Caddy-Basic-Auth (Sprint 8a K-1) + FastAPI-JWT-Cookie (AE-50). Browser fragte mehrfach Basic-Auth pro Session, Session instabil, Material-Symbols-Font-Race (siehe B-9.13b-1). Sprint-10-Prep-Hotfix 2026-05-15: Caddy-Basic-Auth nur noch für `/openapi.json /docs /docs/* /redoc /redoc/*` (Reconnaissance-Schutz, FastAPI hat dort kein eigenes Auth-Layer); `/api/*` und Frontend laufen über Backend-Auth (JWT-Cookie via `require_user`/`require_admin`/`require_real_user`/`require_mitarbeiter`). `/health` + `/healthz` bleiben public (Monitoring + Docker-HEALTHCHECK). Live-verifiziert auf heizung-test 2026-05-15 nach Caddy-Reload: kein Caddy-Popup auf Frontend, Login als kaprun funktioniert, `/devices` lädt, `/openapi.json` weiterhin Caddy-Basic-Auth. Out-of-scope: `Caddyfile.main` (Sprint 12, heizung-main-Migration). PR #154, commit `196e83c`. | ✅ erledigt 2026-05-15 |
| B-10-3 🟢 | **Vulnerability-Scanner-Traffic im Caddy-Log.** Beobachtet 2026-05-15 nach Sprint-10-Prep-Caddy-Hotfix: z.B. IP `192.253.248.169` scannt nach `/crm/.env.local`, `/staging/.env` und weiteren Standard-Pfaden. Caddy antwortet korrekt mit 308-Redirects, kein Daten-Leak. Hardening-Optionen: fail2ban auf wiederholte 4xx-/308-Antworten, Caddy-eigenes Rate-Limit-Modul, oder ein einfacher `@scanner`-Matcher mit `respond 444`. Sprint 10 (CI-Hygiene) oder eigener Security-Hardening-Sprint. |
| B-10-4 ✅ | **DST-Verhalten (Sommer-/Winterzeit Österreich) in zeit-gesteuerten Engine-Pfaden.** Phase-0-Audit (PR #184, 2026-05-25) hat einen 🔴 Befund identifiziert: Layer 2 Nachtabsenkung vergleicht UTC-now gegen Lokal-Konfig (`night_start`/`night_end`), konstanter Offset 1-2h. Engine-Beat, occupancy-Zeitfenster, Override-Expiry, Cleanup-Cron sind alle DST-immun (siehe Audit-Bericht §3-§5). | ✅ erledigt 2026-05-25 (B-10-4-Fix, AE-60, CLAUDE.md §5.65). `_RoomContext.timezone`-Feld aus `global_config.timezone` (Default Europe/Vienna), `layer_temporal` konvertiert UTC-now via `ZoneInfo` vor `.time()`-Vergleich. 3 neue Tests (Sommer CEST, Winter CET, DST-Wechsel 28.10.2026), 10 Bestand-Layer-2-Tests grün ohne Anpassung. Voll-Suite 526/1xfail. Keine DB-Migration. |
| B-11prep-1 🟠 (vor Sprint 17) | **Casablanca-FIAS-Anbindung — Hotelier-Antwort steht aus** (Stand 2026-05-15). Phase 5 (PMS) hängt davon ab. Falls FIAS-Antwort bis Sprint-17-Start nicht vorliegt: Sprint 16a entfällt, PMS rutscht in Phase 7, manuelle Belegungs-Pflege bleibt Fallback. Master-Quelle STRATEGIE-THERMOSTAT-ZUORDNUNG.md §13. |
| B-11prep-2 🟠 (in Sprint 13) | **Mass-Pairing-Werkzeug.** CSV-Import oder Batch-Wizard für ~100 Vickis. Realisiert in Sprint 13 (Pairing-Wizard), genutzt in Sprint 17 (Pre-Pairing September). Vorbereitung Phase 4b. |
| B-11prep-3 🟢 (nach Heizperiode) | **Alarm-Schwellen-Härtung gegen 100-Vicki-Skalierung.** AE-53-3-Stufen-Alarm (Mail-Stub via `logger.warning`) ist heute auf 4 Vickis ausgelegt; bei 100 Vickis ist Alarm-Müdigkeit realistisch. Nach erster Heizperiode 2026/27 empirisch nachjustieren. |
| B-11prep-4 🟠 (Mitte August) | **Pilot-Zimmer-Auswahl finalisieren.** 5 Zimmer maximaler Vielfalt: Standard + Suite + Mehrfach-Vicki + Funk-Rand + häufiger Gästewechsel. Vorbereitung Phase 6 Pilot-Go-Live Oktober Woche 1. Gemeinsam Strategie-Chat + Hotelier. |
| B-11prep-5 🟠 (nach Pre-Pairing September) | **LoRaWAN-Funklast-Monitoring UG65** in ersten Wochen nach Mass-Pairing. Bei ~100 Vickis ist Funk-Auslastung des einzigen Gateways relevant. Backlog für eigenes Monitoring-Item; vor Heizperiode-Start empirisch verifizieren. |
| B-12a-1 | **AE-29 manual_setpoint_event-Cleanup.** DROP TABLE + Modell `models/manual_setpoint_event.py` + Schema `schemas/manual_setpoint_event.py` + Relationships in `room.py` + `room_type.py` + Re-Export `models/__init__.py` atomar entfernen. | ✅ erledigt 2026-05-22 (Hygiene-Sprint T3, Commit `2663a7e`). Migration 0019 mit 1:1-Roundtrip-Reproduktion aus 0003a, plus `ManualOverrideScope`-Enum mit-gedroppt (0 Konsumenten). AE-29-Status-Header in Commit `e970edb` mit Hash-Backfill. |
| B-12a-2 🟢 | **`_create_device`-Helper-Default `health_state="healthy"`.** Test-Konvenienz: bei Sprint-12a T4 musste in `test_drehring_window_open_silent_skip` `device.health_state` manuell auf `healthy` gesetzt werden, weil DB-Default `silent` ist und `detect_open_window_zones` healthy-Filter hat. ~10 Min, Autonomiestufe 3. |
| B-12a-3 🟢 | **Layer 4 zone-differenzierende Window-Wirkung.** Heute setzt Window-Open alle Zonen des Raums auf Frostschutz/`free_target` und verwirft `zone_overrides` komplett (AE-58 Punkt 5). Empirische Bewertung nach Heizperiode 2026/27: soll Zone-Open nur die spezifische Zone in Sicherheits-Setpoint setzen statt ganzen Raum? Architektur-Frage, kein konkreter Sprint vor Heizperiode-Auswertung. |
| B-12a-4 🟡 | **Engine soll `derive_room_status` nutzen statt `room.status`-Field.** Aktuell zwei Quellen-of-Truth fuer „Ist Raum belegt?": `override_service.create` (T2) nutzt `derive_room_status` aus aktiven Occupancies, `rules/engine.py` Layer 1 liest `ctx.room.status` direkt. Sprint-12a T5 hat Drift in Tests sichtbar gemacht (Helper `_force_room_status_occupied` noetig). Single Source of Truth via `derive_room_status` auch im Engine-Pfad. ~3-4 h, Autonomiestufe 2. Eigener Sprint nach 12a-Merge. |
| B-12a-5 🟢 | **`_get_zones_for_room`-Helper konsolidieren nach `rules/zone_helpers.py`.** Aktuell Duplikat in `rules/engine.py` (`_get_zones_for_room_local`) + `tasks/engine_tasks.py` (`_get_zones_for_room`). Abhaengigkeits-Richtung (tasks → rules, nicht umgekehrt) verhindert direkten Import. Helper-Modul `rules/zone_helpers.py` als gemeinsame Quelle. ~30 Min, Autonomiestufe 3. |
| B-12a-6 🟢 | **Dispatch-Test mit `zone_overrides` ergaenzen.** `test_engine_multivicki_write.py` um Zone-Override-Pfad-Assertion erweitern: bei `RuleResult.zone_overrides={zone1: 24}` muss `_dispatch_downlinks_per_zone` Vicki in Zone1 mit Setpoint 24 ansteuern, Vicki in Zone2 mit Room-Default. Aktuell nur indirekt via 4 End-to-End-Tests in `test_engine_layer3.py` abgesichert. ~30 Min, Autonomiestufe 3. |
| B-12a-7 🟢 | **`get_active_zones_bulk`-Optimierung.** N+1-Lookup-Vermeidung im Engine-Zone-Eval-Loop in `evaluate_room`: heute pro Zone ein `get_active`-Roundtrip. Bei typischem 1-2 Zonen/Raum vernachlaessigbar; bei ~100 Vickis × 60s-Beat ist Engine-Last weiterhin Sekunden-Bereich. YAGNI bis Performance-Profil das verlangt. Notiz fuer spaeter. |
| B-12c-AuditGap | **`auto_revoke_on_checkout`-Audit-Luecke.** Sprint 12c hatte die Audit-Schreibung bewusst aus dem Scope genommen. | ✅ erledigt 2026-05-22 (Hygiene-Sprint T2, Commit `3934d33`). `OVERRIDES_AUTO_REVOKED_ON_CHECKOUT`-BusinessAudit in derselben Transaktion wie der Revoke, Idempotenz-Pfad unveraendert, `REVOKE_REASON_CHECKOUT`-Konstante als Single-Source-of-Truth fuer Filter-Rekonstruktion. |
| AE-57-Luecke | **AE-57-Slot in ADR-Log nie vergeben** (Doku-Hygiene-Backlog aus Sprint 12c). | ✅ vergeben 2026-05-21 (Hygiene-Sprint T1, Commits `9e17455` + `4ace2a9`). „Device-Lifecycle: Retire + Pair-New, Zone als stabiler Historie-Anker". Schliesst die Luecke zwischen AE-56 und AE-58. Inhaltliche Basis fuer Sprint 13b. |
| B-FlakyTime-1 | **Time-of-day-Flaky in 2 Layer-1-Pipeline-Tests** zwischen 00:00-06:00 UTC (`test_engine_zone_override_wirkt_nur_auf_zone`, `test_layer4_closed_occupied_passthrough`). Aufgedeckt im Hygiene-Sprint T3-pytest-Lauf um 05:01 UTC. | ✅ erledigt 2026-05-22 (Hygiene-Sprint T3.5, Commit `d2d5311`). `@freeze_time("2026-05-22T12:00:00Z")` auf beiden Tests, `freezegun>=1.5` als Dev-Dep. Kein prophylaktischer Patch auf andere 32 `evaluate_room`-Tests (YAGNI). |
| B-HygieneFollowup-1 🟢 | **`override_service` vs. `override_pms_hook` Modul-Grenzen-Audit nach Sprint 13b.** Phase-0-Befund: `auto_revoke_on_checkout` lebt in `override_pms_hook.py`, nicht in `override_service.py` (Brief T2 hat die Datei-Annahme nicht getroffen). Datei-Aufteilung pruefen ob klar oder Refactor sinnvoll. ~30 min, Stufe 3. |
| B-HygieneFollowup-2 🟢 | **Default-Reason-Param `'auto: guest checked out'` in `revoke_all_active_overrides`.** Nach Sprint 13b pruefen, ob noch Aufrufer existieren die den Default brauchen, oder ob der Param entfernt werden kann. Heute zwei explizite Aufrufer (Hygiene-T2 + Sprint 12c PATCH), plus Default-Nutzung in `test_override_service.py:332`. ~15 min, Stufe 3. |
| B-11prep-6 🟢 (nach Heizperiode) | **Drift-Erkennung statistisch** als KI-Vorbereitung. Aufbau eines Modells für Abweichungen einzelner Vickis von Zone-Geschwistern über Tage/Wochen. Master-Quelle STRATEGIE-THERMOSTAT-ZUORDNUNG.md §7.3 + §13 (bewusst nicht in MVP). |
| B-11prep-7 🟢 (nach Heizperiode) | **Backend-Plausi für Fenster (BR-16).** Heute reine Vicki-Flag-Logik (`vicki.openWindow`-Uplink, AE-47). Backend-Eigenlogik (Temperatursturz-Heuristik o.ä.) als Ergänzung evaluieren, sobald Heizperiode-Daten zeigen, ob Vicki-Flag allein reicht. STRATEGIE-THERMOSTAT-ZUORDNUNG.md §5.1. |
| B-11prep-8 🟢 (in Sprint 14b) | **arc42-Konsolidierung der Architektur-Doku.** Migration als Sprint 14b geplant (zwischen Sprint 14 UI-Erweiterungen und Sprint 15 heizung-main-Migration). Bestehende Inhalte (STRATEGIE.md, ARCHITEKTUR-REFRESH-2026-05-07, STRATEGIE-REFRESH-2026-05-15, ARCHITEKTUR-ENTSCHEIDUNGEN.md, CLAUDE.md §5 Lessons) werden auf arc42-12-Kapitel-Skelett gemappt, nicht neu geschrieben. Source-of-Truth-Hierarchie in CLAUDE.md §0.2 wird dann strukturell und kann entfallen. MkDocs/Renderer-Entscheidung bewusst aufgeschoben (reines Markdown reicht für Solo-Betrieb, Renderer erst bei externer Übergabe geprüft). Diskussions-Grundlage: Strategie-Chat 2026-05-15. |
| B-Sprint13a-1 🟢 | **`activate_open_window_detection.py` ins neue Sub-Package `heizung.scripts/` migrieren.** Aktuell liegt das Skript in `backend/scripts/`, das neue Pairing-Skript in `backend/src/heizung/scripts/`. Konsistenz-Migration nicht-dringend; vor Sprint 17 erledigen, damit der Hotelier nur einen Aufruf-Pfad lernt. |
| B-Sprint13a-2 🟢 | **Pydantic-Feld `zimmer_nummer` von `int \| None` auf `str \| None`.** Entspricht DB-`VARCHAR(20)`, erlaubt Zimmer wie `"DG"`, `"101A"`. Heute crasht der Parser bei nicht-numerischen Zimmern. Vor Sprint 17 klaeren. |
| B-Sprint13a-3 🟢 | **Test-Case fuer Float-String-Coercion in Pairing-CSV.** Excel-Exporte schreiben `"52.0"` statt `"52"` — `PairingCsvRow.zimmer_nummer` muss das tolerieren (Coerce zu `52`) oder klar abweisen. Heute Verhalten ungetestet. |
| B-Sprint13a-4 ✅ | **RUNBOOK-Hinweis zu `app_key` als Cross-Reference-Only dokumentiert.** Erledigt in T7 (Commit `cc27388`). |
| B-Sprint13a-5 🟡 | **Migration 0018 (Sprint 13b) fuehrt `pairing_status`-Feld ein** (Default `active`), um Variante-B fuer Downlink-Failure-Recovery nachzureichen. Heute: Pairing-Service legt Device + Audit an, OW-Downlink failt, `status=error` propagiert — aber kein Persistenz-Marker am Device, dass die OW-Konfig noch nachzuholen ist. Mit `pairing_status='pending_ow_resend'` wird das explizit. |
| B-Sprint13a-6 🟢 | **`list-all`-Subcommand mit Zimmer-Zuordnung.** Verschoben in Sprint 13b als sortierbare Frontend-Tabelle. CLI-Variante zur Eigen-Verifikation nice-to-have, nicht-dringend. |
| B-Sprint13a-7 🟢 | **RUNBOOK §10h.2 Stoerungsfall-Eintrag fuer `resend_open_window-failed`.** Explizite Anleitung: was der Hotelier tun soll wenn die OW-Aktivierung am Tisch failt — manuell re-senden via `python -m heizung.scripts.pair_devices test <id>` oder ignorieren weil der naechste Eingangstest erneut sendet. Heute kein Doku-Eintrag fuer den Fall. |
| B-Sprint13a-8 🟡 | **CLI-Summary-Wording praezisieren — `[FAIL]` bei `DOWNLINK_FAILED` ist semantisch korrekt aber irrefuehrend** wenn Device in DB existiert. Praezise Formulierung: `Resultat: 0 paired, 0 skipped, 3 errors (3 Device-Rows in DB, OW-Downlink fuer alle 3 fehlgeschlagen)`. T8-Live-Verify-Befund 2026-05-23. |
| B-Sprint13a-9 🟢 | **Dry-Run-Schluss-Message umformulieren.** Aktuell: `ChirpStack-Downlinks wurden trotzdem gesendet` — im unreachable-Host-Pfad nicht korrekt. Praeziser: `ChirpStack-Downlinks wurden versucht (Ergebnisse siehe oben)`. T8-Live-Verify-Befund 2026-05-23. |
| B-Sprint13a-10 🟢 | **Master-Inventar-Format-Migration (nur falls notwendig).** Falls in Sprint 16/17 sich herausstellt, dass das Master-Inventar verbindlich versionierbar sein muss (z.B. fuer Bootstrap-Reproduzierbarkeit): Format auf Pure-CSV oder Markdown-Tabelle umstellen (keine Secrets-Vektoren), dann ist `.gitignore`-Ausnahme vertretbar. Heute XLSX am Office-Laptop unter Hotelier-Kontrolle, Repo-README dokumentiert nur das Format. |

### 6.3 — Operative Aufgaben

| ID | Inhalt | Priorität |
|---|---|---|
| OP-1 | Backup-Cron + Off-Site-Replikation auf db | 🔴 (in 12) |
| OP-2 | main-Branch-Strategie | 🟡 (vor 12) |
| OP-3 | heizung-test Kernel-Update | 🟢 |
| OP-4 | ~/.ssh/config Eintrag heizung-test | erledigt |
| OP-5 | RUNBOOK-Sektion für DB-Zugang via SSH-Tunnel ergänzen | 🟡 |

### 6.4 — Sprint 15a Diagnose-Folgen (Backlog-Notizen)

Read-only-Diagnose Sprint 15a hat drei Folge-Stränge belegt. Inhaltliche Quelle: `docs/features/2026-05-31-hardware-health-diagnose.md`.

| ID | Inhalt | Priorität |
|---|---|---|
| B-15a-1 | **Reboot-Drift-Detection per fcnt-Reset** (BLOCK D.5). | ✅ erledigt 2026-06-01 (Sprint 15c, AE-63, Branch `feature/15c-fcnt-reboot-drift`, §2be). Diskriminator `is_reboot_frame(prior_fcnt, current_fcnt)` + Reboot-Gate in `device_adapter.handle_uplink_for_override` + Re-Sync-Flag (Hysterese-Bypass im `engine_tasks._dispatch_downlinks_per_zone`) + off-pipeline Audit `REBOOT_RESYNC`. Keine Migration. AE-45-Pfad unangetastet. 20 neue Tests grün lokal mit DB. |
| B-15a-2 | **AE-17 als superseded markieren** (BLOCK H2). AE-17-Text in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md:197-205` beschreibt eine `uplinks`-Hypertable mit JSONB-Payload — existiert real nicht. Sprint 5 (STATUS §2g.5.7) hat `sensor_reading` wiederverwendet (`models/sensor_reading.py:30-73`, Migration `0001_initial_domain_model.py:263-289` legt sie als Hypertable an, keine `uplinks`-Migration existiert). Separater `chore/`-Doku-PR mit ADR-Markierung „Status: Superseded — siehe `sensor_reading`-Schema". Nicht in andere PRs mischen. | 🟡 |
| B-15a-3 | **AE-45-Block-Pfad lückenlos auditieren** (BLOCK D.6.4 Audit-Gap). | ✅ by-design geschlossen 2026-06-02 (Sprint 15b B0-Beleg, AE-64 §Verworfen). Code-Pipeline post-Sprint-12c/15c schreibt bereits `MANUAL_OVERRIDE_BLOCKED`-event_log (`reason=DEVICE_BLOCKED_ROOM_BLOCKED`) im pre-a-Gate `device_adapter.handle_uplink_for_override` Z.385-399, sobald `detect_user_override` einen echten Setpoint-Change in gesperrtem Raum findet. Q-D4-Befund („0 Rows trotz Block über Stunden") war eine Heartbeat-Phase ohne Drehring-Akte — kein Bug. Heartbeats / Toleranz / Ack-Window dürfen unter der Strategie-Brief-Bedingung „nur echte Setpoint-Changes auditieren" bewusst keinen Audit erzeugen (Skalierungs-Risiko bei ~105 Vickis × ~12 Heartbeats/h). |
| B-15b-1 | **`alert_battery_warn_percent` real verdrahten — toter Schalter in Config-UI.** Sprint 15a Pre-Beleg + 15b A2-Bestätigung: das Feld existiert in `global_config` (Default 20 %, CHECK 1..100) plus Read/Write-Schemas, aber **kein Konsument** in `services/`/`tasks/`. `health_alerts.py` reagiert nur auf `offline_24h` + `implausible_readings_24h`. Hotelier kann den Wert in der Config-UI setzen, aber nichts passiert. Folge-Sprint: Email-Versand-Scope-Entscheidung (`alert_email` ebenfalls heute nur in `global_config`, Email-Service noch nicht implementiert — vgl. §5.20-Pattern „aspirativer Kommentar in Sprint-13"). Klein-mittel, vor Heizperiode 2026/27 wünschenswert (Batterie-Wechsel-Vorlauf). | 🟡 |
| B-15b-2 | **Batterie-UI: Stufen-Badge statt Prozentzahl** (kein Bug, Scheinpräzisions-Hygiene). Codec liefert Geräte-Spannung im 0.1-V-Raster mit 4-Bit-Nibble — Wertebereich 2.0-3.5 V, nibble 15 (= 3.5 V) ist Sättigung am oberen Ende. Effektiv hat das System ~6 unterscheidbare Stufen oberhalb der Wechsel-Schwelle (0/10/30/50/65/80/87/93/100 % an den Codec-Quantisierungs-Stufen 2.7..3.5 V); der Bereich „frisch bis etwas verbraucht" (Live-Beleg 2026-06-02: 3 von 4 Vickis auf nibble=15 saturiert) ist ohne Auflösung. 2-stellige Prozentzahl in der UI ist Scheinpräzision. Vorschlag Folge-Sprint: Stufen-Badge mit ~5 Stufen (`frisch` ≥ 80 %, `gut` ≥ 50 %, `mittel` ≥ 30 %, `warn` ≥ 10 %, `leer` < 10 %), tooltip-Anzeige der Rohspannung für Diagnose. Mit B-15b-1 gemeinsam planbar (UI + Alarm-Anbindung). | 🟢 |

---

## 7. Schmerzpunkte aus heute (Lessons Learned)

- Hetzner Web Console (noVNC) zerlegt `|`, `:` wegen US-Keyboard-Layout → nie für Multi-Character-Commands
- Rescue-Mode NUR mit komplettem Fix-Block (UFW + sshd_config.d + authorized_keys + fail2ban) in einem Shot, nie inkrementell
- Google Drive Sync zwischen Cowork-Workspace und Windows-Client ist unzuverlässig → Dev-Arbeit muss direkt im lokalen Git-Repo laufen
- Memory-Einträge dazu:
  - `feedback_hetzner_ops.md` — 10 Regeln für Hetzner-Operations
  - `reference_paths.md` — Cowork-Workspace-Pfad + SSH-Keys
  - `project_deploy_state.md` — aktueller Deploy-Stand

---

## 8. Zugangsdaten-Übersicht (Pfade, keine Secrets)

| Zweck | Pfad / Referenz |
|---|---|
| SSH-Key Hetzner/Tailscale | `$HOME\.ssh\id_ed25519_heizung` |
| SSH-Key GitHub | `$HOME\.ssh\id_ed25519_github` |
| Git-Repo lokal | `C:\Users\User\dev\heizung-sonnblick` |
| GHCR-Registry | `ghcr.io/rexei123/heizung-{api,web}` |
| Hetzner Cloud Console | https://console.hetzner.cloud |
| Tailscale Admin | https://login.tailscale.com/admin/machines |
| GitHub Repo | https://github.com/rexei123/heizung-sonnblick |

Secrets liegen in:
- Servern: `/opt/heizung-sonnblick/infra/deploy/.env`
- GitHub Actions: Repository Secrets
- Keine Secrets in Git, keine Secrets in diesem Bericht.

---

## 9. Tags

| Tag | Sprint | Datum |
|---|---|---|
| `v0.1.0-baseline` | Sprint 0 (Repo-Hygiene + Playwright + Branch-Protection) | 2026-04-21 |
| `v0.1.1-pat-rotation` | Sprint 1 (GHCR-PAT-Rotation, RUNBOOK §6.1) | 2026-04-21 |
| `v0.1.2-web-healthcheck` | Sprint 2 (`/api/health` + Dockerfile-HEALTHCHECK) | 2026-04-22 |
| `v0.1.3-ufw-reactivation` | Sprint 3 (UFW aktiv auf beiden Servern + RUNBOOK §8 aktualisiert) | 2026-04-22 |
| `v0.1.4-domain-hoteltec` | Sprint 4 (Domain-Umschaltung auf hoteltec.at, Let's-Encrypt-TLS) | 2026-04-22 |
| `v0.1.5-lorawan-foundation` | Sprint 5 (LoRaWAN-Pipeline lokal: ChirpStack + Mosquitto + MQTT-Subscriber + Sensor-Readings-API) | 2026-04-28 |
| `v0.1.6-hardware-pairing` | Sprint 6 (Hardware-Pairing, Vicki-Onboarding) | 2026-04-29 |
| `v0.1.7-frontend-dashboard` | Sprint 7 (Frontend-Dashboard, Devices-Liste) | 2026-04-30 |
| `v0.1.8-stammdaten` | Sprint 8 (Stammdaten + Belegung, Master-Detail-CRUD) | 2026-05-03 |
| `v0.1.9-rc1-walking-skeleton` | Sprint 9 (Engine 6-Layer-Skelett + Downlink + Engine-Panel) | 2026-05-04 |
| `v0.1.9-rc2-manual-override` | Sprint 9.9 + 9.9a (Engine Layer 3 + UI + Hotfix) | 2026-05-06 |
| `v0.1.9-rc3-window-detection` | Sprint 9.10 (Engine Layer 4 Window-Detection + AE-40 Engine-Task-Lock) | 2026-05-07 |
| `v0.1.9-rc6-live-test-2` | Sprint 9.11y (Synthetic-Layer-4-Tests + Inferred-Window-Logger + Hardware-Kältepack-Verify, Sprint-9.11-Familie abgeschlossen) | 2026-05-11 |
| `v0.1.11-device-pairing` | Sprint 9.13 / 9.13b (Pairing-UI + Sidebar-Migration + Empty-State-Stubs, PR #137) | 2026-05-13 |
| `v0.1.12-global-config-ui` | Sprint 9.14 (Global-Config-UI: rule_config + config_audit + Inline-Edit, PR #143) | 2026-05-14 |
| `v0.1.13-szenario-engine` | Sprint 9.16 + 9.16a (Szenario-Engine + Umlaut-Drift-Fix Sommermodus-Seed Migration 0013, PR #146; Sprint 9.15 Profile mit 9.16 fusioniert) | 2026-05-14 |
| `v0.1.14-auth` | Sprint 9.17 + 9.17a + 9.17b (Auth + 2-Rollen-Modell + Audit + Logout-Cookie-Fix, PR #151) | 2026-05-15 |
| `v0.1.15-zuordnungs-architektur-doku` | Sprint 11-Prep (Doku-Konsolidierung Zuordnungs-Architektur, STRATEGIE-THERMOSTAT-ZUORDNUNG + AE-51..AE-54, PR #157) | 2026-05-16 |
| `v0.1.16-health-aggregat` | Sprint 11 (Health-State + Plausi + Zone-Isolation + Aggregat-Lesen, AE-51 §4.1 + AE-53 + AE-54, PR #158) | 2026-05-18 |
| `v0.1.17-multivicki-fenster` | Sprint 12 (Multi-Vicki-Dispatch symmetrisch + Layer 4 occupancy-aware + Override-Reject 409, AE-51 P3 + AE-52 + AE-55 + AE-56, PR #160) | 2026-05-19 |
| `v0.1.17a-override-zone-scope-backend` | Sprint 12a (Override-Zone-Scope + AE-58 Konsolidierung Backend-only: OCCUPIED-Gate, Zone-Scope-Override, Engine Layer 3 zone-aware via `RuleResult.zone_overrides`, AE-29 + AE-45 abgeloest, PR #162) | 2026-05-20 |
| `v0.1.17b-override-zone-scope-frontend` | Sprint 12b (Frontend Zone-Override-Panels + Window-Pre-Check via Engine-Trace + typisierter Error-Helper + Engine-Decision-Panel-Erweiterung, PR #164, Squash-Commit `3587b47`) | 2026-05-20 |
| `v0.1.17c-room-override-blocked` | Sprint 12c (Uebersteuerungs-Sperre pro Zimmer: `room.guest_override_blocked`, Single-Source-of-Truth in `override_service.create`, Auto-Revoke bei Toggle-On mit `revoked_reason="room_override_blocked"`, BusinessAudit `ROOM_OVERRIDE_BLOCK_TOGGLED`, Device-Adapter Pre-A-Gate, Frontend-Toggle + Panel-Banner, PR #166, Squash-Commit `e9b18af`) | 2026-05-20 |
| `v0.1.17d-room-block-list-indicator` | Sprint 12c.a (Schloss-Symbol-Spalte in Zimmer-Uebersicht bei `guest_override_blocked=true`, Frontend-only, PR #168, Squash-Commit `81ed3dc`) | 2026-05-20 |

*Sprint 9.8c (Hygiene) und Sprint 9.8d (shadcn-Migration): kein Tag während Lauf — Tag-Vergabe nach Sprint-9.8d-Abschluss (T3 + T4) bzw. mit Final-Tag `v0.1.9-engine` auf main.*

*Sprints 9.11x, 9.11x.b, 9.11x.c: kein eigener Tag — Familie schließt mit `v0.1.9-rc6-live-test-2` auf 9.11y.*

*`v0.2.0-architektur-refresh` war geplant, nicht vergeben — der Refresh
wurde über mehrere kleine Tags `v0.1.9-rc4` bis `v0.1.9-rc6` ausgerollt.
Tag-Slot `v0.2.0` bleibt frei für späteren Meilenstein.*

*`v0.1.10-frost-protection` war für Sprint 9.12 (Frostschutz pro Raumtyp)
geplant. Sprint zurückgestellt 2026-05-11 (siehe §2aa, AE-42).
Tag-Slot `v0.1.10` bleibt ungenutzt als sprechender Marker für den
zurückgestellten Sprint.*
