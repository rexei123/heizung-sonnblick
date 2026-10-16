/**
 * TanStack-Query Client-Konfiguration.
 *
 * Defaults:
 * - staleTime: 30 s (passt zum LoRaWAN-Reading-Intervall)
 * - refetchOnWindowFocus: true (User wechselt Tab -> sieht aktuelle Daten)
 * - retry: 1 (single retry bei fehlerhaften Requests)
 */

import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { aufAnmeldungUmleiten } from "@/lib/auth/routen";

/**
 * Laeuft die Sitzung **waehrend** der Nutzung ab, meldet die naechste
 * Abfrage 401 — und vorher passierte nichts weiter: die Seite blieb stehen
 * und zeigte "Wert nicht verfuegbar" (Befund 16.10.2026).
 *
 * Deshalb hier, an der einen Stelle, durch die jede Abfrage und jede
 * Mutation laeuft. `aufAnmeldungUmleiten` prueft selbst, ob die aktuelle
 * Seite oeffentlich ist — ein 401 auf `/login` ist ein falsches Passwort
 * und keine abgelaufene Sitzung.
 */
function istAbgelaufen(fehler: unknown): boolean {
  return (
    typeof fehler === "object" &&
    fehler !== null &&
    (fehler as { status?: unknown }).status === 401
  );
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (fehler) => {
        if (istAbgelaufen(fehler)) aufAnmeldungUmleiten();
      },
    }),
    mutationCache: new MutationCache({
      onError: (fehler) => {
        if (istAbgelaufen(fehler)) aufAnmeldungUmleiten();
      },
    }),
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
