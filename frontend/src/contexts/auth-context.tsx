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
 * Aktionen: ``login``, ``logout``, ``refreshUser``. Bei 401 auf
 * ``/me`` oder Folge-Requests wird automatisch auf ``/login`` umgeleitet
 * (siehe ``handleApiError`` in ``use-inactivity-logout.ts``).
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
    } catch (e) {
      const err = e as ApiError;
      if (err?.status === 401) {
        setUser(null);
      } else {
        setUser(null);
      }
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
