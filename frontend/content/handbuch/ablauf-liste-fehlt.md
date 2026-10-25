---
titel: Belegungsliste fehlt
kategorie: Abläufe an der Rezeption
stichworte: Liste, Import, Listen-Wächter, Mail, Veraltet, Belegung, Notbetrieb
rollen: alle
stand: 2026-10-25
---

Die Liste kommt jeden Morgen per Mail. Kommt sie nicht, weiß die
Steuerung nicht, wer heute anreist — und heizt die betroffenen Zimmer
nicht vor. Nach acht Stunden ohne Liste schickt der **Listen-Wächter**
eine Mail an die hinterlegte Adresse.

## 1. Nachsehen, ob sie wirklich fehlt

**API & Webhooks.** Oben steht die Ampel:

- **Aktuell** — die Liste ist da. Dann liegt das Problem woanders.
- **Heute noch kein Import** — noch nichts da, die Frist läuft noch.
- **Veraltet** — die Frist ist überschritten.

Darunter steht unter **Letzte Importe**, was zuletzt kam. Entscheidend
ist die Spalte **Listendatum**, nicht „Eingegangen": eine Liste kann
nachts für den Vortag eintreffen und sieht dann frisch aus.

## 2. Die heutigen Anreisen von Hand eintragen

Das ist der Teil, der eilt — nicht die Fehlersuche. Solange die Liste
fehlt, ist das Buchungssystem die Quelle:

1. Die Anreisen von heute aus dem Buchungssystem ablesen.
2. Unter **Belegungen → Neue Belegung** je Zimmer eintragen.
3. Die Zimmer stehen beim nächsten Lauf auf „Reserviert" und heizen vor.

Wer das bis zum Nachmittag macht, hat vorgeheizte Zimmer. Wer bis abends
wartet, hat kühle Zimmer und Anrufe.

## 3. Die Ursache klären

Drei Möglichkeiten, in dieser Reihenfolge:

- **Die Mail ist nicht abgeschickt worden.** Im Buchungssystem nachsehen,
  ob der Versand lief. Häufigster Fall.
- **Die Mail ist angekommen, wurde aber nicht verarbeitet.** Dann steht
  unter „Letzte Importe" ein Lauf mit einem Ergebnis, das nicht „ok"
  ist, oder Konflikte in der letzten Spalte.
- **Die Verarbeitung läuft nicht.** Dann fehlt der Eintrag ganz. Das ist
  Server-Arbeit; der Weg steht im Betriebshandbuch.

## Wenn der Wächter zu früh oder zu oft meldet

Dann steht **Erwartet bis** falsch. Oben auf derselben Seite steht, wann
die Liste tatsächlich kommt — die Frist gehört dahinter. Ein Melder, der
täglich grundlos anschlägt, wird nach einer Woche ignoriert, und dann
überwacht er nichts mehr. Ändern darf das ein Administrator.
