/**
 * Frontend-Mapping fuer das Backend-``error_code``-Feld (B-Sprint13b2-4,
 * AE-59). Pendant zu ``backend/src/heizung/services/exceptions.py``.
 *
 * Backend-Schema seit B-Sprint13b2-4-Merge:
 *
 *     {"detail": "<message-string>", "error_code": "<CODE>"}
 *
 * App-weiter FastAPI-Handler (``heizung.main._lifecycle_error_handler``)
 * mapt:
 *
 *   - DeviceNotFound          -> 404 + DEVICE_NOT_FOUND
 *   - DeviceStateError        -> 409 + DEVICE_STATE_ERROR
 *   - PoolDeviceUnavailable   -> 409 + POOL_DEVICE_UNAVAILABLE
 *   - SelfReplacementError    -> 409 + SELF_REPLACEMENT_FORBIDDEN
 *
 * Scope-Grenze (Strategie-Setzung 2026-05-24): ausschliesslich
 * Lifecycle-Endpoints (Pool, Replace, Retire). Andere Endpoint-
 * Familien (overrides, auth, ...) liefern heute andere oder keine
 * ``error_code``-Strukturen — ``getErrorCode`` liefert ``null`` fuer
 * alle nicht-Lifecycle-Bodies. ``B-Sprint13b2-7`` konsolidiert
 * spaeter die Konventionen.
 *
 * Konsumenten heute:
 *   - components/patterns/replace-device-dialog.tsx
 *   - components/patterns/retire-device-dialog.tsx
 */

export const ERROR_CODES = {
  POOL_DEVICE_UNAVAILABLE: "POOL_DEVICE_UNAVAILABLE",
  DEVICE_STATE_ERROR: "DEVICE_STATE_ERROR",
  SELF_REPLACEMENT_FORBIDDEN: "SELF_REPLACEMENT_FORBIDDEN",
  DEVICE_NOT_FOUND: "DEVICE_NOT_FOUND",
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
