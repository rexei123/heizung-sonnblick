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
import { useEngineTrace, useHeatingZones, useRoom } from "@/lib/api/hooks-rooms";
import type { EventLogEntry, ManualOverride } from "@/lib/api/types";

interface Props {
  roomId: number;
}

export function ManualOverridePanelList({ roomId }: Props) {
  const zonesQuery = useHeatingZones(roomId);
  const traceQuery = useEngineTrace(roomId);
  const overridesQuery = useRoomOverrides(roomId, { include_expired: true });
  // Sprint 12c (AE-58): Sperre-Flag. React-Query-Cache-Hit aus Parent-
  // Page (gleicher roomId-Key) — kein zusaetzlicher Network-Request.
  const roomQuery = useRoom(roomId);
  const gesperrt = roomQuery.data?.guest_override_blocked === true;
  const bisCheckout = roomQuery.data?.guest_block_bis_checkout === true;
  /**
   * Sprint 23 T4-A2: **die beiden Formen der Sperre tun hier nicht
   * dasselbe.**
   *
   * Die dauerhafte Sperre nimmt das Formular weg — so war es seit
   * Sprint 12c, und so bleibt es. Die Sperre „bis Check-out" nimmt dem
   * **Gast** das Rad, nicht der Rezeption die Eingabe: sie entsteht
   * gerade dadurch, dass die Rezeption einen Wert festsetzt, und wer ihr
   * danach das Formular verschließt, erzwingt für eine Korrektur den
   * Umweg „aufheben, setzen, wieder sperren" — drei Handgriffe, bei denen
   * der mittlere das Rad kurz freigibt. Das Gate im Dienst lässt die
   * `frontend_*`-Quellen aus demselben Grund durch
   * (`override_service.create`).
   */
  const sperreDauerhaft = gesperrt && !bisCheckout;
  const sperreBisCheckout = gesperrt && bisCheckout;
  // Sprint 21 A2: den Belegungs-Status *vor* dem Ausfuellen zeigen, nicht
  // erst danach. Die Abweisung mit 409 ROOM_NOT_OCCUPIED bleibt — sie ist
  // das Gate (§5.53: `room.status` ist die persistierte Spalte, der Service
  // rechnet mit `derive_room_status`, dazwischen liegen bis zu 60 s).
  // `undefined` heisst "noch nicht geladen" und blockiert nichts, sonst
  // blitzt der Hinweis bei jedem Seitenaufruf kurz auf.
  // Sprint 24d (S6): ein Allgemeinbereich hat keine Belegung, und das
  // Belegungs-Gate gilt dort nicht. Ohne diese Zeile stuende in der Bar
  // "Zimmer ist nicht belegt ... ab dem Check-in" — ein Satz ueber einen
  // Check-in, den es dort nie gibt.
  const istBereich = roomQuery.data?.ist_allgemeinbereich === true;
  const nichtBelegt =
    roomQuery.data !== undefined &&
    roomQuery.data.status !== "occupied" &&
    !istBereich;

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

      {gesperrt ? (
        <div
          role="status"
          aria-live="polite"
          className="flex items-start gap-3 rounded-md border border-border bg-surface p-4"
          data-testid="sperre-banner"
        >
          <span
            className="material-symbols-outlined text-text-secondary"
            style={{ fontSize: 22 }}
            aria-hidden
          >
            lock
          </span>
          <div>
            <p className="text-sm font-medium text-text-primary">
              {sperreBisCheckout
                ? "Gast kann bis Check-out nicht ändern"
                : "Übersteuerung gesperrt"}
            </p>
            <p className="text-xs text-text-secondary mt-1">
              {sperreBisCheckout
                ? "Das Rad im Zimmer bleibt ohne Wirkung. Die Rezeption kann den Wert weiter ändern; Sperre und Übersteuerung enden mit der Abreise."
                : "Neue Übersteuerungen sind aktuell nicht möglich. Bitte Mitarbeiter aufheben."}
            </p>
          </div>
        </div>
      ) : null}

      {nichtBelegt && !gesperrt ? (
        <div
          role="status"
          aria-live="polite"
          className="flex items-start gap-3 rounded-md border border-border bg-surface p-4"
        >
          <span
            className="material-symbols-outlined text-text-secondary"
            style={{ fontSize: 22 }}
            aria-hidden
          >
            person_off
          </span>
          <div>
            <p className="text-sm font-medium text-text-primary">
              Zimmer ist nicht belegt
            </p>
            <p className="text-xs text-text-secondary mt-1">
              Eine Wunschtemperatur gilt nur für belegte Zimmer. Ab dem Check-in
              ist sie wieder möglich.
            </p>
          </div>
        </div>
      ) : null}

      {activeRoomScopeOverride ? (
        <ManualOverrideRoomCard
          roomId={roomId}
          override={activeRoomScopeOverride}
          overrideBlocked={sperreDauerhaft}
        />
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
            overrideBlocked={sperreDauerhaft}
            roomNotOccupied={nichtBelegt}
            istBereich={istBereich}
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
