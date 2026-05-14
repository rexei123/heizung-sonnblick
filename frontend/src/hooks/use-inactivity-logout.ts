"use client";

/**
 * Inaktivitaets-Logout-Hook (Sprint 9.17, AE-4).
 *
 * 15 Min ohne keydown/click/touchstart → automatischer Logout.
 * Bewusst KEIN mousemove (Lift-Off-Pause am Schreibtisch zaehlt nicht
 * als Aktivitaet) und KEIN visibilitychange (Background-Tab darf nicht
 * verlaengern).
 *
 * Multi-Tab via BroadcastChannel ``heizung-auth``: jede beobachtete
 * Aktivitaet ``postMessage('activity')`` an alle Tabs. So verlaengert
 * Aktivitaet in einem Tab den Timer in allen.
 *
 * Hart-Cut ohne Warn-Modal — Brief AE-4 explizit.
 */

import { useEffect, useRef } from "react";

const TIMEOUT_MS = 15 * 60 * 1000;
const CHANNEL_NAME = "heizung-auth";
const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = [
  "keydown",
  "click",
  "touchstart",
];

export function useInactivityLogout(
  enabled: boolean,
  onTimeout: () => void,
): void {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const channel =
      typeof BroadcastChannel === "function"
        ? new BroadcastChannel(CHANNEL_NAME)
        : null;
    channelRef.current = channel;

    const resetTimer = () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        onTimeout();
      }, TIMEOUT_MS);
    };

    const handleLocalActivity = () => {
      resetTimer();
      channel?.postMessage("activity");
    };

    const handleBroadcast = (e: MessageEvent) => {
      if (e.data === "activity") {
        // Aktivitaet aus anderem Tab: nur Timer zuruecksetzen, nicht
        // re-broadcasten (Endlosschleife).
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
          onTimeout();
        }, TIMEOUT_MS);
      }
    };

    for (const evt of ACTIVITY_EVENTS) {
      window.addEventListener(evt, handleLocalActivity, { passive: true });
    }
    channel?.addEventListener("message", handleBroadcast);
    resetTimer();

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      for (const evt of ACTIVITY_EVENTS) {
        window.removeEventListener(evt, handleLocalActivity);
      }
      channel?.removeEventListener("message", handleBroadcast);
      channel?.close();
    };
  }, [enabled, onTimeout]);
}
