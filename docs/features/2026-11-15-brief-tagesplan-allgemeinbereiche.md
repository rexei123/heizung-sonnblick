---
datum: 2026-11-15
thema: Brief — Tagesplan für Allgemeinbereiche (Vorschlag, nicht gebaut)
status: Vorschlag, wartet auf Entscheidung
---

# Tagesplan für Allgemeinbereiche

**Wunsch des Betreibers:** mehrere Zeitfenster am Tag mit eigener
Temperatur, zum Beispiel 06:00–08:00 **25 °C**, 08:00–21:00 **22 °C**,
sonst Absenkung. Erste Stufe: **ein** Plan, der jeden Tag gleich gilt,
beliebig viele Fenster, Lücken sind Absenkung. Später Wochentag/Wochenende.

Dieser Brief ist ein Vorschlag. Es ist nichts gebaut.

---

## 1. Was es schon gibt, und warum das nicht reicht

Die Sollwert-Kette steht in `rule_config`: eine Zeile je Ebene, alle
Felder `NULL`-bar, und `NULL` heißt **erben**.

```
rule_config(room_id)        schlägt
rule_config(room_type_id)   schlägt
rule_config(NULL, NULL)     = hausweit
```

Für Zeiten gibt es dort heute genau **ein** Paar:

```python
night_start: time | None
night_end:   time | None
t_night:     Decimal | None
```

Und Layer 2 (`rules/engine.layer_temporal`) macht daraus ein
Nachtfenster: liegt die Ortszeit darin, gilt `t_night`. Die Logik dafür
ist `_is_in_night_window` und kann auch über Mitternacht
(`22:00 → 06:00`).

**Was fehlt**, ist nicht die Nacht, sondern **mehr als ein Fenster**.
Ein Bereich, der morgens wärmer sein soll als mittags, lässt sich mit
einem Paar nicht beschreiben — man müsste `t_night` als „Tagwert"
missbrauchen und das Fenster invertieren, und dann heißt ein Feld
namens `night` etwas anderes als sein Name. Das ist §5.51 (ein Feld, zwei
Bedeutungen) und der Grund, es **nicht** so zu bauen.

## 2. Datenmodell

Eine neue Tabelle, **neben** `rule_config` und nach demselben
Erbmuster:

```python
class Tagesplan(Base):
    __tablename__ = "tagesplan"

    id: int
    # Erbebene -- genau wie rule_config. Beide NULL = hausweit.
    room_id: int | None          # FK room, ON DELETE CASCADE
    room_type_id: int | None     # FK room_type, ON DELETE CASCADE
    name: str                    # "Allgemeinbereiche Winter", fuer die Oberflaeche
    aktiv: bool
    created_at / updated_at


class Tagesplanfenster(Base):
    __tablename__ = "tagesplan_fenster"

    id: int
    tagesplan_id: int            # FK tagesplan, ON DELETE CASCADE
    von: time                    # Ortszeit, ohne Zone (wall clock)
    bis: time                    # Ortszeit, ohne Zone
    temperatur: Decimal          # Numeric(4, 1)
```

**`Decimal`, nicht `float`.** Jeder Sollwert in diesem Projekt ist
`Numeric(4,1)`, und die Engine quantisiert am Ende selbst. Ein `float`
hier wäre die eine Stelle, an der 22,1 zu 22,099999 wird.

**`time` ohne Zone, und das ist Absicht.** Der Betreiber tippt die Zeit,
die an seiner Wand steht. Die Spalte trägt also **Wanduhrzeit**, wie
`night_start` heute. Die Umrechnung passiert beim Vergleich, nicht beim
Speichern:

```python
local_now = now.astimezone(ZoneInfo(ctx.timezone))
```

Das ist §5.65, und der Weg steht schon im Code. **Folge für die
Sommerzeit**, und sie ist zu benennen: ein Fenster „06:00–08:00" ist am
Umstellungstag im Frühjahr **eine Stunde kürzer**, wenn es die
übersprungene Stunde enthält, und im Herbst eine Stunde länger. Für
06:00–08:00 passiert nichts (die Umstellung liegt bei 02:00/03:00); ein
Fenster, das 02:00–04:00 enthält, hat an zwei Tagen im Jahr eine andere
Länge. **Das ist richtig so** — der Betreiber meint Wanduhrzeit, und
`ZoneInfo` liefert sie. Eine Speicherung in UTC würde das Fenster
stattdessen zweimal im Jahr **verschieben**, und das wäre falsch.

**Warum zwei Tabellen und nicht JSONB in `rule_config`.** Ein
JSONB-Feld `tagesplan` wäre eine Migration weniger und drei Nachteile
mehr: keine Prüfung auf Überlappung in der Datenbank, keine Sortierung
ohne Auspacken, und ein Audit, das den ganzen Plan als einen Wert
schreibt statt das geänderte Fenster. Bei etwas, das der Betreiber
selbst bearbeitet, ist die Tabelle die richtige Form.

