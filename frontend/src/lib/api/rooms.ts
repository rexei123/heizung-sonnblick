/**
 * API-Funktionen fuer Zimmer (Sprint 8.10).
 */

import { apiClient, queryString } from "./client";
import type { Room, RoomCreate, RoomListQuery, RoomUpdate } from "./types";

const BASE = "/api/v1/rooms";

export const roomsApi = {
  list: (q: RoomListQuery = {}): Promise<Room[]> =>
    apiClient.get<Room[]>(`${BASE}${queryString(q)}`),

  get: (id: number): Promise<Room> => apiClient.get<Room>(`${BASE}/${id}`),

  create: (payload: RoomCreate): Promise<Room> => apiClient.post<Room>(BASE, payload),

  update: (id: number, payload: RoomUpdate): Promise<Room> =>
    apiClient.patch<Room>(`${BASE}/${id}`, payload),

  delete: (id: number): Promise<void> => apiClient.delete<void>(`${BASE}/${id}`),
};
