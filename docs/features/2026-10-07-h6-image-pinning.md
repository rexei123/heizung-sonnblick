# H-6 — Image-Pinning und ein Rückfallpunkt, der den Timer überlebt

**Datum:** 2026-10-07
**Typ:** Infrastruktur (CI-Workflow + Deploy-Skript + Compose-Umgebung)
**Autonomie-Stufe:** 1 (volle Stop-Points) — der Deploy-Pfad ist die Stelle,
an der ein Fehler alle Server gleichzeitig trifft
**Status:** **Brief zur Freigabe.** Nichts umgesetzt.

---

## 0. Warum das vor dem 01.11. gehört

Heute läuft der Betrieb auf einem **gleitenden Tag**. Die Compose-Datei sagt
`ghcr.io/rexei123/heizung-api:${IMAGE_TAG:-develop}`
([docker-compose.prod.yml:171](infra/deploy/docker-compose.prod.yml:171)), und
`IMAGE_TAG` steht in der `.env` auf `develop`. Jeder Timer-Lauf zieht, was
gerade unter diesem Tag liegt.

Zwei Folgen, und die zweite ist die teure:

1. **Es gibt keinen Rückfallpunkt.** Wenn ein Merge die Steuerung bricht,
   ist der Weg zurück „den vorigen Stand wiederfinden und von Hand einen
   anderen Tag setzen" — während die Heizung läuft und der Timer alle fünf
   Minuten erneut `develop` zieht.
2. **Es ist nicht nachweisbar, was läuft.** „Der Server ist auf `develop`"
   sagt nichts darüber, welcher Commit das ist. Der Digest steht in
   `docker images`, aber niemand hält ihn gegen einen Commit. Das ist §5.68
   in der Infrastruktur: eine Aussage über den Server-Zustand, die man nicht
   belegen kann.

In der Heizperiode ist der zweite Punkt der wichtigere. Ein Zimmer, das nicht
heizt, ist kein CI-Problem, und die erste Frage lautet dann „seit wann und
mit welchem Stand".

---

## 1. Phase-0-Quellcheck: was im Repo tatsächlich steht

### 1.1 Was CI taggt

[build-images.yml](.github/workflows/build-images.yml) nutzt
`docker/metadata-action` mit drei Tag-Regeln je Image:

```yaml
tags: |
  type=ref,event=branch                              # -> develop
  type=sha,prefix={{branch}}-,format=short           # -> develop-394a056
  type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}
```

`type=sha` nimmt `github.sha`. Bei einem `push`-Event auf `develop` ist das
**der Commit auf develop** — also genau der, auf den der Server in Phase 1
synct. `format=short` liefert sieben Zeichen.

**Gemessen, nicht angenommen** (in dieser Session, fünf Merges):

| Commit auf develop | Tag im GHCR |
|---|---|
| `8c1de5c` | `develop-8c1de5c` |
| `8366227` | `develop-8366227` |
| `1e337b4` | `develop-1e337b4` |
| `fc8596f` | `develop-fc8596f` |
| `394a056` | `develop-394a056` |

### 1.2 Die Lesson §5.4 beschreibt den alten Fix, nicht eine Notwendigkeit

§5.4 sagt: „`build-images.yml` taggt mit dem push-event-SHA (= Merge-Commit
auf der Ziel-Branch). Eine Logik in `deploy-pull.sh`, die `IMAGE_TAG` aus
`git log -- backend/...` ableitet, findet aber den Source-Branch-Commit."

**Der zweite Satz ist das Problem, nicht der erste.** Der Versuch von
2026-04-30 hat den Tag aus dem *letzten Commit, der backend berührt hat*
abgeleitet — und das ist bei einem Merge ein anderer Commit als der
Merge-Commit selbst.

Der Server kennt den richtigen Wert längst. Phase 1 berechnet ihn:

```bash
NEW_SHA=$(git rev-parse "origin/$TARGET_BRANCH")
```

[deploy-pull.sh](infra/deploy/deploy-pull.sh) — Zeile mit `NEW_SHA`. Daraus
die ersten sieben Zeichen zu nehmen ist der ganze Trick. **Kein `git log`,
kein Pfadfilter, keine Heuristik.**

Damit ist die Aufgabe deutlich kleiner als die Lesson vermuten lässt. Sie
bleibt aber nicht trivial, und zwar wegen 1.3.

### 1.3 Der echte Blocker: nicht jeder develop-Commit hat ein Image

`build-images.yml` hat einen `paths`-Filter:

