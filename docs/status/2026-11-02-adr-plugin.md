## ADR-Plugin für das Relais-Profil: vorbereitet, nicht ausgerollt (2026-11-02)

**Keine Migration.** Eine JavaScript-Datei, ihr Test, RUNBOOK §10av.
**Nichts davon ist aktiv** — die zwei Zeilen, die es aktiv machen würden,
sind bewusst nicht gesetzt.

### Die Ausgangsfrage und ihre Antwort

Gewünscht war „ein Hex-Befehl, den ich selbst über ChirpStack → 109 →
Queue eingebe". **Den gibt es nicht**, und zwar aus zwei unabhängigen
Gründen:

**Am Gerät nicht.** Die Hersteller-Seite „network-related settings"
dokumentiert vier Befehle — `0x10`/`0x19` (Join-Wiederholung),
`0x1C`/`0x1D` (Funk-Wachhund), `0x11`/`0x1B` (Uplink-Art), `0xA4`
(Region, nur lesbar). Keiner betrifft ADR, Datenrate, Spreizfaktor oder
Sendeleistung.

**In der Warteschlange auch nicht.** Sie nimmt Anwendungs-Nutzlasten;
`LinkADRReq` ist ein MAC-Befehl, den der Server selbst schickt.

### Warum 109 auf SF7 festhängt

**ADR läuft nur, wenn das Gerät das ADR-Bit setzt, und ChirpStacks
Standard-Algorithmus senkt die Datenrate nie** — er erhöht sie nur. 109
ist einmal auf DR5 hochgezogen worden und bleibt dort, auch bei RSSI
−113 dBm. Das ist keine Fehlfunktion, sondern der Algorithmus.

### Was vorbereitet ist

`infra/chirpstack/configuration/adr-plugins/relais-feste-datenrate.js`:
DR3 (SF9) festnageln, `nbTrans 2`, volle Sendeleistung — **nur** für
Geräte mit dem Profil „Relais 16ASPM", weil die Zuweisung je
**Geräteprofil** läuft (`adr_algorithm_id`). Eine Änderung in
`region_eu868.toml` wäre dagegen regionsweit und damit das Gegenteil:
`min_dr`/`max_dr` gelten für alle hundert Vickis.

Das Plugin hält die Region-Grenzen ein. Ein DR außerhalb von
`min_dr`/`max_dr` wäre ein `LinkADRReq`, den das Gerät ablehnen muss —
und ein abgelehnter `LinkADRReq` heißt: die Datenrate bleibt, wie sie
war, ohne Hinweis.

### Der Fund beim Bauen, und er hätte Mittwoch gekostet

**Der Init-Sidecar bindet nur `infra/chirpstack/configuration` als
`/template` ein** und rendert daraus genau zwei Dateien in das Volume,
das ChirpStack als `/etc/chirpstack` sieht. Ein Plugin irgendwo sonst im
Repo wäre im Container **nicht vorhanden** — der Pfad stünde in der
Konfiguration, die Datei fehlte, und ChirpStack sagt dazu nichts
Aussagekräftiges.

Deshalb liegt die Datei unter `configuration/`, und deshalb braucht der
Einbau **zwei** Zeilen und nicht eine: den Eintrag in `chirpstack.toml`
**und** ein `cp -r /template/adr-plugins /output/` im Sidecar. Beides
steht in §10av Schritt 1.

### Warum der Test die Datei ausführt

ChirpStack lädt die Plugins beim Start und führt sie als **Skript** aus
(rquickjs) — `export` ist nicht zulässig, Klassen sind es nicht, und bei
einem Fehler im Skript gibt es **keine** aussagekräftige Meldung. Am
Mittwoch hängen rund hundert Vickis an diesem Server; ein Plugin, das
erst dort auffällt, ist der teuerste mögliche Zeitpunkt.

Der Test ruft die Datei deshalb mit `node` auf, genau wie der Codec-Test.
Ein Python-Nachbau hätte die zwei Fehler, die hier möglich sind — Syntax
und fehlende Funktion —, nicht gefunden.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| `export` vor `handle` (Modul statt Skript) | **alle fünf** Tests |
| Region-Grenzen ignoriert | der Grenzen-Test |
| `nbTrans` auf 1 | der DR3-Test |

Die erste ist die wichtigste: sie ist genau der Fehler, der ChirpStack am
Mittwoch nicht starten ließe, und sie bringt die ganze Datei zu Fall —
nicht ein Detail.

### Sendezeit, gerechnet

Bei 26 Byte und BW 125 kostet ein Uplink bei SF7 **82 ms**, bei SF9
**267 ms**. Mit Keepalive alle zehn Minuten und `nbTrans 2` sind das
3,2 s/h, also **0,09 %** — die 1-%-Grenze ist nicht in Sicht. Sendezeit
ist hier kein Argument gegen irgendetwas.

Ein Downlink in RX1 nimmt die Datenrate des Uplinks, wird also von 51 ms
auf 165 ms langsamer. Das bleibt weit unter den **1319 ms**, die ein
Class-C-Downlink über RX2 bei DR0/SF12 ohnehin kostet.

### Die Notfall-Option, dokumentiert und nicht ausgeführt

Zwei Gerätebefehle, die ohne Server-Eingriff gehen: `1C 00 18` (Wachhund
für bestätigte Uplinks aus) **vor** `11 01` (bestätigte Uplinks), beide
fPort 1, unconfirmed. Die Reihenfolge ist nicht beliebig — der Wachhund
führt nach zwei unbestätigten Uplinks plus sieben Minuten einen
**Neustart des Geräts** aus, und bei 30 % Verlust stellt man damit ein
Gerät ein, das sich regelmäßig selbst neu startet. Der Weg ändert die
Datenrate **nicht**; er behebt den Verlust durch Wiederholung.

Steht in §10au als Rückfall. **Kein Befehl ohne Freigabe.**

### Was nicht geändert wurde

**`rx2_dr` bleibt bei DR0.** Ein Class-C-Downlink würde bei DR3 von
1,32 s auf 0,165 s fallen — Faktor acht —, aber `rx2_dr` ist
**regionsweit**, und bereits beigetretene Geräte behalten ihre
RX2-Einstellung, bis der Server ihnen ein `RXParamSetupReq` schickt oder
sie neu beitreten. In diesem Fenster erwartet ein Vicki DR0, der Server
sendet DR3, und der Downlink ist weg — lautlos. Dieselbe Wirkung erreicht
man über die **Anzahl** der Downlinks, und die ist mit dem
Wächter-Backoff schon gefallen (AE-78 §14).
