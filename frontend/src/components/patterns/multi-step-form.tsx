"use client";

/**
 * MultiStepForm — generischer Wizard mit Stepper, Zurueck/Weiter/Bestaetigen.
 * Sprint 9.13a (TA0). Wiederverwendbar (z.B. NextAuth-Onboarding 9.17).
 *
 * `validate` blockt Weiter-Button bei false. Schritte links vom aktuellen
 * sind via Stepper-Klick erreichbar (vorwaerts nur ueber Weiter).
 * `loading` waehrend onComplete blockt Stepper + Buttons.
 */

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

export interface MultiStepFormStep {
  id: string;
  label: string;
  component: ReactNode;
  /** False blockt Weiter/Bestaetigen. Default: true. */
  valid?: boolean;
}

export interface MultiStepFormProps {
  steps: MultiStepFormStep[];
  onComplete: () => Promise<void> | void;
  onCancel?: () => void;
  /** Wird vom Parent gesetzt, falls onComplete async ist. */
  loading?: boolean;
  /** Optionale Fehlermeldung unter dem Footer (z.B. nach onComplete-Fail). */
  error?: string | null;
}

export function MultiStepForm({
  steps,
  onComplete,
  onCancel,
  loading = false,
  error = null,
}: MultiStepFormProps) {
  const [active, setActive] = useState(0);
  const isLast = active === steps.length - 1;
  const current = steps[active];
  const canProceed = current?.valid !== false;

  const goTo = (index: number) => {
    if (loading) return;
    if (index <= active) setActive(index);
  };

  const next = () => {
    if (!canProceed || loading) return;
    if (isLast) {
      void onComplete();
      return;
    }
    setActive((i) => Math.min(i + 1, steps.length - 1));
  };

  return (
    <div className="space-y-6">
      <ol className="flex items-center gap-2 text-sm" aria-label="Wizard-Schritte">
        {steps.map((step, i) => {
          const done = i < active;
          const isCurrent = i === active;
          const clickable = i < active && !loading;
          return (
            <li key={step.id} className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => goTo(i)}
                disabled={!clickable}
                className={`flex items-center gap-2 ${
                  clickable ? "cursor-pointer hover:opacity-80" : "cursor-default"
                }`}
                aria-current={isCurrent ? "step" : undefined}
              >
                <span
                  className="material-symbols-outlined"
                  aria-hidden
                  style={{
                    fontSize: 22,
                    color: done || isCurrent ? "var(--color-primary)" : undefined,
                  }}
                >
                  {done ? "check_circle" : "radio_button_unchecked"}
                </span>
                <span
                  className={
                    isCurrent
                      ? "font-medium text-text-primary"
                      : done
                        ? "text-text-primary"
                        : "text-text-tertiary"
                  }
                >
                  {step.label}
                </span>
              </button>
              {i < steps.length - 1 ? (
                <span aria-hidden className="text-text-tertiary">
                  ›
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>

      <div className="bg-surface border border-border rounded-md p-5 min-h-[180px]">
        {current?.component}
      </div>

      {error ? (
        <div
          role="alert"
          className="p-3 rounded-md bg-error-soft text-error border border-error/20 text-sm"
        >
          {error}
        </div>
      ) : null}

      <div className="flex items-center justify-between">
        <div>
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel} disabled={loading}>
              Abbrechen
            </Button>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {active > 0 ? (
            <Button
              variant="secondary"
              onClick={() => setActive((i) => Math.max(0, i - 1))}
              disabled={loading}
              icon="chevron_left"
            >
              Zurück
            </Button>
          ) : null}
          <Button
            variant="primary"
            onClick={next}
            disabled={!canProceed}
            loading={loading && isLast}
            icon={isLast ? "check" : "chevron_right"}
          >
            {isLast ? "Bestätigen" : "Weiter"}
          </Button>
        </div>
      </div>
    </div>
  );
}
