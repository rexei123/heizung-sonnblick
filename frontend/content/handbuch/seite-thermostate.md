---
titel: Thermostate
kategorie: Die Seiten
stichworte: Geräte, Vicki, Batterie, Funkstille, nur messen, Reserve-Pool, Ventil prüfen, sortieren
rollen: alle
stand: 2026-10-25
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

## nur messen

Der Schalter sitzt auf der Zimmer-Detailseite im Tab „Geräte". Ein Gerät
auf „nur messen" liefert weiter Werte, bekommt aber keinen Sollwert
geschickt. Der Sollwert der Zone wird trotzdem errechnet und angezeigt.

Derzeit gesetzt bei **027** und **056**. Gerät **100** liegt im
Reserve-Pool.

## Relais

Für die Infrarot-Heizkörper ist ein Relais-Pfad **vorbereitet, aber
nicht in Betrieb**: die Geräteart gibt es im Programm, montiert ist
keines, geschaltet wird keines. Die ausstehende Messung dazu heißt
**Relais-Test T3.0** — nicht zu verwechseln mit dem Listen-Wächter, der
die Belegungsliste überwacht und fertig ist.

## Bezeichnung ändern

Die Bezeichnung lässt sich in der Liste direkt bearbeiten; mit Escape
wird abgebrochen. Alles andere — Zone, Tausch, nur messen — läuft über
die Zimmer-Detailseite, damit ein Gerät nicht ohne seinen Raum geändert
wird.
