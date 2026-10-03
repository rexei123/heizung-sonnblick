/**
 * TanStack-Hooks fuer Belegungen (Sprint 8.11).
 */

import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
  type UseInfiniteQueryResult,
  type InfiniteData,
  type UseMutationResult,
} from "@tanstack/react-query";

import { occupanciesApi } from "./occupancies";
import type {
  Occupancy,
  OccupancyCreate,
  OccupancyListQuery,
  OccupancyListResponse,
} from "./types";

const KEYS = {
  all: ["occupancies"] as const,
  list: (q: OccupancyListQuery) => ["occupancies", q] as const,
};

/** Seitengroesse der Belegungs-Liste. Wie der Server-Default. */
export const BELEGUNGEN_SEITE = 100;

/**
 * Belegungen seitenweise, mit Gesamtzahl.
 *
 * Sprint 20d (B-20c-2). Der Vorgaenger war ein `useQuery` mit
 * `limit: 200` — die Ansicht „Alle" hat damit **200 von 959** gezeigt, ohne
 * das zu sagen. Belegungen wachsen unbegrenzt, also werden sie echt
 * paginiert statt vollstaendig geholt (im Gegensatz zu Geraeten, Zimmern
 * und Raumtypen, siehe `alle-seiten.ts`).
 *
 * `limit` und `offset` setzt dieser Hook selbst; wer sie in `q` mitgibt,
 * wird ueberschrieben. Das ist Absicht — sonst haette ein Aufrufer wieder
 * die Wahl, die der Befund von 20c erst moeglich gemacht hat.
 */
export function useOccupanciesSeiten(
  q: OccupancyListQuery = {},
): UseInfiniteQueryResult<InfiniteData<OccupancyListResponse>, Error> {
  return useInfiniteQuery({
    queryKey: KEYS.list(q),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      occupanciesApi.list({ ...q, limit: BELEGUNGEN_SEITE, offset: pageParam }),
    getNextPageParam: (letzte) => {
      const geladen = letzte.offset + letzte.items.length;
      // Der naechste Versatz ist die Zahl der **geladenen** Zeilen, nicht
      // `offset + limit`: kaeme eine Seite kuerzer zurueck als angefragt,
      // wuerde `offset + limit` die Luecke ueberspringen.
      //
      // `items.length > 0` ist das Sicherheitsnetz: eine leere Seite bei
      // `total > 0` wuerde sonst endlos weiterblaettern.
      if (letzte.items.length === 0 || geladen >= letzte.total) return undefined;
      return geladen;
    },
  });
}

export function useCreateOccupancy(): UseMutationResult<
  Occupancy,
  Error,
  OccupancyCreate
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: OccupancyCreate) => occupanciesApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.all });
      qc.invalidateQueries({ queryKey: ["rooms"] });
    },
  });
}

export function useCancelOccupancy(): UseMutationResult<Occupancy, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => occupanciesApi.cancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.all });
      qc.invalidateQueries({ queryKey: ["rooms"] });
    },
  });
}
