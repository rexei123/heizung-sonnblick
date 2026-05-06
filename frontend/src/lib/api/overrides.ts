/**
 * API-Funktionen fuer Manual-Overrides (Sprint 9.9 T8).
 *
 * Backend-Endpoints:
 *   GET    /api/v1/rooms/{room_id}/overrides
 *   POST   /api/v1/rooms/{room_id}/overrides
 *   DELETE /api/v1/overrides/{override_id}
 */

import { apiClient, queryString } from "./client";
import type {
  ManualOverride,
  ManualOverrideCreate,
  ManualOverrideListQuery,
} from "./types";

export const overridesApi = {
  listForRoom: (
    roomId: number,
    q: ManualOverrideListQuery = {},
  ): Promise<ManualOverride[]> =>
    apiClient.get<ManualOverride[]>(
      `/api/v1/rooms/${roomId}/overrides${queryString(q)}`,
    ),

  createForRoom: (
    roomId: number,
    payload: ManualOverrideCreate,
  ): Promise<ManualOverride> =>
    apiClient.post<ManualOverride>(`/api/v1/rooms/${roomId}/overrides`, payload),

  revoke: (overrideId: number): Promise<ManualOverride> =>
    apiClient.delete<ManualOverride>(`/api/v1/overrides/${overrideId}`),
};
