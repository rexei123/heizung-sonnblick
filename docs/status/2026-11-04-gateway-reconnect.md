# Das Gateway kommt nach einem Neustart nicht von selbst zurück

**Stand:** 04.11.2026

Befund 2 aus der Rotation vom 04.11. (`2026-11-04-rotation-teil2.md`).
Jetzt als Regel in §10ay, mit dem, was an Ursache feststeht, und dem
einen Messwert, der die offene Frage entscheidet.

## Der Vorfall

Im Rahmen von §10ab C4 wurde `mosquitto` um 07:12 neu erzeugt. Die
MQTT-Clients verbanden sich neu — Bridge, ChirpStack-Gateway,
Integration, `heizung-api`-Subscriber. Trotzdem kam **kein einziger
Uplink** mehr. Das Gateway stand ab 07:11:45 offline und kam erst nach
**Stromtrennung** um 07:48 zurück: 36 Minuten ohne Messwerte.

**Der Satz, der die Regel trägt:** dass alle MQTT-Clients im Protokoll
wieder auftauchen, sagt über das Gateway **nichts**. Die Clients sind
nicht das Gateway, und genau diese Verwechslung hat 36 Minuten gekostet —
es sah nach Erholung aus.

## Was feststeht

**Der Caddy-Crashloop desselben Morgens ist nicht die Ursache.** Er lief
06:59–07:04; das Gateway meldete sich **danach noch bis 07:11:45**. Es hat
den Caddy-Ausfall überlebt — was gleichzeitig beweist, dass es sich nach
einer Unterbrechung grundsätzlich wieder melden **kann**. Dieser Befund
macht den Fall interessanter, nicht klarer.

**„Offline ab 07:11:45" ist kein Ausfallzeitpunkt.** Die Bridge schickt
Gateway-Statistik alle 30 Sekunden; die Zeit ist der **letzte
durchgekommene Statistiksatz** und damit vereinbar mit dem Neustart
Sekunden später. Wer sie als Ausfallzeit liest, sucht 15 Sekunden zu früh.

**Serverseitig gibt es keinen Schalter, der das Gateway zurückholt.**
`ping_interval` und `read_timeout` der Bridge regeln, wie schnell die
**Bridge** eine tote Sitzung bemerkt. Ob das **Gateway** neu verbindet,
entscheidet dessen eigene Basic-Station-Implementierung. Die Frage „ist
der Reconnect einstellbar?" gehört an die UG65-Oberfläche und ist offen.

## Die Hypothese und der Messwert, der sie entscheidet

Die Bridge ist der **WebSocket-Server**, das Gateway der Client. Verliert
die Bridge ihre MQTT-Verbindung und **startet ihr Container neu**
(`restart: always`), fallen alle Basic-Station-Sitzungen weg — und das
Gateway müsste von sich aus neu verbinden. Ein reiner MQTT-Reconnect
**ohne** Neustart würde die Sitzungen nicht anfassen.

Das entscheidet eine einzige Zahl, und sie ist noch nicht gelesen:
`RestartCount` und `StartedAt` des Bridge-Containers. Der Befehl steht in
§10ay und liest beides für vier Container auf einmal.

| Bridge | heißt |
|---|---|
| Neustarts > 0, gestartet beim Mosquitto-Neustart | die Kette stimmt, und Schritt 2 der Regel ist die Behebung |
| Neustarts = 0, gestartet beim letzten Deploy | nicht die Bridge — weiter zur WebSocket-Strecke durch Caddy |

## Was nicht behauptet wird

Dass der entfernte Mosquitto-User etwas damit zu tun hatte, ist **nicht**
erwiesen; der Neustart allein erklärt den Ausfall ebenso gut. Und ein
einzelner Vorfall sagt nicht, ob das Gateway **immer** so reagiert.
Deshalb ist §10ay eine **Prüfung** und keine Diagnose: sie schreibt vor,
hinzusehen, nicht, was man finden wird.