```yaml
paths:
  - "backend/**"
  - "frontend/**"
  - ".github/workflows/build-images.yml"
```

Ein Merge, der nur `docs/`, `STATUS.md` oder `infra/` berührt, baut **kein
Image**. Es gibt dann keinen Tag `develop-<sha>`, und ein gepinnter Pull
würde fehlschlagen.

**Das ist nicht theoretisch — es ist heute passiert.** PR #269 war ein
Doku-PR: `develop` steht auf `0b5d9de`, einen Tag `develop-0b5d9de` gibt es
nicht. Mit Pinning in der heutigen Form wäre der Deploy seit diesem Merge
rot.

### 1.4 Ein zweiter, bisher unbenannter Umstand

Phase 1 macht `git reset --hard origin/$TARGET_BRANCH`. Der **Working-Tree**
folgt also immer dem Branch-Kopf — und darin stecken die Compose-Datei, die
Caddyfiles, die ChirpStack-TOMLs und die Mosquitto-Config.

**Ein Rückfall, der nur das Image zurückdreht, ist deshalb kein Rückfall.**
Wer auf einen Stand von vorgestern zurückgeht, bekommt die alten Container
mit der neuen Compose-Datei — und wenn dazwischen ein Service dazukam oder
eine Umgebungsvariable ihren Namen geändert hat, startet der Stack nicht oder
startet falsch.

Das steht heute nirgends und ist der Grund, warum Punkt T4 unten den
git-Stand mitpinnt.

### 1.5 Was die Migration dazu sagt

Der Container führt beim Start `alembic upgrade head` aus
([docker-entrypoint.sh](backend/docker-entrypoint.sh)). **Migrationen sind
nicht rückwärts-automatisch.** Ein Rückfall auf ein Image von vor einer
Migration startet gegen ein Schema, das weiter ist als der Code.

Für die Migrationen dieses Herbstes (0023–0027) ist das unkritisch: alle
fügen nur nullable Spalten hinzu, älterer Code liest sie nicht und stört sich
nicht an ihnen. **Als Regel darf das aber nicht gelten**, und der Runbook-Teil
muss es benennen: ein Rückfall über eine Migration hinweg ist ein Handgriff
mit `alembic downgrade`, nicht ein Tag-Wechsel.

---

## 2. Entscheidung, die das Gate braucht: wie jeder Commit zu einem Image kommt

Pinning setzt voraus, dass es für **jeden** develop-Commit ein Image gibt.
Drei Wege.

| Weg | Dafür | Dagegen |
|---|---|---|
| **A: `paths`-Filter entfernen** — jeder Push auf develop/main baut | Die Invariante „jeder Commit hat ein Image" gilt ohne Ausnahme. Keine Auflösungslogik im Deploy-Skript. Präzedenzfall vorhanden: §5.55 Nachtrag hat genau aus diesem Grund die `paths`-Filter aus den CI-Workflows entfernt | Rund 2–3 min Build je Doku-Commit. GHCR füllt sich schneller (heute 4 Tags je Merge-Serie) |
| **B: Tag auflösen** — neuesten Commit ≤ HEAD finden, der ein Image hat | Keine zusätzlichen Builds | Das Deploy-Skript muss die Registry abfragen (`docker manifest inspect` in einer Schleife) oder `git log -- backend/ frontend/` benutzen. Letzteres ist **genau die Heuristik, die 2026-04-30 gescheitert ist** |
| **C: Digest statt Tag pinnen** — Compose auf `@sha256:…`, Digest in einer Datei | Exakteste Form, unabhängig von Tag-Vergabe | Der Digest ist nicht lesbar und nicht auf einen Commit zurückführbar, ohne ihn irgendwo zu notieren. Verschiebt das Problem in eine zweite Quelle |

**Empfehlung: A.** Begründung: es macht aus einer Heuristik eine Invariante.
Der Preis sind Build-Minuten für Commits, die nichts bauen müssten — gemessen
rund 2–3 min, auf einem Repo mit wenigen Merges am Tag. Weg B spart diese
Minuten und kauft dafür genau den Fehler zurück, den §5.4 beschreibt.

**Nebeneffekt, der gegen A spricht und benannt werden muss:** ein Doku-Commit
erzeugt dann ein neues Image mit neuem Digest (gleicher Inhalt, andere
Layer-Metadaten). `docker compose up -d` rekreiert die Container daraufhin —
also ein Neustart der Steuerung für eine Änderung an `STATUS.md`. Das ist der
eigentliche Preis von A, nicht die Build-Minuten.

