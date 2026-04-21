# Spec-Framework Heizung Sonnblick

**Verbindlich ab:** 2026-04-21
**Gilt für:** Alle Arbeiten am Repo `heizung-sonnblick` — Mensch und KI-Assistent.
**Änderungen:** Nur per Commit auf `main` mit Begründung in der Commit-Message.

Dieses Dokument definiert die **Regeln und Standards**. Der konkrete **Arbeitsablauf pro Feature** steht in `WORKFLOW.md`. **Was** gebaut wird, steht in `STRATEGIE.md`. **Wie es aussieht** in `Design-Strategie-2.0.1.docx`. **Wie Fehler behoben werden** in `RUNBOOK.md`.

---

## 1. Grundprinzipien

1. **Test vor Main.** Nichts landet auf Main ohne vorherigen Live-Test auf Test-Server.
2. **Klein committen.** Ein Commit = ein nachvollziehbarer Schritt. Kein Sammel-Commit.
3. **Dokumentieren beim Bauen, nicht danach.** `STATUS.md` und Doku werden im selben Commit aktualisiert wie der Code.
4. **Keine Secrets im Repo.** Niemals. Auch nicht "nur kurz zum Testen".
5. **Keine inkrementellen Rescue-Versuche.** Server-Rettung immer komplett nach RUNBOOK §X.
6. **Lesbarkeit vor Cleverness.** Der Code wird in 12 Monaten von jemandem gelesen, der den Kontext nicht kennt.

---

## 2. Session-Start-Ritual (verpflichtend bei jedem neuen Chat)

Bei jedem neuen KI-Chat lädt der Assistent **in dieser Reihenfolge**:

1. `STATUS.md` — aktueller Projektstand
2. `docs/SPEC-FRAMEWORK.md` (dieses Dokument)
3. Bei Infra/Deploy-Arbeit zusätzlich: `docs/RUNBOOK.md`
4. Bei UI-Arbeit zusätzlich: `docs/Design-Strategie-2.0.1.docx`
5. Bei Architekturfragen zusätzlich: `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`

**Der Assistent bestätigt kurz, was gelesen wurde, bevor er Änderungen vorschlägt.**

---

## 3. Task-Format

Jede Aufgabe folgt diesem Schema — in Chat wie in Commits:

```
Ziel:         [Was soll am Ende da sein?]
Annahmen:     [Was nehme ich an, wenn nicht gesagt? Kennzeichnung: [Annahme]]
Umfang:       [Dateien/Module/Services, die berührt werden]
Out of Scope: [Was explizit NICHT gemacht wird]
Risiken:      [Was kann brechen?]
Rollback:     [Wie komme ich im Fehlerfall zurück?]
```

Bei Aufgaben unter 10 Minuten reicht: **Ziel + Rollback**.

---

## 4. Branch- und Commit-Flow

### Branches
- `main` — produktiv, geschützt, nur via PR oder Fast-Forward-Merge aus `develop`
- `develop` — Test-Server-Stand, Integrations-Branch
- `feature/<kurzname>` — einzelne Features, von `develop` abgezweigt
- `fix/<kurzname>` — Bugfixes
- `chore/<kurzname>` — Housekeeping (Cleanup, Deps, CI)

### Commit-Message (Conventional Commits)

```
<type>(<scope>): <kurze beschreibung im imperativ>

[optional: warum, nicht was]
[optional: refs #issue]
```

**Types:** `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `infra`
**Scopes:** `api`, `web`, `db`, `deploy`, `caddy`, `ghcr`, `docs`, `repo`

Beispiel: `feat(api): add room occupancy endpoint`

### Pflicht vor jedem Commit
- Lokaler Build/Test läuft grün
- Keine Secrets, keine `.env`, keine Keys im Diff
- `STATUS.md` aktualisiert, wenn sich Stand ändert

---

## 5. Deploy-Flow

**Zwingende Reihenfolge:**

1. Push auf `develop` → GHA baut Image `develop` → Test-Server zieht automatisch (5-Min-Timer)
2. Smoke-Test auf `https://157-90-17-150.nip.io` — **manuell durch Anwender bestätigt**
3. Erst dann: Merge `develop` → `main` → Image `main` → Main-Server zieht
4. Post-Deploy: Health-Check auf Main, Log-Sichtung `docker compose logs --tail=100`

**Bei Migrationen (Alembic):**
- Immer erst auf Test deployen, Migration beobachten, dann Main
- Nie zwei Migrationen in einem Push bündeln

**Abbruch-Kriterium:** Wenn Test-Server nach Deploy nicht binnen 10 Min `healthy` ist, wird `develop` auf letzten grünen Commit zurückgesetzt, bevor `main` angefasst wird.

---

## 6. Command-Konventionen

Jeder Befehl im Chat wird **eindeutig markiert**:

