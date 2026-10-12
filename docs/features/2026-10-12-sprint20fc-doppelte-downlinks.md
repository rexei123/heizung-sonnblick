# Sprint 20f-c — kein Nachsenden, solange ein Downlink aussteht (B-20f-1)

**Stand:** 2026-10-12 · **Befund des Hoteliers**, hier am Code belegt ·
**zur Freigabe** · S4-Fall (Hardware-Schutz, keine doppelten Downlinks)

---

## 0. Der Befund, und er ist bestätigt

Gerät **008** (seit 12.10. Zimmer 110, Schlafzimmer), `control_command`:

| Zeit (UTC) | Soll | `reason` | Herkunft |
|---|---|---|---|
| 06:48:23 | 18,00 | `vacant_setpoint` | normaler Dispatch |
| 06:49:45 | 18,00 | `vacant_setpoint` | **Engine-Abgleich** |

82 Sekunden Abstand, identischer `reason`, identischer Sollwert. Das Gerät
meldete noch 20 °C (Montage-Drehung), der erste Downlink war noch nicht
abgeholt — Class A, das Gerät empfängt nur im Fenster nach einem eigenen
Uplink.

---

## 1. Wer den zweiten gesendet hat

**Der Engine-Abgleich aus Sprint 20f (T3).**
`backend/src/heizung/tasks/engine_tasks.py:619–660`, der Block
`abgleich_forced`:

```python
if (
    not dev_decision.should_send      # Hysterese schweigt (delta = 0)
    and not resync_forced
    and aktiver_override is None
    and ist_wert is not None
    and ist_wert != zone_target_setpoint_c   # Geraet meldet 20, Soll 18
):
    if await asyncio.to_thread(engine_abgleich.darf_senden, dev.dev_eui):
```

Ablauf über zwei Ticks (der Beat läuft alle 60 s):

| Tick | Hysterese | Abgleich |
|---|---|---|
| 06:48:23 | `prev` ≠ 18 → **senden** (`vacant_setpoint`) | übersprungen, weil die Hysterese schon senden wollte |
| 06:49:45 | `prev` = 18 → `delta 0`, **schweigt** | Gerät meldet 20 ≠ 18, kein Override → **sendet** |

## 2. Warum die 30-Minuten-Drosselung nicht gegriffen hat

Sie greift — einen Schritt zu spät. `darf_senden`
(`services/engine_abgleich.py:136–163`) setzt die Sperre per `SET NX` mit
`DROSSEL_TTL_S = 1800`, und gezählt wird in
`engine_tasks.py:764–766`:

```python
if dev.id in abgleich_ids:
    await asyncio.to_thread(engine_abgleich.versuch_gezaehlt, dev.dev_eui)
```

`abgleich_ids` enthält **nur** Geräte, bei denen der Abgleich die Entscheidung
erzwungen hat. Der normale Dispatch um 06:48:23 landet also nicht darin,
setzt keine Sperre und zählt keinen Versuch. Der nächste Tick findet die
Sperre frei.

> **Die Drosselung deckt Abgleich gegen Abgleich. Sie deckt nicht
> Dispatch → erster Abgleich.** Das ist die ganze Lücke.

**Das Ausmaß ist dadurch begrenzt, und das gehört zur Einordnung:** nach dem
Abgleich-Downlink ist die Sperre gesetzt und der Zähler steht auf 1, also
kommt **kein dritter**. Der Schaden ist eine **Verdopplung** bei jeder
Sollwert-Änderung, keine Schleife.

Wie oft: der Abgleich feuert, solange das Gerät den neuen Wert nicht
gemeldet hat. Bei einem Keep-alive alle zehn Minuten und einem Tick-Abstand
von einer Minute holt das Gerät den Downlink in der dazwischenliegenden
Minute mit etwa einem Zehntel Wahrscheinlichkeit ab — **rund neun von zehn
Sollwert-Änderungen erzeugen also einen zweiten Downlink.** Bei zwei bis
vier Änderungen je Gerät und Tag (Nachtabsenkung an/aus, An- und Abreise)
sind das grob 200 bis 400 zusätzliche Downlinks pro Tag im Haus.

## 3. Warum `reason` in beiden Zeilen gleich ist

