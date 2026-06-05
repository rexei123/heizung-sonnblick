/**
 * API-Funktion fuer die Dashboard-KPIs (Sprint 14c).
 *
 * Zod-Validierung des Backend-Payloads (§5.63: Zod-Spiegel zum Pydantic-
 * Schema ``DashboardKpiRead``). Schlaegt die Validierung fehl, wirft
 * ``schema.parse`` — TanStack Query rendert dann den Fehler-State.
 */

import { z } from "zod";

import { apiClient } from "./client";
import type { DashboardKpi } from "./types";

const dashboardKpiSchema = z.object({
  rooms_occupied: z.number(),
  rooms_total: z.number(),
  avg_temperature_celsius: z.number().nullable(),
  devices_online: z.number(),
  devices_total: z.number(),
  active_overrides: z.number(),
  zones_window_open: z.number(),
  last_engine_tick: z.string().nullable(),
  // Sprint 15d (AE-65): ohne diesen Key strippt Zod battery_low_count -> Kachel
  // bekäme undefined (§5.64).
  battery_low_count: z.number(),
});

export const dashboardApi = {
  kpi: async (): Promise<DashboardKpi> => {
    const raw = await apiClient.get<unknown>("/api/v1/dashboard/kpi");
    return dashboardKpiSchema.parse(raw);
  },
};
