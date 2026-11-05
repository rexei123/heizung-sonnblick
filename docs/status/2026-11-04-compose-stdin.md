# `docker compose` hat die eingefügten Folgezeilen verschluckt

**Stand:** 04.11.2026

Befund 3 aus der Rotation vom 04.11. (`2026-11-04-rotation-teil2.md`).
Mehrere Zeilen in einem Rutsch in das Terminal eingefügt: der
`docker compose`-Aufruf lief, und was dahinter stand, war weg. Nicht
ausgeführt, nicht sichtbar liegengeblieben — weg.

## Warum das die schlechteste Sorte Fehler ist

Eine Fehlermeldung sieht man. Hier läuft der erste Befehl, die Shell kommt
zurück, und der Rest existiert nicht mehr. **Es sieht aus wie Erfolg.** In
einer Laufliste, die Blöcke zum Kopieren anbietet, ist das die
gefährlichste Eigenschaft, die ein Handgriff haben kann — und es ist
derselbe Fehlertyp wie bei Befund 1, wo eine Prüfung bestand, während die
Sache kaputt war.

## Was feststeht und was nicht

**Feststehend:** `docker compose exec` und `docker compose run` laufen
**ohne `-T`** interaktiv und ziehen die Standardeingabe an sich — was
dahinter eingefügt wurde, wird zur Eingabe des **Containers**. Das ist
mehrfach dokumentiert und betrifft im RUNBOOK sechs Aufrufe, die jetzt
alle `-T` tragen.

**Nicht erklärt:** der beobachtete Fall selbst. Dort stand ein
`docker compose restart`, und `restart` liest keine Eingabe. Die
naheliegende Erklärung ist die Fortschrittsanzeige von Compose v2, die das
Terminal für ihre Darstellung beansprucht — **das ist eine Vermutung und
nicht nachgesehen.**

Die Regel gilt unabhängig davon. Sie muss den Fall nicht erklären, um ihn
zu verhindern, und das ist hier der richtige Zuschnitt: eine Regel, die
auf eine ungeprüfte Mechanismus-Vermutung gebaut ist, wäre falsch — eine
Regel, die aus einer Beobachtung folgt, nicht.

## Zwei Stellen, an denen das Anhängen Absicht ist

Die Init-Sidecars werden mit `up --force-recreate --no-deps` **ohne `-d`**
gestartet, damit ihr Exit-Code sichtbar wird (vier Aufrufe). Die hängen
sich also absichtlich an das Terminal. Daran wird nichts geändert — sie
gehören nur erst recht allein eingefügt, und das steht jetzt dabei.

## Zahlen zur Lage

**30 Blöcke** im RUNBOOK enthalten einen `compose`-Aufruf, auf den noch
eine Zeile folgt. Die Regel betrifft also nicht eine Ausnahme, sondern
ein Drittel der Betriebsblöcke.

Ob jeder dieser 30 Blöcke tatsächlich etwas verschluckt, ist **nicht**
geprüft — die sechs ohne `-T` taten es nachweislich, bei den übrigen hängt
es an der ungeprüften Vermutung oben. Deshalb lautet die Regel „einzeln
einfügen" und nicht „diese 30 Blöcke sind kaputt".
