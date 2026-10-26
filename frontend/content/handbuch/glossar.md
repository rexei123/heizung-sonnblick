---
titel: Glossar
kategorie: Grundlagen
stichworte: Begriffe, Sollwert, Zone, Raumtyp, Vicki, Listen-Wächter, Relais-Test, Übersteuerung, Hysterese
rollen: alle
stand: 2026-10-25
---

Die Wörter, die in der Software und in diesem Handbuch vorkommen — in
alphabetischer Reihenfolge, mit dem Begriff, der daneben leicht
verwechselt wird.

## A bis F

**Absenkung.** Der niedrigere Sollwert außerhalb der Nutzungszeit. Bei
einem Gästezimmer heißt die Zeit „Nacht", bei einem Allgemeinbereich
„außerhalb der Betriebszeit".

**Allgemeinbereich.** Ein Raum, der nicht gebucht wird: Bar, Rezeption,
Speisesaal, Gang. Sein Raumtyp ist als nicht buchbar gekennzeichnet; er
hat eine Betriebszeit statt einer Belegung.

**Belegungsliste.** Die Datei, die das Buchungssystem jeden Morgen per
Mail schickt. Daraus kommen Anreise, Abreise und damit der Zustand
„belegt".

**Betriebszeit.** Beginn und Ende der Nutzung eines Allgemeinbereichs,
eingetragen beim Zimmer. „24:00" ist als Ende erlaubt und heißt
Mitternacht.

**Downlink.** Ein Funkbefehl von der Steuerung an ein Thermostat. Kostet
Batterie — deshalb der Versandfilter.

**Frostschutz.** Die untere Grenze, auf die ein Zimmer fällt, wenn es
frei ist und ein Fenster offen steht oder der Sommerbetrieb läuft.

## G bis N

**Grenzen am Gerät.** Der Bereich, in dem das **Drehrad** verstellen
darf — im Haus 15–25 °C, im Bad 18–25 °C. Nicht zu verwechseln mit der
**Kappung**: die Grenze am Gerät hindert den Gast am Drehen, die Kappung
begrenzt den errechneten Sollwert. Beide kommen aus demselben Raumtyp.

**Hysterese.** Die Entscheidung, einen Befehl **nicht** zu senden, weil
die Änderung zu klein ist. Steht im Algorithmenverlauf unter der
Schichtenliste.

**Kappung.** Die letzte Schicht: der Sollwert wird auf die Grenzen des
Raumtyps begrenzt. Eine Wunschtemperatur kann dadurch niedriger wirken
als eingegeben.

**Listen-Wächter.** Die Überwachung der Belegungsliste: kommt sie länger
als eine eingestellte Frist nicht, geht eine Mail an die hinterlegte
Adresse. Seit 25.10.2026 im Betrieb, Frist acht Stunden.

> **Nicht zu verwechseln mit dem Relais-Test T3.0.** Beide Aufgaben
> hießen in der Planung „T3". Der Listen-Wächter überwacht die
> **Belegungsliste** und ist fertig. Der Relais-Test T3.0 ist eine
> **Messung am Relais-Pfad** für die Infrarot-Heizkörper und steht noch
> aus — es ist kein Relais montiert.

**nur messen.** Ein Thermostat, das Werte liefert, aber keinen Sollwert
bekommt. Der Sollwert der Zone wird weiter errechnet und angezeigt, nur
nicht gesendet.

## O bis Z

**Raumtyp.** Die Vorlage hinter einem Zimmer: Sollwerte, Grenzen, und ob
er gebucht werden kann. Ein Zimmer erbt vom Raumtyp, der Raumtyp vom
Hausstandard.

**Relais.** Der vorbereitete, **nicht in Betrieb** befindliche Pfad zum
Schalten der Infrarot-Heizkörper. Im Programm vorhanden, in der Anlage
nicht.

**Relais-Test T3.0.** Die ausstehende Messung am Relais-Pfad. Siehe die
Abgrenzung beim Listen-Wächter.

**Sollwert.** Die Temperatur, die ein Zimmer haben soll. Das Ergebnis der
sechs Schichten.

**Übersteuerung.** Ein Wert, der die Automatik für eine bestimmte Zeit
schlägt — von der Rezeption gesetzt oder am Thermostat gedreht.

**Übersteuerungs-Sperre.** Der Schalter, der eine Drehung am Thermostat
nicht mehr übernimmt. Zwei Formen: **bis Check-out** (endet mit der
Abreise) und **dauerhaft**. Nicht zu verwechseln mit dem Zimmerstatus
„gesperrt" — dort nimmt die Steuerung das Zimmer ganz heraus, hier läuft
sie normal weiter.

**Vicki.** Das Funk-Thermostat am Heizkörper (Hersteller MClimate). In
der Oberfläche heißt es „Thermostat".

**Zone.** Die Heizgruppe innerhalb eines Zimmers. Ein Zimmer kann mehrere
haben, zum Beispiel Schlafzimmer und Bad; jede Zone bekommt ihren eigenen
Sollwert.
