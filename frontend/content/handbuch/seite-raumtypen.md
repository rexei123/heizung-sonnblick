---
titel: Raumtypen
kategorie: Die Seiten
stichworte: Raumtyp, Vorlage, Grenzen, buchbar, Allgemeinbereich, wirksam, Wirksamkeit
rollen: admin
stand: 2026-10-25
route: /raumtypen
---

Die Vorlagen hinter den Zimmern. Ein Raumtyp trägt Sollwerte, Grenzen und
die Angabe, ob er gebucht werden kann — jedes Zimmer erbt davon.

## Eingetragen ist nicht wirksam

Das ist die wichtigste Zeile dieser Seite. Neben jedem Wert steht, **ob
er wirkt** und woher der wirksame Wert kommt.

Der Grund: die Steuerung löst Sollwerte über eigene Regelzeilen auf, und
die Spalten eines Raumtyps stehen in dieser Reihenfolge **unter** dem
Hausstandard. Bei einem **buchbaren** Raumtyp zählt die Spalte deshalb
erst, wenn für ihn eine Regelzeile angelegt ist. Bei einem
**Allgemeinbereich** zählt sie unmittelbar.

Daher der Befund vom 24.10.2026: beim Raumtyp der Bar standen 18 °C, die
Bar hatte 21 °C. 18 war eingetragen, 21 war wirksam — und die Seite sagte
es nicht.

## Werte wirksam machen

Bei einem Raumtyp, dessen Werte nicht wirken, gibt es den Knopf, der die
Spalten in eine Regelzeile überträgt. Er ändert damit **wirksame
Sollwerte** und wird mitgeschrieben.

> Für die Raumtypen der **Gästezimmer** ist das derzeit nicht
> freigegeben. Bis die Prüfung abgeschlossen ist, wird auf dieser Seite
> nichts gespeichert.

## Felder

| Feld | Gästezimmer | Allgemeinbereich |
|---|---|---|
| Belegt | Sollwert bei eingechecktem Gast | ungenutzt |
| Frei / Betrieb | Sollwert ohne Gast | Sollwert in der Betriebszeit |
| Nacht / Absenkung | im Nachtfenster | außerhalb der Betriebszeit |
| Mindest- und Höchstwert | Grenzen der Kappung (Schicht 5) | dieselben |

Die Grenzen sind kein Vorschlag: Schicht 5 kürzt jede Wunschtemperatur
darauf, auch die von der Rezeption.

## Buchbar oder nicht

Das Kennzeichen entscheidet mehr als die Beschriftung:

- **buchbar** — Gästezimmer. Belegung, Vorheizen, Nachtabsenkung,
  Übersteuerung nur bei eingechecktem Gast.
- **nicht buchbar** — Allgemeinbereich. Betriebszeit statt Belegung,
  Übersteuerung jederzeit mit Ablauf, Status „Allgemeinbereich".

Ein Raumtyp lässt sich nur löschen, wenn kein Zimmer ihn verwendet.
