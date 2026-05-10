"use client";

/**
 * ConfirmDialog — Modaler Bestaetigungs-Dialog mit Zweit-Klick-Schutz.
 *
 * Pflicht laut Design-Strategie 2.0.1 §6.1 fuer alle destruktiven Aktionen
 * (Loeschen, Deaktivieren, Archivieren).
 *
 * Nutzung:
 *   <ConfirmDialog
 *     open={…}
 *     title="Raumtyp loeschen?"
 *     message="Der Raumtyp wird endgueltig entfernt."
 *     confirmLabel="Endgueltig loeschen"
 *     onConfirm={handleDelete}
 *     onCancel={() => setOpen(false)}
 *     loading={mut.isPending}
 *   />
 */

import { useEffect, useRef } from "react";

import { Button } from "./button";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** "destructive" (Standard) oder "primary" fuer nicht-zerstoererische Bestaetigungen. */
  intent?: "destructive" | "primary";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Bestätigen",
  cancelLabel = "Abbrechen",
  intent = "destructive",
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Fokus-Trap-Light: beim Öffnen Fokus auf "Abbrechen" — verhindert
  // versehentliches Triggern via Enter.
  useEffect(() => {
    if (open) {
      const id = window.setTimeout(() => cancelRef.current?.focus(), 50);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [open]);

  // Esc schliesst.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, loading, onCancel]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-4"
      onClick={(e) => {
        // Klick auf Backdrop = Abbrechen (nicht waehrend Loading).
        if (e.target === e.currentTarget && !loading) onCancel();
      }}
    >
      <div className="bg-surface rounded-lg shadow-lg max-w-md w-full p-6 space-y-4">
        <h2 id="confirm-dialog-title" className="text-lg font-semibold text-text-primary">
          {title}
        </h2>
        <p className="text-base text-text-secondary">{message}</p>
        <div className="flex justify-end gap-2 pt-2">
          <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={intent} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
