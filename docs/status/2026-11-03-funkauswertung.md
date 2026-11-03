## Funkauswertung am Endplatz: das ADR-Plugin bleibt liegen (2026-11-03)

**Keine Migration.** Kein Code. Drei Dokumente: AE-78 §15, RUNBOOK §10au
(Ergebnis und eine Korrektur), §10av (Kopf).

### Die Messung

109 stand seit **02.11.2026 etwa 07:05** am Endplatz in der Dose am
Eingang — nur Zuleitung, kein Panel, zurückgenommen. Ausgewertet am
03.11. nach §10au, mit `scripts.funkqualitaet` und den ChirpStack-Metriken.

| Gerät | empf. / erw. | Verlust | Rücksetzungen |
|---|---|---|---|
| **109** (Relais, Endplatz) | **137 / 140** | **2,1 %** | **0** |
| Vickis, Bereich über alle | | 0 bis 1,4 % | |
| 099, bei RSSI −115/−116 dBm | | 0 % | |
| 095, bei RSSI −115/−116 dBm | | 0,7 % | |

**Entscheidung des Betreibers: das ADR-Plugin wird nicht ausgerollt.** Es
bleibt vorbereitet (§10av), die zwei Zeilen, die es aktiv machen würden,
sind weiter nicht gesetzt. Ein Plugin, das die Datenrate auf DR3 senkt
und jeden Uplink zweimal sendet, behebt 2,1 % nicht — es tauscht sie
gegen die mehrfache Sendezeit und gegen einen Neustart von ChirpStack, an
dem rund hundert Vickis hängen.

**Für die Rotation am 04.11. heißt das: kein Plugin-Schritt.** Die
Laufliste §10aw hatte nie einen; der Einbau hing an §10av und an dieser
Messung. Die Antwort steht dort jetzt trotzdem, weil am 02.11. „Mittwoch,
falls die Messung es verlangt" im Raum stand — und wer am Morgen danach
sucht, soll eine Entscheidung finden und keine Lücke.

### Die Entscheidungstabelle war falsch, und das ist der Befund dieses Eintrags

§10au Schritt 3, Zeile 1, lautete: „Verlust **unter 5 %** **und** RSSI
besser als **−105 dBm** → nichts tun". Beides zusammen.

**Die zweite Hälfte widerlegt das eigene Haus.** 099 und 095 stehen bei
−115 bis −116 dBm und verlieren 0 % und 0,7 %. Der Pegel allein sagt
nichts über den Verlust; es sagt ihn erst der Abstand zur
Empfindlichkeitsgrenze des Spreizfaktors, und die liegt bei SF7 und BW 125
laut Datenblatt bei etwa −123 dBm.

**Für 109 gibt es die Zahl nicht einmal.** `relay_reading` führt weder
`rssi_dbm` noch `snr_db` — das steht in
`docs/status/2026-11-02-paketverlust.md` ausdrücklich als bekannte Lücke.
Die Tabelle hätte für die tatsächlich gemessene Lage also **keine** Zeile
getroffen: zu gut für Zeile 2 und 3, und Zeile 1 nicht belegbar.

Korrigiert ist sie auf einen Satz: **der Verlust entscheidet, der Pegel
erklärt.** Das ist §5.77 in einer Entscheidungstabelle — eine Schwelle,
die niemand nachgerechnet hat, liest sich unter Druck wie ein Befund. Sie
stammt von mir, vom 02.11., aus demselben PR, der das Werkzeug gebaut hat.

### Die Hypothese zum 01.11., mit dem, was sie nicht hergibt

Am 01.11. ergab die Rechnung von Hand **rund 30 %** an 109. Im selben
Zeitfenster (11:22 bis 11:28) ging **jede Minute** ein Downlink an
dasselbe Gerät, sieben Stück, jeder 1,32 s Sendezeit bei SF12 über RX2
(`docs/status/2026-11-02-waechter-backoff.md`).

| | reicht das für 30 %? |
|---|---|
| Gateway halbduplex: neun Sekunden Sendezeit in sieben Minuten | **nein** — rund 2 % des Fensters |
| der Neustart in der Reihe vom 01.11. (`fCnt` 8, Neustart, dann 13); am 02./03.11. **keiner** | **ja** — in einer Reihe von einem Dutzend Werten dominiert dieses Loch |

**Die Hypothese lautet deshalb nicht „Funkloch behoben", sondern: die
30 % waren kein Zustand der Funkstrecke, sondern einer, in dem Steuerung
und Gerät gegeneinander gearbeitet haben.**

**Zwei Dinge, die ich nicht behaupte:**

**Die Messung trennt die Ursachen nicht.** Zwischen 01.11. und 02.11.
haben sich **zwei** Dinge geändert — die Position und die Bremse am
Wächter. Welcher Anteil wem gehört, ist aus diesen Zahlen nicht zu
beantworten.

**Die beiden Zahlen sind nicht gleich belastbar.** 30 % stammen aus vier
fehlenden Frames in einer von Hand gelesenen Reihe, 2,1 % aus 140
erwarteten über einen Tag. Die erste Zahl hat den Bedarf nach einem
Plugin begründet; sie hätte dafür nie gereicht.

### Keine Mutationsprobe, und warum das hier keine Ausrede ist

**Es gibt keinen Test, der fallen könnte.** Über `docs/RUNBOOK.md` und
`docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md` läuft keine Prüfung — nicht auf
Abschnittsnummern, nicht auf Querverweise, nicht auf Inhalt. Der
Handbuch-Spiegel prüft nur `frontend/content/handbuch`, und das Handbuch
ist hier nicht betroffen: nichts am Verhalten und nichts an der
Oberfläche hat sich geändert.

**Was stattdessen geprüft wurde**, weil es die Prüfung ist, die zu dieser
Änderung gehört: eine Suche über alle Dokumente nach Stellen, die die
Entscheidung noch als offen oder als anstehend führen. Gefunden und
nachgezogen sind §10au (Kopf, Schritt 3, der DR-Absatz), §10av (Titel und
Kopf) und §10aw (eigener Abschnitt). Der Eintrag vom 02.11.
(`2026-11-02-adr-plugin.md`) bleibt unverändert — er beschreibt richtig,
was am 02.11. gebaut wurde, und sein Titel sagt „vorbereitet, nicht
ausgerollt".

**Die Lücke bleibt benannt:** dass die Abschnittsnummern `§10…` rund 400
mal außerhalb des RUNBOOKs als reiner Text stehen (gezählt am 03.11.) und
nichts davon geprüft wird, ist derselbe Befund wie beim Vorschlag zu den
RUNBOOK-Kollisionen. Ein Test gegen doppelte Abschnittsnummern wäre der
erste, der hier überhaupt etwas finden könnte.

### Querverweise

AE-78 §15 (die ausführliche Fassung), AE-78 §14 und
`docs/status/2026-11-02-waechter-backoff.md` (die Bremse am Wächter),
`docs/status/2026-11-02-paketverlust.md` (woher die Zahlen kommen, und
was wir für Relais nicht speichern),
`docs/status/2026-11-02-adr-plugin.md` (was vorbereitet ist), RUNBOOK
§10au, §10av, §10aw.
