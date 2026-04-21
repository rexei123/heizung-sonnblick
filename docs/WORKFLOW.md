# Standard-Workflow: Feature-Entwicklung

**Verbindlich ab:** 2026-04-21
**Gilt für:** Jedes neue Feature, jede größere Änderung, jede Teilfunktion dieses Projekts.
**Ausnahmen:** Hotfixes (< 15 Min Arbeit), rein kosmetische Änderungen, Doku-Updates — dafür reicht ein kurzer Commit auf `develop`.

Dieses Dokument ergänzt `SPEC-FRAMEWORK.md` um den konkreten Arbeitsablauf.

---

## Die 5 Phasen

```
Phase 1  →  Phase 2  →  Phase 3      →  Phase 4     →  Phase 5
Definition  Sprintplan   Umsetzung       Abnahme        Merge + Close
(gemeinsam) (Claude)     (Claude solo)   (gemeinsam)    (Claude)
  GATE        GATE          (Branch)       GATE
```

**Gates** = der Anwender muss explizit "frei" sagen, bevor die nächste Phase startet. Keine stillschweigende Freigabe.

---

## Phase 1 — Definition (gemeinsam)

**Ziel:** Das Feature ist so klar beschrieben, dass ein Dritter es umsetzen könnte.

### Ablauf
1. Anwender nennt das Feature grob (ein Satz reicht: "Gäste-Belegung pflegen im Admin").
2. Claude stellt gezielt Rückfragen — kompakt, nicht mehr als 5 auf einmal.
3. Claude erstellt ein **Feature-Brief** als Datei: `docs/features/<YYYY-MM-DD>-<kurzname>.md`

### Pflicht-Inhalte des Feature-Briefs

```
# Feature: <Titel>

## 1. Ziel (1–2 Sätze, aus Anwendersicht)
## 2. Nutzer / Rollen
## 3. Akzeptanzkriterien (als Checkliste, überprüfbar)
## 4. Abgrenzung (Was ist NICHT Teil des Features?)
## 5. Edge Cases und Fehlerfälle
## 6. Datenmodell-Änderungen (falls DB/Prisma betroffen)
## 7. UI-Skizze / Komponenten (falls Frontend betroffen)
## 8. Abhängigkeiten (externe Services, andere Features)
## 9. Risiken
## 10. Offene Fragen / Annahmen
```

### Gate 1: Freigabe durch Anwender
- Anwender liest Feature-Brief
- Gibt schriftlich frei ("freigegeben Phase 1") oder fordert Änderungen
- Erst nach Freigabe → Phase 2

---

## Phase 2 — Sprintplan (Claude)

**Ziel:** Das Feature ist in **kleine, einzeln testbare Sprints** zerlegt.

### Regeln für Sprint-Schnitt
- **Ein Sprint = max. 1 klares Ergebnis**, das einzeln gemergt und getestet werden könnte
- **Dauer:** 30 Min bis max. 2 Std. Arbeitsblock (für Claude)
- **Reihenfolge:** Backend vor Frontend, Datenmodell vor Logik, Logik vor UI
- **Immer zuerst:** Migration + Typen + Tests — danach erst sichtbarer Code
- **Zwischen jedem Sprint:** grüner Build + Commit + Push auf Feature-Branch

### Ablage
`docs/features/<YYYY-MM-DD>-<kurzname>-sprints.md`

### Pflicht-Inhalte pro Sprint

```
## Sprint N: <Kurztitel>

- **Ziel:** <was ist danach funktional vorhanden?>
- **Dateien/Module:** <Pfade>
- **Neue Tests:** <welche Tests werden hinzugefügt>
- **Definition of Done:**
  - [ ] Build grün
  - [ ] Tests grün
  - [ ] Commit gepusht auf <feature-branch>
  - [ ] (wenn serverrelevant) Deploy auf Test-Server, Smoke-Test
- **Rollback:** <wie komme ich zurück?>
- **Geschätzte Dauer:** <min>
```

### Gate 2: Freigabe durch Anwender
- Anwender liest Sprintplan
- Gibt "freigegeben Phase 2" oder fordert Umschnitt
- Erst nach Freigabe → Phase 3

---

## Phase 3 — Umsetzung (Claude autonom auf Feature-Branch)

**Ziel:** Alle Sprints sind abgearbeitet, Feature läuft auf Test-Server stabil.

### Branch-Setup (zu Beginn von Phase 3, einmalig)
- Branch-Name: `feature/<kurzname>` (oder `fix/` / `chore/` je nach Typ)
- Basis: aktueller `develop`
- Push nach GitHub, Feature-Branch wird per GHA gebaut

### Arbeitsweise pro Sprint
1. Claude setzt den nächsten Sprint um (Code schreiben, Tests schreiben)
2. Claude führt lokal aus:
   - `pytest` (Backend) bzw. `npm run build` + `npm test` (Frontend)
   - Lint: `ruff` + `mypy` bzw. `eslint` + `tsc --noEmit`
3. Bei Fehlschlag: Claude fixt eigenständig, bis grün — **ohne Rückmeldung** an Anwender
4. Commit + Push
5. Wenn Sprint server-relevant: Deploy auf Test-Server, Smoke-Test automatisiert
6. Bei Smoke-Test-Fehler: Claude diagnostiziert via Logs, fixt, wiederholt
7. Status-Update im Chat: "Sprint N erledigt, grün, weiter mit Sprint N+1"

