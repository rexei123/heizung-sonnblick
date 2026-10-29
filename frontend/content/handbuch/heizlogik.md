---
titel: Wie das Haus heizt
kategorie: Grundlagen
stichworte: Sollwert, Schichten, Sommer, Absenkung, Vorheizen, Fenster, Kappung, Allgemeinbereich, nur messen, Relais
rollen: alle
stand: 2026-10-25
---

Jedes Zimmer bekommt alle fünf Minuten einen Sollwert errechnet. Das
Ergebnis entsteht in sechs Schichten, die **in dieser Reihenfolge**
laufen; jede darf überschreiben, was die vorige entschieden hat. Wer
wissen will, warum ein Zimmer eine bestimmte Temperatur hat, liest die
Schichten von oben nach unten und hält bei der letzten an, die etwas
getan hat.

{{karte}}

## Die sechs Schichten

**0 — Sommer.** Ist der Sommerbetrieb an, bleibt es beim Frostschutz. Die
Schichten darunter laufen trotzdem und schreiben ihren Befund mit, damit
im Verlauf steht, was ohne Sommerbetrieb gegolten hätte.

**1 — Grundwert.** Hier entscheidet der Zustand des Zimmers: belegt, frei
oder — bei einem Allgemeinbereich — in Betrieb. Woher der Wert kommt,
steht im Abschnitt „Vorrang der Werte".

**2 — Zeit.** Vorheizen vor der Anreise, Absenkung in der Nacht. Die
Zeiten sind Ortszeit; die Umstellung auf Winterzeit ist mitgedacht.

**3 — Übersteuerung.** Eine Wunschtemperatur von der Rezeption oder eine
Drehung am Thermostat durch den Gast. Sie gilt bis zu ihrem Ablauf und
schlägt die Schichten 1 und 2.

**4 — Sicherheit.** Offenes Fenster oder ein abgenommener Kopf. Im freien
Zimmer fällt der Sollwert auf Frostschutz, im belegten auf den Wert für
„frei" — nicht auf Frostschutz, damit ein Gast nicht in ein kaltes Zimmer
zurückkommt, weil er zehn Minuten gelüftet hat.

> **Die Fenstererkennung ist derzeit nicht in Betrieb.** Die Thermostate
> liefern sie ab Werk **ausgeschaltet**, und eingeschaltet wurde sie nie.
> Diese Schicht reagiert heute also allein auf den **abgenommenen Kopf**.
> Wer lüftet, hat keine Wirkung auf den Sollwert — das Zimmer heizt
> weiter gegen das offene Fenster. Die Erprobung ist vorbereitet
> (Sprint 23 T2); bis sie abgeschlossen ist, steht hier bewusst, was
> nicht wirkt.

**5 — Kappung.** Zuletzt wird auf die Grenzen des Raumtyps begrenzt. Was
Schicht 3 erlaubt hat, kann hier noch gekürzt werden — das ist der Grund,
warum eine eingestellte Wunschtemperatur manchmal niedriger wirkt als
eingegeben.

## Vorrang der Werte

Drei Ebenen, die oberste gewinnt:

1. **Zimmer** — ein Wert, der für genau dieses Zimmer eingetragen ist.
2. **Raumtyp** — der Wert des Raumtyps, zu dem das Zimmer gehört.
3. **Hausstandard** — der Wert für das ganze Haus.

Ist eine Ebene nicht gesetzt, entscheidet die nächste. Ein Feld, in dem
„nicht festgelegt" steht, ist deshalb keine Lücke, sondern eine Aussage:
hier entscheidet der Raumtyp.

Auf der Seite „Raumtypen" steht neben jedem Wert, **ob er wirkt** und
woher der wirksame Wert kommt. Dass ein Wert eingetragen ist, heißt
nämlich nicht, dass er gilt.

{{werte}}

## Allgemeinbereiche

Bar, Rezeption, Speisesaal und die anderen gemeinsamen Räume sind keine
Gästezimmer: sie werden nicht gebucht, haben also keine Anreise und keine
Belegung. Ihr Raumtyp ist als **nicht buchbar** gekennzeichnet, und daraus
folgt zweierlei.

**Sie haben eine Betriebszeit statt einer Belegung.** Eingetragen wird
sie beim Zimmer: Beginn und Ende, zum Beispiel 08:00 bis 24:00. Innerhalb
der Betriebszeit gilt der Wert „Betrieb", außerhalb der Wert
„Absenkung". Das Feld „Belegt" bleibt bei einem Allgemeinbereich
ungenutzt — dort steht es deshalb auch so.

