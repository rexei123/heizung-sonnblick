# Master-Inventar Hotel Sonnblick

Diese Datei dokumentiert das Master-Layout des Hotel-Inventars.

## Datei

### Zimmer_Geraete_Liste.xlsx — NICHT im Repo

Master-Layout aller Zimmer mit Heizungs-Zonen und Soll-Geraete-Anzahl.

**Diese Datei wird NICHT im Repo gehalten.** `.gitignore` blockiert
Office-Dateien aus Secret-Hygiene-Gruenden (S4/S5 — siehe
`.gitignore`-Kommentar Zeile 63-65). Die Datei lebt am Office-Laptop
unter Hotelier-Kontrolle.

Diese README dokumentiert nur das **Format** und die **Verwendung**.

## Format

| Spalte | Inhalt |
|---|---|
| Stockwerk | UG/0 bis 4 |
| Zimmernummer | Hotel-Zimmer-Nummer (52-406, mit Luecken) |
| Zimmertyp | Schlafzimmer / Badezimmer / Kinderzimmer / Wohnzimmer / Reserve |
| Zone | Bad / Schlafzimmer / Schlafzimmer L/R / Kinderzimmer / Wohnzimmer / Reserve |
| Geraete | Anzahl Vicki-TRVs pro Zone (i.d.R. 1) |

**KEINE Spalten:** `dev_eui`, `app_key`. Diese werden NICHT im Master-
Inventar gefuehrt — sie kommen separat zur Pairing-CSV dazu (siehe
unten).

## Inhalt

- **45 Zimmer** in 5 Stockwerken (UG/0 bis 4. OG)
- **105 Geraete-Slots** verbaut (30 Zimmer mit 2 Zonen, 15 Zimmer mit 3 Zonen)
- **5 Reserve-Geraete** im Lager (Pool, `heating_zone_id = NULL`)
- **110 Vickis** total

## Verwendung

### Sprint 13a Pre-Pairing-Skript (RUNBOOK §10h.2)

Der Hotelier erweitert das Master-Layout zu einer **Pairing-CSV** mit
zusaetzlichen Spalten `dev_eui` (16 Hex) und `app_key` (32 Hex). Werte
kommen vom Vicki-Aufkleber am Tisch.

Die Pairing-CSV:
- Lebt nur temporaer am Office-Laptop + Server `/tmp/`.
- Wird per `scp` auf den Server kopiert.
- Wird nach Pairing-Lauf vom Server geloescht (`rm /tmp/pairings.csv`).
- Wird **niemals committed** (S4/S5 — AppKeys sind LoRaWAN-Secrets).

### Sprint 16 heizung-main-Bootstrap

Master-Layout dient als Quelle fuer den Zimmer-Seed in heizung-main
(45 Zimmer + zugehoerige Heating-Zones). DevEUI/AppKey nicht
relevant fuer Seed.

### Sprint 17 Pre-Pairing September

Live-Pairing-Lauf am Office-Laptop mit der vom Hotelier erstellten
Pairing-CSV.

## Aenderungs-Konvention

Master-Layout-Aenderungen (neue Zimmer, neue Zonen, neue Reserve-Slots)
werden vom Hotelier am Office-XLSX gepflegt. Strukturelle Aenderungen
(neuer Zimmertyp, neue Zone-Kategorie) brauchen ggf. Schema-Anpassung
in heizung-DB — separater Sprint.

## Querverweise

- RUNBOOK §10h.2 — Pre-Pairing-Skript-Workflow
- `.gitignore` Zeile 63-66 — Office-Dateien-Sperre
- AE-57 — Device-Lifecycle inkl. Pool-Konzept
- STATUS §2at — Sprint 13a Abschluss
