# Rotation Teil 2, 04.11.2026 — gelaufen, mit sechs Befunden

**Stand:** 04.11.2026

Die Laufliste aus §10aw ist abgearbeitet. Vier Blöcke sind erledigt, einer
ausgelassen, einer verschoben, einer ausgeführt und wieder zurückgenommen.
Der Termin hat **zwei Störungen** am laufenden Betrieb erzeugt, und beide
hatten eine Ursache, die vorher im Repo stand und trotzdem nicht gegriffen
hat. Das ist der Teil, der hier mehr Platz bekommt als das Ergebnis.

## Was die Blöcke gemacht haben

| Block | Ergebnis |
|---|---|
| **C1** — SMTP | **ausgelassen.** Das Gmail-App-Passwort „Hotel Heizung" wurde am **20.09.** angelegt, der Screenshot, der den Anlass gab, ist vom **19.09.** — das Passwort im Betrieb ist **jünger als der Anlass** und wurde nie gezeigt. Entscheidung des Betreibers |
| **C2** — `OCCUPANCY_IMPORT_TOKEN` | erledigt, Liste 08:30 übernommen |
| **C3** — `HOTEL_BASIC_AUTH_HASH` | erledigt — **mit der Störung aus Befund 1** |
| **C4** — `gateway-ug65` entfernen | **entfernt und zurückgenommen** — mit der Störung aus Befund 2. **Ab 07.11.: nie wieder ausführen**, der User ist der Datenpfad (§10ab C4) |
| **C5** — ChirpStack-Admin | erledigt. `admin/admin` war **nicht** aktiv |
| **C6** — Server-Neustart | **verschoben** |
| **C7** — alte Backups | erledigt: 20.10., 15.05. und ältere geschreddert; das vom 04.11. bleibt bis 11.11. |

**C1 ist keine offene Aufgabe mehr, sondern eine beantwortete Frage.** Der
Block war dafür geschrieben, ein Passwort zu ersetzen, das auf einem
Bildschirmfoto gelandet war. Das Passwort, das der Server benutzt, gab es
zu diesem Zeitpunkt noch nicht. Damit entfällt der Anlass, nicht nur der
Handgriff.

**C5 hat eine Annahme widerlegt, und das zählt als Ergebnis.** Der Block
rechnete mit einem aktiven `admin/admin`. Es war nicht aktiv. §10ab C5.1
war genau für diesen Fall gebaut — erst prüfen, ob überhaupt ein eigenes
Passwort gesetzt ist — und die Prüfung hat ihren Zweck erfüllt.

## Befund 1 — die Umgebung zerstört den Hash, den die Datei richtig trägt

**Was passiert ist:** `ENV_NEU` lädt die `.env` mit `set -a` und einem
Punkt-Befehl. Der bcrypt-Hash steht dort mit **verdoppelten**
Dollarzeichen, weil Compose die Verdopplung zu einem Zeichen auflöst. Die
Shell löst dieselbe Verdopplung zur **Prozessnummer** auf. Danach trägt
die Sitzung einen zerstückelten Wert, und Compose nimmt die Umgebung
**vor** der Datei. Caddy bekam Zeichenfolge statt Hash und lief von
**06:59 bis 07:04** im Crashloop, Meldung
`base64-decoding password … byte 46`. Auch mit dem alten Wert — der Weg
zurück war genauso kaputt wie der Weg hin.

Gelöst wurde es vor Ort mit `unset` auf die beiden Hash-Variablen, also
damit, die Umgebung **leer** zu machen, damit Compose die Datei liest.

**Das Dokument wusste es und ist trotzdem hineingelaufen.** §10ab C3 warnt
zweimal vor genau diesem Mechanismus — in der Shell ist die Verdopplung
die Prozessnummer — und sagt zwei Zeilen darunter `ENV_NEU`, also das
Sourcen, das ihn auslöst. Beide Sätze sind richtig und stehen in derselben
Spalte. Dass ein Dokument eine Falle beschreibt, heißt nicht, dass es sie
umgeht.

