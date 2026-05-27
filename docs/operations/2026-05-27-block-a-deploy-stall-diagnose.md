# Block-A Deploy-Stall heizung-test — Diagnose (Phantom-Befund)

**Datum:** 2026-05-27
**Branch:** `chore/block-a-deploy-stall-diagnose`
**Basis:** develop @ `57e50c7`
**Typ:** Read-only-Diagnose (kein Server-Eingriff)
**Anlass:** Widerspruch zwischen Übergabe-Brief 2026-05-27 („Live-Deploy
heizung-test bestätigt", Tag `v0.1.19a-cross-sicht-devices`, `897494c`) und
Claude-Code-Aussage im 14a.1-Cowork-Schritt („heizung-test hängt seit
2026-05-23"). Genau eine Aussage muss falsch sein.

---

## 1. Befund (übermittelte Kern-Outputs A1–A7)

> **Provenienz:** SSH-Session des Hoteliers 2026-05-27 ~13:36 CEST (A1–A6) +
> lokale PowerShell 2026-05-27 ~13:35 CEST (A7). Die byte-genauen Roh-Logs
> liegen im Strategie-Chat-Verlauf; hier sind die entscheidungs-relevanten
> Kern-Outputs je Block festgehalten.

**A1 — Server-Repo-Stand:** `git rev-parse HEAD` = **`57e50c7`** (= Doku-PR
#188, aktueller develop-HEAD). Tags `v0.1.19a-cross-sicht-devices` +
`v0.1.19a.1-cross-sicht-hotfix` vorhanden. Working-Tree clean bis auf untracked
Files (separater Hygiene-Punkt, kein Sync-Issue).

**A2 — Deploy-Timer:** `heizung-deploy-pull.timer` **active**; letzter
Service-Run **13:31:21**, `status=0/SUCCESS`.

**A3 — Service-Log (`journalctl`):** seit ~10:40 CEST **lückenlos
erfolgreich**; Working-Tree-Sync `1f6c132 → 57e50c7` um **13:31:16** sauber
durchgelaufen. **Kein Fehler, kein Stall im gesamten Fenster.**

**A4 — Container + Images:** `docker compose`-CLI direkt im
`infra/deploy`-Verzeichnis meldet **`.env not found`** (CLI-Aufruf ohne den
`deploy-pull.sh`-Wrapper). Container laufen via Wrapper dennoch korrekt
(A3 healthy-Reports).

**A5 — Pull-Test:** `docker compose pull api web` → **„No image to be
pulled"** (alles aktuell).

**A6 — Disk + Docker-Storage:** Disk **43 %**; Docker 27 GB Images /
34 GB reclaimable.

**A7 — App-Reality-Check (lokal):** `https://heizung-test.hoteltec.at/devices`
→ **HTTP 200** (Frontend antwortet). `/api/health` → **404** (Health-Route
liegt anderswo — separater Operativ-Punkt, kein Live-Status-Indikator).

---

## 2. Klassifikation pro Block

| Block | Klass. | Kurz |
|---|---|---|
| A1 | 🟢 | Server-HEAD = develop-HEAD `57e50c7`; Tags vorhanden; Tree clean |
| A2 | 🟢 | Timer active, letzter Run 13:31:21 success |
| A3 | 🔴→🟢 | **Killer-Befund:** Log lückenlos erfolgreich, Sync sauber — **kein Stall** |
| A4 | 🟡 | `.env not found` nur bei Direkt-CLI; Wrapper läuft korrekt → operativ |
| A5 | 🟢 | „No image to be pulled" — aktuell |
| A6 | 🟢 | Disk 43 %, Storage unkritisch |
| A7 | 🟢/🟡 | `/devices` 200; `/api/health` 404 (separater Operativ-Punkt) |

---

## 3. Szenario-Einordnung — **eindeutig A**

**A — 14a + 14a.1 sind live; „Block-A" war ein Phantom.**
Beleg: A3 (lückenloser Sync, kein Fehler) + A1 (Server-HEAD = develop-HEAD) +
A7 (Frontend 200). Die Übergabe-Brief-Aussage „Live-Deploy heizung-test
bestätigt" für 14a war **korrekt**. Es gab keinen Deploy-Stall und nie eine
offene Block-A-Diagnose.

---

## 4. Was wirklich passiert ist

Claude Code hat im 14a.1-Cowork-Schritt 2026-05-27 behauptet, „heizung-test
hängt weiterhin auf dem Stand vom 2026-05-23 (Block-A-Deploy-Stall)". A3
widerlegt das: der deploy-pull-Timer lief im fraglichen Zeitraum alle 5 Min
mit `status=0/SUCCESS`, der Working-Tree war seit dem jeweiligen Merge auf
dem korrekten Stand (`1f6c132` ab ~10:40 CEST, danach `57e50c7`).

**Ursachen-Hypothese:** stale Annahme aus einer früheren Session bzw.
Halluzination ohne forensisch klärbare Quelle. Die Behauptung hat 14a.1 in
einen vermeintlichen „Live-Verify pending"-Stop-Zustand versetzt, der real
nicht nötig war (~30 Min Diagnose-Aufwand für einen Phantom-Befund).

---

## 5. Sekundäre operative Befunde (Backlog-Kandidaten, kein 14b-Blocker)

- **B-Ops-1:** `deploy-pull.sh` vs. direktes `docker compose`-CLI — CLI findet
  `.env` im `infra/deploy`-Verzeichnis nicht. Konvention/Wrapper dokumentieren.
- **B-Ops-2:** Working-Tree-Hygiene heizung-test — untracked Verzeichnisse
  (`0003a_stammdaten`, `0003b_event_log`), `backups/`, mehrere `.env.bak-*`
  aus früheren Sprints aufräumen.
- **B-Ops-3:** `celery_beat`-Healthcheck durchgehend „unhealthy" (pre-existing,
  akzeptierter Drift §5.32 — vor Heizperiode klären, trübt das Bild).
- **B-Ops-4:** `/api/health` extern → 404. Echte Route prüfen, dokumentieren
  oder bereitstellen (vgl. B-9.13a-hf2-1 `/api/v1/_meta`-Vorschlag).

---

## 6. Empfehlung

**Kein Fix nötig — kein Re-Trigger, kein 14a.2, kein Infra-Eingriff.** Der
Deploy-Pfad ist gesund. Verbleibende Aktion: rein **optische**
Cowork-Begehung der 4-Spalten-Liste auf
`https://heizung-test.hoteltec.at/devices` (Hard-Reload Strg+Shift+R wegen
Next.js-Cache, B-10-5) — Code-Stand ist identisch zur grünen lokalen
Cowork-Verifikation. B-Ops-1…4 als Backlog, nicht 14b-blockend.

---

## 7. Lesson

CLAUDE.md **§5.68** (operative Aussagen zum Server-State sind Behauptungen,
keine Befunde — vor Brief-Übernahme via Diagnose-Output verifizieren). §5.67
(Tag-mit-Stall + „Live-Verify pending") bleibt gültig für **echte** Stalls;
hier wurde sie auf eine falsche Annahme aufgesetzt.

**Fazit:** Block-A = Phantom. Sprint 14a + 14a.1 sind live-bestätigt. 14b
Phase-0 kann direkt folgen.
