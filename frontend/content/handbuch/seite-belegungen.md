---
titel: Belegungen
kategorie: Die Seiten
stichworte: Anreise, Abreise, Belegung, Liste, Import, Personen, Quelle
rollen: alle
stand: 2026-10-25
route: /belegungen
---

Wer wann in welchem Zimmer ist. Daraus entsteht der Zimmerstatus, und
daraus der Sollwert — diese Seite ist der Grund, warum ein Zimmer warm
oder kalt ist.

## Woher die Einträge kommen

Die Spalte **Quelle** unterscheidet zwei Wege:

- **Import** — aus der Belegungsliste, die das Buchungssystem jeden
  Morgen per Mail schickt. Der Regelfall.
- **Manuell** — von Hand eingetragen, über „Neue Belegung".

Ein importierter Eintrag wird beim nächsten Import überschrieben, ein
manueller nicht. Wer eine spontane Anreise von Hand einträgt und sie
steht am nächsten Tag doppelt in der Liste, sieht genau das.

## Neue Belegung

Zimmer, Anreise, Abreise, Personenzahl. Anreise und Abreise sind
**Kalendertage**; die Uhrzeiten kommen aus den Standardzeiten unter
„Hotel" (Check-in und Check-out) und müssen hier nicht eingetragen
werden.

Sobald die Belegung steht, ändert sich der Zimmerstatus beim nächsten
Lauf der Steuerung — also innerhalb von fünf Minuten.

## Vorheizen

Vor einer Anreise wird vorgewärmt. Wie lange vorher, steht unter
„Temperaturen & Zeiten" als „Vorheizen vor Check-In". Ein Zimmer im
Status „Reserviert" heizt deshalb schon, bevor jemand da ist.

## Wenn die Liste nicht kommt

Der Listen-Wächter meldet sich per Mail, wenn acht Stunden lang keine
Liste eingegangen ist. Der Ablauf dazu steht unter
[Belegungsliste fehlt](/handbuch/ablauf-liste-fehlt); was zuletzt
eingegangen ist, steht unter „API & Webhooks".