Dagegen hilft T3 unten (nur ziehen, wenn der Digest sich wirklich
unterscheidet) — aber bei A unterscheidet er sich ja. Also entweder den
Neustart in Kauf nehmen (er ist kurz und der Timer läuft nachts auch) oder
Weg B mit der Registry-Abfrage. **Diese Abwägung gehört ins Gate; ich
empfehle A mit dem Neustart, weil ein berechenbarer Neustart besser ist als
eine Auflösungslogik, die man nur im Fehlerfall versteht.**

---

## 3. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T1** | `build-images.yml`: `paths`-Filter entfernen (Weg A). Dazu ein Kommentar, der sagt **warum** — sonst setzt ihn der nächste Hygiene-Sprint wieder ein, so wie §5.55 es für die CI-Workflows beschreibt | 0,5 h |
| **T2** | `deploy-pull.sh` Phase 2: `IMAGE_TAG` aus `NEW_SHA` bilden (`${TARGET_BRANCH}-${NEW_SHA:0:7}`) und an `docker compose` übergeben, **nicht** in die `.env` schreiben. Begründung in T5 | 1 h |
| **T3** | Vorhandenheit prüfen, bevor gezogen wird: `docker manifest inspect` auf beide Images. Fehlt eines, **Abbruch mit Grund und ohne Container-Änderung** — nicht stillschweigend auf `develop` zurückfallen. Ein Rückfall auf den gleitenden Tag wäre genau der Zustand, den H-6 beseitigen soll, nur unsichtbar | 1 h |
| **T4** | Rückfallpunkt: `PIN_SHA` in der `.env`. Ist er gesetzt, **gewinnt er** — das Skript checkt diesen Commit aus (statt `reset --hard origin/<branch>`), zieht `<branch>-<pin>` und lässt die Automatik aus. Damit überlebt ein Rückfall den Timer | 1,5 h |
| **T5** | `.env` wird vom Skript **nicht** geschrieben. Der Tag wird je Lauf berechnet und per `IMAGE_TAG=… docker compose …` übergeben. Grund: eine Datei, die der Timer alle fünf Minuten überschreibt, ist kein Ort für eine Entscheidung des Menschen — ein Rückfall per `.env`-Eintrag wäre nach fünf Minuten weg | (in T2/T4) |
| **T6** | Log-Zeile, die den Zusammenhang nennt: `HEAD=<sha> IMAGE_TAG=<tag> api=<digest-kurz> web=<digest-kurz>`. Das ist die Zeile, die bei „seit wann läuft was" gelesen wird | 0,5 h |
| **T7** | Tests: `tests/test_deploy_pull_pinning.py` am **echten** Skript, wie `test_deploy_pull_lock.py` (§5.82-Muster: ein nachgebautes Skript prüft nur sich selbst). Fälle: Tag wird aus HEAD gebildet; fehlendes Image bricht ab **ohne** `up -d`; `PIN_SHA` gewinnt gegen den Branch-Kopf; `PIN_SHA` überlebt einen zweiten Lauf | 2 h |
| **T8** | RUNBOOK §10u: „Stand zurückdrehen" — mit dem Migrations-Vorbehalt aus §1.5 und dem Hinweis, dass der Working-Tree mitgeht | 1 h |
| **T9** | AE-77, STATUS, CLAUDE.md §5.4 **korrigieren**: die Lesson beschreibt heute eine Notwendigkeit, wo es eine Implementierungsentscheidung war. Nach §5.77 ist das genau die Sorte Vermerk, die wie ein Befund gelesen wird und einen späteren Sprint fehlleitet | 1 h |
| **Summe** | | **8,5 h** |

---

## 4. Akzeptanzkriterien

1. Ein Merge nach develop führt dazu, dass der Server auf **demselben**
   Commit läuft, dessen Image er zieht — nachweisbar über eine Log-Zeile, die
   beide nennt.
2. Fehlt das Image zum aktuellen Commit, **bricht der Lauf ab** und ändert
   keinen Container. Der Deploy-Monitor bekommt einen Ping mit Grund (wie bei
   der Eingangstest-Sperre, damit kein Falsch-Alarm entsteht, §5.79).
3. `PIN_SHA=<alter-sha>` in der `.env` plus ein Timer-Lauf fährt den Stand
   zurück — Code **und** Working-Tree — und **bleibt** dort über mindestens
   zwei weitere Timer-Läufe.
