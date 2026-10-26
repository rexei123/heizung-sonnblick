---
titel: Spontane Anreise oder Zimmerwechsel
kategorie: Abläufe an der Rezeption
stichworte: Anreise, Walk-in, Zimmerwechsel, Belegung, Vorheizen, kalt
rollen: alle
stand: 2026-10-25
---

Ein Gast steht da, der nicht in der Liste ist — oder bekommt ein anderes
Zimmer als geplant. Das Zimmer ist dann auf dem Wert für „frei", also
kühl, und die Steuerung weiß nichts davon.

## Der Ablauf

1. **Belegungen → Neue Belegung.** Zimmer, Anreise (heute), Abreise,
   Personenzahl. Die Uhrzeiten kommen aus den Standardzeiten; sie müssen
   nicht eingetragen werden.
2. **Warten, nicht nachhelfen.** Innerhalb von fünf Minuten steht das
   Zimmer auf „Belegt" und heizt auf den Wert für „belegt".
3. **Wenn der Gast gleich hinaufgeht:** zusätzlich eine
   Wunschtemperatur mit Ablauf setzen, etwa vier Stunden. Das ist der
   einzige Weg, schneller warm zu werden, als es die Automatik tut — und
   auch er beschleunigt nicht das Aufheizen, sondern nur das Ziel.
4. **Dem Gast sagen, wie lange es dauert.** Ein ausgekühltes Zimmer
   braucht eine bis drei Stunden. Diese Auskunft erspart den zweiten
   Anruf.

## Beim Zimmerwechsel: die alte Belegung schließen

Sonst heizen beide Zimmer. Die alte Belegung unter „Belegungen" auf das
heutige Datum enden lassen, dann die neue anlegen.

## Warum der Eintrag nötig ist, auch wenn der Gast schon oben ist

Ohne Belegung gilt für die Steuerung „kein Gast". Sie senkt dann in der
Nacht nicht nur ab, sie fährt auf den Frei-Wert — und ein Fenster, das
der Gast öffnet, zieht das Zimmer in Schicht 4 auf **Frostschutz**, weil
die Steuerung ein leeres Zimmer vor sich sieht. Bei einem belegten
Zimmer fällt es nur auf den Frei-Wert.

## Importierte und eingetragene Belegungen

Ein von Hand eingetragener Eintrag wird beim nächsten Import **nicht**
überschrieben. Steht die Buchung am nächsten Morgen auch in der Liste,
gibt es sie zweimal — einmal löschen, den importierten behalten.
