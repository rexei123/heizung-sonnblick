"use client";

/**
 * ScenarioCard (Sprint 9.16, AE-49).
 *
 * Hotelier-Ansicht eines einzelnen Szenarios mit GLOBAL-Toggle. Heute
 * nur summer_mode in Verwendung — die Komponente ist aber generisch
 * gebaut, damit Sprint 9.16b weitere Szenarien (Tagabsenkung, Wartung,
 * etc.) ohne UI-Refactor anfluegen kann.
 *
 * Toggle oeffnet einen ConfirmDialog (AE-5) — kein Inline-Toggle ohne
 * Bestaetigung. Aktivieren ist visuell als „destructive" markiert,
 * weil die Auswirkung systemweit ist; Deaktivieren ist „primary".
 */

import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Switch } from "@/components/ui/switch";

interface Props {
  icon: string;
  name: string;
  description: string | null;
  isActive: boolean;
  pending?: boolean;
  /** szenario-spezifische Texte fuer die Bestaetigungs-Dialoge. */
  activateConfirm: {
    title: string;
    message: string;
    confirmLabel?: string;
  };
  deactivateConfirm: {
    title: string;
    message: string;
    confirmLabel?: string;
  };
  onActivate: () => Promise<void>;
  onDeactivate: () => Promise<void>;
}

export function ScenarioCard({
  icon,
  name,
  description,
  isActive,
  pending = false,
  activateConfirm,
  deactivateConfirm,
  onActivate,
  onDeactivate,
}: Props) {
  const [pendingAction, setPendingAction] = useState<"activate" | "deactivate" | null>(
    null,
  );

  const confirm = pendingAction === "activate" ? activateConfirm : deactivateConfirm;
  const intent = pendingAction === "activate" ? "destructive" : "primary";

  const handleSwitchChange = (next: boolean) => {
    setPendingAction(next ? "activate" : "deactivate");
  };

  const handleConfirm = async () => {
    try {
      if (pendingAction === "activate") {
        await onActivate();
      } else if (pendingAction === "deactivate") {
        await onDeactivate();
      }
    } finally {
      setPendingAction(null);
    }
  };

  return (
    <>
      <Card className="flex flex-col">
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className="material-symbols-outlined text-primary"
                aria-hidden
                style={{ fontSize: 24 }}
              >
                {icon}
              </span>
              <CardTitle>{name}</CardTitle>
            </div>
            <StatusBadge isActive={isActive} />
          </div>
          {description ? (
            <CardDescription className="mt-2">{description}</CardDescription>
          ) : null}
        </CardHeader>
        <CardContent />
        <CardFooter className="mt-auto justify-between border-t border-border pt-3">
          <span className="text-xs text-text-tertiary">
            {isActive ? "Aktiv für gesamtes Hotel" : "Inaktiv"}
          </span>
          <Switch
            checked={isActive}
            disabled={pending || pendingAction !== null}
            onCheckedChange={handleSwitchChange}
            aria-label={isActive ? `${name} deaktivieren` : `${name} aktivieren`}
          />
        </CardFooter>
      </Card>

      <ConfirmDialog
        open={pendingAction !== null}
        title={confirm.title}
        message={confirm.message}
        confirmLabel={confirm.confirmLabel ?? "Bestätigen"}
        intent={intent}
        loading={pending}
        onConfirm={() => void handleConfirm()}
        onCancel={() => setPendingAction(null)}
      />
    </>
  );
}

function StatusBadge({ isActive }: { isActive: boolean }) {
  const cls = isActive
    ? "bg-success-soft text-success"
    : "bg-surface-alt text-text-tertiary";
  return (
    <span
      className={`px-2 py-0.5 rounded-sm text-xs font-medium ${cls}`}
      role="status"
    >
      {isActive ? "Aktiv" : "Inaktiv"}
    </span>
  );
}
