/**
 * Typed Error-Mapping fuer Manual-Override-Endpoints (Sprint 12b T3,
 * konsolidiert in B-Sprint13b2-7 auf AE-59).
 *
 * Backend (``backend/src/heizung/api/v1/overrides.py``) liefert seit
 * B-Sprint13b2-7 das AE-59-Schema: top-level ``error_code`` neben
 * String-``detail`` und domaenen-spezifischen Extra-Feldern:
 *
 *   404 INVALID_ZONE                     {detail, error_code, zone_id, room_id}
 *   409 ROOM_NOT_OCCUPIED                {detail, error_code, room_id}
 *   409 ROOM_OVERRIDE_BLOCKED            {detail, error_code, room_id}
 *   409 OVERRIDE_REJECTED_WINDOW_OPEN    {detail, error_code, zones[]}
 *
 * Plus String-detail-Faelle (kein ``error_code``):
 *
 *   422 Setpoint half-step               detail = "Setpoint muss in ganzen ..."
 *   422 FRONTEND_CHECKOUT ohne Belegung  detail = "„Bis Check-Out" funktioniert ..."
 *   422 ValueError aus service           detail = str(e)
 *   404 unknown room                     detail = "room_id={X} existiert nicht"
 *
 * Diese Datei mappt die Codes auf user-facing deutsche Texte, ohne
 * ID-Leak (z.B. fremde zone_id wird nicht im 404-Text gezeigt). Diskriminator-
 * Extraktion delegiert an ``getErrorCode`` aus ``error-codes.ts`` (zentrale
 * Type-Guard-Quelle).
 */

import { ERROR_CODES, getErrorCode } from "./error-codes";
import type { ApiError } from "./types";

const ROOM_NOT_OCCUPIED = "Zimmer ist nicht belegt — Übersteuerung nicht möglich";
const WINDOW_OPEN = "Fenster ist offen — Übersteuerung nicht möglich";
const INVALID_ZONE = "Heizzone nicht gefunden";
const ROOM_OVERRIDE_BLOCKED = "Übersteuerung für dieses Zimmer gesperrt";
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

function detailAsString(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  return null;
}

/**
 * Sprint 12b T3: einzige Public-Funktion. Nimmt einen unbekannten
 * Fehler (ApiError oder Error oder beliebig), liefert einen deutschen
 * user-facing Text. KEIN switch-case-Stringmatch im Aufrufer.
 *
 * B-Sprint13b2-7: Diskriminator kommt aus dem top-level ``error_code``
 * (via ``getErrorCode`` aus ``error-codes.ts``). Fallback fuer Endpoints
 * ohne ``error_code`` (422-Setpoint-Validation, 404-unknown-room): heute
 * String-detail.
 */
export function mapOverrideError(err: unknown): string {
  if (!isApiError(err)) {
    return err instanceof Error ? err.message : GENERIC_UNKNOWN;
  }

  const code = getErrorCode(err);

  switch (code) {
    case ERROR_CODES.ROOM_NOT_OCCUPIED:
      return ROOM_NOT_OCCUPIED;
    case ERROR_CODES.OVERRIDE_REJECTED_WINDOW_OPEN:
      return WINDOW_OPEN;
    case ERROR_CODES.INVALID_ZONE:
      return INVALID_ZONE;
    case ERROR_CODES.ROOM_OVERRIDE_BLOCKED:
      return ROOM_OVERRIDE_BLOCKED;
  }

  // Kein bekannter Override-Code -> Fallback auf String-detail oder generischen
  // Status-Code-Text. Fuer 422-Setpoint-Validation und 404-unknown-room (beide
  // haben kein error_code) wird so der Backend-Text durchgereicht.
  if (err.status === 409) {
    return detailAsString(err.detail) ?? GENERIC_CONFLICT;
  }
  if (err.status === 404) {
    return detailAsString(err.detail) ?? GENERIC_NOT_FOUND;
  }
  if (err.status === 422) {
    return detailAsString(err.detail) ?? GENERIC_VALIDATION;
  }
  return detailAsString(err.detail) ?? GENERIC_UNKNOWN;
}
