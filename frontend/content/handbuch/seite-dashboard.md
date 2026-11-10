---
titel: Dashboard
kategorie: Die Seiten
stichworte: Übersicht, Kacheln, Melder, Algorithmen-Lauf, Belegungsliste
rollen: alle
stand: 2026-11-08
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

**Fenster offen** zeigt **„Erkennung inaktiv"** statt einer Zahl,
solange kein Thermostat zurückgemeldet hat, dass seine Fenstererkennung
eingeschaltet ist. Die Geräte liefern sie ab Werk ausgeschaltet.

Bis zum 07.11.2026 stand dort eine **0**, und das war die gefährlichere
Anzeige: eine 0 liest sich als „es ist kein Fenster offen", richtig war
„niemand hat gemessen". Hausweit gab es zu diesem Zeitpunkt keine
einzige Meldung über ein offenes Fenster — bei 49 belegten
Temperatureinbrüchen allein in einem Zimmer.

**Funk-Empfang** ist die Kachel, die einen Ausfall zeigt, während alle
anderen Zahlen noch harmlos aussehen.

| Anzeige | Bedeutung |
|---|---|
| **online** | die letzte Meldung ist höchstens fünf Minuten alt |
| **verzögert** | fünf bis fünfzehn Minuten — einmal nachsehen |
| **keine Meldungen** | über fünfzehn Minuten. **Es kommen keine Messwerte mehr an**, und ab dieser Stufe geht auch eine Mail hinaus |

Darunter stehen zwei Zeilen: wann die letzte Meldung kam, und wie viele
in den letzten zehn Minuten eintrafen. Die zweite Zahl beantwortet eine
andere Frage als die erste — bricht die Menge ein, während die jüngste
Meldung frisch ist, ist etwas im Gange, das die erste Zahl nicht sieht.
Normal sind rund hundert.

**Warum diese Kachel nicht den Gateway-Status zeigt.** Am 07.11.2026 war
das Gateway in Ordnung und meldete sich als verbunden — und es kam
**31 Minuten** lang kein einziger Messwert an, weil eine Firewall-Regel
den Weg dahinter blockierte. Ein Gateway-Status hätte grün gezeigt. Diese
Kachel liest deshalb das **Ende** der Kette: was nicht ankommt, ist weg,
ganz gleich welches Glied es verloren hat.

**Befehle nicht angenommen** zählt die Geräte, die einen gesendeten
Sollwert nicht übernehmen. Die Steuerung hat dreimal nachgesendet, das
Gerät meldet weiter seinen eigenen Wert, und danach wird **nicht weiter
gesendet** — jeder Funkbefehl ist eine Motorbewegung und kostet Batterie.

Ein Klick auf die Kachel zeigt die betroffenen Geräte. Zusätzlich geht
eine Mail hinaus, einmal je Vorfall.

**Was zu tun ist.** Am Gerät nachsehen: sitzt der Kopf fest auf dem
Ventil, ist die Batterie frisch. Danach den Funk prüfen. Von Hand muss
nichts gesetzt werden — sobald das Gerät wieder annimmt, zieht die
Steuerung den Wert selbst nach.

**Das Zimmer ist dabei nicht kalt.** Das Gerät heizt, nur nach seinem
eigenen Wert. Liegt der höher als der gewünschte, ist das Zimmer zu warm
statt zu kalt. Deshalb ist die Kachel gelb und nicht rot.

**Warum die Zahl stehen bleibt, bis das Gerät antwortet.** Sie
verschwindet ausdrücklich **nicht** dadurch, dass die Steuerung
inzwischen etwas anderes will. Bis zum 08.11.2026 war genau das der Fall:
verschob die Steuerung ihr Ziel auf den Wert, den das Gerät ohnehin
hielt, sah die Lage behoben aus — und das Gerät hatte nie einen Befehl
angenommen. Der Befund kam beim nächsten Zielwechsel wieder, jedes Mal
mit drei weiteren Funkbefehlen, und war jedes Mal wieder weg, bevor ihn
jemand sah.

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
