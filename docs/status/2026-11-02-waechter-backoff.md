## Der Relais-Wächter funkt nicht mehr jede Minute (2026-11-02)

**Keine Migration.** Backend-Steuerlogik, eine neue Einstellung
(`relay_backoff_max_s`, Vorgabe 1800 s).

**Erster Eintrag in `docs/status/`** — die Konvention steht in
`docs/status/README.md` und CLAUDE.md §3.5.

### Der Befund

Am 01.11.2026 zwischen 11:22 und 11:28 ging an Relais 109 **jede Minute**
ein Downlink hinaus, sieben Stück. Jeder bei SF12 über RX2, also 1,32 s
Sendezeit: rund neun Sekunden Sendezeit des Gateways in sieben Minuten,
an ein Gerät, das nicht antwortete.

`relay_max_versuche` stand dabei auf **3**.

```
t0      senden, versuche=1
t0+60   Frist (60 s) abgelaufen -> senden, versuche=2
t0+120  senden, versuche=3
t0+180  versuche >= 3 -> ALARM, und der Orchestrator löscht den offenen Stand
t0+240  offen ist None, der Regler will weiter EIN -> senden, versuche=1 ...
```

**Der Alarm hat seine eigene Spur gelöscht.** `max_versuche` hat nicht
die Versuche begrenzt, sondern nur getaktet, wie oft ein Alarm kommt —
§5.79 in Maschinenform. Dazu lag die feste Frist von 60 Sekunden genau
auf dem Tick-Intervall: jeder Durchlauf erzeugte einen Versuch.

### Was jetzt gilt

| | |
|---|---|
| **Frist** | verdoppelt sich je Versuch: 60 s, 120 s, 240 s, 480 s, 960 s, dann gekappt bei **1800 s** |
| **Alarm** | **genau einmal**, bei `versuche == max_versuche`. Der Versuch wird hochgezählt, ohne zu senden |
| **danach** | gedrosselte Wiederholung, keine weitere Meldung |
| **Widerspruch** | ein offener Befehl, der dem jetzigen Wunsch widerspricht, wird **nicht** wiederholt, sondern ersetzt oder verworfen |

In der ersten Stunde sind das **sechs** Downlinks statt sechzig. Der
Ende-zu-Ende-Test lässt elf Durchläufe im Minutentakt laufen und zählt
drei Versuche und einen Alarm.

### Zwei Dinge, die anders gebaut sind als besprochen

**„dann Befund" heißt hier nicht Funkstille.** Endgültiges Aufgeben wäre
die naheliegende Lesart. Der Grund dagegen steht in der Messung
desselben Tages: der Uplink-Verlust an 109 lag bei rund **30 %**. Ein
Relais an der Funkgrenze verliert damit irgendwann drei Bestätigungen in
Folge — kein Ausnahmefall, sondern der Regelfall —, und der Wächter hätte
es **dauerhaft** stillgelegt, ohne dass am Gerät etwas kaputt ist. Der
Preis für den Weg zurück ist ein Downlink je halbe Stunde, 1,3 Sekunden
Sendezeit.

**„AUS vor dem offenen Befehl prüfen" trifft den Fall nicht ganz.** Die
Reihenfolge allein hilft nicht: meldet das Gerät AUS, ist nichts zu
senden, und meldet es EIN, während ein EIN offen ist, dann ist der
Befehl bestätigt. Der Schaden lag nicht darin, dass ein AUS blockiert
wird, sondern darin, dass das **EIN wiederholt** wird, obwohl es niemand
mehr will:

> Ein EIN geht hinaus, das Gerät schaltet, der bestätigende Uplink geht
> verloren. Für uns ist das Relais AUS, während es heizt. Der Raum wird
> warm, der Regler will AUS — und der Wächter wiederholt das EIN.

Gebaut ist deshalb die allgemeine Form: **ein offener Befehl bremst nur,
solange er noch gewollt ist.** Die Versuchszählung beginnt beim Ersetzen
von vorn, sonst erbt der frische Befehl das erschöpfte Budget.

### Was beim Bauen auffiel

**Der Backoff hätte einen Absturz im Schaltpfad erzeugt.** `timedelta *
2**98` läuft mit `OverflowError` über, und die Kappung des Ergebnisses
kommt zu spät. Weil der offene Stand jetzt beliebig lange lebt, wächst
`versuche` beliebig weit — bei einem Downlink je halbe Stunde nach zwei
Tagen Funkstille erreicht. Gekappt wird deshalb der **Exponent**.
Gefunden hat das der Test mit 99 Versuchen, nicht der Entwurf.

**Der Zweig „ersetzter Befehl" ist nur unter `REFRESH` erreichbar** und
damit heute Vorsorge. Die Begründung steht in AE-78 §14; der Test sagt
es ebenfalls, damit niemand ihn als toten Code entfernt.

### Mutationsproben

| Mutation | gefallen |
|---|---|
| Backoff entfernt (Frist konstant) | 2 Einheiten-Tests + Ende-zu-Ende |
| Alarm löscht den offenen Stand wieder | Ende-zu-Ende (11 Downlinks statt 3) |
| Wunsch-Widerspruch ignoriert | 2 Einheiten-Tests + Ende-zu-Ende |
| Versuchszähler läuft über den Zielwechsel weiter | Einheiten-Test |
| Exponent nicht gekappt | Einheiten-Test (`OverflowError`) |

Die vierte Probe hat im ersten Durchgang **überlebt** — der Test traf
den Zweig nicht, weil der offene Stand im Ende-zu-Ende-Fall schon
verworfen war. Der Zweig ist nur unter `REFRESH` erreichbar; erst der
gezielte Test dorthin bringt die Probe zum Fallen.

### Was offen bleibt

**Der aufgegebene Zustand ist in der Oberfläche nicht zu sehen.**
`pending_target_on`, `pending_since` und `pending_attempts` haben keinen
Leser außer dem Orchestrator. Ein Relais, das seit Stunden keine
Bestätigung liefert, steht als Alarm im Log und sonst nirgends — und das
Log liest niemand ohne Anlass (§5.76). Vorgeschlagen für den PR zur
Paketverlust-Anzeige, der die Relais-Karte ohnehin anfasst.