`control_command.reason` ist der `CommandReason`-Enum aus der
Engine-Entscheidung — hier `vacant_setpoint`. Der Abgleich ist **kein**
eigener Reason, und das ist bewusst so: §5.45 hält fest, dass der Enum
`length=30` mit DB-`CHECK` hat und Differenzierung in den Kontext gehört,
nicht in neue Enum-Werte.

Gesetzt wird ein eigener Reason nur beim Reboot-Re-Sync
(`engine_tasks.py:700`):

```python
cc_reason = CommandReason.REBOOT_RESYNC if resync_forced else base_reason
```

**Erkennbar ist der Abgleich trotzdem**, nämlich in `rule_context`
(`engine_tasks.py:705–711`): dort steht `hysteresis_reason`, und bei einem
Abgleich beginnt der Text mit `engine_abgleich:`. Die Abfrage in §6 nutzt
genau das.

**Ein Nebenbefund dazu, der nicht zum Fix gehört:** `reason` allein
unterscheidet die beiden Zeilen nicht, und das ist für die Diagnose am
`control_command` eine Lücke. Sie zu schließen heißt nicht, einen
Enum-Wert zu erfinden (30 Zeichen, DB-`CHECK`, Migration), sondern beim
Lesen `rule_context` mitzunehmen — so wie die Abfrage es tut. Als
Backlog-Punkt notiert, nicht Teil dieses Sprints.

---

## 4. Maßnahme A, minimal: ein Mindestalter für den letzten Downlink

Die Bedingung, die fehlt, braucht **keinen neuen Zustand und keine neue
Abfrage**. Der Wert liegt an genau dieser Stelle schon in der Hand
(`engine_tasks.py:588`):

```python
prev = await _last_command_for_device(session, dev.id)
prev_sp, prev_at = (None, None) if prev is None else prev
```

`_last_command_for_device` (`rules/engine.py:1019`) liefert den letzten
**erfolgreich gesendeten** Befehl mit `issued_at`. Also:

```python
and (prev_at is None or (now - prev_at) >= ABGLEICH_MIN_ABSTAND)
```

**Vorgabe `ABGLEICH_MIN_ABSTAND = 15 min`**, Begründung: ein Gerät mit
Keep-alive alle zehn Minuten hat den Downlink bis dahin mit hoher
Wahrscheinlichkeit abgeholt. Weniger als zehn Minuten wäre zu knapp (ein
Keep-alive-Abstand), mehr als 30 wäre sinnlos, weil dann ohnehin die
bestehende Drosselung greift.

**Warum nicht die Sperre beim Dispatch mitsetzen** (die naheliegende
Alternative): das wäre dieselbe Wirkung über einen zweiten Weg — ein
Redis-Schlüssel, der von zwei Stellen gesetzt wird, und ein Zähler, der
nicht mitlaufen darf. Die Bedingung oben steht dort, wo sie gilt, und
braucht nichts, was ausfallen kann. Bei Redis-Ausfall sendet der Abgleich
ohnehin nicht (`darf_senden` gibt dann `False`).

**Warum nicht `acknowledged_at`:** die Spalte existiert in
`control_command` — und **wird nirgends geschrieben**. `grep` über
`backend/src/heizung/` findet außer der Modell-Definition keine
Fundstelle. Eine Maßnahme darauf zu stellen heißt, sie erst zu bauen.

> **Das ist ein eigener Befund und gehört in den Backlog:** eine Spalte
> `acknowledged_at`, die Bestätigung verspricht und keine liefert, ist die
> Klasse aus §5.77 — ein Leser hält sie für eine Auskunft. Sie zu füllen
> wäre fachlich richtig (der Subscriber weiß, wann ein Gerät den Wert
> meldet, und ruft dort schon `erfolg_gemeldet`), aber es ist ein eigener
> Handgriff mit eigener Prüfung. **Nicht in diesem Sprint**, und bis dahin
> gehört ein Vermerk an die Spalte.

### Was die Maßnahme nicht anfasst

* **Die Hysterese.** Normale Dispatches laufen unverändert; die Bedingung
  sitzt allein im Abgleich-Zweig.
* **Den Reboot-Re-Sync.** Der hat eigenen Vorrang (`resync_forced`) und
  eine eigene Begründung (AE-63) — ein Gerät nach einem Neustart soll
  gerade **nicht** warten.
