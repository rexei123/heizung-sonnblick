import type { Route } from "next";
import Link from "next/link";

/**
 * Saison-Stub (Sprint 9.17a B-9.17-6).
 *
 * Ergänzt den EmptyState-Stub um einen sichtbaren Verweis auf den
 * bereits verfügbaren Sommermodus-Soforttoggle unter /szenarien, damit
 * User bei Cutover-Tests nicht annehmen, die Funktion fehle komplett.
 */
export default function SaisonPage() {
  return (
    <div className="p-6 max-w-content mx-auto">
      <div className="flex flex-col items-center text-center py-16">
        <span
          className="material-symbols-outlined text-primary mb-4"
          aria-hidden
          style={{ fontSize: 64 }}
        >
          wb_sunny
        </span>
        <h1 className="text-2xl font-medium text-text-primary">Saison</h1>
        <p className="mt-2 text-sm text-text-secondary max-w-md">
          Sommer-/Winter-Umschaltung und Saisonzeiten. Sommermodus-Soforttoggle
          bereits unter{" "}
          <Link href={"/szenarien" as Route} className="text-primary hover:underline">
            /szenarien
          </Link>{" "}
          verfügbar.
        </p>
        <span className="mt-6 inline-flex items-center gap-1 px-3 py-1 rounded-full bg-primary-soft text-primary text-xs font-medium">
          In Vorbereitung
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
