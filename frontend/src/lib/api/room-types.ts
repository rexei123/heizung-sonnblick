/**
 * API-Funktionen fuer Raumtypen (Sprint 8.9).
 *
 * Spiegel zu backend/src/heizung/api/v1/room_types.py.
 */

import { apiClient, queryString } from "./client";
import type {
  RoomType,
  RoomTypeCreate,
  RoomTypeListQuery,
  RoomTypeUpdate,
} from "./types";

const BASE = "/api/v1/room-types";

export const roomTypesApi = {
  list: (q: RoomTypeListQuery = {}): Promise<RoomType[]> =>
    apiClient.get<RoomType[]>(`${BASE}${queryString(q)}`),

  get: (id: number): Promise<RoomType> => apiClient.get<RoomType>(`${BASE}/${id}`),

  create: (payload: RoomTypeCreate): Promise<RoomType> =>
    apiClient.post<RoomType>(BASE, payload),

  update: (id: number, payload: RoomTypeUpdate): Promise<RoomType> =>
    apiClient.patch<RoomType>(`${BASE}/${id}`, payload),

  delete: (id: number): Promise<void> => apiClient.delete<void>(`${BASE}/${id}`),
};
