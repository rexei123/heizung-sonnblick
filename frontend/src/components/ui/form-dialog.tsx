"use client";

/**
 * FormDialog — Modaler Dialog fuer Formulare mit Body-Slot (Sprint 13b.2).
 *
 * Erweitert das Pattern von `ConfirmDialog`: statt fixem Message-Text einen
 * `children`-Slot fuer beliebige Form-Inhalte (Dropdown, Reason-Select,
 * Warning-Box, etc.). Basiert auf shadcn `Dialog` (Radix), nicht
 * `AlertDialog` — Form-Interaktion erlaubt ESC + Outside-Click zum
 * Abbrechen, wird aber waehrend `isPending` geblockt (Loading-Schutz
 * analog ConfirmDialog).
 *
 * Auto-Schliessen nach Confirm-Klick wird via `event.preventDefault()`
 * unterdrueckt — der Parent setzt `open=false` nach erfolgter Mutation.
 *
 * Konsumenten (Sprint 13b.2): ReplaceDeviceDialog (Pool-Dropdown im Body),
 * RetireDeviceDialog (Reason-Dropdown + optionale Warning-Box).
 */

import type * as React from "react";

import { Button } from "./button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./dialog";

export interface FormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void | Promise<void>;
  confirmDisabled?: boolean;
  /** "default" entspricht Button-Variant `primary`. */
  confirmVariant?: "default" | "destructive";
  isPending?: boolean;
  children: React.ReactNode;
}

export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "Abbrechen",
  onConfirm,
  confirmDisabled = false,
  confirmVariant = "default",
  isPending = false,
  children,
}: FormDialogProps) {
  const buttonVariant = confirmVariant === "destructive" ? "destructive" : "primary";

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent
        onEscapeKeyDown={(event) => {
          if (isPending) event.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>

        {children}

        <DialogFooter>
          <Button
            variant="secondary"
            disabled={isPending}
            onClick={() => onOpenChange(false)}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={buttonVariant}
            disabled={confirmDisabled}
            loading={isPending}
            onClick={(event) => {
              event.preventDefault();
              void onConfirm();
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
