---
titel: Zimmerübersicht
kategorie: Die Seiten
stichworte: Zimmer, Status, belegt, reserviert, Reinigung, gesperrt, Allgemeinbereich, Etage
rollen: alle
stand: 2026-10-25
route: /zimmer
---

Die Liste aller Zimmer und Allgemeinbereiche, mit Nummer, Etage,
Raumtyp und Status. Von hier führt jede Zeile auf die Detailseite.

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

## Die Spalte „Aktiv"

Ein Zimmer, das nicht aktiv ist, wird von der Steuerung übergangen. Das
ist der Schalter für einen Raum, der umgebaut wird oder dauerhaft nicht
geheizt werden soll — nicht für eine kurzfristige Sperre.

## Neues Zimmer

Nur Administratoren. Nummer, Etage, Raumtyp und Orientierung; die
Heizzonen und die Geräte kommen danach auf der Detailseite dazu. Ein
Zimmer ohne Zone bekommt keinen Sollwert — es fehlt dann die Stelle, auf
die er sich bezieht.

Für einen Allgemeinbereich wird ein **nicht buchbarer** Raumtyp gewählt
und anschließend auf der Detailseite die Betriebszeit eingetragen.
