/**
 * TanStack-Query-Hook fuer die Dashboard-KPIs (Sprint 14c).
 *
 * ``refetchInterval: 60_000`` = Engine-Beat-Kadenz (``evaluate-due-rooms``
 * laeuft alle 60 s; schneller liefert keine neuen Werte). TanStack pausiert
 * den Intervall im Hintergrund-Tab (Default ``refetchIntervalInBackground``
 * = false), ``refetchOnWindowFocus`` (Client-Default) holt beim Zurueck-
 * wechseln sofort frische Werte.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { dashboardApi } from "./dashboard";
import type { DashboardKpi } from "./types";

const DASHBOARD_REFRESH_MS = 60_000;

export function useDashboardKpi(): UseQueryResult<DashboardKpi> {
  return useQuery({
    queryKey: ["dashboard", "kpi"],
    queryFn: () => dashboardApi.kpi(),
    refetchInterval: DASHBOARD_REFRESH_MS,
    staleTime: 30_000,
  });
}
