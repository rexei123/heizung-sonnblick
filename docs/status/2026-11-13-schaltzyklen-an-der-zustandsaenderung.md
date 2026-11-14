---
datum: 2026-11-13
thema: Block 2a — der Zykluszähler hängt an der gemeldeten Zustandsänderung
pr: offen
---

# Das Panel hat zweimal eingeschaltet, die Seite zeigte einmal

Vorgabe des Betreibers vom 13.11.2026, Block 2a. **Steuerpfad** — Merge
Montag 16.11. früh.

## Der Befund, in Zeiten

Relais 108 (Rezeption) am 12.11.2026, Ortszeit:

| Zeit | Vorgang |
|---|---|
| 09:38:01 | `0x57` EIN gesendet, Timer 1800 s |
| 09:39:02 | Wiederholung (Bestätigungsfrist 60 s abgelaufen) |
| **09:40:01** | Ist 20,9 > Soll 19,0 → Wunsch kippt auf AUS, offener Stand **verworfen** |
| 09:47:51 | Gerät meldet **EIN**, 1493 W |

Die Zählung stand danach auf **1**, obwohl das Panel an diesem Vormittag
**zweimal** eingeschaltet hat (09:47 und 10:37).

**Das Verwerfen war richtig.** Ein offener Befehl, der dem jetzigen
Wunsch widerspricht, soll nicht wiederholt werden — sonst bremst sein
Backoff ein EIN, das niemand mehr will. Falsch war, den Zähler daran zu
hängen: als die Bestätigung sieben Minuten später kam, gab es keinen
offenen Stand mehr, an dem sie hängen konnte.

**Der Zähler hing an unserer Buchführung statt am Gerät** — und verlor
genau in dem Fall, für den er gebaut ist: beim Takten.

## Was geändert ist

Gezählt wird in `relay_uplink._zaehle_einschaltung`, an der **gemeldeten**
Zustandsänderung, und zwar **vor** dem Einfügen der neuen Zeile.

| Fall | zählt | Grund |
|---|---|---|
| aus → ein | **ja** | der beobachtete Wechsel |
| nie gehört → ein | nein | das Gerät kann seit Tagen laufen; eine Einschaltung, die niemand gesehen hat, wäre eine Behauptung |
| ein → ein | nein | Keepalive, kein Schaltvorgang |
| → aus | nein | keine Einschaltung |
| Zeile ohne `relay_on` | nein | sagt nichts über den Zustand (wie in `relay_state`) |

**Die Reihenfolge ist die Wiederholungsfestigkeit.** MQTT stellt
mindestens einmal zu. Weil vor dem Einfügen gezählt wird, sieht ein
zweiter Durchlauf desselben Frames die Zeile des ersten als Vorzustand
und zählt nicht erneut — ohne eine eigene Prüfung dafür. Die
Mutationsprobe „erst einfügen, dann zählen" macht daraus sechs rote
Tests.

Der Zähler im Wächter ist **entfernt**, nicht ergänzt. Sonst zählte jeder
bestätigte Befehl doppelt.

## Was der Zähler jetzt sagt — und das Etikett dazu

Gezählt wird jede **beobachtete** Einschaltung, auch über den
Handschalter oder nach einer Stromrückkehr. Das ist mehr als „was der
Orchestrator bestätigt bekam", und deshalb ist das Etikett im selben
Schritt nachgezogen:

> „Schaltzyklen der Steuerung" → **„Einschaltungen (gemeldet)"**

Das alte Etikett war am 02.11. aus einem Befund entstanden (der T3.0-Lauf
ging von Hand am Wächter vorbei, die Seite zeigte „0"). Es war richtig
und ist jetzt falsch — ein Etikett, das „der Steuerung" sagt, während
auch der Handschalter mitzählt, ist die nächste §5.77-Stelle. Handbuch
(`seite-thermostate`) und RUNBOOK §10ax-Kriterium sind mitgezogen; im
RUNBOOK steht jetzt ausdrücklich, dass ein Wert über drei erst dann ein
Befund über die Mindestzeiten ist, wenn niemand von Hand geschaltet hat.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| erst einfügen, dann zählen | **6 Tests rot** |
| unbekannter Vorzustand zählt mit | **1 Test rot** |
| Vorzustand gar nicht prüfen | **3 Tests rot** |
| auch AUS zählt | **zuerst grün — Lücke, geschlossen** |
| Wächter zählt wieder mit (Doppelzählung) | **1 Test rot** |

**Die vierte Probe war eine Lücke.** Eine Mutation, die statt „nur EIN
zählt" nur noch „kein NULL" prüfte, blieb grün: die Reihe AUS → EIN →
AUS fällt dabei nicht auf, weil der Vorzustand jedes Mal passt. Auffallen
muss eine Reihe aus **zwei AUS** — und das ist der Normalfall. In der
Nacht vom 12. auf den 13.11. hat 108 **107 Meldungen** geschickt, alle
`relay_on = false`, ohne einen einzigen Wechsel; unter der Mutation hätte
der Zähler über Nacht dreistellig gestanden. Test ergänzt, mit dieser
Reihe als Anker.

## Läufe

* Backend **1924 passed, 45 skipped** — `TEST_DATABASE_URL` gesetzt.
* **385 e2e-Tests grün** mit `--workers=1`.
* `ruff`, `ruff format`, `mypy`, `tsc`, `eslint` grün.

## Was dieser PR nicht tut

**Die Vergangenheit wird nicht nachgerechnet.** `device.switch_cycles`
zählt ab jetzt anders und bleibt auf dem Stand, den die alte Zählung
erreicht hat — bei 108 also auf 1, obwohl es zwei waren. Ein Backfill
wäre aus `relay_reading` möglich, und er stünde dann für zwei
verschiedene Zähldefinitionen in einer Spalte. Die Zahl ist eine
Betriebsgröße und kein Abrechnungswert; wer die wahre Zahl für den
Testzeitraum braucht, bekommt sie aus `testtage-108.sql` Block 1.
