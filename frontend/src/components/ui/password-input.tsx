"use client";

/**
 * PasswordInput — Sprint 9.17a T6 (B-9.17-8).
 *
 * Wrapper um <Input type="password">, mit Toggle-Button rechts im Input.
 * Material-Symbol visibility / visibility_off, ARIA-Label dynamisch.
 *
 * Verwendung: identisch zu <Input>, aber ohne `type`-Prop. Defaults zu
 * `type="password"`; Toggle wechselt nur zwischen `password` und `text`,
 * Layout / Höhe bleiben unverändert.
 */

import * as React from "react";

import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type PasswordInputProps = Omit<React.ComponentProps<typeof Input>, "type">;

export const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ className, ...props }, ref) => {
    const [visible, setVisible] = React.useState(false);
    return (
      <div className="relative">
        <Input
          ref={ref}
          type={visible ? "text" : "password"}
          className={cn("pr-10", className)}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          disabled={props.disabled}
          tabIndex={-1}
          aria-label={visible ? "Passwort verbergen" : "Passwort sichtbar machen"}
          className="absolute inset-y-0 right-0 flex items-center pr-3 text-text-secondary hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span
            className="material-symbols-outlined"
            aria-hidden
            style={{ fontSize: 20 }}
          >
            {visible ? "visibility_off" : "visibility"}
          </span>
        </button>
      </div>
    );
  },
);
PasswordInput.displayName = "PasswordInput";
