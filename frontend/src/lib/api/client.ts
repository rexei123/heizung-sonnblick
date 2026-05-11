/**
 * Minimaler Fetch-Wrapper fuer das Heizung-Backend.
 *
 * - Pfade IMMER relativ ("/api/v1/...") — Caddy proxiert zur FastAPI.
 * - JSON in/out, Standard-Error-Handling.
 * - Kein globaler State, kein Auth (kommt in spaeterem Sprint).
 */

import type { ApiError } from "./types";

const DEFAULT_TIMEOUT_MS = 15_000;

async function request<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(path, {
      ...rest,
      signal: controller.signal,
      // K-1 (Sprint 8a): same-origin schickt Browser-Auth-Header
      // (HTTP-Basic-Auth, Cookies) automatisch mit. Default ohne diese
      // Option waere "same-origin" nur fuer Cookies, NICHT fuer Auth-
      // Header bei manuellen fetch()-Calls — TanStack Query bekommt
      // sonst 401 obwohl Browser eingeloggt ist.
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(rest.body ? { "Content-Type": "application/json" } : {}),
        ...(rest.headers ?? {}),
      },
    });

    if (!res.ok) {
      let detail: unknown = res.statusText;
      try {
        const body = await res.json();
        detail = body?.detail ?? body;
      } catch {
        // body war kein JSON — statusText reicht
      }
      const err: ApiError = { status: res.status, detail };
      throw err;
    }

    if (res.status === 204) {
      return undefined as T;
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export const apiClient = {
  get: <T>(path: string, init?: RequestInit) =>
    request<T>(path, { ...init, method: "GET" }),
  post: <T>(path: string, body: unknown, init?: RequestInit) =>
    request<T>(path, { ...init, method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown, init?: RequestInit) =>
    request<T>(path, { ...init, method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown, init?: RequestInit) =>
    request<T>(path, { ...init, method: "PUT", body: JSON.stringify(body) }),
  delete: <T>(path: string, init?: RequestInit) =>
    request<T>(path, { ...init, method: "DELETE" }),
};

/**
 * Hilfsfunktion: Plain-Object zu URL-Query-String. Akzeptiert
 * jedes typisierte Interface, ueberspringt undefined/null-Werte.
 */
export function queryString<T extends object>(params: T): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    usp.append(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}
