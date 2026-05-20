/**
 * API-Funktionen fuer Manual-Overrides (Sprint 9.9 T8 + Sprint 12a/12b).
 *
 * Backend-Endpoints:
 *   GET    /api/v1/rooms/{room_id}/overrides[?zone_id=X]
 *   POST   /api/v1/rooms/{room_id}/overrides  (Body kann heating_zone_id tragen)
 *   DELETE /api/v1/overrides/{override_id}
 *
 * Sprint 12a T3 (AE-58): ``zone_id``-Query und ``heating_zone_id``-Body
 * fliessen via ``ManualOverrideListQuery``/``ManualOverrideCreate`` direkt
 * durch ``queryString``/``apiClient.post`` — keine separate Helper-
 * Funktion noetig, Type-System sichert Schema.
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
