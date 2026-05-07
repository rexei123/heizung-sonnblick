/**
 * Sprint 9.10 T4 — Window-Indikator-Subkomponente.
 *
 * Eigene Datei, weil das Proof-Script (scripts/dom-marker-proof.mjs)
 * nur diese Funktionen ohne TanStack-Query-Hook-Plumbing importieren
 * koennen muss.
 *
 * Static-Cut-Hinweis: ``sensor_window_open`` ist im aktuellen
 * material-symbols-outlined-v332.woff2-Subset NICHT enthalten
 * (per fonttools-Inspektion). Fallback ``window`` ist enthalten.
 * Backlog: Static-Cut um sensor_window_open ergaenzen.
 */

import * as React from "react";

import type { EventLogEntry } from "../../lib/api/types";

// Sprint 9.10 T4: ``React``-Import nur, damit das DOM-Marker-Proof-Script
// (scripts/dom-marker-proof.tsx) mit dem klassischen JSX-Transform laeuft.
// Next.js mit automatic transform tree-shaket ihn weg — kein Bundle-Effekt.
void React;

export interface EvalGroupLike {
  entries: EventLogEntry[];
}

/**
 * Extrahiert das fruehste reading_at aus open_zones der window_safety-
 * Schicht der juengsten Evaluation. Liefert null, wenn keine offenen
 * Zonen oder Layer 4 nicht vorhanden ist.
 */
export function extractWindowOpenSince(
  group: EvalGroupLike,
): { since: string } | null {
  const wsEntry = group.entries.find((e) => e.layer === "window_safety");
  if (!wsEntry || !wsEntry.details) return null;
  const zones = wsEntry.details["open_zones"];
  if (!Array.isArray(zones) || zones.length === 0) return null;
  const timestamps = zones
    .map((z) =>
      z && typeof z === "object" && "reading_at" in z && typeof z.reading_at === "string"
        ? z.reading_at
        : null,
    )
    .filter((t): t is string => t !== null);
  if (timestamps.length === 0) return null;
  const earliest = timestamps.reduce((a, b) => (a < b ? a : b));
  return { since: earliest };
}

export function WindowOpenIndicator({ since }: { since: string }) {
  const sinceLocal = new Date(since).toLocaleTimeString("de-AT", {
    hour: "2-digit",
    minute: "2-digit",
  });
  const tooltip = `Fenster offen seit ${sinceLocal}`;
  return (
    <span
      data-testid="window-open-indicator"
      className="material-symbols-outlined text-primary"
      style={{ fontSize: 28 }}
      title={tooltip}
      aria-label={tooltip}
      role="img"
    >
      window
    </span>
  );
}
