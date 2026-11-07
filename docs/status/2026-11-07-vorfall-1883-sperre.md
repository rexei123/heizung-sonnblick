# Vorfall 07.11.2026: die 1883-Sperre hat die Anlage abgeschaltet

**Stand:** 07.11.2026 · **31 Minuten ohne Messwerte** · Ursache: ein
Vorschlag von mir, der auf einer ungeprüften Annahme stand

## Was passiert ist

| Zeit (UTC) | |
|---|---|
| 06:08:49 | Das Gateway verbindet sich noch erfolgreich (`u'gateway-ug65'`) |
| ~06:09 | Die Regel `-i eth0 -p tcp --dport 1883 -j DROP` geht in `DOCKER-USER` |
| 06:09:49 | Die Sitzung des Gateways stirbt: `disconnected: exceeded timeout` |
| **06:21:35** | **letzter Messwert** |
| 06:52:37 | Rücknahme der Regel; das Gateway verbindet sich **von selbst** |
| 06:52:46 | erster Messwert danach |

**31 Minuten 11 Sekunden ohne Messwerte.** Die Steuerung hat in dieser
Zeit weiter gerechnet und acht Befehle erzeugt, die nicht ankamen.

## Die widerlegte Annahme — und wo genau ich falsch lag

PR #385 wollte Mosquitto auf `127.0.0.1` binden. Die Begründung stand auf
der Kette:

