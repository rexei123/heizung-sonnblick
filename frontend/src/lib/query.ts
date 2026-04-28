/**
 * TanStack-Query Client-Konfiguration.
 *
 * Defaults:
 * - staleTime: 30 s (passt zum LoRaWAN-Reading-Intervall)
 * - refetchOnWindowFocus: true (User wechselt Tab -> sieht aktuelle Daten)
 * - retry: 1 (single retry bei fehlerhaften Requests)
 */

import { QueryClient } from "@tanstack/react-query";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: 1,
      },
      mutations: {
        retry: 0,
      },
    },
  });
}
