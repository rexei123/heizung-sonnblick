# Eine Laufliste für ein Wartungsfenster (27.11.2026)

Reine Doku. Kein Code, kein Verhalten — bis auf einen Wachposten, der die
Liste vor dem Driften schützt.

## Was drinsteht

RUNBOOK **§10bi**: ein Termin, drei Handgriffe, in der Reihenfolge, in der
sie abgearbeitet werden.

| Schritt | was | Prüfung | Rückweg |
|---|---|---|---|
| **0** | Vorbereitung: Pflicht-Frage §0.3, Notzugang, Sicherung, Ausgangsstand | vier Antworten, jede mit *STOPP, wenn* | — (hier wird noch nichts geändert) |
| **1** | Docker-Update: `apt-mark unhold` der sechs Pakete, nur sie einspielen | Container wieder `Up`, dann die **zwei Gateway-Prüfungen** | Compose neu hoch, sonst Version zurück und wieder halten |
| **2** | Tailscale stilllegen: Firewall-Regel weg, Snap entfernen | Dienst weg, Interface weg, Messwerte unberührt, SSH über die öffentliche IP | Regel zurück, Snap zurück, `tailscale login` |
| **3** | `event_log` verdichten, echter Lauf | mehr freier Platz, **dieselbe Zeilenzahl** | `--zuruecknehmen`, aber erst `df` ansehen |
| **4** | gemeinsamer Abschluss | elf Dienste, 40–55 Messwerte, Ports, Platte, Timer | — |

**Port 1883 ist nicht enthalten.** Die Sperre von außen braucht die
externe IT (#385 bleibt blockiert).

## Die drei Entscheidungen, die in der Liste stecken

**1. Die Gateway-Prüfung läuft über Mosquitto und `sensor_reading`, nicht
über Caddy.** Das UG65 spricht kein Basic Station; es publiziert per MQTT
auf 1883 und meldet sich als `gateway-ug65` an. Bis zum 17.11.2026 stand
in §10ay ein `grep` im Caddy-Protokoll, und die Laufliste vom 16.11. hat
den Fehler mitgenommen. Ein Test hält es jetzt fest.

**Die Stromtrennung am UG65 hat genau eine Bedingung:** beide Prüfungen
leer, zehn Minuten gewartet, beide noch leer. Kommt **eine** von beiden
zurück, ist der Weg in Ordnung und der Stecker bleibt stecken.

**2. Tailscale braucht den dritten Weg, bevor der zweite zugeht.** Der
Knoten ist abgemeldet, aber der Dienst läuft und das Interface existiert
(Befund vom 10.11.2026). Vorbedingung für Schritt 2 ist deshalb: die
Hetzner-Konsole ist erreichbar **und das Root-Passwort liegt im
Passwortspeicher**. Die technische Seite allein genügt nicht — ohne das
Passwort ist die Konsole im Notfall wertlos. Fehlt eines, entfällt
Schritt 2; die anderen laufen trotzdem.

**3. `install` statt `dist-upgrade`.** Heute soll genau ein Thema
durchgehen. Am 16.11. wurden die sechs Docker-Pakete zurückgehalten,
damit der Container-Neustart nicht ungeplant vor den Prüfungen kommt; ein
`dist-upgrade` hier würde 59 weitere Pakete mitnehmen und die Ursache
einer Störung unauffindbar machen.

## Die Doppelung, und was sie kostet

Die Liste wiederholt Befehle aus §10ab, §10ay und §10bh. **Das ist eine
bewusste Entscheidung gegen §5.53:** eine Laufliste, die bei jedem Schritt
„siehe §10ay" sagt, ist um 10 Uhr mit einem Gateway in der Hand nicht
benutzbar.

Der Preis ist die Drift — und genau die ist am 17.11.2026 schon einmal
eingetreten. Dagegen steht `tests/test_laufliste_befehle.py`: jeder
doppelte Befehl muss **mehr als einmal** in der Datei stehen. Wird eine
Stelle geändert, sinkt die Zahl auf 1, und der Test nennt beide Orte. Ein
zweiter Test verbietet, dass wieder eine Caddy-Prüfung in die Liste
wandert.

Beim Angleichen ist ein Unterschied aufgefallen: die Fassung vom 16.11.
hatte `|| true` am `grep -c`, §10ay nicht. Gebaut ist §10ays Form, mit
einem Satz dazu — `grep -c` endet bei null Treffern mit Rückgabewert 1,
und das ist hier die Antwort „keine Neuanmeldung" und kein Fehler.

## Ein Verweis auf etwas, das es noch nicht gibt

Schritt 3 verweist auf **§10bh** und auf das Werkzeug
`event_log_verdichten` — beides kommt mit dem PR „event_log verdichten".
Ist der nicht gemergt, entfällt Schritt 3, und die Reihenfolge des Termins
ist 0, 1, 2, 4. **Das steht als Bedingung in der Liste**, weil ein
Verweis auf einen Abschnitt, den es noch nicht gibt, am 15.11.2026 schon
einmal Zeit gekostet hat.

**Für die Merge-Reihenfolge heißt das:** „event_log verdichten" zuerst,
diese Laufliste danach. Beide fassen das Dateiende von `RUNBOOK.md` an;
§10bi hängt deshalb **hinter** §10bg und nicht davor, damit die
Einfügestellen sich nicht überlappen.

## Mutationsproben

| # | Mutation | Rot |
|---|---|---|
| A | Der Befehl in der Quelle (§10ay) geändert, Laufliste unverändert | 1 |
| B | Der Abschnitt §10bi entfernt | 5 |

## Zahlen

* 5 neue Tests, alle grün. Keine Code-Änderung, kein Frontend.
* `ruff check`, `ruff format --check`, `mypy src` ohne Befund.

## Offen

* **Der §-Referenz-Prüfer** („jeder `§`-Verweis zeigt auf einen Abschnitt,
  den es gibt") hätte den Verweis auf §10bh gefunden. Er scheitert an den
  überlappenden Nummernräumen von RUNBOOK und CLAUDE.md und steht
  weiterhin auf der Liste — die Begründung im Kopf von
  `test_runbook_warnkaesten.py` gilt unverändert.
* Der Termin selbst ist nicht gelegt. Die Liste nennt die Dauer (rund 90
  Minuten, davon 40 Minuten Warten) und wer dabei sein muss.
