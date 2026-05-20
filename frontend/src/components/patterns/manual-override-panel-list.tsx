"use client";

/**
 * Sprint 12b — Container fuer das Pro-Zone-Override-UI.
 *
 * Aufgaben:
 *
 * 1. Heizzonen des Raums laden (``useHeatingZones``)
 * 2. Window-State-Set pro Zone aus dem Engine-Trace ableiten
 *    (gleiches Pattern wie ``engine-window-indicator.tsx`` — KEIN
 *    neuer Backend-Endpoint per Strategie-Chat-E1, 90s-Latenz
 *    akzeptiert)
 * 3. Aktive Overrides pro Zone bzw. fuer Room-Scope-Altbestand
 *    aus der Room-weiten Override-Liste ableiten
 * 4. Pro Zone eine ``ManualOverrideZoneCard`` rendern, plus
 *    optional die Backward-Compat ``ManualOverrideRoomCard``
 *    am Listen-Anfang (nur wenn ein aktiver Override mit
 *    ``heating_zone_id === null`` existiert, E4)
 * 5. Historie als Room-weite Tabelle unter den Cards
 *
 * Brief: Strategie-Chat 2026-05-20, Sprint 12b T2.
 */

import { useMemo } from "react";

import {
  HistoryCard,
  ManualOverrideRoomCard,
  ManualOverrideZoneCard,
} from "@/components/patterns/manual-override-panel";
import { useRoomOverrides } from "@/lib/api/hooks-overrides";
import { useEngineTrace, useHeatingZones } from "@/lib/api/hooks-rooms";
import type { EventLogEntry, ManualOverride } from "@/lib/api/types";

interface Props {
  roomId: number;
}

export function ManualOverridePanelList({ roomId }: Props) {
  const zonesQuery = useHeatingZones(roomId);
  const traceQuery = useEngineTrace(roomId);
  const overridesQuery = useRoomOverrides(roomId, { include_expired: true });

  const zones = useMemo(() => zonesQuery.data ?? [], [zonesQuery.data]);
  const overrides = useMemo(() => overridesQuery.data ?? [], [overridesQuery.data]);

  // Sprint 12b E1: Window-State aus juengster WINDOW_SAFETY-Layer-Row
  // des Engine-Trace ableiten. Pattern aus engine-window-indicator.tsx
  // reuse (extractWindowOpenSince). Hier brauchen wir die Zone-ID-Menge,
  // nicht den Zeitstempel — eigener Helper unten.
  const { openZoneIds, lastEvalTime } = useMemo(
    () => extractWindowState(traceQuery.data ?? []),
    [traceQuery.data],
  );

  // Sprint 12b E4: Backward-Compat-Room-Scope-Override (heating_zone_id
  // === null) zuerst rendern — wenn vorhanden. Sonst nicht.
  const activeRoomScopeOverride = useMemo(
    () => findActiveOverride(overrides, null),
    [overrides],
  );

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-lg font-medium text-text-primary">Übersteuerung</h2>
        <p className="text-sm text-text-secondary mt-1">
          Pro Heizzone kann ein eigener Soll-Wert gesetzt werden. Bei offenem Fenster ist die
          Übersteuerung blockiert.
        </p>
      </header>

      {activeRoomScopeOverride ? (
        <ManualOverrideRoomCard roomId={roomId} override={activeRoomScopeOverride} />
      ) : null}

      {zonesQuery.isLoading ? (
        <p className="text-sm text-text-secondary">Lade Zonen…</p>
      ) : zones.length === 0 ? (
        <p className="text-sm text-text-secondary italic">
          Dieses Zimmer hat noch keine Heizzonen. Lege im Tab „Heizzonen" zuerst eine Zone an.
        </p>
      ) : (
        zones.map((zone) => (
          <ManualOverrideZoneCard
            key={zone.id}
            roomId={roomId}
            zone={zone}
            isWindowOpen={openZoneIds.has(zone.id)}
            lastEvalTime={lastEvalTime}
            activeOverride={findActiveOverride(overrides, zone.id)}
          />
        ))
      )}

      <HistoryCard items={overrides} zones={zones} loading={overridesQuery.isLoading} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface WindowState {
  openZoneIds: Set<number>;
  lastEvalTime: string | null;
}

/**
 * Sprint 12b: liest die juengste WINDOW_SAFETY-Layer-Row aus dem
 * Engine-Trace und extrahiert die ``open_zones``-Liste (Layer-4-Output
 * aus Sprint 12 T3 — AE-52 Praezisierung). Trace ist ``ORDER BY time
 * DESC``, also der erste ``window_safety``-Eintrag ist die juengste
 * Evaluation.
 *
 * ``lastEvalTime`` ist der ISO-Timestamp dieser Layer-Row — wird im
 * Window-Blocker-Hinweis als „Stand: vor Xs" gerendert (Brief R1:
 * 90s-Latenz transparent machen).
 */
function extractWindowState(entries: EventLogEntry[]): WindowState {
  const wsEntry = entries.find((e) => e.layer === "window_safety");
  if (!wsEntry || !wsEntry.details) {
    return { openZoneIds: new Set(), lastEvalTime: null };
  }
  const raw = wsEntry.details["open_zones"];
  const ids = new Set<number>();
  if (Array.isArray(raw)) {
    for (const z of raw) {
      if (z && typeof z === "object" && "zone_id" in z) {
        const id = (z as { zone_id: unknown }).zone_id;
        if (typeof id === "number") {
          ids.add(id);
        }
      }
    }
  }
  return { openZoneIds: ids, lastEvalTime: wsEntry.time };
}

/**
 * Findet den aktiven Override fuer eine Zone (``heating_zone_id ===
 * zoneId``) oder fuer Room-Scope (``heating_zone_id === null``). Aktiv =
 * nicht revoked + nicht abgelaufen. Bei mehreren aktiven gewinnt der
 * juengste (created_at DESC) — wie Service-Layer Sprint 12a T2
 * ``get_active``.
 */
function findActiveOverride(
  overrides: ManualOverride[],
  zoneId: number | null,
): ManualOverride | null {
  const now = Date.now();
  const matches = overrides
    .filter((o) => o.heating_zone_id === zoneId)
    .filter((o) => o.revoked_at === null && new Date(o.expires_at).getTime() > now)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  return matches[0] ?? null;
}
