# H-6 — Image-Pinning und ein Rückfallpunkt, der den Timer überlebt

**Datum:** 2026-10-07
**Typ:** Infrastruktur (CI-Workflow + Deploy-Skript + Compose-Umgebung)
**Autonomie-Stufe:** 1 (volle Stop-Points) — der Deploy-Pfad ist die Stelle,
an der ein Fehler alle Server gleichzeitig trifft
**Status:** **Fassung 2, zur Freigabe.** Nichts umgesetzt.

**Was sich gegenüber Fassung 1 geändert hat:**

- **Weg C** (Re-Tag statt Build) ist der gewählte Weg, auf Entscheidung des
  Hoteliers vom 08.10. Fassung 1 hatte ihn nicht in Betracht gezogen; sie
  stellte Weg A (immer bauen) gegen Weg B (Tag auflösen) und empfahl A mit
  dem Nachteil, dass ein Doku-Commit die Container rekreiert. Weg C hat
  diesen Nachteil nicht. Bewertung in §2a.
- **Eine falsche Angabe in §1.3 ist korrigiert.** Siehe §1.3a — das dort
  genannte Beispiel war nicht geprüft und stimmte nicht. Der Befund selbst
  stimmt, nur mit einem anderen Commit.
- `PIN_SHA`-Erinnerung nach sieben Tagen, danach wöchentlich (§4b).
- Regel „Rückfall nur über additive Migrationen", mit Markierungspflicht im
  PR (§1.5a).

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

### 1.3a Korrektur zu Fassung 1

**Fassung 1 nannte an dieser Stelle PR #269 als Beispiel und behauptete, zu
`0b5d9de` gebe es keinen Tag. Das war falsch, und ich hatte es nicht
geprüft.**

Nachgemessen am 08.10.:

```
d7e54fd  (#261, nur STATUS.md)                       -> kein Tag
0b5d9de  (#269, STATUS.md + docs/ + backend/tests/)   -> develop-0b5d9de
```

