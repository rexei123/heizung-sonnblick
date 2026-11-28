# 27.11.2026 — Test-Hygiene: der Aufräum-Helfer hat nie Geräte gelöscht

**Stand:** PR offen, nichts gemergt. Nur Tests und ein Test-Helfer, kein
Produktionscode.

## Der Anlass und der eigentliche Befund

`test_funkempfang.py::test_lies_funkempfang_zaehlt_nur_das_fenster` ist
am 27.11.2026 **zweimal rot** geworden, in einem Durchgang, der die Datei
nicht angefasst hat: erwartet 4, gezählt 6. In CI blieb alles grün — dort
ist die Datenbank frisch.

Der Auftrag lautete, `test_mqtt_subscriber` solle seine Geräte aufräumen.
**Die Messung sagt etwas anderes.** Stand der lokalen Test-Datenbank nach
drei Gesamtläufen:

| Herkunft (DevEUI-Präfix) | Geräte |
|---|---|
| `5e9e5e9e` (`test_sperre_resync`) | 16 |
| `7c107c…`, `5011ab…`, `7acefeed` (`test_soll_je_zone`, `test_t4b_ausloeser`, `test_trace_gesendeter_wert`) | 33 |
| `fwtest00` (`test_mqtt_subscriber`) | 1 |
| **gesamt ohne Etikett** | **50**, davon **49 ohne Heizzone** |

`test_sperre_resync` ruft den gemeinsamen Helfer
`purge_test_data_by_prefix` **korrekt** auf, vorher und nachher, mit
Gerätemuster. Der Helfer hat nicht geliefert.

## Warum er nicht geliefert hat

Sein Docstring behauptete seit Sprint 11:

> `Room` mit `number LIKE f"{prefix}-%"` — CASCADE räumt `HeatingZone`
> und `Device`.

**Die Hälfte davon ist falsch**, und das ist jetzt gemessen statt gelesen:

```
fk_device_heating_zone | device | heating_zone | n
```

`n` ist `ON DELETE SET NULL`. Ein gelöschtes Zimmer nimmt seine Zonen
mit, und die Geräte **verlieren ihre Zuordnung** — sie bleiben stehen,
ohne Zone. Das erklärt die 49 von 50: es sind nicht Geräte, die nie eine
Zone hatten, sondern Geräte, deren Zone weggelöscht wurde.

Der Helfer löschte also die **Messwerte** der Geräte und danach die
Zimmer, im Vertrauen auf einen Cascade, den es nicht gibt. Zwölf Dateien
stehen auf diesem Boden (§5.39).

**Das ist §5.68 in einem Test-Helfer:** eine Aussage über das Schema, die
niemand nachgesehen hat, in einem Docstring, der wie ein Befund gelesen
wird. Drei Monate lang hat sie die Tests, die sie benutzen, langsam
vergiftet — nicht dort, wo sie steht, sondern in einer anderen Datei, die
eine hausweite Zahl abfragt.

## Was gebaut ist

### a) Der Helfer löscht die Geräte selbst

`purge_test_data_by_prefix` löscht jetzt zu einem passenden
`dev_eui_pattern` erst `sensor_reading`, `relay_reading` und
`control_command`, dann **die Geräte**. Der Cascade über `room` bleibt
für Zonen und Zimmer, wo er greift. Der falsche Satz im Docstring ist
ersetzt — mit der gemessenen Zeile als Beleg.

**Eine Zeile Code, zwölf Dateien.** Die Alternative wäre gewesen, in
jeder Datei eigenes SQL nachzutragen; das wäre zwölf Wahrheiten
(§5.53).

### b) Vier Zusicherungen für den Helfer

`backend/tests/test_aufraeumen.py` — ein Test für einen Test-Helfer, und
die Begründung steht im Modul-Docstring: liefert er nicht, merkt es
niemand dort, wo er gerufen wird.

1. **Ein Gerät ohne Zone verschwindet.** Die Zusicherung, die gefehlt hat.
2. Messwerte, Zimmer und Raumtyp gehen mit.
3. **Ein fremdes Gerät bleibt stehen** — die Gegenprobe. Ohne sie wäre ein
   `DELETE FROM device` ohne Muster grün durchgegangen und hätte die
   Nachbarn abgeräumt.
4. **Ohne Muster bleibt das Gerät liegen**, mit `heating_zone_id = NULL`.
   Das hält das echte Schema-Verhalten fest. Wird der Fremdschlüssel
   eines Tages auf `CASCADE` gestellt, fällt dieser Test — und das ist
   die richtige Nachricht, nicht ein Mangel.

### c) `test_funkempfang` prüft den Zuwachs

