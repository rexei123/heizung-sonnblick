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

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";

import { InlineEditCell } from "@/components/inline-edit-cell";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useScenarios } from "@/lib/api/hooks-scenarios";
import {
  useGlobalRuleConfig,
  useUpdateGlobalRuleConfig,
} from "@/lib/api/hooks-rule-configs";
import type { RuleConfigGlobalUpdate } from "@/lib/api/types";
import { useAuth } from "@/contexts/auth-context";
import { fetchHausstandardNutzung } from "@/lib/api/hausstandard";
import { darfKonfigurationAendern } from "@/lib/auth/rechte";

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

/** „nicht festgelegt" statt einer Zahl, die niemand eingetragen hat. */
const NICHT_FESTGELEGT = "nicht festgelegt — Raumtyp entscheidet";

/**
 * Hüllt einen Formatierer so ein, dass ein leerer Wert als Satz erscheint.
 *
 * Der Umweg über ``""`` statt ``null`` ist die Form, die
 * ``InlineEditCell`` annimmt (``T extends string | number``) — und sie hat
 * den erwünschten Nebeneffekt, dass das Eingabefeld leer startet und nicht
 * mit einem Wert, den der Nutzer erst löschen müsste.
 */
function offenOder<T extends string | number>(
  format: (v: T) => string,
): (v: T | "") => string {
  // ``v`` ist hier entweder der leere String (Feld nicht festgelegt) oder
  // ein Wert des erwarteten Typs. Die Einengung geschieht zur Laufzeit
  // ueber den Vergleich; TypeScript kann sie ueber die Generik nicht
  // mitfuehren, weil ``""`` fuer ``T = number`` kein Teiltyp ist.
  return (v: T | "") => (v === "" ? NICHT_FESTGELEGT : format(v as T));
}

