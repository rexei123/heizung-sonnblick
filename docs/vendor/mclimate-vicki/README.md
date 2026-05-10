# MClimate Vicki LoRaWAN — Konsolidierte Hersteller-Doku

**Status:** Lokale Referenz für Hotel Sonnblick, kompiliert 2026-05-09
**Hardware in Betrieb:** Vicki-001 bis Vicki-004 (4 Devices, EU868)
**Bestimmungszweck:** Reference-Dokumentation für aktuelle und zukünftige
Architektur-Entscheidungen — wird nicht ohne Aktualisierungs-Check
herangezogen.

## Inhalt

| Datei | Thema |
|---|---|
| `01-open-window-detection.md` | Open-Window-Algorithmus, Defaults, Konfiguration |
| `02-operational-modes.md` | 4 Operational Modes + 3 Temperature Algorithms |
| `03-firmware-release-notes.md` | FW 3.2 bis 4.7 Changelog, Featureverfügbarkeit |
| `04-commands-cheat-sheet.md` | Alle Downlink/Uplink-Hex-Codes |
| `vicki-user-manual.pdf` | Original-Installations-Manual (LoRa Alliance) |
| `vicki-cert-test-report.pdf` | LoRa-Alliance-Zertifizierungs-Report (HW 2.3.1, FW 4.0) |

## Quellen (Stand 2026-05-09)

- Hauptdoku: https://docs.mclimate.eu/mclimate-lorawan-devices/devices/mclimate-vicki-lorawan
- API-Doku: https://docs.mclimate.eu/mclimate-api-documentation/control-devices/vicki-lorawan
- Payload Helper Tool: https://mclimate.eu/pages/payload-helper

## Kernbefund aus Sprint 9.11 Live-Test

**Problem:** Vicki meldet `openWindow=true` im Hotelbetrieb nicht zuverlässig,
selbst bei real geöffnetem Fenster mit fallender Raumluft-Temperatur.

**Ursache (durch Doku validiert):**

1. **Default-Status der Open-Window-Detection ist DISABLED** — siehe
   `01-open-window-detection.md`. MClimate liefert die Funktion ab Werk
   ausgeschaltet. Wir haben sie nie aktiviert.

2. **Algorithmus arbeitet auf internem Vicki-Sensor**, der durch HK-Wärme
   dominiert wird. Selbst bei aktiver Funktion ist die Erkennung laut
   Hersteller "not 100% reliable".

3. **Default-Parameter:** 1.0 °C Sturz binnen 1 Min. Im Realbetrieb am
   warmen HK fast nie zu erreichen.

## Sofortige Konsequenzen für unser Projekt

### Quick Wins (kostenlos, schnell, niedriges Risiko)

1. **FW-Version aller 4 Vickis abfragen** via Downlink `0x04`. In DB als
   `device.firmware_version` persistieren. Ohne FW-Info können wir Commands
   nicht zielsicher senden.

2. **Open-Window-Detection per Downlink aktivieren** auf allen Vickis mit
   FW ≥ 4.2:
   - Empfehlung: `0x4501020F` = enabled, 10 Min closed, 1.5 °C delta
   - Aggressiver: `0x45010214` = enabled, 10 Min, 2.0 °C delta (weniger Falsch-Positive)
   - **[Annahme]** Die in Sprint 9.11 verbauten Vickis (kommerziell 2024/2025)
     haben FW ≥ 4.2.

3. **Backplate-Bit ins `sensor_reading` schreiben.** Codec liefert es bereits
   als `attachedBackplate`, Backend ignoriert es. Demontage-Erkennung wird
   damit verlässlich (FW ≥ 4.3 sendet sofortigen Uplink bei Demontage).

### Architektur-Pflichten (planen, in Sprint einbauen)

1. **Backend-Window-Detection als Eigenlogik** (BR-16):
   Layer 4 darf nicht nur auf Vicki-Flag hören. Eigener Trigger über
   `sensor_reading`-Hypertable: Δ ≥ 0.5 °C in 10 Min bei stehendem Heizungs-
   Setpoint = Verdacht auf offenes Fenster. Reason: `inferred_window`.
   Vicki-Flag bleibt zusätzlicher schneller Trigger.

2. **Anti-Freeze-Funktion der Vicki nicht nutzen** (FW ≥ 4.3, Command `0x49`).
   Wir machen Frostschutz im Backend (BR-1, Sprint 9.12) — Vicki-Anti-Freeze
   würde unsere Engine-Entscheidungen unterlaufen.

3. **Heating Schedules der Vicki NICHT nutzen** (FW ≥ 4.6, Commands `0x59`–`0x6C`).
   Single source of truth ist unsere Engine; in 9.15 (Profile) bleibt das
   so. Vicki-interne Schedules würden mit unserem Profile-Konzept kollidieren.

4. **Automatic Setback der Vicki NICHT nutzen** (FW ≥ 4.6, Command `0x61`).
   Unser AE-45 (Auto-Detect-Override mit 7-Tage-Expiry) deckt die Funktion
   bereits zentral ab. Doppelter Mechanismus = doppelter Konflikt.

## Wartungs-Hinweise

- Diese Doku wurde zu einem Stichtag heruntergeladen. **Vor jeder
  Architektur-Entscheidung, die Vicki-Verhalten betrifft: prüfen, ob die
  Online-Doku aktualisiert wurde.**
- Updates der Online-Doku können neue FW-Versionen einführen, die hier nicht
  erfasst sind. Newsletter-Subscription bei MClimate empfohlen:
  https://mclimate.eu/pages/firmware-updates-newsletter
- FUOTA (Firmware-Update Over-The-Air) wird über MClimate-Cloud-Anbindung
  durchgeführt, ~1500 Downlinks pro Update. Im Hotelbetrieb relevant, wenn
  wir uns für FW-Pflege entscheiden.