**Ihr Raumtyp-Wert wirkt ohne Zwischenschritt.** Bei einem Gästezimmer
muss ein Raumtyp-Wert als eigene Zeile hinterlegt sein, um den
Hausstandard zu schlagen; bei einem Allgemeinbereich zählt die Spalte des
Raumtyps unmittelbar. Das ist der Unterschied, der am 24.10.2026 dazu
geführt hat, dass die Bar 21 °C hatte, obwohl beim Raumtyp 18 °C stand.

Im Zimmerstatus steht bei diesen Räumen „Allgemeinbereich" und nicht
„frei" — „frei" würde heißen, dass gerade kein Gast da ist, und das ist
bei einer Bar keine Information.

## Übersteuerung ohne Belegung

In einem Gästezimmer braucht eine Wunschtemperatur einen Gast. In einem
Allgemeinbereich nicht: wer die Bar vor einer Abendveranstaltung wärmer
haben will, setzt eine Übersteuerung **mit Ablauf**. Der Ablauf ist
Pflicht, vorgeschlagen werden vier Stunden, mehr als 24 Stunden gehen
nicht. Gekappt wird auch hier auf die Grenzen des Raumtyps, und zwar im
Programm und nicht erst in der Anzeige — eine Eingabe, die darüber liegt,
wird beim Speichern auf die Grenze gesetzt und sagt das.

## Geräte, die nur messen

Manche Köpfe sind auf **nur messen** gestellt. Sie liefern
Ist-Temperatur, Ventilstellung und Batteriestand, bekommen aber keinen
Sollwert geschickt. Gedacht ist das für einen Kopf, der an einem
Heizkörper hängt, der von Hand geregelt wird, oder für ein Gerät, das zur
Beobachtung montiert ist.

Für die Zone heißt das: **der Sollwert wird weiter errechnet** und steht
im Verlauf, er wird nur nicht gesendet. Bis zum 24.10.2026 zeigte eine
solche Zone 10 °C — den Frostschutz —, weil die Rechnung mit dem
Sendeverbot verwechselt wurde. Heute steht dort der Wert des Raumtyps,
und daneben der Hinweis, dass nichts gesendet wird.

Aktuell auf „nur messen": die Vickis **027** und **056**. Gerät **100**
liegt im Reserve-Pool und ist keiner Zone zugeordnet.

## Relais

Für die Infrarot-Heizkörper ist ein Relais-Pfad **vorbereitet, aber nicht
in Betrieb**. Im Programm gibt es die Geräteart, die Zonenart „kein
Stellglied" und die Unterscheidung im Versandfilter; es ist kein Relais
montiert, und es wird keines geschaltet.

Was das für die Bedienung heißt: eine Zone ohne Stellglied zeigt einen
Sollwert, aber keine Rückmeldung von einem Gerät. Die Ist-Temperatur
kommt dort vom Sensor im Raum, nicht vom Thermostat.

## Warum nicht jede Änderung ankommt

Zwischen Rechnung und Thermostat sitzt ein Filter, und das ist Absicht —
jeder Funkbefehl kostet Batterie und Motorbewegung:

- Gesendet wird, wenn sich der Sollwert um mindestens 0,5 °C ändert.
- Oder wenn seit dem letzten Befehl sechs Stunden vergangen sind.
- Geräte auf „nur messen" bekommen nichts.
- Ein Relais hätte einen eigenen Weg — siehe oben, es ist keines in
  Betrieb.

Dazu kommt der Funk selbst: ein Thermostat meldet sich im Regelfall alle
paar Minuten, im ungünstigen Fall dauert eine Bestätigung bis zu sechs
Stunden. Ein eben gesetzter Wert, der am Gerät noch nicht angekommen ist,
ist deshalb kein Fehler, sondern der Normalfall für die nächsten Minuten.

## Wenn etwas nicht stimmt

Die Zimmer-Detailseite hat den Tab **Engine**. Dort stehen die sechs
Schichten der letzten Auswertung mit Eingangs- und Ausgangswert und einer
Begründung je Schicht. Das ist die Antwort auf „warum hat dieses Zimmer
diese Temperatur" — und sie ist vollständig, weil jede Schicht auch dann
schreibt, wenn sie nichts getan hat.

Der Tab **Verlauf** daneben zeigt die gemessenen Temperaturen der letzten
Stunden als Kurve, mit dem Sollwert als Linie darüber. „Engine"
beantwortet das Warum, „Verlauf" das Ob.
