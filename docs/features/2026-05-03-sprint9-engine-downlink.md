# Feature-Brief Sprint 9 — Regel-Engine + Downlink

**Datum:** 2026-05-03
**Phase:** 1 (Definition) — wartet auf User-OK
**Workflow-Modus:** Ultra-autonom (vereinbart 2026-05-02)
**Vorgaenger:** Sprint 8 (Stammdaten + Belegung, Tag `v0.1.8-stammdaten`)
**Folge-Sprint:** Sprint 10 (Saison + Szenarien + Sommermodus — UI fuer die Engine-Schichten)

---

## 1. Ziel (1-2 Saetze, aus Anwendersicht)

Die Heizung **steuert sich selbst**. Sobald ein Hotelier eine Belegung anlegt, berechnet die Engine den Soll-Setpoint pro Raum und sendet einen Downlink an das Vicki-TRV. Frostschutz, Vorheizen, Nachtabsenkung und manuelle Override greifen automatisch. Der Hotelier sieht im UI **warum** die Engine welchen Setpoint gewaehlt hat (Engine-Decision-Panel im Zimmer-Detail).

## 2. Nutzer / Rollen

- Engine laeuft autonom — kein Nutzer-Trigger.
- Hotelier (Admin) sieht Engine-Entscheidungen im UI (read-only) + kann via "Temperatur jetzt setzen" override (Sprint 10).
- Vicki-TRV erhaelt Downlinks via ChirpStack-API.

## 3. Akzeptanzkriterien (Checkliste)

- [ ] **Codec-fPort-2** parst Setpoint-Reply (0x52) zusaetzlich zu Periodic Reports (fPort 1, Command 0x01/0x81). Backend sieht jeden vom Vicki bestaetigten Setpoint.
- [ ] **Engine** `evaluate(ctx) -> RuleResult` als reine Funktion implementiert. 6 Layer (Layer 0 Sommermodus + Layer 1 Base + Layer 2 Temporal + Layer 3 Manual + Layer 4 Window + Layer 5 Clamp) gemaess AE-31.
- [ ] **Setpoint-Quantisierung** auf ganze Grad mit `int(round(x))` vor Downlink. AE-32 angepasst von 0.5 °C auf **1.0 °C** Hysterese (Vicki-Hardware-Limit, validiert im Spike).
- [ ] **Downlink-Adapter** publiziert via Mosquitto auf `application/<APP-ID>/device/<DevEUI>/command/down` mit base64-encoded `0x51 + 2-Byte-Setpoint*10`. Pattern wie im Vicki-Spike validiert.
- [ ] **Celery + Redis** als Worker + Broker aktiv. Redis ist im Compose vorhanden (Backlog N-13). Celery-Worker laeuft als eigener Container.
- [ ] **Trigger:** Belegungsaenderung (POST/PATCH `/occupancies`), Settings-Aenderung (rule_config / global_config) -> sofortiger `evaluate_room.delay(room_id)` Aufruf.
- [ ] **Scheduler:** Celery-Beat alle 60s prueft Raeume mit `next_transition_at <= now`. Jede Engine-Layer-Funktion traegt ggf. ihren naechsten Schaltpunkt ein.
- [ ] **Audit-Log** `event_log` (Hypertable, Sprint 8.2) wird pro Layer-Eintrag gefuellt. Auch wenn Setpoint unveraendert (KI-Vorbereitung).
- [ ] **Frostschutz** (10 °C) als Hardcoded-Konstante in `heizung.rules.constants` greift in Layer 4 (Window) und Layer 5 (Clamp). Garantiert auch bei Cloud-Ausfall (Edge-Fallback Sprint 14+).
- [ ] **Frontend Engine-Decision-Panel** im Zimmer-Detail (Tab "Engine"). Zeigt pro Layer den aktuellen Setpoint und Reason. Killer-Feature aus Master-Plan.
- [ ] Pytest-Coverage: 30+ Tests fuer Engine-Layers + Edge-Cases (Konflikt R2 vs R4, Frostschutz-Override, etc.).
- [ ] Build gruen, Tests gruen, Deploy auf `heizung-test` erfolgreich, Vicki-001 reagiert auf Belegungs-POST mit Setpoint-Aenderung im Display.

## 4. Abgrenzung (was NICHT in Sprint 9)

- KEINE Saison-Resolution in der Engine (kommt Sprint 10 — wenn `season` aktiv genutzt wird).
- KEIN Szenario-Aktivierungs-Lookup (kommt Sprint 10 — Sprint 9 nutzt direkt `rule_config`).
- KEIN Sommermodus-UI (Sprint 10).
- KEIN Edge-Fallback (Node-RED auf UG65, Sprint 14+).
- KEIN PMS-Connector — Belegungen kommen weiter manuell via UI.
- KEINE Multi-Geraet-Pro-Zone-Logik. Sprint 9 sendet einen Downlink pro Geraet, das einer Zone des Raums zugeordnet ist.

