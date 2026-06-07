/**
 * TanStack-Query-Hook für das Belegungs-Import-Log (Sprint 15f, AE-66).
 *
 * Ein Hook, beide Views (Dashboard-Kachel + Detailseite) konsumieren ihn —
 * derselbe ``queryKey`` teilt den Cache. ``refetchInterval`` 60 s analog
 * ``useDashboardKpi`` (täglicher Import, schneller bringt nichts; der
 * 60-s-Takt hält die Ampel ohne Reload aktuell).
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { occupancyImportApi } from "./occupancy-import";
import type { OccupancyImportLog } from "./types";

const IMPORT_LOG_REFRESH_MS = 60_000;

export function useOccupancyImportLog(): UseQueryResult<OccupancyImportLog> {
  return useQuery({
    queryKey: ["occupancy-import", "log"],
    queryFn: () => occupancyImportApi.log(),
    refetchInterval: IMPORT_LOG_REFRESH_MS,
    staleTime: 30_000,
  });
}
