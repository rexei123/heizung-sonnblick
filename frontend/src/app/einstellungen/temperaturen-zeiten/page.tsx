"use client";

/**
 * Globale Temperaturen + Zeiten UI (Sprint 9.14, AE-46).
 *
 * Hotelier-Editor fuer die 6 Engine-gelesenen rule_config-Felder
 * (Scope=GLOBAL). Zwei Tabs: Zeiten / Temperaturen. Inline-Edit per
 * Klick auf den Wert, Auto-Save-on-Blur (kein Save-Button).
 *
 * Backend-Pfad: GET/PATCH /api/v1/rule-configs/global.
 * Engine uebernimmt neue Werte beim naechsten Beat-Tick (<= 60 s).
 */

import { useState } from "react";
import { z } from "zod";

import { InlineEditCell } from "@/components/inline-edit-cell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useGlobalRuleConfig,
  useUpdateGlobalRuleConfig,
} from "@/lib/api/hooks-rule-configs";
import type { RuleConfigGlobalUpdate } from "@/lib/api/types";

const tempValidator = (min: number, max: number) =>
  z.string().refine(
    (raw) => {
      const n = Number.parseFloat(raw);
      return Number.isFinite(n) && n >= min && n <= max;
    },
    { message: `Bereich ${min.toFixed(1)}–${max.toFixed(1)} °C` },
  );

const timeValidator = z
  .string()
  .regex(/^([01]\d|2[0-3]):[0-5]\d(:\d{2})?$/, "Format HH:MM erwartet");

const preheatValidator = z
  .number()
  .int("Ganze Minuten erwartet")
  .min(0, "Bereich 0–240 Minuten")
  .max(240, "Bereich 0–240 Minuten");

function formatCelsius(v: string): string {
  return `${v} °C`;
}

function formatTime(v: string): string {
  // Backend liefert HH:MM:SS; fuer Anzeige auf HH:MM kuerzen.
  return v.length >= 5 ? v.slice(0, 5) : v;
}

function formatMinutes(v: number): string {
  return `${v} Min`;
}

export default function TemperaturenZeitenPage() {
  const cfg = useGlobalRuleConfig();
  const updateMut = useUpdateGlobalRuleConfig();
  const [toast, setToast] = useState<string | null>(null);
  const [errorToast, setErrorToast] = useState<string | null>(null);

  const showSuccess = () => {
    setToast("Gespeichert — Engine übernimmt in ≤ 60 s");
    setTimeout(() => setToast(null), 3500);
  };

  const saveField = async (payload: RuleConfigGlobalUpdate): Promise<void> => {
    setErrorToast(null);
    await updateMut.mutateAsync(payload);
    showSuccess();
  };

  if (cfg.isLoading) {
    return (
      <div className="p-6 max-w-content mx-auto">
        <h1 className="text-2xl font-medium text-text-primary">
          Temperaturen & Zeiten
        </h1>
        <div className="mt-6 h-64 rounded-lg bg-surface-alt animate-pulse" />
      </div>
    );
  }

  if (cfg.error || !cfg.data) {
    return (
      <div className="p-6 max-w-content mx-auto">
        <h1 className="text-2xl font-medium text-text-primary">
          Temperaturen & Zeiten
        </h1>
        <div
          role="alert"
          className="mt-4 p-4 rounded-md bg-danger-soft text-danger border border-danger/20"
        >
          <p className="font-medium">Konfiguration konnte nicht geladen werden.</p>
          <p className="text-sm mt-1 opacity-80">
            Bitte später erneut versuchen oder Verbindung zur API prüfen.
          </p>
        </div>
      </div>
    );
  }

  const data = cfg.data;

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">
          Temperaturen & Zeiten
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          Globale Sollwerte und Zeitfenster der Heizungssteuerung. Engine
          übernimmt Änderungen beim nächsten Tick (≤ 60 s).
        </p>
      </header>

      <Tabs defaultValue="zeiten" className="w-full">
        <TabsList>
          <TabsTrigger value="zeiten">Globale Zeiten</TabsTrigger>
          <TabsTrigger value="temperaturen">Globale Temperaturen</TabsTrigger>
        </TabsList>

        <TabsContent value="zeiten">
          <SettingsList>
            <SettingRow
              label="Nachtabsenkung Start"
              hint="Beginn des Nachtfensters (HH:MM, lokale Zeit)."
            >
              <InlineEditCell
                value={data.night_start ?? "00:00:00"}
                variant="time"
                validator={timeValidator}
                format={formatTime}
                ariaLabel="Nachtabsenkung Start"
                onSave={(v) => saveField({ night_start: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Nachtabsenkung Ende"
              hint="Ende des Nachtfensters. Über Mitternacht erlaubt."
            >
              <InlineEditCell
                value={data.night_end ?? "06:00:00"}
                variant="time"
                validator={timeValidator}
                format={formatTime}
                ariaLabel="Nachtabsenkung Ende"
                onSave={(v) => saveField({ night_end: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Vorheizen vor Check-In"
              hint="Minuten vor Anreise, ab denen das Zimmer auf Belegt-Sollwert vorgeheizt wird."
            >
              <InlineEditCell
                value={data.preheat_minutes_before_checkin ?? 90}
                variant="number"
                validator={preheatValidator}
                format={formatMinutes}
                ariaLabel="Vorheizen vor Check-In"
                onSave={(v) =>
                  saveField({ preheat_minutes_before_checkin: v as number })
                }
                onSaveError={setErrorToast}
              />
            </SettingRow>
          </SettingsList>
        </TabsContent>

        <TabsContent value="temperaturen">
          <SettingsList>
            <SettingRow
              label="Zimmer belegt"
              hint="Standard-Sollwert wenn Gast eingecheckt. Bereich 16–26 °C."
            >
              <InlineEditCell
                value={data.t_occupied ?? "21.0"}
                variant="decimal"
                validator={tempValidator(16, 26)}
                format={formatCelsius}
                ariaLabel="Zimmer belegt"
                onSave={(v) => saveField({ t_occupied: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Zimmer frei"
              hint="Sollwert wenn Zimmer unbelegt. Bereich 10–22 °C."
            >
              <InlineEditCell
                value={data.t_vacant ?? "18.0"}
                variant="decimal"
                validator={tempValidator(10, 22)}
                format={formatCelsius}
                ariaLabel="Zimmer frei"
                onSave={(v) => saveField({ t_vacant: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Nachtabsenkung"
              hint="Sollwert im Nachtfenster bei belegtem Zimmer. Bereich 14–22 °C."
            >
              <InlineEditCell
                value={data.t_night ?? "19.0"}
                variant="decimal"
                validator={tempValidator(14, 22)}
                format={formatCelsius}
                ariaLabel="Nachtabsenkung"
                onSave={(v) => saveField({ t_night: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
          </SettingsList>
        </TabsContent>
      </Tabs>

      {toast ? <ToastSuccess message={toast} /> : null}
      {errorToast ? (
        <ToastError message={errorToast} onClose={() => setErrorToast(null)} />
      ) : null}
    </div>
  );
}

function SettingsList({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-border rounded-lg divide-y divide-border">
      {children}
    </div>
  );
}

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6 px-4 py-3">
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-text-primary">{label}</div>
        <div className="text-xs text-text-tertiary mt-0.5">{hint}</div>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
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

function ToastError({
  message,
  onClose,
}: {
  message: string;
  onClose: () => void;
}) {
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
