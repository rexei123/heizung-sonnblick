---
datum: 2026-11-13
thema: Meldung, wenn der Fühler einer Relais-Zone schweigt
pr: offen
---

# Vierzehn Stunden kalte Rezeption, und niemand hat es erfahren

Vorgabe des Betreibers vom 13.11.2026, nach der Analyse der Nacht. **Kein
Steuerpfad** — der sichere Zustand ist gebaut und bleibt unberührt; hier
entsteht ausschließlich eine Mitteilung.

## Der Anlass, mit Zahlen

Fühler **056** (Zone Eingang, Rezeption) meldete am 12.11. um **14:41**
zum letzten Mal und wieder am 13.11. um **04:44** — vierzehn Stunden,
`fCnt 2904 → 2988`, also **83 verlorene Frames**. Die Zone führt seit dem
12.11. das Relais **108** in Betrieb.

Die Steuerung hat richtig gehandelt. In jedem Durchlauf stand:

```
{'zone_id': 299, 'soll': '17.0', 'ist': None,
 'regler': 'unveraendert', 'regler_grund': 'kein_istwert'}
```

Das ist der Zwangs-AUS aus Prüfung 1 des Zweipunktreglers (S5): fehlender
Istwert schaltet ab und bricht dafür sogar die Mindestlaufzeit. Das Panel
blieb aus, 0 W, 107 Relais-Meldungen ohne einen einzigen Verlust.

**Gemeldet wurde es nicht, und zwar von keiner Stelle:**

| Melder | Verhalten | Grund |
|---|---|---|
| Health-Stufe `silent` | schwieg | verlangt **> 24 h** offline (AE-53); 14 h sind `degraded`, und die ist ausdrücklich stumm |
| Totalausfall-Wächter | schwieg **korrekt** | 103 Geräte online, 605 Messwerte je Stunde |
| Kachel „Geräte online" | zeigte 102 von 103 | eine Zahl, aus der niemand „die Rezeption ist blind" liest |

§5.76 wörtlich: jeder Mechanismus war grün, die Wirkung war beherrscht —
und die Mitteilung fehlte vollständig.

## Was gebaut ist

**Ein Wächter je Zone**, alle fünf Minuten, Schwelle **30 Minuten**:
`services/relais_fuehler.py` urteilt, `tasks/funk_tasks.pruefe_relais_fuehler`
hält fest und mailt.

| | |
|---|---|
| **Umfang** | nur Zonen mit mindestens einem Relais, für das `relay_service.darf_schalten` gilt |
| **Zustand** | zwei Marken in `business_audit`, `target_type = heating_zone`, `target_id` = Zone |
| **Mail** | eine je Episode (Bremse 6 h), eine Entwarnung bei Rückkehr |
| **Kachel** | „Fühler Relais-Zone", rot, Zusatzzeile „längste Stille N min" |

### Warum nur Zonen mit einem Relais in Betrieb

Ein stummer Fühler ist überall ein Mangel. In einer Zone mit Vickis
regelt aber **jedes Gerät nach seinem eigenen internen Fühler weiter** —
der Raum wird ungenau, nicht kalt. Ein Relais hat keinen eigenen Fühler:
fehlt der Zonenwert, heizt die Zone **gar nicht**. Nur das rechtfertigt
eine Mail.

„In Betrieb" entscheidet `relay_service.darf_schalten` und nicht dieser
Wächter. Vier eigene Prüfungen mit demselben Inhalt wären beim ersten
Nachjustieren falsch (§5.53). Nebeneffekt, gewollt: ein Relais mit
stehender Schutz-Sperre fällt heraus — es kann ohnehin nicht schalten.

### Warum 30 Minuten und nicht die Grenze des Reglers

Der Regler hält einen Messwert bis zum 2,5-fachen des Keepalive-Fensters
für brauchbar, mit der Vorgabe also **fünf Stunden**. Diese Meldung
schlägt nach **30 Minuten** an, also nach drei verpassten Meldungen.

**Zwei Grenzen für zwei Zwecke.** Die des Reglers entscheidet, wann
abgeschaltet wird — sie darf nicht nervös sein. Diese entscheidet, wann
jemand hinsieht, und entscheidet sonst **nichts**. Der Vorlauf von vier
Stunden ist der ganze Zweck, und ein Validator in den Settings hält ihn
fest: die Warn-Grenze muss unter dem Keepalive-Fenster liegen, sonst käme
die Warnung nach dem Abschalten.

