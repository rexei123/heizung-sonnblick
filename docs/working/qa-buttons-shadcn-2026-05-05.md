# Visuelle QA — Button-Migration auf shadcn/ui

**Datum:** 2026-05-05
**System:** https://heizung-test.hoteltec.at (mit Basic-Auth)
**Auditor:** Browser-Pass mit Chrome-MCP, Computed-Style-Auslese via DevTools-JS
**Geprüfte Pages:** /zimmer, /raumtypen, /belegungen, /einstellungen/hotel, /devices

---

## 1. Übersicht

| Page | primary | add | secondary | destructive | ghost | Auffälligkeiten |
|---|---|---|---|---|---|---|
| /zimmer | — | ✓ | — | — | ✓ (als `<a>`, nicht Button) | "Detail →" ist kein `<Button variant="ghost">`, sondern Plain-Link mit Tailwind-Klassen |
| /raumtypen | ✓ | ✓ | ✓ | ✓ | — | Alle 4 Varianten korrekt; cva-Klassen erkennbar |
| /belegungen | — | ✓ | — | ✓ | — | Tab-Pills "Heute/Nächste 7 Tage/Alle" sind keine Button-Komponenten |
| /einstellungen/hotel | ✓ | — | — | — | — | "Speichern" korrekt primary |
| /devices | — | — | ✓ | — | — | "Aktualisieren" mit Refresh-Icon korrekt secondary |

✓ = entspricht Spec
✗ = weicht ab
— = auf Page nicht vorhanden

**Stichprobe Computed-Styles (von /raumtypen Edit-Form, Doppelzimmer):**

| Button | Variante | bg | color | border | padding | font |
|---|---|---|---|---|---|---|
| Aktualisieren | primary | `rgb(221,60,113)` ✓ | `#fff` ✓ | 0 | `8px 16px` | Roboto ✓ |
| Abbrechen | secondary | transparent ✓ | `rgb(20,23,28)` ✓ | `1px solid rgb(227,229,234)` ✓ | `8px 16px` | Roboto ✓ |
| Löschen | destructive | transparent ✓ | `rgb(224,82,82)` ✓ | `1px solid rgb(224,82,82)` ✓ | `8px 16px` | Roboto ✓ |
| Neuer Raumtyp | add | `rgb(22,163,74)` ✓ | `#fff` ✓ | 0 | `8px 16px` | Roboto ✓ |
| Detail → | (ghost-ähnlich) | transparent ✓ | `rgb(221,60,113)` ✓ | 0 | — | Roboto ✓ |

Alle CSS-Variablen werden korrekt aufgelöst. Schriftart ist `__Roboto_a1d03f` (Next.js next/font, korrekt).

---

## 2. Probleme im Detail

### 2.1 KRITISCH — Focus-Ring fehlt komplett bei allen Button-Varianten

**Page:** alle (geprüft auf /raumtypen, /zimmer)
**Variante:** primary, add, secondary, destructive — alle Button-Komponenten
**Beobachtet:**

Die cva-Basisklasse enthält `focus-visible:outline-none`, aber **keine Ersatz-Ring-Definition** (kein `focus-visible:ring-*`, kein `focus-visible:shadow-*`). Computed-Styles im fokussierten Zustand:

```
outline:        rgba(0,0,0,0) solid 2px       (transparent, unsichtbar)
outlineColor:   rgba(0,0,0,0)
boxShadow:      none
--tw-ring-color: rgba(59,130,246,.5)          (Tailwind-Default, aber nicht angewendet)
--tw-ring-shadow: 0 0 #0000                    (deaktiviert)
```

Ergebnis: **Keyboard-Nutzer sehen keinerlei Fokus-Indikator auf Buttons.**

