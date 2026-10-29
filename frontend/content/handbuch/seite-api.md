---
titel: API & Webhooks
kategorie: Die Seiten
stichworte: Import, Belegungsliste, Erwartet bis, Konflikte, Listen-Wächter, Mail
rollen: alle
stand: 2026-10-25
route: /einstellungen/api
---

Der Zustand des Belegungs-Imports. Hier steht, ob die Liste von heute da
ist — und wenn etwas fehlt, ist das die erste Seite, auf die man sieht.

## Der Statuskopf

Eine Ampel mit drei Zuständen:

| Anzeige | Heißt |
|---|---|
| Aktuell | Die Liste von heute ist eingegangen. |
| Heute noch kein Import | Heute noch nichts da, die Frist läuft noch. |
| Veraltet | Die Frist ist überschritten. |

Daneben: **Zuletzt eingegangen** mit Zeitpunkt und Zeitzone, und
**Erwartet bis**.

Dass die Zeitangabe ihre Zone sichtbar trägt, hat einen Anlass. Am
26.09.2026 schlug der Wächter täglich 23 Minuten zu früh an, weil der
Eingangszeitpunkt in Weltzeit neben einer Frist in Ortszeit stand —
beide ohne Einheit, und damit sah es wie ein Vergleich aus.

## Erwartet bis

Die Uhrzeit in Ortszeit, bis zu der die Liste eingegangen sein soll. Nur
Administratoren können sie ändern.

**Sie wird an der Beobachtung eingestellt, nicht geschätzt.** Oben steht,
wann die Liste tatsächlich kommt; die Frist gehört dahinter. Im Haus
trifft sie gegen 10:38 ein — eine Frist um 09:00 würde jeden Tag
anschlagen, und ein Melder, dem niemand mehr glaubt, überwacht nichts.

## Der Listen-Wächter

Zusätzlich zur Ampel läuft eine stündliche Prüfung: kommt **acht
Stunden** lang keine Liste, geht eine Mail an die Adresse unter
„Hotel-Stammdaten". Pro Listendatum höchstens eine Mail — ein Wächter,
der stündlich dasselbe schickt, wird weggefiltert.

Die acht Stunden sind eine **Server-Einstellung** und stehen nicht auf
dieser Seite. Wer sie ändern will, braucht Zugang zum Server; der Weg
steht im Betriebshandbuch (RUNBOOK §10al).

> Nicht zu verwechseln mit dem **Relais-Test T3.0** — das ist die
> ausstehende Messung am Relais-Pfad der Infrarot-Heizkörper. Beide
> Aufgaben hießen in der Planung „T3".

## Letzte Importe

Die letzten Läufe, neueste zuerst, höchstens 30. Je Zeile:

- **Eingegangen** — wann die Mail ankam.
- **Listendatum** — für welchen Tag die Liste gilt. Das ist der
  verlässliche Bezug, nicht der Eingang: eine Liste kann nachts für den
  Vortag eintreffen.
- **Belegt**, **Geschlossen**, **Abreise geändert** — was der Import
  bewirkt hat.
- **Konflikte** — Zeilen, die nicht zu den vorhandenen Daten passten.
  Eine Zahl über null ist ein Grund, unter „Belegungen" nachzusehen.
- **Ergebnis** — ob der Lauf durchging.