**Und die Prüfung konnte es nicht fangen.** Die Kontrolle vor dem Neustart
war ein `grep` auf die **Datei**. Die Datei war in Ordnung. Kaputt war die
Umgebung, und darauf sah niemand hin. Eine Prüfung, die eine andere Stelle
ansieht als die, die der nächste Befehl benutzt, ist keine Prüfung.

**Folge:** `ENV_NEU` wird ein echtes, geprüftes Skript im Repo statt einer
Zeile zum Kopieren in Prosa, §10ab C3 wird samt Rückweg korrigiert, und
die Prüflisten, die das Laden eigenhändig wiederholen, werden nachgezogen
(Befund 6, dieselbe Ursache, derselbe PR).

## Befund 2 — nach dem Mosquitto-Neustart kam kein Uplink mehr

**Was passiert ist:** Mosquitto-Neustart um **07:12** (im Rahmen von C4).
Die MQTT-Clients verbanden sich neu — Bridge, ChirpStack-Gateway,
Integration, `heizung-api`-Subscriber — und trotzdem **null** `data_up`.
Das Gateway UG65 stand in ChirpStack ab **07:11:45** offline und kam erst
nach **Stromtrennung am Gateway** um **07:48** zurück.

**Die Zeitstempel passen zusammen, und sie zeigen auf den Neustart.** Die
Bridge schickt Gateway-Statistik alle **30 Sekunden**
(`stats_interval`, `infra/chirpstack-gateway-bridge/chirpstack-gateway-bridge.toml`).
„Offline ab 07:11:45" ist deshalb kein Ausfallzeitpunkt, sondern der
**letzte durchgekommene Statistiksatz** — vereinbar mit dem Neustart
Sekunden später.

**Der Caddy-Crashloop ist damit als Ursache unwahrscheinlich, aber nicht
ausgeschlossen.** Er lief 06:59–07:04, das Gateway meldete sich danach
noch bis 07:11:45 — es hat den Caddy-Ausfall also **überlebt**. Das ist
ein Argument gegen Caddy als Auslöser und gleichzeitig der Beweis, dass
das Gateway sich nach einer Unterbrechung grundsätzlich wieder melden
**kann**. Beides zusammen macht den Fall interessanter, nicht klarer.

**Die wahrscheinliche Kette, und sie ist eine Hypothese:** die Bridge ist
der **WebSocket-Server** für Basic Station, das Gateway ist der Client.
Verliert die Bridge ihre MQTT-Verbindung und **startet der Container neu**
(`restart: always`), fallen damit **alle** Basic-Station-Sitzungen weg, und
das Gateway müsste von sich aus neu verbinden. Genau das hat es nicht
getan. Ein reiner MQTT-Reconnect der Bridge **ohne** Neustart würde die
WebSocket-Sitzungen dagegen nicht anfassen.

**Nachtrag vom selben Tag: die Zahl ist gelesen, und die Kette hält
nicht.** Bridge und ChirpStack liefen ab **07:39:59 frisch** — acht
Minuten vor der Stromtrennung, und das Gateway kam trotzdem erst mit dem
Stecker. Eine frische Gegenstelle genügt also nicht. Der erste Teil der
Kette mag stimmen, der zweite nicht: das Gateway **müsste** neu
verbinden, es **tut** es nicht.

Ob die Bridge um 07:12 von sich aus mitgegangen ist, lässt sich nicht
mehr feststellen — das `--force-recreate` um 07:39:59 hat die Container
ersetzt und beide Zahlen zurückgesetzt. Dringend ist es nicht mehr, weil
die Behebung ohnehin nicht dort liegt; §10ay liest die Zeiten jetzt
**vor** dem ersten Neustart.