## 5. Edge Cases

- Raum ohne `room_type` -> Engine logt "skipped: no room_type", schreibt Audit-Eintrag. Kein Crash.
- Raum mit Zonen aber ohne aktive Geraete -> Engine berechnet Setpoint, persistiert `control_command`, sendet aber keinen Downlink. Audit-Eintrag mit `skipped_reason="no_active_device"`.
- Geraet `last_seen_at` > 2 h -> Downlink wird trotzdem gesendet (Vicki holt im naechsten Uplink). Audit-Eintrag markiert `device_stale=true`.
- Sommermodus aktiv -> Layer 0 Fast-Path: alle Raeume = Frostschutz. Skip Layer 1-5. Audit nur Layer 0 + Layer 5 (Clamp).
- `ROOM.status = BLOCKED` oder `CLEANING` -> Layer 1 setzt Setpoint = Frostschutz. Restliche Layer normal.
- Konflikt R2 (Vorheizen) vs R4 (Nachtabsenkung): R2 gewinnt (AE-06: Reihenfolge ist Architektur). Beide Layer-Eintraege im Audit.
- Vicki sendet manual_setpoint via fPort 2 (Gast-Override am Vicki-Drehring): Layer 3b cap auf [min, max] gemaess AE-10.
- Downlink-Hysterese: |neu - alt| < 1.0 °C UND letzte Aenderung < 6 h her -> kein Downlink (Battery sparen).

## 6. Datenmodell-Aenderungen

KEINE neuen Tabellen. Sprint 8 Migration 0003a/b hat alles vorbereitet:
- `event_log` (Hypertable) wird in Sprint 9 erstmals beschrieben
- `control_command` wird in Sprint 9 erstmals beschrieben (war seit Sprint 5 vorbereitet)
- `rule_config` wird gelesen (Layer 1)
- `global_config.summer_mode_active` wird gelesen (Layer 0)
- `manual_setpoint_event` wird gelesen (Layer 3a) — aber UI dafuer ist Sprint 10

## 7. UI-Skizze

**Neue Komponente:** `EngineDecisionPanel` als 4. Tab im Zimmer-Detail (`/zimmer/[id]`).

```
┌─ Stammdaten | Heizzonen | Geraete | Engine ────────────┐
│                                                          │
│ Aktueller Setpoint: 21 °C (Layer 1 Base Target)         │
│ Letzte Evaluation: vor 47 Sekunden                       │
│                                                          │
│ ┌─ Schicht-Trace ──────────────────────────────────┐    │
│ │ Layer 0 Sommermodus    inaktiv          —         │    │
│ │ Layer 1 Base Target    21 °C            occupied  │    │
│ │ Layer 2 Temporal       21 °C            (no rule) │    │
│ │ Layer 3 Manual         21 °C            (none)    │    │
│ │ Layer 4 Window         21 °C            closed    │    │
│ │ Layer 5 Clamp          21 °C            within    │    │
│ └─────────────────────────────────────────────────┘    │
│                                                          │
│ Letzter Downlink:                                        │
│   2026-05-03 09:45:12 -> Vicki-001                       │
│   Setpoint 21 °C, ack erhalten 09:45:34                  │
│                                                          │
│ [Audit-Log fuer diesen Raum oeffnen]                    │
└──────────────────────────────────────────────────────────┘
```

Implementierung: liest `event_log` per neuem API `GET /api/v1/rooms/{id}/engine-trace` (limit=50, ordered by time DESC).

## 8. Abhaengigkeiten

- Mosquitto-Broker laeuft + heizung-api hat ACL-Schreibrecht auf `application/+/device/+/command/down` (bereits seit Sprint 6.6.4).
- ChirpStack v4 Application-ID `b7d74615-...` (festgelegt im Spike, in `.env` als `CHIRPSTACK_APP_ID` setzen).
- Vicki-Downlink-Format Command 0x51 validiert (Spike 2026-05-02).
- Redis im Compose-Stack laeuft (existiert seit Sprint 5, ungenutzt).
- Celery + Celery-Beat als neue Compose-Services (worker + scheduler).

## 9. Risiken

