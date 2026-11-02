---
titel: Thermostate
kategorie: Die Seiten
stichworte: Geräte, Vicki, Batterie, Funkstille, nur messen, Reserve-Pool, Ventil prüfen, sortieren, Relais, Knopf am Relais, Paketverlust, Funk
rollen: alle
stand: 2026-11-02
route: /devices
---

Alle Thermostate des Hauses in einer Liste: Bezeichnung, Zone, Zustand,
Batterie und letzte Meldung. Rund hundert Zeilen — deshalb ist die
Sortierung das wichtigste Bedienelement der Seite.

## Sortieren

Zwei Reihenfolgen: **Fehlerstatus** (Vorgabe) stellt die Geräte nach
oben, bei denen etwas nicht stimmt; **Bezeichnung** sortiert alphabetisch
und ist der Weg, ein bestimmtes Gerät zu finden.

## Die Zustände

**Nicht online (Funkstille).** Seit Längerem keine Meldung. Das ist der
Zustand, der einen Handgriff verlangt: **getauscht wird bei etwa drei
Stunden Funkstille.**

**Ventil prüfen.** Die Rückmeldung passt nicht zum Befehl — der Kopf
sitzt möglicherweise nicht richtig oder das Ventil klemmt.

**Zimmer zu warm.** Der Raum liegt deutlich über vergleichbaren, gerade
freien Zimmern. Der typische Grund ist ein abgefallener Kopf auf einem
offenen Ventil.

**Batterie niedrig / schwach.** Die Spannung über 24 Stunden liegt tief.
Eine **Information**, kein Auftrag — siehe oben, der Auftrag heißt
Funkstille. Daneben steht die Spannung in Volt; bei „unbekannt" steht
bewusst keine Zahl, weil unter drei Messwerten keine Aussage möglich ist.

**Im Lager.** Keiner Zone zugeordnet. Reserve für einen Tausch.

## Grenzen am Gerät

Auf der Detailseite eines Thermostats steht die Karte **Grenzen am
Gerät**. Sie sagt, in welchem Bereich das **Drehrad** verstellen darf —
im Haus 15–25 °C im Zimmer und 18–25 °C im Bad.

**Die Zahl kommt vom Gerät, nicht von uns.** Das ist der Punkt: was die
Steuerung gesendet hat, ist eine Absicht; was dort steht, ist die Antwort
des Geräts. Deshalb gibt es drei Zustände:

| Anzeige | Heißt |
|---|---|
| 15–25 °C, bestätigt vor … | das Gerät hat es gemeldet. Gültig. |
| nicht bestätigt | es hat noch nicht geantwortet. **Kein Fehler** — es meldet sich von selbst. |
| 5–30 °C, „Soll wäre 15–25 °C" | Werkseinstellung am Gerät. Der Gast kann auf 30 drehen. |

**Die Grenze gilt nur für das Rad.** Die Steuerung darf darüber hinaus
stellen: Frostschutz und Fenster-Sicherheit bleiben wirksam, ein Bad mit
Untergrenze 18 fällt im Sommerbetrieb trotzdem auf 10.

Gesetzt werden die Grenzen nicht aus der Oberfläche, sondern mit einem
Werkzeug auf dem Server — der Weg steht im Betriebshandbuch
(RUNBOOK §10ap). **Eine Änderung der Grenzen am Raumtyp wirkt also nicht
von selbst am Gerät.** Das ist Absicht: ein Klick würde sonst bis zu
45 Funkbefehle auslösen.

## Paketverlust

Auf der Detailseite eines Geräts steht neben **Signal** die Kachel
**Paketverlust**. Sie sagt, wie viel von dem, was das Gerät gesendet hat,
überhaupt angekommen ist — und zwar gemessen, nicht geschätzt: jede
Meldung trägt eine laufende Nummer, auch die verlorenen. Fehlen Nummern,
fehlen Meldungen.

