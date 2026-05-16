# Strategie: Thermostat-Zone-Zimmer-Zuordnung

**Status:** verbindlich ab 2026-05-15
**Quelle:** Strategie-Chat 2026-05-15, Dietmar + Claude (Lead-Architect)
**Vorgänger:** keiner — bestätigt und erweitert die bisherige
Strategie aus STRATEGIE.md §7.1 und ARCHITEKTUR-REFRESH-2026-05-07 §2.2
**Verankert als ADRs:** AE-51 bis AE-54 in ARCHITEKTUR-ENTSCHEIDUNGEN.md

## 1. Grundsatz

Stabilität schlägt Optimierung. Ein Hardware-Ausfall (Vicki tot,
Batterie leer, Funkstörung, Sensor-Defekt) darf nie:

- ein Zimmer aus der Steuerung nehmen
- die Engine zum Crashen bringen
- andere Zimmer beeinflussen

Jede der folgenden Entscheidungen ist diesem Grundsatz untergeordnet.
Wo Komplexität und Stabilität in Konflikt geraten, gewinnt Stabilität
(siehe S1, S5, S6 aus AE-44).

## 2. Begriffe (einheitlich, ab sofort)

| Begriff | Bedeutung | DB-Tabelle |
|---|---|---|
| Zimmer | Buchungseinheit, PMS-Ankerpunkt | `room` |
| Zone | physischer Sub-Raum innerhalb eines Zimmers | `heating_zone` |
| Raumtyp | Vorlage / Klasse mit Default-Temperaturen | `room_type` |
| Thermostat | physisches Vicki-Gerät | `device` |

**Hierarchie:**

- Ein Zimmer enthält 1..n Zonen
- Eine Zone hat genau einen Raumtyp
- Ein Raumtyp wird von vielen Zonen geteilt (für gemeinsame Defaults)
- Ein Thermostat ist 0..1 einer Zone zugeordnet
- Eine Zone hat 0..n Thermostate

**UI-Sprache:** Im UI darf „Raum" statt „Zone" verwendet werden —
gastgeberisch und für Nicht-Techniker verständlicher. Code-Naming
bleibt `heating_zone` bis zu einer eventuellen späteren
Konsolidierung. Mapping `unit/room` aus STRATEGIE.md §7.1
(historisch) entspricht dem heutigen `room/heating_zone`.

## 3. Zuordnungs-Regeln

1. Zimmer ist übergeordnet. Alle PMS- und Belegungs-Daten hängen
   am Zimmer, nicht an der Zone.
2. Beim Anlegen eines neuen Zimmers werden Zonen automatisch
   vorbelegt (Template aus Raumtyp). Hotelier kann das anpassen.
3. Soft-Constraint: Ein Zimmer ohne Zone wird im UI als
   unvollständig markiert. Keine harte DB-Constraint.
4. Thermostate dürfen ausschließlich Zonen zugeordnet werden,
   niemals direkt einem Zimmer. Kein Shortcut-FK `device.room_id`.
5. Eine Zone ohne Thermostat erzeugt eine Warnung im UI, niemals
   einen Ausfall. Engine berechnet weiter, kein Downlink, kein
   Crash.

## 4. Mehrfach-Vicki pro Zone

Eine Zone kann 0..n Vickis haben. Das ist der Normalfall für
Zimmer mit zwei Heizkörpern im selben Raum.

### 4.1 Lesen (Aggregat-Modell)

- **Ist-Temperatur der Zone** = arithmetischer Mittelwert über alle
  als `healthy` markierten Vickis der Zone
- **Fenster-Status der Zone** = OR über alle `healthy` Vickis
  (eine sagt offen → Zone gilt als offen)
- **Backplate-Status, Batterie, Signalqualität**: pro Vicki einzeln,
  fließen ins Device-Health, nicht ins Zone-Aggregat
- **Offline-Vickis** (Status `silent` oder `degraded` aus
  Health-Modell) werden aus dem Aggregat ausgeschlossen
- **Wenn alle Vickis einer Zone offline**: Zone-Status wird `silent`,
  Engine evaluiert weiter (Setpoint wird berechnet und gespeichert),
  kein Downlink-Versuch

Akzeptierte Konsequenz: Lokale Temperatur-Unterschiede im Raum
(Bett warm, Fenster kühl) werden nicht ausgeglichen — das ist
physikalisch und durch die Architektur des Raums bedingt, nicht
durch die Software lösbar.