**Was auf unserer Seite konfigurierbar ist — und was nicht.** Auf der
Serverseite gibt es **keinen** Schalter, der das Gateway zurückholt:
`ping_interval` und `read_timeout` der Bridge regeln nur, wie schnell die
**Bridge** eine tote Sitzung bemerkt, nicht, ob das **Gateway** neu
verbindet. Der Reconnect ist Sache der Basic-Station-Implementierung im
UG65. Bis das geklärt ist, gilt die Regel aus **§10ay**: nach jedem
Mosquitto-, Caddy- oder Bridge-Neustart den Gateway-Status in ChirpStack
ansehen und die Uplinks zählen — und das Gateway **stromlos machen**, denn
das ist bis auf Weiteres die Behebung und nicht die letzte Ausfahrt. Wer
diese drei Dienste neu startet, muss damit rechnen, am Gerät stehen zu
müssen.

## Befund 3 — `docker compose` frisst eingefügte Folgezeilen

Mehrere Zeilen in einem Rutsch in das Terminal eingefügt: der
`docker compose`-Aufruf verschluckt, was dahinter stand. Die Folgezeilen
sind nicht ausgeführt und auch nicht sichtbar liegengeblieben — sie waren
weg. In einer Laufliste, die Blöcke zum Kopieren anbietet, ist das
gefährlicher als ein Fehler, denn es sieht aus wie Erfolg.

## Befund 4 — Port 1883 steht öffentlich, und ein Gerät aus dem Haus klopft

**Was gemessen wurde:** Mosquitto hört auf allen Adressen, IPv4 und IPv6.
Ein Gerät mit der Adresse **213.153.54.49** — dem Internetanschluss des
Hauses — versucht sich **alle paar Sekunden** ohne gültige Anmeldung.
**Schon vor C4**, also nicht durch den Termin verursacht.

**Hier steht eine Behauptung im Repo gegen eine andere, und das muss vor
dem Schließen geklärt werden.** Die Compose-Datei begründet den
öffentlichen Port ausdrücklich damit, dass das UG65 direkt MQTT
veröffentlichen kann (`infra/deploy/docker-compose.prod.yml:55`), und die
ACL führt dafür den User `gateway-ug65`. §10ab und der Befund vom 20.10.
sagen das Gegenteil: das Gateway spricht **Basic Station** gegen die
Bridge, und `MQTT_GATEWAY_UG65_PASSWORD` existiert in der Server-`.env`
**nicht**.

**Beide können gleichzeitig wahr sein, und dann erklärt das den Klopfer.**
Wenn das UG65 sein Packet-Forwarder-Profil aus §10a.2 **noch trägt**, der
Server das zugehörige Passwort aber nicht mehr kennt, dann versucht das
Gateway sich im Sekundenrhythmus anzumelden, scheitert an der Anmeldung —
und die Uplinks laufen daneben über Basic Station. Das wäre **eine**
Ursache für zwei Beobachtungen und macht den „fremden" Klopfer zum eigenen
Gerät.

**Das ist nicht bewiesen, und der naheliegende Beweis geht nicht.** Man
würde den **Benutzernamen** in den abgewiesenen Anmeldungen lesen wollen —
den schreibt Mosquitto aber nicht hin. Bei einer gescheiterten Anmeldung
steht dort die **Client-ID** oder `<unknown>`, und die Adresse nur in der
Verbindungszeile davor; der Benutzername erscheint ausschließlich in der
Zeile einer **erfolgreichen** Anmeldung. Ein Gerät, das immer scheitert,
nennt seinen Benutzernamen dem Protokoll also nie.

**Was stattdessen trägt, ist der Blick auf das Gerät.** In der
UG65-Oberfläche steht unter Packet Forwarder, ob das Profil aus §10a.2
noch aktiv ist und auf welchen Benutzernamen es zeigt. Das ist eine
direkte Ablesung und braucht keine Protokoll-Forensik. Zweitbeste Quelle:
die **Client-ID** in der `not authorised`-Zeile, zusammen mit der
`New connection from 213.153.54.49`-Zeile unmittelbar davor — die beiden
gehören zusammen und sagen zumindest, *welches* Gerät klopft.

