/**
 * TanStack-Query-Hooks fuer Szenarien (Sprint 9.16, AE-48).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { scenariosApi } from "./scenarios";
import type { Scenario } from "./types";

const KEYS = {
  list: ["scenarios"] as const,
};

export function useScenarios(): UseQueryResult<Scenario[]> {
  return useQuery({
    queryKey: KEYS.list,
    queryFn: () => scenariosApi.list(),
  });
}

export function useActivateScenario(
  code: string,
): UseMutationResult<Scenario, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => scenariosApi.activate(code, { scope: "global" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
    },
  });
}

export function useDeactivateScenario(
  code: string,
): UseMutationResult<Scenario, Error, void> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => scenariosApi.deactivate(code, { scope: "global" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.list });
    },
  });
}
