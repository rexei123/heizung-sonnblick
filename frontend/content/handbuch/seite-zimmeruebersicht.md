---
titel: Zimmerübersicht
kategorie: Die Seiten
stichworte: Zimmer, Status, belegt, reserviert, Reinigung, gesperrt, Allgemeinbereich, Etage, Übersteuern, Details
rollen: alle
stand: 2026-10-30
route: /zimmer
---

Die Liste aller Zimmer und Allgemeinbereiche, mit Nummer, Etage,
Orientierung und Status — dazu Ist und Soll des Schlafzimmers und, ganz
rechts, die zwei Knöpfe für jede Zeile.

## Übersteuern, ohne die Seite zu wechseln

**„Übersteuern" öffnet die Temperatur-Eingabe direkt in der Liste.** Es
ist dieselbe Eingabe wie auf der Zimmerseite im Reiter „Übersteuerung":
ein Wert je Heizzone, die Dauer, der Grund, und das Häkchen „Gast kann bis
Check-out nicht ändern" mit denselben Regeln.

Nach dem Abschicken bleibt das Fenster offen und zeigt den gesetzten Wert
mit seiner Restzeit — das ist die Bestätigung. Wer es schließt, steht
wieder in der Liste, und die Spalte „Übersteuerung" sagt dann „Aktiv".

**Wann der Knopf grau ist**, mit dem Grund als Hinweis am Mauszeiger:

| Grau, weil | Was zu tun ist |
|---|---|
| Das Zimmer ist nicht belegt | Eine Wunschtemperatur gilt nur für belegte Zimmer. Ab dem Check-in geht es wieder. |
| Die Übersteuerung ist dauerhaft gesperrt | Zuerst die Sperre aufheben — der Knopf dafür steht in der Kopfzeile der Zimmerseite. |

Eine Sperre **bis Check-out** lässt den Knopf stehen. Sie nimmt dem Gast
das Rad, nicht der Rezeption die Eingabe: ein vereinbarter Wert lässt sich
weiter korrigieren, ohne die Sperre dafür zwischendurch zu lösen.

Ein **Allgemeinbereich** lässt sich ebenfalls übersteuern — dort mit einer
Dauer in Stunden statt mit „Bis Check-out", weil ein Bereich keine Abreise
hat. Am Handy stehen beide Knöpfe nur als Symbol da; der Name steht am
Mauszeiger und wird vorgelesen.

**„Details"** führt wie bisher auf die Zimmerseite, mit Stammdaten,
Heizzonen, Geräten, Verlauf und Engine.

## Was die Status bedeuten

| Status | Heißt |
|---|---|
| Belegt | Ein Gast ist eingecheckt. Es gilt der Sollwert für „belegt". |
| Reserviert | Anreise steht an. Ab dem Vorheiz-Vorlauf wird gewärmt. |
| Frei | Kein Gast. Es gilt der Sollwert für „frei". |
| Reinigung | Zwischenstatus nach der Abreise. Heizt wie „frei". |
| Gesperrt | Nicht vermietbar. Heizt wie „frei". |
| Allgemeinbereich | Kein Gästezimmer — Bar, Rezeption, Speisesaal. Es gilt die Betriebszeit. |

„Allgemeinbereich" steht dort bewusst anstelle von „frei". Dass in der
Bar gerade kein Gast gemeldet ist, ist keine Information.

Bei „Reinigung" und „Gesperrt" steht zusätzlich „Automatik angehalten":
Anreisen und Abreisen setzen den Status dieser Zimmer nicht mehr um.

## Ist und Soll

**Ist** ist der Mittelwert der gesunden Thermostate im Schlafzimmer,
**Soll** der Wert, den die Steuerung zuletzt gesetzt hat. Liegt das Ist
mehr als zwei Grad unter dem Soll, steht die Zahl in Farbe — ein Hinweis,
kein Alarm. Ein Zimmer darf kalt sein, wenn gerade erst angereist wurde.

Ein Strich heißt „kein Wert": kein Gerät, kein Messwert, oder kein
Schlafzimmer. Warum, steht auf der Zimmerseite.

## Die Spalte „Übersteuerung"

Drei Zustände, nie gemischt: ein **Schloss**, wenn die Übersteuerung
gesperrt ist; **„Aktiv"**, wenn gerade eine läuft; sonst leer.

## Neues Zimmer

Nur Administratoren. Nummer, Etage, Raumtyp und Orientierung; die
Heizzonen und die Geräte kommen danach auf der Detailseite dazu. Ein
Zimmer ohne Zone bekommt keinen Sollwert — es fehlt dann die Stelle, auf
die er sich bezieht.

Für einen Allgemeinbereich wird ein **nicht buchbarer** Raumtyp gewählt
und anschließend auf der Detailseite die Betriebszeit eingetragen.