### Zwei Entscheidungen, die im Entwurf nicht standen

**Eine Zone ohne Fühler bekommt einen eigenen Grund.** Ein in Betrieb
genommenes Relais in einer Zone ohne Fühler kann **nie** heizen; der
Regler meldet dort dauerhaft `kein_istwert`. Ein Wächter, der genau hier
schweigt, weil es keine Stille zu messen gibt, wäre der nächste Melder,
der dann nichts sagt, wenn es am meisten zählt (§5.79). Betreff und Text
sind andere, und die Mail nennt **keine Minutenzahl** — die gab es nie.

**Bei hausweitem Ausfall schweigt dieser Melder.** Dann kommt überhaupt
nichts an, die Totalausfall-Mail sagt das bereits, und jede Zonen-Mail
daneben ist dieselbe Nachricht in kleinerer Schrift. Der Wert liegt im
anderen Fall: das Haus ist in Ordnung und **eine** Zone ist blind — so
war es in dieser Nacht. Folge, gewollt: endet der hausweite Ausfall und
bleibt eine Zone stumm, beginnt die Episode erst dann.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Grenze inklusiv statt exklusiv | **2 Tests rot** |
| `darf_schalten`-Filter entfernt | **2 Tests rot** |
| Zone ohne Fühler gilt als in Ordnung | **3 Tests rot** |
| „nie gehört" gilt als in Ordnung | **1 Test rot** |
| Fühler ohne Etikett wird herausgefiltert | **1 Test rot** |
| Totalausfall-Tor entfernt | **1 Test rot** |
| Wiederholungsbremse entfernt | **1 Test rot** |
| Entwarnung auch ohne vorherigen Alarm | **1 Test rot** |
| `target_id`-Filter im Zustands-Helfer entfernt | **1 Test rot** |
| Kachel immer neutral | **1 Test rot** |
| Zusatzzeile entfernt | **2 Tests rot** |
| ohne Fühler trotzdem Minuten anzeigen | **1 Test rot** |
| Kachel aus `CARD_META` entfernt | **zuerst grün — echte Lücke, geschlossen** |

**Die letzte Probe war eine Lücke, und keine kleine.** Wer eine Kachel in
`buildCards` ergänzt und in `CARD_META` vergisst, baut genau das, was PR
#402 für die Höhe behoben hat: die Seite springt beim Laden. 23 von 23
Tests blieben grün. Geschlossen mit einem Vergleich im bestehenden
Skelett-Test — geprüft wird die **Eigenschaft** („die Zahl der Karten
ändert sich beim Eintreffen der Daten nicht") und nicht eine Zahl, die
bei jeder neuen Kachel an einer zweiten Stelle nachzuziehen wäre.

Dass der Test für die Kachelzahl selbst fällt, ist sein Zweck — und er
fiel an **zwei** Stellen (Zeile 106 und die Mobil-Prüfung), nicht an
einer.

## Läufe

* Backend **1916 passed, 45 skipped** — `TEST_DATABASE_URL` gesetzt, die
  DB-Tests sind gelaufen. Docker lokal gestartet, Test-DB auf 0039.
* **385 e2e-Tests grün** mit `--workers=1`, wie die CI läuft.
* `ruff check`, `ruff format --check`, `mypy`, `tsc`, `eslint` grün.
* Ein Bestandstest ist gefallen und hat seinen Zweck erfüllt:
  `test_api_dashboard::test_dashboard_kpi_admin_200_schema` hält die
  Schlüsselmenge der Antwort fest. Die zwei neuen Schlüssel sind
  nachgetragen — eine Schema-Erweiterung soll eine Entscheidung sein,
  keine Entdeckung.

## Offen

**Die Kachel hat kein Ziel.** Ein Klick führt nirgends hin, weil es keine
Ansicht der Relais-Zonen gibt, auf der sich die Zahl auflöst — und eine
Liste aller Zimmer tut das nicht. Sobald es eine gibt, gehört sie
hierher; die Regel dieser Seite ist, dass nur eine Kachel ein Ziel
bekommt, deren Zahl sich dort auflöst.
