/**
 * TanStack-Hooks fuer Belegungen (Sprint 8.11).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { occupanciesApi } from "./occupancies";
import type { Occupancy, OccupancyCreate, OccupancyListQuery } from "./types";

const KEYS = {
  all: ["occupancies"] as const,
  list: (q: OccupancyListQuery) => ["occupancies", q] as const,
};

export function useOccupancies(
  q: OccupancyListQuery = {},
): UseQueryResult<Occupancy[]> {
  return useQuery({
    queryKey: KEYS.list(q),
    queryFn: () => occupanciesApi.list(q),
  });
}

export function useCreateOccupancy(): UseMutationResult<
  Occupancy,
  Error,
  OccupancyCreate
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: OccupancyCreate) => occupanciesApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.all });
      qc.invalidateQueries({ queryKey: ["rooms"] });
    },
  });
}

export function useCancelOccupancy(): UseMutationResult<Occupancy, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => occupanciesApi.cancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.all });
      qc.invalidateQueries({ queryKey: ["rooms"] });
    },
  });
}
