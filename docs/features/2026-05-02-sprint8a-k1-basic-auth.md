# Sprint 8a — K-1 API-Auth via Caddy-Basic-Auth (interim)

**Typ:** Sicherheit / Operations
**Datum:** 2026-05-02
**Audit-Bezug:** QA-Audit `docs/working/qa-audit-2026-04-29.md` Befund K-1 (Keine Authentifizierung an der API)
**Folge-Sprint:** Sprint 9 plant echte Session-Auth (NextAuth/FastAPI-Users + Login-Form)

---

## Ausgangslage

Vor Sprint 8a waren `/api/v1/devices`, `/api/v1/devices/<id>/sensor-readings`, `/openapi.json`, `/docs` und `/redoc` auf `heizung-test.hoteltec.at` und `heizung.hoteltec.at` **vollstaendig public**. Jeder mit der URL konnte:

- Geraeteliste lesen
- Sensor-Readings einsehen (Hotel-interne Daten)
- Neue Geraete via `POST /api/v1/devices` anlegen
- Geraete via `PATCH` bearbeiten oder via `DELETE` loeschen (sobald die Routen existieren)
- Per `/docs` die OpenAPI-Doku lesen, alle Endpoints inkl. Schemas

Das war der wichtigste QA-Audit-Befund (K-1, Kritisch). Vor jedem produktiven Live-Betrieb muss das geschlossen sein.

## Aenderungen

### Caddy-Layer-Auth

`infra/caddy/Caddyfile.test` und `infra/caddy/Caddyfile.main` bekommen einen geteilten Matcher:

- `@api_public { path /health }` — bleibt ohne Auth, fuer externes Uptime-Monitoring
- `@api_protected { path /api/* /openapi.json /docs /redoc }` — Caddy-Basic-Auth mit User `hotel` und bcrypt-Hash aus env-Var `HOTEL_BASIC_AUTH_HASH`

Frontend selbst bleibt browsbar ohne Auth (HTML-Routing). Aber jeder Daten-Call vom Frontend geht durch `/api/*` und triggert den Browser-Auth-Prompt. Browser cached die Credentials nach erstem Login -> nahtlos fuer den Hotelier.

### Compose + .env

`docker-compose.prod.yml` Caddy-Service bekommt `HOTEL_BASIC_AUTH_HASH` als env-Var. `.env.example` dokumentiert den Hash + Erzeugung mit `caddy hash-password`. Das Doppel-Dollar-Pattern (gleich wie CHIRPSTACK_BASIC_AUTH_HASH) ist beibehalten.

### RUNBOOK §10b

Setup-Anleitung pro Server (Hash erzeugen, .env setzen, Caddy recreate, Verifikation, Passwort-Rotation, Sprint-9-Backlog).

## User-Schema (interim)

- **Ein** geteilter User: `hotel`
- Single-Password fuer alle Hotel-Mitarbeiter
- Kein Audit-Trail, kein Logout
- Browser-Native-Auth-Dialog (nicht hubsch, aber funktional)

Sprint 9 plant: NextAuth oder FastAPI-Users mit echtem User-Modell, Login-Form, Logout, RBAC, Audit-Log.

## Edge Cases

- **Frontend-SSR-Calls** vom Web-Container an api:8000 gehen Container-intern, NICHT via Caddy -> kein Auth-Header noetig. Funktioniert ohne Sonderbehandlung.
- **TanStack-Query-Calls** vom Browser gehen via Caddy. Browser sendet `Authorization`-Header automatisch nach erstem Login (cached fuer die Session).
- **`/health` bleibt public** -> externes Uptime-Monitoring (UptimeRobot, statuspage.io etc.) funktioniert ohne API-Key.
- **`/openapi.json` hinter Auth** -> Auto-Generierung von TS-Clients braucht jetzt Credentials. Pro Mitarbeiter ein Browser-Login reicht.
- **Caddy-Basic-Auth Hash-Format** -> doppelte $-Zeichen wegen Compose-Interpolation, gleiches Pattern wie CHIRPSTACK_BASIC_AUTH_HASH.

## Risiken

| Risiko | Eintritt | Impact | Mitigation |
|---|---|---|---|
| HOTEL_BASIC_AUTH_HASH falsch in .env (Single-Dollar) | mittel | hoch (Caddy startet nicht) | RUNBOOK §10b zeigt Doppel-Dollar; Caddy-Logs zeigen Parse-Error |
| Browser cached altes Passwort nach Rotation | hoch | niedrig | RUNBOOK §10b.5 Hinweis "Browser-Cache loeschen" |
| Kein Audit-Log fuer Logins | hoch | mittel | Sprint-9-Backlog explizit |
| Single-User -> alle Mitarbeiter teilen Account | hoch | mittel | Sprint-9-Backlog (RBAC + User-Tabelle) |
| Frontend-Pages selbst sind ohne Auth lesbar (nur statisches HTML) | hoch | gering | tatsaechliche Daten kommen via `/api/*` und sind geschuetzt |

## Verifikation

Nach Deploy auf `heizung-test`:

```bash
# Ohne Auth -> 401
curl -I https://heizung-test.hoteltec.at/api/v1/devices

# Mit Auth -> 200
curl -u hotel:<pw> https://heizung-test.hoteltec.at/api/v1/devices

# Health bleibt public
curl https://heizung-test.hoteltec.at/health

# Frontend selbst lesbar (ohne Daten)
curl https://heizung-test.hoteltec.at/devices  # liefert HTML
```

Plus Browser-Test: `https://heizung-test.hoteltec.at/devices` -> Liste laedt initial leer + Browser fragt nach Auth (von erstem `/api/v1/devices`-Call). Nach Auth lädt die Liste mit Werten.

## Server-Setup-Workflow

Pro Server (test, main):

1. bcrypt-Hash mit `docker run --rm caddy:2 caddy hash-password --plaintext "<pw>"` erzeugen
2. In `.env` eintragen, jedes `$` verdoppeln
3. `docker compose up -d --force-recreate caddy`
4. Verifikation per `curl`
5. Im Browser einmal einloggen + Cache speichern lassen

## Nicht enthalten (Sprint-9-Backlog)

- Echte User-Tabelle (`users`-Migration)
- Login-Form im Frontend
- Logout-Endpunkt
- Session-Cookie statt Basic-Auth
- RBAC (z.B. Admin vs. Read-Only)
- Audit-Log (Login-Time, IP, User)
- 2FA / TOTP
- API-Token fuer Maschinen-Clients (z.B. CI, externe Integrationen)
