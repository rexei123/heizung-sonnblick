/**
 * Toast-Wrapper auf sonner (Sprint 13b.2 T0.6).
 *
 * Duenne Indirektion ueber die Library, damit eine spaetere Migration
 * (andere Lib, Repo-eigene Komponente, Style-Token-Wechsel) an einer
 * einzigen Stelle passiert. Alle Mutation-Feedbacks in 13b.2 und
 * spaeteren Sprints rufen ueber diesen Wrapper, NICHT direkt
 * ``sonner.toast.*``.
 *
 * Inline-Error-Banner-Pattern (ManualOverridePanel, DetachConfirm,
 * Login-Form) bleibt unveraendert — Migration optional in einem
 * Hygiene-Sprint, wenn Strategie das will.
 *
 * Toaster-Komponente sitzt in app/layout.tsx mit position="top-right",
 * richColors, closeButton.
 */

import { toast } from "sonner";

export function showSuccessToast(message: string): void {
  toast.success(message);
}

export function showErrorToast(message: string): void {
  toast.error(message);
}

export function showWarningToast(message: string): void {
  toast.warning(message);
}
