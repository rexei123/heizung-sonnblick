# Sprint 9.17a — Endpoint-Inventar (T1)

**Stand:** 2026-05-15
**Quelle:** `backend/src/heizung/api/v1/*.py` + Router-Registrierung in `__init__.py`
**Zweck:** Pflicht-Stop nach T1. Soll-Dependency-Spalte vom User freizugeben.

## Regeln (aus Sprint-Brief)

- **Mutierend in `occupancies` / `manual_overrides`** → `require_mitarbeiter`.
- **Alle anderen mutierenden Endpoints** (POST/PUT/PATCH/DELETE) → `require_admin`.
- **Lesende Endpoints (GET)** → `require_user` (Admin ODER Mitarbeiter, neue Dependency, anzulegen in T2).
- **Ausnahmen unauth:** `/api/v1/auth/login`, `/health`. Sonst nichts.
- **Identitäts-kritisch (T3-Spezial):** `/api/v1/auth/me`, `/api/v1/auth/logout`, `/api/v1/auth/change-password`.

## Zusammenfassung

| Router            | Endpoints | aktuell ≠ Soll | Bemerkung                                   |
|-------------------|-----------|----------------|---------------------------------------------|
| auth              | 4         | 0              | T3-Spezial (siehe unten)                    |
| users             | 5         | 0 / **1?**     | GET `/users`: Abweichung vom Brief, siehe Diskussion |
| devices           | 8         | 4              | 4 GET-Endpoints unauth                      |
| global_config     | 2         | 1              | GET unauth                                  |
| heating_zones     | 5         | 2              | 2 GET unauth                                |
| occupancies       | 5         | 2 (+1)         | 2 GET unauth, DELETE-405-Stub (Diskussion)  |
| overrides         | 3         | 1              | 1 GET unauth                                |
| room_types        | 5         | 2              | 2 GET unauth                                |
| rooms             | 6         | 3              | 3 GET unauth (inkl. engine-trace)           |
| rule_configs      | 2         | 1              | GET unauth                                  |
| scenarios         | 3         | 1              | GET unauth                                  |
| **Total**         | **48**    | **17 (+1+1)**  | 17 sicher MISS + 1 DELETE-Stub + 1 GET-`/users`-Diskussion |

Cross-Check zur Lesson §5.30-Schätzung ("~9 GET-Endpoints in 5 Routern"):
real **17 GET-Endpoints in 9 Routern** — die Lesson hat untertrieben.

---

## Router: auth

`prefix="/auth"` — alle hier sind T3-Spezial oder Ausnahmen.

| Methode | Pfad             | aktuelle Dependency       | Soll-Dependency             | Begründung |
|---------|------------------|---------------------------|-----------------------------|------------|
| POST    | `/auth/login`    | rate-limit (slowapi)      | unauth (Brief-Ausnahme)     | Login muss unauth sein, sonst Henne/Ei. |
| POST    | `/auth/logout`   | —                         | unauth (bleibt)             | Cookie-Cleanup ist unschädlich; läuft auch unter `AUTH_ENABLED=false`. |
| GET     | `/auth/me`       | `get_current_user`        | T3-Spezial → 503 unter `AUTH_ENABLED=false`, sonst Cookie-Pflicht | Identitäts-kritisch (B-9.17-10). Cookie-spezifisch, System-User-Fallback liefert falsche Identität. |
| POST    | `/auth/change-password` | `get_current_user` | T3-Spezial → 503 unter `AUTH_ENABLED=false`, sonst Cookie-Pflicht | Identitäts-kritisch (B-9.17-10). Cutover-Bug: vergleicht current_password gegen falschen Hash. |

---

## Router: users

`prefix="/users"` — User-Verwaltung, sensible Daten.

