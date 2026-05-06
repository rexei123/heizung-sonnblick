"use client";

/**
 * ManualOverridePanel - Rezeptions-UI fuer Manual-Override (Sprint 9.9 T8).
 *
 * Eine zusammenhaengende Card mit zwei Modi:
 *  - aktiver Override vorhanden: Setpoint + Quelle + Restzeit + "Aufheben"
 *  - kein aktiver: Formular zum Anlegen
 *
 * Plus eine zweite Card mit der Historie (limit 20, "Mehr laden").
 */

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useCreateRoomOverride,
  useRevokeOverride,
  useRoomOverrides,
} from "@/lib/api/hooks-overrides";
import type {
  ApiError,
  FrontendOverrideSource,
  ManualOverride,
  OverrideSource,
} from "@/lib/api/types";
import { SOURCE_ICON, SOURCE_LABEL, useRemainingTime } from "@/lib/overrides-display";

const FRONTEND_SOURCES: FrontendOverrideSource[] = [
  "frontend_4h",
  "frontend_midnight",
  "frontend_checkout",
];

const HISTORY_PAGE_SIZE = 20;

interface Props {
  roomId: number;
}

export function ManualOverridePanel({ roomId }: Props) {
  const [historyLimit, setHistoryLimit] = useState(HISTORY_PAGE_SIZE);
  const list = useRoomOverrides(roomId, {
    limit: historyLimit,
    include_expired: true,
  });

  const items = useMemo(() => list.data ?? [], [list.data]);
  const active = useActiveOverride(items);

  return (
    <div className="space-y-6">
      <div className="bg-surface border border-border rounded-md p-5">
        <h2 className="text-lg font-medium text-text-primary mb-4">
          Manuelle Übersteuerung
        </h2>
        {active ? (
          <ActiveOverrideCard roomId={roomId} override={active} />
        ) : (
          <CreateOverrideForm roomId={roomId} />
        )}
      </div>

      <div className="bg-surface border border-border rounded-md p-5">
        <h2 className="text-lg font-medium text-text-primary mb-4">
          Historie
        </h2>
        <HistoryTable items={items} loading={list.isLoading} />
        {items.length >= historyLimit ? (
          <div className="mt-3 text-center">
            <Button
              variant="ghost"
              onClick={() => setHistoryLimit((n) => n + HISTORY_PAGE_SIZE)}
            >
              Mehr laden
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aktiver Override
// ---------------------------------------------------------------------------

function ActiveOverrideCard({
  roomId,
  override,
}: {
  roomId: number;
  override: ManualOverride;
}) {
  const revokeMut = useRevokeOverride(roomId);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remaining = useRemainingTime(override.expires_at);

  const performRevoke = async () => {
    setError(null);
    try {
      await revokeMut.mutateAsync(override.id);
      setConfirmRevoke(false);
    } catch (e) {
      setError(toMessage(e));
      setConfirmRevoke(false);
    }
  };

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-medium text-text-primary tabular-nums">
              {override.setpoint}
            </span>
            <span className="text-xl text-text-secondary">°C</span>
          </div>
          <SourceBadge source={override.source} className="mt-2" />
          <p className="text-sm text-text-secondary mt-3">
            Läuft ab in <span className="font-medium">{remaining}</span> ·{" "}
            {new Date(override.expires_at).toLocaleString("de-AT")}
          </p>
          {override.reason ? (
            <p className="text-sm text-text-secondary mt-1">
              Grund: {override.reason}
            </p>
          ) : null}
        </div>
        <Button
          variant="destructive"
          icon="cancel"
          onClick={() => setConfirmRevoke(true)}
          disabled={revokeMut.isPending}
        >
          Übersteuerung aufheben
        </Button>
      </div>

      {error ? <p className="text-sm text-error mt-3">{error}</p> : null}

      <ConfirmDialog
        open={confirmRevoke}
        title="Übersteuerung aufheben?"
        message={`Setpoint ${override.setpoint} °C (${SOURCE_LABEL[override.source]}) wird sofort beendet. Engine fällt auf den regulären Setpoint zurück.`}
        confirmLabel="Aufheben"
        loading={revokeMut.isPending}
        onConfirm={performRevoke}
        onCancel={() => setConfirmRevoke(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create-Formular
// ---------------------------------------------------------------------------

function CreateOverrideForm({ roomId }: { roomId: number }) {
  const createMut = useCreateRoomOverride(roomId);
  const [setpoint, setSetpoint] = useState("21.0");
  const [source, setSource] = useState<FrontendOverrideSource>("frontend_4h");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await createMut.mutateAsync({
        setpoint,
        source,
        reason: reason.trim() ? reason.trim() : null,
      });
      setReason("");
    } catch (err) {
      setError(toMessage(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-text-secondary">
        Aktuell keine manuelle Übersteuerung. Engine arbeitet nach den regulären
        Regeln.
      </p>

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium text-text-primary mb-1 block">
            Setpoint (°C)
          </span>
          <Input
            type="number"
            step="0.5"
            min="5"
            max="30"
            value={setpoint}
            onChange={(e) => setSetpoint(e.target.value)}
            required
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-text-primary mb-1 block">
            Dauer
          </span>
          <Select
            value={source}
            onValueChange={(v) => setSource(v as FrontendOverrideSource)}
          >
            <SelectTrigger>
              <SelectValue placeholder="Bitte wählen" />
            </SelectTrigger>
            <SelectContent>
              {FRONTEND_SOURCES.map((s) => (
                <SelectItem key={s} value={s}>
                  {SOURCE_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>

      <label className="block">
        <span className="text-sm font-medium text-text-primary mb-1 block">
          Grund (optional)
        </span>
        <Input
          type="text"
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="z.B. Wunsch des Gastes"
        />
      </label>

      {error ? <p className="text-sm text-error">{error}</p> : null}

      <div>
        <Button type="submit" variant="primary" loading={createMut.isPending}>
          Anwenden
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Historie
// ---------------------------------------------------------------------------

function HistoryTable({
  items,
  loading,
}: {
  items: ManualOverride[];
  loading: boolean;
}) {
  if (loading) {
    return <p className="text-sm text-text-secondary">Lade…</p>;
  }
  if (items.length === 0) {
    return (
      <p className="text-sm text-text-secondary italic">
        Noch keine Übersteuerungen für dieses Zimmer.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-text-tertiary border-b border-border">
            <th className="py-2 pr-4 font-medium">Zeitpunkt</th>
            <th className="py-2 pr-4 font-medium">Setpoint</th>
            <th className="py-2 pr-4 font-medium">Quelle</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Grund</th>
          </tr>
        </thead>
        <tbody>
          {items.map((o) => (
            <tr key={o.id} className="border-b border-border last:border-b-0">
              <td className="py-2 pr-4 text-text-secondary tabular-nums">
                {new Date(o.created_at).toLocaleString("de-AT")}
              </td>
              <td className="py-2 pr-4 font-medium text-text-primary tabular-nums">
                {o.setpoint} °C
              </td>
              <td className="py-2 pr-4">
                <SourceBadge source={o.source} />
              </td>
              <td className="py-2 pr-4">
                <StatusBadge override={o} />
              </td>
              <td className="py-2 pr-4 text-text-secondary">
                {o.reason ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subkomponenten
// ---------------------------------------------------------------------------

function SourceBadge({
  source,
  className,
}: {
  source: OverrideSource;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-alt text-xs text-text-primary ${className ?? ""}`}
    >
      <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
        {SOURCE_ICON[source]}
      </span>
      {SOURCE_LABEL[source]}
    </span>
  );
}

function StatusBadge({ override }: { override: ManualOverride }) {
  if (override.revoked_at !== null) {
    return (
      <span className="text-xs text-text-tertiary">manuell aufgehoben</span>
    );
  }
  if (new Date(override.expires_at) <= new Date()) {
    return <span className="text-xs text-text-tertiary">abgelaufen</span>;
  }
  return (
    <span className="text-xs text-primary font-medium">aktiv</span>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function useActiveOverride(items: ManualOverride[]): ManualOverride | null {
  // TanStack-Query liefert die Liste zeitlich sortiert (created_at DESC).
  // Aktiv = nicht revoked + expires_at in der Zukunft.
  const now = Date.now();
  return (
    items.find(
      (o) =>
        o.revoked_at === null && new Date(o.expires_at).getTime() > now,
    ) ?? null
  );
}

function toMessage(err: unknown): string {
  const e = err as ApiError | Error;
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
