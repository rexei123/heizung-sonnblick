"use client";

/**
 * Raumtypen-Seite (Sprint 8.9). Master-Detail-Layout:
 *   Liste links, Form rechts. Klick auf Listen-Eintrag laedt Edit-Form.
 *   Button "Neu" oeffnet leere Form.
 */

import { useState } from "react";

import { RoomTypeForm } from "@/components/patterns/room-type-form";
import {
  useCreateRoomType,
  useDeleteRoomType,
  useRoomTypes,
  useUpdateRoomType,
} from "@/lib/api/hooks-room-types";
import type { ApiError, RoomType, RoomTypeCreate, RoomTypeUpdate } from "@/lib/api/types";

type Mode = { kind: "list" } | { kind: "create" } | { kind: "edit"; id: number };

export default function RoomTypesPage() {
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const list = useRoomTypes();
  const createMut = useCreateRoomType();
  const updateMut = useUpdateRoomType(mode.kind === "edit" ? mode.id : 0);
  const deleteMut = useDeleteRoomType();

  const [error, setError] = useState<string | null>(null);

  const handleCreate = async (payload: RoomTypeCreate | RoomTypeUpdate) => {
    setError(null);
    try {
      await createMut.mutateAsync(payload as RoomTypeCreate);
      setMode({ kind: "list" });
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const handleUpdate = async (payload: RoomTypeCreate | RoomTypeUpdate) => {
    setError(null);
    try {
      await updateMut.mutateAsync(payload as RoomTypeUpdate);
      setMode({ kind: "list" });
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Raumtyp wirklich loeschen? Nur moeglich, wenn keine Zimmer verknuepft sind.")) {
      return;
    }
    setError(null);
    try {
      await deleteMut.mutateAsync(id);
      setMode({ kind: "list" });
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const editingItem =
    mode.kind === "edit" ? list.data?.find((rt) => rt.id === mode.id) : undefined;

  return (
    <div className="p-6 max-w-6xl mx-auto">
        <header className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-medium text-text-primary">Raumtypen</h1>
            <p className="text-sm text-text-secondary mt-1">
              Stammdaten fuer alle Zimmertypen mit Default-Sollwerten.
            </p>
          </div>
          {mode.kind === "list" ? (
            <button
              type="button"
              onClick={() => {
                setError(null);
                setMode({ kind: "create" });
              }}
              className="px-4 py-2 bg-primary text-on-primary rounded-md flex items-center gap-2"
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
                add
              </span>
              Neuer Raumtyp
            </button>
          ) : null}
        </header>

        <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6">
          <RoomTypeList
            items={list.data ?? []}
            isLoading={list.isLoading}
            isError={list.isError}
            selectedId={mode.kind === "edit" ? mode.id : null}
            onSelect={(id) => {
              setError(null);
              setMode({ kind: "edit", id });
            }}
          />

          <div className="bg-surface border border-border rounded-md p-5">
            {mode.kind === "list" ? (
              <EmptyState />
            ) : mode.kind === "create" ? (
              <>
                <h2 className="text-lg font-medium text-text-primary mb-4">
                  Neuer Raumtyp
                </h2>
                <RoomTypeForm
                  onSubmit={handleCreate}
                  onCancel={() => setMode({ kind: "list" })}
                  submitting={createMut.isPending}
                  error={error}
                />
              </>
            ) : editingItem ? (
              <>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-lg font-medium text-text-primary">
                    Raumtyp bearbeiten
                  </h2>
                  <button
                    type="button"
                    onClick={() => handleDelete(editingItem.id)}
                    className="text-sm text-domain-heating-off hover:underline"
                    disabled={deleteMut.isPending}
                  >
                    {deleteMut.isPending ? "Loesche…" : "Loeschen"}
                  </button>
                </div>
                <RoomTypeForm
                  initial={editingItem}
                  onSubmit={handleUpdate}
                  onCancel={() => setMode({ kind: "list" })}
                  submitting={updateMut.isPending}
                  error={error}
                />
              </>
            ) : (
              <p className="text-sm text-text-secondary">Lade…</p>
            )}
          </div>
        </div>
      </div>
  );
}

interface ListProps {
  items: RoomType[];
  isLoading: boolean;
  isError: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

function RoomTypeList({ items, isLoading, isError, selectedId, onSelect }: ListProps) {
  if (isLoading) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-text-secondary">
        Lade…
      </div>
    );
  }
  if (isError) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-domain-heating-off">
        Fehler beim Laden.
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-text-secondary">
        Noch keine Raumtypen angelegt.
      </div>
    );
  }
  return (
    <ul className="bg-surface border border-border rounded-md overflow-hidden">
      {items.map((rt) => (
        <li key={rt.id}>
          <button
            type="button"
            onClick={() => onSelect(rt.id)}
            className={`w-full text-left px-3 py-2.5 border-b border-border last:border-b-0 hover:bg-surface-alt transition-colors ${
              selectedId === rt.id ? "bg-surface-alt" : ""
            }`}
          >
            <div className="font-medium text-text-primary text-sm">{rt.name}</div>
            <div className="text-xs text-text-tertiary mt-0.5">
              Belegt {rt.default_t_occupied}° · Frei {rt.default_t_vacant}°
              {!rt.is_bookable ? " · nicht buchbar" : ""}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function EmptyState() {
  return (
    <div className="text-center py-12">
      <span
        className="material-symbols-outlined text-text-tertiary"
        style={{ fontSize: 48 }}
      >
        category
      </span>
      <p className="mt-2 text-sm text-text-secondary">
        Klicken Sie auf einen Raumtyp links zum Bearbeiten oder auf
        &quot;Neuer Raumtyp&quot;.
      </p>
    </div>
  );
}

function toMessage(err: unknown): string {
  const e = err as ApiError | Error;
  if (typeof e === "object" && e !== null && "detail" in e) {
    const detail = (e as ApiError).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