| Methode | Pfad                       | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|----------------------------|---------------------|-----------------|------------|
| GET     | `/users`                   | `require_admin`     | **`require_admin` (Empfehlung)** ⚠️ | Brief-Regel "GET → require_user" passt hier NICHT: User-Liste mit E-Mails, Rollen, is_active ist sensibel. Mitarbeiter sollen keine User-Liste sehen. **Diskussion im Stop-Bericht.** |
| POST    | `/users`                   | `require_admin`     | `require_admin` | Mutating, nicht occupancy/override. |
| PATCH   | `/users/{id}`              | `require_admin`     | `require_admin` | Mutating. |
| POST    | `/users/{id}/reset-password` | `require_admin`   | `require_admin` | Mutating. |
| DELETE  | `/users/{id}`              | `require_admin`     | `require_admin` | Mutating. |

---

## Router: devices

`prefix="/devices"` — Gerät-CRUD + Zeitreihen.

| Methode | Pfad                              | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|-----------------------------------|---------------------|-----------------|------------|
| POST    | `/devices`                        | `require_admin`     | `require_admin` | Mutating. |
| GET     | `/devices`                        | **—** ⚠️            | `require_user`  | Lesend. |
| GET     | `/devices/{id}`                   | **—** ⚠️            | `require_user`  | Lesend. |
| PATCH   | `/devices/{id}`                   | `require_admin`     | `require_admin` | Mutating. |
| PUT     | `/devices/{id}/heating-zone`      | `require_admin`     | `require_admin` | Mutating. |
| DELETE  | `/devices/{id}/heating-zone`      | `require_admin`     | `require_admin` | Mutating. |
| GET     | `/devices/{id}/sensor-readings`   | **—** ⚠️            | `require_user`  | Lesend (Zeitreihen-Daten). |
| GET     | `/devices/{id}/hardware-status`   | **—** ⚠️            | `require_user`  | Lesend (Frontend-Badge, B-LT-2). |

---

## Router: global_config

`prefix="/global-config"` — Hotel-globale Singleton-Konfig.

| Methode | Pfad             | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|------------------|---------------------|-----------------|------------|
| GET     | `/global-config` | **—** ⚠️            | `require_user`  | Lesend (Frontend-Anzeige in Einstellungen). |
| PATCH   | `/global-config` | `require_admin`     | `require_admin` | Mutating. |

---

## Router: heating_zones

`prefix="/rooms/{room_id}/heating-zones"`.

| Methode | Pfad                                       | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|--------------------------------------------|---------------------|-----------------|------------|
| GET     | `/rooms/{room_id}/heating-zones`           | **—** ⚠️            | `require_user`  | Lesend. |
| POST    | `/rooms/{room_id}/heating-zones`           | `require_admin`     | `require_admin` | Mutating. |
| GET     | `/rooms/{room_id}/heating-zones/{id}`      | **—** ⚠️            | `require_user`  | Lesend. |
| PATCH   | `/rooms/{room_id}/heating-zones/{id}`      | `require_admin`     | `require_admin` | Mutating. |
| DELETE  | `/rooms/{room_id}/heating-zones/{id}`      | `require_admin`     | `require_admin` | Mutating. |

---

## Router: occupancies

`prefix="/occupancies"` — Belegungen (operativ → Mitarbeiter darf).

| Methode | Pfad                          | aktuelle Dependency      | Soll-Dependency           | Begründung |
|---------|-------------------------------|--------------------------|---------------------------|------------|
| POST    | `/occupancies`                | `require_mitarbeiter`    | `require_mitarbeiter`     | Mutating, operativ. |
| GET     | `/occupancies`                | **—** ⚠️                 | `require_user`            | Lesend. |
| GET     | `/occupancies/{id}`           | **—** ⚠️                 | `require_user`            | Lesend. |
| PATCH   | `/occupancies/{id}`           | `require_mitarbeiter`    | `require_mitarbeiter`     | Storno-Mutating. |
| DELETE  | `/occupancies/{id}`           | **—** (immer 405)        | `require_mitarbeiter` ⚠️  | DELETE liefert immer 405. Mit Auth wird 401 vor 405 geworfen — konsistenter Stil. **Diskussion.** |

---

## Router: overrides

Kein einheitlicher Prefix — zwei Pfade.

