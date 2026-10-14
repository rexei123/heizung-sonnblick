# Sprint 21 — Bedienung (A1-A3 des Hoteliers, B-21-2, plus drei Handlungen, die nichts tun)

**Stand:** 2026-10-14 · **zur Freigabe** · Autonomie-Stufe 2 ·
**zusammengeführte Fassung:** A1-A3 vom Hotelier (Brief 10.10., nachgereicht
13.10.), T1-T4 aus dem Backlog

---

## 0. Wie diese Fassung entstanden ist

Der Sprint-21-Brief des Hoteliers vom **10.10.** ist nie im Repo angekommen.
Ich habe am 13.10. gesucht und nichts gefunden — `docs/features/` endet bei
20f-c, `grep -rln "Sprint 21"` trifft nur `STATUS.md`, und
`git log --all --diff-filter=A -- docs/**` zeigt, dass nie eine solche Datei
angelegt wurde. Daraufhin habe ich eine eigene Fassung aus dem Backlog
gebaut (T1-T4 unten).

**Die Zeile „Brief liegt" in `STATUS.md` stand trotzdem falsch da** — zweimal,
im Kopf und in §1, beide von mir. Sie stammt aus der 20e-c-Zeile („Brief liegt
zur Freigabe vor", dort richtig) und ist beim Nachziehen des Kopfes auf
Sprint 21 mitgewandert. Dass es *einen* Brief gab, war Zufall, nicht Wissen:
die Zeile hat eine Datei im Repo behauptet, und die gab es nicht. §5.26 —
der Kopf von `STATUS.md` ist die Quelle, die die nächste Brief-Verfassung
ungeprüft übernimmt. **T5 korrigiert sie.**

Diese Fassung **ergänzt**: A1-A3 sind die Tasks des Hoteliers und haben
Vorrang, T1 (B-21-2) ist Pflicht, T2-T4 laufen nur bei Zeit.

**Entschieden (13.10., keine Rückfrage mehr nötig):** Lager als kleine Zeile
unter der Kachel · `devices_total` → `devices_assigned`, neu `devices_pool` ·
ein PR je Thema · G1 nach RUNBOOK §10t · bis 01.11. kein Merge-Fenster.

**Drei Prämissen aus A1-A3 halten am Code nicht** — §2.6, §3.2 und §4.2.
Zwei kosten eine Entscheidung (§8), eine nur eine andere Umsetzung.

---

# Teil A — die Tasks des Hoteliers (Pflicht)

## A1 — Zimmer-Verlauf (~5 h, Aufwand belastbar: §2.7)

**Soll:** Zimmerseite, neuer Reiter „Verlauf", Umschalter 24 h / 7 Tage. Je
Zone eine Linie Raumtemperatur, Sollwert als Stufenlinie. Hinterlegte
Bereiche: Belegung und Nachtabsenkung. Backend
`GET /rooms/{id}/history?range=24h|7d`, serverseitig zusammengefasst
(24 h: 10 min, 7 d: 1 h). Decimal als Zahl, TS-Spiegel. Dazu die
recharts-Warnung.

### §2.1 Der Reiter passt ohne Umbau

`frontend/src/app/zimmer/[id]/page.tsx:33` hat heute
`type Tab = "stammdaten" | "zonen" | "geraete" | "engine" | "override"`, und
die Reiter-Leiste rendert über ein Array (Zeile 163). **„verlauf" ist ein
Eintrag in beiden** plus ein Zweig im Inhalt. Die Übersteuerung ist schon
heute der Sonderfall, der ohne Karten-Rahmen rendert (Zeile 189) — der
Verlauf wird genauso behandelt, weil ein Diagramm seinen eigenen Rahmen
braucht.

### §2.2 Serverseitige Zusammenfassung: `time_bucket`, erstmals

`sensor_reading` ist eine Hypertable, und `time_bucket` ist damit verfügbar —
**benutzt wird es im Repo bisher nirgends** (`grep` über
`backend/src/heizung`: keine Fundstelle). Dieser Task führt es ein.

Das ist unkritisch, weil CI dieselbe Datenbank fährt wie der Server:
`.github/workflows/backend-ci.yml:36` → `timescale/timescaledb:latest-pg16`.
Ein `date_trunc`-Ersatz mit Epoch-Arithmetik wäre portabler und unleserlicher;
portabel müssen wir nicht sein.

```
24 h → time_bucket('10 minutes', time)   144 Punkte je Zone
7 d  → time_bucket('1 hour', time)        168 Punkte je Zone
```

Bei zwei bis vier Zonen je Zimmer sind das 300-700 Punkte je Antwort. Ohne
Zusammenfassung wären es bei 10-min-Takt und vier Geräten rund 4000 — der
Grund, warum die Zusammenfassung auf den Server gehört und nicht ins
Diagramm.

### §2.3 Was je Bucket gerechnet wird, und warum

| Reihe | Aggregat | Begründung |
|---|---|---|
| Raumtemperatur je Zone | **Mittel** über die Geräte der Zone | AE-51: die Zone liest als Mittelwert, und die Anzeige darf nicht anders rechnen als die Engine |
| Sollwert je Zone | **Maximum** der gemeldeten `setpoint` | ein Sprung soll sichtbar sein, sobald er an **einem** Gerät ankommt; das Mittel würde eine Änderung verschleifen, solange ein zweites Gerät den Downlink noch nicht abgeholt hat (Class A, §5.71) |

Der Sollwert kommt aus `sensor_reading.setpoint`, also **vom Gerät** — nicht
aus `control_command`. Das ist dieselbe Entscheidung wie bei Regel 3c
(AE-74): gezeigt wird, was am Heizkörper gilt, nicht was die Engine wollte.
Ein nicht angekommener Downlink ist damit im Diagramm **sichtbar** statt
geglättet, und das ist der Zweck der Ansicht.

`Numeric` → Zahl per `field_serializer` wie im Haus üblich
(`schemas/device.py:140,171`). Dazu der strukturelle Test: Decimal als
JSON-**String** war der Hotfix #272, und ein Diagramm mit String-Werten
zeichnet eine Linie auf 0.

### §2.4 Die Nachtabsenkung ist nicht global — sie muss aufgelöst werden

Hier hält die naheliegende Annahme nicht. Die Nachtabsenkung steht **nicht**
in `global_config`, sondern in `rule_config`
(`models/rule_config.py:71-72`) — mit **Geltungsbereich-Kette**
`ROOM > ROOM_TYPE > GLOBAL`, jedes Feld `NULL`-fähig („erben"), optional
saisonal begrenzt, und das Fenster darf über Mitternacht gehen
(`schemas/rule_config.py:13`).

**Folge:** Das hinterlegte Nacht-Band kann das Frontend nicht selbst
berechnen. Es müsste die Kette nachbauen — eine zweite Wahrheit neben der
Engine (§5.53, und B-12a-4 ist genau dieser offene Punkt in anderer Sache).

Der Auflöser existiert: `rules/engine.py:247 _resolve_field(field_name, ctx)`.
Er braucht von `ctx` **nur** `ctx.rule_configs`. Deshalb:

> **A1 extrahiert ihn nach `rules/config_resolve.py` als
> `resolve_rule_field(rule_configs, field_name)`**, `engine.py` behält einen
> Zweizeiler als Hülle.

Der Weg über ein neutrales Modul ist Pflicht und nicht Geschmack: `engine.py`
importiert `services/override_service`, ein Import in die Gegenrichtung wäre
zirkulär (§5.46, derselbe Fall wie `rules/window_state.py`). Abnahme der
Extraktion ist §5.47: **alle bestehenden Layer-2-Tests grün ohne
Anpassung.** Fällt einer, ist die Extraktion nicht verhaltensneutral — dann
Pflicht-Stop statt Test-Anpassung.

Das Band wird in **Ortszeit** gezeichnet (§5.65). Die Antwort trägt deshalb
`timezone` mit; eine Uhrzeit ohne Zone neben einer anderen Uhrzeit ist die
Falle aus §5.79, Teil drei.

### §2.5 Belegungs-Bänder brauchen keinen neuen Pfad

`GET /api/v1/occupancies?from=&to=&room_id=` existiert
(`api/v1/occupancies.py:5`). Die Bänder kommen von dort, nicht aus dem neuen
Endpunkt — ein zweiter Weg zu denselben Zeilen wäre eine zweite Wahrheit für
nichts (§0 S6).

Die Antwort von `/history` trägt damit: `buckets` je Zone, `night_window`
(aufgelöst, Ortszeit, `null` wenn nicht konfiguriert) und `timezone`.
Belegung holt das Frontend selbst.

### §2.6 Die Abnahme, die der Brief nennt, liegt nicht mehr im Fenster

> AK (Brief 10.10.): Zimmer 101, 7 d zeigt Belegungen 05.-07.10. und
> 07.-08.10., Absenkung nachts, Override 06.10. als Sollwert-Sprung.

Am 10.10. reichte ein 7-Tage-Fenster bis zum 03.10. **Heute ist der 14.10.,
das Fenster beginnt am 07.10.** Die Belegung vom 05.-07.10. und der Override
vom 06.10. fallen heraus, und bis A1 live ist (frühestens 15.10.) ist auch
die zweite Belegung am Rand.

Die Abnahme ist damit nicht schwächer zu machen, sondern anders zu legen —
dieselbe Lage wie bei der 3c-Abfrage, die auf ein **festes** Fenster gesetzt
wurde, weil die Köpfe inzwischen im Lager lagen:

1. **Der Beleg wird ein Test, nicht eine Sichtprobe.** Synthetische
   Belegungen, ein Override und eine Nacht in einem festen Fenster; geprüft
   wird, dass die Bänder und der Sollwert-Sprung in der Antwort stehen. Das
   ist reproduzierbar und altert nicht.
2. **Die Sichtprobe prüft, was heute da ist:** Zimmer 101, 7 d — Nacht-Bänder
   an jedem Tag, die aktuell sichtbaren Belegungen, die Linien je Zone.

Wenn Sie **den Beleg vom 05.-08.10. mit eigenen Augen** wollen, braucht der
Endpunkt optionale `from`/`to`-Parameter (**+0,5 h**, und das Diagramm bekommt
dann keinen Umschalter dafür — der Weg wäre `curl` oder die URL). Das ist
Frage 1 in §8.

### §2.7 Die recharts-Warnung: erst messen, dann beheben

> Brief: „recharts-Warnung `width(-1) and height(-1)` beheben (Mindesthöhe
> Container), auch beim bestehenden Diagramm."

**Die Mindesthöhe am Container ist schon da.** Das einzige Diagramm im Repo
(`components/patterns/sensor-readings-chart.tsx`, eingebunden auf der
Geräteseite) sitzt in einem `<div className="h-72 w-full">` (Zeile 58), also
mit fester Höhe, und in einem sichtbaren Abschnitt — nicht in einem
eingeklappten Reiter.

Was **fehlt**, ist etwas anderes: `ResponsiveContainer` hat eigene
`minHeight`/`minWidth`-Eigenschaften, und die sind nicht gesetzt (Zeile 60:
`width="100%" height="100%"`). Das ist die dokumentierte Abhilfe für genau
diese Meldung — die Wrapper-Klasse hilft dem Messer nicht, der beim ersten
Durchlauf noch keine aufgelöste Größe sieht.

**Die Warnung ist im Repo nirgends festgehalten** (`grep` über `docs/`,
`STATUS.md`, `CONTEXT.md`: keine Fundstelle), und ich kann sie ohne laufende
Anwendung nicht reproduzieren. Ich baue deshalb nicht auf Verdacht:

1. Anwendung starten, Geräteseite öffnen, Konsole lesen — **Meldung im
   Wortlaut** notieren (§5.68: eine Warnung, die ich nicht gesehen habe, ist
   eine Behauptung).
2. `minHeight`/`minWidth` setzen, neu messen, **Konsole leer** als Beleg in
   den PR.
3. Bleibt sie, ist die Ursache eine andere (Messung im Playwright-Kontext,
   `ResizeObserver` im Flex-Eltern) — dann berichte ich, statt zu raten.

Der neue Verlauf bekommt die Eigenschaften von Anfang an. Zwei Diagramme,
eine Stelle: der Container-Teil wandert in eine gemeinsame Hülle, damit die
Einstellung nicht an zwei Orten gepflegt wird.

### §2.8 Aufwand A1

| | |
|---|---|
| Endpunkt, Zusammenfassung, Schema, Serializer | 1,5 h |
| `resolve_rule_field` extrahieren (+ Bestandstests als Abnahme) | 0,5 h |
| Reiter, Diagramm, Bänder, Umschalter, TS-Spiegel | 2 h |
| Tests (fester Beleg nach §2.6, Struktur-Test Decimal, e2e-Reiter) | 1 h |
| recharts: messen, setzen, nachmessen | 0,5 h |
| **Summe** | **5,5 h** |

Ihre Schätzung war 5 h. Die halbe Stunde darüber ist die Extraktion aus
§2.4 — ohne sie gäbe es das Nacht-Band nur als Nachbau im Frontend.

---

## A2 — Knopf „Temperatur ändern" (~2 h, belastbar)

**Soll:** Grüner Hauptknopf in der Zimmer-Kopfzeile → Übersteuerungs-Formular.
Bei nicht belegtem Zimmer ausgegraut mit Hinweis „nur bei belegtem Zimmer".
„Übersteuerung sperren" zweitrangig (nur Umriss). „Zimmer löschen" raus aus
der Kopfzeile → Stammdaten, „Gefahrenbereich", mit Bestätigung. Knöpfe nur
für Rollen, die sie benutzen dürfen.

### §3.1 Der Befund stimmt, und er ist derselbe Fehlertyp wie T2

Heute steht in der Kopfzeile (`zimmer/[id]/page.tsx:147-161`) die
Sperr-Umschaltung und daneben **„Zimmer löschen" in Rot** — die
zerstörerischste Handlung der Seite als einer von zwei Knöpfen, und der
häufigste Handgriff („Temperatur ändern") gar nicht, sondern drei Reiter
weiter rechts.

Dazu zwei Handlungen, die ins Leere laufen:

| Heute | Was passiert | Server |
|---|---|---|
| Übersteuerung bei **freiem** Zimmer | Formular öffnet, lehnt erst nach „Anwenden" ab | 409 `ROOM_NOT_OCCUPIED` (`main.py:110`) |
| „Zimmer löschen" als **mitarbeiter** | Dialog öffnet, Löschen schlägt fehl | 403, `delete_room` ist `require_admin` (`rooms.py:312`) |

Das ist §5.77 eine Ebene höher und derselbe Satz wie bei T2: eine Handlung
anzubieten, die nichts tut, kostet beim nächsten Mal Vertrauen in die, die
etwas tut.

### §3.2 Das Ausgrauen hat zwei Wahrheiten — und darf das Gate nicht ersetzen

`RoomRead.status` kommt aus der **persistierten Spalte** `room.status`
(`api/v1/rooms.py`, kein `derive_room_status` im Lesepfad). Das Gate im
Service rechnet dagegen mit `derive_room_status` über die aktiven Belegungen
(§5.53, B-12a-4).

Nachgesehen, wie weit die beiden auseinanderlaufen können:
`heizung.sync_room_statuses` läuft **alle 60 s**
(`tasks/occupancy_status_tasks.py:3`). Das Fenster ist also höchstens eine
Minute — plus der Fall, dass Beat nicht tickt.

**Folge für die Umsetzung, und sie ist nicht verhandelbar:**

> Der ausgegraute Knopf ist ein **Hinweis**, nicht das Gate. Die Behandlung
> von 409 `ROOM_NOT_OCCUPIED` bleibt und wird **besser**, nicht entfernt.

Heute behandelt `manual-override-panel-list.tsx` den Code nicht eigens
(`grep`: keine Fundstelle) — die Ablehnung kommt als allgemeine
Fehlermeldung. A2 rendert sie als Satz, der den Grund nennt. Ein Gate, das
nur in der Oberfläche steht, ist in der Minute nach dem Check-in falsch; und
wer in dieser Minute auf den grauen Knopf drückt, soll den Grund lesen statt
nichts zu sehen.

### §3.3 Rollen: der Server schließt schon ab, die Oberfläche soll es zeigen

`contexts/auth-context.tsx` liefert `user` nach `/me`, `types.ts:604` trägt
`role`. Die Gates sind nachgesehen, nicht vermutet:

| Handlung | Endpunkt | Gate | mitarbeiter |
|---|---|---|---|
| Temperatur ändern | `POST /rooms/{id}/overrides` | `require_mitarbeiter` (`overrides.py:135`) | **ja** |
| Übersteuerung sperren | `PATCH /rooms/{id}/override-block-state` | `require_mitarbeiter` (`rooms.py:220`) | **ja** |
| Zimmer löschen | `DELETE /rooms/{id}` | `require_admin` (`rooms.py:312`) | nein |
| Gerät lösen | `DELETE /devices/{id}/heating-zone` | `require_admin` (`devices.py:473`) | nein |

Das deckt sich mit Ihrer Vorgabe. **Und es ist wichtig, dass es der Server
tut:** das Verstecken eines Knopfes ist keine Zugangsbeschränkung (§5.30).
Weil die vier Gates stehen, ist das Verstecken hier reine Bedienung — es
nimmt eine Sackgasse weg und behauptet keine Sicherheit.

Rollenabhängige Anzeige kommt als Hilfsfunktion
(`darfLoeschen(user)` / `darfTemperaturAendern(user)`), nicht als
`user?.role === "admin"` an vier Stellen — sonst steht die Rollenlogik
verstreut und driftet beim nächsten Gate auseinander.

### §3.4 „Gefahrenbereich" in den Stammdaten

„Zimmer löschen" wandert unter das Stammdaten-Formular, in einen abgesetzten
Abschnitt mit eigener Überschrift. Der Bestätigungsdialog existiert
(`page.tsx:223`, „Endgültig löschen") und zieht mit um. Sichtbar nur für
`admin`.

### §3.5 Aufwand A2

| | |
|---|---|
| Kopfzeile umbauen (Hauptknopf, Sperre als Umriss, Löschen entfernen) | 0,5 h |
| Ausgrauen + Hinweis + 409-Behandlung im Panel | 0,5 h |
| Rollen-Hilfsfunktion und vier Anwendungsstellen | 0,5 h |
| Gefahrenbereich in Stammdaten, Tests (e2e: mitarbeiter sieht kein Löschen) | 0,5 h |
| **Summe** | **2 h** |

---

## A3 — Fehler-Auswahl Geräteliste + klickbare Kacheln (~3 h, belastbar)

**Soll:** Dropdown „Anzeigen": Alle · Funkstille · Batterie niedrig · Zimmer
zu warm · Ventil prüfen (inkl. Ventil schließt nicht) · Im Lager, mit Anzahl
in Klammern. Auswahl in der URL (`?zeige=`), Dashboard-Kacheln verlinken
darauf. Sortierung nach Fehlerstatus bleibt Standard. Konsumenten-Liste im PR.

### §4.1 Die Teile liegen bereit

`devices/page.tsx` hat `useRouter` und `useSearchParams` schon im Einsatz
(Zeile 195-205, für `?sort=`), und `useDevices()` liefert die **ganze** Liste
(B-20c-1 ist behoben). Filtern und Zählen sind damit im Client kostenlos —
keine Endpunkt-Änderung, kein zweiter Abruf.

Die sechs Einträge lesen sich direkt aus den Feldern, die es schon gibt:
`health_state === "silent"` · `battery_state` in warn/kritisch ·
`valve_state === "zimmer_zu_warm"` · `valve_state` in
`{ventil_klemmt_zu, ventil_schliesst_nicht}` · `heating_zone_id === null`.

**Die Zahl in Klammern wird aus derselben Liste gerechnet, aus der die
Tabelle rendert.** Nicht aus den Dashboard-Kacheln: die kommen aus
`dashboard_aggregates` mit eigenen Abfragen, und zwei Zahlen aus zwei Quellen
driften (§5.53). Wo die Kachel zählt und der Filter zählt, muss **eine**
Quelle gewinnen, und auf der Geräteseite ist es die Liste.

**Folge, die benannt gehört:** Kachel und Filter können sich dadurch um
Sekunden unterscheiden (verschiedene Abrufzeitpunkte). Das ist richtig so —
die Alternative wäre, die Liste nach den Kachelzahlen zu biegen.

### §4.2 Der Sortier-Knopf **ist** eine Auswahl — die Prämisse fällt

> Brief: „Der Knopf `Sortierung: Fehlerstatus` ist keine Auswahl → als
> Beschriftung darstellen oder entfernen."

Am Code ist er ein **Umschalter mit zwei Zuständen**
(`devices/page.tsx:234-237`): ein Klick wechselt zwischen Fehlerstatus und
Bezeichnung und schreibt `?sort=label` in die URL.

Dass er wie eine Beschriftung aussieht, hat einen anderen Grund: **er zeigt
den Zustand, nicht die Handlung.** „Sortierung: Fehlerstatus" liest sich als
Aussage; ein Knopf verspricht eine Handlung. Deshalb hat ihn nicht einmal
sein Autor als Auswahl erkannt.

Ihn zu entfernen würde eine Funktion wegnehmen, die es gibt — bei
104 Geräten ist „nach Bezeichnung" der Weg, ein bestimmtes Gerät zu finden.
**Mein Vorschlag:** ein zweites Dropdown daneben, `Sortieren: Fehlerstatus /
Bezeichnung`, gleiche Bauform wie „Anzeigen". Dann lesen sich beide Steuer-
elemente gleich, beide stehen in der URL, und die Sortierung bleibt
auffindbar. Frage 2 in §8.

### §4.3 Kacheln verlinken: `KpiCard` braucht eine Eigenschaft

`KpiCardProps` (`components/patterns/kpi-card.tsx:24`) hat heute
`label, value, subValue, icon, tone, loading, error` — **kein** `href`. A3
ergänzt es: ist es gesetzt, rendert die Karte als `Link`, sonst wie bisher.

Zuordnung Kachel → Auswahl: Geräte online → `funkstille` · Schwache Batterie
→ `batterie` · Ventil prüfen → `ventil` · Zimmer zu warm → `zu-warm`. Die
drei übrigen Kacheln (Belegte Zimmer, Ø Raumtemperatur, Fenster offen,
Letzter Algorithmen-Lauf, Aktive Übersteuerungen) bekommen **kein** `href` —
eine Karte, die manchmal klickbar ist, muss das sichtbar unterscheiden, und
das ist Teil des Tasks (Zeiger, Hover, `aria`).

**Eine neue Eigenschaft, die durchgereicht werden muss — genau B-18-3.**
Läuft T4 nach A3, fällt `href` in dessen Prüfumfang; läuft T4 gar nicht,
bekommt A3 den Durchreich-Test selbst. So oder so steht ein Test dafür im
PR, nicht nur im Typ.

### §4.4 Aufwand A3

| | |
|---|---|
| Auswahl-Dropdown mit Zählern, `?zeige=`, Filterung | 1 h |
| Sortier-Umschalter zum Dropdown (§4.2) | 0,5 h |
| `KpiCard` mit `href` + Verlinkung der vier Kacheln + Unterscheidbarkeit | 1 h |
| Tests (e2e: Kachel-Klick landet gefiltert; Zähler stimmt), Konsumenten-Liste | 0,5 h |
| **Summe** | **3 h** |

---

# Teil B — aus dem Backlog

## T1 — die Kachel zählt Lager mit (B-21-2, Pflicht, 1,5 h)

### Befund

`dashboard_aggregates.count_devices_online` (Zeile 60-78) filtert **nur** auf
`retired_at IS NULL`, zweimal. Ein Ersatzteil im Lager ist korrekt nicht
stillgelegt und korrekt nicht online — es steht damit im Nenner und nicht im
Zähler: **„101 von 104", und die Zahl sagt nicht mehr, ob ein Zimmer
unversorgt ist.** Seit 12.10. keine Theorie: 027, 100 und 056 liegen ohne
Batterien im Lager.

Verschärfend: die Kachel färbt sich bei `online < total` gelb
(`page.tsx:85`) — **Dauer-Warnung für einen Normalzustand**, also §5.79 in
der Oberfläche.

### Soll (entschieden)

| heute | künftig | Bedeutung |
|---|---|---|
| `devices_online` | `devices_online` | zugeordnet **und** online |
| `devices_total` | **`devices_assigned`** | zugeordnet, nicht stillgelegt |
| — | **`devices_pool`** | nicht zugeordnet, nicht stillgelegt |

Grenze ist `heating_zone_id IS NOT NULL`, nicht `mounted_confirmed_at`:
gefragt ist, ob ein **Zimmer** versorgt ist. `_ONLINE_STATES` bleibt
unberührt. Gelb nur noch an `devices_online < devices_assigned`;
`devices_pool` färbt **nie**. Darstellung: `101`, Subline
`von 101 Zimmergeräten`, darunter klein `3 im Lager`.

Der neue Name ist kein Schönheitsschritt: ein Feld, das `total` heißt und
nicht alle zählt, wäre die nächste §5.77-Stelle — in einem Sprint, der genau
diesen Fehlertyp aufräumt.

### Berührte Stellen (gezählt)

`dashboard_aggregates.py` (1), `schemas/dashboard.py` (2),
`api/v1/dashboard.py` (3), `page.tsx` (3), `lib/api/types.ts` (2),
`lib/api/dashboard.ts` (2); Tests: `test_api_dashboard.py` (11),
`test_dashboard_aggregates.py` (3), `test_devices_liste_vollstaendig.py` (3),
e2e `sprint-14c-dashboard` und `sprint-15f-occupancy-import`.

Der Frontend-Spiegel ist **Pflichtbestandteil** (§5.63): ein umbenanntes Feld
ohne Spiegel zeigt `undefined`, und `undefined` rendert als falsche Zahl,
nicht als Fehler.

**Reihenfolge-Hinweis:** T1 berührt `page.tsx` (Kacheln) und A3 ebenfalls
(`href`). Wer zuerst läuft, bestimmt, wer den Konflikt auflöst — §9 sagt,
welche Reihenfolge ich vorschlage und warum.

## T2-T4 — nur bei Zeit (optional, zusammen ~2 h)

| | Befund | Fix |
|---|---|---|
| **T2** (B-20f-3, 0,5 h) | „Stornieren" an jeder Belegungszeile, auch abgelaufenen (`belegungen/page.tsx:246-255`) — wirkt nicht mehr auf die Regelung, ändert nur die Historie | Knopf nur bei `check_out > jetzt`. Kein Server-Gate — sinnlos ist nicht gefährlich, und eine neue Domain-Invariante wäre ein anderer Sprint (§5.51) |
| **T3** (B-20f-2, 0,5 h) | `check_in`/`check_out` sind als timezone-aware **beschrieben** (`schemas/occupancy.py:16-17`), aber nicht geprüft; `curl` ohne `Z` wird angenommen, die Bedeutung entscheidet die Datenbanksitzung | `AwareDatetime` + Test mit naivem Wert. Die RUNBOOK-Beispiele tragen `Z` (Zeile 859, 885) — die Verengung trifft Sie nicht, steht aber im PR-Text |
| **T4** (B-18-3, 1 h) | `NumFieldProps extends Omit<FieldProps,"type">` erbt `hint`; `TimeField` (Zeile 247) reicht vier Props weiter — ein Typ, der mehr verspricht als die Komponente hält, und der Compiler kann es nicht melden | Bestand auflisten, Lücken schließen **oder** die Props aus dem Typ entfernen. Befund mit Datum und Umfang (§5.79) |

T2 und T3 sind derselbe Fehlertyp wie A2 (§3.1). Wenn A1-A3 die Zeit
auffressen, fällt T4 zuerst — es ist das einzige, das nach oben offen ist
(§10 G3).

## T5 — Doku (1 h, läuft mit)

RUNBOOK: Kachel-Bedeutung „Geräte online" neu, §10t um **G1** (unten),
Verlauf-Reiter im Bedien-Teil. `STATUS.md`: §2cd, Kopf nach §5.26 — **inklusive
der falschen Zeile aus §0**. Backlog-Zeilen schließen.

Dazu, als Zugangsregel aus B-18-7 auf uns selbst angewandt:
**`lowMotorConsumption` als Diagnose-Text bekommt eine Nummer.** AE-74 hat
ihn als „eigener Backlog-Punkt" angekündigt und keine Zeile angelegt — ein
Backlog-Eintrag, der nur in einem ADR-Absatz steht, ist keiner. Vorschlag
**B-20e-2**, 🟢, mit dem Befund, dass der Flag im Backend nicht persistiert
ist.

---

## 5. Was dieser Sprint nicht anfasst

- **Keine Migration.** Kein Schema-Eingriff in A1-A3, T1-T5.
- **Keine Engine-Berührung.** Die Extraktion aus §2.4 ist verhaltensneutral
  und wird daran gemessen.
- Kein Downlink, kein Steuerpfad, kein `control_command`.
- Die **Montage-Frage** (`mounted_confirmed_at`) — T1 zählt Zuordnung.
- **Stilllegen** (`retired_at`) bleibt endgültig und außerhalb der Zählung.
- Aus dem Backlog bewusst draußen: B-20f-4 (Paketverlust), B-15b-1 (Mail an
  der Batterie-Stufe, nach §5.73 erst neu zu fassen), B-20c-3/4, B-18-2/6
  (eigene Wartungsblöcke), B-21-1 (nach 01.11.).

## 6. Akzeptanzkriterien

| | Kriterium | Wie geprüft |
|---|---|---|
| **AK 1** | Verlauf Zimmer 101, 7 d: Linien je Zone, Sollwert als Stufe, Nacht-Bänder, sichtbare Belegungen hinterlegt | **Ihre Sicht**; der datierte Beleg als Test (§2.6) |
| **AK 2** | 24 h / 7 d schalten um, Antwort zusammengefasst (144 bzw. 168 Punkte je Zone), Werte als Zahl | Backend-Test + Netzwerk-Ansicht |
| **AK 3** | recharts-Warnung vorher im Wortlaut notiert, nachher Konsole leer | Konsole, beide Male im PR |
| **AK 4** | Zimmer-Kopfzeile: „Temperatur ändern" grün und zuerst, Sperre als Umriss, kein Löschen | Ihre Sicht |
| **AK 5** | Freies Zimmer: Knopf grau mit Hinweis; wird trotzdem gesendet, nennt die Meldung den Grund | Ihre Sicht + Test |
| **AK 6** | Als `mitarbeiter`: kein „Zimmer löschen", kein „Gerät lösen"; „Temperatur ändern" vorhanden | e2e-Test |
| **AK 7** | „Anzeigen"-Auswahl filtert, Zahl in Klammern stimmt mit der Tabelle, Auswahl steht in der URL | Ihre Sicht + Test |
| **AK 8** | Klick auf „Ventil prüfen" landet in der gefilterten Liste; dieselbe Zahl beiderorts bei gleichzeitigem Abruf | Ihre Sicht |
| **AK 9** | Kachel zeigt Zähler und Nenner über zugeordnete Geräte, Lager als Zeile darunter, **kein Gelb** bei allen online | Ihre Sicht |

**Zu AK 9, ehrlich:** Welche Zahlen dort stehen, kann ich nicht vorhersagen —
kein Zugriff auf die Produktionsdatenbank, und jede Zahl hier wäre eine
Behauptung über einen Server-Zustand (§5.68). Nach Ihrem Stand vom 12.10.
(027, 100, 056 im Lager) ist „von 101" plus drei zu erwarten. Die Probe ist
nicht die Zahl, sondern ob Zähler und Nenner gleich sind, wenn kein Zimmer
unversorgt ist.

## 7. Aufwand gesamt

| Task | | Aufwand |
|---|---|---|
| **A1** | Zimmer-Verlauf | 5,5 h |
| **A2** | Temperatur ändern | 2 h |
| **A3** | Fehler-Auswahl, klickbare Kacheln | 3 h |
| **T1** | B-21-2 Geräte online | 1,5 h |
| **T5** | Doku (verteilt auf die PRs) | 1 h |
| | **Pflicht** | **13 h** |
| T2-T4 | optional | +2 h |

Fünf PRs (A1, A2, A3, T1, Rest gebündelt), fünf Neustarts des Stacks — bis
01.11. ohne Fenster, aber §0.3 gilt bei jedem.

## 8. Zwei offene Fragen

1. **A1-Beleg (§2.6):** reicht der feste Beleg als Test plus Sichtprobe auf
   den heutigen Stand — oder wollen Sie `from`/`to` am Endpunkt, um
   05.-08.10. selbst anzusehen (+0,5 h)?
2. **Sortier-Knopf (§4.2):** er **ist** ein Umschalter. Zweites Dropdown
   „Sortieren" neben „Anzeigen" (mein Vorschlag) — oder soll er wirklich
   verschwinden, und die Sortierung nach Bezeichnung mit ihm?

## 9. Reihenfolge-Vorschlag

Steht als eigene Nachricht an den Hotelier, zusammen mit dem PR.

## 10. Risiken

**G1 — Ein zugeordnetes Gerät, das jemand ins Lager legt, verschwindet aus
der Kachel.** Heute fiele es als `silent` im Nenner auf; nach T1 aus Zähler
**und** Nenner, und die Kachel bleibt grün. Gewollt (ein Gerät ohne Zimmer
sagt nichts über ein Zimmer) und trotzdem ein Sichtverlust: wer ein Gerät
abzieht, **ohne** Ersatz zuzuordnen, sieht den unversorgten Heizkörper dort
nicht. Gegenmittel ist vorhanden — `/devices` zeigt Geräte ohne Zone, und
nach A3 mit einem Klick (`?zeige=lager`). **Nach RUNBOOK §10t, entschieden
13.10.**

**G2 — Die Umbenennung in T1 trifft elf Dateien**, davon sechs Tests und zwei
e2e-Specs. Ein vergessener Spiegel zeigt `undefined`, und das rendert als
Zahl (§5.63, der Live-Bug über drei Tage). Gegenmittel: `grep` auf beide
alten Feldnamen als letzter Schritt, Ergebnis in den PR-Text.

**G3 — T4 ist nach oben offen.** Mehr als zwei oder drei Lücken: ich liefere
die **Liste** und schließe nur, was der Hotelier bedient (Einstellungen,
Belegungen); der Rest wird Backlog mit Datum und Umfang. Melden statt
ausdehnen (§0 S6).

**G4 — Die Extraktion in §2.4 berührt die Engine.** Sie ist
verhaltensneutral, aber sie liegt in `rules/engine.py`. Abnahme ist §5.47:
alle Layer-2-Tests grün **ohne Anpassung**. Fällt einer, Pflicht-Stop — kein
Nachziehen von Tests im selben Schritt.

**G5 — Zwei PRs fassen `page.tsx` an** (T1 und A3). Kein inhaltlicher
Konflikt, aber ein textueller; §9 legt die Reihenfolge so, dass er einmal und
am kleineren Diff auftritt.

**Kein S1-S6-Fall.** Kein Steuerpfad, keine Migration, kein Downlink. Die
einzige Stelle mit Außenwirkung ist T3 (eine Eingabe-Validierung verengt
sich, nur auf dem `curl`-Weg).
