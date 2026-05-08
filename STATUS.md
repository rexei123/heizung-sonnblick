# Status-Bericht Heizungssteuerung Hotel Sonnblick

Stand: 2026-05-05. Sprints 0-9.8 abgeschlossen, Sprint 9.8c (Hygiene-Sprint) in Arbeit.

---

## 1. Aktueller Stand

**Stichtag:** 2026-05-07
**Aktueller Branch:** develop, HEAD `654fbab` (Doku-Patch §5.24+§5.25)
**Letzter Tag:** `v0.1.9-rc5-trace-consistency`
**Nächster Sprint:** 9.11 Live-Test #2 (siehe `docs/SPRINT-PLAN.md`)
**Architektur-Refresh:** durchgeführt 2026-05-07, siehe
`docs/ARCHITEKTUR-REFRESH-2026-05-07.md`

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
- Alembic-Migrationen 0001-0004 + 0008 + 0009 (0003 in zwei Files: 0003a Stammdaten + 0003b event_log-Hypertable; 0008 manual_override aus 9.9; 0009 sensor_reading.open_window aus 9.10)
- Engine: 6-Layer-Pipeline vollständig — Layer 0 Sommer / 1 Base / 2 Temporal / 3 Manual / 4 Window-Detection / 5 Hard-Clamp + Hysterese. Sprint 9.10: Reading-Trigger feuert Re-Eval, Race-Condition durch Redis-SETNX-Lock (AE-40) abgesichert.
- ~25 Test-Dateien, 190 Test-Cases lokal grün (+10 pre-existing psycopg2-Failures, kein 9.10-Bezug)

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
- `/zimmer/[id]` — Zimmer-Detail (Tabs: Stammdaten, Heizzonen, Geräte, Engine, Übersteuerung)
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
| BR-1 🔴 | Frostschutz pro Raumtyp (DB + Engine + API) | 9.12 |
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

### 6.2 — Hygiene-Aufgaben (B-9.10*)

Werden im Hygiene-Sprint 10 abgearbeitet.

| ID | Inhalt | Priorität |
|---|---|---|
| B-9.10-1 | Fenster-Indikator in /zimmer-Liste | 🟡 |
| B-9.10-2 | Fehler-Übersicht für Devices (in BR-2 enthalten) | erledigt |
| B-9.10-6 | psycopg2-Failures | 🟡 |
| B-9.10c-1 | ChirpStack-Codec-Bootstrap-Skript | 🟡 |
| B-9.10c-2 | Codec-Re-Paste auf heizung-main bei Production-Migration | 🔴 (in 12) |
| B-9.10d-1 | detail-Konvention vereinheitlichen | 🟡 |
| B-9.10d-2 | mypy-Vorlast 71 Errors in tests/ | 🟡 |
| B-9.10d-3 | Type-Inkonsistenz Engine `int` vs. EventLog `Decimal` | 🟡 |
| B-9.10d-5 | engine_tasks DB-Session per Dependency-Injection | 🟢 |
| B-9.10d-6 | Pre-Push-Hook für `ruff format --check` | 🟢 |
| B-9.11-1 | celery_beat Healthcheck korrigieren | 🟡 |

### 6.3 — Operative Aufgaben

| ID | Inhalt | Priorität |
|---|---|---|
| OP-1 | Backup-Cron + Off-Site-Replikation auf db | 🔴 (in 12) |
| OP-2 | main-Branch-Strategie | 🟡 (vor 12) |
| OP-3 | heizung-test Kernel-Update | 🟢 |
| OP-4 | ~/.ssh/config Eintrag heizung-test | erledigt |

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

*Sprint 9.8c (Hygiene) und Sprint 9.8d (shadcn-Migration): kein Tag während Lauf — Tag-Vergabe nach Sprint-9.8d-Abschluss (T3 + T4) bzw. mit Final-Tag `v0.1.9-engine` auf main.*
