# Status-Bericht Heizungssteuerung Hotel Sonnblick

Stand: 2026-04-28. Sprints 0 (Baseline), 1 (GHCR-PAT-Rotation), 2 (Web-Healthcheck), 3 (UFW-Reaktivierung), 4 (Domain hoteltec.at) und 5 (LoRaWAN-Foundation lokal) abgeschlossen.

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
- ⏳ **6.7 Vicki-Pairing** — wartet auf MClimate-Support (Vicki-EUI/AppKey nicht auf Geraet aufgedruckt)
- ⏳ **6.8 Codec-Validierung gegen Realdaten**
- ⏳ **6.9 PR + Merge + Tag** `v0.1.6-hardware-pairing`

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
- ⏳ **7.8 Doku + PR + Tag** `v0.1.7-frontend-dashboard` — wird zusammen mit Sprint 6 (`v0.1.6-hardware-pairing`) gemerged, beide Tags auf demselben Merge-Commit.

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
- Domain-Model vollständig: Zimmer, Raumtypen, Gäste, Belegungen, Geräte, Events
- Alembic-Migration 0001_initial deployed auf beiden Servern
- Seed-Daten: 45 Zimmer + Raumtypen eingespielt
- Unit-Tests grün

### Frontend (Next.js 14.2 App Router + Tailwind)
- Grundgerüst mit Design-Strategie 2.0.1 (Rosé `#DD3C71`, Roboto, Material Symbols Outlined)
- AppShell mit 200 px Sidebar
- Caddy-Reverse-Proxy konfiguriert
- **Hinweis:** shadcn/ui ist derzeit **nicht** installiert. Runtime-Deps sind `next`, `react`, `react-dom`, `clsx`, `tailwind-merge`. Einführung von shadcn/ui wird separat entschieden, wenn erste Komponenten es brauchen.
- Playwright E2E eingerichtet (Smoke-Tests) + CI-Job `e2e` in `.github/workflows/frontend-ci.yml`

### Infrastruktur
- Docker Compose: api, web, postgres, redis, caddy (5 Container pro Umgebung)
- CI/CD: GitHub Actions baut Images bei Push auf `develop`/`main`, published nach GHCR
- Deploy: systemd-Timer auf Server zieht neue Images alle 5 Min
- SSH-Zugang nur über Tailscale (Public-IP als Fallback via `id_ed25519_heizung`)

---

## 5. Wichtige Dokumente im Repo

- `docs/STRATEGIE.md` — Gesamtkonzept, Architektur, Roadmap
- `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` — ADR-Log
- `docs/Design-Strategie-2.0.1.docx` — UI-Richtlinie (verbindlich)
- `docs/RUNBOOK.md` — Troubleshooting, Rescue-Mode, SSH-Fehlerbilder, UFW-Hardening, GHCR-PAT-Rotation

---

## 6. Nächste Schritte

**Unmittelbar:**
1. **LoRaWAN-Integration** starten: ChirpStack auf Milesight UG65 Gateway, erstes Pairing mit MClimate Vicki (Referenzgerät)
2. **Regel-Engine** (8 Kernregeln) implementieren — Start mit Frostschutz + belegungsabhängige Temperatur

**Backlog (nicht dringend):**
- Caddy: separater öffentlich erreichbarer Health-Endpoint (aktuell routet `/api/*` auf Backend, der frontend-interne `/api/health` ist von extern nicht getrennt adressierbar — z. B. auf `/_health` umbiegen)
- Caddyfile formatieren (`caddy fmt --overwrite` — Warnung im Log, kosmetisch)
- CI-Mirror-Redundanz (`frontend-ci-skip.yml`) aufräumen wenn Branch-Protection-Matcher smarter wird
- `~/.ssh/config`-Einträge für `heizung-test`/`heizung-main` auf dem Entwickler-Client (spart `-i …`-Flag)
- heizung-test: Kernel-Update ausstehend (`*** System restart required ***`)

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
