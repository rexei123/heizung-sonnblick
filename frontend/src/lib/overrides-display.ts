/**
 * Wiederverwendbare Anzeige-Helper fuer Manual-Overrides
 * (Sprint 9.9 T8/T9). Werden aus zwei Stellen genutzt:
 *
 * - ``components/patterns/manual-override-panel.tsx`` (T8 - Bedien-UI)
 * - ``components/patterns/engine-decision-panel.tsx`` (T9 - Layer-3-Trace)
 */

import { useEffect, useState } from "react";

import type { OverrideSource } from "@/lib/api/types";

// Sprint 14d FU-6: Quelle (Gast/Mitarbeiter) als Klammer-Suffix sichtbar
// machen — vorher zeigte das Label nur Dauer/Mechanik. Heizzonen-Tab
// (ZoneCard-Banner) + Übersteuerung-Tab (SourceBadge / Confirm-Dialog /
// Historie-Zelle) + Engine-Decision-Panel (Layer-3-Trace) teilen sich diesen
// Map. Geräte-Seite hat einen eigenen ausführlicheren Map
// (``app/devices/[device_id]/page.tsx::OVERRIDE_SOURCE_LABEL``).
export const SOURCE_LABEL: Record<OverrideSource, string> = {
  // Sprint 20f-b: ``device_manual`` ist die **gemeldete** Drehung (0x28).
  // ``device`` war die aus einem Sollwert-Unterschied abgeleitete Vermutung —
  // sie wird seit 20f-b nicht mehr angelegt, weil sie Phantome erzeugt hat.
  // Das Etikett sagt das, damit eine Bestandszeile nicht wie ein Gastwunsch
  // gelesen wird.
  //
  // Fix A (20.10.2026): die Dauer steht **nicht** mehr im Etikett der
  // Gast-Drehung. Sie ist jetzt für Gast und Mitarbeiter-24-h dieselbe, und
  // eine Zahl im Etikett wäre eine zweite Wahrheit neben dem Restzeit-Feld
  // daneben (§5.77). ``frontend_4h`` und ``frontend_midnight`` behalten ihre
  // Zahl: sie sind historisch, und die Zahl ist der einzige Hinweis darauf,
  // was damals gegolten hat.
  device_manual: "Drehknopf (Gast)",
  device: "Drehknopf, vermutet (alt)",
  frontend_24h: "24 Stunden (Mitarbeiter)",
  frontend_checkout: "Bis Check-out (Mitarbeiter)",
  // Sprint 24d: die Dauer steht hier **nicht** im Etikett, weil sie je
  // Eintrag verschieden ist — sie steht als Endzeit daneben.
  frontend_bereich: "Allgemeinbereich (Mitarbeiter)",
  frontend_4h: "4 Stunden (Mitarbeiter, alt)",
  frontend_midnight: "Bis Mitternacht (Mitarbeiter, alt)",
};

export const SOURCE_ICON: Record<OverrideSource, string> = {
  device_manual: "tune",
  device: "tune",
  frontend_24h: "schedule",
  frontend_checkout: "logout",
  frontend_bereich: "storefront",
  frontend_4h: "schedule",
  frontend_midnight: "bedtime",
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
