/**
 * TanStack-Hooks fuer Manual-Overrides (Sprint 9.9 T8).
 *
 * Mutationen invalidieren auch ``["room", roomId]``, damit der Engine-
 * Decision-Panel-Refetch (Layer-3-Eintrag) automatisch laeuft.
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