4. `PIN_SHA` leeren und ein Timer-Lauf holt den Branch-Kopf zurück.
5. Die bestehenden Tests zu `deploy-pull.sh` bleiben **ohne Anpassung** grün
   (§5.47).
6. Live auf heizung-test verifiziert, mit einem echten Rückfall auf den
   vorherigen Stand und zurück.

---

## 5. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| **Pinning macht den Deploy strenger — ein fehlendes Image stoppt ihn.** Das ist gewollt, aber es ist eine neue Art, wie der Deploy stehen bleiben kann | T3 bricht mit Grund ab und pingt; der Monitor sieht es. Vorher ist der gleitende Tag aktiv, dieser Fall gibt es also heute nicht |
| **`PIN_SHA` wird gesetzt und vergessen.** Der Server bleibt auf einem alten Stand, und weitere Merges wirken nicht | T6-Log nennt den Pin in jedem Lauf. Zusätzlich: der Deploy-Ping bekommt den Pin als Body mit, damit er im Monitor steht und nicht nur im Server-Log. **Offene Frage fürs Gate:** soll ein gesetzter Pin nach n Tagen eine Mail auslösen? |
| **Rückfall über eine Migration hinweg** | §1.5 und T8: das ist ein Handgriff mit `alembic downgrade`, kein Tag-Wechsel. Die Migrationen 0023–0027 sind alle nullable-Spalten ohne Backfill, also unkritisch — als Regel gilt das nicht |
| **Weg A rekreiert Container bei Doku-Commits** | §2, bewusst in Kauf genommen. Der Neustart ist kurz; falls er störend wird, ist Weg B der Ausweg und braucht dann einen eigenen Schnitt |
| **Zwei Server, ein Skript** | heizung-test und heizung-main unterscheiden sich nur über `STAGE`. T2 bildet den Tag aus `TARGET_BRANCH`, also `develop-…` bzw. `main-…`. Ein Test deckt beide Zweige ab |

---

## 6. Was NICHT in H-6 gehört

- **Digest-Pinning** (Weg C). Exakter, aber nicht lesbar; wenn Tags nicht
  reichen, ist das der nächste Zug und nicht dieser.
- **Automatischer Rückfall bei Fehlern.** Ein Deploy, der selbst entscheidet
  zurückzugehen, braucht ein Urteil darüber, was „kaputt" heißt — und ein
  falsches Urteil würde die Steuerung im Kreis fahren. Der Rückfall bleibt
  ein Handgriff mit einer Zeile in der `.env`.
- **`latest`-Tag auf develop.** Gibt es heute nur auf main
  ([build-images.yml](.github/workflows/build-images.yml), `type=raw`), und
  dabei bleibt es.
- **Retention im GHCR.** Mit Weg A wachsen die Tags schneller. Aufräumen ist
  eine eigene Aufgabe (eigener Backlog-Eintrag), und sie muss wissen, wie weit
  zurück ein Rückfallpunkt reichen soll — das ist eine Betriebs- und keine
  Technikfrage.

---

## 7. Querverweise

- **§5.4** — die Lesson, die diesen Sprint ausgelöst hat und in T9 korrigiert
  wird.
- **§5.10 / §5.11** — `build-images.yml` triggert nicht immer zuverlässig,
  und `docker compose pull` ist kein Beweis. Mit einem gepinnten Tag wird
  beides prüfbar: entweder das Image zum Commit ist da oder nicht.
- **§5.55 Nachtrag** — Präzedenzfall für Weg A: `paths`-Filter aus den
  CI-Workflows entfernt, weil zwei synchron zu haltende Listen eine
  unsichtbare Lücke erzeugen. `build-images.yml` war dort ausdrücklich die
  Ausnahme; dieser Sprint hebt sie auf.
- **§5.68** — „der Server läuft auf develop" ist eine Behauptung, solange
  niemand den Commit nennen kann.
- **§5.76** — Wirkung statt Mechanik: T6 und der Ping machen den
  Zusammenhang Commit↔Image sichtbar, statt zu prüfen, ob der Timer läuft.
- **§5.78** — `docker compose` ohne `-f` auf dem Server. Jeder Befehl im
  Runbook-Teil trägt es.
- **§5.82** — Tests am echten Skript, nicht an einem Nachbau.
- **§0.3** — ein Merge nach develop ist ein Deploy. Die Deploy-Sperre
  (Phase 0) bleibt unberührt und läuft **vor** allem Neuen.
