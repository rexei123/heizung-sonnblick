/**
 * API-Funktionen fuer Raumtypen (Sprint 8.9).
 *
 * Spiegel zu backend/src/heizung/api/v1/room_types.py.
 */

import { alleSeiten } from "./alle-seiten";
import { apiClient, queryString } from "./client";
import type {
  RoomType,
  RoomTypeCreate,
  RoomTypeListQuery,
  RoomTypeUpdate,
} from "./types";

const BASE = "/api/v1/room-types";

export const roomTypesApi = {
  /**
   * **Alle** Raumtypen, über so viele Seiten wie nötig.
   *
   * Sprint 20d (B-20c-2). Alle vier Aufrufer haben hier nie ein `limit`
   * gesetzt und damit still 100 Zeilen genommen — unter ihnen die
   * Auswahlfelder in `room-form` und `room-type-inline-editor`, die ohne
   * den passenden Typ keinen Speichervorgang zulassen.
   *
   * Heute sind es eine Handvoll Raumtypen; der Befund ist also latent und
   * nicht scharf. Er bleibt latent, weil der Typ gewechselt wird, nicht
   * weil ihn jemand überwacht — deshalb derselbe Pfad wie bei Zimmern.
   *
   * Sortierung serverseitig auf `id` (`api/v1/room_types.py:88`),
   * eindeutig.
   */
  list: (q: RoomTypeListQuery = {}): Promise<RoomType[]> =>
    alleSeiten(
      (limit, offset) =>
        apiClient.get<RoomType[]>(`${BASE}${queryString({ ...q, limit, offset })}`),
      "Raumtypen-Liste",
    ),

  get: (id: number): Promise<RoomType> => apiClient.get<RoomType>(`${BASE}/${id}`),

  create: (payload: RoomTypeCreate): Promise<RoomType> =>
    apiClient.post<RoomType>(BASE, payload),

  update: (id: number, payload: RoomTypeUpdate): Promise<RoomType> =>
    apiClient.patch<RoomType>(`${BASE}/${id}`, payload),

  delete: (id: number): Promise<void> => apiClient.delete<void>(`${BASE}/${id}`),
};