**Was ein hoher Wert bedeutet.** Die Temperaturen werden lückenhaft, und
Schaltbefehle bleiben unbestätigt — bei einem Relais wiederholt die
Steuerung dann, mit wachsendem Abstand. Über **10 %** ist der Bereich, in
dem das regelmäßig passiert; der Wert steht dann in Gelb, über 25 % in
Rot.

**Ein Strich ist nicht null.** Liegen weniger als zwei Meldungen im
Fenster, gibt es keine Lücke, die man sehen könnte. Die Kachel schreibt
dann einen Strich und sagt im Hinweis, warum — eine Null würde einen
Funk behaupten, der nicht gemessen wurde.

**Ein Neustart ist kein Verlust.** Nach einem Batteriewechsel oder einem
Stromausfall beginnt die Nummernfolge von vorn. Die Kachel erkennt das,
rechnet beide Teile getrennt und weist den Neustart eigens aus.

**Was die Kachel nicht beantwortet, ist die Richtung.** Eine verlorene
Meldung kann am Funkweg, am Gateway oder am Netz dahinter liegen.

## nur messen

Der Schalter sitzt auf der Zimmer-Detailseite im Tab „Geräte". Ein Gerät
auf „nur messen" liefert weiter Werte, bekommt aber keinen Sollwert
geschickt. Der Sollwert der Zone wird trotzdem errechnet und angezeigt.

Derzeit gesetzt bei **027** und **056**. Gerät **100** liegt im
Reserve-Pool.

**Beim Setzen wird das Rad am Gerät gesperrt**, beim Zurücknehmen wieder
freigegeben — ein Fühler, der unmontiert im Raum liegt, soll nicht
verstellbar sein.

**Mit einer Ausnahme seit 29.10.2026:** steht auf dem Zimmer eine
Gast-Sperre, bleibt das Rad beim Zurücknehmen der Rolle **gesperrt**. Die
Sperre hat dann einen zweiten Grund, und der gilt weiter. In diesem Fall
wird kein Funkbefehl gesendet — es gibt nichts zu ändern —, und der
Hinweis unter dem Schalter sagt es.

## Relais

Für die Infrarot-Heizkörper gibt es den Relais-Pfad im Programm. **Das
erste Gerät ist angelegt und geprüft** (109, Eingang, seit 01.11.2026) —
es hängt an der Zuleitung, ein Panel ist noch nicht angeschlossen, und
geschaltet wird noch nichts.

Die Messung, von der das abhing, ist durch: der Relais-Test **T3.0** hat
am 01.11.2026 ergeben, dass ein abgelaufener Timer das Relais abfallen
lässt. Damit trägt die Grundregel des Pfades — **ein Relais wird nie
dauerhaft eingeschaltet, sondern immer nur auf Zeit.** Fällt die
Steuerung aus, geht das Panel von selbst aus.

### Der Knopf am Relais

**Zweimal kurz auf den Knopf schaltet ein Relais von Hand um.** Das ist
eine Eigenschaft des Geräts, kein Handgriff des Programms — und das
Relais **meldet den Druck von selbst**, die Steuerung erfährt es also
ohne Nachfragen.

Was dann passiert, hängt davon ab, ob das Relais **in Betrieb genommen**
ist:

| Zustand des Relais | Von Hand eingeschaltet |
|---|---|
| in Betrieb genommen | die Steuerung schaltet es wieder ab, sobald die Meldung da ist — sie will AUS, und AUS hat Vorrang |
| nur angelegt (Eingangstest) | es **bleibt an**. Vor der Inbetriebnahme schickt die Steuerung bewusst keinen Befehl |

**Für Sie heißt das:** während des Eingangstests nimmt nur derselbe
Knopf das Einschalten zurück — noch einmal zweimal kurz drücken. Im
Betrieb braucht es den Knopf nicht; wer ein Panel warm haben will,
nimmt die Übersteuerung im Programm, weil die ein Ende hat.

## Bezeichnung ändern

Die Bezeichnung lässt sich in der Liste direkt bearbeiten; mit Escape
wird abgebrochen. Alles andere — Zone, Tausch, nur messen — läuft über
die Zimmer-Detailseite, damit ein Gerät nicht ohne seinen Raum geändert
wird.