| Risiko | Eintritt | Impact | Mitigation |
|---|---|---|---|
| Engine-Komplexitaet eskaliert (6 Layer + Edge-Cases) | hoch | hoch | TDD: jeden Layer einzeln entwickeln + testen, dann verschalten |
| Downlink wird zu oft gesendet (Battery-Drain) | mittel | hoch | Hysterese 1.0 °C + Heartbeat 6 h. Tests mit Vicki-001 vor Rollout. |
| Celery-Setup auf Hetzner CPX22 zu RAM-hungrig | mittel | mittel | Worker-Concurrency=2 (statt default 4). Bei Bedarf RAM-Upgrade. |
| Race-Condition: zwei Evaluations gleichzeitig fuer denselben Raum | mittel | mittel | Celery-Task-Lock per Redis (`SETNX room:N:eval_lock`) mit 30s-TTL. |
| Vicki ack kommt nicht (Class-A) | hoch | mittel | Engine sendet Downlink optimistisch; nur bei naechstem Periodic Report wird `control_command.acknowledged_at` gesetzt. |
| ChirpStack-API-Limit (Rate Limit) bei 130 Geraeten | gering | mittel | Pro Evaluation ein Downlink — bei 60s-Scheduler max. 130 Downlinks/Min, weit unter ChirpStack-Limit. |
| Frostschutz-Bug: Engine-Bug setzt Setpoint < 10 °C | gering | **sehr hoch** (Wasserschaden) | Layer 5 (Clamp) garantiert. Plus Pytest mit Negative-Test "Setpoint nie < 10". |

## 10. Offene Fragen / Annahmen

[Annahme] **Engine-Trigger:** Event-basiert (sofort) + Scheduler (60 s). Reicht fuer 45 Zimmer.
[Annahme] **Celery-Worker-Container:** Eigener Service `celery_worker` im docker-compose.prod.yml. Image = api-Image (gleiche Codebasis).
[Annahme] **CHIRPSTACK_APP_ID** wird neu in `.env` gesetzt (heizung-test + heizung-main). Wert ist server-spezifisch.
[Annahme] **Frostschutz-Konstante** bleibt 10.0 °C (`heizung.rules.constants.FROST_PROTECTION_C`). Aenderung nur via Code-Review.
[Annahme] **Audit-Schreib-Frequenz:** pro Evaluation 6 Eintraege (1 pro Layer), bei 60s-Scheduler + 45 Raeumen ergibt 6*45*60 = 16'200 Rows/h. TimescaleDB-Compression deckt das ab.

**Wirklich offen — User-Entscheidung:**

- KEINE — Annahmen sind alle annehmbar. Bei Bedarf nachjustieren.

---

## 11. Definition of Done fuer den ganzen Sprint 9

- [ ] Codec-Erweiterung fPort 2 deployed + verifiziert (Vicki-Setpoint kommt im Backend an)
- [ ] Engine-Code mit 30+ Tests gruen
- [ ] Celery-Worker laeuft auf heizung-test
- [ ] Belegung POST -> Engine-Run -> Downlink -> Vicki-Display zeigt neuen Setpoint (durchgehender Live-Test)
- [ ] Frontend Engine-Decision-Panel zeigt Layer-Trace
- [ ] AE-32 ADR-Update auf 1.0 °C Hysterese in `docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`
- [ ] Tag `v0.1.9-engine` gesetzt
- [ ] STATUS.md + CONTEXT.md aktualisiert

---

## Sprint-9-Sub-Sprints (vorlaeufig — finaler Sprintplan in separater Datei)

| # | Titel | Zeit |
|---|---|---|
| 9.0 | Codec mclimate-vicki.js fPort 2 Erweiterung + Test mit Vicki | 2-3 h |
| 9.1 | Celery + Redis-Setup, Worker-Container, Compose-Erweiterung | 2-3 h |
| 9.2 | ChirpStack-Downlink-Adapter (mosquitto-publisher) | 2 h |
| 9.3 | Engine Layer 0 + 5 (Sommermodus + Hard Clamp) + Hysterese | 3 h |
| 9.4 | Engine Layer 1 + 2 (Base + Temporal) | 4 h |
| 9.5 | Engine Layer 3 + 4 (Manual + Window) | 3 h |
| 9.6 | Trigger-Logik (Event + Scheduler) | 2-3 h |
| 9.7 | Audit-Log-Persistenz + GET /rooms/{id}/engine-trace API | 2 h |
| 9.8 | Frontend EngineDecisionPanel | 3-4 h |
| 9.9 | Live-Test mit Vicki-001: Belegung -> Engine -> Downlink -> Display | 2 h |
| 9.10 | Doku + PR + Tag v0.1.9-engine | 1-2 h |

**Gesamt: ca. 26-32 h Arbeitsblock** ueber mehrere PRs.

---

*Phase 1 (Definition) abgeschlossen. Phase 2 (Sprintplan) folgt nach User-OK in `docs/features/2026-05-03-sprint9-engine-downlink-sprintplan.md`.*