### 4.2 Schreiben (symmetrische Setpoints)

- Alle Vickis einer Zone bekommen denselben Setpoint
- Setpoints sind ganzzahlig (entspricht Vicki-Hardware-Constraint,
  siehe RUNBOOK §10d.7)
- Hysterese 0.5°C (AE-32) gilt pro Vicki — Downlink nur bei
  Setpoint-Änderung

## 5. Fenster-offen-Logik

### 5.1 Erkennung

- **Quelle**: ausschließlich `vicki.openWindow`-Flag im Uplink
- **Keine** Backend-eigene Plausibilitäts-Erkennung in der ersten
  Heizperiode. BR-16 (Backend-Window-Detection) bleibt im Backlog,
  Reevaluation nach Heizperiode-Auswertung Frühjahr 2027

### 5.2 Reaktion belegungs-abhängig

| Belegungs-Status der Zone | Fenster zu | Fenster offen |
|---|---|---|
| frei | Frei-Sollwert (aus Raumtyp) | Frostschutz 10°C |
| belegt | Belegt-Sollwert (aus Raumtyp) | Frei-Sollwert |

**Rückkehr zum Normal-Setpoint**: sobald **eine beliebige** Vicki
der Zone `openWindow=false` meldet, gilt die Zone als „Fenster zu".

**Pädagogische Wirkung**: Der Gast lernt während offenem Fenster
„Drehen am Vicki bringt nichts" — Override wird ignoriert (siehe
§5.3). Das motiviert zum Fenster-Schließen.

### 5.3 Override während Fenster offen

- **Gast-Override** (am Vicki erkannt via `manual_setpoint`-Field
  im Sensor-Reading): wird **ignoriert** — nicht gespeichert,
  nicht angewendet, nicht nach Fenster-Schließen reaktiviert
- **Mitarbeiter-Override im UI** während Fenster offen: ebenfalls
  ignoriert. UI muss diesen Zustand explizit anzeigen, damit der
  Mitarbeiter weiß, dass seine Eingabe wirkungslos bleibt

## 6. Override-Modell (einheitlich)

- **Override wirkt immer auf Zone-Ebene**, niemals pro Vicki
- Quelle bestimmt Dauer und Grenzen, nicht die Wirkung:
  - **Gast-Override** (Auto-Detect via Vicki): 4 h Gültigkeit
    (AE-45)
  - **Mitarbeiter-Frontend-Override**: konfigurierbar — 4h /
    Mitternacht / bis Check-out (siehe RUNBOOK §10d.7)
  - **System-Override** (`manual_setpoint_event`, AE-29): bis
    manuelles Revoke
- Wenn ein Gast nur eine Vicki einer Mehrfach-Vicki-Zone dreht,
  übernimmt die Zone den gemeldeten Wert. Alle Vickis der Zone
  fahren symmetrisch auf diesen Setpoint.

## 7. Health-Monitoring

### 7.1 Device-Health (`device.health_state`)

| Status | Bedingung |
|---|---|
| `healthy` | letzter Uplink < 2 h, alle Readings plausibel |
| `degraded` | letzter Uplink 2-24 h, oder ≥ 1 implausibles Reading in den letzten 24 h |
| `silent` | letzter Uplink > 24 h, oder ≥ 10 implausible Readings in den letzten 24 h |
| `suspicious` | Outlier gegen andere Vickis derselben Zone > 7°C Differenz |

### 7.2 Zone-Health (`heating_zone.health_state`)

Abgeleitet aus den zugeordneten Devices:

- alle Vickis `healthy` → Zone `healthy`
- mindestens eine `degraded` oder `suspicious` → Zone `degraded`
- alle `silent` oder offline → Zone `silent`
- keine Devices zugeordnet → Zone `no_device`

### 7.3 Plausibilitäts-Filter

Im MQTT-Subscriber bei Eingang jedes Sensor-Readings:

- **Ist-Temperatur außerhalb [-20°C, 60°C]** → Reading verwerfen,
  nicht persistieren, Logger-Event `implausible_reading`
- Grenzwerte bewusst weit gefasst, damit Fenster-offen-Szenarien
  (kalte Luft direkt an Vicki) nicht versehentlich gefiltert werden
- **Outlier-Erkennung gegen Zone-Geschwister**: Backlog, nach
  Heizperiode evaluieren
