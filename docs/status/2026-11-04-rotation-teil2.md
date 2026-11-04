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
| **C4** — `gateway-ug65` entfernen | **entfernt und zurückgenommen** — mit der Störung aus Befund 2 |
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

**Was das unterscheidet, ist eine einzige Zahl:** die Startzeit des
Bridge-Containers. Liegt sie beim Neustart, hat der Container neu
gestartet und die Kette oben stimmt. Liegt sie beim letzten Deploy, lief
die Bridge durch — dann liegt es nicht an ihr, und die Suche geht zur
WebSocket-Strecke durch Caddy.

**Was auf unserer Seite konfigurierbar ist — und was nicht.** Auf der
Serverseite gibt es **keinen** Schalter, der das Gateway zurückholt:
`ping_interval` und `read_timeout` der Bridge regeln nur, wie schnell die
**Bridge** eine tote Sitzung bemerkt, nicht, ob das **Gateway** neu
verbindet. Der Reconnect ist Sache der Basic-Station-Implementierung im
UG65. Bis das geklärt ist, gilt die Regel aus §10ab: nach jedem
Mosquitto- oder Caddy-Neustart den Gateway-Status in ChirpStack ansehen,
Uplinks zählen, und das Gateway notfalls stromlos machen.

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

**Das ist nicht bewiesen.** Es hängt an einer Angabe, die niemand
nachgesehen hat: dem Benutzernamen in den abgewiesenen Anmeldungen. Steht
dort `gateway-ug65`, ist die Sache erklärt. Steht dort etwas anderes,
klopft wirklich etwas Fremdes, und das ist eine andere Frage.

**Deshalb wird nichts geschlossen, bevor das gelesen ist.** Ein intern
gebundener Port ist richtig — aber wenn die Compose-Begründung stimmt und
nicht der Befund vom 20.10., dann schneidet er das Gateway ab und die
Heizung steht. Die Freigabe des Betreibers liegt vor, die Prüfung davor
ist noch offen.

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
| **Befund 4** | Benutzername in den abgewiesenen Anmeldungen lesen, dann entscheiden |
| **Befund 2** | Startzeit des Bridge-Containers lesen, dann weitersuchen |
| **danach** | Relais 109 Taster-Test und Panel, Relais 108, T2-Fenstertest, Paket 3 |

**Eine Lücke, die dieser Termin nicht geschlossen hat.** Zwei von sieben
Blöcken haben den Betrieb gestört, und in beiden Fällen stand die Ursache
vorher im Repo: die Dollarzeichen-Falle in C3, der Widerspruch über Port
1883 in der Compose-Datei. Gelesen wurde beides erst, als es weh tat. Das
ist kein Argument für mehr Prosa, sondern dafür, dass Prüfungen auf **die
Stelle** sehen müssen, die der nächste Befehl benutzt.
