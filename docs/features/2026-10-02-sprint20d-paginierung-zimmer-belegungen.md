# Sprint 20d — Paginierung bei Zimmern, Raumtypen und Belegungen (B-20c-2)

**Typ:** Frontend + Backend (kleiner Endpoint-Eingriff)
**Ziel:** Keine Liste in der Oberfläche schneidet still ab. Zimmer und
Raumtypen werden vollständig geladen, Belegungen echt paginiert mit
Gesamtzahl.
**Branch:** `fix/paginierung-zimmer-belegungen` (von `develop`)
**Frist:** vor dem 01.11.2026, laut Auftrag **direkt nach #251** und vor der
Pilotmontage.
**Autonomie-Stufe:** 2 (Standard). Kein Engine-Pfad betroffen — siehe §1.
**Geschätzte Dauer:** 4–6 h.

---

## 1. Die beauftragte Vorprüfung: liest die Heizlogik Belegungen über die API?

**Nein. Direkt aus der Datenbank, per SQLAlchemy.** Die Steuerung ist von
B-20c-2 **nicht** betroffen.

| Stelle | Zugriff |
|---|---|
| `rules/engine.py:872-876` | `select(Occupancy).where(room_id == …).where(is_active).where(check_out > now).order_by(check_in)` — direkter Select für `ctx.next_occupancy` |
| `services/occupancy_service.py:183` | `derive_room_status` — direkter Select, `limit(1)` |
| `services/occupancy_service.py:122` / `:154` | `next_active_checkout` / `next_active_checkin` — direkte Selects, `limit(1)` |
| `services/occupancy_service.py:268` | `sync_active_rooms` — `distinct()` über **alle** Räume im ±1-Tag-Fenster, **ohne** Limit |
| `tasks/occupancy_status_tasks.py:37` | der Beat-Task ruft denselben Service |
| `services/device_adapter.py:45` | importiert `derive_room_status` / `next_active_checkout` |

