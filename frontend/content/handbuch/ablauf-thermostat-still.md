---
titel: Ein Thermostat meldet sich nicht
kategorie: Abläufe an der Rezeption
stichworte: Funkstille, offline, Batterie, tauschen, Ventil prüfen, Gateway
rollen: alle
stand: 2026-10-25
---

Auf dem Dashboard steht „Geräte online" niedriger als sonst, oder ein
Zimmer reagiert nicht. Die erste Frage ist **nicht**, welches Gerät —
sondern **wie viele**.

## 1. Einer oder alle?

**Dashboard → Geräte online.** Fehlen eines oder zwei, ist es ein
Gerätefehler. Fehlen viele, ist es der Funk: das Gateway im Haus gibt
die Meldungen weiter, und fällt es aus, sind alle Geräte auf einmal
still. Dann ist nichts am einzelnen Zimmer zu machen — das ist
Server- und Technikarbeit.

## 2. Welches Gerät

**Thermostate**, Sortierung „Fehlerstatus". Die betroffenen stehen
oben.

| Anzeige | Bedeutung | Was tun |
|---|---|---|
| Nicht online (Funkstille) | keine Meldung mehr | ab etwa drei Stunden: Batterie tauschen |
| Ventil prüfen | Rückmeldung passt nicht zum Befehl | Kopf prüfen, Jemand muss hin |
| Zimmer zu warm | Raum deutlich über vergleichbaren | meist abgefallener Kopf |
| Batterie niedrig | Spannung über 24 h tief | **nur Information**, kein Auftrag |

## 3. Die Regel für den Tausch

**Getauscht wird bei etwa drei Stunden Funkstille, nicht bei einer
Spannung.** Das ist keine Schlamperei, sondern ein Befund: Gerät 102 lag
am 04.10.2026 zwei Tage bei 2,6 V — das sieht wie ein leerer Akku aus —
funkte dabei lückenlos weiter und war am 06.10. wieder bei 3,5 V. Der
Einbruch kam vom Motorstrom, nicht vom Lebensende.

Eine niedrige Spannung ist also ein Hinweis darauf, wo man zuerst
nachsieht. Der Auftrag kommt vom Schweigen.

## 4. Was im Zimmer passiert, während ein Gerät still ist

Die Steuerung rechnet weiter und schickt weiter. Das Thermostat hält
seinen letzten empfangenen Sollwert — ein stilles Gerät ist also nicht
automatisch ein kaltes Zimmer. Umgekehrt: nach dem Batteriewechsel kommt
der Kopf mit einem gedrifteten Wert zurück und wird von der Steuerung
innerhalb weniger Minuten wieder eingefangen. Dafür ist nichts zu tun.

## 5. Zwei Geräte, bei denen Stille kein Fehler ist

Die Vickis **027** und **056** stehen auf **nur messen**. Sie bekommen
keine Befehle, melden aber. Und Gerät **100** liegt im Reserve-Pool —
ohne Zone, ohne Aufgabe.
