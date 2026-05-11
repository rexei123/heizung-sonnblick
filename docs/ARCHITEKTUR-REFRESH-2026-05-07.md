# Architektur-Refresh 2026-05-07

**Status:** Verbindlich ab 2026-05-07
**Ersetzt:** Teile von STRATEGIE.md v1.0, präzisiert ARCHITEKTUR-ENTSCHEIDUNGEN.md
**Gilt für:** Alle Arbeiten ab Sprint 9.11

## Zweck

Nach 9 Sprints Implementierung und einer vollständigen Cowork-Inventarisierung
des Betterspace-Referenzsystems (46 Screens in 2 Durchgängen) wurde der
Stand des Projekts gegen die ursprüngliche Strategie geprüft. Dieses Dokument
fasst zusammen:

1. Was die Strategie bereits korrekt vorgesehen hat (Bestätigung)
2. Was die Strategie nicht oder anders gesehen hatte (Korrektur)
3. Wie der Sprint-Plan ab Sprint 9.11 angepasst wird

Dieses Dokument ist ab heute die **gemeinsame Bezugsquelle** für die drei
KI-Rollen (Strategie-Chat, Claude Code, Cowork). Bei Konflikten zwischen
diesem Dokument und älteren Dokumenten gilt dieses.

---

## 1. Was die Strategie korrekt vorgesehen hat

Die ursprüngliche Strategie (April 2026, Version 1.0) war architektonisch
solide. Cowork bestätigt:

- **Drei-Ebenen-Hierarchie** Global → Raumtyp → Raum (STRATEGIE §6.3) — exakt
  das, was Betterspace praktiziert
- **Reine Engine-Funktion** mit Layer-Pipeline (AE-06, AE-31) — sauberer
  als Betterspace-Sammelsurium aus 21 Algorithmen
- **Auditierbarkeit pro Layer** (AE-08) — vollständiger Trace, Betterspace
  hat nur einen einfachen Algorithmenverlauf
- **`scenario`/`scenario_assignment` als orthogonale Schicht** (AE-27) —
  direkte Inspiration durch Betterspace, gleiche Idee
- **Saisonale Konfiguration über `season_id`** (AE-26) — Betterspace bestätigt
  Saison-Konzept
- **Manueller Setpoint als zeitlich begrenzter Override** (AE-29) — exakt
  Betterspace „Manuelle Steuerung mit automatischer Deaktivierung"
- **DSGVO-saubere Reservation** ohne Gastnamen (AE-03) — Cowork: Betterspace
  zeigt Klarnamen, wir sind hier sauberer
- **Wetterdaten ab Tag 1** + Multi-Mandanten + API-First — alles Vorteile
  gegenüber Betterspace

## 2. Was korrigiert werden muss

Drei substantielle Korrekturen plus mehrere Klarstellungen.

### 2.1 Frostschutz zweistufig (statt absolut)

**Bisherige Strategie (§6.2 R8):** „Harte Untergrenze bei 10 °C. Nicht
verhandelbar, nicht konfigurierbar. Systemkonstante."

**Neue Strategie:** Zweistufig.

- **Hard-Cap im Code:** `FROST_PROTECTION_C = Decimal("10.0")` in
  `backend/src/heizung/rules/constants.py`. Niemand kann das per UI
  unterschreiten.
