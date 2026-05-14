"use client";

/**
 * App-weite Client-Provider.
 *
 * Sprint 9.17 (AE-50): TanStack-Query + AuthProvider + Inaktivitaets-
 * Logout (15 Min, Hard-Cut).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";

import { AuthProvider, useAuth } from "@/contexts/auth-context";
import { useInactivityLogout } from "@/hooks/use-inactivity-logout";
import { makeQueryClient } from "@/lib/query";

function InactivityGuard({ children }: { children: ReactNode }): ReactNode {
  const { user, logout } = useAuth();
  useInactivityLogout(user !== null, () => {
    void logout();
  });
  return <>{children}</>;
}

export function Providers({ children }: { children: ReactNode }): ReactNode {
  const [queryClient] = useState(() => makeQueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <InactivityGuard>{children}</InactivityGuard>
      </AuthProvider>
      {process.env.NODE_ENV === "development" ? (
        <ReactQueryDevtools initialIsOpen={false} />
      ) : null}
    </QueryClientProvider>
  );
}
