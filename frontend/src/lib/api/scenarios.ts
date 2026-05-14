/**
 * API-Funktionen fuer Szenarien (Sprint 9.16, AE-48).
 *
 * Heute nur Scope=GLOBAL. ROOM_TYPE/ROOM kommen mit Sprint 9.16b.
 */

import { apiClient } from "./client";
import type { Scenario, ScenarioToggleRequest } from "./types";

const BASE = "/api/v1/scenarios";

export const scenariosApi = {
  list: (): Promise<Scenario[]> => apiClient.get<Scenario[]>(BASE),

  activate: (code: string, payload: ScenarioToggleRequest): Promise<Scenario> =>
    apiClient.post<Scenario>(`${BASE}/${code}/activate`, payload),

  deactivate: (code: string, payload: ScenarioToggleRequest): Promise<Scenario> =>
    apiClient.post<Scenario>(`${BASE}/${code}/deactivate`, payload),
};
