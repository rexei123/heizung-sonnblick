/**
 * EmptyState — generischer Stub fuer noch nicht implementierte Routen
 * (Sprint 9.13b TB0). Wird von 8 Sidebar-Stub-Pages wiederverwendet.
 */

import type { Route } from "next";
import Link from "next/link";

export interface EmptyStateProps {
  title: string;
  description: string;
  plannedSprint: string;
  /** Material-Symbol-Name (z.B. "schedule"). */
  icon: string;
}

export function EmptyState({ title, description, plannedSprint, icon }: EmptyStateProps) {
  return (
    <div className="p-6 max-w-content mx-auto">
      <div className="flex flex-col items-center text-center py-16">
        <span
          className="material-symbols-outlined text-primary mb-4"
          aria-hidden
          style={{ fontSize: 64 }}
        >
          {icon}
        </span>
        <h1 className="text-2xl font-medium text-text-primary">{title}</h1>
        <p className="mt-2 text-sm text-text-secondary max-w-md">{description}</p>
        <span className="mt-6 inline-flex items-center gap-1 px-3 py-1 rounded-full bg-primary-soft text-primary text-xs font-medium">
          Kommt in {plannedSprint}
        </span>
        <Link
          href={"/" as Route}
          className="mt-8 inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
            arrow_back
          </span>
          Zur Übersicht
        </Link>
      </div>
    </div>
  );
}