| Methode | Pfad                                | aktuelle Dependency      | Soll-Dependency        | Begründung |
|---------|-------------------------------------|--------------------------|------------------------|------------|
| GET     | `/rooms/{room_id}/overrides`        | **—** ⚠️                 | `require_user`         | Lesend. |
| POST    | `/rooms/{room_id}/overrides`        | `require_mitarbeiter`    | `require_mitarbeiter`  | Mutating, operativ (Brief). |
| DELETE  | `/overrides/{id}`                   | `require_mitarbeiter`    | `require_mitarbeiter`  | Revoke (Mutating, operativ). |

---

## Router: room_types

`prefix="/room-types"`.

| Methode | Pfad                  | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|-----------------------|---------------------|-----------------|------------|
| POST    | `/room-types`         | `require_admin`     | `require_admin` | Mutating. |
| GET     | `/room-types`         | **—** ⚠️            | `require_user`  | Lesend. |
| GET     | `/room-types/{id}`    | **—** ⚠️            | `require_user`  | Lesend. |
| PATCH   | `/room-types/{id}`    | `require_admin`     | `require_admin` | Mutating. |
| DELETE  | `/room-types/{id}`    | `require_admin`     | `require_admin` | Mutating. |

---

## Router: rooms

`prefix="/rooms"`.

| Methode | Pfad                          | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|-------------------------------|---------------------|-----------------|------------|
| POST    | `/rooms`                      | `require_admin`     | `require_admin` | Mutating. |
| GET     | `/rooms`                      | **—** ⚠️            | `require_user`  | Lesend. |
| GET     | `/rooms/{id}`                 | **—** ⚠️            | `require_user`  | Lesend. |
| PATCH   | `/rooms/{id}`                 | `require_admin`     | `require_admin` | Mutating. |
| GET     | `/rooms/{id}/engine-trace`    | **—** ⚠️            | `require_user`  | Lesend (Engine-Decision-Panel). |
| DELETE  | `/rooms/{id}`                 | `require_admin`     | `require_admin` | Mutating. |

---

## Router: rule_configs

`prefix="/rule-configs"`.

| Methode | Pfad                       | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|----------------------------|---------------------|-----------------|------------|
| GET     | `/rule-configs/global`     | **—** ⚠️            | `require_user`  | Lesend. |
| PATCH   | `/rule-configs/global`     | `require_admin`     | `require_admin` | Mutating. |

---

## Router: scenarios

`prefix="/scenarios"`.

| Methode | Pfad                          | aktuelle Dependency | Soll-Dependency | Begründung |
|---------|-------------------------------|---------------------|-----------------|------------|
| GET     | `/scenarios`                  | **—** ⚠️            | `require_user`  | Lesend. |
| POST    | `/scenarios/{code}/activate`  | `require_admin`     | `require_admin` | Mutating. |
| POST    | `/scenarios/{code}/deactivate`| `require_admin`     | `require_admin` | Mutating. |

---

## Diskussions-Items für Stop-Bericht

1. **GET `/users`:** Brief-Regel verlangt `require_user`. Empfehlung: bei `require_admin` belassen, weil User-Liste (E-Mails, Rollen, is_active) sensibel ist und Mitarbeiter dieses Wissen nicht brauchen. Wenn der User die Brief-Regel strikt will, ändern wir auf `require_user`.

2. **DELETE `/occupancies/{id}`:** Aktuell ohne Auth, liefert immer 405. Mit `require_mitarbeiter` wird 401 vor 405 geworfen — kein Sicherheitsrisiko, aber konsistenter Stil. Vorschlag: setzen.

3. **T3-Endpoints:** `/me` und `/change-password` sollen unter `AUTH_ENABLED=false` 503 liefern (B-9.17-10 Fix). `/logout` läuft trotzdem (Cookie-Cleanup). `/login` ist sowieso unauth.

4. **Neue Dependency `require_user`:** muss in `backend/src/heizung/auth/dependencies.py` angelegt werden. Technisch identisch zu aktuellem `require_mitarbeiter` (beide Rollen erlaubt), aber semantisch klar für „lesendes Recht für alle authentifizierten User".
