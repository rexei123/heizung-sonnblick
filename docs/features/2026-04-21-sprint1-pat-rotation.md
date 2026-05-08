> **Historisch (Stand 2026-05-07).** Diese Datei dokumentiert einen
> abgeschlossenen Sprint und ist nicht mehr Bezugsquelle für neue
> Pläne. Maßgeblich sind ab 2026-05-07:
> `docs/ARCHITEKTUR-REFRESH-2026-05-07.md`, `docs/SPRINT-PLAN.md`.

# Sprint 1 — GHCR-PAT rotieren und Rotations-Verfahren dokumentieren

**Typ:** Sicherheits-Hygiene, einmalige Rotation + wiederkehrendes Verfahren
**Ziel:** Exponierter GHCR-PAT ersetzt, minimaler Scope etabliert, Verfahren getestet und in RUNBOOK §6.1 dokumentiert.
**Branch:** `chore/sprint1-pat-rotation` (von `main`)
**Status:** Rotation durchgeführt in Sprint 1.1–1.6 (s. u.). Dieser Brief dokumentiert das Ergebnis + finales Doku-Update.

---

## Feature-Brief (Phase 1)

### Ausgangslage
- Alter GHCR-PAT `claude-sprint2-push` mit breitem `repo`-Scope wurde am 2026-04-20 im Chat exponiert.
- Fine-grained PATs unterstützen GHCR nicht (kein `packages`-Scope auswählbar).
- Deploy-Timer `heizung-deploy-pull.service` authentifiziert sich via `docker login`-Credentials in `/root/.docker/config.json`.

### Ziel
Neuer Classic PAT mit minimalem Scope `read:packages`, auf beiden Servern ausgetauscht, alter Token widerrufen, Verfahren reproduzierbar dokumentiert.

### Akzeptanzkriterien
- [x] Neuer Classic PAT mit **ausschließlich** `read:packages` erzeugt
- [x] `docker login ghcr.io` auf `heizung-test` und `heizung-main` mit neuem Token erfolgreich
- [x] Test-Pull `heizung-api:develop` / `:main` + `heizung-web:develop` / `:main` erfolgreich
- [x] `heizung-deploy-pull.service` manuell getriggert, Result=success auf beiden Servern
- [x] Alter Token `claude-sprint2-push` auf GitHub gelöscht
- [x] `docs/RUNBOOK.md` §6.1 beschreibt das tatsächlich getestete Verfahren (nicht das alte Git-HTTPS-PAT-Verfahren)
- [x] `STATUS.md`: PAT-Warnung in §3.1 entfernt, Sprint 1 dokumentiert
- [ ] PR gemergt, Tag nicht nötig (keine Release-Änderung)

### Abgrenzung — NICHT Teil von Sprint 1
- Kein Austausch anderer Geheimnisse (`POSTGRES_PASSWORD`, `SECRET_KEY`)
- Kein Git-HTTPS-PAT für Server-seitige `git fetch`-Operationen (Repo ist public → kein Token nötig)
- Kein UFW-Hardening auf Main (Sprint 2)

### Risiken
1. **Alter Token bleibt gültig bis Widerruf** → Sprint 1.6 schließt diese Lücke aktiv.
2. **Token-Leak beim Übertragen** → Mitigiert: SecureString-Eingabe, stdin-Pipe, nie als Argv, nie auf Disk.
3. **Fine-grained-PAT-Experiment in Sprint 1.2 schlug fehl** → Dokumentiert, damit nicht wiederholt.

---

## Sprintplan (Phase 2) — bereits ausgeführt

| Sprint | Inhalt | Status |
|---|---|---|
| 1.1 | Plan & Freigabe | ✅ |
| 1.2 | Neuen Classic PAT (`read:packages`) auf GitHub erstellen | ✅ |
| 1.3 | Rotation `heizung-test` via `sprint1.3.ps1` | ✅ |
| 1.4 | Rotation `heizung-main` via `sprint1.4.ps1` | ✅ |
| 1.5 | Verifikation Deploy-Timer beider Server via `sprint1.5.ps1` | ✅ |
| 1.6 | Alten PAT `claude-sprint2-push` auf GitHub gelöscht | ✅ |
| 1.7 | Doku-Update (dieser Commit): Feature-Brief + RUNBOOK §6.1 + STATUS | 🔄 |

---

## Ergebnis

Rotations-Verfahren ist ab jetzt mit drei Skripten reproduzierbar:

```powershell
# Einmalig pro Rotation
$secure = Read-Host -AsSecureString "Neuen PAT einfuegen"
$bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
$env:NEW_PAT = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

.\sprint1.3.ps1   # heizung-test
.\sprint1.4.ps1   # heizung-main
.\sprint1.5.ps1   # Verifikation
Remove-Item Env:NEW_PAT
```

Siehe `docs/RUNBOOK.md` §6.1 für die kanonische Anleitung.
