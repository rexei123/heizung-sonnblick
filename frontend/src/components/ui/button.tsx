"use client";

/**
 * Button — Design-Strategie 2.0.1 §6.1 konforme Button-Komponente.
 *
 * Varianten:
 *   - "primary"     Rosé, weisser Text. Haupt-CTA pro Region (max. 1).
 *   - "add"         Gruen, weisser Text. AUSSCHLIESSLICH "Neu anlegen"-Aktionen.
 *                   Pflicht: Plus-Icon links (Material Symbol "add").
 *   - "secondary"   Outline, neutraler Rahmen. Abgeleitete Aktionen
 *                   ("Abbrechen", "Vorschau", "Zurueck").
 *   - "destructive" Outline rot. Loeschen / Deaktivieren / Archivieren.
 *                   Strategie schreibt Confirm-Dialog vor — siehe ConfirmDialog.
 *   - "ghost"       Transparent, nur Text in Primary. Tertiaer.
 *
 * Groessen: sm (8/16 px Padding), md (12/20 px), lg (14/24 px) — §6.1.
 */

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

export type ButtonVariant = "primary" | "add" | "secondary" | "destructive" | "ghost";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Material-Symbol-Name (z.B. "add", "delete"). Wird links vom Label gerendert. */
  icon?: string;
  /** Wenn true: ganzer Button blockiert + zeigt Spinner-Text. */
  loading?: boolean;
  /** Icon-Groesse in px, default 18. */
  iconSize?: number;
  children?: ReactNode;
}

const variantClass: Record<ButtonVariant, string> = {
  primary:
    "bg-primary text-on-primary hover:bg-primary-hover active:bg-primary-active disabled:opacity-50",
  add: "bg-add text-on-add hover:bg-add-hover disabled:opacity-50",
  secondary:
    "bg-transparent text-text-primary border border-border hover:bg-surface-alt disabled:opacity-50",
  destructive:
    "bg-transparent text-error border border-error hover:bg-error-soft disabled:opacity-50",
  ghost: "bg-transparent text-primary hover:bg-primary-soft disabled:opacity-50",
};

const sizeClass: Record<ButtonSize, string> = {
  sm: "px-4 py-2 text-sm",
  md: "px-5 py-3 text-base",
  lg: "px-6 py-3.5 text-base",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "sm",
    icon,
    iconSize = 18,
    loading = false,
    disabled,
    className = "",
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading;
  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      className={`inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors focus-visible:outline-none ${variantClass[variant]} ${sizeClass[size]} ${className}`}
      {...rest}
    >
      {icon ? (
        <span className="material-symbols-outlined" style={{ fontSize: iconSize }} aria-hidden>
          {icon}
        </span>
      ) : null}
      {loading ? "Bitte warten…" : children}
    </button>
  );
});