Die `limit(1)`-Aufrufe sind **Einzeltreffer-Lookups** („die nächste
Belegung"), keine Paginierungs-Obergrenzen. Sie sind korrekt und bleiben.

**Gegenprobe, die den Befund schließt:** Im gesamten Backend-Produktionscode
gibt es genau **einen** HTTP-Client, und das ist der Dead-Man-Ping an
healthchecks.io (`tasks/engine_tasks.py:191`,
`grep -rn "import httpx|import requests|aiohttp" backend/src/heizung`). Das
Backend ruft seine eigene API nicht auf — es gibt keinen Pfad, auf dem ein
`limit` der Steuerung in die Quere kommen könnte.

**Folge für den Sprint:** reines Oberflächen-Thema. Kein S4-Risiko, keine
Engine-Tests nötig, der Sprint kann neben der Montage laufen.

---

## 2. Ausgangslage

Sprint 20c (B-20c-1) hat gezeigt, dass ein Client, der eine Seite für die
Gesamtmenge nimmt, **nichts meldet — er zeigt einfach weniger**. Bei den
Geräten waren es 100 von 104. Drei weitere Endpoints haben denselben
Default 100, und ihre Aufrufer behandeln ihn uneinheitlich:

| Aufrufer | gesetztes `limit` |
|---|---|
| `app/belegungen/page.tsx:46` (`useOccupancies`) | **200** |
| `app/belegungen/page.tsx:47` (`useRooms`) | 1000 — am `le`-Anschlag |
| `components/patterns/occupancy-form.tsx:36` (`useRooms`) | 1000 — am `le`-Anschlag |
| `app/zimmer/page.tsx:46` (`useRooms`) | 200 |
| `app/devices/pair/page.tsx:72` (`useRooms`) | **keines** → 100 |
| `app/raumtypen/page.tsx:25`, `app/zimmer/page.tsx:45`, `components/patterns/room-form.tsx:30`, `components/patterns/room-type-inline-editor.tsx:33` (`useRoomTypes`) | **keines** → 100 |

Drei verschiedene Zahlen für denselben Endpoint, zwei davon am Maximum, vier
Aufrufer ohne jede Angabe. Das ist kein Entwurf, das ist gewachsen.

**Und ein Fall ist nicht latent, sondern heute scharf.** Die
Belegungen-Seite hat einen Bereichsfilter mit der Option **„Alle"**
(`belegungen/page.tsx:37` gibt kein `from`/`to` zurück) und dazu
`limit: 200`. Messung auf dem Server am 02.10.2026:

```
SELECT count(*) FROM occupancy WHERE is_active;  -->  959
```

**Die Ansicht „Alle" zeigt 200 von 959 Belegungen, ohne das zu sagen.**
759 fehlen. Das ist derselbe Befund wie bei den Geräten, nur vier Mal so
groß und schon länger im Betrieb.

---

## 3. Entscheidungen

### Entscheidung A — Zimmer und Raumtypen: alles holen, wie bei den Geräten

`roomsApi.list` und `roomTypesApi.list` holen alle Seiten, Seitengröße 100
(dieselbe Zahl wie der Server-Default), Abbruch bei kürzerer Seite,
**Fehler** statt Abschneiden oberhalb der Sicherheitsgrenze. `limit` und
`offset` verlassen `RoomListQuery` und `RoomTypeListQuery`, und **alle**
Aufrufer geben ihr eigenes `limit` ab — auch die mit 200 und 1000.

Begründung: Beide Mengen sind **nach oben gebunden**. 45 Zimmer, 103 Zonen,
eine Handvoll Raumtypen; das wächst nur, wenn das Hotel baut. Eine
Oberfläche, die Zimmer blättert, wäre Umstand ohne Gegenwert.

### Entscheidung B — Belegungen: echt paginieren, nicht alles holen

Belegungen wachsen **unbegrenzt** — ein Datensatz je Buchung und Tag, seit
dem 06.06. täglicher Import, heute 959. Sie alle zu laden, wäre dieselbe
Entscheidung wie A, nur mit umgekehrtem Vorzeichen: in einem Jahr sind es
mehrere Tausend, und der Browser lädt sie bei jedem Seitenaufruf.

Also: serverseitig paginiert, Seitengröße 100, **Gesamtzahl vom Endpoint**,
die Oberfläche zeigt „**N von M**" und einen Knopf „**Weitere laden**".
Kein stilles Abschneiden: solange `N < M`, sagt die Seite das.

### Entscheidung C — die Gesamtzahl kommt im Body, nicht im Header

Zwei Wege, und der Unterschied ist nicht Geschmack:

| Weg | Dafür | Dagegen |
|---|---|---|
| `X-Total-Count`-Header | Response-Form bleibt eine Liste, keine Typ-Änderung | **`client.ts` verwirft Header.** `request<T>` gibt nur den geparsten Body zurück (`client.ts:60`) |
| Envelope `{items, total}` | explizit, typisiert, der Compiler erzwingt die Anpassung | Response-Form ändert sich, OpenAPI-Vertrag und Konsumenten ziehen nach |

**Empfehlung: Envelope.** Der Header-Weg ist exakt die Falle aus §5.64: dort
hat `client.ts` das Feld `error_code` verworfen, weil der Wrapper nur
`body.detail` gelesen hat — ein Wert außerhalb des erwarteten Pfades
verschwindet lautlos. Ein Header wäre derselbe Fehler eine Ebene tiefer, und
er fällt erst auf, wenn „N von M" dauerhaft „N von 0" anzeigt.

Der Preis ist klein, weil die Liste **einen** Konsumenten hat: `useOccupancies`
auf der Belegungen-Seite. Ein zweiter Treffer im Backend-Test
(`test_api_read_endpoints_auth.py:297`) prüft nur den Status-Code und ist
nicht betroffen. Die RUNBOOK-Handgriffe zu Belegungen nutzen POST und PATCH,
nicht die Liste (`RUNBOOK.md:860`, `:886`).

Form:

```json
{ "items": [ … ], "total": 959, "limit": 100, "offset": 0 }
```

`limit`/`offset` mit zurückzugeben kostet nichts und macht die Antwort
selbsterklärend — wer sie im Log sieht, weiß, welche Seite er hat.

### Entscheidung D — die Sortierung muss eindeutig werden (nicht im Auftrag, aber Voraussetzung)

**Das ist ein Befund, der die Vorgabe „Sortierung serverseitig" ergänzt.**
Serverseitig ist sie schon — aber nicht **eindeutig**:

```python
stmt = stmt.order_by(Occupancy.check_in).offset(offset).limit(limit)
#                    ^^^^^^^^^^^^^^^^^^ nicht unique
```

`occupancies.py:155`. Viele Buchungen haben denselben `check_in` — bei
45 Zimmern und einem Anreisetag sind das Dutzende. Postgres gibt bei
gleichem Sortierschlüssel **keine garantierte Reihenfolge**; zwischen zwei
Seitenabrufen kann dieselbe Zeile zweimal erscheinen und eine andere
gar nicht.

Bei „alles holen" fällt das nicht auf, weil es nur eine Seite gibt. Mit
„Weitere laden" wird es sichtbar — und zwar als scheinbar sprunghafte
Liste, die niemand einem Sortierschlüssel zuordnet.

**Also: `order_by(Occupancy.check_in, Occupancy.id)`.** Der zweite
Schlüssel ist eindeutig und macht die Ordnung total. Dasselbe gilt für die
Prüfung der beiden anderen Endpoints — sie sind in Ordnung, und das ist
belegt:

| Endpoint | Sortierung | eindeutig? |
|---|---|---|
| `/devices` | `id` | ✅ (20c prüft es) |
| `/room-types` | `id` | ✅ |
| `/rooms` | `floor nullslast, numeric_prefix nullslast, number asc` | ✅ — `Room.number` ist `unique=True` (`models/room.py:44`) |
| `/occupancies` | `check_in` | ❌ **zu reparieren** |

### Entscheidung E — die Sortierrichtung ist eine Produktfrage, keine technische

Heute sortiert die Liste `check_in` **aufsteigend**. Bei Bereich „Alle" und
959 Zeilen heißt das: die erste Seite zeigt die ältesten Belegungen vom
Juni. Mit „Weitere laden" müsste der Hotelier sich bis heute durchklicken.

Vorschlag: bei „Alle" **absteigend** (`check_in DESC, id DESC`) — die
jüngsten und kommenden zuerst. Bei „Heute" und „Nächste 7 Tage" bleibt
aufsteigend richtig, weil das Fenster klein ist und chronologisch gelesen
wird.

**Das ist eine Entscheidung des Hoteliers, nicht meine.** Umgesetzt wird,
was im Gate festgelegt wird; ohne Festlegung bleibt die Richtung wie heute
(aufsteigend überall), und der Hinweis steht dann im STATUS-Eintrag.

---

## 4. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T1** | `/occupancies`: `order_by(check_in, id)` (Entscheidung D) + Envelope `{items, total, limit, offset}`; `total` als `count()` über **dieselben** Filter, in derselben Session. Response-Model `OccupancyListResponse`. | 1 h |
| **T2** | Frontend-Typen + Client: `OccupancyListResponse` in `types.ts`, `occupanciesApi.list` liefert den Envelope. `RoomListQuery`/`RoomTypeListQuery` verlieren `limit`/`offset`. | 0,5 h |
| **T3** | `roomsApi.list` + `roomTypesApi.list` holen alle Seiten (Muster aus `devices.ts`, Sprint 20c). Alle neun Aufrufer von ihrem eigenen `limit` befreien — inklusive `occupancy-form.tsx` (Zimmerauswahl) und `devices/pair/page.tsx`. | 1 h |
| **T4** | Belegungen-Seite: `useInfiniteQuery`, „N von M", „Weitere laden", Knopf verschwindet bei `N === M`. Leerer Zustand und Ladezustand wie bisher. | 1,5 h |
| **T5** | Backend-Tests: Zimmer 101+ über Seiten vollständig; Raumtypen 101+; Belegungen 201+ mit korrektem `total`; **Stabilität der Sortierung** — zwei Seiten bei vielen gleichen `check_in` ohne Dopplung und ohne Lücke (der Test, der ohne T1 rot ist). | 1 h |
| **T6** | e2e: Zimmerliste 101, Raumtypen 101, Belegungen 201 mit „100 von 201" → „Weitere laden" → „200 von 201" → „201 von 201" und Knopf weg. Zimmerauswahl im Belegungs-Formular zeigt alle 101 Zimmer. Mocks werten `limit`/`offset` aus. | 1 h |
| **T7** | Doku: STATUS-Abschnitt, B-20c-2 auf ✅, AE-Eintrag für den Envelope (erste Antwort im Repo, die nicht eine nackte Liste ist — das gehört als Konvention festgehalten, sonst entsteht beim nächsten Endpoint die dritte Form). RUNBOOK-Handgriff zum Zählen. | 0,5 h |

**Gegenprobe als Pflicht (aus 20c übernommen):** vor dem PR wird der alte
Code-Stand wiederhergestellt und belegt, dass die neuen Tests fallen — mit
dem Bild, das der Hotelier gemeldet hat. Ein Regressionstest, der gegen den
Fehler nicht rot ist, prüft nichts (§5.79).

---

## 5. Akzeptanzkriterien

1. Keine Liste in der Oberfläche schneidet ab, ohne es zu sagen. Bei
   Belegungen steht „N von M"; solange `N < M`, gibt es „Weitere laden".
2. Kein Aufrufer von `useRooms` / `useRoomTypes` setzt ein eigenes `limit`;
   die Felder existieren im Query-Type nicht mehr.
3. Die Belegungs-Sortierung ist eindeutig, und ein Test belegt es über
   Seitengrenzen bei gleichem `check_in`.
4. `total` kommt aus denselben Filtern wie `items` — ein Test, der filtert
   und beide gegeneinander hält.
5. Merge-Anker: `collected N = passed + xfailed`, `0 skipped`, `head_sha`
   gegen PR-HEAD, Image-SHA-Beleg. §0.3-Frage vor dem Merge.
6. Live-Verify nach dem Deploy: Belegungen „Alle" zeigt „100 von 959" (oder
   den dann aktuellen Stand), und „Weitere laden" führt bis zur letzten.

---

## 6. Risiken

| Risiko | Einordnung |
|---|---|
| **Envelope ändert einen bestehenden Endpoint-Vertrag.** | Ein Konsument (`useOccupancies`), typisiert, der Compiler findet ihn. Der Auth-Test prüft nur den Status. Niedrig — aber es ist der einzige Teil des Sprints, der eine Schnittstelle bricht, und deshalb T1/T2 zusammen in einem PR. |
| **`count()` als zweite Query je Seitenaufruf.** | `occupancy` hat heute 959 Zeilen; ein `count(*)` mit denselben Filtern ist Millisekunden. Bei sechsstelligen Beständen wäre es zu prüfen — dann ist aber die ganze Ansicht neu zu denken. Kein Thema für diesen Sprint. |
| **`useInfiniteQuery` ist neu im Repo.** | Bisher nur `useQuery`. Ein neues Muster bei TanStack Query, kein neues Paket. Wenn es im Bauen hakt: „Weitere laden" auch mit `useQuery` und eigenem `offset`-State machbar — dann aber ohne Cache-Zusammenführung, also zweite Wahl. |
| **Pilotmontage läuft parallel.** | Der Sprint berührt keinen Engine-Pfad (§1) und keinen Downlink. Das Risiko liegt allein im Merge-Zeitpunkt (§0.3), nicht im Inhalt. |
| **Ein vierter Endpoint derselben Klasse wird übersehen.** | Gesucht wird nach dem **Verhalten**, nicht nach Namen: alle `limit: int = Query` in `api/v1/` plus alle `*Api.list`-Aufrufer. Die Suche nach Symbolnamen hat in #250 vier DB-Tests durchgelassen — in diesem Sprint ist die Inventarliste Teil von T1. |

---

## 7. Was NICHT in diesem Sprint ist

- **`/overrides`** (`limit` default 50, `le` 200) und
  **`/rooms/{id}/engine-trace`** (default 50, `le` 500): beide sind
  bewusst kurze Fenster — ein Trace zeigt die letzten Einträge, keine
  Gesamtliste. Kein stilles Abschneiden, weil niemand dort
  Vollständigkeit erwartet. Wird in T1 im Inventar dokumentiert und
  begründet, nicht geändert.
- **`/devices/{id}/sensor-readings`** (default 100, `le` 1000): dieselbe
  Begründung — eine Zeitreihe ist per Definition ein Fenster.
- Umstellung der übrigen Listen auf den Envelope. Erst wenn ein zweiter
  Endpoint eine Gesamtzahl braucht; S6 (Komplexität trägt Beweislast).

---

## 8. Querverweise

- **B-20c-1** / STATUS §2bu — der Befund bei den Geräten, aus dem dieser
  Sprint folgt. Das Muster in `frontend/src/lib/api/devices.ts` ist die
  Vorlage für T3.
- **B-20c-2** — der Backlog-Eintrag, den dieser Sprint schließt.
- **§5.64** — der Grund für Entscheidung C (ein Wert außerhalb des
  erwarteten Body-Pfades verschwindet im Wrapper).
- **§5.63** — Frontend-Type-Spiegel bei Backend-Schema-Änderung; hier im
  selben Sprint erledigt (T2), nicht im Folge-Sprint.
- **§5.39** — Leftover-Festigkeit der DB-Tests; die Grenzfall-Tests in T5
  rechnen relativ zum Ist-Bestand, wie in 20c.
- **§5.54** — Playwright-Mocks mit Query-String brauchen Regex, nicht Glob.
- **AE-66** — der Belegungs-Import, der die 959 Zeilen erzeugt.