> Das Gateway spricht Basic Station gegen die Bridge, und
> `MQTT_GATEWAY_UG65_PASSWORD` existiert in der Server-`.env` nicht mehr
> (§10ab, „B3 entfällt") — es kann sich also nicht erfolgreich anmelden.
> Uplinks kommen trotzdem an, **also nicht über diesen Weg.**

**Jedes Glied davon ist falsch.** Belegt am 07.11.:

```
New client connected from 213.153.54.49:21331 as auto-0FC0BE47-…
    (p4, c1, k30, u'gateway-ug65')
```

Und die Benutzerliste des Brokers:

```
chirpstack
heizung-api
gateway-ug65
```

Die ACL-Datei sagt es sogar ausdrücklich:

```
#   - gateway-ug65  : Milesight UG65 (direkter MQTT-Push im ChirpStack-v4-Modus)
user gateway-ug65
topic write eu868/gateway/+/event/+
```

**Der Fehler in einem Satz:** ich habe aus dem Fehlen einer
Umgebungsvariablen auf den Inhalt der Benutzerdatenbank des Brokers
geschlossen. Das sind zwei verschiedene Dinge. `MQTT_GATEWAY_UG65_PASSWORD`
in der `.env` speist allenfalls die **Erzeugung** des Eintrags in
`/mosquitto/config/passwd`; die Datei ist gemountet und überlebt das
Entfernen der Variablen. Ein Befehl hätte es gezeigt:

```bash
docker exec deploy-mosquitto-1 sh -c 'cut -d: -f1 /mosquitto/config/passwd'
```

Das ist §5.68 im Kern: eine Aussage über den Zustand der Anlage, aus
einer Konfigurationsdatei abgeleitet statt an der Anlage gemessen.

### Und die Ironie, die dazugehört

Der Kommentar in `docker-compose.prod.yml` sagte:

> *„Port 1883 oeffentlich, damit UG65 (ChirpStack-v4-Modus) direkt MQTT
> publishen kann."*

**Er war richtig.** Ich habe ihn in #385 zum Kronzeugen einer
§5.77-Lehre gemacht — „ein Kommentar, der eine Sicherheitsentscheidung
begründet und dessen Begründung nicht mehr stimmt, ist schlimmer als kein
Kommentar". Der überholte Vermerk in diesem Vorgang war **meine
Schlussfolgerung**, nicht der Kommentar. Die Lehre gilt weiter; sie traf
nur die andere Seite.

## Wie die Uplinks tatsächlich laufen

**Über MQTT auf 1883, nicht über Basic Station.** Drei unabhängige
Belege:

| Beleg | |
|---|---|
| Der Ausfall selbst | 1883 gesperrt → **0** Uplinks. Käme die Nutzlast über 443, hätte die Regel sie nicht treffen können |
| `chirpstack-gateway-bridge` | letzte Logzeile ist der Start des Websocket-Listeners am **04.11. 06:40** — seither **keine** Sitzung |
| Caddy `cs-test.access.log` | **2** `router`-Treffer in **39.607** Zeilen |

Basic Station ist also **eingerichtet und unbenutzt**. Der Listener läuft
leer, die Caddy-Route ist da, und das Gerät nimmt sie nicht.

**Das korrigiert auch §10ay.** Dort stand als Voraussetzung, das Gateway
spreche Basic Station gegen die Bridge. Mit dem richtigen Pfad wird der
Vorfall vom 04.11. erst schlüssig: **ein Neustart von `mosquitto` trennt
die MQTT-Sitzung des Gateways**, und das Gateway verbindet sich nicht von
selbst neu. Die 36 Minuten und die Stromtrennung brauchen keine weitere
Erklärung — und der frische Bridge-Container konnte nichts helfen, weil
er am Datenpfad nicht beteiligt ist.

## Ein Fund, der günstig ist: das Gateway puffert

Die Sitzung starb um 06:09:49, der **letzte Messwert** trägt aber die Zeit
**06:21:35**. Das ist kein Widerspruch:
`sensor_reading.time` kommt aus `uplink.time` (`mqtt_subscriber.py:325`),
also vom Gateway — nicht vom Schreibzeitpunkt.

**Das Gerät hat die Uplinks aus den ersten ~12 Minuten gepuffert und bei
der Rückverbindung mit ihren Originalzeiten nachgeliefert.** Danach war
der Puffer erschöpft; alles von 06:21:35 bis 06:52:46 ist **endgültig
verloren**.

Zur Einordnung: der Ausfall dauerte **44 Minuten** (06:08:49–06:52:37),
der Datenverlust **31**. Das Gerät hat ein Viertel gerettet. Es ist eine
Reserve, kein Schutz — und sie ist nicht gemessen, sondern aus diesem
einen Fall geschätzt.

## Folgen des Ausfalls — geprüft

| Frage | Antwort |
|---|---|
| Geräte als offline markiert? | **Nein.** 103 `healthy`. Die 6 `silent` sind **Altbestand** und kein Zimmer-Thermostat: 100 (ohne Zone), 108 und „109 Panel" (nie gesendet), 105/106/107 (Reserve, zuletzt 04.11.) |
| Alarm-Mail ausgelöst? | **Nein.** Letzter Versand 05.11. 08:25. Richtig so — die Schwelle für `silent` ist 24 h, nicht 31 Minuten |
| Befehle in der Sperrzeit? | **8 an 7 Geräte.** Sieben davon melden heute den befohlenen Wert |
| Der achte? | Gerät **60** (054) wurde um 07:00:21 auf **21,0** gesetzt und meldet **25,0**. Die drei Befehle davor lauteten ebenfalls 21,0 bzw. 19,0 — der Wert 25,0 stammt also **nicht** von uns. Offen, und getrennt anzusehen |
| Abgleich erschöpft? | **Nein**, 0 Fälle heute |
| Belegungs-Import | Letzter angewandter Lauf **06.11. 18:30**. Die Liste von heute 08:30 Ortszeit **lag zum Zeitpunkt dieser Prüfung noch in der Zukunft** (Serverzeit 07:06 UTC = 08:06 Ortszeit) — also **nicht beurteilbar**, nicht „in Ordnung" |

**Der Ausfall hat keinen Alarm ausgelöst**, und das ist kein Trost: eine
halbe Stunde ohne Messwerte liegt unter jeder vorhandenen Schwelle. Wer
die Sperre gesetzt und nicht hingesehen hätte, hätte es nicht erfahren.

## Die Regel, die daraus folgt

Sie steht in RUNBOOK §5.4 und gilt für **jede** Änderung an einer
Firewall, einem Port oder einer Bindung:

**Vorher belegen, nachher messen.**

1. **Vorher**, in den Logs, **welche externen Clients den Port benutzen**
   — nicht ableiten, nicht aus einer `.env` schließen. Für MQTT ist das
   die Benutzerliste des Brokers und die Verbindungszeilen; für HTTP das
   Caddy-Zugriffsprotokoll.
2. **Nachher innerhalb von zwei Minuten** prüfen, ob die Uplinks
   weiterlaufen. Laufen sie nicht: **sofort zurück**, ohne weitere
   Diagnose.

**Warum zwei Minuten und nicht fünf:** die Geräte senden im
10-Minuten-Takt, aber **über 100 Geräte** verteilt — in zwei Minuten
kommen normal rund 20 Meldungen. Bleiben sie aus, ist das schon
eindeutig. Und zwei Minuten sind kurz genug, dass der Gerätepuffer die
Lücke noch deckt.

## Was ich daraus mitnehme

Die Kette in #385 hatte **fünf** Glieder und ich habe jedes einzelne für
belegt ausgegeben. Vier waren Schlüsse aus Dateien im Repo; nur eines
(`$SYS/broker/clients/connected = 5`) war eine Messung an der Anlage —
und die habe ich falsch **gedeutet**, weil ich die fünf Clients
zugeordnet habe, ohne sie zu lesen. Einer davon war das Gateway.

Die Messung, die gefehlt hat, war in jedem Moment verfügbar und kostet
eine Zeile.
