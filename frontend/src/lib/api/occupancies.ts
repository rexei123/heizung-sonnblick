/**
 * API-Funktionen fuer Belegungen (Sprint 8.11).
 */

import { apiClient, queryString } from "./client";
import type { Occupancy, OccupancyCreate, OccupancyListQuery } from "./types";

const BASE = "/api/v1/occupancies";

export const occupanciesApi = {
  list: (q: OccupancyListQuery = {}): Promise<Occupancy[]> =>
    apiClient.get<Occupancy[]>(`${BASE}${queryString(q)}`),

  get: (id: number): Promise<Occupancy> => apiClient.get<Occupancy>(`${BASE}/${id}`),

  create: (payload: OccupancyCreate): Promise<Occupancy> =>
    apiClient.post<Occupancy>(BASE, payload),

  cancel: (id: number): Promise<Occupancy> =>
    apiClient.patch<Occupancy>(`${BASE}/${id}`, { cancel: true }),
};
