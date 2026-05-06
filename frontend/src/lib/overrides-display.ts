/**
 * Wiederverwendbare Anzeige-Helper fuer Manual-Overrides
 * (Sprint 9.9 T8/T9). Werden aus zwei Stellen genutzt:
 *
 * - ``components/patterns/manual-override-panel.tsx`` (T8 - Bedien-UI)
 * - ``components/patterns/engine-decision-panel.tsx`` (T9 - Layer-3-Trace)
 */

import { useEffect, useState } from "react";

import type { OverrideSource } from "@/lib/api/types";

export const SOURCE_LABEL: Record<OverrideSource, string> = {
  device: "Drehknopf",
  frontend_4h: "Für 4 Stunden",
  frontend_midnight: "Bis Mitternacht",
  frontend_checkout: "Bis Check-Out",
};

export const SOURCE_ICON: Record<OverrideSource, string> = {
  device: "tune",
  frontend_4h: "schedule",
  frontend_midnight: "bedtime",
  frontend_checkout: "logout",
};

/**
 * Restzeit als formatierter String, Update jede Minute clientseitig.
 * Liefert z.B. "2h 15m", "45m", "abgelaufen", "3T 4h".
 */
export function useRemainingTime(expiresAt: string): string {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);

  const diffMs = new Date(expiresAt).getTime() - now;
  if (diffMs <= 0) return "abgelaufen";
  const totalMin = Math.floor(diffMs / 60_000);
  const hours = Math.floor(totalMin / 60);
  const mins = totalMin % 60;
  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    const remHours = hours % 24;
    return `${days}T ${remHours}h`;
  }
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}
