---
datum: 2026-11-14
thema: Der Melder der Relais-Zone hört jetzt auf beide Geräte
pr: offen
---

# Die andere Hälfte derselben Zone

Punkt **2** des Auftrags vom 14.11.2026: *„Melder erweitern (#403): Zone
mit in Betrieb genommenem Relais → Warnung, wenn Fühler ODER Relais > 30
min ohne Meldung. Eine Kachel, eine Mail je Episode, Text nennt das
schweigende Gerät. Kein eigener Melder."*

**Kein Steuerpfad** — es entstehen nur eine Kachelzahl, ein Audit-Eintrag
und eine Mail. Der Vorschlag kam aus der Arbeit an #409 („Es gibt keinen
Melder für ein dauerhaft stummes Relais") und ist damit erledigt.

## Was fehlte

#403 hat den **Fühler** einer Relais-Zone beobachtet. Das Relais selbst
blieb ungemessen — und es ist die andere Hälfte derselben Zone.

**Warum es zählt.** Hört die Zustandsmeldung des Relais auf, weiß
niemand mehr, ob das Panel heizt. Seit #409 fällt der Wächter dann auf
die Zustandsabfrage zurück und fragt alle 25 Minuten nach; mehr kann er
nicht tun. Bleibt die Antwort aus, ist der Zustand auf Dauer unbekannt —
ein 1600-W-Panel, von dem wir nicht wissen, ob es an ist. Genau dafür
hat dieses Haus einen Wächter.

**Und es war sichtbar nirgends.** Die Kachel „Geräte online" zählt das
Relais mit, aber `health_state = silent` verlangt mehr als 24 Stunden
(AE-53). Zwischen 30 Minuten und einem Tag stand nichts — dieselbe
Lücke, die #403 für den Fühler geschlossen hat.

## Die Entscheidung dahinter: ein Melder, nicht zwei

Beide Gerätearten gehören derselben Zone, und die Folge ist dieselbe:
die Zone wird nicht verlässlich geregelt. Zwei Melder hätten zwei
Episoden, zwei Mails und zwei Kacheln für einen Vorgang — und beim ersten
gleichzeitigen Ausfall (Gateway, Netz, Strom) beide zugleich. Wer zwei
Mails für eine Sache bekommt, liest bald keine mehr (§5.79).

Der Text nennt deshalb, **wer** schweigt, statt dass zwei Mails es
getrennt sagen.

**Dieselbe Grenze für beide**, 30 Minuten. Die Meldeintervalle sind
verschieden (Vicki eine Stunde Keepalive, Relais zehn Minuten), die
Frage ist dieselbe: hat sich das Gerät in der letzten halben Stunde
gemeldet. Eine zweite Grenze wäre eine zweite Einstellung mit derselben
Begründung (§5.53) — und beim Relais ist 30 Minuten ohnehin strenger,
weil es öfter melden soll.

## Was gebaut ist

**Der Befund trägt jetzt beide Seiten.** `ZonenBefund` bekommt `relais`
(die Etiketten), `relais_letzte_meldung`, `relais_alter_min` und
`relais_stumm`. Dazu eine Eigenschaft `schweigende_geraete` — die Liste,
die in der Mail und im Audit steht.

**`relais_in_betrieb` ist von einem Feld zu einer Eigenschaft geworden**
(`len(self.relais)`). Vorher war es eine eigene Zahl; sobald der Text die
Namen braucht, wären zwei Angaben für dasselbe da, und beim ersten
Fehlgriff stünde „2 in Betrieb" neben einem einzigen Etikett (§5.53).

**Die Rangfolge der Gründe folgt der Folge:**

| Lage | Grund | was die Mail sagt |
|---|---|---|
| kein Fühler zugeordnet | `kein_fuehler` | heizt nie, fehlende Zuordnung |
| Fühler stumm | `stumm` | wird gerade nicht geheizt |
| nur Relais stumm | `relais_stumm` | **Schaltzustand** unbekannt, Regelung läuft |

`relais_stumm` wird in **jedem** Fall mitgeführt, auch wenn schon der
Fühler den Grund stellt. Sonst fehlte in der Mail genau die Hälfte, die
einen Gerätefehler von einem Verbindungsausfall unterscheidet.

**Die Folge ist bei den beiden Gerätearten nicht dieselbe**, und deshalb
sind es zwei Texte. Ohne Fühlerwert heizt die Zone **nicht** — gebaut
und beabsichtigt. Schweigt nur das Relais, sind Soll und Ist da und
unbekannt ist allein, ob das Panel schaltet. Beides in einen Satz zu
fassen hieße, einen der Fälle falsch zu beschreiben — und eine Mail, die
„wird nicht geheizt" sagt, wenn vielleicht geheizt wird, ist die Sorte,
der man nach dem zweiten Mal nicht mehr glaubt.

**Gezählt wird „gehört", nicht „geschaltet."** Jede Zeile in
`relay_reading` ist ein Lebenszeichen, auch eine ohne Schaltzustand. Die
Frage „was gilt am Relais" ist eine andere und steht im Wächter — dort
wird sehr wohl auf `relay_on` gefiltert.

## Die Umbenennungen, und warum sie zum Thema gehören

Ein Melder, der beide Geräte misst, und eine Kachel, die „Fühler" heißt,
wären die nächste Stelle, die jemand in einem halben Jahr für einen
Befund liest (§5.77). Deshalb in diesem PR:

| vorher | jetzt |
|---|---|
| Kachel „Fühler Relais-Zone" | **„Relais-Zone stumm"** |
| `services/relais_fuehler.py` | `services/relais_zone_melder.py` |
| `RELAIS_FUEHLER_STUMM_MIN` | `RELAIS_ZONE_STUMM_MIN` |
| `RELAIS_FUEHLER_WIEDERHOLUNG_H` | `RELAIS_ZONE_WIEDERHOLUNG_H` |
| `relais_fuehler_stumme_zonen` (API) | `relais_zonen_stumm` |
| `relais_fuehler_stumm_min` (API) | `relais_zonen_stille_min` |
| Audit `RELAIS_ZONE_FUEHLER_STUMM` | `RELAIS_ZONE_STUMM` |
| Task `heizung.pruefe_relais_fuehler` | `heizung.pruefe_relais_zone` |

**Die beiden Einstellungen sind in keiner `.env` gesetzt** (geprüft), die
Umbenennung ändert also keinen Wert. Die Ausgabe heißt bewusst
`relais_zonen_stille_min` und nicht wie die Einstellung: dort steht die
**Grenze**, hier das **Alter**. Zwei Dinge, zwei Namen.

**Die alten Audit-Namen werden weiter gelesen** (`AUDIT_ALTE_NAMEN`).
Eine Episode, die beim Deploy offen ist, trägt noch die alte Marke; ohne
das hätte der erste Durchlauf danach keine laufende Episode gesehen und
für denselben Vorgang eine zweite Alarm-Mail geschickt. Ein Melder, der
beim Umbenennen seiner eigenen Marken Fehlalarm gibt, ist die Sorte, die
man nach einer Woche überliest.

Entfernbar, sobald keine Episode von vor dem 14.11.2026 mehr offen sein
kann:

```bash
docker exec deploy-db-1 psql -U heizung -d heizung -c "SELECT target_id, action, max(ts) FROM business_audit WHERE action LIKE 'RELAIS_ZONE_FUEHLER_STUMM%' GROUP BY 1, 2 ORDER BY 1;"
```

Steht je Zone als jüngste Marke ein `..._ENDE` (oder gar nichts), sind
die alten Namen toter Code und können weg.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| M1 Relais-Seite gar nicht geprüft | **10 Tests rot** |
| M2 eigene Grenze für das Relais (doppelt so hoch) | **9 Tests rot** |
| M3 Relais schlägt Fühler (Rangfolge gedreht) | **3 Tests rot** |
| M4 `relais_stumm` nur, wenn es auch der Grund ist | **4 Tests rot** |
| M5 der Relais-Block fehlt in der Mail | **2 Tests rot** |
| M6 „nie gehört" zählt beim Relais nicht als stumm | **2 Tests rot** |
| M7 nur Zeilen mit Schaltzustand gelten als Lebenszeichen | **1 Test rot** |
| M8 schweigende Geräte werden nicht gesammelt | **2 Tests rot** |
| M9 das Audit hält die Namen nicht fest | **1 Test rot** |
| M10 die alten Audit-Namen werden nicht mitgelesen | **1 Test rot** |

**M10 war zuerst grün** — die Übergangslesung war ungeprüft, und damit
hätte sie beim ersten Umbau wieder entfernt werden können, ohne dass
etwas rot wird. Zwei Tests nachgezogen: eine Episode unter dem alten
Namen läuft weiter, eine **beendete** unter dem alten Namen wird nicht
wieder aufgenommen.

## Läufe

* Backend **1930 passed, 45 skipped, 1 xfailed**.
* `ruff check`, `ruff format --check` (338 Dateien), `mypy` (160 Dateien) grün.
* `tsc --noEmit` grün.
* e2e `kacheln-gleiche-hoehe` + `sprint-14c-dashboard`: **23 passed**
  (lokal, `API_PROXY_TARGET=http://127.0.0.1:9`, Port 3123).

### Der lokale Rotstand, und diesmal mit Spur

`test_funkempfang::test_lies_funkempfang_zaehlt_nur_das_fenster` war
wieder rot — 6 Meldungen im Zehn-Minuten-Fenster statt 4. **Neu ist die
Spur:** die zwei überzähligen Geräte (ids 48/49) wurden um **08:23:54
und 08:23:57 desselben Laufs** angelegt, also nicht von einer früheren
Sitzung. Beide: `kind = thermostat`, kein Etikett, `dev_eui` ein
16-stelliges uuid4-Hex, `health_state = silent`, je ein `sensor_reading`
im Fenster.

Damit ist es **kein** Altbestand, sondern ein Test der Suite, der zwei
Geräte ohne Aufräumen hinterlässt. Nicht hier gefixt (§0.1 Pflicht-Stop
4, §5.1) — gehört in die offene Aufgabe aus #400, die jetzt eine
brauchbare Spur hat. In CI fällt es nicht auf, weil die Datenbank frisch
ist; das macht es nicht harmloser, sondern schwerer zu finden (§5.55).

## Was dieser PR nicht tut

**Die Kachel verlinkt weiter nichts.** Es gibt keine Ansicht der
Relais-Zonen, auf der sich die Zahl auflösen würde; ein `href` auf die
Zimmerliste würde die Frage „welche Zone" nicht beantworten. Unverändert
gegenüber #403.

**Der Melder sagt nicht, wie lange schon.** Nach `RELAIS_ZONE_WIEDERHOLUNG_H`
(6 h) kommt dieselbe Mail erneut, aber sie zählt die Episode nicht mit.
Für ein Relais, das seit zwei Tagen schweigt, liest sich die zweite Mail
wie die erste.

**Kein Melder für die Zustandsabfrage selbst.** Dass der Wächter seit
#409 alle 25 Minuten nach dem Zustand fragt und nie eine Antwort
bekommt, steht nur im Protokoll. Diese Mail deckt den Fall ab, weil ein
Relais, das nicht antwortet, auch nicht meldet — aber die beiden Dinge
sind nicht dasselbe, und bei einem Relais, das meldet und auf `0xB1`
nicht antwortet, schweigt dieser Melder.
