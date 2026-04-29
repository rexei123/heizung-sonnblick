"use client";

import type { Route } from "next";
import Link from "next/link";

import { useDevices } from "@/lib/api/hooks";
import { formatDateTime, formatRelative } from "@/lib/format";

export default function DevicesPage() {
  const { data, isLoading, error, refetch, isFetching } = useDevices();

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Geräte</h1>
          <p className="text-sm text-text-secondary mt-1">
            Übersicht aller LoRaWAN-Geräte (Vicki, WT102, …) im System.
          </p>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium border border-border bg-surface hover:bg-surface-alt disabled:opacity-50 transition-colors"
        >
          <span
            className="material-symbols-outlined"
            aria-hidden="true"
            style={{ fontSize: 18 }}
          >
            refresh
          </span>
          {isFetching ? "Aktualisiere…" : "Aktualisieren"}
        </button>
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
        <DevicesTable devices={data} />
      ) : null}
    </div>
  );
}

function DevicesTable({
  devices,
}: {
  devices: import("@/lib/api/types").Device[];
}) {
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
            <tr
              key={d.id}
              className="border-t border-border hover:bg-surface-alt transition-colors"
            >
              <td className="px-4 py-3">
                <Link
                  href={`/devices/${d.id}` as Route}
                  className="font-medium text-text-primary hover:text-primary"
                >
                  {d.label ?? `Device ${d.id}`}
                </Link>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-text-tertiary">
                {d.dev_eui}
              </td>
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
              <td className="px-4 py-3 text-text-secondary" title={formatDateTime(d.last_seen_at)}>
                {formatRelative(d.last_seen_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
        aria-hidden="true"
      >
        thermostat
      </span>
      <h2 className="mt-3 text-lg font-medium text-text-primary">
        Noch keine Geräte
      </h2>
      <p className="mt-1 text-sm text-text-secondary max-w-md mx-auto">
        Im System sind noch keine LoRaWAN-Geräte gepairt. Pairing-Anleitung siehe
        RUNBOOK §10 oder Sprint 6 Pairing-Plan.
      </p>
    </div>
  );
}
