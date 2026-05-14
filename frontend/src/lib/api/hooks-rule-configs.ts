/**
 * TanStack-Query-Hooks fuer rule_config (Sprint 9.14, AE-46).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { ruleConfigsApi } from "./rule-configs";
import type { RuleConfigGlobal, RuleConfigGlobalUpdate } from "./types";

const KEYS = {
  global: ["rule-configs", "global"] as const,
};

export function useGlobalRuleConfig(): UseQueryResult<RuleConfigGlobal> {
  return useQuery({
    queryKey: KEYS.global,
    queryFn: () => ruleConfigsApi.getGlobal(),
  });
}

export function useUpdateGlobalRuleConfig(): UseMutationResult<
  RuleConfigGlobal,
  Error,
  RuleConfigGlobalUpdate
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RuleConfigGlobalUpdate) =>
      ruleConfigsApi.patchGlobal(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.global });
    },
  });
}
