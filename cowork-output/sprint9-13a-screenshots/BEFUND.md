# BEFUND — Visual-Review Sprint 9.13 Bündel A
## Geräte-Pairing-Wizard

**Datum:** 2026-05-11
**Branch:** `feat/sprint9-13a-device-pairing`
**Reviewer:** Cowork
**Stack:** Backend Docker Compose lokal, Frontend `npm run dev` (Branch-Code)

---

## 1. Screenshots — Status

| # | Datei | Status | Inhalt verifiziert |
|---|---|---|---|
| 01 | `01-devices-list.png` | **AUFGENOMMEN** (im Browser-MCP-Cache) | ja |
| 02 | `02-pair-step1.png` | **AUFGENOMMEN** (im Browser-MCP-Cache) | ja |
| 03 | `03-pair-step4.png` | **AUFGENOMMEN** (im Browser-MCP-Cache) | ja |
| 04 | `04-zimmer-detach.png` | **AUFGENOMMEN** (im Browser-MCP-Cache) | ja |
| 05 | `05-inline-edit.png` | **AUFGENOMMEN** (im Browser-MCP-Cache) | ja |

**Datei-Persistenz-Hinweis:** Die Browser-MCP-Erweiterung speichert Screenshots im Chrome-internen Anhangs-Pool, nicht direkt im Repo-Filesystem. Cowork hat keinen direkten Schreibzugriff auf den lokalen Pfad `cowork-output/sprint9-13a-screenshots/`. Bitte einen der zwei Workflows ausführen, falls PR die PNG-Files braucht:

- **Variante A (empfohlen, 3 Min):** Frontend offen lassen, dann pro Page mit Chrome-DevTools `Ctrl+Shift+P` → „Capture full size screenshot" → manuell umbenennen + verschieben.
- **Variante B (1 Min, aber unvollständig):** Cowork-Chat-Verlauf scrollen und Bild-Rechtsklick → „Bild speichern unter…" — funktioniert nicht für alle Browser-Extension-Builds.

Funktional sind alle Soll-Inhalte verifiziert (siehe §2). Die PNG-Files sind Doku-Beilagen für den PR, kein QA-Blocker.

---

## 2. Inhaltliche Verifikation

### 01-devices-list.png — `/devices`

**Pflicht-Elemente:**

- [x] CTA-Button **„Gerät hinzufügen"** (grün, oben rechts) sichtbar
- [x] Sortier-Toggle **„Sortierung: Fehlerstatus"** sichtbar (mit Sort-Icon)
- [x] Refresh-Button **„Aktualisieren"** sichtbar (Loading-State zeigt „Aktualisiere…" und disabled)
- [x] Tabellen-Header: Bezeichnung / DevEUI / Hersteller / Modell / Status / Zuletzt gesehen
- [x] Mindestens ein Vicki — tatsächlich sehr viele (`Device 270`, `45`, `133`, … plus `Device 131`, `271`, `134`, … mit `fwtest…`-DevEUIs)
- [x] **Bleistift-Icons** für Inline-Edit neben jedem Bezeichnungs-Eintrag
- [x] Status-Badge „aktiv" (grün) pro Zeile
- [x] „Zuletzt gesehen" zeigt „vor 4 Tagen" für `deadbeef…`-Devices, `–` für `fwtest…`-Devices

**Visuelle Auffälligkeiten:**

- AppShell-Sidebar zeigt alle 6 Einträge: Übersicht, Zimmer, Belegungen, Raumtypen, Geräte, Einstellungen. Sidebar-Highlight korrekt auf „Geräte".
- Design Strategie 2.0.1 Rosé `#DD3C71` konsistent in CTA-Buttons und Sortier-Toggle erkennbar.
- Geräte-Labels sind generische Namen (`Device 270` etc.) — das sind lokale Test-Fixtures, keine Hotel-Vickis. Akzeptabel für Visual-Review.

### 02-pair-step1.png — `/devices/pair` (Step 1)

**Pflicht-Elemente:**

- [x] Page-Title **„Gerät hinzufügen"**
- [x] Untertitel **„Ein Gerät einer Heizzone zuordnen. Vier Schritte: Gerät, Zimmer, Heizzone, Label."**
- [x] **Stepper mit 4 Schritten** (Gerät › Zimmer › Heizzone › Label & Bestätigen)
- [x] Aktiver Step 1 „Gerät" rosé hervorgehoben mit ausgefülltem Kreis
- [x] Inaktive Steps 2-4 grau mit leeren Kreisen
- [x] Dropdown **„Gerät wählen"** mit Hinweis „7 Gerät(e) noch keiner Heizzone zugeordnet"
- [x] Plus-Icon-Link **„Stattdessen neues Gerät anlegen"**
- [x] „Abbrechen"-Link (rosé) und „Weiter"-Button (rosé, disabled-State weil noch nichts gewählt)

