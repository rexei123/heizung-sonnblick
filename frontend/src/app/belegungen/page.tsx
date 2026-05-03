"use client";

/**
 * Belegungs-Liste (Sprint 8.11, Sprint 8.15 Design-Fixes).
 * Filter: heute / 7 Tage / alle. Anlegen + Storno.
 */

import { useState } from "react";

import { OccupancyForm } from "@/components/patterns/occupancy-form";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useCancelOccupancy, useCreateOccupancy, useOccupancies } from "@/lib/api/hooks-occupancies";
import { useRooms } from "@/lib/api/hooks-rooms";
import type { ApiError, Occupancy, OccupancyCreate } from "@/lib/api/types";

type Range = "today" | "next7" | "all";

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

function rangeBounds(r: Range): { from?: string; to?: string } {
  const now = new Date();
  if (r === "today") {
    const from = startOfDay(now).toISOString();
    const to = new Date(startOfDay(now).getTime() + 24 * 3600 * 1000).toISOString();
    return { from, to };
  }
  if (r === "next7") {
    const from = startOfDay(now).toISOString();
    const to = new Date(startOfDay(now).getTime() + 7 * 24 * 3600 * 1000).toISOString();
    return { from, to };
  }
  return {};
}

export default function BelegungenPage() {
  const [range, setRange] = useState<Range>("next7");
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState<Occupancy | null>(null);

  const list = useOccupancies({ ...rangeBounds(range), active: true, limit: 200 });
  const rooms = useRooms({ limit: 1000 });
  const createMut = useCreateOccupancy();
  const cancelMut = useCancelOccupancy();

  const handleCreate = async (payload: OccupancyCreate) => {
    setError(null);
    try {
      await createMut.mutateAsync(payload);
      setShowCreate(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const performCancel = async () => {
    if (!confirmCancel) return;
    setError(null);
    try {
      await cancelMut.mutateAsync(confirmCancel.id);
      setConfirmCancel(null);
    } catch (e) {
      setError(toMessage(e));
      setConfirmCancel(null);
    }
  };

  const roomNumber = (id: number): string => {
    const r = (rooms.data ?? []).find((x) => x.id === id);
    return r ? r.number : `#${id}`;
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Belegungen</h1>
          <p className="text-sm text-text-secondary mt-1">
            {list.data?.length ?? 0} aktive Belegung(en) in diesem Zeitraum.
          </p>
        </div>
        {showCreate ? (
          <Button variant="secondary" onClick={() => setShowCreate(false)}>
            Abbrechen
          </Button>
        ) : (
          <Button
            variant="add"
            icon="add"
            onClick={() => {
              setError(null);
              setShowCreate(true);
            }}
          >
            Neue Belegung
          </Button>
        )}
      </header>

      {showCreate ? (
        <div className="bg-surface border border-border rounded-md p-5 mb-6">
          <h2 className="text-lg font-medium text-text-primary mb-4">Neue Belegung</h2>
          <OccupancyForm
            onSubmit={handleCreate}
            onCancel={() => setShowCreate(false)}
            submitting={createMut.isPending}
            error={error}
          />
        </div>
      ) : null}

      <div className="bg-surface border border-border rounded-md p-3 mb-4 flex gap-2">
        {(["today", "next7", "all"] as const).map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRange(r)}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              range === r
                ? "bg-primary text-on-primary"
                : "text-text-secondary hover:bg-surface-alt"
            }`}
          >
            {r === "today" ? "Heute" : r === "next7" ? "Nächste 7 Tage" : "Alle"}
          </button>
        ))}
      </div>

      <List
        list={list.data ?? []}
        loading={list.isLoading}
        isError={list.isError}
        roomNumber={roomNumber}
        onCancel={(o) => setConfirmCancel(o)}
        cancelPending={cancelMut.isPending}
      />

      <ConfirmDialog
        open={confirmCancel !== null}
        title="Belegung stornieren?"
        message={
          confirmCancel
            ? `Belegung für Zimmer ${roomNumber(confirmCancel.room_id)} (Anreise ${new Date(confirmCancel.check_in).toLocaleString("de-AT")}) wird storniert. Daten bleiben für Audit erhalten.`
            : ""
        }
        confirmLabel="Stornieren"
        loading={cancelMut.isPending}
        onConfirm={performCancel}
        onCancel={() => setConfirmCancel(null)}
      />
    </div>
  );
}

interface ListProps {
  list: Occupancy[];
  loading: boolean;
  isError: boolean;
  roomNumber: (id: number) => string;
  onCancel: (o: Occupancy) => void;
  cancelPending: boolean;
}

function List({ list, loading, isError, roomNumber, onCancel, cancelPending }: ListProps) {
  if (loading) return <Box>Lade…</Box>;
  if (isError) return <Box error>Fehler beim Laden.</Box>;
  if (list.length === 0) return <Box>Keine Belegungen in diesem Zeitraum.</Box>;
  return (
    <div className="bg-surface border border-border rounded-md overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-surface-alt border-b border-border">
          <tr>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Zimmer</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Anreise</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Abreise</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Personen</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Quelle</th>
            <th className="text-right px-3 py-2 font-medium text-text-secondary"></th>
          </tr>
        </thead>
        <tbody>
          {list.map((o) => (
            <tr key={o.id} className="border-b border-border last:border-b-0 hover:bg-surface-alt">
              <td className="px-3 py-2 font-medium">{roomNumber(o.room_id)}</td>
              <td className="px-3 py-2 text-text-secondary">
                {new Date(o.check_in).toLocaleString("de-AT")}
              </td>
              <td className="px-3 py-2 text-text-secondary">
                {new Date(o.check_out).toLocaleString("de-AT")}
              </td>
              <td className="px-3 py-2 text-text-secondary">{o.guest_count ?? "—"}</td>
              <td className="px-3 py-2 text-text-tertiary">{o.source}</td>
              <td className="px-3 py-2 text-right">
                <Button
                  variant="destructive"
                  icon="cancel"
                  onClick={() => onCancel(o)}
                  disabled={cancelPending}
                >
                  Stornieren
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Box({ children, error }: { children: React.ReactNode; error?: boolean }) {
  return (
    <div
      className={`bg-surface border border-border rounded-md p-4 text-sm ${
        error ? "text-error" : "text-text-secondary"
      }`}
    >
      {children}
    </div>
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