`lies_funkempfang` beantwortet eine **hausweite** Frage und hat deshalb
bewusst keinen Geräte-Filter; einen für den Test einzubauen wäre ein
Argument, das nur Tests benutzen (§5.53). Der Auftrag nannte einen
`own_ids`-Filter — der ist hier nicht möglich, ohne den Lesepfad zu
verbiegen.

Stattdessen misst der Test den **Zuwachs**: vier neue Meldungen im
Fenster, drei außerhalb, und die drei dürfen den Zuwachs nicht ändern.
Dieselbe Zusicherung, aber abhängig von nichts, was der Test nicht selbst
angelegt hat. Das ist Schicht 2 von §5.39, nur in der Form, die hier
möglich ist.

### d) `test_mqtt_subscriber` räumt auf

Wie beauftragt — und mit dem gemeinsamen Helfer, nicht mit eigenem SQL.
**Ein `rollback` reichte dort nicht**, und der Kommentar an den Tests
behauptete drei Monate lang das Gegenteil („beim Test-Tear-down
weggerollt"). Die Tests schieben dem Code unter Prüfung ihre eigene
Sitzung unter, und `_persist_uplink` ruft darauf `commit()`. Weil der
Kommentar es anders sagte, hat niemand gesucht.

## Zwei Messungen statt Behauptungen

**Das Fehlerbild von heute Morgen, auf Abruf reproduziert.** Ein fremdes
Gerät mit zwei frischen Meldungen in die Test-Datenbank, dann derselbe
Test zweimal:

| Zusicherung | Ergebnis |
|---|---|
| Zuwachs (neu) | **grün** |
| absolut (alt) | **rot** — „4 erwartet, 6 gezählt", wörtlich der Befund vom Morgen |

**Der Reste-Stand nach einem Gesamtlauf**, von null ausgehend gemessen:
**5 Geraete ohne Etikett** statt rund 17 je Lauf. Die fuenf kommen aus
Dateien, die ihre DevEUI vollstaendig aus einem ``uuid4`` bauen
(``test_seed_rooms``, ``test_sprint14e_hygiene_rest`` und vier weitere) --
sie haben kein stabiles Praefix, und ein Muster kann sie deshalb nicht
treffen. Das ist kein Rest dieses PR, sondern der naechste Schritt: diese
Dateien brauchen ein Praefix, dann greift der Helfer auch dort.

## Mutationsproben

| Probe | was rot wird |
|---|---|
| Geräte-Löschung aus dem Helfer entfernt | 2 Tests |
| Geräte **ohne** Musterfilter löschen | die Gegenprobe |
| Zuwachs zurück auf absolut, mit Fremdrest | der Fenster-Test |

**Die zweite Probe hat beim ersten Lauf einen Mangel gefunden** und ist
deshalb hier die lehrreichste: sie blieb **grün**. Die Gegenprobe legte
nur das fremde Gerät an, damit war die Trefferliste leer, der ganze
Muster-Zweig des Helfers wurde übersprungen — ein Test, der seinen
Gegenstand nicht erreicht (§5.55). Der Aufbau legt jetzt **zwei** Geräte
an: eines, das verschwinden muss, und eines, das bleiben muss.

## Was offen bleibt

**Fünf Geräte je Lauf bleiben liegen**, und zwar aus einem anderen Grund:
sechs Dateien bauen ihre DevEUI vollständig aus einem `uuid4` und haben
damit kein stabiles Präfix, auf das ein Muster passen könnte
(`test_seed_rooms`, `test_sprint14e_hygiene_rest`, `test_assign`,
`test_device_adapter`, `test_fcnt_reboot_drift`, `test_pair_devices_cli`).
Der richtige Schritt dort ist ein Präfix, nicht ein weiterer Helfer —
**nicht in diesem PR**, weil es sechs weitere Dateien anfasst und nicht
beauftragt war. Der `funkempfang`-Test ist durch die
Zuwachs-Zusicherung ohnehin unabhängig davon geworden.

**Dateien ohne Gerätemuster räumen weiter keine Geräte auf.** Der Helfer
kann nur löschen, was ein Aufrufer ihm nennt. Test 4 hält genau das fest,
damit es nicht wieder für einen Cascade gehalten wird.

**Ein Wächter gegen Reste gibt es nicht.** Ein Test „nach dem Lauf steht
nichts mehr da" wäre von der Ausführungsreihenfolge abhängig und würde
genau dann rot, wenn jemand eine einzelne Datei laufen lässt. Die
Messung oben ist der Ersatz; sie gehört in den Durchgang, nicht in die
Suite.

**Querverweise:** §5.39 (Cleanup-Fixture und own_ids-Filter), §5.68
(Behauptung vs. Befund — hier in einem Docstring), §5.53 (eine Wahrheit),
§5.55 (die grüne Probe), `backend/tests/conftest.py`
(`purge_test_data_by_prefix`).