**Deshalb wird nichts geschlossen, bevor das gelesen ist.** Ein intern
gebundener Port ist richtig — aber wenn die Compose-Begründung stimmt und
nicht der Befund vom 20.10., dann schneidet er das Gateway ab und die
Heizung steht. Die Freigabe des Betreibers liegt vor, die Prüfung davor
ist noch offen.

> ## Aufgelöst am 07.11.2026 — die Compose-Begründung stimmte
>
> **Das UG65 publiziert per MQTT auf 1883 als `gateway-ug65`.** Der
> Befund vom 20.10. war falsch; der Kommentar in der Compose-Datei war
> richtig. Basic Station ist eingerichtet und unbenutzt: die Bridge hat
> seit dem 04.11. keine Sitzung, Caddy zählt 2 `router`-Treffer in
> 39.607 Zeilen.
>
> **Und die Prüfung, die dieser Absatz verlangt hat, ist nicht gemacht
> worden.** Am 06.11. habe ich eine Firewall-Regel auf 1883 empfohlen,
> ohne sie durchzuführen — die Anlage stand **31 Minuten**. Befund 5
> unten nennt den richtigen Befehl und die richtige Begründung, drei Tage
> vor dem Ausfall, in diesem Dokument.
>
> Das ist der teuerste Teil daran: das Wissen war da, aufgeschrieben, von
> mir. Eine Lehre, die man notiert und beim nächsten Vorschlag nicht
> anwendet, hat denselben Wert wie keine. Einzelheiten:
> `docs/status/2026-11-07-vorfall-1883-sperre.md`, Regel in RUNBOOK
> §5.0a.

## Befund 5 — „sieben Tage keine Anmeldung" beweist bei Dauerverbindungen nichts

C4 stützte sich darauf, dass sich sieben Tage lang niemand als
`gateway-ug65` angemeldet hat. Bei MQTT-Clients, die **dauerhaft**
verbunden bleiben, steht die Anmeldung einmal am Anfang im Protokoll und
danach nie wieder. Ein Client, der seit drei Wochen hängt, erzeugt
dieselbe Protokollstille wie einer, den es nicht gibt. Die Prüfung muss
auf **offene Verbindungen** sehen, nicht auf Protokollgeschichte.

Und selbst das beweist nur eine Richtung: eine offene Verbindung zeigt
Benutzung, ihr Fehlen zeigt keine Unbenutztheit. Ein Gerät, das alle paar
Sekunden erfolglos klopft (Befund 4), hat **keine** offene Verbindung und
**keine** erfolgreiche Anmeldung — und braucht den User trotzdem.

## Befund 6 — die Prüflisten wiederholen den Fehler aus Befund 1

Mehrere Prüfbefehle laden die `.env` selbst, statt den Helfer zu benutzen.
Dieselbe Ursache wie Befund 1, deshalb derselbe PR.

## Was offen bleibt

| | |
|---|---|
| **C6** | Server-Neustart, verschoben — neuer Termin offen |
| **Befund 4** | UG65-Oberfläche: trägt das Gerät das Packet-Forwarder-Profil aus §10a.2 noch? Dann entscheiden |
| **Befund 2** | UG65-Oberfläche: ist der Basic-Station-Reconnect einstellbar? Die Bridge ist es nicht gewesen |
| **danach** | Relais 109 Taster-Test und Panel, Relais 108, T2-Fenstertest, Paket 3 |

**Eine Lücke, die dieser Termin nicht geschlossen hat.** Zwei von sieben
Blöcken haben den Betrieb gestört, und in beiden Fällen stand die Ursache
vorher im Repo: die Dollarzeichen-Falle in C3, der Widerspruch über Port
1883 in der Compose-Datei. Gelesen wurde beides erst, als es weh tat. Das
ist kein Argument für mehr Prosa, sondern dafür, dass Prüfungen auf **die
Stelle** sehen müssen, die der nächste Befehl benutzt.