- **Raumtyp-Override (neu):** `room_type.frost_protection_c NUMERIC(4,1)
  NULL`. Default NULL → fällt auf Hard-Cap. Kann pro Raumtyp **höher**
  gesetzt werden (z. B. 12 °C für „Bad mit Handtuchwärmer"), niemals
  niedriger.

**Begründung:** Betterspace hat untere Temperaturgrenze pro Raumtyp
(Cowork S107 Use-Case 7). Reale Hotelbetriebe brauchen das, weil ein Bad
mit Wasserleitungen und Handtuchwärmer empfindlicher ist als ein Flur.
Hard-Cap bleibt als Sicherheitsnetz.

**Engine-Auswirkung:** Layer 0 (Sommer) und Layer 4 (Window) lesen
`room_type.frost_protection_c` falls gesetzt, sonst Hard-Cap. Layer 5
(Hard-Clamp) untere Grenze ist `MAX(min_temp_celsius, frost_protection_c,
HARD_CAP)`.

Verankert als **AE-42**.

> **Update 2026-05-11:** Diese Strategie-Änderung wurde zurückgestellt
> (siehe AE-42 Status „zurückgestellt"). Frostschutz bleibt vorerst
> systemweit 10 °C. Migrations-Pfad ist im AE-42-Text dokumentiert,
> Feature wird bei konkretem Bedarf aktiviert.

### 2.2 Geräte-Lifecycle als eigene UI-Disziplin

**Bisherige Strategie (§8.3):** „Thermostate Master-Detail mit Drawer."

**Neue Strategie:** Geräte-Verwaltung ist ein eigener Sub-Bereich mit
mehreren Bausteinen:

- **Pairing-Wizard** (mehrstufig): Gerät auswählen → Zimmer wählen →
  Heizzone wählen (Schlafzimmer/Bad) → Label vergeben → Bestätigen
- **Inline-Edit** für Gerät-Label (analog Betterspace-PEQ-Nummer-Edit)
- **Sortierung nach Fehlerstatus** (Default beim Aufrufen der Geräte-Liste)
- **Health-Indikatoren** pro Zeile: Battery + Signal + Online-Status +
  Notification-Bell
- **Tausch-Workflow:** Gerät kann von Heizzone getrennt und neu zugewiesen
  werden (für Hardware-Tausch)

**Akuter Anlass:** Heute haben wir keine Funktion, um ein Gerät einer
Heizzone zuzuweisen. Vicki-001 ist via Cowork-Code direkt in der DB
verlinkt, Vicki-002/003/004 hängen frei. Das blockiert Sprint 9.11
Live-Test.

Verankert als **AE-43**.

### 2.3 Drei-Ebenen-Hierarchie braucht UI auf allen drei Ebenen

**Bisherige Strategie (§6.3):** Hierarchie textlich beschrieben, UI-Mapping
implizit.

**Neue Strategie:** Klare UI-Zuordnung pro Ebene:

| Ebene | Inhalt | Route |
|---|---|---|
| Global | 17 Globale Zeiten, 8 Globale Temperaturen, Klimaanlage-Sektion | `/einstellungen/temperaturen-zeiten` |
| Raumtyp | 4 Temperatur-Schwellen (Obere/Untere Grenze, Belegt, Frei) + Verhaltens-Flags + Frostschutz | `/raumtypen/[id]` |
| Raum | Manuelle Steuerung, Fenstererkennung erzwingen, Frühzeitiger Check-In, Referenztemperatur | Cog-Modal in `/zimmer/[id]` |

Heute haben wir nur Global (rudimentär als Singleton-Form) und Raumtyp
(rudimentär ohne Frostschutz). Pro-Raum-Overrides fehlen komplett.

### 2.4 Klarstellungen ohne Strategie-Änderung

- **Phasen-Konflikt:** STRATEGIE.md §9.3 nennt 7 Phasen, WORKFLOW.md
  beschreibt 5 Phasen. **Entscheidung:** WORKFLOW.md gewinnt, STRATEGIE
  wird auf 5 Phasen harmonisiert.
- **Sidebar:** STRATEGIE.md §8.3 sieht 14 Einträge in 5 Gruppen vor.
  Heute haben wir 7 flache Einträge. Migration in einem dedizierten
  UI-Sprint.
- **Sommer-Modus:** Hardware-Faktum (vom Hotelier bestätigt): im Sommer
  übernimmt Klimaanlage, Heizthermostate sind funktionslos. Layer-0-Fast-Path
  mit nur 2 LayerSteps ist daher korrekt — keine 6-Layer-Pipeline im
  Sommer nötig. Klima-Integration kommt als eigene Domain in Phase 2+.

## 3. Datenmodell-Anpassungen

| ID | Tabelle | Änderung |
|---|---|---|
| DB-1 | `room_type` | ~~Neue Spalte `frost_protection_c NUMERIC(4,1) NULL`~~ — **zurückgestellt 2026-05-11** (siehe AE-42) |
| DB-3 | `device` | Bestehende Spalte `label` reicht, neue API-Route nötig |

Keine weiteren Schemaänderungen. Bestehende Tabellen `scenario`,
`scenario_assignment`, `season`, `manual_setpoint_event`,
`global_config` werden in späteren Sprints erst aktiviert.

## 4. Engine-Pipeline-Anpassungen

| ID | Layer | Änderung |
|---|---|---|
| E-1 | Layer 0 (Sommer) | ~~`frost_protection_c` aus `room_type` lesen, Fallback Hard-Cap~~ — **zurückgestellt 2026-05-11** (AE-42) |
| E-2 | Layer 4 (Window) | ~~analog E-1~~ — **zurückgestellt 2026-05-11** (AE-42) |
| E-3 | Layer 5 (Hard-Clamp) | ~~untere Grenze `MAX(min_temp_celsius, frost_protection_c, HARD_CAP)`~~ — **zurückgestellt 2026-05-11** (AE-42) |

Layer 1, 2, 3 unverändert. Pipeline-Reihenfolge unverändert.

Bis zur Reaktivierung lesen Layer 0, 4, 5 die globale Konstante
`FROST_PROTECTION_C` direkt aus `constants.py`, ohne Helper.

## 5. UI-Bauplan

Ergibt sich aus §2.3 und der Sidebar-Migration. Konkrete Routen:

| Route | Status | Sprint |
|---|---|---|
| `/zimmer/[id]/devices` (Tab) — Geräte zuordnen | fehlt | 9.11a |
| `/devices/pair` Pairing-Wizard | fehlt | 9.13 |
| `/devices` Liste mit Sortierung + Inline-Edit | erweitert | 9.13 |
| `/einstellungen/temperaturen-zeiten` Globale Zeiten/Temp | fehlt | 9.14 |
| `/profile` Wochentag-Schedule | fehlt | 9.15 |
| `/szenarien` Card-Grid | fehlt | 9.16 |
| `/einstellungen/saison` Sommer/Winter | fehlt | 9.16 |
| `/einstellungen/benutzer` mit NextAuth | fehlt | 9.17 |
| `/` Dashboard mit 6 KPI-Cards | leer | 9.18 |
| `/analyse/temperaturverlauf` | fehlt | 9.19 |
| `/einstellungen/api` API-Keys + Webhooks | fehlt | 9.20 |
| `/einstellungen/gateway` Gateway-Status | fehlt | 9.21 |

## 6. Sidebar-Migration

Von heute (7 flache Einträge) auf Strategie-Konform (14 Einträge in 5
Gruppen):

ÜBERSICHT
- Dashboard `/`
- Zimmerübersicht `/zimmer`
- Belegungen `/belegungen`

STEUERUNG
- Temperaturen & Zeiten `/einstellungen/temperaturen-zeiten` [NEU]
- Raumtypen `/raumtypen`
- Profile `/profile` [NEU]
- Szenarien `/szenarien` [NEU]

GERÄTE
- Thermostate `/devices`
- Pairing `/devices/pair` [NEU]
- Gateway `/einstellungen/gateway` [NEU, später]

ANALYSE
- Algorithmenverlauf — Tab in `/zimmer/[id]` (existiert)
- Temperaturverlauf `/analyse/temperaturverlauf` [NEU, später]

EINSTELLUNGEN
- Hotel `/einstellungen/hotel`
- Saison `/einstellungen/saison` [NEU, später]
- Benutzer `/einstellungen/benutzer` [mit NextAuth]
- API & Webhooks `/einstellungen/api` [NEU, später]

Migration in Sprint 9.13 (mit Geräte-Pairing).

## 7. Sprint-Plan-Adaption

Detaillierter Sprint-Plan in `docs/SPRINT-PLAN.md`. Übersicht:

| Sprint | Inhalt | Priorität |
|---|---|---|
| 9.11 | Live-Test #2 (minimal, mit DB-Hack-Zuordnung) | jetzt |
| 9.11a | API-Endpoint Geräte-Zuordnung (Quick Fix) | sofort |
| 9.13 | Geräte-Pairing-UI + Sidebar-Migration | hoch |
| 9.14 | Globale Temperaturen + Zeiten UI | hoch |
| 9.15 | Profile (Wochentag-Schedule) | mittel |
| 9.16 | Szenarien + Saison UI | mittel |
| 9.17 | NextAuth + User-UI | hoch (vor Go-Live) |
| 9.18 | Dashboard mit KPI-Cards | mittel |
| 9.19 | Temperaturverlauf-Analytics | niedrig |
| 9.20 | API-Keys + Webhooks | niedrig |
| 9.21 | Gateway-Status-UI | niedrig |
| 10 | Hygiene-Sprint (alle B-9.10*-Backlog) | hoch (vor Final-Tag) |
| 11 | PMS-Casablanca-Integration | hoch (vor Go-Live) |
| 12 | Backup + Production-Migration | hoch (vor Go-Live) |
| 13 | Wetterdaten-Service aktivieren | mittel |
| 14 | Final-Tag `v1.0.0` + Go-Live | Meilenstein |

## 8. Was bleibt unberührt

- **Engine-Logik:** 6-Layer-Pipeline + Hysterese ist korrekt und
  auditierbar. Keine Refactors.
- **Datenbank:** alle 16 Modelle bleiben. Nur eine neue Spalte (DB-1).
- **Stabilitätsregeln S1-S6** (CLAUDE.md §0): bleiben verbindlich,
  werden zusätzlich als AE-44 ins ADR-Log gehoben.
- **Autonomie-Default Stufe 2** (CLAUDE.md §0.1): bleibt.
- **Design-Strategie 2.0.1:** bleibt verbindlich.
- **WORKFLOW.md** Phasen-Modell: bleibt verbindlich, STRATEGIE wird daran
  angepasst.

## 9. Was als veraltet markiert wird

Folgende Inhalte gelten ab heute als historisch — sie werden nicht
gelöscht, aber dürfen nicht mehr für neue Pläne herangezogen werden:

- ~~STRATEGIE.md §6.2 R8 alte Fassung („absolut, nicht konfigurierbar")~~
  — **Update 2026-05-11:** Diese Markierung ist hinfällig. Strategie-Chat-
  Review hat den Schwenk auf zweistufigen Frostschutz zurückgenommen.
  R8 gilt wieder als „absolut, nicht konfigurierbar"; AE-42 wurde auf
  „zurückgestellt" gesetzt. Der Refresh-Eintrag bleibt als Historie
  stehen.
- STRATEGIE.md §9.3 7-Phasen-Modell (gilt: WORKFLOW.md 5 Phasen)
- Alle Sprint-Briefe in `docs/features/` mit Datum vor 2026-05-07
  (gilt: SPRINT-PLAN.md)
- STATUS.md §6 alter Backlog (gilt: STATUS.md §6 nach Refresh-Update)

## 10. Wie KI-Sessions ab heute starten

Siehe `docs/SESSION-START.md`. Erste Aktion in jeder neuen Session:

> „Architektur-Refresh aktiv ab 2026-05-07. Lies `docs/SESSION-START.md`
> und bestätige."
