/**
 * TanStack-Hooks fuer Manual-Overrides (Sprint 9.9 T8 + Sprint 12b).
 *
 * Mutationen invalidieren auch ``["room", roomId]``, damit der Engine-
 * Decision-Panel-Refetch (Layer-3-Eintrag) automatisch laeuft.
 *
 * Sprint 12b: Query-Keys tragen zusaetzlich die Zone-Achse, damit
 * Per-Zone-Lookups (``useZoneOverride``) nicht mit Room-weiten Listen
 * gegeneinander cachen.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { overridesApi } from "./overrides";
import type {
  ManualOverride,
  ManualOverrideCreate,
  ManualOverrideListQuery,
} from "./types";

const KEYS = {
  forRoom: (roomId: number, q: ManualOverrideListQuery) =>
    ["overrides", roomId, q] as const,
  forRoomScoped: (roomId: number, zoneId: number | null, q: ManualOverrideListQuery) =>
    ["overrides", roomId, { zoneId, q }] as const,
  allForRoom: (roomId: number) => ["overrides", roomId] as const,
};

export function useRoomOverrides(
  roomId: number,
  q: ManualOverrideListQuery = {},
): UseQueryResult<ManualOverride[]> {
  return useQuery({
    queryKey: KEYS.forRoom(roomId, q),
    queryFn: () => overridesApi.listForRoom(roomId, q),
    enabled: roomId > 0,
  });
}

/**
 * Sprint 12b: Convenience-Hook fuer den aktiven Per-Zone-Override.
 *
 * Liest Backend mit ``zone_id``-Query (Zone-Match + Room-Scope-Fallback
 * sortiert nach Service-Priority Zone > Room) und filtert clientseitig
 * den juengsten nicht-revokierten, nicht-expired Eintrag. ``null`` =
 * keine aktive Uebersteuerung fuer diese Zone (auch kein
 * Room-Scope-Fallback aktiv).
 *
 * Bewusst keine eigene API-Funktion fuer „active only" — Backend hat
 * ``include_expired=false`` als Listing-Option, aber Frontend muss
 * sowieso lokal nach ``revoked_at``/``expires_at`` filtern (Real-
 * Time-Anzeige der Restzeit).
 */
export function useZoneOverride(
  roomId: number,
  zoneId: number,
): UseQueryResult<ManualOverride | null> {
  const q: ManualOverrideListQuery = { zone_id: zoneId, include_expired: false };
  return useQuery({
    queryKey: KEYS.forRoomScoped(roomId, zoneId, q),
    queryFn: async (): Promise<ManualOverride | null> => {
      const list = await overridesApi.listForRoom(roomId, q);
      const now = Date.now();
      const active = list.find(
        (o) => o.revoked_at === null && new Date(o.expires_at).getTime() > now,
      );
      return active ?? null;
    },
    enabled: roomId > 0 && zoneId > 0,
  });
}

export function useCreateRoomOverride(
  roomId: number,
): UseMutationResult<ManualOverride, Error, ManualOverrideCreate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ManualOverrideCreate) =>
      overridesApi.createForRoom(roomId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.allForRoom(roomId) });
      qc.invalidateQueries({ queryKey: ["room", roomId] });
    },
  });
}

export function useRevokeOverride(
  roomId: number,
): UseMutationResult<ManualOverride, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (overrideId: number) => overridesApi.revoke(overrideId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.allForRoom(roomId) });
      qc.invalidateQueries({ queryKey: ["room", roomId] });
    },
  });
}
