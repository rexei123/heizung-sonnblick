---
titel: Hotel-Stammdaten
kategorie: Die Seiten
stichworte: Hotel, Zeitzone, Check-in, Check-out, Warnungen, E-Mail, offline
rollen: admin
stand: 2026-10-25
route: /einstellungen/hotel
---

Die Angaben, die für das ganze Haus gelten. Drei Gruppen: Allgemein,
Standardzeiten, Warnungen.

## Allgemein

**Hotel-Name** steht in Mails und in Berichten.

**Zeitzone** ist die Grundlage **aller** Zeitangaben in der Steuerung.
Die Nachtabsenkung, die Betriebszeiten und das Vorheizen rechnen in
dieser Zone; intern speichert die Steuerung in Weltzeit und rechnet vor
jedem Vergleich um. Die Umstellung auf Winter- und Sommerzeit ist damit
mitgedacht. Die Zone zu ändern verschiebt jede eingetragene Uhrzeit in
ihrer Wirkung — das ist keine Anzeigeeinstellung.

## Standardzeiten

**Default Check-in** und **Default Check-out**. Eine Belegung wird mit
Kalendertagen eingetragen; diese beiden Zeiten machen daraus Zeitpunkte.
Check-in ist auch der Bezugspunkt für das Vorheizen: „Vorheizen vor
Check-In" zählt von hier zurück.

## Warnungen

**E-Mail für Warnungen** ist die Adresse, an die die Melder schreiben —
die fehlende Belegungsliste und die Engine-Alarme. Steht hier keine
Adresse, laufen die Melder weiter und schreiben ins Protokoll, aber
niemand erfährt davon.

**Gerät offline nach (Min)** legt fest, ab welcher Funkstille ein Gerät
auf der Geräteseite als nicht online gilt. Die Betriebsregel für den
Batterietausch — drei Stunden Funkstille — ist davon unabhängig; dieser
Wert steuert nur die Anzeige.

## Speichern

Der Knopf bleibt untätig, solange sich nichts geändert hat („Keine
Änderungen."). Nach dem Speichern wirken die Werte beim nächsten Lauf
der Steuerung.
