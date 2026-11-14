---
datum: 2026-11-14
thema: Zwei Schreibpfade bekommen ihre Spur — Raumtyp-Sollwerte und Zonen-Trennung
pr: offen
---

# Zwei Vorgänge, die stattgefunden haben und nirgends standen

Vorgabe des Betreibers vom 13.11.2026. **Kein Steuerpfad** — es entstehen
nur Audit-Zeilen. Merge Montag 16.11.

## Befund 1: die Werte, nach denen Rezeption und Bar geregelt werden

Am 13.11.2026 hat der Betreiber den Grundsollwert der Rezeption **dreimal**
geändert. Aus dem Engine-Trace:

| Zeit | Sollwert |
|---|---|
| bis 07:21 | 19,0 |
| 07:21 | → 22,0 |
| 07:53 | → 20,0 |
| 08:09 | → 21,0 |

In `config_audit` stand aus **36 Stunden** genau **eine** Zeile, und die
betraf die hausweite Regel (`rule_config`, `t_vacant` 15,0 → 18). Die
drei Raumtyp-Änderungen ließen sich nur über `event_log` rekonstruieren —
also über eine Tabelle, die einem anderen Zweck dient und deren
Aufbewahrung gerade zur Diskussion steht.

**Und es sind nicht irgendwelche Werte.** Für einen **nicht buchbaren**
Raumtyp hebt `rules.engine.bereichs_kette` die drei Spalten auf
ROOM_TYPE-Rang, womit sie die hausweite Zeile **schlagen**. Rezeption und
Bar werden nach genau diesen Zahlen geregelt; der Trace sagt es selbst
(`"sollwert_quelle": "raumtyp"`).

`rule_config`, `global_config`, `scenarios` und `users` schreiben ihre
Spur seit Sprint 22. `room_type` nicht — und das war die Lücke.

## Befund 2: eine Trennung, die es nie gegeben hat

Beim Tausch der vertauschten Relais am 12.11. stehen in `business_audit`
zwei Zeilen:

| Zeit | Aktion | Gerät | vorher | nachher |
|---|---|---|---|---|
| 09:01:24 | `DEVICE_ZONE_ASSIGNED` | 110 | `{"heating_zone_id": null}` | Zone 302 |
| 09:02:17 | `DEVICE_ZONE_ASSIGNED` | 109 | `{"heating_zone_id": null}` | Zone 299 |

**Dass Relais 109 Panel vorher in der Zone Eingang hing, steht
nirgends.** Im Audit sieht es aus, als wäre es aus dem Nichts an die Bar
gekommen. Der Detach-Endpunkt hinterließ nur eine Logzeile
(`device_zone_detached`) — also nichts, was über die Aufbewahrung des
Container-Logs hinaus Bestand hat.

Ein Audit, das nur Zuordnungen kennt und keine Trennungen, erzählt die
halbe Geschichte. Die fehlende Hälfte ist genau die, die man bei einer
Verwechslung braucht.

## Was gebaut ist

**`PATCH /room-types/{id}`** schreibt eine `config_audit`-Zeile je
**geändertem** Feld, in derselben Form wie `rule_configs`:

| | |
|---|---|
| `table_name` | `room_type` |
| `scope_qualifier` | die **Raumtyp-Id** (nicht `"global"`) |
| `source` | `api` |
| Idempotenz | unveränderte Felder schreiben nichts |

**Warum die Id und nicht `"global"`:** eine Änderung an einem Raumtyp
gilt für dessen Zimmer, und wer die Spur liest, muss sehen, welcher
gemeint war. Bei `rule_config` ist `"global"` richtig, weil es dort nur
eine Zeile gibt.

**Die Gleichziehung bekommt ihre eigene Zeile.** Bei einem
Allgemeinbereich zieht das Speichern `default_t_occupied` auf den
Frei-Wert nach (`_betrieb_gleichziehen`). Das ist eine Änderung an einer
Spalte, die **niemand angefasst hat** — ohne eigene Zeile wäre sie im
Audit unsichtbar, und beim nächsten Vergleich stimmte der `old_value`
nicht mehr.

**`DELETE /devices/{id}/heating-zone`** schreibt
`DEVICE_ZONE_DETACHED` in `business_audit`, in derselben Form wie
`device_service.assign_zone`: `old_value` trägt die Zone, aus der
getrennt wurde, `new_value` das `null`. Der **Montage-Nachweis** kommt
mit, weil er hier ebenfalls zurückgesetzt wird — sonst steht später ein
Nachweis auf `null`, dessen Verschwinden keine Zeile erklärt.

Ein Gerät ohne Zone zu trennen schreibt **nichts**: der Endpunkt kehrt
früh zurück, und eine Zeile wäre ein Vorgang, der nicht stattgefunden
hat.

## Mutationsproben

| Probe | Ergebnis |
|---|---|
| Raumtyp: Audit je Feld entfernt | **3 Tests rot** |
| Raumtyp: Idempotenz-Prüfung entfernt (schreibt immer) | **1 Test rot** |
| Raumtyp: Gleichziehung nicht mitgeschrieben | **1 Test rot** |
| Raumtyp: `scope_qualifier` auf `"global"` statt der Id | **3 Tests rot** |
| Trennen: Audit-Zeile entfernt | **3 Tests rot** |
| Trennen: vorherige Zone nicht festgehalten | **2 Tests rot** |
| Trennen: Montage-Nachweis nicht festgehalten | **1 Test rot** |

Sieben Proben, sieben rot. Zwei Tests sind Gegenproben zu den Befunden
selbst: die drei Änderungen des 13.11. müssen **drei** Zeilen mit
lückenloser Kette `19 → 22 → 20 → 21` ergeben, und die Reihe Zuordnung →
Trennen → Zuordnung muss die alte Zone lesbar lassen.

## Läufe

* Backend **1924 passed, 45 skipped** — `TEST_DATABASE_URL` gesetzt.
* `ruff check`, `ruff format --check`, `mypy` grün.
* Kein Frontend-Code berührt.

## Was dieser PR nicht tut

**Die Vergangenheit wird nicht nachgetragen.** Die drei Änderungen vom
13.11. und die Trennung vom 12.11. bleiben ohne Zeile; sie sind im
Engine-Trace bzw. in diesem Dokument festgehalten und sonst nirgends.
Eine nachträglich erzeugte Audit-Zeile wäre eine Behauptung mit falschem
Zeitstempel.

**Die Spur wird nirgends angezeigt.** `config_audit` und `business_audit`
sind heute nur per SQL lesbar. Eine Ansicht dafür wäre ein eigenes Thema
— und erst sinnvoll, wenn die Schreibpfade vollständig sind.
