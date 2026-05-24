/**
 * TanStack-Hooks fuer Device-Lifecycle (Sprint 13b.2, AE-57).
 *
 * Sitzt auf den drei 13b.1-Backend-Endpoints:
 *   - GET  /api/v1/devices/pool                  -> useDevicePool
 *   - POST /api/v1/devices/{id}/replace/from-pool -> useReplaceFromPool
 *   - POST /api/v1/devices/{id}/retire            -> useRetireDevice
 *
 * Pattern-Vorbild: hooks-overrides.ts. Mutationen invalidieren breit
 * den ``["devices"]``-Prefix (deckt Listen + Pool + Detail-Keys aus
 * hooks.ts ab) plus optional ``["room", roomId]`` fuer den Zimmer-
 * Detail-Refetch (EngineDecisionPanel + Zone-Liste).
 *
 * Pool-Query hat verkuerzte ``staleTime``, weil Pool race-relevant
 * ist (zwei Sessions koennen denselben Reserve-Thermostat sehen, nur
 * eine bekommt ihn — Backend race-safe via UPDATE-WHERE, siehe
 * CLAUDE.md §5.60).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { devicesApi } from "./devices";
import type {
  Device,
  DeviceReplaceFromPoolRequest,
  DeviceRetireRequest,
} from "./types";

const KEYS = {
  pool: ["devices", "pool"] as const,
};

export function useDevicePool(): UseQueryResult<Device[]> {
  return useQuery({
    queryKey: KEYS.pool,
    queryFn: () => devicesApi.getPool(),
    staleTime: 10_000,
  });
}

export function useReplaceFromPool(
  deviceId: number,
  roomId?: number,
): UseMutationResult<Device, Error, DeviceReplaceFromPoolRequest> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DeviceReplaceFromPoolRequest) =>
      devicesApi.replaceFromPool(deviceId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device", deviceId] });
      if (roomId !== undefined) {
        qc.invalidateQueries({ queryKey: ["room", roomId] });
      }
    },
  });
}

export function useRetireDevice(
  deviceId: number,
  roomId?: number,
): UseMutationResult<Device, Error, DeviceRetireRequest> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DeviceRetireRequest) =>
      devicesApi.retireDevice(deviceId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["devices"] });
      qc.invalidateQueries({ queryKey: ["device", deviceId] });
      if (roomId !== undefined) {
        qc.invalidateQueries({ queryKey: ["room", roomId] });
      }
    },
  });
}
