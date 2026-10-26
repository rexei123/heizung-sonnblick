---
titel: Ein Zimmer im Detail
kategorie: Die Seiten
stichworte: Stammdaten, Heizzonen, Geräte, Verlauf, Engine, Übersteuerung, Betriebszeit, Temperatur ändern
rollen: alle
stand: 2026-10-25
route: /zimmer/[id]
---

Alles zu einem Zimmer, in sechs Tabs. Oben stehen Nummer, Status und die
beiden Knöpfe, die etwas bewirken: **Temperatur ändern** und die Sperre
für Übersteuerungen.

## Temperatur ändern

Setzt eine Wunschtemperatur mit Ablauf — das ist Schicht 3 der
Heizlogik. Bei einem Gästezimmer geht das **nur bei belegtem Zimmer**;
der Hinweis steht unter dem Knopf, wenn er nicht nutzbar ist. Bei einem
Allgemeinbereich geht es immer, dafür ist der Ablauf Pflicht
(Vorschlag vier Stunden, höchstens 24).

Die Eingabe wird auf die Grenzen des Raumtyps gekappt, und zwar beim
Speichern. Wer 28 °C einträgt und 24 °C zurückbekommt, hat nicht
falsch geklickt — die Grenze des Raumtyps liegt bei 24.

## Die sechs Tabs

**Stammdaten.** Nummer, Etage, Raumtyp, Orientierung. Bei einem
Allgemeinbereich steht hier zusätzlich die **Betriebszeit**: Beginn und
Ende der Nutzung. „24:00" als Ende ist erlaubt und heißt Mitternacht.
Ein halbes Fenster — nur Beginn oder nur Ende — wird abgelehnt.

**Heizzonen.** Die Heizgruppen des Zimmers, etwa Schlafzimmer und Bad.
Jede Zone bekommt ihren eigenen Sollwert. Die Zonenart sagt, was die
Zone zum Stellen hat: Thermostate, kein Stellglied, oder beides.

**Geräte.** Die Thermostate je Zone, mit Batteriestand, letzter Meldung
und dem Schalter **nur messen**. Hier wird auch getauscht: ein Gerät aus
dem Reserve-Pool nimmt den Platz des alten ein, das alte wird
ausgemustert.

**Verlauf.** Die gemessenen Temperaturen als Kurve, mit dem Sollwert als
Linie. Zeigt, **ob** geheizt wurde.

**Engine.** Die sechs Schichten der letzten Auswertung, mit Eingangs-
und Ausgangswert und einer Begründung je Schicht. Zeigt, **warum** der
Sollwert so ist. Das ist die Seite für jede Frage, die mit „warum" anfängt.

**Übersteuerung.** Die laufenden und abgelaufenen Wunschtemperaturen des
Zimmers, mit Quelle (Rezeption oder Gast am Thermostat) und Ablauf. Hier
wird eine Übersteuerung auch vorzeitig beendet.

## Die Sperre für Übersteuerungen

Der Schalter oben rechts verhindert, dass eine Drehung am Thermostat
übernommen wird. Gedacht für Zimmer, in denen Gäste die Einstellung
verstellen und sich danach beschweren. Er sperrt **nicht** die
Wunschtemperatur von der Rezeption.

Beim Sperren wird gefragt, **wie lange**:

| Form | Gilt | Wann richtig |
|---|---|---|
| Bis Check-out | endet mit der Abreise von selbst | der Regelfall: es geht um **diesen** Gast |
| Dauerhaft | bleibt, bis jemand sie aufhebt | das Zimmer selbst soll kein bedienbares Rad haben |

**Warum die Frage gestellt wird.** Eine dauerhafte Sperre, die niemand
zurücknimmt, trifft den **nächsten** Gast: er dreht am Rad, nichts
passiert, und an der Rezeption gibt es keine Erklärung dafür — die
Ursache ist eine Entscheidung von vorletzter Woche. „Bis Check-out"
nimmt diese Sorge weg; der Belegungsabgleich löst die Sperre mit der
Abreise.

Ist gesperrt, steht unter dem Knopf, **welche Form** gilt. Das ist die
Zeile, die sagt, ob sich jemand später darum kümmern muss.

**Im Allgemeinbereich gibt es nur „dauerhaft".** Eine Bar hat keine
Abreise — eine Sperre „bis Check-out" würde dort nie enden, und ein
Versprechen ohne Einlösung ist schlechter als keines. Die Auswahl sagt
das an der Stelle, an der man sie sucht.

Beim Sperren werden laufende Wunschtemperaturen des Zimmers aufgehoben;
die Auswahl nennt ihre Anzahl, bevor man sich entscheidet.
