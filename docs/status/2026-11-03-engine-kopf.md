## Der Engine-Kopf nennt die wirksame Schicht (2026-11-03)

**Keine Migration.** Zwei Helfer und ein geänderter Aufruf in
`engine-decision-panel.tsx`, vier Playwright-Tests.

### Der Befund, aus der Boost-Abnahme

Bei laufendem Boost stand im Kopf der Engine-Seite:

> **23°C** · aktueller Sollwert
> Grund: **Frei-Sollwert** · Sollwert aus: hausweit

**Beide Hälften waren für sich richtig und zusammen falsch.** Die
**Zahl** kam aus `hard_clamp`, also vom Ende der Schichtkette; der
**Grund** aus `base_target`, also vom Anfang. Zwei Zeilen derselben
Tabelle, als ein Satz gelesen — und darunter stand im Trace korrekt
„Boost (Mitarbeiter) bis 20:00".

**Der Fehler war nicht boost-eigen.** Jede Übersteuerung erzeugte ihn,
eine gewöhnliche Wunschtemperatur ebenso, und er wuchs mit dem Abstand
der beiden Schichten. Aufgefallen ist er am Boost, weil dort zum ersten
Mal jemand den Kopf gegen den Trace darunter gehalten hat — kein
Zufallsfund, sondern das, wofür eine Abnahme da ist.

**Die zweite Hälfte war die unangenehmere.** „Sollwert aus: hausweit"
behauptete eine **Herkunft** für einen Wert, der nicht von dort kam. Das
ist nicht nur ungenau: wer der Zeile glaubt, sucht die 23 in den
hausweiten Temperaturen und findet dort 15.

### Was jetzt gilt

| | |
|---|---|
| **Grund** | aus der Schicht, die den Wert **verändert** hat — rückwärts durch die Pipeline, die späteste Änderung gewinnt |
| **Übersteuerung** | ihr Etikett statt „Manuell": „Boost (Mitarbeiter) bis 20:00", dasselbe `SOURCE_LABEL` wie im Trace darunter |
| **Endzeit** | in Hotel-Zeit (`formatTime`), wie am Knopf in der Zimmerübersicht. Fehlt sie, steht das Etikett allein |
| **„Sollwert aus"** | verschwindet von selbst — die Details einer Übersteuerung tragen kein `sollwert_quelle` |
| **ohne Übersteuerung** | unverändert: Basis-Schicht, mit Herkunft |

### Warum die Veränderung und nicht die letzte Schicht

`hard_clamp` steht immer am Ende und trägt laut §5.23 den
**durchgereichten** Grund. Darauf allein zu bauen hätte weniger Code
gekostet, und es wäre die schlechtere Lösung:

1. Es verlässt sich auf das Durchreichen in **jeder** Schicht — eine
   Zusicherung aus einer Lesson, nicht eine Beobachtung an den Daten.
2. Es verschweigt, **welche** Schicht entschieden hat. Genau das ist die
   Frage, die der Kopf beantworten soll.

`setpoint_in != setpoint_out` ist dagegen am Datensatz ablesbar. Die
Mutationsprobe „letzte Schicht statt letzter Änderung" bringt drei der
vier Tests zu Fall — der Unterschied ist also keiner auf dem Papier.

**Was der Weg nicht findet:** eine Schicht, die den Wert belässt und
trotzdem der Grund ist — eine Absenkung etwa, die zufällig denselben Wert
ergibt. Dann nennt der Kopf die Schicht davor. Ein stiller Irrtum, aber
ein kleinerer als der bisherige: er verwechselt zwei Schichten mit
**demselben** Wert, nicht zwei mit verschiedenen. Das steht als Absatz im
Code, damit es niemand für einen Zufall hält.

`manual_override_blocked` ist ausgenommen: off-pipeline, synthetische
`evaluation_id`, keine Geschwister (§5.52).

### Tests

| Test | prüft |
|---|---|
| laufender Boost | Etikett **und** Endzeit in Ortszeit, **und** dass „Sollwert aus" fehlt |
| Wunschtemperatur (`frontend_24h`) | derselbe Weg — der Fehler war nicht boost-eigen |
| Fenster offen **nach** dem Boost | der Kopf gehört der **späteren** Schicht, nicht der Übersteuerung |
| ohne Übersteuerung | Basis-Schicht und Herkunft bleiben, wie sie waren |

**Der dritte ist der, der eine naheliegende Fehllösung ausschließt**
(„irgendeine Übersteuerung gewinnt"). Der vierte ist der, ohne den ein
Fix den Normalfall mitnehmen könnte.

**Die Endzeit prüft zugleich die Zeitzone.** Die Antwort trägt
`19:00:00Z`, die Anzeige muss `20:00` zeigen — im November ist Wien
UTC+1. Genau hier verrutscht eine Endzeit sonst um eine Stunde (§5.65).

Dazu eine neue Marke `trace-sollwert` am Wert im Kopf: derselbe Wert
steht auch im Trace darunter, und ein Test muss die Zahl **dieses**
Kopfes greifen können — die Verwechslung von Zeilen war ja der Fehler.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| zurück auf `base_target` (der Fehler selbst) | **drei von vier** |
| letzte Schicht statt letzter Änderung | **drei von vier** |
| Endzeit aus dem Etikett entfernt | die zwei Übersteuerungs-Tests |
| vorwärts statt rückwärts durch die Pipeline | der Fenster-Test |

Die letzte ist die feinste: nur **ein** Test unterscheidet die beiden
Richtungen, und es ist der, der dafür geschrieben wurde.

### Nebenbei: zwei Uhrzeiten in Kommentaren

`uebersteuern-dialog.tsx` und `types.ts` behaupteten im Kommentar „Boost
bis 22:00". Nachgezogen auf 20:00, mit dem Zusatz, dass die Uhrzeit der
Nachtbeginn des Hauses ist und mit ihm wandert — dieselbe Drift wie in
`docs/status/2026-11-03-boost-abnahme.md`, hier in Kommentaren derselben
Dateifamilie.

**Nicht angefasst** sind zwei weitere 22:00 in `room-history-chart.tsx`
und `types.ts`: die illustrieren ein **Datenformat** („Absenkung
22:00–06:00 MESZ" als Beispiel einer Zeichenkette, deren Werte vom Server
kommen) und behaupten nichts über dieses Haus. Die Grenze ist Absicht —
korrigiert ist, was eine Aussage über den Stand des Hauses macht.

### Lokal

365 e2e passed (frischer Port 3177, §5.55), `tsc --noEmit`, `next lint`
ohne Befund. Backend nicht berührt.

**Querverweise:** RUNBOOK §10ax (die Abnahme, die den Befund gebracht
hat), `docs/status/2026-11-03-boost-abnahme.md`, §5.23
(Trace-Konsistenz — die Zusicherung, auf die ich bewusst nicht gebaut
habe), §5.52 (off-pipeline-Zeilen), §5.65 (Ortszeit gegen UTC), §5.57
(die Information ist da, nur nicht dort, wo der Leser sie sucht).
