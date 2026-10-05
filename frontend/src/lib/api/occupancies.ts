/**
 * API-Funktionen fuer Belegungen (Sprint 8.11).
 */

import { apiClient, queryString } from "./client";
import type {
  Occupancy,
  OccupancyCreate,
  OccupancyListQuery,
  OccupancyListResponse,
} from "./types";

const BASE = "/api/v1/occupancies";

export const occupanciesApi = {
  /**
   * **Eine Seite** Belegungen plus die Gesamtzahl.
   *
   * Sprint 20d (B-20c-2) — und bewusst der **Gegenfall** zu Geräten,
   * Zimmern und Raumtypen, die alle vollständig geholt werden. Belegungen
   * wachsen unbegrenzt: ein Datensatz je Buchung, täglicher PMS-Import seit
   * dem 06.06.2026, am 02.10.2026 **959** aktive. Sie alle in den Browser
   * zu laden, wäre in einem Jahr mehrere Tausend Zeilen bei jedem
   * Seitenaufruf.
   *
   * Der Befund, der das scharf gemacht hat: die Belegungen-Seite stand auf
   * `limit: 200` und hat im Bereich „Alle" **200 von 959** gezeigt, ohne
   * das zu sagen. 759 fehlten — dasselbe Bild wie bei den Geräten, nur
   * vier Mal so groß.
   *
   * Die Antwort ist deshalb ein Envelope mit `total`, nicht eine nackte
   * Liste: ohne Gesamtzahl kann die Oberfläche nicht „100 von 959" sagen
   * und weiß nicht, ob noch etwas kommt. Warum `total` im Body steht und
   * nicht in einem Header, steht am Schema
   * (`backend/src/heizung/schemas/occupancy.py`) — kurz: `client.ts`
   * verwirft Header (`client.ts:60`), ein `X-Total-Count` käme hier nie an.
   */
  list: (q: OccupancyListQuery = {}): Promise<OccupancyListResponse> =>
    apiClient.get<OccupancyListResponse>(`${BASE}${queryString(q)}`),

  get: (id: number): Promise<Occupancy> => apiClient.get<Occupancy>(`${BASE}/${id}`),

  create: (payload: OccupancyCreate): Promise<Occupancy> =>
    apiClient.post<Occupancy>(BASE, payload),

  cancel: (id: number): Promise<Occupancy> =>
    apiClient.patch<Occupancy>(`${BASE}/${id}`, { cancel: true }),
};
