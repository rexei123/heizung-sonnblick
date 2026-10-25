---
titel: Dashboard
kategorie: Die Seiten
stichworte: Übersicht, Kacheln, Melder, Algorithmen-Lauf, Belegungsliste
rollen: alle
stand: 2026-10-25
route: /
---

Die Startseite. Sie beantwortet eine Frage: **muss ich jetzt etwas tun?**
Alles andere steht auf den Seiten darunter.

## Die Kacheln

**Belegte Zimmer** und **Ø Raumtemperatur** sind Lagebilder, keine
Melder. Sie sagen, wie das Haus gerade dasteht.

**Geräte online** zählt die Thermostate, von denen in der jüngsten Zeit
etwas gekommen ist. Eine Zahl, die unter der Gesamtzahl liegt, ist nicht
sofort ein Fehler — Funkstille von einer Stunde kommt vor. Dauerhaft
niedrig ist ein Fall für die Seite „Thermostate".

**Schwache Batterie** zählt die Geräte, deren Spannung über die letzten
24 Stunden niedrig liegt. Das ist eine **Information**, kein Auftrag:
getauscht wird, wenn ein Gerät drei Stunden nicht mehr funkt, nicht wenn
eine Spannung einen Wert unterschreitet. Ein Einbruch unter Motorlast
sieht wie ein Lebensende aus und ist keines — Gerät 102 lag am 04.10.2026
zwei Tage bei 2,6 V und war danach wieder bei 3,5 V, ohne Tausch.

**Ventil prüfen** und **Zimmer zu warm** sind die beiden echten Melder.
„Zimmer zu warm" vergleicht nicht gegen eine feste Grenze, sondern gegen
**vergleichbare Zimmer**: Räume, die gerade frei sind. Nur so ist der
Melder im Oktober und im Jänner derselbe. Was er sucht, ist ein
abgefallener Kopf — ein Ventil ohne Kopf steht offen.

**Aktive Übersteuerungen** ist ein Zustandszähler. Eine Übersteuerung,
die seit Tagen läuft, ist der häufigste Grund für „das Zimmer reagiert
nicht auf die Automatik".

**Fenster offen** steht heute dauerhaft auf **0**, und das ist keine
Aussage über die Fenster im Haus: die Thermostate liefern ihre
Fenstererkennung ab Werk ausgeschaltet, und eingeschaltet wurde sie nie.
Die Kachel wird erst nach der Erprobung (Sprint 23 T2) etwas melden
können. Bis dahin ist eine 0 dort kein Befund.

## Letzter Algorithmen-Lauf

Die wichtigste Zeile der Seite. Die Steuerung rechnet alle fünf Minuten;
steht hier eine Zeit, die weiter zurückliegt, rechnet gerade **nichts**,
und dann ist jede andere Zahl auf dieser Seite ein Standbild.

Steht „Noch nie", ist die Steuerung seit dem letzten Start nicht
durchgelaufen.

## Belegungsliste

Zeigt, wann die Liste von heute eingegangen ist. Kommt sie nicht, geht
nach acht Stunden eine Mail an die hinterlegte Adresse — der
**Listen-Wächter**. Was dann zu tun ist, steht unter
[Belegungsliste fehlt](/handbuch/ablauf-liste-fehlt).
