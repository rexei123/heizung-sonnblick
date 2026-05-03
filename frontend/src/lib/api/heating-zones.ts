/**
 * API-Funktionen fuer Heizzonen (nested unter rooms, Sprint 8.10).
 */

import { apiClient } from "./client";
import type {
  HeatingZone,
  HeatingZoneCreate,
  HeatingZoneUpdate,
} from "./types";

const base = (roomId: number) => `/api/v1/rooms/${roomId}/heating-zones`;

export const heatingZonesApi = {
  list: (roomId: number): Promise<HeatingZone[]> =>
    apiClient.get<HeatingZone[]>(base(roomId)),

  create: (roomId: number, payload: HeatingZoneCreate): Promise<HeatingZone> =>
    apiClient.post<HeatingZone>(base(roomId), payload),

  update: (
    roomId: number,
    zoneId: number,
    payload: HeatingZoneUpdate,
  ): Promise<HeatingZone> =>
    apiClient.patch<HeatingZone>(`${base(roomId)}/${zoneId}`, payload),

  delete: (roomId: number, zoneId: number): Promise<void> =>
    apiClient.delete<void>(`${base(roomId)}/${zoneId}`),
};
