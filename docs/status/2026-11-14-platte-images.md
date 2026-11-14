---
datum: 2026-11-14
thema: Die Platte war zu 95 % voll — 213 alte Deploy-Images entfernt
pr: offen
---

# Zehn Merges vor dem Stillstand

**Reine Doku.** Der Eingriff am Server ist am 14.11.2026 um 07:30 vom
Betreiber ausgeführt worden; dieser Eintrag hält fest, was gefunden
wurde, was getan wurde und was danach noch offen ist.

## Gefunden am 13.11.2026, bei der Arbeit an etwas anderem

Die Platte war zu **94 %** voll, am nächsten Morgen zu **95 %** — 4,1 GB
frei von 75 GB. Aufgefallen war es niemandem; es gab keinen Melder dafür.

| | vorher |
|---|---|
| Images gesamt | **206 Stück, 48,74 GB** |
| davon `heizung-api` / `heizung-web` | **121 / 121** |
| in Benutzung | **2** |
| Volumes (die Datenbanken) | 12,3 GB, darin `event_log` 11 GB |
| frei | **4,1 GB** |

Jeder Merge erzeugt ein Image-Paar: H-6 gibt jedem Commit seinen eigenen
Tag, und `build-images.yml` vergibt je Image **zwei** Tags, Quell- und
Merge-SHA (§5.4). Bei rund 200 MB marginal je Image kostet ein Merge
etwa **400 MB** — also waren noch **rund zehn Merges** Platz, und für
Montag standen sechs an.

**Was bei 100 % passiert:** Postgres nimmt keine Schreibvorgänge mehr an.
Keine Messwerte, keine Engine-Auswertung, keine Relais-Bestätigungen.

## Das Ergebnis

| | vorher | nachher |
|---|---|---|
| Platte | 95 %, **4,1 GB** frei | **64 %, 27 GB** frei |
| Images | 206, 48,74 GB | **98, 24,83 GB** |
| `heizung-*`-Tags | 242 | **29** (auf 14 Image-IDs) |
| Container | alle Up | alle Up auf `develop-dd6408f` |
| Messwerte in 5 min | — | **50 von 50 Geräten** |

213 Tags gelöscht, Sicherheitsprobe leer, kein Container hat etwas
gemerkt. Die Befehle stehen vollständig in **RUNBOOK §10az**.

## Meine Vorhersage war zu hoch, und warum

Ich hatte **35 bis 45 GB** angekündigt, geworden sind es **27 GB**.

Der Grund: `docker system df` nennt unter „reclaimable" eine Größe, die
**gemeinsame Schichten mehrfach zählt** — vor dem Aufräumen 56 GB bei
48,74 GB Gesamtgröße, also mehr als 100 %. Zwei Images, die sich eine
900-MB-Basisschicht teilen, erscheinen dort als zweimal 900 MB; gelöscht
wird die Schicht aber nur einmal.

**Die Lehre für die nächste Vorhersage:** „reclaimable" ist eine
Obergrenze und keine Schätzung. Die einzige verlässliche Zahl ist `df`
**danach**. Das steht so in §10az.

## Was nach dem Aufräumen offen bleibt

**Es sind weiter 23,88 GB „reclaimable", also 96 % der Images.** Die 29
verbliebenen `heizung-*`-Tags liegen auf 14 Image-IDs, von denen **zwei**
laufen. Eine engere Grenze als sieben Tage würde noch einmal ähnlich
viel freigeben — sieben Tage sind der Preis für den Rückfallweg (§10u,
`PIN_SHA`), und dass dieselbe Menge in einer Woche wieder dasteht, ist
genau der Grund für die Automatisierung.

**`event_log` wächst mit rund 4,8 GB im Monat.** 300 000 Zeilen am Tag,
seit dem 02.10., als mit §5.23 alle Engine-Schichten anfingen, immer zu
schreiben — auch im wirkungslosen Fall:

| Monat | Zeilen |
|---|---|
| Juni–September | 1,7 bis 2,0 Mio je Monat |
| **Oktober** | **9,11 Mio** |
| November (13 Tage) | 3,89 Mio |

Die 27 GB sind damit in etwa **fünf Monaten** aufgebraucht, auch ohne
einen einzigen Merge. Eine Timescale-Verdichtung ist verfügbar
(`timescaledb.license = timescale`, 2.26.3) und steht als Vorschlag;
sie würde die 11 GB auf geschätzt 0,7 bis 1,5 GB bringen, **ohne eine
Zeile zu verlieren**.

## Was als nächstes gebaut wird

**Automatisches Aufräumen im `deploy-pull.sh`** mit zwei Ausnahmen, die
der Handgriff von heute nicht brauchte: der **laufende Tag** und das
**`PIN_SHA`-Ziel** bleiben immer, auch älter als sieben Tage. Steht
`PIN_SHA` auf einem Commit von vor drei Wochen, ist dessen Image das
wichtigste im System.

**Eine Warnung ab 85 % Belegung**, als Kachel und als Mail je Episode mit
Entwarnung — derselbe Weg wie der Fühler-Wächter aus #403, mit dem
Zustand in `business_audit`.

**Warum 85 und nicht 90:** 85 % von 75 GB lassen 11 GB, also rund 25
Merges Vorlauf. Bei 90 % wären es 7,5 GB und 18 Merges — zu knapp, wenn
die Warnung über ein Wochenende liegt.

**Der eigentliche Mangel war, dass es keinen Melder gab.** Die Platte ist
nicht über Nacht vollgelaufen; sie ist monatelang vollgelaufen, und
niemand konnte es sehen. Das ist §5.76 noch einmal, nur mit einer Zahl,
die kein Gerät meldet.
