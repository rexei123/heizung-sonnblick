"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDevices, useUpdateDevice } from "@/lib/api/hooks";
import type { ApiError, Device } from "@/lib/api/types";
import { formatDateTime, formatRelative } from "@/lib/format";

type SortMode = "status" | "label";

const STALE_HOURS_HIGH = 24;
const STALE_HOURS_LOW = 1;

function toMessage(e: unknown): string {
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}

/**
 * Fehlerstatus-Score absteigend: hoeher = problematischer.
 * - inaktiv: 3
 * - last_seen > 24h: 2
 * - last_seen > 1h: 1
 * - sonst (frisch): 0
 */
function statusScore(d: Device): number {
  if (!d.is_active) return 3;
  if (d.last_seen_at === null) return 2;
  const ageMs = Date.now() - new Date(d.last_seen_at).getTime();
  const ageH = ageMs / (1000 * 60 * 60);
  if (ageH > STALE_HOURS_HIGH) return 2;
  if (ageH > STALE_HOURS_LOW) return 1;
  return 0;
}

export default function DevicesPage() {
  return (
    <Suspense fallback={<DevicesSkeletonPage />}>
      <DevicesPageInner />
    </Suspense>
  );
}

function DevicesSkeletonPage() {
  return (
    <div className="p-6 max-w-content mx-auto">
      <DevicesSkeleton />
    </div>
  );
}

function DevicesPageInner() {
  const { data, isLoading, error, refetch, isFetching } = useDevices();
  const router = useRouter();
  const params = useSearchParams();
  const sort: SortMode = params?.get("sort") === "label" ? "label" : "status";

  const setSort = (next: SortMode) => {
    const usp = new URLSearchParams(params?.toString() ?? "");
    if (next === "status") usp.delete("sort");
    else usp.set("sort", next);
    const q = usp.toString();
    router.replace((q ? `/devices?${q}` : "/devices") as Route);
  };

  const sorted = (() => {
    if (!data) return [];
    const copy = [...data];
    if (sort === "label") {
      copy.sort((a, b) => (a.label ?? a.dev_eui).localeCompare(b.label ?? b.dev_eui));
    } else {
      copy.sort((a, b) => {
        const diff = statusScore(b) - statusScore(a);
        if (diff !== 0) return diff;
        return (a.label ?? a.dev_eui).localeCompare(b.label ?? b.dev_eui);
      });
    }
    return copy;
  })();

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Geräte</h1>
          <p className="text-sm text-text-secondary mt-1">
            Übersicht aller LoRaWAN-Geräte (Vicki, WT102, …) im System.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            icon="sort"
            onClick={() => setSort(sort === "status" ? "label" : "status")}
          >
            Sortierung: {sort === "status" ? "Fehlerstatus" : "Bezeichnung"}
          </Button>
          <Button
            variant="secondary"
            icon="refresh"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            {isFetching ? "Aktualisiere…" : "Aktualisieren"}
          </Button>
          <Button asChild variant="add" icon="add">
            <Link href="/devices/pair">Gerät hinzufügen</Link>
          </Button>
        </div>
      </header>

      {isLoading ? <DevicesSkeleton /> : null}

      {error ? (
        <div
          role="alert"
          className="p-4 rounded-md bg-danger-soft text-danger border border-danger/20"
        >
          <p className="font-medium">Geräteliste konnte nicht geladen werden.</p>
          <p className="text-sm mt-1 opacity-80">
            Bitte später erneut versuchen oder Verbindung zur API prüfen.
          </p>
        </div>
      ) : null}

      {!isLoading && !error && data?.length === 0 ? <EmptyState /> : null}

      {!isLoading && !error && data && data.length > 0 ? (
        <DevicesTable devices={sorted} />
      ) : null}
    </div>
  );
}

