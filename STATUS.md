# Status-Bericht Heizungssteuerung Hotel Sonnblick

Stand: 2026-05-05. Sprints 0-9.8 abgeschlossen, Sprint 9.8c (Hygiene-Sprint) in Arbeit.

---

## 1. Was läuft produktiv

### Test-System
- **URL:** https://heizung-test.hoteltec.at
- **Hetzner:** CPX22, `157.90.17.150`
- **Tailscale:** `heizung-test` = `100.82.226.57`
- **Branch:** `develop`, **GHCR-Tag:** `develop`
- **Deploy-Mode:** GHCR Pull-Deploy via systemd-Timer, 5-Min-Intervall
- **UFW:** aktiv (22/80/443 + tailscale0)
- **TLS:** Let's Encrypt via Caddy (Auto-Renewal)
- **Status:** ✅ Läuft, alle Container up, `web` (healthy)

### Main-System
- **URL:** https://heizung.hoteltec.at
- **Hetzner:** CPX32, `157.90.30.116`
- **Tailscale:** `heizung-main` = `100.82.254.20`
- **Branch:** `main`, **GHCR-Tag:** `main`
- **Deploy-Mode:** Identisch zu Test (Pull-Deploy + Auto-Migration)
- **UFW:** aktiv (22/80/443 + tailscale0)
- **TLS:** Let's Encrypt via Caddy (Auto-Renewal)
- **Status:** ✅ Läuft, alle Container up, `web` (healthy), Auto-Migration erfolgreich gelaufen

### Entwicklungs-Client
- **Hostname:** `work02` (Tailscale = `100.78.38.29`)
- **Git-Repo:** `C:\Users\User\dev\heizung-sonnblick`
- **SSH-Key:** `$HOME\.ssh\id_ed25519_heizung`

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
- 14 Modelle: device, heating_zone, room, room_type, occupancy, rule_config, global_config, manual_setpoint_event, scenario, scenario_assignment, season, sensor_reading (Hypertable), event_log (Hypertable), control_command
- Alembic-Migrationen 0001-0004 deployed auf beiden Servern (0003 in zwei Files: 0003a Stammdaten + 0003b event_log-Hypertable)
- Engine: 6-Layer-Pipeline (Layer 0/1/2/5 + Hysterese implementiert, Layer 3/4 offen)
- 10 Test-Dateien, 96 Test-Cases, CI grün

### Frontend (Next.js 14.2 App Router + Tailwind)
- Next.js 14.2.15, React 18.3.1, TypeScript 5.6.3 strict
- Tailwind 3.4.14, Design-Strategie 2.0.1 (Rosé `#DD3C71`, Roboto, Material Symbols Outlined)
- TanStack Query 5.100.5 für Server-State, recharts 3.8.1 für Charts
- Eigene UI-Komponenten unter `components/ui/` (Button, ConfirmDialog) — kein shadcn/ui
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
- `/zimmer/[id]` — Zimmer-Detail (Tabs: Stammdaten, Belegungen, Engine, Devices)
- `/raumtypen` — Raumtypen Master-Detail
- `/belegungen` — Belegungen-Liste + Form
- `/einstellungen/hotel` — Hotel-Stammdaten Singleton
- `/devices` — Geräteliste
- `/devices/[device_id]` — Geräte-Detail mit Reading-Chart
- `/healthz` — Frontend-Healthcheck (Caddy/Compose)

### Backend-API (`/api/v1/...`)

- `/api/v1/devices/*` — CRUD Devices, GET `{device_id}/sensor-readings`
- `/api/v1/rooms/*` — CRUD Rooms, GET `{room_id}/engine-trace`
- `/api/v1/room-types/*` — CRUD Raumtypen
- `/api/v1/rooms/{room_id}/heating-zones` — CRUD Heating-Zones (nested unter Rooms)
- `/api/v1/occupancies/*` — CRUD Belegungen
- `/api/v1/global-config` — GET/PATCH Hotel-weite Settings
- `/healthz` — Backend-Healthcheck

---

## 5a. Wichtige Dokumente im Repo

- `docs/STRATEGIE.md` — Gesamtkonzept, Architektur, Roadmap
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log
- `docs/Design-Strategie-2.0.1.docx` — UI-Richtlinie (verbindlich)
- `docs/RUNBOOK.md` — Troubleshooting, Rescue-Mode, SSH-Fehlerbilder, UFW-Hardening, GHCR-PAT-Rotation

---

## 6. Nächste Schritte

Pipeline-Modell: Claude Code arbeitet kontinuierlich am ausdiskutierten Task. Parallel wird im Strategie-Chat der jeweils nächste Task geplant.

**Aktiv in Claude Code:**
- (kein aktiver Task — Sprint 9.8c abgeschlossen, wartet auf nächste Vorgabe)

**Aktiv in Planung (Strategie):**
- (Platzhalter — wird nach Entscheidung über Sprint 9.8d/9.9 gefüllt)

**Backlog (nicht priorisiert):**
- Sprint 9.8d: shadcn/ui-Foundation (Button, Dialog, Form-Felder von shadcn übernehmen)
- Sprint 9.9: Engine Layer 3 (Manual-Override) + Layer 4 (Window/Fenster-offen)
- Backup-Cron + Off-Site-Replikation (manueller Dump in `/opt/heizung-backup/`, kein Cron)
- main-Branch-Strategie (aktuell hinter develop, Image-Tag-Logik klären)
- Sprint 10: Szenarien (scenario/scenario_assignment-Modelle vorbereitet)
- NextAuth/Multi-Tenant (Sprint 11+)
- frontend-ci-skip.yml aufräumen
- `~/.ssh/config`-Einträge für heizung-test/heizung-main
- heizung-test: Kernel-Update ausstehend
- e2e-Smoketests für Sprint-8-Routen (/belegungen, /einstellungen/hotel, 
  Master-Detail-Pages): aktuell keine e2e-Coverage. Architektur-Entscheidung 
  vor Implementierung — Playwright-Mocking via route.fulfill ODER 
  api+db-Container in CI hochfahren. Eigener Mini-Sprint, nicht Hygiene.

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