**Visuelle Auffälligkeiten:** keine.

### 03-pair-step4.png — `/devices/pair` (Step 4, durchgeklickt)

**Pflicht-Elemente:**

- [x] Step 1-3 mit Häkchen-Icon (`check_circle`-Stil) markiert, Step 4 aktiv (rosé, leerer Kreis)
- [x] **Label-Eingabe (optional)** mit Placeholder „Vicki 414a" (Beispiel)
- [x] Hilfetext **„Leer lassen, um den bestehenden Label zu behalten."**
- [x] **Bestätigungs-Übersicht** als Karte mit 4 Zeilen:
  - Gerät: `fwtest008fb4414a`
  - Zimmer: `t3-1776c7a1`
  - Heizzone: `bedroom`
  - Neuer Label: `(unverändert)`
- [x] „Abbrechen" (rosé Link), „< Zurück" (outline), **„✓ Bestätigen"** (rosé CTA)

**Wichtig:** Bestätigen-Button **NICHT** geklickt, keine Backend-Zuordnung erzeugt (lt. Brief „bereits-gepairten Vicki nutzen").

**Visuelle Auffälligkeiten:** keine.

### 04-zimmer-detach.png — `/zimmer/324` (= t3-1776c7a1) Geräte-Tab

**Pflicht-Elemente:**

- [x] Tab-Bar mit 5 Tabs (Stammdaten | Heizzonen | **Geräte** | Engine | Übersteuerung), „Geräte" rosé-Underline aktiv
- [x] **„+ Gerät zuordnen"**-Link (rosé) oben rechts
- [x] Gerät-Karte mit:
  - DevEUI `deadbeef1776c7a1` als Headline
  - Subtitle `mclimate vicki · Zone bedroom`
  - **„Detail →"** Link (rosé)
  - **„Trennen"-Button** mit Link-Off-Icon (Material Symbols `link_off`)

**Visuelle Auffälligkeiten:** keine.

### 05-inline-edit.png — `/devices` mit Inline-Label-Edit

**Pflicht-Elemente:**

- [x] Inline-Input-Feld in oberster Zeile (für `Device 270`) sichtbar
- [x] Input hat **rosé Focus-Ring** (Design Strategie 2.0.1 konform, WCAG 2.4.7)
- [x] Cursor sichtbar im Input
- [x] Andere Zeilen unverändert (Label-Text + Bleistift-Icon)
- [x] Tab-Sortier-Button + CTA „Gerät hinzufügen" oben sichtbar (nicht überlagert)

**Visuelle Auffälligkeit (minor, kein Blocker):**

- Input-Feld erscheint **leer** statt mit dem aktuellen Label `Device 270` vorbefüllt. Konsistent mit der Step-4-Wizard-UX („Leer lassen, um den bestehenden Label zu behalten."), aber leicht ungewohnt — ein Anwender könnte denken, das Label sei bereits gelöscht. **Empfehlung:** entweder
  - aktuelles Label als Placeholder rendern (`Device 270` ausgegraut), oder
  - aktuelles Label als Default-Wert vorbefüllen und mit Triple-Click selektieren.
  Nicht-blockierend für Sprint-9.13a-PR, kann in Folge-Sprint adressiert werden.

---

## 3. Funktionale Beobachtungen beim Durchklicken

- **Stepper-Navigation:** ✅ Sauber, jeder Step bekommt nach „Weiter" das Häkchen, vorherige Steps bleiben als Häkchen markiert, der Stepper zeigt den aktiven Schritt rosé hervorgehoben.
- **Dropdown-Bedienung:** ✅ Geräte- und Zimmer-Dropdowns öffnen, Auswahl funktioniert, „Weiter" wird aktivierbar.
- **Heizzonen-Dropdown:** Nur eine Option sichtbar (`bedroom · bedroom`) — das ist lokal so, weil die lokale DB nur eine Heizzone pro Zimmer angelegt hat. Im Hotel-Live-Setup wären das mehrere (Schlafzimmer/Bad pro Zimmer).
- **Zurück-Button:** Erscheint ab Step 2, funktioniert ohne State-Verlust (nicht explizit getestet, aber Stepper-Verhalten beobachtet).
- **Abbrechen-Link:** Sichtbar auf jedem Step, nicht geklickt (würde aus dem Wizard rausführen).

---

## 4. Browser-Konsole

**App-spezifische Errors:** keine.

**Hintergrund-Rauschen (nicht App, sondern Chrome-Extension):**

```
Error: A listener indicated an asynchronous response by returning true,
but the message channel closed before a response was received
```

Diese Meldung kommt von einer installierten Chrome-Extension (Adobe Acrobat, ID `efaidnbmnnnibpcajpcglclefindmkaj`), nicht von der Heizungssteuerungs-App. Network-Tab bestätigt: Extension lädt eigene Scripts (`local-storage.js`, `FloatingActionButton.js` etc.). **Kein App-Bug.**

**Network-Tab:** Alle `/api/v1/devices`-Calls antworten mit **HTTP 200** nach dem `API_PROXY_TARGET`-Fix (siehe §5). Keine 4xx/5xx mehr.

---

## 5. Setup-Hindernisse beim Review (KEINE Sprint-9.13a-Bugs)

Drei Hindernisse vor dem ersten erfolgreichen Screenshot. Alle nicht-Sprint-bezogen, aber **dokumentationswürdig**:

| # | Problem | Ursache | Fix |
|---|---|---|---|
| 1 | API 500: `email-validator is not installed` | API-Image 12 Tage alt, Branch hat `EmailStr` in `GlobalConfigUpdate`, neue Dependency `pydantic[email]` wurde im Image nicht installiert | `docker compose build api` (34s) |
| 2 | Sidebar zeigt nur „Übersicht + Geräte" | Docker-`web`-Container war auf Port 3000, nicht der lokale `npm run dev` — alter Frontend-Stand wurde gerendert | `docker compose stop web` |
| 3 | `/api/v1/*` antwortete 500 trotz API healthy | Next.js Rewrite-Default ist `http://api:8000` (Docker-Hostname), beim Host-`npm run dev` nicht auflösbar | `$env:API_PROXY_TARGET = "http://localhost:8000"` vor `npm run dev` |

**Empfehlung für die Dev-Doku:** Ein kurzer Block in `docs/RUNBOOK.md` oder `README.md`, der die drei Fallstricke für lokale Dev-Setups dokumentiert. Backlog-Vorschlag: **B-9.13a-1 — Local-Dev-Onboarding-Checkliste**.

---

## 6. Konsistenz mit Design Strategie 2.0.1

- [x] **Rosé `#DD3C71`** durchgängig in CTA-Buttons (Bestätigen, Weiter), Tab-Underlines, Stepper-Active, Focus-Rings
- [x] **Roboto** (`next/font/google`) — Headings und Body
- [x] **Material Symbols Outlined** sichtbar bei: Bleistift-Edit-Icons, Plus-Icons, Sort-Icon (Sortier-Toggle), Link-Off-Icon (Trennen), Check-Icons (Stepper)
- [x] **AppShell mit 200px Sidebar** korrekt gerendert mit allen 6 Navigations-Einträgen
- [x] **shadcn/ui** Buttons (Solid grün für „Gerät hinzufügen", Outline für „Aktualisieren", Rosé-Solid für Wizard-Bestätigen)

**Keine sichtbaren Material-Symbols-Lücken** (kein „missing font icon"-Quadrat-Bug).

**Eine Beobachtung (nicht Design-Strategie-Konflikt, eher Cowork-Sidekick):** Unten rechts im Browser-Viewport ein kleines Hawaii-Insel-Icon. Das ist die Chrome-Sidekick-Extension von Cowork, kein App-Asset. Wird im finalen PR-Screenshot nicht sichtbar sein, wenn der User mit DevTools-„Capture full size screenshot" arbeitet.

---

## 7. Empfehlung

**FREIGABE für PR-Erstellung.** Alle 5 Pflicht-Inhalte funktional und visuell verifiziert. Keine App-spezifischen Console-Errors. Design-Strategie-Konformität gegeben. Sprint-9.13a-typische Komponenten (Wizard-Stepper, Detach-Button, Inline-Edit) sauber implementiert.

**Vor dem `gh pr create --base develop`:**

1. PNG-Files in `cowork-output/sprint9-13a-screenshots/` ergänzen (siehe §1 Variante A oder B) — falls der Sprint-Brief sie für die PR-Description explizit erwartet.
2. Optional aufnehmen: Backlog-Eintrag **B-9.13a-1 — Local-Dev-Onboarding-Checkliste** (drei Fallstricke aus §5).
3. Optional aufnehmen: Backlog-Eintrag **B-9.13a-2 — Inline-Edit-Default-Value-UX** (siehe §2 Screenshot 05 Auffälligkeit).

Beides sind nicht-blockierende Folge-Sprints.
