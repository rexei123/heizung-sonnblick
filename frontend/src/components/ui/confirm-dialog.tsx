"use client";

/**
 * ConfirmDialog — Modaler Bestaetigungs-Dialog mit Zweit-Klick-Schutz.
 *
 * Pflicht laut Design-Strategie 2.0.1 §6.1 fuer alle destruktiven Aktionen
 * (Loeschen, Deaktivieren, Archivieren).
 *
 * Sprint 9.8d T3: intern shadcn AlertDialog (Radix). Externe Props-API
 * unveraendert. Outside-Click ist via Radix-Default fuer alertdialog
 * geblockt. Waehrend `loading` ignoriert onOpenChange das Schliessen,
 * sodass weder ESC noch Cancel-Klick die laufende Mutation abbrechen.
 * Auto-Schliessen nach Action-Klick wird via event.preventDefault()
 * unterdrueckt — der Parent setzt `open` nach erfolgter Mutation.
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

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "./alert-dialog";
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
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !loading) onCancel();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{message}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel asChild>
            <Button variant="secondary" disabled={loading}>
              {cancelLabel}
            </Button>
          </AlertDialogCancel>
          <AlertDialogAction asChild>
            <Button
              variant={intent}
              loading={loading}
              onClick={(event) => {
                event.preventDefault();
                onConfirm();
              }}
            >
              {confirmLabel}
            </Button>
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
