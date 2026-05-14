# Brief für Claude Code — Sprint 9.17 (Auth + 2-Rollen + business_audit)

> Archivkopie des Sprint-Briefs zur Nachvollziehbarkeit. Aktueller
> Stand: STATUS.md §2af, ADR AE-50.

## Ziel

FastAPI-native JWT-Cookie-Auth statt NextAuth. Zwei Rollen
(`admin`, `mitarbeiter`). `config_audit` bekommt `user_id` befüllt,
neues `business_audit` für Mitarbeiter-Aktionen. Feature-Flag
`AUTH_ENABLED` (Default `false` bei Merge).

## Architektur-Entscheidungen (verbindlich) — AE-50

1. JWT in HttpOnly-Cookie, FastAPI-native (`python-jose` +
   `passlib[bcrypt]` + `slowapi`).
2. Zwei Rollen: `admin` (alles), `mitarbeiter` (Belegungen +
   Manual-Overrides + eigenes Passwort).
3. Audit-Domain-Trennung: `config_audit` (Konfig + Stammdaten) /
   `business_audit` (operative Aktionen).
4. Inaktivitäts-Logout 15 Min, Hard-Cut ohne Modal,
   BroadcastChannel Multi-Tab.
5. Bootstrap-Admin via `INITIAL_ADMIN_EMAIL` +
   `INITIAL_ADMIN_PASSWORD_HASH`.
6. Feature-Flag `AUTH_ENABLED` (Default `false`).
7. Passwort-Reset nur durch Admin (kein Self-Service in 9.17).
8. `X-User-Email`-Header in `overrides.py` vollständig entfernt.

## Endpoint-Inventar (T1)

Vollständige Liste aller mutierenden API-Endpoints + Rolle-Zuordnung.
Liste ist mit Sprint 9.17 T6 1:1 umgesetzt
(`Depends(require_admin)` / `Depends(require_mitarbeiter)`).

### admin-only

| # | Endpoint | Datei |
|---|---|---|
| 1 | POST   /api/v1/devices | `api/v1/devices.py` |
| 2 | PATCH  /api/v1/devices/{id} | `api/v1/devices.py` |
| 3 | PUT    /api/v1/devices/{id}/heating-zone | `api/v1/devices.py` |
| 4 | DELETE /api/v1/devices/{id}/heating-zone | `api/v1/devices.py` |
| 5 | POST   /api/v1/rooms | `api/v1/rooms.py` |
| 6 | PATCH  /api/v1/rooms/{id} | `api/v1/rooms.py` |
| 7 | DELETE /api/v1/rooms/{id} | `api/v1/rooms.py` |
| 8 | POST   /api/v1/room-types | `api/v1/room_types.py` |
| 9 | PATCH  /api/v1/room-types/{id} | `api/v1/room_types.py` |
| 10 | DELETE /api/v1/room-types/{id} | `api/v1/room_types.py` |
| 11 | POST   /api/v1/rooms/{room_id}/heating-zones | `api/v1/heating_zones.py` |
| 12 | PATCH  /api/v1/heating-zones/{id} | `api/v1/heating_zones.py` |
| 13 | DELETE /api/v1/heating-zones/{id} | `api/v1/heating_zones.py` |
| 14 | PATCH  /api/v1/global-config | `api/v1/global_config.py` |
| 15 | PATCH  /api/v1/rule-configs/global | `api/v1/rule_configs.py` |
| 16 | POST   /api/v1/scenarios/{code}/activate | `api/v1/scenarios.py` |
| 17 | POST   /api/v1/scenarios/{code}/deactivate | `api/v1/scenarios.py` |
| 18 | POST   /api/v1/users | `api/v1/users.py` |
| 19 | PATCH  /api/v1/users/{id} | `api/v1/users.py` |
| 20 | POST   /api/v1/users/{id}/reset-password | `api/v1/users.py` |
| 21 | DELETE /api/v1/users/{id} | `api/v1/users.py` |
| 22 | GET    /api/v1/users | `api/v1/users.py` |

### mitarbeiter (admin auch)

| # | Endpoint | Datei |
|---|---|---|
| 23 | POST   /api/v1/occupancies | `api/v1/occupancies.py` |
| 24 | PATCH  /api/v1/occupancies/{id} | `api/v1/occupancies.py` |
| 25 | POST   /api/v1/rooms/{room_id}/overrides | `api/v1/overrides.py` |
| 26 | DELETE /api/v1/overrides/{id} | `api/v1/overrides.py` |
| 27 | POST   /api/v1/auth/change-password | `api/v1/auth.py` |
| 28 | POST   /api/v1/auth/logout | `api/v1/auth.py` |
| 29 | GET    /api/v1/auth/me | `api/v1/auth.py` |

### public

| # | Endpoint | Datei |
|---|---|---|
| 30 | POST  /api/v1/auth/login (rate-limited 5/min) | `api/v1/auth.py` |
| –  | DELETE /api/v1/occupancies/{id} → 405 static | `api/v1/occupancies.py` |
| –  | /health, /healthz | `main.py`, web |
| –  | Alle GET-Endpoints (Daten lesen offen — Brief: read access ist heute kein Risiko) | viele |

## Brief-Abweichungen während Umsetzung

- T2 Bootstrap-Admin als Python-Code in Migration 0014: `op.get_bind()`
  + raw SQL-`INSERT`. ENV-Vars beim alembic-upgrade gelesen — bei
  fehlenden ENV-Vars kein Bootstrap (Test-DB-freundlich).
- T6 `_admin: User = Depends(require_admin)` mit Underscore-Prefix
  als Argument-Name, damit Ruff/mypy keine Unused-Variable-Warning
  geben (Dependency-Resolution läuft trotzdem).
- T8 Inactivity-Hook: bewusst KEIN `mousemove` und KEIN
  `visibilitychange` (Brief AE-4 explizit) — BroadcastChannel
  synchronisiert Aktivität über Multi-Tabs.
- T10 EmptyState mit optionalem `plannedSprint` (statt String-
  Manipulation pro Stub): `<EmptyState>` zeigt „In Vorbereitung"
  wenn Prop weggelassen.
- T12 Password-Backend von `passlib[bcrypt]` auf direktes `bcrypt`
  umgestellt (Pflicht-Stop in T12 ausgelöst). Befund: passlib 1.7.4
  ist unmaintained seit 2020-10 und inkompatibel mit `bcrypt>=4.1`
  (`detect_wrap_bug`-Init-Test triggert `ValueError` für >72-Byte-
  Test-Secrets, blockiert jeden ersten `hash_password()`-Aufruf).
  Konsequenz wäre gewesen: CLI `hash_password`, `change-password`
  und `reset-password` crashen in Production beim ersten Aufruf.
  Fix: `password.py` direkt auf `bcrypt.hashpw` / `bcrypt.checkpw`;
  `pyproject.toml` ersetzt `passlib[bcrypt]>=1.7` durch
  `bcrypt>=4.2`. API gleich (`hash_password` / `verify_password`),
  Rest des Auth-Stacks unverändert.
