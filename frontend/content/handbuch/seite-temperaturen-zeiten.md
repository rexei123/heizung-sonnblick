---
titel: Temperaturen & Zeiten
kategorie: Die Seiten
stichworte: Hausstandard, Nachtabsenkung, Vorheizen, Sollwert, global, Vorrang
rollen: admin
stand: 2026-10-25
route: /einstellungen/temperaturen-zeiten
---

Der **Hausstandard**: die Werte, die gelten, wenn weder das Zimmer noch
der Raumtyp etwas eigenes sagt. Die Seite trägt den Vorrang selbst oben
als Zeile: Zimmer → Raumtyp → Hausstandard.

Nur Administratoren können hier speichern. Sichtbar ist die Seite für
alle — was hier steht, ist Betriebswissen.

## Globale Temperaturen

| Feld | Wirkt wann | Bereich |
|---|---|---|
| Zimmer belegt | Gast eingecheckt | 16–26 °C |
| Zimmer frei | kein Gast | 10–22 °C |
| Nachtabsenkung | im Nachtfenster | 14–22 °C |

**„Nicht festgelegt" ist eine Entscheidung, keine Lücke.** Steht ein Feld
leer, entscheidet der Raumtyp. Im Haus ist das der Normalfall für
„belegt" und „frei": nur die Nachtabsenkung ist hausweit gesetzt, die
beiden anderen Werte kommen aus den Raumtypen. Neben jedem Feld steht,
wie viele Räume den Wert tatsächlich nutzen.

## Globale Zeiten

**Nachtabsenkung Start** und **Ende** in Ortszeit, Format HH:MM. Über
Mitternacht ist erlaubt — 20:00 bis 06:00 ist das Fenster im Haus.

**Vorheizen vor Check-In** in Minuten, 0 bis 240. Ein Zimmer im Status
„Reserviert" beginnt so viele Minuten vor der Check-in-Zeit zu heizen.

## Nach dem Speichern

Die Meldung lautet „Gespeichert — Engine übernimmt in ≤ 60 s". Das ist
wörtlich zu nehmen: der neue Wert wirkt beim nächsten Lauf, nicht
sofort. Wer den Erfolg prüfen will, sieht auf der Zimmer-Detailseite im
Tab „Engine" nach, welchen Wert die Schichten gerade verwenden.

## Sommerbetrieb

Ist der Sommerbetrieb an, steht hier ein Hinweis. Dann gilt nichts von
dieser Seite — alle Räume laufen auf Frostschutz. Der Schalter dafür
liegt unter „Szenarien".