**Spec verlangt:** Brand-Rosé-Ring (#DD3C71), 2px, mit Offset.
**Severity:** **KRITISCH** (WCAG 2.4.7 Focus Visible — A11y-Verletzung; betrifft Tastatur-/Screenreader-Nutzer)
**Fix:** In der cva-Base-Klasse `focus-visible:outline-none` ersetzen durch:

```ts
"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
```

oder (falls Caddy/CSS-Variablen):

```ts
"focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
```

**Ergänzende Beobachtung:** Auf List-Items (`/zimmer` Zimmer-103-Card, `/raumtypen` Suite-Card) UND auf dem `<a>`-Link "Detail →" ist der Brand-Rosé-Fokus-Ring sichtbar — das funktioniert dort aus globalem CSS (`*:focus-visible { outline: 2px solid var(--color-border-focus); outline-offset: 2px }` aus `globals.css`). Aber die Button-Komponente hat in ihrer cva-Base bewusst `focus-visible:outline-none` gesetzt und damit den globalen Stil deaktiviert, ohne Ersatz.

**Reproduktion:** Auf /raumtypen einen Raumtyp wählen (Doppelzimmer), in das letzte Eingabefeld klicken, dann zweimal Tab drücken → Fokus auf "Aktualisieren". Visuell: kein Ring sichtbar.

---

### 2.2 DISKUSSION — "Detail →" ist `<a>` mit Plain-Tailwind, nicht `<Button variant="ghost">`

**Page:** /zimmer (jede Tabellenzeile)
**Beobachtet:** `<a class="text-xs text-primary hover:underline">Detail →</a>`
**Spec verlangt für ghost:** "Komplett transparent, Brand-Rosé Text, kein Border. Beispiele: Tertiär-Aktionen, Alle ansehen-Links."
**Visuell:** entspricht der Spec (transparent, Brand-Rosé, kein Border) — aber als Link, nicht als Button-Komponente.

**Bewertung:**
- Semantisch korrekt: Navigation gehört zu `<a>`, nicht zu `<button>`. Das ist sogar gut.
- Inkonsequent zur Migration: Wenn ghost als Button-Variante existiert, sollte sie auch dort verwendet werden, wo ein "Button" gewollt ist (z. B. modale Tertiär-Aktionen). Wenn das nicht der Fall ist, ist die ghost-Variante MVP-mäßig ungenutzt.
- Hover unterscheidet sich von der Spec: hier `underline`, Spec sagt "Brand-Rosé Schimmer". Akzeptabel für Links, nicht für Buttons.

**Severity:** **Diskussion** (kein Bug, aber inkonsistent zwischen Spec und Implementierung)
**Empfehlung:** Spec präzisieren: "ghost-Variante gilt für Button-Elemente; Navigation-Links nutzen Tailwind-Utility-Klassen direkt." Oder: ghost-Variante an den Stellen einsetzen, wo es einen echten button-Use-Case gibt (z. B. ein "Alle ansehen"-Toggle).

---

### 2.3 KOSMETISCH — secondary-Border zu blass (border-border = #E3E5EA)

**Page:** /raumtypen, /devices, alle secondary-Buttons
**Beobachtet:** `borderColor: rgb(227, 229, 234)` — sehr helles Grau auf weißem Hintergrund. Der Button "Abbrechen" wirkt fast randlos im Vergleich zu "Aktualisieren" daneben.
**Spec verlangt:** "TRANSPARENTER Hintergrund mit grauem Border, schwarzer Text"
**Visuell:** Border ist da, aber der Kontrast Border-zu-Hintergrund ist niedrig. Auf einem Surface-Alt-Hintergrund (#F0F0F3) wäre er fast unsichtbar.
**Severity:** **kosmetisch**
**Empfehlung:** Optional `border-strong` (#C9CCD3) als Ton wählen, oder `border-2` statt `border-1` für mehr Präsenz.

---

### 2.4 KOSMETISCH — Tab-Pills auf /belegungen sind keine Button-Komponente

**Page:** /belegungen (oben "Heute / Nächste 7 Tage / Alle")
**Beobachtet:** Aktiver Tab "Nächste 7 Tage" hat solid Brand-Rosé Hintergrund mit weißem Text. Inaktive Tabs sind transparent mit dunklem Text.
**Bewertung:** Das ist ein Pill-Toggle/Tab-Pattern, kein klassischer Button. Spec definiert keine "Tab-Pill"-Variante, daher streng genommen kein Verstoß. **Kein Issue.**
**Empfehlung:** Falls in Zukunft mehr solche Toggles auftauchen: eigene Toggle-/SegmentedControl-Komponente einführen, statt Button-Variante zu missbrauchen.

---

## 3. Hover-Test pro Variante

| Variante | Beobachtung | Spec | Status |
|---|---|---|---|
| primary "Aktualisieren" | Hintergrund wechselt von `rgb(221,60,113)` zu `--color-primary-hover` (etwas dunkler) | "etwas dunkler" | ✓ |
| add "Neues Zimmer" | Hintergrund von `rgb(22,163,74)` zu `--color-add-hover` (dunkler) | "etwas dunkler" | ✓ |
| secondary "Abbrechen" | leichter `bg-surface-alt`-Schimmer (= #F0F0F3) | "leichter grauer Schimmer" | ✓ |
| destructive "Löschen" | leichter roter Schimmer | "leicht roter Schimmer" | ✓ |
| ghost "Detail →" (a-Tag) | Underline erscheint, Farbe bleibt | Spec sagt "Brand-Rosé Schimmer" | ✗ leicht abweichend, aber kein Button |

**Befund:** Die echten Button-Varianten haben korrekte Hover-States. Die ghost-Variante (sofern überhaupt vorhanden) wurde im Browser nicht als Button-Komponente angetroffen.

---

## 4. Focus-Ring-Test (Tab-Sequenz)

Geprüft auf /zimmer und /raumtypen.

**/zimmer:**
- Tab durch Sidebar-Links: kein Ring (Sidebar-Items haben `aria-current`-Stil, ist OK)
- Tab durch Filter-Selects: brauner Ring (Browser-Default für `<select>`)
- Tab durch Tabellenzeilen "Zimmer-Nummer 101..145": **Brand-Rosé Ring mit Offset** ✓ (kommt aus globalem `*:focus-visible` aus `globals.css`)
- Tab auf "Detail →"-Link: **Brand-Rosé Ring** ✓ (anchor erbt globalen Stil)
- Tab auf "+ Neues Zimmer" (add-Button): **kein sichtbarer Ring** ✗

**/raumtypen:**
- Tab in Form-Felder: brauner Ring (Browser-Default für `<input>`)
- Tab auf "Aktualisieren" (primary): **kein sichtbarer Ring** ✗
- Tab auf "Abbrechen" (secondary): **kein sichtbarer Ring** ✗
- Tab auf "Löschen" (destructive): **kein sichtbarer Ring** ✗

**Diagnose:** Der Button-Komponente fehlt der Focus-Ring (siehe §2.1). List-Items und einfache Links bekommen ihn aus dem globalen CSS, das von der Button-cva-Base mit `focus-visible:outline-none` deaktiviert wird, ohne Ersatz.

**Severity:** **KRITISCH** (siehe §2.1, A11y-Verletzung)

---

## 5. Plus-Icon-Test bei add-Buttons

Stichprobe: "+ Neues Zimmer" auf /zimmer, "+ Neuer Raumtyp" auf /raumtypen, "+ Neue Belegung" auf /belegungen.

| Kriterium | Beobachtet | Spec | Status |
|---|---|---|---|
| Position | links vom Label | links vom Label | ✓ |
| Icon-Set | `<span class="material-symbols-outlined">add</span>` mit `font-family: "Material Symbols Outlined"` | Material Symbols Outlined | ✓ |
| Größe | `font-size: 18px` (computed) | "etwa 18px" | ✓ |
| Farbe | `color: rgb(255,255,255)` | weiß | ✓ |
| Stil | dünne, geometrische Linien (Outlined-Variante) | dünne Linien, geometrisch | ✓ |

**Befund:** Plus-Icon entspricht der Spec auf allen drei Pages exakt.

---

## 6. ConfirmDialog-Buttons (Löschen-Flow)

Geprüft: /raumtypen → "Doppelzimmer" → "🗑 Löschen"-Button → Dialog öffnet sich.

| Button | Erwartete Variante | Beobachtet | Status |
|---|---|---|---|
| "Abbrechen" | secondary | weiß/transparent, hellgrauer Border, dunkler Text | ✓ |
| "Endgültig löschen" | destructive | transparent, roter Border, roter Text | ✓ |

**Befund:** Beide Dialog-Buttons entsprechen der Spec. Dialog wurde mit Esc geschlossen, keine Datenänderung.

---

## 7. Schrift-Test

Computed `font-family` auf allen Buttons:
```
"__Roboto_a1d03f, __Roboto_Fallback_a1d03f, system-ui, sans-serif"
```

Das ist Next.js `next/font/google` mit Roboto, korrekt geladen. **Kein generic-sans, kein Times-Fallback.** ✓

---

## 8. Padding-Test

Alle 4 cva-Button-Varianten: `padding: 8px 16px`. Wirkt visuell ausgewogen, nicht zu eng, nicht zu luftig. ✓

Add-Variante hat zusätzlich `gap-2` (8px Lücke zwischen Icon und Label), passt visuell.

---

## 9. Gesamturteil

**Migration: erfolgreich, mit einem kritischen A11y-Mangel.**

**Was läuft sehr gut:**
- 5 Varianten visuell sauber unterscheidbar
- Computed-Styles entsprechen den Brand-Tokens (#DD3C71, #16A34A, #E05252, #E3E5EA)
- Roboto korrekt geladen, Material Symbols Outlined korrekt eingesetzt
- Hover-States funktionieren bei allen Button-Varianten
- ConfirmDialog-Buttons spec-konform
- Padding stimmt überall

**Mängel:**

| ID | Schweregrad | Beschreibung |
|---|---|---|
| **B-1** | **kritisch** | Focus-Ring auf allen Button-Varianten fehlt (cva-Base setzt `focus-visible:outline-none` ohne Ersatz). A11y-Verletzung WCAG 2.4.7. |
| **B-2** | Diskussion | "Detail →" auf /zimmer ist Plain-`<a>`, nicht `<Button variant="ghost">`. Spec präzisieren oder Komponente einsetzen. |
| **B-3** | kosmetisch | secondary-Border (`#E3E5EA`) ist sehr blass — auf surface-alt-Hintergrund kaum sichtbar. |

**Empfehlung:**
- B-1 muss vor Produktivbetrieb gefixt werden (1-Zeilen-Patch in der cva-Base-Klasse). Nicht-blockierend für aktuellen Sprint, aber **muss vor MVP-Go-Live** dran.
- B-2 mit Programmierer-KI klären: ist "Detail →" als Link gewollt (semantisch besser) oder ist die Migration unvollständig?
- B-3 optional, kosmetisch.

**Kritischer Fehler:** Nur B-1 (Focus-Ring fehlt). Der Rest ist sauber.

---

*Bericht erstellt im Browser-QA-Pass am 2026-05-05.*
