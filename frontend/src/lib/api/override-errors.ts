/**
 * Sprint 12b T3 — Typed Error-Mapping fuer Manual-Override-Endpoints.
 *
 * Backend (siehe ``backend/src/heizung/api/v1/overrides.py``) liefert
 * strukturierte Fehler-Details fuer drei Domain-Codes:
 *
 *   409 ``room_not_occupied``                  detail = {error, room_id}
 *   409 ``override_rejected_window_open``      detail = {error, zones[]}
 *   404 ``invalid_zone``                       detail = {error, zone_id, room_id}
 *
 * Plus String-detail-Faelle:
 *
 *   422 Setpoint half-step                     detail = "Setpoint muss in ganzen ..."
 *   422 FRONTEND_CHECKOUT ohne Belegung        detail = "„Bis Check-Out" funktioniert ..."
 *   422 ValueError aus service                 detail = str(e)
 *   404 unknown room                           detail = "room_id={X} existiert nicht"
 *
 * Diese Datei mappt sie auf user-facing deutsche Texte, ohne ID-Leak
 * (z.B. fremde zone_id wird nicht im 404-Text gezeigt).
 *
 * Brief: Strategie-Chat 2026-05-20, Sprint 12b T3.
 */

import type { ApiError } from "./types";

const ROOM_NOT_OCCUPIED = "Zimmer ist nicht belegt — Übersteuerung nicht möglich";
const WINDOW_OPEN = "Fenster ist offen — Übersteuerung nicht möglich";
const INVALID_ZONE = "Heizzone nicht gefunden";
const GENERIC_VALIDATION = "Anfrage ungültig";
const GENERIC_NOT_FOUND = "Nicht gefunden";
const GENERIC_CONFLICT = "Konflikt mit dem aktuellen Zustand";
const GENERIC_UNKNOWN = "Unbekannter Fehler";

function isApiError(err: unknown): err is ApiError {
  return (
    typeof err === "object" &&
    err !== null &&
    "status" in err &&
    typeof (err as { status: unknown }).status === "number"
  );
}

function extractErrorCode(detail: unknown): string | null {
  if (
    typeof detail === "object" &&
    detail !== null &&
    "error" in detail &&
    typeof (detail as { error: unknown }).error === "string"
  ) {
    return (detail as { error: string }).error;
  }
  return null;
}

function detailAsString(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (
    typeof detail === "object" &&
    detail !== null &&
    "error" in detail &&
    typeof (detail as { error: unknown }).error === "string"
  ) {
    // Strukturierte Detail-Objekte ohne dedizierten Mapping-Eintrag —
    // liefere den ``error``-Token als Hint statt rohem JSON.
    return (detail as { error: string }).error;
  }
  return null;
}

/**
 * Sprint 12b T3: einzige Public-Funktion. Nimmt einen unbekannten
 * Fehler (ApiError oder Error oder beliebig), liefert einen deutschen
 * user-facing Text. KEIN switch-case-Stringmatch im Aufrufer.
 */
export function mapOverrideError(err: unknown): string {
  if (!isApiError(err)) {
    return err instanceof Error ? err.message : GENERIC_UNKNOWN;
  }

  const code = extractErrorCode(err.detail);

  if (err.status === 409) {
    if (code === "room_not_occupied") return ROOM_NOT_OCCUPIED;
    if (code === "override_rejected_window_open") return WINDOW_OPEN;
    return detailAsString(err.detail) ?? GENERIC_CONFLICT;
  }

  if (err.status === 404) {
    if (code === "invalid_zone") return INVALID_ZONE;
    return detailAsString(err.detail) ?? GENERIC_NOT_FOUND;
  }

  if (err.status === 422) {
    return detailAsString(err.detail) ?? GENERIC_VALIDATION;
  }

  return detailAsString(err.detail) ?? GENERIC_UNKNOWN;
}
