---
titel: Zimmerübersicht
kategorie: Die Seiten
stichworte: Zimmer, Status, belegt, reserviert, Reinigung, gesperrt, Allgemeinbereich, Etage, Temperatur, Boost, Details
rollen: alle
stand: 2026-11-03
route: /zimmer
---

Die Liste aller Zimmer und Allgemeinbereiche, mit Nummer, Etage,
Orientierung und Status — dazu Ist und Soll des Schlafzimmers und, ganz
rechts, die zwei Knöpfe für jede Zeile: **Temperatur** und
**Details**.

## Temperatur: zwei Wege, ohne die Seite zu wechseln

**„Temperatur" öffnet beide Wege direkt in der Liste** — oben den Boost,
darunter die Temperatur-Eingabe.

### Boost

**Ein Klick, und das Zimmer heizt bis zum Nachtbeginn.** Der Knopf sagt
vorher, bis wann — er trägt den Nachtbeginn des Zimmers, im Haus derzeit
„Boost bis 20:00". Wert und Endzeit kommen aus den Einstellungen des
Hauses; es ist nichts auszuwählen. Beide stehen unter Einstellungen →
Temperaturen und Zeiten: die Zeiten oben, der Wert als vierte Zeile
„Boost" unter Globale Temperaturen. **Wird das Nachtfenster verschoben,
verschiebt sich die Uhrzeit am Knopf mit** — die Zahl hier ist der Stand
des Hauses und keine feste Eigenschaft.

**Das Ende ist der nächste Wechsel des Nachtfensters.** Am Tag ist das der
Nachtbeginn, in der Nacht das Nachtende — danach gilt wieder die normale
Regel. Es gibt **kein Mindestmaß**: ein Boost fünf Minuten vor dem
Nachtbeginn endet nach fünf Minuten, und der Knopf zeigt das vorher.

**Ein Boost geht auch in einem freien Zimmer.** Das ist der Unterschied zur
Temperatur-Eingabe darunter: eine Wunschtemperatur gilt nur für belegte
Zimmer, ein Boost auch für ein Zimmer, das in einer Stunde bezogen wird.

**Läuft schon eine Übersteuerung, geht kein Boost** — der Hinweis nennt
dann den Wert, die Endzeit und die Stelle, an der er zu ändern ist. Das ist
Absicht: ein Boost, der einen von der Rezeption gesetzten Wert
überschreibt, wäre eine Überraschung.

### Temperatur-Eingabe

Dieselbe Eingabe wie auf der Zimmerseite im Reiter „Übersteuerung": ein
Wert je Heizzone, die Dauer, der Grund, und das Häkchen „Gast kann bis
Check-out nicht ändern" mit denselben Regeln.

Nach dem Abschicken bleibt das Fenster offen und zeigt den gesetzten Wert
mit seiner Restzeit — das ist die Bestätigung. Wer es schließt, steht
wieder in der Liste, und die Spalte „Übersteuerung" sagt dann, was gilt.

### Wann der Knopf grau ist

Der Knopf heißt auch dann „Temperatur" und bleibt stehen; der Grund steht
am Mauszeiger und wird vorgelesen. Grau wird er erst, wenn **keiner** der
beiden Wege geht:

| Grau, weil | Was zu tun ist |
|---|---|
| **Sommermodus aktiv** | Es heizt im ganzen Haus nichts. Ein Wert hätte hier keine Wirkung. |
| **Dauerhaft gesperrt** | Zuerst die Sperre aufheben — der Knopf dafür steht in der Kopfzeile der Zimmerseite. |
| **Kein Nachtfenster konfiguriert** | Ohne Nachtfenster gibt es kein Ende für einen Boost. Die Zeiten stehen unter Einstellungen → Temperaturen und Zeiten. |
| **Zimmer ist nicht belegt** | Steht nur, wenn auch kein Boost geht. Ab dem Check-in geht die Eingabe wieder. |

Eine Sperre **bis Check-out** lässt den Knopf stehen. Sie nimmt dem Gast
das Rad, nicht der Rezeption die Eingabe: ein vereinbarter Wert lässt sich
weiter korrigieren, ohne die Sperre dafür zwischendurch zu lösen.

Ein **Allgemeinbereich** lässt sich ebenfalls übersteuern — dort mit einer
Dauer in Stunden statt mit „Bis Check-out", weil ein Bereich keine Abreise
hat. **Einen Boost bekommt er nicht**: ohne Abreise und ohne Nachtfenster
im Sinne eines Zimmers gibt es kein Ende, auf das er laufen könnte. Am
Handy stehen beide Knöpfe nur als Symbol da; der Name steht am Mauszeiger
und wird vorgelesen.

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
**Soll** der Wert, den die Steuerung für **dieses Schlafzimmer** zuletzt
gesetzt hat. Beide Spalten sprechen also von derselben Zone — läuft eine
Wunschtemperatur nur für das Schlafzimmer, steht sie hier, und nicht der
Wert des übrigen Zimmers.

Liegt das Ist mehr als zwei Grad unter dem Soll, steht die Zahl in Farbe
— ein Hinweis, kein Alarm. Ein Zimmer darf kalt sein, wenn gerade erst
angereist wurde.

Ein Strich heißt „kein Wert": kein Gerät, kein Messwert, oder kein
Schlafzimmer. Warum, steht auf der Zimmerseite.

## Die Spalte „Übersteuerung"

Zwei Marken, und sie stehen **nebeneinander**: ein **Schloss**, wenn die
Übersteuerung gesperrt ist, und die laufende Übersteuerung selbst. Ist
beides der Fall, steht beides da; ist nichts davon der Fall, bleibt die
Zelle leer.

**Die laufende Übersteuerung nennt ihre Endzeit**, und ein Boost ist eigens
gekennzeichnet:

| Marke | Bedeutung |
|---|---|
| 🔥 **Boost bis 20:00** | Ein Boost läuft und endet zum Nachtbeginn — die Uhrzeit ist die des Hauses |
| **Aktiv bis 09:00** | Eine gewöhnliche Übersteuerung läuft, mit ihrer Endzeit |

Bis zum 02.11.2026 stand dort nur „Aktiv" — die Spalte verschwieg damit
die Endzeit, und ein Boost war von einer 24-Stunden-Eingabe nicht zu
unterscheiden.

Beides zusammen ist der Regelfall nach „Wert setzen und gleich
festhalten": die Wunschtemperatur läuft, und das Rad im Zimmer ist still.
Bis zum 31.10.2026 verdeckte das Schloss das „Aktiv" — die Spalte
verschwieg dann genau die Zahl, nach der man sie fragt.

## Neues Zimmer

Nur Administratoren. Nummer, Etage, Raumtyp und Orientierung; die
Heizzonen und die Geräte kommen danach auf der Detailseite dazu. Ein
Zimmer ohne Zone bekommt keinen Sollwert — es fehlt dann die Stelle, auf
die er sich bezieht.

Für einen Allgemeinbereich wird ein **nicht buchbarer** Raumtyp gewählt
und anschließend auf der Detailseite die Betriebszeit eingetragen.
