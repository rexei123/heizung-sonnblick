import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Badge — shadcn-Standard-Primitive (Sprint 13b.2 T2).
 *
 * Konsistent mit dialog.tsx + select.tsx: shadcn-Default-Tokens
 * (``bg-primary`` etc.) gemapped via CSS-Variables in globals.css,
 * KEINE heizung-Design-System-Tokens (Strategie-Setzung 2026-05-23,
 * Phase-0-Update Audit 4). Design-System-Token-Migration ist Phase-7-
 * Thema, hier bewusst akzeptierter Drift.
 *
 * Varianten: ``default`` (Brand-Rosé), ``secondary`` (neutral hellgrau),
 * ``destructive`` (rot), ``outline`` (transparent + Border).
 *
 * Erster Konsument (Sprint 13b.2 T6): Reserve-Tag mit ``secondary`` an
 * Pool-Devices in /devices-Liste.
 */

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
