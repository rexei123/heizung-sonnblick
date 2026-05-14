"use client";

/**
 * Generische Inline-Edit-Komponente (Sprint 9.14 T4, AE-46).
 *
 * Pattern aus ``app/devices/page.tsx`` ``LabelCell`` als wiederverwendbarer
 * Baustein extrahiert. ``LabelCell`` bleibt unangetastet, weil das
 * /devices-Edit-Verhalten (Edit-Button neben Link) sich von der hier
 * gewuenschten Direct-Click-Edit-Semantik unterscheidet.
 *
 * Verhalten:
 *  - Klick auf Display-Wert → Edit-Mode (Input mit autoFocus)
 *  - Enter / Tab / Blur → Validate → Save
 *  - Esc → Abbrechen (Wert wird zurueckgesetzt)
 *  - Validate-Fehler: Inline-Error, bleibt im Edit-Mode
 *  - Save-Fehler: Toast-Callback ruft Strategie auf, bleibt im Edit-Mode
 *
 * AE-3 (Auto-Save-on-Blur): kein expliziter Save-Button noetig.
 */

import { useState, type KeyboardEvent } from "react";
import type { ZodSchema } from "zod";

import { Input } from "@/components/ui/input";

type Variant = "text" | "number" | "time" | "decimal";

interface Props<T extends string | number> {
  value: T;
  variant: Variant;
  /** Optional: Zod-Schema fuer client-seitige Validierung vor Save. */
  validator?: ZodSchema<T>;
  /** Wird nach erfolgreicher Validierung mit dem geparsten Wert aufgerufen. */
  onSave: (next: T) => Promise<void>;
  /** Anzeige-Formatter (z.B. Decimal mit Einheit). */
  format?: (v: T) => string;
  /** Optional: Label fuer aria-label im Edit-Modus. */
  ariaLabel?: string;
  /** Optional: Toast-Callback fuer Save-Fehler. */
  onSaveError?: (message: string) => void;
}

function parseDraft<T extends string | number>(
  raw: string,
  variant: Variant,
): T | { error: string } {
  if (variant === "number") {
    const n = Number.parseInt(raw, 10);
    if (Number.isNaN(n)) return { error: "Ganze Zahl erwartet" };
    return n as T;
  }
  if (variant === "decimal") {
    // Dezimal-Trennzeichen: Komma → Punkt fuer Deutschland-Eingabe
    const normalized = raw.replace(",", ".");
    if (!/^-?\d+(\.\d+)?$/.test(normalized)) {
      return { error: "Dezimalzahl erwartet (z.B. 21.5)" };
    }
    return normalized as T;
  }
  if (variant === "time") {
    if (!/^([01]\d|2[0-3]):[0-5]\d(:\d{2})?$/.test(raw)) {
      return { error: "Format HH:MM erwartet" };
    }
    // Normalisiere auf HH:MM:SS fuer Backend (Pydantic time akzeptiert beides)
    const withSeconds = raw.length === 5 ? `${raw}:00` : raw;
    return withSeconds as T;
  }
  return raw as T;
}

export function InlineEditCell<T extends string | number>({
  value,
  variant,
  validator,
  onSave,
  format,
  ariaLabel,
  onSaveError,
}: Props<T>) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(() => String(value));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const display = format ? format(value) : String(value);

  const tryCommit = async () => {
    setError(null);
    const parsed = parseDraft<T>(draft, variant);
    if (typeof parsed === "object" && "error" in parsed) {
      setError(parsed.error);
      return;
    }
    if (validator) {
      const result = validator.safeParse(parsed);
      if (!result.success) {
        const msg = result.error.issues[0]?.message ?? "Ungueltiger Wert";
        setError(msg);
        return;
      }
    }
    if (parsed === value) {
      setEditing(false);
      return;
    }
    setPending(true);
    try {
      await onSave(parsed);
      setEditing(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Speichern fehlgeschlagen";
      onSaveError?.(msg);
      setError(msg);
    } finally {
      setPending(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      void tryCommit();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setDraft(String(value));
      setError(null);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            onBlur={() => void tryCommit()}
            autoFocus
            autoComplete="off"
            disabled={pending}
            type={variant === "time" ? "time" : "text"}
            inputMode={
              variant === "number" || variant === "decimal" ? "decimal" : undefined
            }
            aria-label={ariaLabel}
            aria-invalid={error !== null}
            className="h-8 text-sm w-32"
          />
          {pending ? (
            <span
              className="material-symbols-outlined text-text-tertiary animate-spin"
              aria-hidden
              style={{ fontSize: 16 }}
            >
              progress_activity
            </span>
          ) : null}
        </div>
        {error ? (
          <span role="alert" className="text-xs text-error">
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => {
        setDraft(String(value));
        setEditing(true);
        setError(null);
      }}
      className="text-left font-medium text-text-primary hover:text-primary"
      aria-label={ariaLabel ? `${ariaLabel} bearbeiten` : "Wert bearbeiten"}
    >
      {display}
    </button>
  );
}
