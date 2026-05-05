/**
 * TanStack-Hooks fuer Hotel-globale Konfiguration (Sprint 8.12).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { globalConfigApi } from "./global-config";
import type { GlobalConfig, GlobalConfigUpdate } from "./types";

const KEY = ["global-config"] as const;

export function useGlobalConfig(): UseQueryResult<GlobalConfig> {
  return useQuery({ queryKey: KEY, queryFn: () => globalConfigApi.get() });
}

export function useUpdateGlobalConfig(): UseMutationResult<
  GlobalConfig,
  Error,
  GlobalConfigUpdate
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: GlobalConfigUpdate) => globalConfigApi.update(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY });
    },
  });
}
