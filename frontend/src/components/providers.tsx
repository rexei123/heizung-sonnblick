"use client";

/**
 * App-weite Client-Provider.
 *
 * Aktuell: TanStack-Query (mit DevTools im Development).
 * Spaeter: Theme-Provider, Auth-Context, Toast-Provider, etc.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";

import { makeQueryClient } from "@/lib/query";

export function Providers({ children }: { children: ReactNode }): ReactNode {
  // Lazy-Init via useState, damit der Client nicht auf jedem Render neu entsteht.
  const [queryClient] = useState(() => makeQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === "development" ? (
        <ReactQueryDevtools initialIsOpen={false} />
      ) : null}
    </QueryClientProvider>
  );
}
