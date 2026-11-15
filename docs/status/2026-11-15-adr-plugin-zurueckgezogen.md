---
datum: 2026-11-15
thema: ADR-Plugin zurückgezogen — sieben Minuten Ausfall beim Rollout von #406
pr: offen
---

# 54 grüne Tests, und der Dienst startete nicht

## Was passiert ist

Der Rollout von #406 lief nach Laufliste §10av. Schritt 1 war in Ordnung
(HEAD `0aeed7e`, `installation_margin = 20.0`, Kopierzeile vorhanden).
Beim Neustart von ChirpStack in Schritt 2a brach der Dienst ab:

```
Setting up ADR plugin file_path=/etc/chirpstack/adr-plugins/relais-feste-datenrate.js
Error: Get id function: JS error: Error converting from js 'undefined' into type 'function'
```

Danach lief er in Schleife (`Restarting (1)`). **Von 08:53 bis 09:00 hat
die Anlage nichts verarbeitet** — keine Uplinks, keine Downlinks, kein
Regler-Eingriff. Nach der Notreparatur: 34 Messwerte von 34 Geräten in
fünf Minuten, jüngste 09:02:42.

Schritt 3 (Profil in ChirpStack zuweisen) war nicht erreicht — die
Oberfläche war während der Schleife nicht erreichbar. Das hat einen
zweiten Fehler verhindert: ein Geräteprofil, das auf ein nicht geladenes
Plugin zeigt, läuft bei jedem Uplink des Relais in einen Fehler.

## Die Notreparatur

Der `adr_plugins`-Eintrag wurde in der **gerenderten** `chirpstack.toml`
im Volume `deploy_chirpstack_config_rendered` geleert (Sicherung daneben
als `chirpstack.toml.vor-notfix`), danach nur `chirpstack` mit
`--force-recreate --no-deps` neu erstellt. Mosquitto und das Gateway
blieben unberührt.

**Sie hält nicht.** `deploy-pull.sh` ruft in Phase 3 bei **jedem**
Timer-Lauf `docker compose up -d` über alle Dienste; `chirpstack-init`
ist ein einmaliger Sidecar mit `restart: "no"` und wird dabei erneut
gestartet, rendert die TOML neu und bringt den Eintrag zurück.
`chirpstack` selbst wird nicht neu erstellt (unveränderte
Compose-Konfiguration) und läuft mit der Konfiguration weiter, die es
beim Start gelesen hat — die Reparatur hält also in der **Wirkung**,
während die Datei wieder falsch ist.

Das ist eine Mine: der nächste Neustart aus beliebigem Grund — der
Server-Neustart am Mittwoch nach §10aw, ein Crash, ein
`--force-recreate` — fährt wieder in die Schleife. Deshalb dieser PR.

## Was dieser PR tut

* `adr_plugins` ist aus `infra/chirpstack/configuration/chirpstack.toml`
  **heraus**. An seiner Stelle steht, warum.
* `installation_margin = 20.0` in `region_eu868.toml` bleibt
  **unverändert**. Sie ist eine Zahl in der Regionsdatei, lädt keinen
  Code und war an dem Ausfall nicht beteiligt — und sie löst die Hälfte
  des Problems, die die Vickis betrifft.
* Die Plugin-Datei bleibt im Repo, die Kopierzeile im Init-Sidecar
  bleibt. Ohne den Eintrag sind beide wirkungslos: die Datei liegt im
  Container, und niemand lädt sie. Der zweite Versuch braucht sie.
* `test_die_datei_steht_in_der_plugin_liste` ist **umgedreht** zu
  `test_die_datei_ist_nicht_verdrahtet`. Der Test war der Wachposten
  dafür, dass der Eintrag **da** ist; jetzt ist er der Wachposten dagegen.

## Warum 54 grüne Tests das nicht gefunden haben

Das ist der eigentliche Befund, und er ist noch nicht abgeschlossen.

Die Tests in `infra/chirpstack/tests/test_adr_plugins.py` laden die Datei
mit **Node** und rufen `handle(...)` auf. Sie prüfen damit, ob die
Funktion rechnet, was sie rechnen soll — und das tut sie. Was sie nicht
prüfen können: ob **ChirpStack** die Datei laden kann. ChirpStack 4.17
führt ADR-Plugins in einer eingebetteten JS-Engine aus, nicht in Node,
und holt sich `id`, `name` und `handle` auf einem Weg, den ein
`module.exports` unter Node erfüllt und die Engine offenbar nicht.

**Das ist Paragraph 5.55 in Reinform:** ein grüner Lauf, der eine andere
Umgebung geprüft hat als die, in der es laufen muss. Dieselbe Klasse wie
die drei Funde des Wochenendes — ein Testaufbau, der eine *mögliche*,
aber nicht die *vorhandene* Lage beschreibt.

**Offen, und eigens zu belegen:** in welcher Form ChirpStack 4.17 die
Funktionen erwartet. Das ist am **Quelltext von ChirpStack** zu klären,
nicht an der Doku, und der zweite Versuch braucht einen Test, der die
Datei so lädt wie ChirpStack. Bis dahin bleibt der Eintrag draußen.

## Was offen bleibt

108 hängt auf DR3, und der Standard-Algorithmus senkt die Datenrate
**nie** von selbst. Die 16 Prozent Verlust an 108 bleiben bis zum zweiten
Versuch. Das ist die bewusste Wahl: 16 Prozent Verlust an einem Relais
gegen einen Dienst, der nicht startet.

## Nachtrag in eigener Sache

Der Notfall-Befehl, den ich gegeben habe, endete auf
`sed -n '36,46p' /vol/chirpstack.toml` — zur Kontrolle, ob der Block
richtig aussieht. Durch das Löschen der Pfadzeile rutschte der
Zeilenbereich um eins nach oben, und damit stand
`secret = "${CHIRPSTACK_API_SECRET}"` **aufgelöst** auf dem Bildschirm.

Der Fehler ist nicht der Zahlendreher, sondern der Zeilenbereich: eine
Konfigurationsdatei mit Geheimnissen prüft man **gezielt** (`grep -n
adr_plugins`, `grep -c`), nicht mit einem Fenster um die geänderte
Stelle. Ein Fenster verschiebt sich, sobald man etwas löscht — genau
dann, wenn man es benutzt.

Folge: `CHIRPSTACK_API_SECRET` rotieren, auf der Liste für Mi 18.11.
Wirkung der Rotation: das Geheimnis signiert die API- und
UI-Sitzungstoken von ChirpStack. Nach dem Wechsel sind **laufende
Anmeldungen in der ChirpStack-Oberfläche ungültig** (neu anmelden), und
dasselbe gilt für ausgestellte API-Token. Unsere Anwendung ist nicht
betroffen: der Downlink-Weg läuft über MQTT, nicht über die ChirpStack-API
(§5.28), und `CHIRPSTACK_API_KEY` ist ein eigenes Geheimnis.
