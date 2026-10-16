"use client";

/**
 * AuthContext (Sprint 9.17, AE-50).
 *
 * Laedt beim Mount ``GET /api/v1/auth/me``. State:
 *  - ``loading``   initial, vor erstem /me-Result
 *  - ``user|null`` nach /me — null heisst nicht eingeloggt
 *
 * Bei ``AUTH_ENABLED=false`` im Backend liefert /me den System-User
 * (Bootstrap-Admin) — Frontend behandelt das identisch zu „eingeloggt".
 *
 * Aktionen: ``login``, ``logout``, ``refreshUser``.
 *
 * **Wer umleitet (korrigiert am 16.10.2026):** nicht dieser Context. Hier
 * steht nach einem 401 nur ``user = null`` — die Umleitung macht der
 * ``AuthGate`` in ``components/providers.tsx``, und ein 401 *waehrend* der
 * Nutzung geht ueber ``lib/query.ts`` an ``aufAnmeldungUmleiten``
 * (``lib/auth/routen.ts``).
 *
 * **Hier stand bis zum 16.10.2026 das Gegenteil:** „Bei 401 … wird
 * automatisch auf ``/login`` umgeleitet (siehe ``handleApiError`` in
 * ``use-inactivity-logout.ts``)". Diese Funktion hat es **nie** gegeben;
 * die einzige Fundstelle im Repo war dieser Satz. Die Folge war nicht nur
 * eine falsche Zeile: ohne Anmeldung zeigte das Dashboard sein Geruest mit
 * „Wert nicht verfuegbar" und ohne Weg zur Anmeldung, und der Satz hier
 * liess es wie geloest aussehen (§5.20 — aspirative Kommentare in
 * Sicherheitslogik).
 */

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { authApi } from "@/lib/api/auth";
import type { ApiError, User } from "@/lib/api/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    try {
      const me = await authApi.me();
      setUser(me);
    } catch {
      // Jeder Fehlschlag heisst hier dasselbe: keine belastbare Sitzung.
      // Vorher stand hier ein ``if (401) … else …`` mit identischen
      // Zweigen — die Verzweigung sah aus, als wuerde 401 besonders
      // behandelt, und genau das war der Kern des Befunds vom 16.10.2026.
      // Was mit ``user === null`` passiert, entscheidet der ``AuthGate``.
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshUser();
  }, [refreshUser]);

  const login = useCallback(
    async (email: string, password: string): Promise<User> => {
      const resp = await authApi.login({ email, password });
      setUser(resp.user);
      return resp.user;
    },
    [],
  );

  const logout = useCallback(async (): Promise<void> => {
    try {
      await authApi.logout();
    } finally {
      setUser(null);
      router.push("/login");
    }
  }, [router]);

  const value: AuthContextValue = {
    user,
    loading,
    login,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth muss innerhalb <AuthProvider> aufgerufen werden");
  }
  return ctx;
}