* **Die bestehende Drosselung.** Sie bleibt, und die neue Bedingung steht
  davor: erst „ist überhaupt lange genug nichts passiert", dann „darf der
  Abgleich jetzt".

---

## 5. Tasks

| # | Inhalt | Dauer |
|---|---|---|
| **T1** | Bedingung `ABGLEICH_MIN_ABSTAND` im Abgleich-Zweig, Konstante in `engine_abgleich` (keine Einstellung — es ist eine Eigenschaft des LoRaWAN-Fensters, keine Betriebspräferenz) | 0,5 h |
| **T2** | Tests: zwei Ticks nacheinander erzeugen **einen** Downlink; nach 15 min erzeugt der Abgleich wieder einen; der Reboot-Re-Sync bleibt unberührt; ohne vorigen Befehl (`prev_at is None`) greift der Abgleich sofort | 1 h |
| **T3** | Der Befund vom 12.10. als Testwand: Gerät meldet 20, Soll 18, letzter Downlink 82 s alt → **kein** zweiter | 0,5 h |
| **T4** | AE-76 um die Lücke und die Maßnahme erweitern, RUNBOOK §10s (dort steht der Abgleich für den Hotelier), STATUS | 0,75 h |
| **Summe** | | **2,75 h** |

Backlog aus diesem Sprint, **nicht** enthalten: `acknowledged_at` füllen;
`rule_context` beim Lesen von `control_command` mitnehmen.

---

## 6. Die Abfrage für die Nacht 07.10.

Absenkung 22:00 Ortszeit = 20:00 UTC. Das Fenster beginnt bewusst vorher,
damit der letzte Downlink **vor** der Absenkung als Vorgänger sichtbar ist.

Steht im PR-Text. Sie zeigt je Downlink die Herkunft (`ABGLEICH` oder den
Hysterese-Grund) und den Abstand zum vorigen Downlink desselben Geräts.

**Erwartung, falls die Analyse stimmt:** zu jedem Gerät, dessen Sollwert um
20:00 UTC gefallen ist, zwei Zeilen im Abstand von 60 bis 120 Sekunden, die
zweite mit `herkunft = ABGLEICH`. Und **keine dritte** — die Drosselung
greift ab dem zweiten.

**Funktionsprobe gelaufen** (synthetisch, der 008-Fall nachgebaut):

```
 geraet  | zeit_utc | soll  |     reason      | herkunft         | sek_seit_vorigem
----------+----------+-------+-----------------+------------------+------------------
 probe008 | 20:48:23 | 18.00 | vacant_setpoint | delta 2.0 >= 0.5 |
 probe008 | 20:49:45 | 18.00 | vacant_setpoint | ABGLEICH         |               82
```

---

## 7. Akzeptanzkriterien

1. Zwei aufeinanderfolgende Ticks nach einer Sollwert-Änderung erzeugen
   **einen** Downlink, nicht zwei (Test).
2. Meldet das Gerät nach 15 Minuten weiter den alten Wert, sendet der
   Abgleich erneut — die Lücke, die 20f geschlossen hat, bleibt geschlossen
   (Test).
3. Die Abfrage aus §6 zeigt nach dem Deploy in der nächsten Nacht **keine**
   Paare unter 15 Minuten mehr (Live-Abnahme).
4. Reboot-Re-Sync unverändert (Test).

---

## 8. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| **Der Abgleich kommt 15 min später** — ein Gerät, das nach einer Montage-Drehung falsch steht, bleibt 15 min falsch | Es blieb vorher 82 s falsch und dann weitere 30 min, weil die Drosselung nach dem ersten Abgleich greift. Der Unterschied ist klein; der Nutzen (halb so viele Downlinks) ist messbar |
| **Ein fehlgeschlagener Dispatch blockiert den Abgleich** | Nein: `_last_command_for_device` filtert auf `sent_to_gateway_at IS NOT NULL`. Ein nicht gesendeter Befehl zählt nicht als Vorgänger |
| **15 Minuten sind geraten** | Ja, aber die Spanne ist eng: unter 10 min (ein Keep-alive-Abstand) zu knapp, über 30 min sinnlos. Als Konstante mit Begründung im Code, nicht als Einstellung |
