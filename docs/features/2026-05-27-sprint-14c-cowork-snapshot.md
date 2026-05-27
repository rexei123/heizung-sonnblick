# Sprint 14c — T0 Cowork-Snapshot heizung-test

**Datum:** 2026-05-27
**Sprint:** 14c Stufe 2, T0 (read-only Live-Verify)
**Quelle:** SSH heizung-test, `docker exec deploy-db-1 psql -U heizung -d heizung`
**Zweck:** Erwartbare KPI-Werte für T6/T10-Verifikation festhalten (§5.68: aus
Diagnose-Output, nicht angenommen).

---

## Snapshot-Tabelle (Live, 2026-05-27 ~16:32 UTC)

| Kennzahl | Realwert (Live) | KPI-Bezug |
|---|---|---|
| **Zimmer 101** | Status `occupied`, Belegung check_in 2026-05-27 12:00 UTC, check_out 2026-05-29 09:00 UTC, **aktiv = true** | KPI 1 |
| **Devices healthy/degraded/silent** | **4 healthy**, 0 degraded, 0 silent (alle `retired_at IS NULL`) | KPI 3 |
| **Aktive Overrides** | **0** (`revoked_at IS NULL AND expires_at > now()`) | KPI 4 |
| **Letzter HARD_CLAMP** | 2026-05-27 16:31:54 UTC, **Alter 00:00:59** (< 10 min ✓) | KPI 6 |
| **Fenster offen (10 min)** | **0 offen** / 4 mit Flag / 4 Readings total | KPI 5 |

## Abgeleitete KPI-Erwartung (für T6/T10)

| # | KPI | Erwarteter Wert |
|---|-----|-----------------|
| 1 | Belegte Zimmer | ≥ 1 belegt (Zimmer 101), `{occupied} von {total}` |
| 2 | Ø Raumtemperatur | Wert aus 4 healthy Vickis (°C, gerundet 0,1) — nicht `—` |
| 3 | Geräte online | **4 von 4** (alle healthy) → kein warning-Tone |
| 4 | Aktive Übersteuerungen | **0** |
| 5 | Fenster offen | **0** (R1 bestätigt: kein Vicki meldet `open_window=true`; Detection-Flag wird gesendet, aber kein Fenster offen) |
| 6 | Letzter Algorithmen-Lauf | < 1 min alt → kein warning-Tone |

## Befunde

- **Zimmer 101 belegt & aktiv** (14b-Cowork-Belegung läuft bis 2026-05-29) → KPI 1
  liefert ≥ 1.
- **4 Test-Vickis healthy** — KPI 3 zeigt „4 von 4", kein degraded/silent.
- **R1 (Phase-0 §11) bestätigt:** Open-Window-Detection **ist aktiv** (4 Readings
  tragen ein `open_window`-Flag, nicht NULL), aber **kein Fenster offen** → KPI 5 = 0.
  Das ist Hardware-/Betriebs-Realität (Mai, Heizkörper kalt), **kein UI-Bug**.
- **Engine-Tick frisch** (< 1 min) — kein Deploy-Stall (§5.68), HARD_CLAMP-Marker
  liefert sinnvolle Werte.

**Akzeptanz T0 erfüllt:** Tabelle gefüllt, kein „pending"-Eintrag, alle Werte aus
echtem Diagnose-Output.
