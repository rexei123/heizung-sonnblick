---
datum: 2026-11-17
thema: Die Wächter-Strategie umschalten, ohne Kommandozeile
pr: offen
---

# Wächter-Knopf

**Keine Migration, kein neuer Endpunkt, keine Server-Änderung.** Die
Oberfläche bedient den Endpunkt aus #416, den es seit dem 15.11. gibt.

## Der Anlass

Bis heute ging das Umschalten nur per `curl` oder `Invoke-RestMethod`
mit Sitzungs-Cookie. Der **Wert** stand auf der Relais-Karte, der Weg
dorthin nicht — ein Zustand, den man sieht und nicht ändern kann,
schickt jeden zur Kommandozeile. Heute früh war das ein Einzeiler, den
ich dem Betreiber zuschicken musste; der Knopf macht ihn überflüssig.

## Was geändert ist

| Stelle | Änderung |
|---|---|
| `lib/api/relays.ts` | `setzeWaechterStrategie(deviceId, strategie)` → PATCH, zod-geprüfte Antwort |
| `relay-card.tsx` | Knopf im Handgriff-Block, nur für Admin und nur bei einem Relais **in Betrieb** |
| `relay-card.tsx` | die Zeile „Wächter" zeigt einen Satz statt des Datenbankwerts |
| `content/handbuch/seite-thermostate.md` | neuer Abschnitt „Der Wächter: zwei Verfahren, ein Knopf", `stand` nachgezogen |

### Die Zeile sagt den Zustand, der Knopf die Handlung

Hier stand `expire_and_resend` — ein Datenbankwert, kein Satz. Jetzt:

| Zeile „Wächter" | Was es heißt |
|---|---|
| **Timer läuft ab, dann neu** | Das Panel geht aus, wenn die Zeit um ist; die Steuerung schaltet im nächsten Lauf wieder ein. Dazwischen ist es kalt. |
| **Timer wird nachgesetzt** | Die Steuerung verlängert, solange geheizt werden soll. Das Panel bleibt an. |

Der Knopf darunter heißt nach dem, was er **tut**: „Timer nachsetzen
lassen" bzw. „Timer ablaufen lassen" (§5.85 — die Probe ist, die
Beschriftung laut zu lesen; kommt eine Aufforderung heraus, stimmt es).

### Drei Dinge, die der Knopf bewusst nicht tut

**Er sendet keinen Funkbefehl.** Der Endpunkt schreibt Audit und setzt
`relais_ein_gesendet_at` zurück; gesendet wird beim nächsten regulären
Lauf des Orchestrators. Die Karte meldet deshalb keinen Funkverkehr —
sie hat keinen ausgelöst.

**Er nennt keine Zahlen.** Timer und Abstand stehen in den Settings und
sind pro Haus verstellbar. Die Meldung nach dem Umschalten kommt aus
dem Backend (`hinweis`) und nennt sie von dort; sie im Frontend zu
wiederholen wäre eine zweite Wahrheit (§5.73).

**Er erscheint nicht vor der Inbetriebnahme.** Vorher hat der Wächter
nichts zu tun — ein Knopf, der eine Strategie für einen Wächter
umstellt, der nicht läuft, verspricht eine Wirkung, die es nicht gibt.

## Das Handbuch, und eine überholte Stelle darin

Goldene Regel 13 verlangt den Artikel im selben PR. Dabei ist
aufgefallen, dass der Relais-Abschnitt noch sagte, es sei „ein Panel
noch nicht angeschlossen, und geschaltet wird noch nichts". Das galt bis
Anfang November; **zwei Relais schalten echte Panels.** Korrigiert, mit
dem Vermerk, bis wann die alte Aussage stimmte (§5.77).

## Prüfungen

Sechs neue e2e-Fälle: die Zeile nennt das Verfahren statt des Rohwerts,
der Knopf nennt die Handlung, von `refresh` aus bietet er den Rückweg,
der Klick schickt PATCH mit dem jeweils **anderen** Verfahren (zweimal,
aus beiden Richtungen), und ohne Inbetriebnahme gibt es ihn nicht. Der
Mitarbeiter-Test prüft ihn mit.

**Sechs Mutationsproben, alle rot.** Eine blieb im ersten Durchgang
grün: ein fest verdrahtetes `mutate("refresh")` kam durch, weil der
PATCH-Test nur vom Zustand `expire_and_resend` aus klickte — dort ist
„das andere Verfahren" zufällig dasselbe wie „immer refresh". Die
Gegenprobe aus der anderen Richtung fehlte und ist nachgezogen.

Lokal: `type-check`, `lint`, **415 e2e-Tests**. Der eine Fehlschlag
(`zimmerliste-knopffarbe`, Hover-Farbe) besteht allein und ist unter
Parallellast flatterig — nicht von dieser Änderung.

**Querverweise:** RUNBOOK §10bc (der Handgriff, den der Knopf ersetzt),
§5.85 (Knopf nennt die Handlung), §5.73 (Schwellen und Zeiten im
Backend), §5.77 (die überholte Stelle im Handbuch), #416 (der
Endpunkt).