### Autonomie-Grenzen (Claude **muss** den Anwender rufen bei)
1. **Hardware-Aktion nötig** — z. B. Gateway-Pairing, physischer Zugriff
2. **Secret-Rotation nötig** — z. B. neuer PAT, neuer SSH-Key
3. **Externer Dienstleister nötig** — DNS-Änderung, Drittservices, Zahlungen
4. **Architektur-Entscheidung** — wenn eine Annahme aus Phase 1 kippt und ein neuer Weg nötig ist, der nicht im Feature-Brief steht
5. **Drei fehlgeschlagene Fix-Versuche** — wenn Claude denselben Fehler dreimal nicht lösen kann, stoppt er und meldet sich

### Automatisiertes Smoke-Testing (verpflichtend bei UI-Features)
- Playwright-Skript unter `frontend/tests/e2e/<feature>.spec.ts`
- Läuft lokal und gegen Test-Server
- Deckt mindestens die Akzeptanzkriterien aus Phase 1 ab

### Sicherheitsregeln während Phase 3
- Keine Merges nach `develop` oder `main` während der Sprints
- Alle Commits ausschließlich auf dem Feature-Branch
- Kein Anfassen von Secrets, `.env`, Keys, Infra-Config außerhalb des Feature-Scopes
- Keine Refactorings außerhalb der berührten Module ("Boy Scout Rule" ist **deaktiviert** in Phase 3)

---

## Phase 4 — Abnahme (gemeinsam)

**Ziel:** Anwender bestätigt, dass das Feature auf dem Test-Server real funktioniert.

### Ablauf
1. Claude meldet: "Alle Sprints grün, Feature auf Test-Server live unter `<URL>`"
2. Claude liefert im Chat:
   - Link zum Feature-Brief
   - Link zum Sprintplan
   - Liste der Commits im Feature-Branch
   - Zusammenfassung: was läuft, was sind bekannte Einschränkungen
   - Smoke-Test-Ergebnis (Playwright-Report, Screenshots falls UI)
3. Anwender testet real auf Test-Server
4. Bei Findings:
   - Anwender meldet konkret: "Fehler bei X, erwartet Y"
   - Claude öffnet **Mini-Sprint** auf demselben Feature-Branch, fixt, testet, meldet zurück
   - Schleife bis Anwender zufrieden

### Gate 4: Freigabe durch Anwender
- Anwender gibt "freigegeben Phase 4 — merge" oder fordert weitere Änderungen
- Erst nach Freigabe → Phase 5

---

## Phase 5 — Merge und Close (Claude)

**Ziel:** Feature ist in `main`, produktiv, dokumentiert, Branch weg.

### Ablauf
1. Feature-Branch mit `develop` synchronisieren (Rebase oder Merge, je nach Historie)
2. Merge `feature/<kurzname>` → `develop`
3. Warten auf grünen CI-Build
4. Test-Server-Deploy beobachten (5-Min-Timer)
5. Smoke-Test auf Test-Server erneut (Automatik)
6. Merge `develop` → `main` (Fast-Forward wenn möglich)
7. Main-Server-Deploy beobachten
8. Health-Check auf Main grün
9. **Doku-Updates** im selben Commit oder direkt danach:
   - `STATUS.md` — neues Feature im Abschnitt "zuletzt erledigt"
   - ggf. `ARCHITEKTUR-ENTSCHEIDUNGEN.md` — falls ADR-relevant
   - ggf. `RUNBOOK.md` — falls neue Betriebs-Hinweise
10. Feature-Branch lokal und remote löschen
11. Abschluss-Meldung an Anwender mit Commit-Hash auf `main`

---

## Wann dieser Workflow NICHT gilt

- **Hotfix** (< 15 Min, akuter Produktivfehler): Kurzer Fix direkt auf `fix/<kurzname>` → Test → Main, ohne Feature-Brief, ohne Sprintplan. Muss aber in `STATUS.md` nachgetragen werden.
- **Doku-Änderung** (nur `.md`/`.docx`): Direkt auf `develop` committen.
- **Abhängigkeits-Updates** (`npm update`, `pip upgrade`): Auf `chore/deps-<datum>`, Test-Deploy, dann merge.

---

## Checkliste für den Anwender

Bei jedem neuen Feature nutzt der Anwender diese vier Sätze:

1. **Start:** "Ich möchte Feature X. Bitte Phase 1 starten."
2. **Nach Feature-Brief:** "Freigegeben Phase 1." oder "Bitte ändern: …"
3. **Nach Sprintplan:** "Freigegeben Phase 2. Leg los." oder "Bitte umschneiden: …"
4. **Nach Abnahme:** "Freigegeben Phase 4 — merge." oder "Fix bitte: …"

Claude nutzt genau diese Trigger-Phrasen als Gate-Bestätigung.

---

## Änderungs-Log

| Datum | Änderung | Autor |
|---|---|---|
| 2026-04-21 | Initial-Version (v1.0) | Sonnblick + Claude |