export default function TemperaturenZeitenPage() {
  const cfg = useGlobalRuleConfig();
  // Sprint 22 T4: `PATCH /rule-configs/global` ist `require_admin`
  // (`api/v1/rule_configs.py:79`). Die Werte bleiben lesbar — wer wissen
  // will, ab wann abgesenkt wird, soll nachsehen koennen.
  const { user } = useAuth();
  const darfAendern = darfKonfigurationAendern(user);
  const updateMut = useUpdateGlobalRuleConfig();
  const scenariosQ = useScenarios();
  const summerActive = (scenariosQ.data ?? []).some(
    (s) => s.code === "summer_mode" && s.current_global_assignment_active,
  );
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

  // Sprint 24d: wie viele Raumtypen und Zimmer diesen Wert wirklich nehmen.
  //
  // Ohne diese Zahl ist nicht zu sehen, ob eine Änderung hier 45 Zimmer
  // bewegt oder keines — und am 24.10.2026 war der Fall eindeutig: zwei
  // der Felder waren leer, und die Seite zeigte trotzdem Zahlen.
  const nutzung = useQuery({
    queryKey: ["hausstandard-nutzung"],
    queryFn: fetchHausstandardNutzung,
  });

  const hinweis = (feld: string, grund: string): string => {
    const n = nutzung.data?.find((x) => x.feld === feld);
    if (n === undefined) {
      return grund;
    }
    const teile = [grund];
    if (n.raumtypen_eigen > 0) {
      teile.push(
        `${n.raumtypen_nutzen} Raumtyp${n.raumtypen_nutzen === 1 ? "" : "en"} ` +
          `nehmen diesen Wert, ${n.raumtypen_eigen} ` +
          `${n.raumtypen_eigen === 1 ? "hat" : "haben"} einen eigenen.`,
      );
    } else {
      teile.push(`Alle ${n.raumtypen_nutzen} Raumtypen nehmen diesen Wert.`);
    }
    if (n.zimmer_eigen > 0) {
      teile.push(
        `${n.zimmer_eigen} Zimmer ${n.zimmer_eigen === 1 ? "hat" : "haben"} ` +
          "eine eigene Einstellung und bleiben unberührt.",
      );
    }
    return teile.join(" ");
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
          Hausstandard — gilt nur, wenn Zimmer oder Raumtyp nichts vorgeben
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          Die Regelung löst jeden Wert in der Reihenfolge{" "}
          <strong>Zimmer → Raumtyp → Hausstandard</strong> auf. Was hier
          steht, wirkt also nur dort, wo nichts Näheres gesagt ist. Engine
          übernimmt Änderungen beim nächsten Durchlauf (≤ 60 s).
        </p>
        {/* Sprint 24d: der Satz, der die Seite ehrlich macht. Bis zum
            24.10.2026 zeigten „Zimmer belegt" und „Zimmer frei" die Zahlen
            21,0 und 18,0, obwohl beide Felder **leer** sind — die Anzeige
            setzte einen Vorgabewert ein, der wie eine Einstellung aussah.
            Ein Speichern hätte ihn wirksam gemacht und jeden Raumtyp
            überstimmt (§5.77: ein Hinweis, der eine Wirkung behauptet, die
            es nicht gibt). */}
        <p className="text-sm text-text-secondary mt-2">
          Ein leeres Feld heißt <em>nicht festgelegt</em> und ist kein
          Versäumnis: dann entscheidet der Raumtyp. Wer es ausfüllt,
          übersteuert damit <strong>alle</strong> Raumtypen, die den Wert
          nicht selbst setzen.
        </p>
      </header>

      {summerActive ? (
        <div
          role="alert"
          className="mb-6 flex items-start gap-3 rounded-md border border-warning/30 bg-warning-soft text-warning px-4 py-3 text-sm"
        >
          <span
            className="material-symbols-outlined"
            aria-hidden
            style={{ fontSize: 20 }}
          >
            warning
          </span>
          <div className="flex-1">
            <p className="font-medium">Sommermodus aktiv.</p>
            <p className="opacity-90">
              Globale Werte wirken nicht — alle Räume sind auf Frostschutz.
            </p>
          </div>
          <Link
            href="/szenarien"
            className="font-medium underline hover:no-underline"
          >
            Verwalten →
          </Link>
        </div>
      ) : null}

      <Tabs defaultValue="zeiten" className="w-full">
        <TabsList>
          <TabsTrigger value="zeiten">Globale Zeiten</TabsTrigger>
          <TabsTrigger value="temperaturen">Globale Temperaturen</TabsTrigger>
        </TabsList>

        <TabsContent value="zeiten">
          <SettingsList>
            <SettingRow
              label="Nachtabsenkung Start"
              hint={hinweis("night_start", "Beginn des Nachtfensters (HH:MM, lokale Zeit).")}
            >
              <InlineEditCell
          readOnly={!darfAendern}
                value={data.night_start ?? ""}
                variant="time"
                validator={timeValidator}
                format={offenOder(formatTime)}
                ariaLabel="Nachtabsenkung Start"
                onSave={(v) => saveField({ night_start: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Nachtabsenkung Ende"
              hint={hinweis("night_end", "Ende des Nachtfensters. Über Mitternacht erlaubt.")}
            >
              <InlineEditCell
          readOnly={!darfAendern}
                value={data.night_end ?? ""}
                variant="time"
                validator={timeValidator}
                format={offenOder(formatTime)}
                ariaLabel="Nachtabsenkung Ende"
                onSave={(v) => saveField({ night_end: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Vorheizen vor Check-In"
              hint={hinweis("preheat_minutes_before_checkin", "Minuten vor Anreise, ab denen das Zimmer auf Belegt-Sollwert vorgeheizt wird.")}
            >
              <InlineEditCell
          readOnly={!darfAendern}
                value={data.preheat_minutes_before_checkin ?? ""}
                variant="number"
                validator={preheatValidator}
                format={offenOder(formatMinutes)}
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
              hint={hinweis("t_occupied", "Standard-Sollwert wenn Gast eingecheckt. Bereich 16–26 °C.")}
            >
              <InlineEditCell
          readOnly={!darfAendern}
                value={data.t_occupied ?? ""}
                variant="decimal"
                validator={tempValidator(16, 26)}
                format={offenOder(formatCelsius)}
                ariaLabel="Zimmer belegt"
                onSave={(v) => saveField({ t_occupied: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Zimmer frei"
              hint={hinweis("t_vacant", "Sollwert wenn Zimmer unbelegt. Bereich 10–22 °C.")}
            >
              <InlineEditCell
          readOnly={!darfAendern}
                value={data.t_vacant ?? ""}
                variant="decimal"
                validator={tempValidator(10, 22)}
                format={offenOder(formatCelsius)}
                ariaLabel="Zimmer frei"
                onSave={(v) => saveField({ t_vacant: v })}
                onSaveError={setErrorToast}
              />
            </SettingRow>
            <SettingRow
              label="Nachtabsenkung"
              hint={hinweis("t_night", "Sollwert im Nachtfenster. Bereich 14–22 °C.")}
            >
              <InlineEditCell
          readOnly={!darfAendern}
                value={data.t_night ?? ""}
                variant="decimal"
                validator={tempValidator(14, 22)}
                format={offenOder(formatCelsius)}
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
