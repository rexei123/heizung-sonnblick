/**
 * TanStack-Query-Hooks fuer Raumtypen (Sprint 8.9).
 *
 * Convention: pro Entity ein eigenes hooks-File, damit hooks.ts nicht
 * monolithisch wird (Sprint 8 fuegt 6 weitere CRUD-Entitaeten hinzu).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { roomTypesApi } from "./room-types";
import type {
  RoomType,
  RoomTypeCreate,
  RoomTypeListQuery,
  RoomTypeUpdate,
} from "./types";

const KEYS = {
  all: ["room-types"] as const,
  list: (q: RoomTypeListQuery) => ["room-types", q] as const,
  one: (id: number) => ["room-type", id] as const,
};

export function useRoomTypes(
  q: RoomTypeListQuery = {},
): UseQueryResult<RoomType[]> {
  return useQuery({
    queryKey: KEYS.list(q),
    queryFn: () => roomTypesApi.list(q),
  });
}

export function useRoomType(id: number | null): UseQueryResult<RoomType> {
  return useQuery({
    queryKey: KEYS.one(id ?? -1),
    queryFn: () => roomTypesApi.get(id!),
    enabled: id !== null && id > 0,
  });
}

export function useCreateRoomType(): UseMutationResult<
  RoomType,
  Error,
  RoomTypeCreate
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RoomTypeCreate) => roomTypesApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

export function useUpdateRoomType(
  id: number,
): UseMutationResult<RoomType, Error, RoomTypeUpdate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RoomTypeUpdate) => roomTypesApi.update(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.one(id) });
      qc.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}

export function useDeleteRoomType(): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => roomTypesApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.all });
    },
  });
}