- **Drift-Erkennung statistisch**: Backlog (KI-Vorbereitung)

### 7.4 Alarmierung (3 Stufen)

| Stufe | Bedingung | Aktion |
|---|---|---|
| 1 | offline 2-24 h | Dashboard-Warnung, kein Mail-Versand |
| 2 | offline > 24 h | Mail an Hotelier, Zone-Health = `silent` |
| 3 | > 10 implausible Readings in 24 h | Mail an Hotelier, Device-Health = `silent` |

**Mail-Versand initial als Logger-Platzhalter**
(`logger.warning(...)`). Echter SMTP-Versand wird nach erstem
Winter in eigenem Sprint nachgereicht.

**Kein automatischer Software-Workaround bei Ausfall** — Hotelier
fixt physisch (Batterie tauschen, Vicki neu paaren). Begründung:
Versuche, eine Offline-Vicki durch andere zu kompensieren,
verschleiern das Problem statt es zu lösen.

## 8. Engine-Isolation (S5-Verstärkung)

- Engine-Eval-Lauf iteriert pro Zone in `try/except`
- Crash in einer Zone (Datenfehler, Codec-Problem, fehlende
  Foreign-Key-Daten) → Log + Skip, **kein Abbruch der Schleife**
- Andere Zonen werden normal weiter evaluiert
- Zone-Health wird bei wiederholtem Eval-Fehler auf `degraded`
  gesetzt
- Dies verankert formal eine Eigenschaft, die im Code-Stand
  bereits teilweise existiert, aber bisher nicht als
  Architektur-Pflicht festgehalten war

## 9. UI-Konsequenzen (Cross-Sicht-Pflicht)

Folgende Sichten sind ab sofort architektonische Pflicht:

- **Geräte-Liste**: Spalten `Zimmer` und `Zone` als Pflicht
  (deckt Hotelier-Feedback B-9.11x-5 ab)
- **Zimmer-Detail**: Karten pro Zone mit Soll/Ist-Temperaturen
  plus Thermostat-Bubbles (Name, Health-Status, Batterie, Signal)
- **Zone-Detail**: Liste aller Thermostate der Zone mit
  Health-Badge
- **Pairing-Wizard**: dreistufig — Zimmer wählen → Zone wählen →
  Label vergeben. Plus ChirpStack-Pairing-Stufe vorgeschaltet
  (Sprint 13). Plus Vicki-Eingangstest am Ende des Wizards
- **Dashboard**: Health-Indikator pro Zone, Warnungen sichtbar
  ohne Drill-Down

## 10. Was sich NICHT ändert

Alle bestehenden Fixpunkte bleiben unangetastet:

- **Frostschutz 10°C** als Code-Konstante (AE-42, Hard-Cap)
- **Hysterese 0.5°C** für Downlinks (AE-32)
- **Setpoint-Ganzzahligkeit** (Vicki-Hardware-Constraint)
- **6-Layer-Engine-Pipeline** (AE-31)
- **3-Ebenen-Settings-Hierarchie** Global/Raumtyp/Zone (Raum)
- **AE-43 Geräte-Lifecycle** (Pairing-Wizard, Inline-Edit,
  Sortierung)
- **AE-45 Auto-Detect-Override** (4 h Expiry für Gast-Override)
- **Sommermodus-Layer-0-Fast-Path** (AE-34)

Dieses Dokument **erweitert** die Engine um Mehrfach-Vicki-
Aggregation, belegungs-abhängige Fenster-Reaktion und Health-
Monitoring. Es **ersetzt nichts**.

## 11. ADR-Mapping

| ADR | Inhalt | Dokument-Abschnitt |
|---|---|---|
| AE-51 | Zone-Aggregat-Modell für Mehrfach-Vicki | §4 |
| AE-52 | Fenster-offen-Logik belegungs-abhängig | §5 |
| AE-53 | Health-State-Modell + Plausi-Grenzen | §7 |
| AE-54 | Engine-Zone-Isolation | §8 |

ADR-Volltexte in ARCHITEKTUR-ENTSCHEIDUNGEN.md.

## 12. STRATEGIE.md-Anpassungspunkte

- §6.2 R5 Fenster-offen-Erkennung: belegungs-abhängige Reaktion
  ergänzen, Verweis auf AE-52
