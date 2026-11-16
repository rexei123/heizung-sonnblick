---
datum: 2026-11-15
thema: Auswertungswerkzeug für die Panel-Frage
pr: offen
---

# Zwei Zahlen nebeneinander, sonst entscheidet man über das falsche Gerät

## Wofür

Der Betreiber überlegt, ein zweites Panel für die Rezeption zu kaufen.
Die Frage dahinter ist „hält ein Panel die 23 Grad", und sie ist heute
**nicht beantwortbar**: am 14./15.11. lief das Panel nur 60 bis 67
Prozent der Zeit, weil der Relais-Timer nach 30 Minuten ablief und die
Mindestpause danach weitere zehn Minuten hielt. Eine Messung gegen diese
Steuerung würde dem Gerät zuschreiben, was in der Steuerung liegt.

`python -m heizung.scripts.relais_auswertung` liefert die beiden Zahlen
**nebeneinander**: den Einschaltanteil je Stunde und den Abstand zwischen
Ist und Soll. Daraus wird die Entscheidung ablesbar:

| Einschaltanteil in den Stunden mit Heizwunsch | Ist unter Soll? | Schluss |
|---|---|---|
| nahe 100 % | ja | **das Panel ist zu schwach** |
| nahe 100 % | nein | reicht |
| unter ~80 % | ja | **die Steuerung bremst noch** — Frage nicht reif |

Die dritte Zeile ist die Lage von heute. Deshalb gehört die Messung
hinter REFRESH und nicht davor.

## Warum ein Werkzeug und keine Seite

Die Entscheidung fällt **einmal**, nach zwei bis drei Tagen, und sie
braucht Zahlen zum Weitergeben — keine Ansicht zum täglichen Hinsehen.
Ein Werkzeug kostet keine Oberfläche, keine e2e-Tests und keine Kachel,
die danach für immer dasteht; seine Ausgabe lässt sich in eine Nachricht
kopieren. Dasselbe Muster wie `funkqualitaet` (§10au), aus demselben
Grund.

Die **Ansicht** kommt ohnehin: der Relais-Verlauf auf der Geräteseite
(Diagramm, Tabelle je Tag, CSV) steht als eigener Punkt im Auftrag. Er
beantwortet „wie lief es gestern", nicht „reicht das Gerät".

## Wie der Sollwert gelesen wird

Aus derselben `hard_clamp`-Zeile und mit derselben Vorrangregel wie im
Regler. **Die Regel selbst steht nicht im Werkzeug**, sondern in
`SollStand.fuer`: das Werkzeug baut je Stunde einen `SollStand` und fragt
ihn. Zwei Rechnungen für denselben Sollwert wären zwei Wahrheiten, und
genau daran lag der Fehler vom 15.11. (§5.53).

## Was die Zahlen nicht sagen

* **Auflösung zehn Minuten.** Das Relais meldet alle zehn Minuten; die
  Phasengrenzen liegen bis zu zehn Minuten neben der Wirklichkeit, die
  Dauern stimmen im Mittel. Einer Meldung werden höchstens 15 Minuten
  zugerechnet, damit eine Lücke von Stunden nicht als „die ganze Zeit
  ein" zählt.
* **Eine Lücke ist keine Null.** Ein Fenster ohne Meldung erscheint als
  Strich. Eine 0 wäre eine Behauptung über ein Gerät, von dem wir nichts
  gehört haben — und sie zöge den Gesamtanteil nach unten, also genau in
  die Richtung, die eine Fehlentscheidung über das Panel begründen würde.
* **Der Gesamtanteil ist nach erfasster Zeit gewichtet**, nicht der
  Mittelwert der Stundenwerte. Am Rand des Fensters sind die Stunden
  immer kurz; der Mittelwert wäre bei **jedem** Lauf falsch.
* **Nur Stunden mit Heizwunsch zählen für die Panel-Frage.** In einer
  warmen Stunde ist ein niedriger Anteil richtig.

## Tests

15 Tests. Elf davon rein (Sollwert-Vorrang, Zeitzone am Eingang,
Gewichtung), vier gegen die Datenbank.

Die tragenden sind die Gewichtungs-Tests: eine Randstunde mit sechs
erfassten Minuten und 100 Prozent neben einer vollen Stunde mit 60
Prozent ergibt **64**, nicht 80. Und der DB-Test prüft eine Stunde voll
EIN neben einer halben — ein Test auf „irgendein Prozentwert kommt
heraus" wäre grün, auch wenn die Fensterfunktion die Phasen falsch
zuordnet.

Dazu die Zeitzone in beide Richtungen (November eine Stunde, Juli zwei)
und die `isinstance(True, int)`-Falle beim Sollwert aus dem JSON.

**Ein Testfehler in eigener Sache:** der erste Ende-zu-Ende-Test rief
`_verteile` auf und fiel mit „asyncio.run() cannot be called from a
running event loop". Genau davor warnt §5.14, und dieselbe Lesson
beschreibt die Naht: `main` parst, `_verteile` startet, und der Test
**ersetzt** `_verteile` statt es aufzurufen.

## Noch nicht geprüft: der erste Lauf gegen die Produktion

Das Werkzeug lief gegen die Test-Datenbank, **nicht** gegen den Server.
Die Abfragen dahinter sind an den Produktionsdaten belegt — der
Einschaltanteil von 60–67 % stammt aus derselben Rechnung, über `psql`
gelesen —, das Programm selbst aber nicht.

Eigenen Code im api-Container der Produktion laufen zu lassen, wäre für
eine schönere Zahl zu viel Risiko gewesen. Der erste Lauf gehört deshalb
als Prüfschritt hinter den Merge:

```bash
docker exec deploy-api-1 python -m heizung.scripts.relais_auswertung --stunden 24
```

Erwartet: zwei Abschnitte (Rezeption/Eingang und Bar/Barbereich), je
Stunde eine Zeile, Einschaltanteil im Bereich 50–67 %, Soll 23 bzw. 22.
