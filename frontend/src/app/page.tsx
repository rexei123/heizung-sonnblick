/**
 * Sprint-1-Platzhalter.
 *
 * Zeigt, dass Roboto, Material Symbols und die Design-Tokens funktionieren.
 * Wird in Sprint 2 durch das richtige AppShell-Layout (Sidebar 200px + Content) ersetzt.
 */
export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <section className="bg-surface rounded-lg shadow-md p-8 max-w-md w-full text-center">
        <div className="flex items-center justify-center gap-2 mb-4 text-primary">
          <span className="material-symbols-outlined" style={{ fontSize: 40 }} aria-hidden="true">
            thermostat
          </span>
          <h1 className="text-2xl font-medium text-text-primary">Heizung Sonnblick</h1>
        </div>
        <p className="text-text-secondary mb-6">
          Sprint 1 — Grundgerüst läuft. Das Admin-Interface entsteht in Sprint 2.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2 text-xs">
          <span className="px-2 py-1 rounded-sm bg-success-soft text-success font-medium">
            Heizung an
          </span>
          <span className="px-2 py-1 rounded-sm bg-warning-soft text-warning font-medium">
            Vorheizen
          </span>
          <span className="px-2 py-1 rounded-sm bg-danger-soft text-danger font-medium">
            Heizung aus
          </span>
          <span
            className="px-2 py-1 rounded-sm font-medium text-white"
            style={{ backgroundColor: "var(--color-heating-frost)" }}
          >
            Frostschutz
          </span>
        </div>
      </section>
    </main>
  );
}
