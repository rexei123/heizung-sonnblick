"use client";

/**
 * /szenarien — Hotelier-UI fuer Szenarien (Sprint 9.16, AE-48).
 *
 * Heute nur ein Szenario in Verwendung: ``summer_mode``. Layout ist
 * bereits als responsives Grid vorbereitet; weitere Szenarien aus
 * Sprint 9.16b benoetigen keinen UI-Refactor.
 */

import { useState } from "react";

import { ScenarioCard } from "@/components/scenario-card";
import {
  useActivateScenario,
  useDeactivateScenario,
  useScenarios,
} from "@/lib/api/hooks-scenarios";
import type { Scenario } from "@/lib/api/types";

const SCENARIO_PRESENTATION: Record<
  string,
  { icon: string; activateConfirm: ConfirmCopy; deactivateConfirm: ConfirmCopy }
> = {
  summer_mode: {
    icon: "wb_sunny",
    activateConfirm: {
      title: "Sommermodus aktivieren?",
      message:
        "Alle Räume werden auf Frostschutz gefahren. Heizthermostate funktionieren nicht, bis Sommermodus wieder deaktiviert wird.",
      confirmLabel: "Sommermodus aktivieren",
    },
    deactivateConfirm: {
      title: "Sommermodus deaktivieren?",
      message:
        "Heizpipeline läuft wieder normal mit allen globalen und raumtypspezifischen Regeln.",
      confirmLabel: "Sommermodus deaktivieren",
    },
  },
};

interface ConfirmCopy {
  title: string;
  message: string;
  confirmLabel?: string;
}

const DEFAULT_PRESENTATION = {
  icon: "movie",
  activateConfirm: {
    title: "Szenario aktivieren?",
    message: "Bitte bestätigen.",
  } satisfies ConfirmCopy,
  deactivateConfirm: {
    title: "Szenario deaktivieren?",
    message: "Bitte bestätigen.",
  } satisfies ConfirmCopy,
};

export default function SzenarienPage() {
  const scenariosQ = useScenarios();
  const [toast, setToast] = useState<string | null>(null);
  const [errorToast, setErrorToast] = useState<string | null>(null);

  const showSuccess = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">Szenarien</h1>
        <p className="text-sm text-text-secondary mt-1">
          Sondersituationen für den Heizbetrieb. Aktivierungen wirken hotelweit
          beim nächsten Engine-Tick (≤ 60 s).
        </p>
      </header>

      {scenariosQ.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-40 rounded-lg bg-surface-alt animate-pulse"
            />
          ))}
        </div>
      ) : scenariosQ.error ? (
        <div
          role="alert"
          className="p-4 rounded-md bg-danger-soft text-danger border border-danger/20"
        >
          <p className="font-medium">Szenarien konnten nicht geladen werden.</p>
          <p className="text-sm mt-1 opacity-80">
            Bitte später erneut versuchen oder Verbindung zur API prüfen.
          </p>
        </div>
      ) : !scenariosQ.data || scenariosQ.data.length === 0 ? (
        <div className="bg-surface border border-border rounded-lg p-8 text-center">
          <p className="text-sm text-text-secondary">
            Aktuell sind keine Szenarien definiert.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {scenariosQ.data.map((s) => (
            <ScenarioCardSlot
              key={s.id}
              scenario={s}
              onSuccess={showSuccess}
              onError={setErrorToast}
            />
          ))}
        </div>
      )}

      {toast ? <ToastSuccess message={toast} /> : null}
      {errorToast ? (
        <ToastError message={errorToast} onClose={() => setErrorToast(null)} />
      ) : null}
    </div>
  );
}

function ScenarioCardSlot({
  scenario,
  onSuccess,
  onError,
}: {
  scenario: Scenario;
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const activate = useActivateScenario(scenario.code);
  const deactivate = useDeactivateScenario(scenario.code);
  const presentation =
    SCENARIO_PRESENTATION[scenario.code] ?? DEFAULT_PRESENTATION;

  const handleActivate = async () => {
    try {
      await activate.mutateAsync();
      onSuccess(`${scenario.name} aktiviert — Engine übernimmt in ≤ 60 s.`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Aktivieren fehlgeschlagen";
      onError(msg);
    }
  };

  const handleDeactivate = async () => {
    try {
      await deactivate.mutateAsync();
      onSuccess(`${scenario.name} deaktiviert — Engine übernimmt in ≤ 60 s.`);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Deaktivieren fehlgeschlagen";
      onError(msg);
    }
  };

  return (
    <ScenarioCard
      icon={presentation.icon}
      name={scenario.name}
      description={scenario.description}
      isActive={scenario.current_global_assignment_active}
      pending={activate.isPending || deactivate.isPending}
      activateConfirm={presentation.activateConfirm}
      deactivateConfirm={presentation.deactivateConfirm}
      onActivate={handleActivate}
      onDeactivate={handleDeactivate}
    />
  );
}

function ToastSuccess({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="fixed bottom-6 right-6 z-50 max-w-sm rounded-md bg-success-soft text-success border border-success/20 px-4 py-3 shadow-md text-sm"
    >
      <div className="flex items-start gap-2">
        <span
          className="material-symbols-outlined"
          aria-hidden
          style={{ fontSize: 18 }}
        >
          check_circle
        </span>
        <span>{message}</span>
      </div>
    </div>
  );
}

function ToastError({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div
      role="alert"
      className="fixed bottom-6 right-6 z-50 max-w-sm rounded-md bg-danger-soft text-danger border border-danger/20 px-4 py-3 shadow-md text-sm"
    >
      <div className="flex items-start gap-2">
        <span
          className="material-symbols-outlined"
          aria-hidden
          style={{ fontSize: 18 }}
        >
          cancel
        </span>
        <div className="flex-1">{message}</div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fehlermeldung schließen"
          className="text-danger/70 hover:text-danger"
        >
          ×
        </button>
      </div>
    </div>
  );
}
