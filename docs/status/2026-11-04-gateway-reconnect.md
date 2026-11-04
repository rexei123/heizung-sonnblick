# Das Gateway kommt nach einem Neustart nicht von selbst zurück

**Stand:** 04.11.2026

Befund 2 aus der Rotation vom 04.11. (`2026-11-04-rotation-teil2.md`).
Jetzt als Regel in §10ay — mit dem, was feststeht, und mit der einen
Hypothese, die beim Lesen der Containerzeiten gefallen ist.

## Der Vorfall

Ortszeit; der Server rechnet in UTC (+1 h).

| Zeit | was |
|---|---|
| 06:59–07:04 | Caddy-Crashloop (§10ab C3) |
| 07:11:45 | letzter Statistiksatz des Gateways |
| 07:12 | `mosquitto` neu erzeugt (§10ab C4), danach **kein Uplink mehr** |
| 07:39:59 | `chirpstack` **und** `chirpstack-gateway-bridge` laufen frisch |
| 07:48 | **Stromtrennung am Gateway** — danach kommt es zurück |

36 Minuten ohne Messwerte. Die MQTT-Clients verbanden sich dabei die
ganze Zeit brav neu — Bridge, ChirpStack-Gateway, Integration,
`heizung-api`-Subscriber.

**Der Satz, der die Regel trägt:** dass alle MQTT-Clients im Protokoll
wieder auftauchen, sagt über das Gateway **nichts**. Die Clients sind
nicht das Gateway, und genau diese Verwechslung hat die 36 Minuten
gekostet — es sah nach Erholung aus.

## Die Hypothese ist gefallen

Die erste Fassung von §10ay vermutete: die Bridge ist der
WebSocket-Server, das Gateway der Client; geht der Bridge-Container neu,
fallen alle Basic-Station-Sitzungen weg, und das Gateway muss neu
verbinden — **also wäre ihr Neustart die Behebung.** Entschieden werden
sollte das an `RestartCount` und `StartedAt`.

**Die Zahlen sind gelesen, und sie sagen nein.** Bridge und ChirpStack
liefen ab **07:39:59 frisch**. Das Gateway kam trotzdem erst mit der
Stromtrennung um 07:48. Acht Minuten mit einer frischen Gegenstelle, und
nichts.

Der erste Teil der Kette mag stimmen; der zweite nicht. Das Gateway
**müsste** neu verbinden — es **tut** es nicht. Acht Minuten beweisen
nicht, dass es nie gekommen wäre, aber sie beweisen, dass es nicht in der
Zeit kommt, die im Betrieb zur Verfügung steht.

**Die Behebung ist bis auf Weiteres die Stromtrennung am UG65.**
Serverseitig gibt es keinen Handgriff, der das Gateway zurückholt.

## Was der Messwert nicht mehr hergibt — und warum das meine Schuld ist

Ob die Bridge um 07:12 **von sich aus** mitgegangen ist, lässt sich nicht
mehr feststellen. Das `--force-recreate` um 07:39:59 hat neue Container
erzeugt und damit beide Zahlen zurückgesetzt; sie zeigen den
Rettungsversuch, nicht den Vorfall.

**Der Fehler steckte in der Reihenfolge, die ich vorgeschlagen hatte.**
Der Befehl stand in §10ay unter „Ursache", also hinter der Regel — und
die Regel erzeugt die Container neu. Der Handgriff, der hilft, löscht die
Spur. §10ay liest die Containerzeiten deshalb jetzt in **Schritt 1**, vor
jedem Neustart.

Dringend ist die Frage nicht mehr: die Behebung liegt ohnehin nicht an
dieser Stelle. Beim nächsten Vorfall fällt die Antwort mit Schritt 1 ab.

## Was feststeht

**Der Caddy-Crashloop ist nicht die Ursache.** Er lief 06:59–07:04; das
Gateway meldete sich **danach noch bis 07:11:45** und hat ihn überlebt —
was gleichzeitig beweist, dass es sich nach einer Unterbrechung
grundsätzlich wieder melden **kann**. Dieser Befund macht den Fall
interessanter, nicht klarer.

**„Offline ab 07:11:45" ist kein Ausfallzeitpunkt.** Die Bridge schickt
Gateway-Statistik alle 30 Sekunden; die Zeit ist der **letzte
durchgekommene Statistiksatz** und damit vereinbar mit einem Abriss
Sekunden später. Wer sie als Ausfallzeit liest, sucht 15 Sekunden zu
früh.

**Die offene Frage liegt am Gerät.** Ob der Basic-Station-Reconnect am
UG65 einstellbar ist, entscheidet dessen eigene Implementierung;
`ping_interval` und `read_timeout` der Bridge regeln nur, wie schnell die
**Bridge** eine tote Sitzung bemerkt. §10ay Schritt 4 grenzt die Frage
ein: Caddy protokolliert die `/router*`-Zugriffe des Gateways, und wer
beim Warten mitliest, sieht, ob das Gerät überhaupt klopft. Klopft es
nicht, ist es seine Seite — und Warten ist sinnlos.

## Die Folge, die über das Prüfen hinausgeht

Wer `mosquitto`, `caddy` oder die Bridge neu startet, muss damit rechnen,
**am Gateway stehen zu müssen.** Diese drei Dienste werden deshalb nicht
neu gestartet, solange niemand ans Gerät kommt. Das ist die eigentliche
Änderung am Betrieb — nicht ein zusätzlicher Prüfschritt, sondern eine
Bedingung dafür, wann man diese Neustarts überhaupt anfassen darf.

## Was nicht behauptet wird

Dass der entfernte Mosquitto-User etwas damit zu tun hatte, ist **nicht**
erwiesen; der Neustart allein erklärt den Ausfall ebenso gut. Und ein
einzelner Vorfall sagt nicht, ob das Gateway **immer** so reagiert.
Deshalb ist §10ay eine **Prüfung** und keine Diagnose: sie schreibt vor,
hinzusehen, nicht, was man finden wird.
