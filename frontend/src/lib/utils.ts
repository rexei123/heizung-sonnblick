import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * cn() — kombiniert clsx (bedingte Klassen) mit tailwind-merge (löst Tailwind-Konflikte).
 *
 * Wird von shadcn/ui-Komponenten erwartet, die in Sprint 2 hinzukommen.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
