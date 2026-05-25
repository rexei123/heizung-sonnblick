/**
 * Frontend-Mapping fuer das Backend-``error_code``-Feld (B-Sprint13b2-4,
 * B-Sprint13b2-7, AE-59).
 *
 * Pendant zu ``backend/src/heizung/services/exceptions.py`` (Lifecycle)
 * + ``backend/src/heizung/services/override_service.py`` (Override-Domain).
 *
 * Backend-Schema:
 *
 *     {"detail": "<message-string>", "error_code": "<CODE>", ...extras}
 *
 * App-weite FastAPI-Handler (``heizung.main``):
 *
 * Lifecycle-Domain (``LifecycleError``-Hierarchie):
 *   - DeviceNotFound                -> 404 + DEVICE_NOT_FOUND
 *   - DeviceStateError              -> 409 + DEVICE_STATE_ERROR
 *   - PoolDeviceUnavailable         -> 409 + POOL_DEVICE_UNAVAILABLE
 *   - SelfReplacementError          -> 409 + SELF_REPLACEMENT_FORBIDDEN
 *
 * Override-Domain (``OverrideError``-Hierarchie, B-Sprint13b2-7):
 *   - InvalidZoneError              -> 404 + INVALID_ZONE
 *   - RoomNotOccupiedError          -> 409 + ROOM_NOT_OCCUPIED
 *   - RoomOverrideBlockedError      -> 409 + ROOM_OVERRIDE_BLOCKED
 *   - OverrideRejectedWindowOpenError -> 409 + OVERRIDE_REJECTED_WINDOW_OPEN
 *
 * Scope (Strategie-Setzung 2026-05-24, erweitert B-Sprint13b2-7):
 * alle API-Endpoints mit Mehrfach-Subtypen pro HTTP-Status liefern
 * top-level ``error_code``. ``getErrorCode`` ist die zentrale
 * Type-Guard-Funktion fuer alle Konsumenten.
 *
 * Konsumenten heute:
 *   - components/patterns/replace-device-dialog.tsx (Lifecycle)
 *   - components/patterns/retire-device-dialog.tsx (Lifecycle)
 *   - lib/api/override-errors.ts (Override-Domain)
 */

export const ERROR_CODES = {
  // Lifecycle-Domain (B-Sprint13b2-4)
  POOL_DEVICE_UNAVAILABLE: "POOL_DEVICE_UNAVAILABLE",
  DEVICE_STATE_ERROR: "DEVICE_STATE_ERROR",
  SELF_REPLACEMENT_FORBIDDEN: "SELF_REPLACEMENT_FORBIDDEN",
  DEVICE_NOT_FOUND: "DEVICE_NOT_FOUND",
  // Override-Domain (B-Sprint13b2-7)
  INVALID_ZONE: "INVALID_ZONE",
  ROOM_NOT_OCCUPIED: "ROOM_NOT_OCCUPIED",
  ROOM_OVERRIDE_BLOCKED: "ROOM_OVERRIDE_BLOCKED",
  OVERRIDE_REJECTED_WINDOW_OPEN: "OVERRIDE_REJECTED_WINDOW_OPEN",
} as const;

export type ErrorCode = (typeof ERROR_CODES)[keyof typeof ERROR_CODES];

/**
 * Form des Backend-Response-Bodies bei einem ``LifecycleError`` (siehe
 * App-weiter Handler in ``heizung.main``). ``error_code`` ist optional,
 * weil FastAPI-Default-Pfade (Validation-Error, generische
 * ``HTTPException``-Aufrufe ohne unseren Handler) das Feld NICHT
 * setzen.
 *
 * ``ErrorCode | string`` als Union: bekannte Codes sind exhaustiv
 * typisiert, unbekannte Server-Codes (kuenftige Erweiterungen,
 * Repo-Drift) brechen den Type nicht — der ``getErrorCode``-Type-Guard
 * verengt strikt auf das ``ERROR_CODES``-Set.
 */
export interface ApiErrorBody {
  detail: string;
  error_code?: ErrorCode | string;
}

/**
 * Extrahiert einen bekannten ``ErrorCode`` aus einem beliebigen
 * Object, das ein ``error_code``-Feld traegt (typischerweise
 * ``ApiError`` aus ``client.ts``, das von ``lib/api/client.ts`` mit
 * dem Backend-Body angereichert wird).
 *
 * Liefert ``null`` (nicht ``undefined``) — konsistent zur
 * ``useZoneOverride``-Konvention in ``hooks-overrides.ts``.
 *
 * Strikte Validierung: liefert nur dann ein Ergebnis, wenn
 * ``error_code`` als String vorliegt UND zu einem bekannten
 * ``ERROR_CODES``-Wert passt. Unbekannte Strings -> ``null`` (Caller
 * faellt in den generischen Fehler-Pfad).
 */
export function getErrorCode(response: unknown): ErrorCode | null {
  if (
    typeof response === "object" &&
    response !== null &&
    "error_code" in response
  ) {
    const code = (response as { error_code?: unknown }).error_code;
    if (typeof code === "string") {
      const known = Object.values(ERROR_CODES) as string[];
      if (known.includes(code)) {
        return code as ErrorCode;
      }
    }
  }
  return null;
}
