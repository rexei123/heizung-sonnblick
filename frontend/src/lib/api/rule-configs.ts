/**
 * API-Funktionen fuer rule_config-Endpoints (Sprint 9.14, AE-46).
 *
 * Heute nur Scope=GLOBAL. Room-Type- und Room-Scope kommen mit
 * Sprint 9.15/9.16.
 */

import { apiClient } from "./client";
import type { RuleConfigGlobal, RuleConfigGlobalUpdate } from "./types";

const BASE = "/api/v1/rule-configs";

export const ruleConfigsApi = {
  getGlobal: (): Promise<RuleConfigGlobal> =>
    apiClient.get<RuleConfigGlobal>(`${BASE}/global`),

  patchGlobal: (payload: RuleConfigGlobalUpdate): Promise<RuleConfigGlobal> =>
    apiClient.patch<RuleConfigGlobal>(`${BASE}/global`, payload),
};
