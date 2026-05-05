/**
 * TanStack-Hooks fuer Zimmer + Heizzonen (Sprint 8.10).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { heatingZonesApi } from "./heating-zones";
import { roomsApi } from "./rooms";
import type {
  EventLogEntry,
  HeatingZone,
  HeatingZoneCreate,
  HeatingZoneUpdate,
  Room,
  RoomCreate,
  RoomListQuery,
  RoomUpdate,
} from "./types";

const ROOM_KEYS = {
  all: ["rooms"] as const,
  list: (q: RoomListQuery) => ["rooms", q] as const,
  one: (id: number) => ["room", id] as const,
  engineTrace: (id: number) => ["room", id, "engine-trace"] as const,
};

/** Sprint 9.5/9.10: Engine-Pipeline-Trace fuer Decision-Panel.
 *  Refetch alle 30 s damit Hotelier auch nach automatischen Re-Evals
 *  (Belegung POST -> evaluate_room.delay) den neuen Setpoint sieht.
 */
export function useEngineTrace(roomId: number | null): UseQueryResult<EventLogEntry[]> {
  return useQuery<EventLogEntry[]>({
    queryKey: roomId ? ROOM_KEYS.engineTrace(roomId) : ["room", "engine-trace", "noop"],
    queryFn: () => roomsApi.engineTrace(roomId as number, 50),
    enabled: roomId !== null,
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
}

const ZONE_KEYS = {
  list: (roomId: number) => ["heating-zones", roomId] as const,
};

export function useRooms(q: RoomListQuery = {}): UseQueryResult<Room[]> {
  return useQuery({
    queryKey: ROOM_KEYS.list(q),
    queryFn: () => roomsApi.list(q),
  });
}

export function useRoom(id: number | null): UseQueryResult<Room> {
  return useQuery({
    queryKey: ROOM_KEYS.one(id ?? -1),
    queryFn: () => roomsApi.get(id!),
    enabled: id !== null && id > 0,
  });
}

export function useCreateRoom(): UseMutationResult<Room, Error, RoomCreate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RoomCreate) => roomsApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ROOM_KEYS.all });
    },
  });
}

export function useUpdateRoom(
  id: number,
): UseMutationResult<Room, Error, RoomUpdate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RoomUpdate) => roomsApi.update(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ROOM_KEYS.one(id) });
      qc.invalidateQueries({ queryKey: ROOM_KEYS.all });
    },
  });
}

export function useDeleteRoom(): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => roomsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ROOM_KEYS.all });
    },
  });
}

// ---------------------------------------------------------------------------
// Heizzonen
// ---------------------------------------------------------------------------

export function useHeatingZones(
  roomId: number | null,
): UseQueryResult<HeatingZone[]> {
  return useQuery({
    queryKey: ZONE_KEYS.list(roomId ?? -1),
    queryFn: () => heatingZonesApi.list(roomId!),
    enabled: roomId !== null && roomId > 0,
  });
}

export function useCreateHeatingZone(
  roomId: number,
): UseMutationResult<HeatingZone, Error, HeatingZoneCreate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: HeatingZoneCreate) =>
      heatingZonesApi.create(roomId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ZONE_KEYS.list(roomId) });
    },
  });
}

export function useUpdateHeatingZone(
  roomId: number,
): UseMutationResult<
  HeatingZone,
  Error,
  { zoneId: number; payload: HeatingZoneUpdate }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ zoneId, payload }) =>
      heatingZonesApi.update(roomId, zoneId, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ZONE_KEYS.list(roomId) });
    },
  });
}

export function useDeleteHeatingZone(
  roomId: number,
): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (zoneId: number) => heatingZonesApi.delete(roomId, zoneId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ZONE_KEYS.list(roomId) });
    },
  });
}