`#269` hat eine Testdatei unter `backend/` angefasst, der `paths`-Filter traf
also zu und das Image wurde gebaut. Ich hatte vom Zweck des PRs („Doku") auf
die berührten Pfade geschlossen, statt in den Diff zu sehen — §5.68 in eigener
Sache, und in einem Brief, auf dem eine Entscheidung aufsetzt.

**Der Befund selbst bleibt und ist belegt:** `d7e54fd` (PR #261, der
Backlog-Eintrag B-21-1) berührte ausschließlich `STATUS.md` und hat **keinen**
Tag. Mit Pinning in der heutigen Form wäre der Deploy an diesem Merge
hängengeblieben.

Die Lücke ist damit enger als Fassung 1 behauptet — sie trifft nur Merges, die
**ausschließlich** außerhalb von `backend/` und `frontend/` liegen. Das sind
die reinen Doku- und Backlog-PRs, und von denen gab es in diesem Sprint
mehrere.

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

### 1.5a Regel: Rückfall nur über additive Migrationen

**Entscheidung des Hoteliers (08.10.), und sie gehört in die
Projektregeln, nicht nur in diesen Brief.**

> Ein Rückfall ist nur über **additive** Migrationen zulässig. Jede
> nicht-additive Migration — `DROP COLUMN`, `RENAME`, nachträgliches
> `NOT NULL`, Enum-Wert entfernen, Typ verengen — wird **im PR als „bricht
> Rückfall" markiert**.

Additiv heißt: eine nullable Spalte oder Tabelle hinzufügen, ohne Backfill
und ohne Beschränkung, die ältere Zeilen betrifft. Älterer Code liest sie
nicht und stört sich nicht an ihnen; ein Image von vor der Migration läuft
gegen das neuere Schema unverändert.

**Die Migrationen dieses Herbstes sind alle additiv:**

| Migration | Inhalt | additiv |
|---|---|---|
| 0023 | `sensor_reading.broken_sensor` nullable | ✅ |
| 0024 | `sensor_reading.battery_voltage` nullable | ✅ |
| 0025 | `sensor_reading.calibration_failed` nullable | ✅ |
| 0026 | `ck_manual_override_source` **erweitert** um `device_manual` | ✅ (lockert, verengt nicht) |
| 0027 | `device.mounted_confirmed_at` nullable | ✅ |

0026 ist der interessante Fall und der Grund, die Regel genau zu
formulieren: eine `CHECK`-Beschränkung zu **erweitern** ist additiv, sie zu
**verengen** nicht. Ein Rückfall auf ein Image vor 0026 läuft gegen das
erweiterte `CHECK` ohne Problem — er schreibt nur nie `device_manual`. Die
Gegenrichtung (Beschränkung verengt, Bestandszeilen verletzen sie) wäre ein
Rückfall, der die Datenbank nicht mehr annimmt.

**Wo die Markierung hingehört:** in den PR-Text, und zusätzlich als Zeile im
Docstring der Migration. Der PR-Text ist, was beim Suchen nach „seit wann"
gelesen wird; der Docstring ist, was beim Lesen der Migration gelesen wird.
Eine Markierung nur im PR-Text wäre in einem Jahr nicht mehr zu finden.

**Keine CI-Prüfung dafür**, und das ist eine Abwägung: ein Linter könnte
`op.drop_column`, `op.alter_column(nullable=False)` und
`op.execute("ALTER TABLE … DROP CONSTRAINT")` erkennen und eine Markierung
im Docstring verlangen. Das wäre machbar und würde die Regel durchsetzen,
statt sie zu dokumentieren. Es ist aber ein eigener Mechanismus mit eigenen
Falsch-Positiven (eine `drop_column` im `downgrade` ist normal und richtig),
und die Regel betrifft wenige Migrationen im Jahr. **Offene Frage fürs
Gate:** jetzt mitbauen oder als Backlog?

---

## 2. Wege A und B — Fassung 1, durch §2a überholt

> **Dieser Abschnitt bleibt als Begründung stehen, ist aber nicht mehr die
> Empfehlung.** Der Hotelier hat am 08.10. Weg C gewählt (§2a), und Weg C
> hat den Nachteil nicht, der hier gegen A sprach. Wer wissen will, warum
> A und B verworfen sind, liest weiter; wer wissen will, was gebaut wird,
> springt zu §2a.

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

## 2a. Weg C: Re-Tag statt Build — Bewertung

**Der Vorschlag (Hotelier, 08.10.):** Bei einem Merge, der das jeweilige
Image nicht betrifft, wird nicht gebaut, sondern das **bestehende Image auf
den neuen Tag umgehängt** — `docker buildx imagetools create` oder
`crane tag`. Jeder Commit hat dann einen Tag, der Digest bleibt identisch,
`docker compose up -d` rekreiert nichts, und für einen Doku-Commit startet
die Steuerung nicht neu.

**Das ist besser als beide Wege aus Fassung 1**, und zwar nicht nur
geringfügig. Es löst den Nachteil von A (Neustart für Doku) und braucht nicht
die Heuristik von B (Registry-Abfrage oder `git log`-Pfadsuche im
Deploy-Skript). Empfehlung: **C**.

### 2a.1 Wo die Entscheidung fällt — und wo nicht

**Nicht über zwei Workflows mit `paths` und `paths-ignore`.** Diese Form
wäre naheliegend (ein Build-Workflow, ein Re-Tag-Workflow) und ist im Repo
ausdrücklich verboten: §5.55 Nachtrag beschreibt, warum das Spiegel-Paar
abgeschafft wurde. Zwei von Hand synchron gehaltene Pfadlisten erzeugen
genau die Lücke, die der Mechanismus schließen soll, und zwar unsichtbar.

**Sondern in einem Workflow ohne `paths`-Filter, mit einer
Laufzeit-Entscheidung je Image.** Der `paths`-Filter verschwindet wie bei
Weg A — aber was danach passiert, hängt davon ab, was der Push berührt hat.

### 2a.2 Die Entscheidung fällt je Image, nicht je Commit

Das ist ein Detail mit Folgen. Heute steht der Filter auf
**Workflow**-Ebene: berührt ein Commit `backend/**`, laufen **beide** Jobs —
auch `build-web`, obwohl sich am Frontend nichts geändert hat. Jeder
Backend-Merge baut also das Web-Image mit.

Mit Weg C je Image gibt es vier Fälle:

| Push berührt | api | web |
|---|---|---|
| `backend/` und `frontend/` | bauen | bauen |
| nur `backend/` | bauen | **re-taggen** |
| nur `frontend/` | **re-taggen** | bauen |
| keines von beiden | **re-taggen** | **re-taggen** |

**Weg C baut damit weniger als der heutige Zustand**, nicht mehr. Das war in
Fassung 1 nicht zu sehen, weil dort der Vergleich gegen Weg A lief.

### 2a.3 „Welches Image ist das letzte" — die Frage aus dem Auftrag

Die naheliegende Antwort „das, worauf der gleitende Tag `develop` zeigt" ist
**falsch**, oder genauer: sie ist richtig und nicht beweisbar. `develop`
bewegt sich mit jedem Build; bei zwei knapp aufeinanderfolgenden Pushes oder
nach einem abgebrochenen Lauf (`cancel-in-progress: true` steht im Workflow)
zeigt er womöglich nicht dorthin, wo man ihn vermutet. Ein Mechanismus, der
auf einen beweglichen Zeiger baut, ist kein Pinning.

Die zweite naheliegende Antwort — `git log -1 -- backend/` — ist **genau die
Heuristik, die 2026-04-30 gescheitert ist** (§5.4, §1.2). Sie taucht hier in
anderem Gewand wieder auf, und sie bleibt falsch.

**Die belastbare Antwort ist der erste Parent des Push-Commits:**

```
develop-<sha von HEAD^1>   ->   develop-<sha von HEAD>
```

Begründung: Weg C stellt die Invariante her, dass **jeder** Commit auf
`develop` einen Tag hat. Damit hat der Vorgänger per Konstruktion einen —
unabhängig davon, was er berührt hat. Keine Pfadsuche, keine
Registry-Schleife, keine Annahme über Zeitpunkte.

`HEAD^1` ist bei einem Squash-Merge (`gh pr merge --squash`, der Weg in
diesem Repo) der vorherige `develop`-Kopf, und bei einem echten
Merge-Commit ebenfalls der erste Parent, also auch der vorherige Kopf. Beide
Fälle sind damit abgedeckt. Der Workflow braucht dafür `fetch-depth: 2` im
`actions/checkout` — der Standard ist 1 und hätte keinen Parent.

### 2a.4 Fallstricke

| # | Fallstrick | Antwort |
|---|---|---|
| **F1** | **Bootstrap.** Die Invariante gilt erst ab Einführung. Heute haben `d7e54fd` und weitere Commits keinen Tag; der erste Re-Tag-Lauf fände seine Quelle nicht | Beim ersten Lauf nach dem Merge ist `HEAD^1` der Merge-Commit dieses Sprints selbst — und der berührt `.github/` **und** `infra/`, baut also sowieso. Die Invariante greift ab dem Commit **danach**. Trotzdem: F2 muss den Fall sauber behandeln, statt sich darauf zu verlassen |
| **F2** | **Quelle fehlt** (Bootstrap, abgebrochener Build, gelöschtes Tag) | **Dann bauen statt raten.** Der Re-Tag-Schritt prüft die Quelle (`imagetools inspect`); fehlt sie, fällt er auf einen regulären Build zurück und sagt das im Log. Ein Abbruch wäre hier falsch: ein fehlendes Vorgänger-Tag ist kein Grund, einen Commit ohne Image zu lassen — das wäre der Zustand, den H-6 beseitigt |
| **F3** | **Abgebrochene Läufe.** `concurrency.cancel-in-progress: true` kann einen Build mitten im Push-Lauf beenden; dann entsteht kein Tag für diesen Commit, und der nächste Re-Tag sucht ihn | Deckt F2 ab (Rückfall auf Build). Zusätzlich zu prüfen, ob `cancel-in-progress` für diesen Workflow überhaupt noch richtig ist: er pusht Images, und ein abgebrochener Push lässt eine Lücke. **Offene Frage fürs Gate:** `cancel-in-progress: false` für `build-images.yml`? |
| **F4** | **Manifest-Listen.** `docker tag` + `push` würde eine Multi-Arch-Liste plattdrücken. `imagetools create` kopiert den Index korrekt | Die Builds sind heute single-arch (kein `platforms:` im Workflow), der Fall tritt nicht ein. `imagetools create` ist trotzdem das richtige Werkzeug, weil es auch nach einem späteren Multi-Arch-Wechsel stimmt |
| **F5** | **Der gleitende `develop`-Tag.** `type=ref,event=branch` setzt ihn bei jedem Build | Beim Re-Tag ist der Digest identisch, `develop` zeigt also schon auf dasselbe Image — nichts zu tun. Der Re-Tag-Schritt setzt **nur** `develop-<sha>` |
| **F6** | **Rechte.** Der Re-Tag liest ein bestehendes Tag und schreibt ein neues | `packages: write` steht im Workflow, der GHCR-Login ebenfalls. Nichts Neues nötig |
| **F7** | **Erkennen, was berührt wurde.** `github.event.before` ist bei einem ersten Push oder nach einem Force-Push unbrauchbar (Null-SHA bzw. verschwundener Commit) | `git diff --name-only HEAD^1 HEAD` mit `fetch-depth: 2`. Arbeitet auf dem Checkout statt auf Event-Metadaten und stimmt für Squash- und Merge-Commits gleichermaßen |
| **F8** | **Unverifiziert:** dass GHCR `imagetools create` für dieses Paket annimmt | **T1a ist eine Probe**, einmalig und von Hand, bevor der Workflow umgebaut wird. Ich schreibe das nicht als Tatsache in diesen Brief — ich habe es nicht ausgeführt |

### 2a.5 Aufwand

| | |
|---|---|
| Workflow-Umbau (Entscheidung je Image, Re-Tag-Schritt, Rückfall auf Build) | 2,5 h |
| Probe gegen GHCR (T1a) | 0,5 h |
| **Mehraufwand gegenüber Weg A** | **+2 h** |

Dafür entfällt der Neustand-Neustart bei Doku-Commits, und das Repo baut in
Summe weniger als heute.

---

## 3. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T1a** | **Probe zuerst:** von Hand `docker buildx imagetools create --tag …:develop-probe …:develop` gegen GHCR laufen lassen und prüfen, dass der Digest identisch bleibt. Erst danach den Workflow umbauen. Probe-Tag hinterher löschen | 0,5 h |
| **T1** | `build-images.yml`: `paths`-Filter entfernen, `fetch-depth: 2`, Entscheidung **je Image** aus `git diff --name-only HEAD^1 HEAD`, Re-Tag-Schritt mit Rückfall auf Build, wenn die Quelle fehlt (F2). Kommentar, der sagt **warum** der Filter weg ist — sonst setzt ihn der nächste Hygiene-Sprint wieder ein (§5.55) | 2,5 h |
| **T2** | `deploy-pull.sh` Phase 2: `IMAGE_TAG` aus `NEW_SHA` bilden (`${TARGET_BRANCH}-${NEW_SHA:0:7}`) und an `docker compose` übergeben, **nicht** in die `.env` schreiben. Begründung in T5 | 1 h |
| **T3** | Vorhandenheit prüfen, bevor gezogen wird: `docker manifest inspect` auf beide Images. Fehlt eines, **Abbruch mit Grund und ohne Container-Änderung** — nicht stillschweigend auf `develop` zurückfallen. Ein Rückfall auf den gleitenden Tag wäre genau der Zustand, den H-6 beseitigen soll, nur unsichtbar | 1 h |
| **T4** | Rückfallpunkt: `PIN_SHA` in der `.env`. Ist er gesetzt, **gewinnt er** — das Skript checkt diesen Commit aus (statt `reset --hard origin/<branch>`), zieht `<branch>-<pin>` und lässt die Automatik aus. Damit überlebt ein Rückfall den Timer | 1,5 h |
| **T5** | `.env` wird vom Skript **nicht** geschrieben. Der Tag wird je Lauf berechnet und per `IMAGE_TAG=… docker compose …` übergeben. Grund: eine Datei, die der Timer alle fünf Minuten überschreibt, ist kein Ort für eine Entscheidung des Menschen — ein Rückfall per `.env`-Eintrag wäre nach fünf Minuten weg | (in T2/T4) |
| **T6** | Log-Zeile, die den Zusammenhang nennt: `HEAD=<sha> IMAGE_TAG=<tag> api=<digest-kurz> web=<digest-kurz>`. Das ist die Zeile, die bei „seit wann läuft was" gelesen wird | 0,5 h |
| **T7** | Tests: `tests/test_deploy_pull_pinning.py` am **echten** Skript, wie `test_deploy_pull_lock.py` (§5.82-Muster: ein nachgebautes Skript prüft nur sich selbst). Fälle: Tag wird aus HEAD gebildet; fehlendes Image bricht ab **ohne** `up -d`; `PIN_SHA` gewinnt gegen den Branch-Kopf; `PIN_SHA` überlebt einen zweiten Lauf | 2 h |
| **T8** | RUNBOOK §10u: „Stand zurückdrehen" — mit dem Migrations-Vorbehalt aus §1.5 und dem Hinweis, dass der Working-Tree mitgeht | 1 h |
| **T9** | AE-77, STATUS, CLAUDE.md §5.4 **korrigieren**: die Lesson beschreibt heute eine Notwendigkeit, wo es eine Implementierungsentscheidung war. Nach §5.77 ist das genau die Sorte Vermerk, die wie ein Befund gelesen wird und einen späteren Sprint fehlleitet | 1 h |
| **T10** | `PIN_SHA`-Erinnerung (§4b): Beat-Task, Textbaustein, Zustand in `mail_status`, Test mit vorgerückter Uhr | 1,5 h |
| **T11** | Regel aus §1.5a in `CLAUDE.md` (§3-Goldene-Regeln) und in die PR-Vorlage, falls vorhanden | 0,5 h |
| **Summe** | | **12,5 h** |

Gegenüber Fassung 1 (8,5 h): +2 h Weg C statt A, +1,5 h Erinnerung,
+0,5 h Regel. Der Linter aus §1.5a ist **nicht** enthalten.

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
7. **Ein Merge, der nur `docs/` oder `STATUS.md` berührt, erzeugt einen Tag
   mit demselben Digest** wie sein Vorgänger — nachweisbar über
   `imagetools inspect`, und die Container werden dabei **nicht** rekreiert
   (`docker compose ps` zeigt dieselben Container-IDs vor und nach dem
   Timer-Lauf). Das ist die Kernzusicherung von Weg C.
8. Fehlt das Vorgänger-Tag, **baut** der Workflow und bricht nicht ab (F2) —
   geprüft, indem ein Tag von Hand gelöscht und der Workflow erneut
   ausgelöst wird.
9. Ein gesetzter `PIN_SHA` löst nach sieben Tagen eine Mail aus, danach
   wöchentlich; ein geleerter Pin beendet die Erinnerung.

## 4b. Erinnerung an einen gesetzten `PIN_SHA`

**Entscheidung des Hoteliers (08.10.): Mail nach sieben Tagen, danach
wöchentlich, solange gepinnt.**

Umsetzung über den bestehenden Weg, nicht über einen neuen: `services/mailer`
versendet, und der Auslöser gehört in einen Beat-Task, nicht in
`deploy-pull.sh`. Grund: das Skript läuft alle fünf Minuten und wüsste nicht,
ob es heute schon erinnert hat — ein Zustand, den es nirgends ablegen kann,
ohne eine Datei zu schreiben, die beim nächsten `git reset --hard`
verschwindet.

Der Beat-Task liest den Pin dagegen aus derselben Quelle wie das Skript (die
`.env` des Compose-Verzeichnisses), hält den letzten Versandzeitpunkt im
bestehenden `mail_status` und zählt die Tage seit dem Setzen. „Seit wann
gepinnt" steht nicht in der `.env` — deshalb schreibt der erste Lauf, der
einen neuen Pin sieht, den Zeitpunkt in `mail_status` und erinnert ab dann.

**Warum kein Alarm, sondern eine Erinnerung:** ein gesetzter Pin ist kein
Fehler, sondern eine Entscheidung. Der Text sagt entsprechend, was gilt und
was zu tun ist („Seit 7 Tagen auf `<sha>` gepinnt. Automatik aus. Pin leeren
und Timer abwarten, um wieder dem Branch zu folgen."), nicht „Fehler".

Dazu — wie in Fassung 1 vorgesehen — die Log-Zeile in jedem Lauf und der
Pin im Body des Deploy-Pings, damit er im Monitor steht und nicht nur im
Server-Log.

**Aufwand:** +1,5 h (Beat-Task, Textbaustein, Test mit vorgerückter Uhr).

---

---

## 5. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| **Pinning macht den Deploy strenger — ein fehlendes Image stoppt ihn.** Das ist gewollt, aber es ist eine neue Art, wie der Deploy stehen bleiben kann | T3 bricht mit Grund ab und pingt; der Monitor sieht es. Vorher ist der gleitende Tag aktiv, dieser Fall gibt es also heute nicht |
| **`PIN_SHA` wird gesetzt und vergessen.** Der Server bleibt auf einem alten Stand, und weitere Merges wirken nicht | T6-Log nennt den Pin in jedem Lauf. Zusätzlich: der Deploy-Ping bekommt den Pin als Body mit, damit er im Monitor steht und nicht nur im Server-Log. **Offene Frage fürs Gate:** soll ein gesetzter Pin nach n Tagen eine Mail auslösen? |
| **Rückfall über eine Migration hinweg** | §1.5 und T8: das ist ein Handgriff mit `alembic downgrade`, kein Tag-Wechsel. Die Migrationen 0023–0027 sind alle nullable-Spalten ohne Backfill, also unkritisch — als Regel gilt das nicht |
| ~~Weg A rekreiert Container bei Doku-Commits~~ | **Entfällt mit Weg C** (§2a): der Digest bleibt identisch, `up -d` rekreiert nichts. Das war der Grund für den Wechsel |
| **Der Re-Tag zeigt auf das falsche Image** | Quelle ist `HEAD^1`, nicht der gleitende `develop`-Tag und nicht eine Pfadsuche (§2a.3). Fehlt sie, wird gebaut (F2) |
| **Eine nicht-additive Migration macht den Rückfall unmöglich, ohne dass es jemand merkt** | Markierungspflicht im PR **und** im Migrations-Docstring (§1.5a). Ohne CI-Prüfung ist das eine Regel und keine Garantie — die offene Frage dazu steht in §1.5a |
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
