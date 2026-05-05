/**
 * API-Funktionen fuer Hotel-globale Konfiguration (Sprint 8.12, Singleton).
 */

import { apiClient } from "./client";
import type { GlobalConfig, GlobalConfigUpdate } from "./types";

const BASE = "/api/v1/global-config";

export const globalConfigApi = {
  get: (): Promise<GlobalConfig> => apiClient.get<GlobalConfig>(BASE),

  update: (payload: GlobalConfigUpdate): Promise<GlobalConfig> =>
    apiClient.patch<GlobalConfig>(BASE, payload),
};
