"use client";

/**
 * App-weite Client-Provider.
 *
 * Sprint 9.17 (AE-50): TanStack-Query + AuthProvider + Inaktivitaets-
 * Logout (15 Min, Hard-Cut).
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AuthProvider, useAuth } from "@/contexts/auth-context";
import { useInactivityLogout } from "@/hooks/use-inactivity-logout";
import { istOeffentlicheRoute, loginZielFuer } from "@/lib/auth/routen";
import { makeQueryClient } from "@/lib/query";

/**
 * Keine geschuetzte Seite ohne Sitzung (Hotfix 16.10.2026).
 *
 * Drei Zustaende, drei Antworten:
 *
 * | Zustand | Was passiert |
 * |---|---|
 * | `loading` | ein Hinweis, **nicht** die Seite — sonst blitzt das leere Gerüst auf |
 * | `user === null` | Umleitung auf `/login?next=<Pfad>` |
 * | angemeldet | die Seite |
 *
 * Oeffentliche Routen (`/login`, `/auth/*`) gehen immer durch, sonst dreht
 * sich die Umleitung im Kreis.
 *
 * **Warum clientseitig und nicht als `middleware.ts`:** eine Middleware
 * sieht nur, **ob** ein Cookie da ist, nicht ob es gueltig ist — den
 * abgelaufenen Fall (genau den aus dem Befund) wuerde sie durchlassen, und
 * dann braeuchte es diesen Waechter trotzdem. Zwei Waechter, von denen einer
 * weniger weiss, sind eine zweite Wahrheit (§5.53). Was eine Middleware
 * zusaetzlich koennte, ist das Aufblitzen im Bruchteil einer Sekunde sparen
 * — dafuer sorgt hier der `loading`-Zweig.
 */
function AuthGate({ children }: { children: ReactNode }): ReactNode {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const oeffentlich = istOeffentlicheRoute(pathname);

  useEffect(() => {
    if (oeffentlich || loading || user !== null) return;
    // `window.location.search` statt `useSearchParams`: der Hook erzwingt
    // im App-Router eine Suspense-Grenze um jede Seite, und der Waechter
    // laeuft ohnehin nur im Browser.
    const suche = typeof window === "undefined" ? "" : window.location.search;
    router.replace(loginZielFuer(pathname, suche) as never);
  }, [oeffentlich, loading, user, pathname, router]);

  if (oeffentlich) return <>{children}</>;
  if (loading || user === null) {
    return (
      <div
        className="min-h-screen bg-bg flex items-center justify-center text-sm text-text-secondary"
        role="status"
      >
        Anmeldung wird geprüft …
      </div>
    );
  }
  return <>{children}</>;
}

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
        <InactivityGuard>
          <AuthGate>{children}</AuthGate>
        </InactivityGuard>
      </AuthProvider>
      {process.env.NODE_ENV === "development" ? (
        <ReactQueryDevtools initialIsOpen={false} />
      ) : null}
    </QueryClientProvider>
  );
}