**Überlappungen.** Zwei Fenster dürfen sich nicht überschneiden, sonst
entscheidet die Reihenfolge der Zeilen über die Temperatur — genau die
Sorte Nichtdeterminismus, die §0 S2 verbietet. Vorschlag: eine
`EXCLUDE`-Bedingung mit `btree_gist` je `tagesplan_id`, dazu die Prüfung
im Service für die klare Fehlermeldung (dasselbe Doppel wie bei
`replace_device`, §5.60).

**Fenster über Mitternacht** (23:00–01:00) brauchen eine Entscheidung.
Vorschlag: **nicht erlauben**, sondern in zwei Fenster zerlegen
(23:00–24:00 und 00:00–01:00). Begründung: eine `EXCLUDE`-Bedingung kann
mit einem umschlagenden Bereich nicht umgehen, und der Betreiber tippt
ohnehin lieber zwei Zeilen als eine mit einer Sonderregel. Die
`_is_in_night_window`-Logik bleibt davon unberührt — sie gehört zur
Absenkung, nicht zum Plan.

## 3. Einordnung in die Engine-Kette

Die Kette ist heute (Layer-Reihenfolge, `rules/engine`):

| Schicht | Aufgabe |
|---|---|
| 0 Sommer | Heizperiode aus? Dann Schluss |
| 1 `base_target` | Grundwert aus Belegung: `t_occupied` / `t_vacant` |
| **2 `temporal`** | **Nachtabsenkung, Vorheizen, Nachlauf** |
| 3 `manual_override` | Übersteuerung durch Mitarbeiter oder Gast |
| 4 `window_safety` | Fenster offen → Frostschutz bzw. Frei-Sollwert |
| 5 Kappung | Grenzen je Gerät |

**Der Tagesplan gehört in Schicht 2**, und zwar als **Erweiterung**, nicht
als neue Schicht. Begründung:

* Er beantwortet dieselbe Frage wie die Nachtabsenkung („welcher Wert
  gilt zu dieser Uhrzeit"), nur mit mehr als zwei Antworten. Zwei
  Schichten für eine Frage wären zwei Stellen, an denen jemand dieselbe
  Entscheidung ändern könnte — §5.53.
* Eine neue Schicht würde die Reihenfolge gegen Layer 3 und 4 neu
  verhandeln, und die ist seit Sprint 9.10d festgelegt und getestet.

**Verhältnis zur Absenkung.** Der Plan **ersetzt** das Nachtfenster nicht,
er **umschließt** es. Vorschlag für die Regel in Schicht 2:

1. Gibt es für dieses Zimmer einen aktiven Tagesplan **und** trifft ein
   Fenster auf die Ortszeit → dessen Temperatur gilt.
2. Trifft kein Fenster (Lücke) → `t_night`, also der vorhandene
   Absenkwert. **Das ist die Antwort auf „sonst Absenkung"** — und sie
   braucht kein neues Feld.
3. Gibt es keinen aktiven Plan → alles bleibt wie heute
   (`night_start`/`night_end`/`t_night`).

Punkt 3 ist der wichtige: **ohne Plan ändert sich nichts.** 47 Zimmer
laufen weiter wie bisher, der Plan betrifft nur die Bereiche, für die
einer angelegt wurde.

**Verhältnis zur Übersteuerung.** Layer 3 kommt **nach** Schicht 2 und
schlägt den Plan — unverändert. Das ist richtig und muss so bleiben: ein
Mitarbeiter, der die Bar auf 23 stellt, will 23, auch wenn der Plan 22
sagt. Die Übersteuerung läuft ab, danach greift der Plan wieder. **Zu
prüfen beim Bauen:** dass eine Zonen-Übersteuerung den Plan nicht
dauerhaft „gewinnt" — das ist genau der Fehler, den #414 im Relais-Pfad
behoben hat, nur in der anderen Richtung.

**Verhältnis zur Belegung.** Ein Allgemeinbereich ist nicht buchbar, also
ist `base_target` dort immer `t_vacant` (bzw. der Wert des Raumtyps). Der
Plan schreibt diesen Wert in Schicht 2 um. Für **Zimmer** gilt derselbe
Mechanismus, aber dort ist er selten sinnvoll — der Gast bestimmt, nicht
die Uhr. Vorschlag: der Plan ist technisch für jede Ebene möglich, die
Oberfläche bietet ihn aber nur an Raumtypen an, deren
`is_bookable = false` ist.

## 4. Oberfläche

**Die Seite gibt es schon — leer.** `frontend/src/app/profile/page.tsx`
ist ein `EmptyState` mit dem Text „Tag-, Nacht- und Wochenend-Heizprofile
für Räume", und `lib/handbuch/routen.ts` führt `/profile` auf den Artikel
`seite-profile`.

**Das ist genau dieser Wunsch, vor Monaten reserviert.** Der Tagesplan
gehört dorthin und nicht auf eine neue Seite. Ein zweiter Ort für
„Heizprofile" neben einer leeren Seite mit demselben Namen wäre die
Variante, bei der der Betreiber künftig an zwei Stellen sucht.

Vorschlag für den Aufbau:

* Liste der Pläne mit Ebene („hausweit", Raumtyp-Name, Zimmernummer),
  Namen und Zustand.
* Je Plan eine Tabelle der Fenster: **von**, **bis**, **Temperatur**, und
  eine Zeile zum Hinzufügen. Zeiten als `<input type="time">`, damit die
  Tastatur des Telefons passt.
* Unter der Tabelle eine **Tagesleiste**: 24 Stunden als Balken, die
  Fenster eingezeichnet, Lücken in der Farbe der Absenkung. Sie ist das
  eigentliche Bedienelement — eine Tabelle mit sechs Zeilen sagt nicht,
  ob 21:00 noch drin ist.
* Der Absenkwert (`t_night`) wird **angezeigt**, nicht hier bearbeitet —
  er gehört zu den Raumtypen. Mit Link dorthin.

**Umlaute und keine Ids**, wie im Anzeige-PR verlangt.

## 5. Audit

Jede Änderung an einem Plan oder Fenster schreibt `config_audit`, je
Feld, mit `scope_qualifier` = `tagesplan_id` — dasselbe Muster wie bei
den Raumtypen seit #408. Aktionen:

```
TAGESPLAN_ANGELEGT · TAGESPLAN_GEAENDERT · TAGESPLAN_GELOESCHT
TAGESPLAN_FENSTER_ANGELEGT · ..._GEAENDERT · ..._GELOESCHT
```

**Und im Engine-Trace:** Schicht 2 schreibt ohnehin einen `LayerStep`
(§5.23, auch im Pass-Through-Fall). Der `detail` bekommt die Marke
`tagesplan_fenster_<id>` statt `night_setback` — damit steht im
Engine-Panel, **welches** Fenster den Wert gesetzt hat. Ohne das wäre „22
statt 25" nicht nachvollziehbar.

## 6. Migration

Additiv: zwei neue Tabellen, keine Spalte geändert, keine entfernt.
`night_start`/`night_end`/`t_night` bleiben unberührt und bleiben in
Gebrauch (Punkt 2 und 3 der Regel oben).

**Kein Backfill.** Es gibt keinen Plan, bis jemand einen anlegt. Einen
Plan aus den heutigen Nachtfenstern zu erzeugen wäre eine Übersetzung,
die niemand bestellt hat — und sie würde 47 Zimmer von der einen Logik
auf die andere schieben, ohne dass sich ihr Verhalten ändern soll.

`btree_gist` braucht eine Extension (`CREATE EXTENSION IF NOT EXISTS
btree_gist`), falls die `EXCLUDE`-Bedingung kommt. Das ist in der
Migration zu prüfen — auf TimescaleDB ist sie vorhanden, aber „vorhanden"
ist eine Annahme, bis `\dx` es zeigt.

## 7. Aufwand in Tasks

| | Task | Umfang |
|---|---|---|
| T1 | Migration + Modelle + `EXCLUDE`-Bedingung, mit Roundtrip-Test (§5.56) | klein |
| T2 | Service: Pläne und Fenster lesen/schreiben, Überlappungsprüfung, Audit | mittel |
| T3 | Erbkette: `aktiver_tagesplan(room)` nach dem Muster von `rule_config` — **ein** Helfer, den Engine und Oberfläche benutzen (§5.53) | klein |
| T4 | Schicht 2 erweitern, `detail`-Marke, Tests mit `freeze_time` über alle Fenstergrenzen **und** über den Sommerzeit-Wechsel (§5.59, §5.65) | **mittel, Steuerpfad** |
| T5 | API: Endpunkte für Pläne und Fenster, nur Admin | klein |
| T6 | Oberfläche: Seite `/profile` füllen, Tagesleiste, e2e | **groß** |
| T7 | Handbuch `seite-profile` schreiben, Zahlen als `{{werte}}` (Regel 13) | klein |

**Zwei bis drei Sprints**, und T4 ist der Pflicht-Stop: er ändert den
Sollwert, den jedes Zimmer bekommt.

## 8. Was ich davon abraten würde

**Wochentag/Wochenend-Pläne in der ersten Stufe.** Der Wunsch nennt sie
ausdrücklich als „später", und das ist richtig: die Ebene dafür ist nicht
der Plan, sondern eine zweite Dimension am Fenster (`wochentage` als
Bitmaske oder eine Zuordnungstabelle). Beides lässt sich **additiv**
nachrüsten, wenn die erste Stufe steht und man gesehen hat, wie der
Betreiber sie benutzt. Jetzt mitzubauen heißt, eine Oberfläche für einen
Fall zu entwerfen, den noch niemand bedient hat (§0 S6).

**Einen Plan je Saison.** `rule_config` hat `season_id`, und es wäre
naheliegend, das mitzunehmen. Es wäre auch eine dritte Dimension in einer
Oberfläche, die noch keine erste hat. Später, wenn der Bedarf sichtbar
ist.
