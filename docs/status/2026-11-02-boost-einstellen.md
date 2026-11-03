## „Boost" als vierte Zeile unter Globale Temperaturen (2026-11-02)

**Keine Migration.** Ein Feld in zwei Schemata, eine Zeile in der
Oberfläche, der Seed-Wert für eine frische Datenbank.

### Und zuerst: das war nie ein offener Punkt

In AE-83 §9 stand, der Boost-Wert sei „nirgends in der Oberfläche
einstellbar", das sei der stärkste offene Punkt, und gebaut sei es nicht,
**„weil niemand es verlangt hat (S6)"**.

**Der letzte Halbsatz war falsch.** Der Betreiber hat es am 31.10.2026
verlangt — „die Boost-Temperatur soll in den globalen
Temperatur-Einstellungen änderbar sein" — und das stand in der
ursprünglichen Vorgabe, nicht in einem Wunsch danach. Ich habe es beim
Bauen übersehen und es dann als **offenen Punkt mit Begründung**
eingetragen.

Das ist die unangenehmere Hälfte dieses Fehlers: eine vergessene Vorgabe,
die als bewusste Entscheidung aussieht, wird nicht mehr nachgefragt. Eine
Lücke fällt auf; eine Lücke mit Begründung nicht.

### Was gebaut ist

**„Boost" ist die vierte Zeile** unter Einstellungen → Temperaturen &
Zeiten → Globale Temperaturen, in derselben Darstellung wie die drei
darüber: Inline-Bearbeitung, Speichern beim Verlassen des Feldes,
Protokoll je geändertem Feld.

| | |
|---|---|
| **Bereich** | 18–25 °C, in **Zod und in Pydantic** |
| **unten 18** | ein Boost unter dem Belegt-Sollwert hat keinen Sinn |
| **oben 25** | der Höchstwert der Gerätegrenzen im Haus (Zimmer 15–25, Bad 18–25). Darüber wäre eine Zahl, die Layer 5 ohnehin kappt |
| **Hinweistext** | „Zieltemperatur für Boost; endet mit der nächsten Nachtabsenkung" |
| **Rollen** | ändern nur Administratoren (`PATCH /rule-configs/global` ist `require_admin`), lesen alle Angemeldeten — wie bei den drei Zeilen darüber |
| **Decimal** | als **String** über die Schnittstelle. Eine Dezimalzahl durch ein JSON-Float gibt 24,499999 zurück |
| **Handbuch** | die vierte Zeile in `seite-temperaturen-zeiten` (plus der Satz, warum dort keine Nutzungszahl steht), und in `seite-zimmeruebersicht` der Verweis, **wo** der Wert liegt — dort stand bisher nur „kommt aus den Einstellungen des Hauses" |

Dazu der **Seed**: eine frische Datenbank bekommt 23,0 mit der hausweiten
Zeile. Migration `0037` setzt den Wert in bestehenden; ohne den Seed
hinge eine Neuinstallation an der Migration, und das ist eine Reihenfolge,
auf die man sich nicht verlassen sollte.

### Ohne die Nutzungszahl, und das mit Absicht

Die anderen Felder dieser Seite tragen im Hinweis eine Zahl: „wie viele
Raumtypen nehmen diesen Wert". Sie kommt aus
`raumtyp_regel.hausstandard_nutzung` und zählt je Feld gegen eine Spalte
auf `room_type` — für `boost_temperature` gibt es die nicht.

`hinweis()` gibt bei einem unbekannten Feld den Grundtext zurück, die
Zeile sieht also vollständig aus. **Eine erfundene Zahl wäre schlimmer
als keine**, und eine echte bräuchte eine `room_type`-Spalte, also eine
Migration für eine Beschriftung (§5.45 ist dieselbe Abwägung).

### Tests

| | |
|---|---|
| Bereich 18–25, **beide Grenzen knapp daneben** (17,9 / 18,0 / 25,0 / 25,1) | Pydantic |
| `Decimal` bleibt `Decimal` (23,5 schreiben, 23,5 lesen) | Pydantic |
| ein Audit-Eintrag je Änderung, mit altem und neuem Wert | Pydantic |
| sieben Felder in der Leseantwort statt sechs | Pydantic |
| die Zeile steht **als vierte** da (Reihenfolge der `aria-label`) | Playwright |
| Bereich greift schon im Browser, beide Grenzen | Playwright |
| Administrator ändert, der Rumpf trägt einen **String** | Playwright |
| Mitarbeiter sieht den Wert, kann ihn nicht öffnen | Playwright |

**Die Reihenfolge wird geprüft**, weil die Festlegung „vierte Zeile"
lautet. Ein Wert, der zwischen „Zimmer frei" und „Nachtabsenkung"
rutscht, ist nicht falsch — aber nicht das, was abgesprochen war, und
ohne Prüfung fällt es niemandem auf.