function DevicesTable({ devices }: { devices: Device[] }) {
  return (
    <div className="bg-surface rounded-lg border border-border overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-surface-alt text-text-secondary">
          <tr>
            <th className="text-left px-4 py-3 font-medium">Bezeichnung</th>
            <th className="text-left px-4 py-3 font-medium">DevEUI</th>
            <th className="text-left px-4 py-3 font-medium">Hersteller / Modell</th>
            <th className="text-left px-4 py-3 font-medium">Status</th>
            <th className="text-left px-4 py-3 font-medium">Zuletzt gesehen</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((d) => (
            <DeviceRow key={d.id} device={d} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeviceRow({ device: d }: { device: Device }) {
  return (
    <tr className="border-t border-border hover:bg-surface-alt transition-colors">
      <td className="px-4 py-3">
        <LabelCell device={d} />
      </td>
      <td className="px-4 py-3 font-mono text-xs text-text-tertiary">{d.dev_eui}</td>
      <td className="px-4 py-3 text-text-secondary">
        {d.vendor} / {d.model}
      </td>
      <td className="px-4 py-3">
        {d.is_active ? (
          <span className="px-2 py-0.5 rounded-sm bg-success-soft text-success text-xs font-medium">
            aktiv
          </span>
        ) : (
          <span className="px-2 py-0.5 rounded-sm bg-surface-alt text-text-tertiary text-xs font-medium">
            inaktiv
          </span>
        )}
      </td>
      <td
        className="px-4 py-3 text-text-secondary"
        title={formatDateTime(d.last_seen_at)}
      >
        {formatRelative(d.last_seen_at)}
      </td>
    </tr>
  );
}

/**
 * Inline-Edit fuer device.label (TA3, AE-43-Pattern aus Betterspace).
 * Klick aufs Label oeffnet Input, Enter speichert, Esc bricht ab.
 */
function LabelCell({ device: d }: { device: Device }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(d.label ?? "");
  const [error, setError] = useState<string | null>(null);
  const updateMut = useUpdateDevice(d.id);

  const display = d.label ?? `Device ${d.id}`;

  const save = async () => {
    const trimmed = draft.trim();
    const next = trimmed.length === 0 ? null : trimmed;
    if (next === (d.label ?? null)) {
      setEditing(false);
      return;
    }
    setError(null);
    try {
      await updateMut.mutateAsync({ label: next });
      setEditing(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setDraft(d.label ?? "");
      setError(null);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            onBlur={() => void save()}
            autoFocus
            disabled={updateMut.isPending}
            className="h-8 text-sm"
            aria-label="Bezeichnung bearbeiten"
          />
          {updateMut.isPending ? (
            <span
              className="material-symbols-outlined text-text-tertiary animate-spin"
              aria-hidden
              style={{ fontSize: 16 }}
            >
              progress_activity
            </span>
          ) : null}
        </div>
        {error ? (
          <span role="alert" className="text-xs text-error">
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Link
        href={`/devices/${d.id}` as Route}
        className="font-medium text-text-primary hover:text-primary"
      >
        {display}
      </Link>
      <button
        type="button"
        onClick={() => {
          setDraft(d.label ?? "");
          setEditing(true);
        }}
        className="text-text-tertiary hover:text-primary"
        aria-label="Bezeichnung bearbeiten"
        title="Bezeichnung bearbeiten"
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 16 }}>
          edit
        </span>
      </button>
    </div>
  );
}

function DevicesSkeleton() {
  return (
    <div className="bg-surface rounded-lg border border-border overflow-hidden">
      <div className="h-12 bg-surface-alt" />
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-14 border-t border-border flex items-center gap-4 px-4"
        >
          <div className="h-4 w-32 rounded bg-surface-alt animate-pulse" />
          <div className="h-3 w-40 rounded bg-surface-alt animate-pulse" />
          <div className="h-3 w-28 rounded bg-surface-alt animate-pulse" />
          <div className="h-5 w-12 rounded bg-surface-alt animate-pulse" />
          <div className="h-3 w-20 rounded bg-surface-alt animate-pulse ml-auto" />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="bg-surface rounded-lg border border-border p-8 text-center">
      <span
        className="material-symbols-outlined text-text-tertiary"
        style={{ fontSize: 48 }}
        aria-hidden
      >
        thermostat
      </span>
      <h2 className="mt-3 text-lg font-medium text-text-primary">Noch keine Geräte</h2>
      <p className="mt-1 text-sm text-text-secondary max-w-md mx-auto">
        Im System sind noch keine LoRaWAN-Geräte gepairt. Über „Gerät hinzufügen"
        oben rechts ein neues Gerät anlegen oder die RUNBOOK-Pairing-Anleitung
        (§10) befolgen.
      </p>
      <div className="mt-4">
        <Button asChild variant="add" icon="add">
          <Link href="/devices/pair">Gerät hinzufügen</Link>
        </Button>
      </div>
    </div>
  );
}