- §6.2 R6 Gast-Override: Wirkung auf Zone-Ebene klarstellen,
  Verweis auf AE-51 + §6
- §7.1 Datenmodell: Begriffs-Konsolidierung mit Hinweis
  „Code-Stand: `room` entspricht hier `unit`, `heating_zone`
  entspricht hier `room`"
- Neuer §6.5 Health-Monitoring: Tabellen aus §7 hier spiegeln,
  Verweis auf STRATEGIE-THERMOSTAT-ZUORDNUNG.md als Master-Quelle

## 13. Offene Punkte (bewusst nicht entschieden)

- **Drift-Erkennung** statistisch: nach Heizperiode-Auswertung
  Frühjahr 2027
- **Backend-Plausi für Fenster** (BR-16): nach Heizperiode
  evaluieren, ob Vicki-Flag allein reicht
- **Outlier-Schwelle 7°C**: Wert ist Best Guess, empirisch nach
  Heizperiode nachjustieren
- **Flapping-Schutz / Cooldown** auf Fenster-Übergänge: nach
  Heizperiode prüfen, ob nötig
- **Casablanca-FIAS-Belegungs-Sync**: fällig vor Sprint 17,
  Hotelier-Antwort steht aus
- **Pilot-Zimmer-Auswahl** für ersten Rückbau: gemeinsam
  Mitte August festlegen

## 14. Skalierungs-Annahme

Heizperiode-Start 1. Oktober 2026 mit **Vollausbau-Ziel**:
45 Zimmer, ~100 Vickis. Kein vorsichtiges Wachstum, sondern
Direkteinstieg.

Folgekonsequenzen:

- **Pairing-UI** (Sprint 13) ist Vorbedingung, nicht nice-to-have
- **heizung-main-Migration** (Sprint 15) muss vor Pre-Pairing-
  Schwung im September durch sein
- Health-Schwellwerte sind für 100 Vickis ausgelegt, nicht 4
- **LoRaWAN-Funk-Auslastung** UG65 wird in ersten Wochen monitort
  (Backlog)
- Alarm-Schwellen Stufe 1 ggf. nach Heizperiode höher setzen —
  Alarm-Müdigkeit ist bei 100 Vickis realistisch (Backlog)

## 15. Migrations-Plan

**Grundsatz**: Phasen-Modell statt Big-Bang. Betterspace bleibt
parallel aktiv, bis das eigene System eine Heizperiode bestanden
hat.

| Zeitraum | Aktion | Hotel-Steuerung |
|---|---|---|
| Mai-Juli 2026 | Bauen auf heizung-test (Sprint 10-14) | Betterspace |
| August 2026 | Stabilisieren + heizung-main-Migration leer (Sprint 15-16) | Betterspace |
| Ende August | Erste 4 Vickis auf Main produktiv, Schulung Hotelier (Sprint 17) | Betterspace |
| September 2026 | **Pre-Pairing** aller ~100 Vickis auf einem Tisch, ohne Montage. Vicki-Eingangstest pro Gerät. | Betterspace |
| Oktober Woche 1 | **5 Pilot-Zimmer** umrüsten: Betterspace-Thermostate ab, Vickis dran. Maximale Vielfalt (Standard / Suite / Mehrfach-Vicki / Funk-Rand / häufiger Gästewechsel) | 5 Vicki + 40 Betterspace |
| Oktober-Dezember | Schrittweiser Rückbau pro Zimmer, abhängig von Lerngeschwindigkeit | gemischt |
| Frühjahr 2027 | Vollständige Migration abgeschlossen | nur Vicki |
| Nach Heizperiode | **Betterspace-Kündigung** | nur Vicki |

**Rückbau-Pfad bei Problemen**: pro Zimmer ~5 Minuten Hands-on
(Vicki ab, Betterspace-eQ-3 wieder dran, in Betterspace
aktivieren). Fallback bleibt bis zur Betterspace-Kündigung
jederzeit möglich.

**Pre-Pairing ohne Montage**: Vickis brauchen nur Funkkontakt
zum UG65-Gateway, um sich anzumelden. Pre-Pairing kann auf einem
Tisch im Hotel-Office geschehen. Vicki-Eingangstest (Setpoint
hoch → Ventil hörbar auf, Setpoint runter → Ventil hörbar zu)
bestätigt Funktionsfähigkeit vor Montage. Spart Fehler-Suche im
kalten Zimmer.