- **PowerShell (lokal):** Arbeitsrechner `work02`, Windows, Pfade mit `\`
- **SSH-Terminal (Server):** Hetzner-Server oder Tailscale-Host, Linux, Pfade mit `/`
- **Browser:** Web-Konsole (Hetzner, GitHub, Tailscale-Admin)

**Mehrzeilige Server-Kommandos** werden als **ein Block** übergeben (Copy-Paste in einem Rutsch), nicht Zeile für Zeile — siehe Lesson Learned RUNBOOK.

---

## 7. Definition of Done (DoD)

Eine Aufgabe gilt erst als erledigt, wenn **alle** Punkte zutreffen:

- [ ] Code committed und gepusht
- [ ] Lokaler Build grün (Backend: `pytest`; Frontend: `npm run build`)
- [ ] Deploy auf Test-Server erfolgreich, Smoke-Test durchgeführt
- [ ] Doku aktualisiert (`STATUS.md` + ggf. `RUNBOOK.md` / `ARCHITEKTUR-ENTSCHEIDUNGEN.md`)
- [ ] Wenn Main-Relevanz: Deploy auf Main erfolgreich, Health-Check grün
- [ ] Offene Folgeaufgaben als Issue oder in `STATUS.md` Abschnitt 3 erfasst

---

## 8. Dokumentationspflicht

| Situation | Zu aktualisieren |
|---|---|
| Sprint-Ende oder Session-Wechsel | `STATUS.md` |
| Neue Rescue-/Troubleshooting-Erkenntnis | `docs/RUNBOOK.md` |
| Architekturentscheidung (Wahl zwischen Optionen) | `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` (ADR) |
| UI/Design-Abweichung oder -Erweiterung | `docs/Design-Strategie-2.0.1.docx` (Changelog im selben Dokument) |
| Neues verbindliches Arbeitsprinzip | Dieses Dokument (`SPEC-FRAMEWORK.md`) |

**Regel:** Kein Merge in `main` ohne zugehörige Doku-Aktualisierung, wenn die Änderung eine der obigen Kategorien trifft.

---

## 9. Sicherheit und Secrets

- **Secrets-Speicherorte (verbindlich):**
  - Server-Laufzeit: `/opt/heizung-sonnblick/infra/deploy/.env`
  - CI/CD: GitHub Actions Repository Secrets
  - Entwickler-Maschine: `$HOME/.ssh/` (keys), lokale `.env` (nicht getrackt)
- **Rotation-Pflicht:**
  - Sobald ein Token/Key in Chat, Log, Screenshot oder Commit sichtbar wurde → **sofort** rotieren
- **SSH:**
  - Zugang nur über Tailscale (Public-IP + Key als Fallback)
  - Root-Login dauerhaft deaktiviert nach Server-Setup
- **UFW:**
  - Reihenfolge zwingend nach `RUNBOOK §8`, kein `ufw enable` ohne vorherige Allow-Regel für Tailscale

---

## 10. Code-Standards (Kurzverweis)

Vollständige Regeln siehe User-Preferences / interne Richtlinie. Hier nur die verbindlichen Mindeststandards:

### Backend (Python / FastAPI)
- Python 3.12, `ruff` + `black` + `mypy --strict`
- Pydantic v2 für alle Ein-/Ausgabe-Modelle
- SQLAlchemy 2.0 Style, Migrations ausschließlich über Alembic
- Tests für jede neue Route, Coverage-Ziel 80 %

### Frontend (Next.js / TypeScript)
- TypeScript strict, keine `any`, keine `@ts-nocheck`-Neuanlagen
- Design-Tokens aus `tailwind.config.ts`, keine Inline-Styles außerhalb definierter Tokens
- **Material Symbols Outlined** statt Emojis in UI
- Server Components bevorzugt, Client Components nur wenn nötig (`'use client'` bewusst setzen)
- Zod für Formular- und API-Validierung
- Kommunikation: **Deutsch, Sie-Form, aus Hotel-Perspektive neutral**

### Allgemein
- Zentrale Typen/Schemata wiederverwenden, keine Parallel-Definitionen
- Error-Codes sprechend, keine rohen Exceptions nach außen
- Keine toten Debug-Prints / `console.log` im Commit

---

## 11. Umgang mit KI-Assistenz

- **Kein Ja-Sager-Modus:** Der Assistent widerspricht, wenn eine Idee problematisch ist. Bestätigung nur bei tatsächlich guter Lösung.
- **Annahmen transparent machen:** Fehlende Infos werden als `[Annahme]` gekennzeichnet, dann wird weitergearbeitet.
- **Keine halben Lösungen:** Lieber nachfragen und sauber bauen als blind Code ausliefern, der nicht läuft.
- **Verifizieren statt behaupten:** Nach Änderungen Build/Deploy/Test prüfen, bevor "fertig" gemeldet wird.
- **Kein Code ohne Kontext:** Bei unbekannten Dateien erst lesen, dann ändern.

---

## 12. Eskalation und Abbruch

Ein laufender Task wird **abgebrochen**, wenn:

- Ein Rescue-Szenario (Server-Lockout, Datenverlust) droht → Stop, RUNBOOK folgen
- Eine Änderung Secrets exponieren würde → Stop, alternativen Weg finden
- Der Scope während der Arbeit um mehr als 50 % wächst → Neue Task, alte abschließen
- Eine Annahme sich als falsch erweist und die bisherige Arbeit obsolet macht → Rückfrage, nicht weiterbauen

---

## 13. Änderungs-Log dieses Dokuments

| Datum | Änderung | Autor |
|---|---|---|
| 2026-04-21 | Initial-Version (v1.0) | Sonnblick + Claude |

