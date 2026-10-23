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
  // Vorgabe 0: Audit-Zeilen von vor dem 19.10.2026 fuehren das Feld nicht,
  // und ein fehlendes Feld darf das Protokoll nicht leer laufen lassen.
  checkouts_changed: z.number().default(0),
  result: z.enum(["applied", "rejected"]),
});

const occupancyImportLogSchema = z.object({
  status: z.enum(["green", "yellow", "red"]),
  last_success_at: z.string().nullable(),
  expected_by_local: z.string(),
  // `.default(null)`: ein Frontend, das kurz neuer ist als die API (rollender
  // Deploy), soll die Seite trotzdem rendern und den Satz weglassen.
  first_list_local_label: z.string().nullable().default(null),
  // Dieselbe Zeit mit Kuerzel ("12:00 MESZ"). Muss hier stehen, sonst
  // strippt Zod das Feld still aus der Antwort (§5.64).
  expected_by_local_label: z.string(),
  today_received: z.boolean(),
  imports: z.array(importRowSchema),
});

export const occupancyImportApi = {
  log: async (): Promise<OccupancyImportLog> => {
    const raw = await apiClient.get<unknown>("/api/v1/integrations/occupancy-import/log");
    return occupancyImportLogSchema.parse(raw);
  },
};
