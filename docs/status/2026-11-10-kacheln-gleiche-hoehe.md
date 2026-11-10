---
datum: 2026-11-10
thema: Dashboard — alle Kacheln gleich hoch
pr: 402
---

# Alle Kacheln gleich hoch, und der Wert bricht nicht mehr um

Vorgabe des Betreibers vom 10.11.2026. **Reine Anzeige**, kein Backend-Code
außer einem Kommentar.

## Was geändert ist

| | |
|---|---|
| **Raster** | `auto-rows-fr` — alle Zeilen gleich hoch, nicht nur je Reihe |
| **Karte** | `h-full`, `items-start` (Inhalt oben) |
| **Großer Wert** | `truncate` + `title`, bricht nie um |
| **Fenster offen** | Wert **„inaktiv"**, Zusatzzeile „Erkennung im Gerät ausgeschaltet" |
| **Lade-Skelett** | gleiche Höhe wie die fertige Kachel |
| **Symbol** | `text-2xl` statt `style={{ fontSize: 24 }}` — Token statt Inline-Style |

## Das Lade-Skelett bekommt keine Zahl

Vorher stand dort `h-28`, also **112 px**. Die fertige Karte ist **118**,
seit Sprint 21 die zweite Zusatzzeile dazukam — die Seite ist bei jedem
Aufruf um sechs Pixel gesprungen, und niemand konnte der Zahl ansehen,
woher sie kam.

Jetzt trägt das Skelett **dieselben Typografie-Klassen** wie die echte
Karte (`text-sm`, `text-2xl`, `text-xs`, `text-[11px] leading-tight`) und
je ein `&nbsp;` als Inhalt. Die Höhe ist damit **abgeleitet**: wer eine
Zeile ergänzt, ändert beide Seiten in derselben Änderung.

Ein erster Versuch mit festen Balkenhöhen lag **6,75 px** daneben —
gemessen, nicht geschätzt. Genau das ist der Grund gegen Zahlen an dieser
Stelle.

## Drei Dinge, die erst die Mutationsproben gezeigt haben

**1. `h-full` an den Hüllen tat nichts.** Probe: Klasse entfernt → alle
Tests grün. Ein Rasterkind wird ohnehin auf die Zeilenhöhe gedehnt
(`align-items: stretch`), und damit hat die Hülle die feste Höhe, gegen
die das `h-full` der **Karte** rechnet. Drei Klassen entfernt (§0 S6).

**2. Zwei Tests fehlten.** Die Proben „`title` entfernt" und „ohne
Symbol-Schrift" blieben grün — also gab es für beides keinen Test. Jetzt
gibt es ihn: der Wert trägt seinen vollen Text als `title`, und die
Kacheln bleiben auch ohne geladene Symbol-Schrift gleich hoch.

**3. Meine eigene Begründung für `overflow-hidden` war falsch.** Ich hatte
geschrieben, die Klasse halte die Kachelhöhe unabhängig vom Schriftladen.
Die Probe widerlegt das: Klasse entfernt → neun von neun Tests grün, auch
der mit blockierter Schrift. **Die Höhe hängt an `h-10`**, einer festen
Zahl, und die gilt mit und ohne Schrift. Die Klasse verhindert, dass der
Ligatur-Name während des Ladens sichtbar ins Etikett läuft — Aussehen,
nicht Layout. Kommentar im Code und im Test richtiggestellt.

## Ein Flake, der jetzt erklärt ist

`sprint-14c-dashboard.spec` „Mobile 390px" ist am **08.** und am
**10.11.** im Gesamtlauf gefallen und allein jedes Mal grün. Ursache ist
nicht die Schrift, sondern die **Messung**: zwischen zwei
`boundingBox()`-Aufrufen zeichnet React neu, sobald die Belegungsliste
eintrifft, und der Locator zeigt dann auf ein abgelöstes Element —
`boundingBox()` liefert `null`.

Der neue Helfer misst alle Kacheln in **einem** Durchgang
(`evaluateAll`). Zweimal hintereinander gelaufen: 9/9 grün. Der alte Test
wartet zusätzlich auf `document.fonts.ready`.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| `auto-rows-fr` entfernt | **6 Tests rot** |
| `h-full` an der Karte entfernt | **6 Tests rot** |
| `truncate` am Wert entfernt | **1 Test rot** |
| Skelett zurück auf feste Höhe | **1 Test rot** |
| alter Wortlaut „Erkennung inaktiv" | **1 Test rot** |
| `title` am Wert entfernt | **1 Test rot** (Test danach ergänzt) |
| `h-full` an der Hülle entfernt | **grün — Klasse war wirkungslos, entfernt** |
| `overflow-hidden` entfernt | **grün — meine Begründung war falsch, richtiggestellt** |

## Läufe

* **382 e2e-Tests grün** mit `--workers=1`, wie die CI läuft.
* `tsc` und `eslint` grün.
* Backend: nur ein Kommentar in `test_api_dashboard.py` (der Wortlaut der
  Kachel stand dort). **Docker Desktop war an diesem Vormittag nicht
  gestartet** — die DB-Tests laufen in der CI (§5.50).

## Offen

**Das Etikett „Befehle nicht angenommen" kürzt bei zwei Spalten** auf
„Befehle nicht angenomm…" (768 px, schmalste Kachelbreite). Auf dem
Telefon und am Rechner passt es. Der `title` macht den vollen Text
verfügbar; ein kürzeres Wort wäre die bessere Lösung, und das ist eine
Benennungsfrage für den Betreiber — siehe `tablet.png`.
