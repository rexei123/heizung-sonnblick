"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Button — Design-Strategie 2.0.1 §6.1 konforme Button-Komponente.
 * cva-basiert (shadcn-Pattern, Sprint 9.8d).
 *
 * Variants:
 *   - "primary"     Brand-Rosé solid + weisser Text. Haupt-CTA pro Region (max. 1).
 *   - "add"         Gruen solid + weisser Text. AUSSCHLIESSLICH "Neu anlegen"-Aktionen.
 *                   Pflicht: Plus-Icon links (Material Symbol "add").
 *   - "secondary"   Outline neutral mit Border. Abgeleitete Aktionen
 *                   ("Abbrechen", "Vorschau", "Zurueck").
 *   - "destructive" Outline rot. Loeschen / Deaktivieren / Archivieren.
 *                   Strategie schreibt Confirm-Dialog vor — siehe ConfirmDialog.
 *   - "ghost"       Transparent + Primary-Text. Tertiaer.
 *
 * Sizes: sm (h-9 px-4) | md (h-10 px-5) | lg (h-11 px-6) — §6.1.
 *
 * Custom Props:
 *   - icon: Material-Symbol-Name, links vor Children.
 *   - iconSize: Icon-Groesse in px (default 18).
 *   - loading: disabled + zeigt "Bitte warten…" statt Children.
 *   - asChild: shadcn-Slot fuer Polymorphie. Deaktiviert Icon/Loading-Logic
 *              (Slot akzeptiert nur ein einzelnes Child).
 */

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-on-primary hover:bg-primary-hover active:bg-primary-active",
        add: "bg-add text-on-add hover:bg-add-hover",
        secondary:
          "bg-transparent text-text-primary border border-border hover:bg-surface-alt",
        destructive:
          "bg-transparent text-error border border-error hover:bg-error-soft",
        ghost: "bg-transparent text-primary hover:bg-primary-soft",
      },
      size: {
        sm: "h-9 px-4 text-sm",
        md: "h-10 px-5 text-base",
        lg: "h-11 px-6 text-base",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "sm",
    },
  },
);

export type ButtonVariant = NonNullable<VariantProps<typeof buttonVariants>["variant"]>;
export type ButtonSize = NonNullable<VariantProps<typeof buttonVariants>["size"]>;

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Material-Symbol-Name (z.B. "add", "delete"). Wird links vom Label gerendert. */
  icon?: string;
  /** Wenn true: ganzer Button blockiert + zeigt Spinner-Text. */
  loading?: boolean;
  /** Icon-Groesse in px, default 18. */
  iconSize?: number;
  /** shadcn-Slot fuer Polymorphie. Deaktiviert Icon/Loading-Logic. */
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      variant = "primary",
      size = "sm",
      icon,
      iconSize = 18,
      loading = false,
      asChild = false,
      disabled,
      className,
      children,
      type,
      ...rest
    },
    ref,
  ) {
    const isDisabled = disabled || loading;
    const classes = cn(buttonVariants({ variant, size }), className);

    if (asChild) {
      return (
        <Slot ref={ref} className={classes} {...rest}>
          {children}
        </Slot>
      );
    }

    return (
      <button
        ref={ref}
        type={type ?? "button"}
        disabled={isDisabled}
        className={classes}
        {...rest}
      >
        {icon ? (
          <span
            className="material-symbols-outlined"
            style={{ fontSize: iconSize }}
            aria-hidden
          >
            {icon}
          </span>
        ) : null}
        {loading ? "Bitte warten…" : children}
      </button>
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
