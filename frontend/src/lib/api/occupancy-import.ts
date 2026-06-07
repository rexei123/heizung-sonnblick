/**
 * API-Funktion für das Belegungs-Import-Log (Sprint 15f, AE-66).
 *
 * Zod-Spiegel zum Pydantic ``OccupancyImportLogResponse`` (§5.63). Schlägt die
 * Validierung fehl, wirft ``schema.parse`` — TanStack Query rendert dann den
 * Fehler-State. ``status`` kommt fertig berechnet vom Backend; das Frontend
 * baut KEINE Schwellen nach.
 */

import { z } from "zod";

import { apiClient } from "./client";
import type { OccupancyImportLog } from "./types";

const importRowSchema = z.object({
  received_at: z.string(),
  list_date: z.string(),
  external_id: z.string(),
  rooms_occupied: z.number(),
  rooms_closed: z.number(),
  conflicts: z.number(),
  result: z.enum(["applied", "rejected"]),
});

const occupancyImportLogSchema = z.object({
  status: z.enum(["green", "yellow", "red"]),
  last_success_at: z.string().nullable(),
  expected_by_local: z.string(),
  today_received: z.boolean(),
  imports: z.array(importRowSchema),
});

export const occupancyImportApi = {
  log: async (): Promise<OccupancyImportLog> => {
    const raw = await apiClient.get<unknown>("/api/v1/integrations/occupancy-import/log");
    return occupancyImportLogSchema.parse(raw);
  },
};
