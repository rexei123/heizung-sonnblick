# Funk-Empfang: die Kachel, die den Ausfall von heute Morgen gezeigt hätte

**Stand:** 07.11.2026 · Sprint 25 **T8** · PR offen, nicht gemergt

## Der Anlass

Am 07.11.2026 stand die Anlage **31 Minuten** ohne einen einzigen
Messwert. Letzte Meldung 06:21:35Z, erste danach 06:52:46Z. Ursache war
eine Firewall-Regel auf Port 1883, die ich selbst empfohlen hatte
(`docs/status/2026-11-07-vorfall-1883-sperre.md`).

**Kein vorhandener Melder hat angeschlagen**, und das ist der Befund, aus
dem dieser PR entstanden ist:

| Melder | Warum er geschwiegen hat |
|---|---|
| Health-Stufe `silent` | greift erst nach `health_degraded_max_age_h` = **3 h** |
| Funk-Wächter (T6, #390) | urteilt bei zu wenigen Daten `unbekannt` — und ein Totalausfall *erzeugt* genau diesen Zustand |
| Kachel „Thermostate online" | zählt `device.health_state`, also dieselbe 3-Stunden-Grenze |
| ChirpStack-Gateway-Status | das Gateway **war in Ordnung** und hätte grün gezeigt |

Gefunden wurde der Ausfall, weil jemand hingesehen hat. Das ist kein
Überwachungskonzept (§5.76: die Wirkung überwachen, nicht die Mechanik).

## Was gebaut ist

**1. Eine Quelle für Kachel und Alarm** —
`backend/src/heizung/services/funkempfang.py`. Zwei billige Abfragen auf
`sensor_reading`: `max(time)` (rückwärts laufender Index-Scan, jüngster
Chunk) und ein Zähler über die letzten zehn Minuten (Chunk-Exclusion
schließt 189 der 190 Chunks aus). Gelesen wird das **Ende** der Kette,
bewusst nicht der Gateway-Status — Vorgabe des Betreibers und der Kern
der Sache: was nicht ankommt, ist weg, ganz gleich welches Glied es
verloren hat.

**2. Dashboard-Kachel „Funk-Empfang".** Grün „online" bis 5 min, gelb
„verzögert" bis 15 min, rot „keine Meldungen" darüber. Darunter „letzte
Meldung vor X min" und „Y Meldungen in 10 min".

**3. Mail bei Totalausfall** — Beat-Task alle 5 Minuten, Wiederholung
höchstens alle 2 Stunden, Entwarnung wenn Meldungen zurückkommen.

**4. Kachel „Fenster offen" sagt „Erkennung inaktiv"** statt einer 0,
solange kein Gerät seine Fenstererkennung als eingeschaltet
zurückgemeldet hat.

**5. Drei Menüpunkte weg** — „Profile", „Saison", „Gateway". Alle drei
Seiten zeigen nur „In Vorbereitung".

**6. `alert_device_offline_minutes` aus Schema und Formular entfernt**
(B-17-1, B-18-7 Punkt 2). Spalte bleibt.

## Zwei Entscheidungen, die ich gegen die naheliegende Variante getroffen habe

### Der Alarm-Zustand steht in `business_audit`, nicht in Redis

Naheliegend wäre ein Redis-Key mit TTL gewesen — so macht es
`alert_throttle`. Dagegen spricht der Fall, für den der Alarm gebaut ist:
Redis fällt aus. `alert_throttle` ist bewusst **fail-open** (ein
unterdrückter Alarm ist schlimmer als ein doppelter), und bei einem
5-Minuten-Takt wären das **zwölf Mails pro Stunde**, solange Redis weg
ist. Ein Melder, der im Störungsfall Mails spuckt, ist nach dem zweiten
Mal keiner mehr (§5.79).

`business_audit` ist eine Tabelle mit Zeitstempel und überlebt jeden
Neustart. Der Preis ist eine Abfrage pro Takt, also eine alle fünf
Minuten.

### Die gelbe Grenze ist exklusiv, die grüne inklusiv

**Das hat ein eigener Test gefunden, nicht ich.** Bei genau 15:00 war die
Kachel noch gelb, während der Alarm schon gemailt hätte — wer dann
nachsieht, findet eine gelbe Kachel zu einer roten Mail. Grün bleibt
inklusiv, weil es dort nichts kostet und eine Kachel, die bei 5:00 kippt
und bei 4:59 zurückkippt, flackert.

Der Test heißt `test_genau_auf_der_gelben_grenze_ist_schon_rot` und steht
im Repo, damit die Asymmetrie nicht beim nächsten Aufräumen
„vereinheitlicht" wird.

## Die Routen bleiben erreichbar und leiten nicht um

Der Betreiber hat die Wahl mir überlassen. Ein Lesezeichen auf
`/profile` landet weiter auf der Seite, die „In Vorbereitung" sagt — das
ist wahr. Eine Umleitung aufs Dashboard wäre eine stumme Lüge: man
klickt „Profile" und bekommt etwas anderes, ohne Hinweis. Außerdem prüft
`test_handbuch_spiegel.py` beide Richtungen der Zuordnung; Artikel und
Zuordnung bleiben damit unangetastet, entfernt ist nur die
Sichtbarkeit.

## Ein Fund im eigenen Kommentar

Beim Einfügen der Kachel habe ich ans Lade-Skelett (`CARD_META` in
`frontend/src/app/page.tsx`) geschrieben, es zeige „dieselbe Zahl wie der
geladene Stand". **Das war schon vorher nicht wahr:** acht Einträge im
Skelett, zehn Karten in `buildCards` — „Ventil prüfen" und „Zimmer zu
warm" kamen mit Sprint 20e und sind nie eingetragen worden. Daneben stand
ein Kommentar, der die Synchronität ausdrücklich behauptete.

Das ist §5.77 in der unangenehmen Form: nicht eine alte Stelle, die
jemand anders hinterlassen hat, sondern eine Behauptung, die ich **in
derselben Sitzung** geschrieben habe, ohne sie zu prüfen. Gefunden hat
sie ein Zähl-Test, der 11 statt 10 Kacheln sah — und der hätte sie nicht
gefunden, wenn ich die Kachel nicht hinzugefügt hätte.

Beide Einträge sind nachgetragen (Skelett jetzt 10). Die Ausnahme
„Belegungsliste" bleibt beabsichtigt und steht als solche am Array.

## Zwei Doku-Stellen, die das Gegenteil behauptet haben (§5.77)

1. **RUNBOOK §10m** schrieb „Ein Gerät ist über 24 h stumm". Die Grenze
   ist seit Sprint 20e **3 h**.
2. **RUNBOOK §10ab** schrieb „Erwarteter Output bei Stufe-2-Alarm
   (offline > 24h)". Der Alarm hängt am Übergang nach `silent`, also
   ebenfalls an 3 h. Die Zeichenkette `offline_24h` im Code ist ein
   **Name aus Sprint 11**, keine Schwelle — Sprint 20e hat die Grenze
   bewegt, den Namen nicht. Das ist eine eigene Aufgabe, nicht Teil
   dieses PR: die Zeichenkette landet in Logs und in
   Drosselungs-Schlüsseln, ein Umbenennen ist eine Verhaltensänderung
   und gehört in einen eigenen Durchgang.

Die Begründung in B-17-1 trug denselben Fehler („`DEGRADED_MAX_AGE`
24 h") und ist mitkorrigiert.

## Was nicht geprüft ist

**Die zwei DB-Tests in `test_funkempfang.py` sind lokal nicht gelaufen** —
Docker Desktop läuft auf diesem Rechner nicht, §5.50 war also nicht
erfüllbar. 18 von 20 Tests laufen (die beiden DB-Tests werden
übersprungen). **Der Beweis ist die CI**, nicht dieser Satz.

Nicht gebaut und bewusst offen:

* Die Kachel zeigt **keine** Vorgeschichte. Ob der Ausfall vor zehn
  Minuten der erste oder der fünfte heute war, steht nicht da. Dafür
  wäre ein Verlauf nötig, und der kostet mehr als die Kachel wert ist.
* Der Alarm sagt **nicht**, welches Glied gerissen ist. Er sagt, dass
  nichts ankommt, und nennt die Reihenfolge der Prüfschritte — zuerst
  das, was jemand gerade geändert hat. Das ist die Lehre vom 07.11.
* `fenstererkennung_bestaetigt` sieht **7 Tage** zurück. Eine
  Bestätigung vom Juni ist keine Aussage über heute, und ohne Index auf
  `ow_detection_enabled` wäre ein längeres Fenster auch teuer.

## Querverweise

* `docs/status/2026-11-07-vorfall-1883-sperre.md` — der Ausfall
* RUNBOOK §5.0a — die Regel, die aus ihm folgt
* RUNBOOK §10m — Alarm-Übersicht, zwei korrigierte Zahlen
* CLAUDE.md §5.76 (Wirkung statt Mechanik), §5.77 (überholter Vermerk),
  §5.79 (ein Melder, dem niemand glaubt), §5.64 (Zod-Strip — dritte
  Begegnung, diesmal hat der Typecheck sie sofort gemeldet)
