/**
 * API-Funktionen fuer Zimmer (Sprint 8.10).
 */

import { alleSeiten } from "./alle-seiten";
import { apiClient, queryString } from "./client";
import type { EventLogEntry, Room, RoomCreate, RoomListQuery, RoomUpdate } from "./types";

const BASE = "/api/v1/rooms";

export const roomsApi = {
  /**
   * **Alle** Zimmer, über so viele Seiten wie nötig.
   *
   * Sprint 20d (B-20c-2). Der Endpoint liefert ohne `limit` 100 Zeilen
   * (`api/v1/rooms.py:97`). Vier Aufrufer erwarten die vollständige Liste
   * und hatten dafür drei verschiedene Antworten: 1000 (zweimal, am
   * `le`-Anschlag), 200 und **keine** — letzteres auf der Pairing-Seite,
   * also bei der Zuordnung während der Montage.
   *
   * Zimmer werden **vollständig** geholt und nicht geblättert, weil die
   * Menge nach oben gebunden ist: 45 Zimmer, und das wächst nur, wenn das
   * Hotel baut. Belegungen sind der Gegenfall (`occupanciesApi.list`).
   *
   * Verlässlich ist das, weil die Sortierung serverseitig und eindeutig
   * ist: `floor`, numerischer Präfix, `number` — und `Room.number` ist
   * `unique` (`models/room.py:44`), macht die Ordnung also total.
   */
  list: (q: RoomListQuery = {}): Promise<Room[]> =>
    alleSeiten(
      (limit, offset) =>
        apiClient.get<Room[]>(`${BASE}${queryString({ ...q, limit, offset })}`),
      "Zimmerliste",
    ),

  get: (id: number): Promise<Room> => apiClient.get<Room>(`${BASE}/${id}`),

  create: (payload: RoomCreate): Promise<Room> => apiClient.post<Room>(BASE, payload),

  update: (id: number, payload: RoomUpdate): Promise<Room> =>
    apiClient.patch<Room>(`${BASE}/${id}`, payload),

  delete: (id: number): Promise<void> => apiClient.delete<void>(`${BASE}/${id}`),

  // Sprint 9.5: Engine-Trace fuer Decision-Panel.
  engineTrace: (id: number, limit = 50): Promise<EventLogEntry[]> =>
    apiClient.get<EventLogEntry[]>(`${BASE}/${id}/engine-trace?limit=${limit}`),

  // Sprint 12c (AE-58): Uebersteuerungs-Sperre togglen.
  patchOverrideBlockState: (id: number, blocked: boolean): Promise<Room> =>
    apiClient.patch<Room>(`${BASE}/${id}/override-block-state`, { blocked }),
};
