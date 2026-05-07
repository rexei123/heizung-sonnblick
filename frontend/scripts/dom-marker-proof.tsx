/**
 * Sprint 9.10 T4 — DOM-Marker-Beweis (Lesson 9.8d).
 *
 * Rendert ``WindowOpenIndicator`` via react-dom/server und prueft,
 * dass das Marker-Attribut data-testid="window-open-indicator" im
 * gerenderten HTML auftaucht (positiver Pfad) bzw. nicht (negativer
 * Pfad — extractWindowOpenSince liefert null, der Marker wird nicht
 * gerendert).
 *
 * Aufruf: ./node_modules/.bin/tsx scripts/dom-marker-proof.tsx
 */

import { renderToString } from "react-dom/server";
import { createElement } from "react";

import {
  type EvalGroupLike,
  WindowOpenIndicator,
  extractWindowOpenSince,
} from "../src/components/patterns/engine-window-indicator";

const MARKER = 'data-testid="window-open-indicator"';

function assert(cond: unknown, msg: string): void {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
  console.log("OK:  ", msg);
}

// ---- Positive case: open_zones populated -> marker present ----
const groupOpen: EvalGroupLike = {
  entries: [
    {
      time: "2026-05-07T10:00:00Z",
      room_id: 1,
      evaluation_id: "ev-1",
      layer: "window_safety",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "10",
      reason: "window_open",
      details: {
        open_zones: [{ zone_id: 1, reading_at: "2026-05-07T09:42:00Z" }],
        occupancy_state: "occupied",
      },
    },
  ],
};

const since = extractWindowOpenSince(groupOpen);
assert(since !== null, "extractWindowOpenSince returns truthy for open zones");
assert(
  since && since.since === "2026-05-07T09:42:00Z",
  "since == earliest reading_at",
);

const htmlOpen = renderToString(
  createElement(WindowOpenIndicator, { since: since!.since }),
);
console.log("\nPositive HTML:\n  ", htmlOpen, "\n");
assert(htmlOpen.includes(MARKER), `positive render contains ${MARKER}`);
assert(htmlOpen.includes(">window<"), "positive render uses 'window' glyph (Static-Cut-Fallback)");
assert(
  htmlOpen.includes("Fenster offen seit"),
  "positive render hat de-AT Tooltip 'Fenster offen seit'",
);

// ---- Negative case 1: open_zones empty -> extractor returns null ----
const groupClosed: EvalGroupLike = {
  entries: [
    {
      ...groupOpen.entries[0],
      details: { open_zones: [], occupancy_state: "occupied" },
    },
  ],
};
assert(
  extractWindowOpenSince(groupClosed) === null,
  "extractWindowOpenSince returns null for empty open_zones",
);

// ---- Negative case 2: no window_safety layer at all -> null ----
const groupNoLayer4: EvalGroupLike = {
  entries: [{ ...groupOpen.entries[0], layer: "base_target" }],
};
assert(
  extractWindowOpenSince(groupNoLayer4) === null,
  "extractWindowOpenSince returns null when window_safety layer absent",
);

// ---- Negative case 3: details.open_zones missing -> null ----
const groupNoOpenZones: EvalGroupLike = {
  entries: [
    {
      ...groupOpen.entries[0],
      details: { occupancy_state: "vacant" },
    },
  ],
};
assert(
  extractWindowOpenSince(groupNoOpenZones) === null,
  "extractWindowOpenSince returns null when open_zones field missing",
);

console.log("\nALL DOM-marker assertions passed.");
